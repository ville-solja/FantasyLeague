"""
Tests for plan-issue-123-password-reset-token-flow.md (resolves GitHub issue #123).

Covers the plan's first two user stories (backend-testable). The plan's third story
("Reset Password UI") is frontend-only -- modal auto-open on `?reset_token=`, URL-param
stripping via history.replaceState -- and has no backend test surface, so it is
intentionally not stubbed here.

  Story 1: Request a Password Reset Without Touching the Real Password
  Story 2: Complete a Password Reset with a Valid Token

Background: POST /forgot-password currently generates a random temp password and
IMMEDIATELY overwrites the account's real password_hash before emailing it -- knowing a
username alone is enough to mutate real credentials. This plan replaces that with a
single-use, expiring PasswordResetToken (new table: token PK, user_id, expires_at --
same shape/precedent as TwitchLinkCode in backend/models.py, whose "invalidate prior
unexpired code for this user" pattern in twitch.py's generate_link_code() --
`db.query(TwitchLinkCode).filter_by(user_id=user_id).delete()` -- this plan's token
creation is meant to mirror). /forgot-password only ever creates/replaces that token and
emails it; a new POST /reset-password endpoint is the only thing that actually changes
user.password_hash now.

Acceptance criteria under test (from the plan):

  Story 1 -- POST /forgot-password:
  1. Never sets user.password_hash, must_change_password, or temp_password_expires_at.
  2. Creates exactly one PasswordResetToken for the account per request.
  3. A second request for the same user invalidates (removes) the prior unused token --
     only one live token per user at a time.
  4. Token TTL defaults to 1 hour when PASSWORD_RESET_TOKEN_TTL_HOURS is unset.
  5. Token TTL is configurable via PASSWORD_RESET_TOKEN_TTL_HOURS.
  6. Email includes a clickable link (`{APP_BASE_URL}/?reset_token={token}`) when
     APP_BASE_URL is configured.
  7. Email omits the link entirely (manual-code-only) when APP_BASE_URL is unset.
  8. Email always includes the raw token as a manual-entry fallback, regardless of
     APP_BASE_URL.
  9. Email wording states the current password remains valid / nothing changes until the
     reset is completed (the inverse of the old "already... replaced" wording).
  10. The endpoint's response contract is otherwise unchanged: always
      {"status": "ok"} for an existing user (issues #121/#122's rate limit/cooldown are
      NOT re-tested here -- see test_issue_121_rate_limiting.py /
      test_issue_122_forgot_password_cooldown.py for those; this plan does not touch
      either mechanism, only what happens once a request is *not* suppressed by them).

  Story 2 -- POST /reset-password:
  11. new_password is subject to Field(min_length=6, max_length=128), same as elsewhere
      (e.g. RegisterBody.password) -- rejects too-short input.
  12. ... and rejects too-long input.
  13. A valid, unexpired token sets user.password_hash to the new password.
  14. A valid, unexpired token clears legacy must_change_password/temp_password_expires_at
      state on the account (cleanup, matching what PUT /profile/password already does --
      see backend/routers/profile.py's change_password()).
  15. A valid, unexpired token is deleted from the DB after use (single-use).
  16. Reusing an already-consumed token on a second call is rejected (proves single-use is
      enforced end-to-end, not just "the row happens to be gone").
  17. A valid, unexpired token reset returns {"status": "ok"}.
  18. An unknown/invalid token returns 400 and makes no change to any account.
  19. An expired token returns 400 and makes no change to any account (including not
      deleting/consuming it as if it were valid).
  20. A completed reset is recorded in the audit log as "password_reset_completed"
      (see backend/deps.py's _audit() and backend/models.py's AuditLog).

STATUS: stub -- all 20 tests below raise pytest.fail("not yet implemented"). No
PasswordResetToken model, no POST /reset-password endpoint, and no changes to
forgot_password() exist yet; this file defines the test contract the developer must
satisfy. Do not add `from models import PasswordResetToken` at module level until that
model exists -- it would turn every test in this file into a collection error instead of
a clean, reportable failure.

Fixture/style notes (see backend/tests/test_issue_122_forgot_password_cooldown.py, the
most recent and directly relevant precedent for testing this exact endpoint):

- `_make_app` below reloads `rate_limit` then `routers.auth` on every call, exactly like
  test_issue_122's helper of the same name -- this remains necessary so that
  RATE_LIMIT_FORGOT_PASSWORD / FORGOT_PASSWORD_COOLDOWN_SECONDS (existing module-level
  constants read at import time) don't leak state or stale env-var values between tests.
  NOTE: per the plan's own Step 2/Step 3 sample code, PASSWORD_RESET_TOKEN_TTL_HOURS and
  APP_BASE_URL are read inline via os.getenv(...) *inside* forgot_password()/
  reset_password() at request time (same pattern as the existing inline
  `app_name = os.getenv("APP_NAME", ...)` already in forgot_password()), not hoisted to
  module-level constants -- so, unlike RATE_LIMIT_FORGOT_PASSWORD, they would work with a
  bare monkeypatch.setenv() and no reload at all. The reload-before-each-test pattern
  below is still used for consistency and because it is a safe superset (it works
  whether the eventual implementation reads them inline or hoists them to module
  constants); if the developer does hoist them, no test here needs to change.
- rate_limit.limiter is disabled by default (`client` fixture) so these tests are not
  incidentally affected by issue #121's per-IP limit; none of the scenarios here need it
  enabled, unlike test_issue_122's AC4 tests.
- `_do_forgot_password` mocks `routers.auth.send_email` and captures its call args (not
  just a call count, unlike test_issue_122's helper) so email-content assertions (link
  present/absent, raw token present, wording) can inspect `subject`/`body` directly
  instead of re-deriving the token out-of-band.
- Distinct usernames are used per test (never re-using "alice" across tests that call
  /forgot-password more than once within the same test file run) specifically so
  issue #122's per-username cooldown -- which is correct, expected behavior and out of
  scope to disable here -- never suppresses a second /forgot-password call this file
  intentionally makes to test token invalidation (AC 3). Where a test needs two
  back-to-back /forgot-password calls for the *same* username in the same test (only
  AC 3 needs this), FORGOT_PASSWORD_COOLDOWN_SECONDS is monkeypatched to "0" before
  building the app so the second call is not itself suppressed by the cooldown --
  that suppression is issue #122's own tested behavior, not something this file
  should re-verify or accidentally trip over.
- Story 2 tests seed a PasswordResetToken row directly via the `db_session` fixture
  (bypassing /forgot-password entirely) once the model exists, mirroring how
  test_issue_122 seeds Users directly via `_create_user` rather than registering
  through the API. No precedent file yet exists for POST /reset-password itself since
  the endpoint doesn't exist; `_do_reset_password` below is new scaffolding for it,
  shaped like `_do_forgot_password`.

Run with: cd backend && python -m pytest tests/test_issue_123_password_reset_token_flow.py -v
"""

import importlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from database import Base, get_db
from models import User, AuditLog, PasswordResetToken
from auth import hash_password, verify_password
import rate_limit
import routers.auth as auth_router_module


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)  # will pick up PasswordResetToken automatically
    # once it exists in models.py -- no fixture change needed when the model lands.
    return engine


def _make_app(engine, disable_rate_limit=True):
    """Build a minimal FastAPI test app wrapping only routers.auth, backed by
    `engine` -- mirrors test_issue_122_forgot_password_cooldown.py's `_make_app`.

    Reloads `rate_limit` then `routers.auth` (in that order) so any monkeypatched env
    var set before this call is picked up, and so each call starts from clean,
    empty in-memory state for the rate limiter's hit counts and the cooldown tracker
    (_last_forgot_password_request), instead of accumulating state left over from a
    previous test.
    """
    importlib.reload(rate_limit)
    importlib.reload(auth_router_module)
    if disable_rate_limit:
        rate_limit.limiter.enabled = False

    Session = sessionmaker(bind=engine)

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-123")
    app.include_router(auth_router_module.router)
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.fixture()
def engine():
    return _make_engine()


@pytest.fixture()
def app(engine):
    return _make_app(engine)


@pytest.fixture()
def client(app):
    """Default client: rate_limit.limiter disabled, default
    PASSWORD_RESET_TOKEN_TTL_HOURS (1) / FORGOT_PASSWORD_COOLDOWN_SECONDS (300)."""
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def db_session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _create_user(db, username="alice", email="alice@example.com",
                 password="secret123", tokens=5):
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        tokens=tokens,
        created_at=int(time.time()),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _do_forgot_password(client, username):
    """POST /forgot-password against `client` with routers.auth.send_email mocked out.
    Returns (response, calls) where `calls` is a list of
    {"to_address":..., "subject":..., "body":...} dicts, one per actual send attempt --
    lets email-content assertions inspect the link/token/wording directly."""
    calls = []

    def fake_send_email(to_address, subject, body):
        calls.append({"to_address": to_address, "subject": subject, "body": body})
        return True

    with patch("routers.auth.send_email", side_effect=fake_send_email):
        resp = client.post("/forgot-password", json={"username": username})
    return resp, calls


def _do_reset_password(client, token, new_password):
    """POST /reset-password against `client`. New scaffolding (no existing precedent
    file) -- shaped like _do_forgot_password above."""
    return client.post("/reset-password", json={"token": token, "new_password": new_password})


# ---------------------------------------------------------------------------
# Story 1: Request a Password Reset Without Touching the Real Password
# ---------------------------------------------------------------------------

def test_forgot_password_leaves_real_credentials_untouched(client, db_session):
    """AC: POST /forgot-password never sets user.password_hash, must_change_password,
    or temp_password_expires_at -- the account's real credentials are completely
    unaffected by the request itself (this is the core fix for issue #123)."""
    user = _create_user(db_session)
    original_hash = user.password_hash

    resp, calls = _do_forgot_password(client, "alice")

    assert resp.status_code == 200
    assert len(calls) == 1
    db_session.refresh(user)
    assert user.password_hash == original_hash
    assert user.must_change_password in (False, None)
    assert user.temp_password_expires_at is None


def test_forgot_password_creates_exactly_one_password_reset_token(client, db_session):
    """AC: a single-use PasswordResetToken row is created for the account -- exactly
    one, with user_id pointing at the requesting account."""
    user = _create_user(db_session)

    resp, _calls = _do_forgot_password(client, "alice")
    assert resp.status_code == 200

    tokens = db_session.query(PasswordResetToken).filter_by(user_id=user.id).all()
    assert len(tokens) == 1
    assert tokens[0].user_id == user.id


def test_forgot_password_repeat_request_invalidates_prior_token(client, db_session, monkeypatch):
    """AC: a second /forgot-password request for the same user invalidates (removes)
    any prior unused token for that user -- only one live PasswordResetToken per user
    at a time, mirroring TwitchLinkCode's invalidate-on-regenerate precedent in
    twitch.py's generate_link_code(). FORGOT_PASSWORD_COOLDOWN_SECONDS is set to "0"
    here so the second call isn't itself suppressed by issue #122's unrelated
    per-username cooldown."""
    user = _create_user(db_session)

    resp1, calls1 = _do_forgot_password(client, "alice")
    assert resp1.status_code == 200
    assert len(calls1) == 1
    first_token = db_session.query(PasswordResetToken).filter_by(user_id=user.id).first()
    assert first_token is not None
    first_token_value = first_token.token

    # Rebuild the app with the cooldown disabled (env read at module-reload time --
    # see _make_app's docstring) so the second call is not itself suppressed by
    # issue #122's cooldown, and issue only a fresh token invalidation.
    monkeypatch.setenv("FORGOT_PASSWORD_COOLDOWN_SECONDS", "0")
    engine = db_session.get_bind()
    app2 = _make_app(engine)
    client2 = TestClient(app2, raise_server_exceptions=True)

    resp2, calls2 = _do_forgot_password(client2, "alice")
    assert resp2.status_code == 200
    assert len(calls2) == 1

    tokens = db_session.query(PasswordResetToken).filter_by(user_id=user.id).all()
    assert len(tokens) == 1
    assert tokens[0].token != first_token_value


def test_forgot_password_token_default_ttl_is_one_hour(client, db_session, monkeypatch):
    """AC: with PASSWORD_RESET_TOKEN_TTL_HOURS unset, the created token's expires_at
    is ~1 hour (3600s) from creation time."""
    monkeypatch.delenv("PASSWORD_RESET_TOKEN_TTL_HOURS", raising=False)
    user = _create_user(db_session)

    before = int(time.time())
    resp, _calls = _do_forgot_password(client, "alice")
    after = int(time.time())

    assert resp.status_code == 200
    token = db_session.query(PasswordResetToken).filter_by(user_id=user.id).first()
    assert token is not None
    assert before + 3600 <= token.expires_at <= after + 3600


def test_forgot_password_token_ttl_configurable_via_env_var(monkeypatch, engine):
    """AC: PASSWORD_RESET_TOKEN_TTL_HOURS overrides the token's validity window --
    e.g. setting it to "2" produces a token whose expires_at is ~2 hours out."""
    monkeypatch.setenv("PASSWORD_RESET_TOKEN_TTL_HOURS", "2")
    app = _make_app(engine)
    client = TestClient(app, raise_server_exceptions=True)

    Session = sessionmaker(bind=engine)
    db = Session()
    user = _create_user(db)

    before = int(time.time())
    resp, _calls = _do_forgot_password(client, "alice")
    after = int(time.time())

    assert resp.status_code == 200
    db.refresh(user)
    token = db.query(PasswordResetToken).filter_by(user_id=user.id).first()
    assert token is not None
    assert before + 2 * 3600 <= token.expires_at <= after + 2 * 3600
    db.close()


def test_forgot_password_email_includes_link_when_app_base_url_set(monkeypatch, engine):
    """AC: with APP_BASE_URL configured, the emailed body contains a clickable link of
    the form "{APP_BASE_URL}/?reset_token={token}"."""
    monkeypatch.setenv("APP_BASE_URL", "https://kana.example.com")
    app = _make_app(engine)
    client = TestClient(app, raise_server_exceptions=True)

    Session = sessionmaker(bind=engine)
    db = Session()
    user = _create_user(db)

    resp, calls = _do_forgot_password(client, "alice")
    assert resp.status_code == 200
    assert len(calls) == 1

    token = db.query(PasswordResetToken).filter_by(user_id=user.id).first()
    assert token is not None
    expected_link = f"https://kana.example.com/?reset_token={token.token}"
    assert expected_link in calls[0]["body"]
    db.close()


def test_forgot_password_email_omits_link_when_app_base_url_unset(client, db_session, monkeypatch):
    """AC: with APP_BASE_URL unset, the emailed body contains no reset link -- only
    the manual-entry raw token fallback."""
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    _create_user(db_session)

    resp, calls = _do_forgot_password(client, "alice")
    assert resp.status_code == 200
    assert len(calls) == 1
    assert "http://" not in calls[0]["body"]
    assert "https://" not in calls[0]["body"]


def test_forgot_password_email_always_includes_raw_token(client, db_session):
    """AC: the raw token is always present in the email body as a manual-entry
    fallback, regardless of whether APP_BASE_URL is set."""
    user = _create_user(db_session)

    resp, calls = _do_forgot_password(client, "alice")
    assert resp.status_code == 200
    assert len(calls) == 1

    token = db_session.query(PasswordResetToken).filter_by(user_id=user.id).first()
    assert token is not None
    assert token.token in calls[0]["body"]


def test_forgot_password_email_wording_states_password_still_valid(client, db_session):
    """AC: the email wording reflects the new reality -- states the current password
    remains valid and nothing changes until the reset is completed (the inverse of the
    old wording, which said the previous password had "already... replaced")."""
    _create_user(db_session)

    resp, calls = _do_forgot_password(client, "alice")
    assert resp.status_code == 200
    assert len(calls) == 1
    body = calls[0]["body"].lower()

    assert "remains valid" in body or "has not been changed" in body
    assert "already" not in body  # old wording said the password was "already...replaced"
    assert "replaced" not in body


def test_forgot_password_response_contract_unchanged_status_ok(client, db_session):
    """AC: the endpoint's existing response contract is otherwise unchanged -- an
    existing user still gets exactly {"status": "ok"} with HTTP 200 once the token
    flow replaces the old temp-password flow. (Enumeration-safety and the #121/#122
    rate-limit/cooldown mechanics themselves are NOT re-tested here -- see
    test_issue_121_rate_limiting.py / test_issue_122_forgot_password_cooldown.py.)"""
    _create_user(db_session)

    resp, calls = _do_forgot_password(client, "alice")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Story 2: Complete a Password Reset with a Valid Token
# ---------------------------------------------------------------------------

def test_reset_password_rejects_new_password_below_min_length(client, db_session):
    """AC: new_password is subject to Field(min_length=6, max_length=128) -- a
    5-character new_password is rejected (422) even against an otherwise-valid
    token."""
    user = _create_user(db_session)
    db_session.add(PasswordResetToken(token="tok-min-length", user_id=user.id,
                                      expires_at=int(time.time()) + 3600))
    db_session.commit()

    resp = _do_reset_password(client, "tok-min-length", "abcde")
    assert resp.status_code == 422

    # No side effects: token still present, password untouched.
    db_session.refresh(user)
    assert db_session.get(PasswordResetToken, "tok-min-length") is not None
    assert verify_password("secret123", user.password_hash)


def test_reset_password_rejects_new_password_above_max_length(client, db_session):
    """AC: a 129-character new_password is rejected (422) even against an
    otherwise-valid token."""
    user = _create_user(db_session)
    db_session.add(PasswordResetToken(token="tok-max-length", user_id=user.id,
                                      expires_at=int(time.time()) + 3600))
    db_session.commit()

    resp = _do_reset_password(client, "tok-max-length", "a" * 129)
    assert resp.status_code == 422

    db_session.refresh(user)
    assert db_session.get(PasswordResetToken, "tok-max-length") is not None
    assert verify_password("secret123", user.password_hash)


def test_reset_password_valid_token_changes_password_hash(client, db_session):
    """AC: POST /reset-password with a valid, unexpired token sets
    user.password_hash to a hash of the new password (verifiable via
    auth.verify_password)."""
    user = _create_user(db_session)
    db_session.add(PasswordResetToken(token="tok-valid-1", user_id=user.id,
                                      expires_at=int(time.time()) + 3600))
    db_session.commit()

    resp = _do_reset_password(client, "tok-valid-1", "brand-new-password")
    assert resp.status_code == 200

    db_session.refresh(user)
    assert verify_password("brand-new-password", user.password_hash)
    assert not verify_password("secret123", user.password_hash)


def test_reset_password_valid_token_clears_legacy_temp_password_state(client, db_session):
    """AC: a valid reset clears any legacy must_change_password/
    temp_password_expires_at state on the account -- cleanup matching what
    PUT /profile/password already does (backend/routers/profile.py's
    change_password()). Seed the user with must_change_password=True and a non-null
    temp_password_expires_at (simulating a pre-fix outstanding temp password) to
    prove the reset actually clears it rather than leaving it untouched."""
    user = _create_user(db_session)
    user.must_change_password = True
    user.temp_password_expires_at = int(time.time()) + 3600
    db_session.commit()

    db_session.add(PasswordResetToken(token="tok-legacy-cleanup", user_id=user.id,
                                      expires_at=int(time.time()) + 3600))
    db_session.commit()

    resp = _do_reset_password(client, "tok-legacy-cleanup", "brand-new-password")
    assert resp.status_code == 200

    db_session.refresh(user)
    assert user.must_change_password is False
    assert user.temp_password_expires_at is None


def test_reset_password_valid_token_deletes_token_row(client, db_session):
    """AC: after a successful reset, the PasswordResetToken row is deleted from the
    DB (single-use)."""
    user = _create_user(db_session)
    db_session.add(PasswordResetToken(token="tok-delete-me", user_id=user.id,
                                      expires_at=int(time.time()) + 3600))
    db_session.commit()

    resp = _do_reset_password(client, "tok-delete-me", "brand-new-password")
    assert resp.status_code == 200

    assert db_session.get(PasswordResetToken, "tok-delete-me") is None


def test_reset_password_token_cannot_be_reused_after_reset(client, db_session):
    """AC: submitting the same token a second time (after it was already consumed by
    a first successful reset) is rejected with 400 and does not change the password
    again -- proves single-use is enforced end-to-end, not just that the row happens
    to be gone."""
    user = _create_user(db_session)
    db_session.add(PasswordResetToken(token="tok-reuse", user_id=user.id,
                                      expires_at=int(time.time()) + 3600))
    db_session.commit()

    resp1 = _do_reset_password(client, "tok-reuse", "first-new-password")
    assert resp1.status_code == 200
    db_session.refresh(user)
    assert verify_password("first-new-password", user.password_hash)

    resp2 = _do_reset_password(client, "tok-reuse", "second-new-password")
    assert resp2.status_code == 400

    db_session.refresh(user)
    assert verify_password("first-new-password", user.password_hash)
    assert not verify_password("second-new-password", user.password_hash)


def test_reset_password_valid_token_returns_status_ok(client, db_session):
    """AC: a successful reset returns HTTP 200 with exactly {"status": "ok"}."""
    user = _create_user(db_session)
    db_session.add(PasswordResetToken(token="tok-status-ok", user_id=user.id,
                                      expires_at=int(time.time()) + 3600))
    db_session.commit()

    resp = _do_reset_password(client, "tok-status-ok", "brand-new-password")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_reset_password_invalid_token_returns_400_no_side_effects(client, db_session):
    """AC: an unknown/nonexistent token returns 400 with a clear error and makes no
    change to any account (password_hash, must_change_password, etc. all untouched)."""
    user = _create_user(db_session)
    original_hash = user.password_hash

    resp = _do_reset_password(client, "this-token-does-not-exist", "brand-new-password")
    assert resp.status_code == 400
    assert resp.json().get("detail")

    db_session.refresh(user)
    assert user.password_hash == original_hash
    assert user.must_change_password in (False, None)
    assert user.temp_password_expires_at is None


def test_reset_password_expired_token_returns_400_no_side_effects(client, db_session):
    """AC: an expired token (expires_at in the past) returns 400 and makes no change
    to any account -- it must be rejected as invalid, not silently accepted or
    partially consumed."""
    user = _create_user(db_session)
    original_hash = user.password_hash
    db_session.add(PasswordResetToken(token="tok-expired", user_id=user.id,
                                      expires_at=int(time.time()) - 100))
    db_session.commit()

    resp = _do_reset_password(client, "tok-expired", "brand-new-password")
    assert resp.status_code == 400

    db_session.refresh(user)
    assert user.password_hash == original_hash
    assert user.must_change_password in (False, None)
    assert user.temp_password_expires_at is None


def test_reset_password_records_audit_log_entry(client, db_session):
    """AC: a successful reset is recorded in the audit log with
    action="password_reset_completed" (see backend/deps.py's _audit() and
    backend/models.py's AuditLog), attributed to the resetting user."""
    user = _create_user(db_session)
    db_session.add(PasswordResetToken(token="tok-audit", user_id=user.id,
                                      expires_at=int(time.time()) + 3600))
    db_session.commit()

    resp = _do_reset_password(client, "tok-audit", "brand-new-password")
    assert resp.status_code == 200

    entry = (
        db_session.query(AuditLog)
        .filter_by(action="password_reset_completed", actor_id=user.id)
        .first()
    )
    assert entry is not None
    assert entry.actor_username == user.username
