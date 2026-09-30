"""
Tests for plan-issue-119-session-revocation.md (resolves GitHub issue #119).

A per-user integer `users.session_version` is copied into the session cookie
(key "sv") at login/register. Every session-based check compares the two; bumping
the number invalidates every existing session of that user at once.

  Story 1: Password Changes Log Out Other Sessions
  Story 2: Log Out Everywhere
  Story 3: Admin Force Logout
  Story 4: All Session Checks Go Through One Place
  Story 5: Configurable Session Lifetime

Approach notes:

- `session_env`: a minimal FastAPI app on a StaticPool in-memory
  engine, like `auth_env` in test_issue_136_security_audit_3.py. Include the auth,
  profile, admin_users, cards and twitch routers, add
  `SessionMiddleware(secret_key="test-secret-key-123")`, override `get_db`, and set
  `rate_limit.limiter.enabled = False` (restore in finally). Do not reload `main`
  for these tests; its lifespan starts background loops (lessons-learned
  2026-09-27 / 2026-09-28). Reload only modules already in `sys.modules`.
- Two sessions for the same user = two `TestClient(app)` instances on the same app,
  each POSTing `/login`. Each TestClient keeps its own cookie jar.
- Seed users directly through the Session factory (`User(username=...,
  password_hash=hash_password(...))`), as test_issue_123 does. For admin tests,
  set `is_admin=True` on the seeded row.
- Reset-password tests seed a `PasswordResetToken` row directly (see
  test_issue_123_password_reset_token_flow.py `_seed_token`-style helpers).
- A cookie without "sv": sign `{"user_id": <id>}` with the same secret the
  SessionMiddleware uses. Starlette's format is
  `itsdangerous.TimestampSigner(secret).sign(base64.b64encode(json.dumps(data).encode()))`;
  set it as the `session` cookie on the client.
- Startup-guard tests (Story 5) use a subprocess `import main`, like
  `_run_import_main` in test_issue_136_security_audit_3.py (keep `HTTPS_ONLY=true`
  in the env, per lessons-learned 2026-09-28). The default-value and override
  tests print SessionMiddleware's `max_age` from `main.app.user_middleware` in the
  same subprocess, so `main` is never reloaded in-process.
- Frontend criteria are static text checks of `frontend/*.js` / `index.html`,
  reading files relative to the repo root like `_read()` in test_issue_136.

Run with: cd backend && python -m pytest tests/test_issue_119_session_revocation.py -v
"""

import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import itsdangerous
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from auth import hash_password
from models import AuditLog, Card, PasswordResetToken, Player, User

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
_SECRET = "test-secret-key-123"
_PASSWORD = "secret123"


def _read(rel_path):
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _js_function(source, name):
    """Body of `function name(...) { ... }` (sync or async) in a JS source, by brace matching."""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", source)
    assert m, f"function {name} not found"
    start = source.index("{", m.end())
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


class _Env:
    def __init__(self, app, Session):
        self.app = app
        self.Session = Session

    def client(self):
        return TestClient(self.app)

    def add_user(self, username="alice", is_admin=False, session_version=0):
        db = self.Session()
        try:
            user = User(username=username, email=f"{username}@example.com",
                        password_hash=hash_password(_PASSWORD), is_admin=is_admin,
                        tokens=5, created_at=int(time.time()),
                        session_version=session_version)
            db.add(user)
            db.commit()
            return user.id
        finally:
            db.close()

    def login(self, username="alice", password=_PASSWORD):
        client = self.client()
        resp = client.post("/login", json={"username": username, "password": password})
        assert resp.status_code == 200, resp.text
        return client

    def version(self, user_id):
        db = self.Session()
        try:
            return db.get(User, user_id).session_version
        finally:
            db.close()

    def bump_in_db(self, user_id):
        db = self.Session()
        try:
            user = db.get(User, user_id)
            user.session_version = (user.session_version or 0) + 1
            db.commit()
        finally:
            db.close()

    def audit(self, action):
        db = self.Session()
        try:
            return db.query(AuditLog).filter_by(action=action).all()
        finally:
            db.close()


@pytest.fixture
def session_env():
    import rate_limit
    import twitch
    from database import Base, get_db
    from deps import get_current_user
    from routers import admin_users as admin_users_router
    from routers import auth as auth_router
    from routers import cards as cards_router
    from routers import profile as profile_router

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    modules = (auth_router, profile_router, admin_users_router, cards_router, twitch)
    # Disable the limiter each router was decorated with too, in case another
    # test reloaded rate_limit after these routers were imported.
    limiters = {id(rate_limit.limiter): rate_limit.limiter}
    for m in modules:
        if hasattr(m, "limiter"):
            limiters[id(m.limiter)] = m.limiter
    was_enabled = {k: lim.enabled for k, lim in limiters.items()}
    for lim in limiters.values():
        lim.enabled = False

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=_SECRET)
    app.state.limiter = rate_limit.limiter
    for m in modules:
        app.include_router(m.router)
    app.dependency_overrides[get_db] = _override_get_db

    @app.get("/_test/whoami")
    def _whoami(current_user: dict = Depends(get_current_user)):
        return current_user

    try:
        yield _Env(app, Session)
    finally:
        for k, lim in limiters.items():
            lim.enabled = was_enabled[k]
        engine.dispose()


def _run_import_main(tmp_path, env_overrides, code="import main"):
    """Run `code` (default `import main`) in a subprocess with a controlled environment."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("ENV", "DEBUG", "TWITCH_LOCAL_DEV", "SECRET_KEY", "AUTO_INGEST_LEAGUES",
                     "SESSION_MAX_AGE_SECONDS")
    }
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'fantasy.db'}"
    env["HTTPS_ONLY"] = "true"
    env["DEBUG"] = "true"
    env["BACKGROUND_TASKS_ENABLED"] = "false"
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND_DIR), env=env, capture_output=True, text=True, timeout=120,
    )


_PRINT_MAX_AGE = (
    "import main\n"
    "print('MAX_AGE=' + str([m.kwargs.get('max_age') for m in main.app.user_middleware "
    "if m.cls.__name__ == 'SessionMiddleware'][0]))"
)


def _seed_deck(env, user_id, rarity):
    db = env.Session()
    try:
        db.add(Player(id=501, name="P1"))
        db.add(Card(player_id=501, owner_id=user_id, card_type=rarity,
                    is_active=False, generation=1))
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Story 1 — Password Changes Log Out Other Sessions
# ---------------------------------------------------------------------------

def test_user_model_session_version_defaults_to_zero(db):
    """users.session_version is an integer, default 0 (new User row in the `db` fixture has session_version == 0)."""
    user = User(username="zero", email="zero@example.com", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.session_version == 0


def test_migration_028_adds_session_version_to_legacy_users_table(tmp_path):
    """Migration 028_users_session_version adds users.session_version (INTEGER, default 0) to a legacy table; existing rows read 0. Build a legacy users table without the column, run run_migrations(engine), check PRAGMA table_info (see test_migrate.py)."""
    from migrate import run_migrations

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT, email TEXT,
                password_hash TEXT, is_admin BOOLEAN, tokens INTEGER DEFAULT 5,
                created_at INTEGER, player_id INTEGER, must_change_password BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'old')"))
        conn.commit()

    run_migrations(engine)

    with engine.connect() as conn:
        cols = {r[1]: r for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
        assert "session_version" in cols
        assert cols["session_version"][2].upper() == "INTEGER"
        assert cols["session_version"][4] == "0"
        assert conn.execute(text("SELECT session_version FROM users WHERE id = 1")).scalar() == 0
    engine.dispose()


def test_login_stores_session_version_in_session(session_env):
    """POST /login stores the user's current session_version as "sv": with session_version=3 in the DB, GET /me succeeds after login (session_env)."""
    session_env.add_user(session_version=3)
    client = session_env.login()
    assert client.get("/me").status_code == 200


def test_register_stores_session_version_in_session(session_env):
    """POST /register stores session_version ("sv") in the session, so GET /me returns 200 immediately after registering (session_env)."""
    client = session_env.client()
    resp = client.post("/register", json={"username": "newbie", "email": "newbie@example.com",
                                          "password": _PASSWORD})
    assert resp.status_code == 200, resp.text
    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["username"] == "newbie"


def test_change_password_keeps_current_session_and_revokes_others(session_env):
    """PUT /profile/password increments session_version; client A (requester) still gets 200 on GET /me, client B (other session of same user) gets 401 (session_env, two TestClients)."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    resp = a.put("/profile/password", json={"current_password": _PASSWORD,
                                            "new_password": "brand-new-pw"})
    assert resp.status_code == 200, resp.text
    assert session_env.version(uid) == 1
    assert a.get("/me").status_code == 200
    assert b.get("/me").status_code == 401


def test_change_password_wrong_current_password_does_not_bump_version(session_env):
    """Failure path: PUT /profile/password with a wrong current password is rejected, session_version is unchanged, and the other session still gets 200 on GET /me."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    resp = a.put("/profile/password", json={"current_password": "wrong-password",
                                            "new_password": "brand-new-pw"})
    assert resp.status_code == 401
    assert session_env.version(uid) == 0
    assert b.get("/me").status_code == 200


def test_reset_password_revokes_all_existing_sessions(session_env):
    """POST /reset-password with a valid seeded PasswordResetToken increments session_version; every existing logged-in client gets 401 on GET /me."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    db = session_env.Session()
    db.add(PasswordResetToken(token="tok-119", user_id=uid, expires_at=int(time.time()) + 3600))
    db.commit()
    db.close()
    resp = session_env.client().post("/reset-password",
                                     json={"token": "tok-119", "new_password": "brand-new-pw"})
    assert resp.status_code == 200, resp.text
    assert session_env.version(uid) == 1
    assert a.get("/me").status_code == 401
    assert b.get("/me").status_code == 401


def test_reset_password_invalid_token_does_not_bump_version(session_env):
    """Failure path: POST /reset-password with an unknown token returns 400, session_version unchanged, existing session still gets 200 on GET /me."""
    uid = session_env.add_user()
    a = session_env.login()
    resp = session_env.client().post("/reset-password",
                                     json={"token": "no-such-token", "new_password": "brand-new-pw"})
    assert resp.status_code == 400
    assert session_env.version(uid) == 0
    assert a.get("/me").status_code == 200


def test_session_with_mismatched_version_returns_401(session_env):
    """A session whose "sv" does not match users.session_version gets 401 from GET /me (bump the version directly in the DB after login)."""
    uid = session_env.add_user()
    client = session_env.login()
    assert client.get("/me").status_code == 200
    session_env.bump_in_db(uid)
    assert client.get("/me").status_code == 401


def test_session_without_version_returns_401(session_env):
    """A legacy cookie with no "sv" (signed {"user_id": id} with the test secret via itsdangerous.TimestampSigner) gets 401 from GET /me."""
    uid = session_env.add_user()
    signer = itsdangerous.TimestampSigner(_SECRET)
    legacy = base64.b64encode(json.dumps({"user_id": uid, "username": "alice",
                                          "is_admin": False}).encode("utf-8"))
    client = session_env.client()
    client.cookies.set("session", signer.sign(legacy).decode("utf-8"))
    assert client.get("/me").status_code == 401

    # Control: the same signing with the current version is accepted.
    current = base64.b64encode(json.dumps({"user_id": uid, "sv": 0}).encode("utf-8"))
    ok_client = session_env.client()
    ok_client.cookies.set("session", signer.sign(current).decode("utf-8"))
    assert ok_client.get("/me").status_code == 200


def test_session_for_deleted_user_returns_401(session_env):
    """A session for a user id that no longer exists (row deleted from DB after login) gets 401 from GET /me."""
    uid = session_env.add_user()
    client = session_env.login()
    db = session_env.Session()
    db.delete(db.get(User, uid))
    db.commit()
    db.close()
    assert client.get("/me").status_code == 401


# ---------------------------------------------------------------------------
# Story 2 — Log Out Everywhere
# ---------------------------------------------------------------------------

def test_logout_everywhere_bumps_version_and_clears_session(session_env):
    """POST /logout-everywhere increments the caller's session_version, returns {"status": "ok"}, and the caller's own next GET /me is 401 (session cleared)."""
    uid = session_env.add_user()
    client = session_env.login()
    resp = client.post("/logout-everywhere")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert session_env.version(uid) == 1
    assert client.get("/me").status_code == 401


def test_logout_everywhere_writes_audit_entry(session_env):
    """POST /logout-everywhere writes an AuditLog row with action "user_logout_everywhere" and actor_id = caller."""
    uid = session_env.add_user()
    client = session_env.login()
    assert client.post("/logout-everywhere").status_code == 200
    rows = session_env.audit("user_logout_everywhere")
    assert len(rows) == 1
    assert rows[0].actor_id == uid
    assert rows[0].actor_username == "alice"


def test_logout_everywhere_revokes_second_session(session_env):
    """After POST /logout-everywhere from client A, client B (same user) gets 401 from GET /me; logging in again on B works."""
    session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    assert a.post("/logout-everywhere").status_code == 200
    assert b.get("/me").status_code == 401
    assert b.post("/login", json={"username": "alice", "password": _PASSWORD}).status_code == 200
    assert b.get("/me").status_code == 200


def test_logout_everywhere_without_session_returns_401(session_env):
    """Failure path: POST /logout-everywhere without a session returns 401 and writes no audit entry."""
    resp = session_env.client().post("/logout-everywhere")
    assert resp.status_code == 401
    assert session_env.audit("user_logout_everywhere") == []


def test_frontend_profile_has_logout_everywhere_button():
    """Static check: frontend/index.html or frontend/app-profile.js contains a "Log out everywhere" button that POSTs /logout-everywhere."""
    html = _read("frontend/index.html")
    assert re.search(
        r'<button[^>]*onclick="logoutEverywhere\(\)"[^>]*>\s*Log out everywhere\s*</button>', html)
    handler = _js_function(_read("frontend/app-profile.js"), "logoutEverywhere")
    assert "/logout-everywhere" in handler
    assert 'method: "POST"' in handler


def test_frontend_logout_everywhere_resets_local_auth_state():
    """Static check: the logout-everywhere handler in frontend/app-profile.js clears local auth state (removes localStorage "username"/"is_admin" and calls applyAuthState, or calls a shared cleanup used by logout())."""
    auth_js = _read("frontend/app-auth.js")
    handler = _js_function(_read("frontend/app-profile.js"), "logoutEverywhere")
    assert "_clearLocalAuthState()" in handler
    # The shared cleanup is the one logout() uses.
    assert "_clearLocalAuthState()" in _js_function(auth_js, "logout")
    cleanup = _js_function(auth_js, "_clearLocalAuthState")
    assert 'localStorage.removeItem("username")' in cleanup
    assert 'localStorage.removeItem("is_admin")' in cleanup
    assert "applyAuthState()" in cleanup


# ---------------------------------------------------------------------------
# Story 3 — Admin Force Logout
# ---------------------------------------------------------------------------

def test_force_logout_bumps_target_version_and_returns_user(session_env):
    """POST /users/{user_id}/force-logout as admin increments the target's session_version, returns {"user_id", "username"}, and the target's session gets 401 on GET /me."""
    session_env.add_user("boss", is_admin=True)
    target = session_env.add_user("bob")
    admin = session_env.login("boss")
    victim = session_env.login("bob")
    resp = admin.post(f"/users/{target}/force-logout")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"user_id": target, "username": "bob"}
    assert session_env.version(target) == 1
    assert victim.get("/me").status_code == 401
    assert admin.get("/me").status_code == 200


def test_force_logout_writes_audit_entry_naming_target(session_env):
    """POST /users/{user_id}/force-logout writes an AuditLog row with action "admin_force_logout" whose detail names the target user."""
    admin_id = session_env.add_user("boss", is_admin=True)
    target = session_env.add_user("bob")
    admin = session_env.login("boss")
    assert admin.post(f"/users/{target}/force-logout").status_code == 200
    rows = session_env.audit("admin_force_logout")
    assert len(rows) == 1
    assert rows[0].actor_id == admin_id
    assert "bob" in rows[0].detail


def test_force_logout_unknown_user_returns_404(session_env):
    """Failure path: POST /users/99999/force-logout as admin returns 404."""
    session_env.add_user("boss", is_admin=True)
    admin = session_env.login("boss")
    assert admin.post("/users/99999/force-logout").status_code == 404
    assert session_env.audit("admin_force_logout") == []


def test_force_logout_non_admin_returns_403(session_env):
    """Failure path: POST /users/{user_id}/force-logout as a non-admin returns 403 and the target's session_version is unchanged."""
    session_env.add_user("mallory")
    target = session_env.add_user("bob")
    mallory = session_env.login("mallory")
    victim = session_env.login("bob")
    assert mallory.post(f"/users/{target}/force-logout").status_code == 403
    assert session_env.version(target) == 0
    assert victim.get("/me").status_code == 200


def test_force_logout_self_ends_own_sessions(session_env):
    """An admin forcing their own logout succeeds and their own session then gets 401 on GET /me."""
    admin_id = session_env.add_user("boss", is_admin=True)
    admin = session_env.login("boss")
    assert admin.post(f"/users/{admin_id}/force-logout").status_code == 200
    assert session_env.version(admin_id) == 1
    assert admin.get("/me").status_code == 401


def test_frontend_admin_users_has_force_logout_button_with_confirm():
    """Static check: frontend/app-admin-users.js renders a "Force logout" button per user, guarded by confirm(), that POSTs /users/{id}/force-logout."""
    js = _read("frontend/app-admin-users.js")
    render = _js_function(js, "_renderUsers")
    assert re.search(r'onclick="forceLogout\(\$\{u\.id\}\)"[^>]*>Force logout</button>', render)
    handler = _js_function(js, "forceLogout")
    assert "confirm(" in handler
    assert handler.index("confirm(") < handler.index("fetch(")
    assert "/users/${userId}/force-logout" in handler
    assert 'method: "POST"' in handler


# ---------------------------------------------------------------------------
# Story 4 — All Session Checks Go Through One Place
# ---------------------------------------------------------------------------

def test_get_current_user_returns_fields_from_db_not_cookie(session_env):
    """get_current_user returns user_id, username and is_admin from the DB row: rename the user / flip is_admin in the DB after login and GET /me reflects the DB values."""
    uid = session_env.add_user()
    client = session_env.login()
    assert client.get("/_test/whoami").json() == {"user_id": uid, "username": "alice",
                                                  "is_admin": False}
    db = session_env.Session()
    user = db.get(User, uid)
    user.username = "alice2"
    user.is_admin = True
    db.commit()
    db.close()
    assert client.get("/_test/whoami").json() == {"user_id": uid, "username": "alice2",
                                                  "is_admin": True}


def test_get_current_user_logged_out_request_raises_401_without_db():
    """Failure path: calling deps.get_current_user directly with a logged-out request raises 401 before touching db (keeps test_issue_132's direct call working)."""
    from fastapi import HTTPException
    from deps import get_current_user

    class _Request:
        session = {}

    class _ExplodingDb:
        def __getattr__(self, name):
            raise AssertionError(f"db.{name} touched for a logged-out request")

    with pytest.raises(HTTPException) as exc:
        get_current_user(_Request(), _ExplodingDb())
    assert exc.value.status_code == 401
    # Also with the default db argument, as test_issue_132 calls it.
    with pytest.raises(HTTPException) as exc:
        get_current_user(_Request())
    assert exc.value.status_code == 401


def test_twitch_link_code_with_valid_session_succeeds(session_env):
    """POST /twitch/link-code with a current session returns a code (get_session_user delegates to get_current_user)."""
    session_env.add_user()
    client = session_env.login()
    resp = client.post("/twitch/link-code")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["code"]) == 6


def test_twitch_link_code_with_revoked_session_returns_401(session_env):
    """Failure path: POST /twitch/link-code with a revoked session (version bumped in DB) returns 401."""
    uid = session_env.add_user()
    client = session_env.login()
    session_env.bump_in_db(uid)
    assert client.post("/twitch/link-code").status_code == 401


def test_deck_with_revoked_session_treated_as_logged_out(session_env):
    """GET /deck with a revoked session returns the logged-out counts (all combos available), not the user's owned-card-filtered counts. Seed a Player and a Card owned by the user to tell them apart."""
    uid = session_env.add_user()
    _seed_deck(session_env, uid, "common")
    client = session_env.login()
    assert client.get("/deck").json()["common"] == 0
    session_env.bump_in_db(uid)
    assert client.get("/deck").json() == {"common": 1, "rare": 1, "epic": 1, "legendary": 1}


def test_deck_with_valid_session_excludes_owned_cards(session_env):
    """GET /deck with a current session still excludes the user's owned (player, rarity) combos (session_user_or_none returns the user)."""
    uid = session_env.add_user()
    _seed_deck(session_env, uid, "rare")
    client = session_env.login()
    assert client.get("/deck").json() == {"common": 1, "rare": 0, "epic": 1, "legendary": 1}
    assert session_env.client().get("/deck").json()["rare"] == 1


def test_frontend_load_me_clears_auth_state_on_401():
    """Static check: loadMe in frontend/app-auth.js handles res.status === 401 by resetting activeUserId/activeUsername/activeIsAdmin, removing localStorage "username" and "is_admin", and calling applyAuthState()."""
    js = _read("frontend/app-auth.js")
    body = _js_function(js, "loadMe")
    assert "res.status === 401" in body
    after_401 = body[body.index("res.status === 401"):]
    assert "_clearLocalAuthState()" in after_401[:after_401.index("return")]
    cleanup = _js_function(js, "_clearLocalAuthState")
    assert "activeUserId = activeUsername = null" in cleanup
    assert "activeIsAdmin = false" in cleanup
    assert 'localStorage.removeItem("username")' in cleanup
    assert 'localStorage.removeItem("is_admin")' in cleanup
    assert "applyAuthState()" in cleanup


# ---------------------------------------------------------------------------
# Story 5 — Configurable Session Lifetime
# ---------------------------------------------------------------------------

def test_session_max_age_defaults_to_86400(tmp_path):
    """With SESSION_MAX_AGE_SECONDS unset, SessionMiddleware max_age is 86400 (subprocess `import main`, inspect main.app.user_middleware)."""
    result = _run_import_main(tmp_path, {}, code=_PRINT_MAX_AGE)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "MAX_AGE=86400" in result.stdout


def test_session_max_age_env_overrides_value(tmp_path):
    """SESSION_MAX_AGE_SECONDS=1209600 sets SessionMiddleware max_age to 1209600."""
    result = _run_import_main(tmp_path, {"SESSION_MAX_AGE_SECONDS": "1209600"}, code=_PRINT_MAX_AGE)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "MAX_AGE=1209600" in result.stdout


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_session_max_age_invalid_value_fails_startup(tmp_path, value):
    """Failure path: a non-integer or non-positive SESSION_MAX_AGE_SECONDS fails `import main` with a RuntimeError naming the variable (subprocess, like _run_import_main in test_issue_136)."""
    result = _run_import_main(tmp_path, {"SESSION_MAX_AGE_SECONDS": value})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "SESSION_MAX_AGE_SECONDS" in result.stderr


def test_env_example_documents_session_max_age():
    """.env.example documents SESSION_MAX_AGE_SECONDS, and markdown/features/core/auth.md mentions it with a note that revocation makes a longer value safe."""
    env_example = _read(".env.example")
    assert re.search(r"^#?\s*SESSION_MAX_AGE_SECONDS=86400", env_example, re.M)
    auth_doc = _read("markdown/features/core/auth.md")
    assert "SESSION_MAX_AGE_SECONDS" in auth_doc
    assert "revocation" in auth_doc.lower()
