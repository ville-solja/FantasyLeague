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
"""

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


def test_temp_password_expires_at_is_set_when_forgot_password_called(client, db_session):
    """forgot_password() stores a non-null temp_password_expires_at on the user."""
    user = _create_user(db_session)

    resp, _ = _do_forgot_password(client, "alice")

    assert resp.status_code == 200
    db_session.refresh(user)
    assert user.temp_password_expires_at is not None


def test_temp_password_expires_at_equals_now_plus_ttl_hours(client, db_session):
    """The stored expiry timestamp equals the request time plus TEMP_PASSWORD_TTL_HOURS * 3600."""
    user = _create_user(db_session)
    ttl_hours = 6

    before = int(time.time())
    resp, _ = _do_forgot_password(client, "alice", ttl_hours=ttl_hours)
    after = int(time.time())

    assert resp.status_code == 200
    db_session.refresh(user)
    expires_at = user.temp_password_expires_at
    assert expires_at is not None
    assert before + ttl_hours * 3600 <= expires_at <= after + ttl_hours * 3600


def test_temp_password_ttl_defaults_to_24_hours(client, db_session):
    """When TEMP_PASSWORD_TTL_HOURS is unset, the expiry window defaults to 24 hours."""
    user = _create_user(db_session)

    before = int(time.time())
    with patch("routers.auth.send_email", return_value=True), \
         patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TEMP_PASSWORD_TTL_HOURS", None)
        resp = client.post("/forgot-password", json={"username": "alice"})
    after = int(time.time())

    assert resp.status_code == 200
    db_session.refresh(user)
    expires_at = user.temp_password_expires_at
    assert expires_at is not None
    expected_min = before + 24 * 3600
    expected_max = after + 24 * 3600
    assert expected_min <= expires_at <= expected_max


def test_login_with_valid_temp_password_within_ttl_succeeds(client, db_session):
    """A temporary password used before expiry grants a successful login."""
    user = _create_user(db_session, password="old-password")

    resp, _ = _do_forgot_password(client, "alice")
    assert resp.status_code == 200

    # Pull the new password from the database — we know it's set; extract via hash
    # Actually we need to get the temp password. Let's capture it from email body.
    # Re-do with body capture to get temp password.

    # Reset user state and redo to capture the temp password from email body
    user2 = _create_user(db_session, username="bob", email="bob@example.com")

    captured = {}

    def capture_send(to_address, subject, body):
        captured["body"] = body
        return True

    with patch("routers.auth.send_email", side_effect=capture_send):
        resp2 = client.post("/forgot-password", json={"username": "bob"})

    assert resp2.status_code == 200

    # Extract temp password from email body
    body_text = captured["body"]
    # The temp password is on an indented line: "    {temp_password}"
    temp_pw = None
    for line in body_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("Hi ") and not stripped.startswith("A temp") \
                and not stripped.startswith("Your") and not stripped.startswith("This temp") \
                and not stripped.startswith("Log in") and not stripped.startswith("If you"):
            # Check it looks like a token (no spaces, alphanumeric + URL-safe chars)
            if len(stripped) > 6 and " " not in stripped and stripped[0] not in "HALY":
                temp_pw = stripped
                break

    # Simpler: split on the known markers
    parts = body_text.split("    ")
    # The temp password line has 4-space indent
    for part in parts:
        candidate = part.strip().split("\n")[0].strip()
        if candidate and len(candidate) >= 8 and not any(
            w in candidate for w in ["Hi ", "A ", "Your", "This", "Log ", "If "]
        ):
            temp_pw = candidate
            break

    assert temp_pw is not None, f"Could not extract temp password from email body:\n{body_text}"

    db_session.refresh(user2)
    # Set expiry in the future
    user2.temp_password_expires_at = int(time.time()) + 3600
    user2.must_change_password = True
    db_session.commit()

    login_resp = client.post("/login", json={"username": "bob", "password": temp_pw})
    assert login_resp.status_code == 200


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


def test_reset_email_body_states_previous_password_no_longer_valid(client, db_session):
    """The password reset email body explicitly states the previous password is no longer valid."""
    body = _get_reset_email_body(client, db_session)
    assert "no longer valid" in body.lower()


def test_reset_email_body_includes_expiry_duration(client, db_session):
    """The email body mentions the number of hours until the temporary password expires."""
    ttl_hours = 48
    body = _get_reset_email_body(client, db_session, ttl_hours=ttl_hours)
    assert str(ttl_hours) in body
    assert "hour" in body.lower()


def test_reset_email_body_does_not_contain_deferred_change_statement(client, db_session):
    """The email does not say the password change is deferred until the user logs in."""
    body = _get_reset_email_body(client, db_session)
    # The old incorrect statement said the password was not changed until login
    assert "was not changed until you log in" not in body


def test_reset_email_body_advises_contact_support_if_not_requested(client, db_session):
    """The email tells users who did not request the reset to contact support immediately."""
    body = _get_reset_email_body(client, db_session)
    assert "contact support" in body.lower()
