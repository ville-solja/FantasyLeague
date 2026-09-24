"""
Failing test stubs for plan-issue-115-username-xss-fix.md (resolves GitHub
issue #115).

Issue #115 reports user "Eul" being repeatedly promoted/demoted with no admin
action taken — the stored username was
`<img src=x alt="Eul" onerror="toggleAdmin(69)">`. This is a live,
actively-exploitable stored-XSS privilege-escalation vulnerability:
`frontend/app-admin-users.js::_renderUsers` interpolates `u.username`
directly into an `innerHTML` string with no escaping, so every time an admin
opens User Management the browser attempts to load the fake `<img src=x>`,
fails, and its `onerror` fires `toggleAdmin(69)` with the admin's own
authenticated session. Two more unescaped instances of the same pattern exist:
`frontend/app-admin-ingest.js` (Audit Log's `actor_username`) and
`frontend/app-admin-demo.js` (seeded demo account usernames). The correct
pattern (`_escHtml()`, defined in `frontend/app-globals.js`) is already used
correctly in `frontend/app-leaderboard.js` — the admin surfaces were simply
missed.

Every stub below is a `pytest.fail("not yet implemented")` placeholder.

Covers two user stories from markdown/plans/plan-issue-115-username-xss-fix.md:

  Story 1 — Usernames Cannot Execute Script in Admin Views (display-side fix,
  the actual fix — these are file-content assertions against the three
  frontend files, matching the established pattern in
  test_mvp_visibility.py/test_issue_89_fix_available_draws_count.py, since no
  JS runtime/DOM is available in this test environment):
    - `frontend/app-admin-users.js::_renderUsers` wraps `u.username` in
      `_escHtml()` before it's concatenated into the users table's innerHTML
    - The old raw `${u.username}` interpolation (no `_escHtml()`) is gone
      from `_renderUsers`
    - `frontend/app-admin-ingest.js`'s Audit Log row renderer wraps
      `r.actor_username` in `_escHtml()` the same way
    - The old raw `${r.actor_username || ...}` interpolation is gone from the
      audit log row renderer
    - `frontend/app-admin-demo.js`'s seeded-accounts row renderer wraps
      `a.username` in `_escHtml()` the same way
    - The old raw `${a.username}` interpolation is gone from the
      seeded-accounts row renderer

  Story 2 — Reject Usernames Containing HTML-Significant Characters at
  Registration (defense in depth, backend validation — these call the actual
  FastAPI endpoints through a TestClient with SessionMiddleware, matching the
  established pattern in test_issue_77_temp_password_expiry.py, since
  `RegisterBody`/`UpdateUsernameBody` validation and `/login`-derived session
  state are both exercised):
    - `POST /register` rejects a username containing `<` or `>` with HTTP 422
    - `POST /register` rejects a username containing `"` or `'` with HTTP 422
    - `POST /register` still accepts a normal username (letters/digits/common
      punctuation not in the rejected set) — the added validator must not be
      overly strict
    - `PUT /profile/username` rejects a username containing HTML-significant
      characters (`<`, `>`, `"`, `'`) with HTTP 422, the same as registration
    - `PUT /profile/username` still accepts a normal replacement username
    - An account whose username already contains HTML-significant characters
      (stored before this validation existed) is unaffected by the new
      validator on read — no retroactive rename, `GET /profile/{user_id}`
      still returns the legacy value unchanged

Run with: cd backend && python -m pytest tests/test_issue_115_username_xss_fix.py -v
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from database import Base, get_db
from models import User
from auth import hash_password
from routers import auth as auth_router
from routers import profile as profile_router


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
APP_ADMIN_USERS_JS_PATH  = os.path.join(FRONTEND_DIR, "app-admin-users.js")
APP_ADMIN_INGEST_JS_PATH = os.path.join(FRONTEND_DIR, "app-admin-ingest.js")
APP_ADMIN_DEMO_JS_PATH   = os.path.join(FRONTEND_DIR, "app-admin-demo.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Backend fixtures (Story 2) — TestClient + SessionMiddleware, matching
# test_issue_77_temp_password_expiry.py's established pattern.
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
    """Create a minimal FastAPI test app with the auth and profile routers."""
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    # This test file's /register and /login calls exercise username
    # validation, not rate limiting — but routers/auth.py's routes carry a
    # @limiter.limit(...) decorator bound to a *shared, process-wide*
    # `rate_limit.limiter` singleton (see backend/rate_limit.py and
    # test_issue_121_rate_limiting.py's module docstring). Disable it here so
    # this file's request volume never interacts with rate-limit state left
    # over from — or shared with — other test files/runs.
    import rate_limit
    rate_limit.limiter.enabled = False

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


# ---------------------------------------------------------------------------
# Story 1 — Usernames Cannot Execute Script in Admin Views
# ---------------------------------------------------------------------------

class TestUsernamesCannotExecuteScriptInAdminViews:

    def test_render_users_escapes_username_with_esc_html(self):
        """_renderUsers() in frontend/app-admin-users.js wraps u.username in
        _escHtml() before concatenating it into the users table's innerHTML."""
        src = _read(APP_ADMIN_USERS_JS_PATH)
        assert "<td>${_escHtml(u.username)}${testerBadge}${adminBadge}</td>" in src

    def test_render_users_no_longer_interpolates_raw_username(self):
        """The old unescaped `<td>${u.username}${testerBadge}${adminBadge}</td>`
        pattern is gone from _renderUsers() in frontend/app-admin-users.js."""
        src = _read(APP_ADMIN_USERS_JS_PATH)
        assert "<td>${u.username}${testerBadge}${adminBadge}</td>" not in src

    def test_audit_log_escapes_actor_username_with_esc_html(self):
        """The Audit Log row renderer in frontend/app-admin-ingest.js wraps
        r.actor_username in _escHtml() before rendering it, same as the
        users-table fix."""
        src = _read(APP_ADMIN_INGEST_JS_PATH)
        assert '<td>${r.actor_username ? _escHtml(r.actor_username) : "<em style=\'color:#555\'>system</em>"}</td>' in src

    def test_audit_log_no_longer_interpolates_raw_actor_username(self):
        """The old unescaped `${r.actor_username || "<em ...>system</em>"}`
        pattern is gone from the Audit Log row renderer in
        frontend/app-admin-ingest.js."""
        src = _read(APP_ADMIN_INGEST_JS_PATH)
        assert '<td>${r.actor_username || "<em style=\'color:#555\'>system</em>"}</td>' not in src

    def test_seeded_demo_accounts_escapes_username_with_esc_html(self):
        """The seeded-accounts row renderer in frontend/app-admin-demo.js
        wraps a.username in _escHtml() before rendering it, same as the
        users-table fix."""
        src = _read(APP_ADMIN_DEMO_JS_PATH)
        assert '<td>${_escHtml(a.username)}</td><td style="font-family:monospace;">${_escHtml(a.password)}</td>' in src

    def test_seeded_demo_accounts_no_longer_interpolates_raw_username(self):
        """The old unescaped `<td>${a.username}</td>` pattern is gone from the
        seeded-accounts row renderer in frontend/app-admin-demo.js."""
        src = _read(APP_ADMIN_DEMO_JS_PATH)
        assert "<td>${a.username}</td><td" not in src


# ---------------------------------------------------------------------------
# Story 2 — Reject Usernames Containing HTML-Significant Characters at
# Registration
# ---------------------------------------------------------------------------

class TestRejectUsernamesContainingHtmlSignificantCharactersAtRegistration:

    def test_register_rejects_username_containing_angle_brackets(self, client):
        """POST /register with a username containing `<`/`>` (e.g. an
        `<img onerror=...>` payload) returns HTTP 422."""
        resp = client.post("/register", json={
            "username": '<img src=x alt="Eul" onerror="toggleAdmin(69)">',
            "email": "attacker@example.com",
            "password": "secret123",
        })
        assert resp.status_code == 422

    def test_register_rejects_username_containing_quote_characters(self, client):
        """POST /register with a username containing `"` or `'` returns
        HTTP 422."""
        resp = client.post("/register", json={
            "username": "o'brien\"quote",
            "email": "quote@example.com",
            "password": "secret123",
        })
        assert resp.status_code == 422

    def test_register_allows_normal_username(self, client):
        """POST /register with a normal username (letters, digits, common
        punctuation not in the rejected set) still succeeds — the new
        validator must not be overly strict."""
        resp = client.post("/register", json={
            "username": "normal_user-99",
            "email": "normal@example.com",
            "password": "secret123",
        })
        assert resp.status_code == 200
        assert resp.json()["username"] == "normal_user-99"

    def test_profile_username_change_rejects_html_significant_characters(self, client, db_session):
        """PUT /profile/username (or wherever username changes are accepted)
        rejects a username containing `<`, `>`, `"`, or `'` with HTTP 422,
        the same second independent validation layer as registration."""
        _create_user(db_session, username="bob")
        login_resp = client.post("/login", json={"username": "bob", "password": "secret123"})
        assert login_resp.status_code == 200
        resp = client.put("/profile/username", json={"username": "<script>alert(1)</script>"})
        assert resp.status_code == 422

    def test_profile_username_change_allows_normal_username(self, client, db_session):
        """PUT /profile/username still succeeds for a normal replacement
        username with no HTML-significant characters."""
        _create_user(db_session, username="carol")
        login_resp = client.post("/login", json={"username": "carol", "password": "secret123"})
        assert login_resp.status_code == 200
        resp = client.put("/profile/username", json={"username": "carol-renamed"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "carol-renamed"

    def test_existing_legacy_html_username_unaffected_by_new_validation(self, client, db_session):
        """An account whose username already contains HTML-significant
        characters (stored before this validation existed) is unaffected by
        the new validator on read — GET /profile/{user_id} still returns the
        legacy value unchanged, with no retroactive rename forced.

        GET /profile/{user_id} requires login (issue #120,
        markdown/features/reference/profile-requires-login.md) — any
        authenticated account can view any profile, so a second normal
        account logs in here purely to satisfy that auth gate; it is not
        the profile being viewed."""
        legacy_username = '<img src=x alt="Eul" onerror="toggleAdmin(69)">'
        user = _create_user(db_session, username=legacy_username, email="legacy@example.com")
        _create_user(db_session, username="viewer", email="viewer@example.com")
        login_resp = client.post("/login", json={"username": "viewer", "password": "secret123"})
        assert login_resp.status_code == 200
        resp = client.get(f"/profile/{user.id}")
        assert resp.status_code == 200
        assert resp.json()["username"] == legacy_username
