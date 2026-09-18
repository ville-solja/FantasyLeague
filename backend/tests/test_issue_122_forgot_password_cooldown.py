"""
Tests for plan-issue-122-forgot-password-cooldown.md (resolves GitHub issue #122).

Covers the plan's single user story:

  Story: Per-Account Cooldown on Forgot Password

Issue #121 already added a per-IP rate limit to POST /forgot-password
(RATE_LIMIT_FORGOT_PASSWORD, default 3/minute, via @limiter.limit(...) on the
route). This plan adds an independent, per-*username* cooldown
(FORGOT_PASSWORD_COOLDOWN_SECONDS, default 300) so an attacker spread across
multiple source IPs -- or simply patient -- can't repeatedly spam a single
account's inbox once the per-IP limit resets. It mirrors the existing
_is_locked_out/_record_failed_login pattern already used for /login's
per-username lockout (backend/routers/auth.py), via two new functions,
_forgot_password_in_cooldown(username) / _record_forgot_password_request(username),
backed by a module-level `_last_forgot_password_request: dict[str, float]`,
wired into forgot_password() right after the user lookup and before any
password/email work. The suppressed path must return the exact same
{"status": "ok"} response (via the same dummy-hash timing-equalization call)
as the existing nonexistent-username fast-exit, so the cooldown introduces no
new username-enumeration side channel.

Acceptance criteria (from the plan):
  1. A second request for the same username within
     FORGOT_PASSWORD_COOLDOWN_SECONDS does not send another email or issue
     another temp password, even from a different source IP.
  2. The suppressed request still returns {"status": "ok"} -- identical to
     both the "username doesn't exist" and "email successfully sent"
     responses.
  3. The cooldown is keyed by the submitted username string, only populated
     when the username resolves to a real account (the nonexistent-username
     fast-exit path is unchanged and never populates it).
  4. The cooldown is configurable via FORGOT_PASSWORD_COOLDOWN_SECONDS and is
     independent of, and stacks with, the existing per-IP
     RATE_LIMIT_FORGOT_PASSWORD -- either alone is sufficient to suppress a
     request, neither depends on the other.
  5. The cooldown expires on its own after the window -- no permanent
     lockout.

Fixture/style notes (see backend/tests/test_issue_121_rate_limiting.py and
test_issue_77_temp_password_expiry.py, the two directly relevant sibling
files -- the former for the per-IP-limit-vs-cooldown interaction and varying
-source-IP pattern, the latter for this endpoint's existing
enumeration-safety/TTL test style and its `send_email`-mocking helper):

- FORGOT_PASSWORD_COOLDOWN_SECONDS is expected to be read as a module-level
  constant in routers.auth at import time, exactly like RATE_LIMIT_FORGOT_PASSWORD
  already is -- per test_issue_121's module docstring, a monkeypatch.setenv(...)
  override only takes effect if routers.auth (and rate_limit, which it
  imports) is reloaded *after* the env var is set. `_make_app` below does
  that reload on every call.
- rate_limit.limiter is a shared, process-wide singleton with in-memory
  counters. Most tests here are about the per-username cooldown, not the
  per-IP limit, so the default `client` fixture disables it
  (rate_limit.limiter.enabled = False, matching test_issue_77's own
  rationale). The `client_with_rate_limit` fixture leaves it enabled and
  freshly reloaded (zero counts) for the handful of tests that specifically
  exercise the interaction between the two independent limits (acceptance
  criterion 4).
- Varying "source IP" uses multiple TestClient instances pinned to distinct
  `client=(ip, port)` scope tuples, all wrapping the same already-built app
  -- TestClient's ASGI transport reports one fixed client host per instance,
  and slowapi's default key_func (get_remote_address) keys off
  request.client.host (does not honor X-Forwarded-For).
- No precedent exists anywhere in backend/tests/ for mocking time.time() /
  freezegun-style time travel. Per this plan's own suggestion and this
  repo's established alternative (TTL-style tests that just do real integer
  arithmetic on timestamps, e.g. test_issue_77_temp_password_expiry.py), the
  "cooldown expires" acceptance criterion is tested with a short
  FORGOT_PASSWORD_COOLDOWN_SECONDS override plus a real (short) time.sleep(),
  not a time.time() mock.

STATUS: implemented -- all 11 stubs have real assertions against the
_forgot_password_in_cooldown()/_record_forgot_password_request() wiring in
backend/routers/auth.py.

UPDATED (issue #123, password-reset-token-flow redesign): forgot_password() no
longer mutates user.password_hash at all -- see
plan-issue-123-password-reset-token-flow.md and
tests/test_issue_123_password_reset_token_flow.py. Most tests below use
password_hash equality across a *suppressed* request only as a "nothing
happened" proxy, which is still trivially true post-redesign (password_hash was
never touched either way) and needed no change. One test,
test_forgot_password_cooldown_expires_after_window_allows_new_email, asserted
password_hash *inequality* across two *non-suppressed* requests as proof a new
temp password was issued -- that assertion would now be permanently false, so
it was rewritten to check the PasswordResetToken row instead (still proving
"not suppressed, a new artifact was issued", just the new artifact).

Run with: cd backend && python -m pytest tests/test_issue_122_forgot_password_cooldown.py -v
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
from models import User, PasswordResetToken
from auth import hash_password
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
    Base.metadata.create_all(engine)
    return engine


def _make_app(engine, disable_rate_limit=True):
    """Build a minimal FastAPI test app wrapping only routers.auth, backed by
    `engine` -- mirrors test_issue_77_temp_password_expiry.py's `_make_app`.

    Reloads `rate_limit` then `routers.auth` (in that order, matching
    test_issue_121_rate_limiting.py's `_setup_test_app`) so that:
      (a) any FORGOT_PASSWORD_COOLDOWN_SECONDS / RATE_LIMIT_FORGOT_PASSWORD
          env var monkeypatched *before* this call is actually picked up
          (both are read as module-level constants at import time), and
      (b) each call starts from clean, empty in-memory state for both the
          rate limiter's hit counts and the cooldown tracker
          (_last_forgot_password_request), instead of accumulating state left
          over from a previous test.

    disable_rate_limit=True (the default) turns off rate_limit.limiter
    entirely, isolating the per-username cooldown under test from the
    separate per-IP limit added in issue #121. Pass disable_rate_limit=False
    for tests that specifically exercise the interaction between the two
    (acceptance criterion 4 -- independence/stacking).
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
    FORGOT_PASSWORD_COOLDOWN_SECONDS (300) -- use for tests about the
    per-username cooldown alone."""
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def client_with_rate_limit(engine):
    """Like `client`, but leaves rate_limit.limiter enabled and freshly
    reloaded -- for tests exercising the per-IP RATE_LIMIT_FORGOT_PASSWORD
    limit (issue #121) alongside or instead of the cooldown."""
    app = _make_app(engine, disable_rate_limit=False)
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


def _do_forgot_password(client, username, ip=None):
    """POST /forgot-password against `client` (or a same-app TestClient
    pinned to `ip`, mirroring test_issue_121_rate_limiting.py's per-simulated
    -source-IP pattern) with routers.auth.send_email mocked out. Returns
    (response, send_email_call_count) so callers can assert on both the HTTP
    response and whether an email was actually attempted."""
    calls = {"count": 0}

    def fake_send_email(to_address, subject, body):
        calls["count"] += 1
        return True

    target = client if ip is None else TestClient(
        client.app, raise_server_exceptions=True, client=(ip, 12345)
    )
    with patch("routers.auth.send_email", side_effect=fake_send_email):
        resp = target.post("/forgot-password", json={"username": username})
    return resp, calls["count"]


# ---------------------------------------------------------------------------
# Story: Per-Account Cooldown on Forgot Password
# ---------------------------------------------------------------------------

# --- AC 1: a second request for the same username within the cooldown
#     window does not send another email or issue another temp password,
#     even from a different source IP. -------------------------------------

def test_forgot_password_second_request_same_username_in_cooldown_suppresses_email(client, db_session):
    """AC: a second /forgot-password request for the same username sent
    shortly after the first, within FORGOT_PASSWORD_COOLDOWN_SECONDS, does
    not call send_email a second time and does not overwrite the user's
    password_hash a second time."""
    user = _create_user(db_session)

    resp1, count1 = _do_forgot_password(client, "alice")
    assert resp1.status_code == 200
    assert count1 == 1
    db_session.refresh(user)
    hash_after_first = user.password_hash

    resp2, count2 = _do_forgot_password(client, "alice")
    assert resp2.status_code == 200
    assert count2 == 0

    db_session.refresh(user)
    assert user.password_hash == hash_after_first


def test_forgot_password_cooldown_suppresses_request_from_different_source_ip(client, db_session):
    """AC: the per-username cooldown suppresses a second request even when it
    arrives from a different source IP than the first -- the cooldown is
    keyed by username, independent of source IP, not merely of TestClient
    connection reuse."""
    user = _create_user(db_session)

    resp1, count1 = _do_forgot_password(client, "alice", ip="10.0.0.1")
    assert resp1.status_code == 200
    assert count1 == 1
    db_session.refresh(user)
    hash_after_first = user.password_hash

    resp2, count2 = _do_forgot_password(client, "alice", ip="10.0.0.2")
    assert resp2.status_code == 200
    assert count2 == 0

    db_session.refresh(user)
    assert user.password_hash == hash_after_first


# --- AC 2: the suppressed request still returns {"status": "ok"},
#     identical to both the nonexistent-username and successful-send
#     responses. -------------------------------------------------------------

def test_forgot_password_cooldown_suppressed_response_is_status_ok(client, db_session):
    """AC: a cooldown-suppressed request returns HTTP 200 with exactly
    {"status": "ok"} -- not a 429, not an error, and with no extra fields
    hinting at cooldown state."""
    _create_user(db_session)

    resp1, _ = _do_forgot_password(client, "alice")
    assert resp1.status_code == 200

    resp2, count2 = _do_forgot_password(client, "alice")
    assert count2 == 0
    assert resp2.status_code == 200
    assert resp2.json() == {"status": "ok"}


def test_forgot_password_cooldown_response_matches_nonexistent_username_response(client, db_session):
    """AC: a cooldown-suppressed response body is identical
    ({"status": "ok"}, same status code) to the response for a nonexistent
    username, so the new cooldown path introduces no distinguishing signal
    about account existence or cooldown state."""
    _create_user(db_session)

    resp1, _ = _do_forgot_password(client, "alice")
    assert resp1.status_code == 200

    cooldown_resp, cooldown_count = _do_forgot_password(client, "alice")
    assert cooldown_count == 0

    nonexistent_resp, nonexistent_count = _do_forgot_password(client, "definitely-does-not-exist")
    assert nonexistent_count == 0

    assert cooldown_resp.status_code == nonexistent_resp.status_code == 200
    assert cooldown_resp.json() == nonexistent_resp.json() == {"status": "ok"}


# --- AC 3: the cooldown is keyed by the submitted username string, only
#     populated when the username resolves to a real account -- the
#     nonexistent-username fast-exit path is unchanged. ---------------------

def test_forgot_password_nonexistent_username_does_not_populate_cooldown_tracker(client):
    """AC: repeated /forgot-password requests for a username that does not
    resolve to a real account never populate
    routers.auth._last_forgot_password_request and are never suppressed by
    the cooldown (the existing fast-exit path is untouched by this plan)."""
    resp1, count1 = _do_forgot_password(client, "ghost-user")
    assert resp1.status_code == 200
    assert count1 == 0
    assert "ghost-user" not in auth_router_module._last_forgot_password_request

    resp2, count2 = _do_forgot_password(client, "ghost-user")
    assert resp2.status_code == 200
    assert count2 == 0
    assert "ghost-user" not in auth_router_module._last_forgot_password_request


def test_forgot_password_cooldown_is_scoped_per_username_not_global(client, db_session):
    """AC: the cooldown is keyed per-username -- a request for account B
    while account A is in its cooldown window is unaffected by A's cooldown
    and proceeds normally (sends an email, issues a temp password)."""
    user_a = _create_user(db_session, username="alice", email="alice@example.com")
    user_b = _create_user(db_session, username="bob", email="bob@example.com")

    resp_a1, count_a1 = _do_forgot_password(client, "alice")
    assert resp_a1.status_code == 200
    assert count_a1 == 1

    # alice is now in cooldown -- bob is unaffected.
    resp_b1, count_b1 = _do_forgot_password(client, "bob")
    assert resp_b1.status_code == 200
    assert count_b1 == 1
    db_session.refresh(user_b)
    hash_after_bob_first = user_b.password_hash

    # alice's second request is suppressed.
    resp_a2, count_a2 = _do_forgot_password(client, "alice")
    assert resp_a2.status_code == 200
    assert count_a2 == 0

    # bob's second request is also suppressed by his own cooldown now.
    resp_b2, count_b2 = _do_forgot_password(client, "bob")
    assert resp_b2.status_code == 200
    assert count_b2 == 0
    db_session.refresh(user_b)
    assert user_b.password_hash == hash_after_bob_first


# --- AC 4: the cooldown is configurable via FORGOT_PASSWORD_COOLDOWN_SECONDS
#     and is independent of, and stacks with, the existing per-IP
#     RATE_LIMIT_FORGOT_PASSWORD -- either alone suppresses a request. ------

def test_forgot_password_cooldown_window_configurable_via_env_var(monkeypatch, engine):
    """AC: FORGOT_PASSWORD_COOLDOWN_SECONDS controls the cooldown window --
    setting it to a value shorter than the real gap between two requests
    lets the second request through instead of being suppressed."""
    monkeypatch.setenv("FORGOT_PASSWORD_COOLDOWN_SECONDS", "1")
    app = _make_app(engine)
    short_client = TestClient(app, raise_server_exceptions=True)

    Session = sessionmaker(bind=engine)
    db = Session()
    _create_user(db)
    db.close()

    resp1, count1 = _do_forgot_password(short_client, "alice")
    assert resp1.status_code == 200
    assert count1 == 1

    time.sleep(1.5)  # exceeds the 1s override

    resp2, count2 = _do_forgot_password(short_client, "alice")
    assert resp2.status_code == 200
    assert count2 == 1


def test_forgot_password_cooldown_suppresses_regardless_of_per_ip_rate_limit_state(client, db_session):
    """AC: the per-username cooldown alone is sufficient to suppress a
    request, independent of RATE_LIMIT_FORGOT_PASSWORD -- with the per-IP
    limiter disabled (so it can never be the cause), a second request for the
    same username from a brand-new source IP is still suppressed by the
    cooldown alone."""
    _create_user(db_session)

    resp1, count1 = _do_forgot_password(client, "alice", ip="192.168.1.1")
    assert resp1.status_code == 200
    assert count1 == 1

    resp2, count2 = _do_forgot_password(client, "alice", ip="192.168.1.2")
    assert resp2.status_code == 200
    assert count2 == 0


def test_forgot_password_per_ip_rate_limit_triggers_independent_of_cooldown(client_with_rate_limit):
    """AC: the existing per-IP RATE_LIMIT_FORGOT_PASSWORD (issue #121) still
    triggers 429 on its own for requests against *different* usernames sent
    from the same source IP -- proving the per-IP limit does not depend on
    the per-username cooldown ever being triggered, i.e. the two limits are
    independent, not one gating the other."""
    statuses = []
    for i in range(4):
        resp, _count = _do_forgot_password(client_with_rate_limit, f"nonexistent-user-{i}")
        statuses.append(resp)
    # Default RATE_LIMIT_FORGOT_PASSWORD is 3/minute; each request used a
    # distinct, nonexistent username, so the per-username cooldown is never
    # triggered here -- only the per-IP limit can be responsible for the 4th.
    assert [r.status_code for r in statuses[:3]] == [200] * 3
    blocked = statuses[3]
    assert blocked.status_code == 429


# --- AC 5: the cooldown expires on its own after the configured window --
#     no permanent lockout. --------------------------------------------------

def test_forgot_password_cooldown_expires_after_window_allows_new_email(monkeypatch, engine):
    """AC: once FORGOT_PASSWORD_COOLDOWN_SECONDS has fully elapsed since the
    first request, a follow-up request for the same username is no longer
    suppressed -- it sends a new email and issues a new PasswordResetToken,
    proving the cooldown expires on its own rather than being a permanent
    lockout.

    NOTE (issue #123): forgot_password() no longer mutates user.password_hash
    at all (see plan-issue-123-password-reset-token-flow.md) -- it creates a
    single-use PasswordResetToken instead, invalidating any prior one for the
    user. "a new temp password issued" is now proven by the token value
    changing between the two non-suppressed calls, not by password_hash."""
    monkeypatch.setenv("FORGOT_PASSWORD_COOLDOWN_SECONDS", "1")
    app = _make_app(engine)
    short_client = TestClient(app, raise_server_exceptions=True)

    Session = sessionmaker(bind=engine)
    db = Session()
    user = _create_user(db)

    resp1, count1 = _do_forgot_password(short_client, "alice")
    assert resp1.status_code == 200
    assert count1 == 1
    token_after_first = db.query(PasswordResetToken).filter_by(user_id=user.id).first()
    assert token_after_first is not None
    token_value_after_first = token_after_first.token

    time.sleep(1.5)  # fully exceeds the 1s cooldown window

    resp2, count2 = _do_forgot_password(short_client, "alice")
    assert resp2.status_code == 200
    assert count2 == 1  # new email actually sent, not suppressed

    tokens = db.query(PasswordResetToken).filter_by(user_id=user.id).all()
    assert len(tokens) == 1  # prior token invalidated, only the new one remains
    assert tokens[0].token != token_value_after_first  # new reset token issued
    db.close()


def test_forgot_password_cooldown_still_active_just_before_window_elapses(monkeypatch, engine):
    """AC (boundary): a follow-up request sent just before
    FORGOT_PASSWORD_COOLDOWN_SECONDS has fully elapsed is still suppressed --
    the cooldown does not expire early."""
    monkeypatch.setenv("FORGOT_PASSWORD_COOLDOWN_SECONDS", "3")
    app = _make_app(engine)
    short_client = TestClient(app, raise_server_exceptions=True)

    Session = sessionmaker(bind=engine)
    db = Session()
    user = _create_user(db)

    resp1, count1 = _do_forgot_password(short_client, "alice")
    assert resp1.status_code == 200
    assert count1 == 1
    db.refresh(user)
    hash_after_first = user.password_hash

    time.sleep(1)  # comfortably inside the 3s window -- must still be suppressed

    resp2, count2 = _do_forgot_password(short_client, "alice")
    assert resp2.status_code == 200
    assert count2 == 0  # still suppressed -- did not expire early
    db.refresh(user)
    assert user.password_hash == hash_after_first
    db.close()
