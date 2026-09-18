"""
Test stubs for plan-issue-77-temp-password-expiry.md

Story 1 — Temporary Password Expiry
  AC: temp password expires after TEMP_PASSWORD_TTL_HOURS hours (default 24)
  AC: login with an expired temp password returns 401 with a clear message
  AC: temp_password_expires_at is cleared to NULL on successful /change-password
  AC: expiry timestamp is stored in the users table and covered by a migration

Story 2 — Accurate Password Reset Email
  AC: email body states previous password is no longer valid and includes the TTL
  AC: email does not contain the incorrect deferred-change statement
  AC: email advises user to contact support if they did not request the reset

NOTE (issue #123, password-reset-token-flow redesign): POST /forgot-password no
longer generates or issues a temp password at all, and never touches
password_hash / must_change_password / temp_password_expires_at itself — it now
only creates a PasswordResetToken and emails a link/code (see
tests/test_issue_123_password_reset_token_flow.py and
markdown/features/reference/password-reset-token-flow.md). The following tests
were REMOVED because they exercised that now-fully-removed mechanism and have no
possible passing form under the new design (there is no remaining code path that
computes/sets temp_password_expires_at from forgot_password(), and the reset
email's wording is now the deliberate inverse of what these tests asserted):
  - test_temp_password_expires_at_is_set_when_forgot_password_called
  - test_temp_password_expires_at_equals_now_plus_ttl_hours
  - test_temp_password_ttl_defaults_to_24_hours
  - test_login_with_valid_temp_password_within_ttl_succeeds
  - test_reset_email_body_states_previous_password_no_longer_valid
  - test_reset_email_body_includes_expiry_duration
  - test_reset_email_body_advises_contact_support_if_not_requested
The remaining tests below are unaffected: the login-side expiry check
(POST /login rejecting/accepting based on a manually-seeded
temp_password_expires_at) and PUT /profile/password's clearing of that legacy
state are both still fully live code paths, untouched by issue #123 — those
tests seed the field directly rather than deriving it from forgot_password(),
so their coverage remains valid as-is. The migration/schema tests and the
"does not contain deferred-change statement" trivial-negative test are also
unaffected.
"""

import importlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models import User
from auth import hash_password
from routers import auth as auth_router
from routers import profile as profile_router
from migrate import run_migrations, _m020_temp_password_expiry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _make_app(engine):
    """Create a minimal FastAPI test app with auth and profile routers."""
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    # This test's /login and /forgot-password calls exercise temp-password
    # expiry, not rate limiting — but routers/auth.py's routes carry a
    # @limiter.limit(...) decorator bound to a *shared, process-wide*
    # `rate_limit.limiter` singleton (see backend/rate_limit.py and
    # test_issue_121_rate_limiting.py's module docstring). Without disabling
    # it here, repeated /forgot-password calls across this file's many test
    # functions (well over RATE_LIMIT_FORGOT_PASSWORD's default 3/minute, all
    # from TestClient's identical default source IP) would eventually start
    # returning 429 instead of the {"status": "ok"} these tests expect —
    # rate-limiting is out of scope for this test file, so it's turned off
    # for the app under test here.
    import rate_limit
    rate_limit.limiter.enabled = False

    # routers/auth.py also carries a module-level, process-wide
    # `_last_forgot_password_request` dict backing the per-username
    # /forgot-password cooldown (issue #122). Several tests below call
    # /forgot-password against the same username ("alice") repeatedly across
    # separate test functions; without reloading routers.auth to reset that
    # dict, the second and later calls within the process would be suppressed
    # by the cooldown and never actually send an email — unrelated to what
    # this file is testing. Reload it fresh for every app under test, mirroring
    # test_issue_121_rate_limiting.py and test_issue_122_forgot_password_cooldown.py.
    importlib.reload(auth_router)

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-123")
    app.include_router(auth_router.router)
    app.include_router(profile_router.router)
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


def _do_forgot_password(client, username, monkeypatch=None, ttl_hours=None):
    """Call POST /forgot-password with send_email mocked. Returns (response, captured_body)."""
    captured = {}

    def fake_send_email(to_address, subject, body):
        captured["body"] = body
        return True

    patch_kwargs = {}
    if ttl_hours is not None:
        patch_kwargs["TEMP_PASSWORD_TTL_HOURS"] = str(ttl_hours)

    env_patch = {}
    if ttl_hours is not None:
        env_patch["TEMP_PASSWORD_TTL_HOURS"] = str(ttl_hours)

    with patch("routers.auth.send_email", side_effect=fake_send_email):
        if env_patch:
            with patch.dict(os.environ, env_patch):
                resp = client.post("/forgot-password", json={"username": username})
        else:
            resp = client.post("/forgot-password", json={"username": username})

    return resp, captured.get("body", "")


# ---------------------------------------------------------------------------
# Story 1 — Temporary Password Expiry
# ---------------------------------------------------------------------------


def test_login_with_expired_temp_password_returns_401(client, db_session):
    """Logging in after the temp password TTL has elapsed returns HTTP 401."""
    plain_pw = "temp-password-xyz"
    user = _create_user(db_session, password=plain_pw)
    db_session.refresh(user)

    # Manually set the expiry to the past and mark as temp
    user.must_change_password = True
    user.temp_password_expires_at = int(time.time()) - 1  # already expired
    db_session.commit()

    resp = client.post("/login", json={"username": "alice", "password": plain_pw})
    assert resp.status_code == 401


def test_login_with_expired_temp_password_returns_expiry_message(client, db_session):
    """The 401 detail for an expired temp password prompts the user to request a new reset."""
    plain_pw = "temp-password-abc"
    user = _create_user(db_session, password=plain_pw)

    user.must_change_password = True
    user.temp_password_expires_at = int(time.time()) - 100
    db_session.commit()

    resp = client.post("/login", json={"username": "alice", "password": plain_pw})
    assert resp.status_code == 401
    detail = resp.json().get("detail", "")
    assert "expired" in detail.lower()
    assert "reset" in detail.lower() or "new password" in detail.lower()


def test_change_password_clears_temp_password_expires_at(client, db_session):
    """A successful POST /change-password sets temp_password_expires_at to NULL."""
    plain_pw = "old-password-123"
    user = _create_user(db_session, password=plain_pw)

    # Set a temp expiry
    user.must_change_password = True
    user.temp_password_expires_at = int(time.time()) + 3600
    db_session.commit()

    # Log in (expiry is in the future, so login should succeed)
    login_resp = client.post("/login", json={"username": "alice", "password": plain_pw})
    assert login_resp.status_code == 200

    # Change the password
    change_resp = client.put("/profile/password", json={
        "current_password": plain_pw,
        "new_password": "new-password-456",
    })
    assert change_resp.status_code == 200

    db_session.refresh(user)
    assert user.temp_password_expires_at is None


def test_change_password_also_clears_must_change_password_flag(client, db_session):
    """POST /change-password sets both must_change_password=False and temp_password_expires_at=NULL."""
    plain_pw = "old-password-789"
    user = _create_user(db_session, password=plain_pw)

    user.must_change_password = True
    user.temp_password_expires_at = int(time.time()) + 3600
    db_session.commit()

    login_resp = client.post("/login", json={"username": "alice", "password": plain_pw})
    assert login_resp.status_code == 200

    change_resp = client.put("/profile/password", json={
        "current_password": plain_pw,
        "new_password": "new-password-000",
    })
    assert change_resp.status_code == 200

    db_session.refresh(user)
    assert user.must_change_password is False
    assert user.temp_password_expires_at is None


def test_temp_password_expires_at_column_present_in_users_table():
    """The users table has a temp_password_expires_at column after migrations run."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}

    assert "temp_password_expires_at" in cols


def test_migration_020_adds_temp_password_expires_at_column():
    """Migration 020_temp_password_expiry adds temp_password_expires_at when the column is absent."""
    engine = create_engine("sqlite:///:memory:")

    # Create a legacy users table WITHOUT temp_password_expires_at
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                email TEXT,
                password_hash TEXT,
                is_admin BOOLEAN,
                tokens INTEGER DEFAULT 5,
                created_at INTEGER,
                player_id INTEGER,
                must_change_password BOOLEAN DEFAULT 0,
                is_tester BOOLEAN DEFAULT 0,
                twitch_user_id TEXT
            )
        """))
        conn.commit()

    # Verify the column is absent
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
    assert "temp_password_expires_at" not in cols

    # Run migration
    with engine.connect() as conn:
        _m020_temp_password_expiry(conn)

    # Column should now be present
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
    assert "temp_password_expires_at" in cols


def test_migration_020_is_idempotent_when_column_already_exists():
    """Running migration 020 twice does not raise an error."""
    engine = create_engine("sqlite:///:memory:")

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                temp_password_expires_at INTEGER
            )
        """))
        conn.commit()

    # Running twice should not raise
    with engine.connect() as conn:
        _m020_temp_password_expiry(conn)
        _m020_temp_password_expiry(conn)


# ---------------------------------------------------------------------------
# Story 2 — Accurate Password Reset Email
# ---------------------------------------------------------------------------


def _get_reset_email_body(client, db_session, ttl_hours=None):
    """Helper: create a user, trigger forgot-password, return the email body."""
    _create_user(db_session)
    _resp, body = _do_forgot_password(client, "alice", ttl_hours=ttl_hours)
    assert _resp.status_code == 200
    return body


def test_reset_email_body_does_not_contain_deferred_change_statement(client, db_session):
    """The email does not say the password change is deferred until the user logs in."""
    body = _get_reset_email_body(client, db_session)
    # The old incorrect statement said the password was not changed until login
    assert "was not changed until you log in" not in body
