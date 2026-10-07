"""
Tests for plan-issue-117-longer-sessions.md (resolves GitHub issue #117).

Sessions move to a server-side `user_sessions` table keyed by sha256(session id).
The cookie payload becomes {"sid": "<token>"} only; idle and absolute limits are
enforced on the server, per role (player vs admin); admins re-authenticate before
destructive actions.

  Story 1: Stay Logged In While Active
  Story 2: Logout Ends the Session on the Server
  Story 3: New Session ID on Login and Privilege Change
  Story 4: Shorter Sessions and Re-Authentication for Admins
  Story 5: See and End My Sessions
  Story 6: Operators Can Tune and Audit the Limits

Approach notes:

- `session_env`: a minimal FastAPI app on a StaticPool in-memory engine, copied
  from `session_env` in test_issue_119_session_revocation.py. It includes the
  auth, profile, admin_users, cards and twitch routers plus admin_season,
  admin_leagues and admin_backups (for the re-auth endpoints), adds
  `SessionMiddleware(secret_key=_SECRET)`, overrides `get_db`, and disables
  every limiter the routers were decorated with (restored in finally). `main`
  is never reloaded in-process; its lifespan starts background loops
  (lessons-learned 2026-09-27 / 2026-09-28).
- Two sessions for the same user = two `TestClient(app)` instances, each
  POSTing `/login` (each keeps its own cookie jar).
- Clock control: patch sessions' clock helper (the single `time.time()` wrapper
  in backend/sessions.py that plan Step 2 describes) with monkeypatch, so idle,
  absolute, touch and re-auth windows can be crossed without sleeping.
- Reading the session id: decode the signed Starlette cookie with
  `itsdangerous.TimestampSigner(_SECRET).unsign(...)` + base64/json, as
  test_issue_119 builds cookies; the payload must be exactly {"sid": ...}.
- Tests that hit /admin/backups or /admin/season/reset must
  `monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'fantasy.db'}")`
  (lessons-learned 2026-09-24) so no real data/ file is touched.
- Startup-validation and cookie-config criteria (Stories 3 and 6) use a
  subprocess `import main` like `_run_import_main` in test_issue_119 /
  test_issue_136 (keep HTTPS_ONLY=true unless the test is about the cookie name
  without it; lessons-learned 2026-09-28). Inspect
  `main.app.user_middleware` kwargs in the same subprocess.
- Frontend criteria are static text checks of `frontend/*.js` / `index.html`,
  read relative to the repo root with `_read()`.

Run with: cd backend && python -m pytest tests/test_issue_117_longer_sessions.py -v
"""

import base64
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import itsdangerous
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from auth import hash_password
from models import AuditLog, PasswordResetToken, User, UserSession

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
_SECRET = "test-secret-key-117"
_PASSWORD = "secret123"

_SESSION_SETTINGS = (
    "SESSION_IDLE_SECONDS",
    "SESSION_ABSOLUTE_SECONDS",
    "SESSION_TOUCH_SECONDS",
    "ADMIN_SESSION_IDLE_SECONDS",
    "ADMIN_SESSION_ABSOLUTE_SECONDS",
    "ADMIN_REAUTH_SECONDS",
)

# (method, path) of every endpoint that must require a recent re-auth.
_REAUTH_ENDPOINTS = (
    ("POST", "/admin/season/end"),
    ("POST", "/admin/season/reset"),
    ("DELETE", "/admin/leagues/{league_id}/data"),
    ("POST", "/admin/backups"),
    ("GET", "/admin/backups"),
    ("GET", "/admin/backups/{filename}"),
    ("POST", "/users/{user_id}/toggle-admin"),
)


def _read(rel_path):
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


class _Env:
    def __init__(self, app, Session):
        self.app = app
        self.Session = Session

    def client(self):
        return TestClient(self.app)

    def add_user(self, username="alice", is_admin=False):
        db = self.Session()
        try:
            user = User(username=username, email=f"{username}@example.com",
                        password_hash=hash_password(_PASSWORD), is_admin=is_admin,
                        tokens=5, created_at=int(time.time()))
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

    def rows(self, user_id=None):
        """Session rows as plain dicts (optionally only one user's)."""
        db = self.Session()
        try:
            q = db.query(UserSession)
            if user_id is not None:
                q = q.filter_by(user_id=user_id)
            return [{"id": r.id, "sid_hash": r.sid_hash, "user_id": r.user_id,
                     "created_at": r.created_at, "last_seen_at": r.last_seen_at,
                     "reauth_at": r.reauth_at} for r in q.order_by(UserSession.id).all()]
        finally:
            db.close()

    def row_for(self, client):
        """The session row the client's cookie points at, or None."""
        sid_hash = hashlib.sha256(_sid(client).encode("utf-8")).hexdigest()
        matches = [r for r in self.rows() if r["sid_hash"] == sid_hash]
        return matches[0] if matches else None

    def update_row(self, row_id, **values):
        db = self.Session()
        try:
            db.query(UserSession).filter_by(id=row_id).update(values)
            db.commit()
        finally:
            db.close()

    def audit(self, action):
        """(actor_id, detail) of every audit entry with this action."""
        db = self.Session()
        try:
            return [(a.actor_id, a.detail) for a in db.query(AuditLog).filter_by(action=action).all()]
        finally:
            db.close()

    def user(self, user_id):
        db = self.Session()
        try:
            return {"is_admin": bool(db.get(User, user_id).is_admin)}
        finally:
            db.close()


@pytest.fixture
def session_env():
    import rate_limit
    import twitch
    import twitch_oauth
    from database import Base, get_db
    from deps import get_current_user
    from routers import admin_backups as admin_backups_router
    from routers import admin_leagues as admin_leagues_router
    from routers import admin_season as admin_season_router
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

    modules = (auth_router, profile_router, admin_users_router, cards_router, twitch, twitch_oauth,
               admin_season_router, admin_leagues_router, admin_backups_router)
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
                     "SESSION_MAX_AGE_SECONDS") + _SESSION_SETTINGS
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


_PRINT_SESSION_MIDDLEWARE = (
    "import json, main\n"
    "kw = [m.kwargs for m in main.app.user_middleware "
    "if m.cls.__name__ == 'SessionMiddleware'][0]\n"
    "print('MW=' + json.dumps({k: v for k, v in kw.items() if k != 'secret_key'}))\n"
    "import sessions\n"
    "print('ABS=' + str(sessions.SESSION_ABSOLUTE_SECONDS))\n"
)


def _middleware_kwargs(result):
    line = next(l for l in result.stdout.splitlines() if l.startswith("MW="))
    return json.loads(line[3:])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DAY = 86400
HOUR = 3600


class _Clock:
    def __init__(self, t):
        self.t = t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    """Patch the single clock helper in backend/sessions.py."""
    import sessions
    c = _Clock(int(time.time()))
    monkeypatch.setattr(sessions, "_now", lambda: c.t)
    return c


@pytest.fixture(autouse=True)
def _clear_login_lockouts():
    from routers import auth as auth_router
    names = ("alice", "bob", "boss", "mallory", "carol")
    for n in names:
        auth_router._failed_login_attempts.pop(n, None)
    yield
    for n in names:
        auth_router._failed_login_attempts.pop(n, None)


def _cookie_payload(value):
    raw = itsdangerous.TimestampSigner(_SECRET).unsign(value.encode("utf-8"))
    return json.loads(base64.b64decode(raw))


def _sid(client):
    return _cookie_payload(client.cookies.get("session"))["sid"]


def _signed_cookie(payload):
    data = base64.b64encode(json.dumps(payload).encode("utf-8"))
    return itsdangerous.TimestampSigner(_SECRET).sign(data).decode("utf-8")


def _replay(env, cookie_value):
    """A fresh client carrying only the given cookie value."""
    c = env.client()
    c.cookies.set("session", cookie_value)
    return c


def _admin_pair(env):
    """A logged-in admin client and a target user id."""
    env.add_user("boss", is_admin=True)
    target = env.add_user("bob")
    return env.login("boss"), target


def _reauth(client):
    resp = client.post("/reauth", json={"password": _PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp


# ---------------------------------------------------------------------------
# Story 1 — Stay Logged In While Active
# ---------------------------------------------------------------------------

def test_player_session_active_weekly_stays_valid_until_absolute_limit(session_env, clock):
    """A player who makes a request once a week stays logged in (GET /me 200) through day 29 (session_env; patch sessions' clock helper)."""
    session_env.add_user()
    client = session_env.login()
    for _ in range(4):  # days 7, 14, 21, 28
        clock.advance(7 * DAY)
        assert client.get("/me").status_code == 200
    clock.advance(1 * DAY)  # day 29
    assert client.get("/me").status_code == 200


def test_player_session_idle_past_idle_limit_returns_401_and_deletes_row(session_env, clock):
    """Failure path: a player idle for 15 days (> SESSION_IDLE_SECONDS default 1209600) gets 401 on GET /me and their user_sessions row is deleted (patch sessions' clock helper)."""
    uid = session_env.add_user()
    client = session_env.login()
    assert len(session_env.rows(uid)) == 1
    clock.advance(15 * DAY)
    assert client.get("/me").status_code == 401
    assert session_env.rows(uid) == []


def test_player_session_past_absolute_limit_returns_401_even_when_active(session_env, clock):
    """Failure path: a player active weekly gets 401 on the first request after day 30 (SESSION_ABSOLUTE_SECONDS default 2592000) and the row is deleted (patch sessions' clock helper)."""
    uid = session_env.add_user()
    client = session_env.login()
    for _ in range(4):
        clock.advance(7 * DAY)
        assert client.get("/me").status_code == 200
    clock.advance(2 * DAY + 1)  # day 30 plus one second, last active 2 days ago
    assert client.get("/me").status_code == 401
    assert session_env.rows(uid) == []


def test_session_limits_checked_against_row_not_cookie(session_env):
    """Limits are checked on the server: with a freshly signed cookie, moving the row's last_seen_at (or created_at) back past the limit in the DB makes GET /me return 401."""
    session_env.add_user("alice")
    session_env.add_user("bob")
    now = int(time.time())

    idle = session_env.login("alice")
    row = session_env.row_for(idle)
    session_env.update_row(row["id"], last_seen_at=now - 15 * DAY)
    assert idle.get("/me").status_code == 401

    old = session_env.login("bob")
    row = session_env.row_for(old)
    session_env.update_row(row["id"], created_at=now - 31 * DAY)
    assert old.get("/me").status_code == 401


def test_last_seen_at_touched_at_most_once_per_touch_interval(session_env, clock):
    """50 GET /me requests within SESSION_TOUCH_SECONDS (default 300) write last_seen_at at most once (count changes to the row; patch sessions' clock helper)."""
    uid = session_env.add_user()
    client = session_env.login()
    seen = [session_env.rows(uid)[0]["last_seen_at"]]
    for _ in range(50):
        clock.advance(5)  # 250 s in total, under the 300 s touch interval
        assert client.get("/me").status_code == 200
        seen.append(session_env.rows(uid)[0]["last_seen_at"])
    changes = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
    assert changes <= 1


def test_last_seen_at_touched_after_touch_interval_elapses(session_env, clock):
    """After more than SESSION_TOUCH_SECONDS have passed (patched clock), the next authenticated request updates last_seen_at to the current time."""
    uid = session_env.add_user()
    client = session_env.login()
    before = session_env.rows(uid)[0]["last_seen_at"]
    clock.advance(301)
    assert client.get("/me").status_code == 200
    after = session_env.rows(uid)[0]["last_seen_at"]
    assert after == clock.t
    assert after > before


# ---------------------------------------------------------------------------
# Story 2 — Logout Ends the Session on the Server
# ---------------------------------------------------------------------------

def test_user_session_model_columns(db):
    """UserSession (user_sessions) has id, sid_hash (unique, 64 chars), user_id (FK users.id, indexed), created_at, last_seen_at, reauth_at (nullable) — new table via create_all (db fixture)."""
    table = UserSession.__table__
    assert table.name == "user_sessions"
    cols = table.c
    assert {"id", "sid_hash", "user_id", "created_at", "last_seen_at", "reauth_at"} <= set(cols.keys())
    assert cols.id.primary_key
    assert cols.sid_hash.unique and cols.sid_hash.type.length == 64 and not cols.sid_hash.nullable
    assert {fk.target_fullname for fk in cols.user_id.foreign_keys} == {"users.id"}
    assert cols.user_id.index
    assert not cols.created_at.nullable and not cols.last_seen_at.nullable
    assert cols.reauth_at.nullable
    # Created by create_all in the db fixture.
    assert db.query(UserSession).count() == 0


def test_login_creates_session_row_and_cookie_holds_only_sid(session_env):
    """POST /login creates one user_sessions row for the user; the decoded cookie payload is exactly {"sid": <token>} (no user_id, username, is_admin or sv)."""
    uid = session_env.add_user()
    client = session_env.login()
    assert len(session_env.rows(uid)) == 1
    payload = _cookie_payload(client.cookies.get("session"))
    assert set(payload) == {"sid"}
    assert isinstance(payload["sid"], str) and len(payload["sid"]) >= 43


def test_session_row_stores_sha256_hash_not_raw_sid(session_env):
    """user_sessions.sid_hash == sha256(sid).hexdigest() (64 hex chars) and no column of any row contains the raw sid from the cookie."""
    session_env.add_user()
    client = session_env.login()
    sid = _sid(client)
    rows = session_env.rows()
    assert len(rows) == 1
    assert rows[0]["sid_hash"] == hashlib.sha256(sid.encode("utf-8")).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", rows[0]["sid_hash"])
    for row in rows:
        assert all(sid not in str(v) for v in row.values())


def test_logout_deletes_row_and_replayed_cookie_returns_401(session_env):
    """POST /logout deletes the current row and clears the cookie; replaying the old cookie value in a second TestClient gets 401 on GET /me."""
    uid = session_env.add_user()
    client = session_env.login()
    old_cookie = client.cookies.get("session")
    resp = client.post("/logout")
    assert resp.status_code == 200
    assert session_env.rows(uid) == []
    assert client.get("/me").status_code == 401
    assert _replay(session_env, old_cookie).get("/me").status_code == 401


def test_logout_leaves_other_sessions_of_same_user_valid(session_env):
    """POST /logout on client A deletes only A's row; client B (same user) still gets 200 on GET /me."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    assert len(session_env.rows(uid)) == 2
    assert a.post("/logout").status_code == 200
    assert len(session_env.rows(uid)) == 1
    assert b.get("/me").status_code == 200


def test_logout_everywhere_deletes_all_session_rows(session_env):
    """POST /logout-everywhere deletes every user_sessions row of the caller; both of the user's clients get 401 afterwards (#119 response and audit entry unchanged)."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    resp = a.post("/logout-everywhere")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert session_env.rows(uid) == []
    assert a.get("/me").status_code == 401
    assert b.get("/me").status_code == 401
    assert [actor for actor, _ in session_env.audit("user_logout_everywhere")] == [uid]


def test_reset_password_deletes_all_session_rows(session_env):
    """POST /reset-password with a valid seeded PasswordResetToken deletes all of the user's rows; every existing client gets 401."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    db = session_env.Session()
    db.add(PasswordResetToken(token="tok-117", user_id=uid, expires_at=int(time.time()) + 3600))
    db.commit()
    db.close()
    resp = session_env.client().post("/reset-password",
                                     json={"token": "tok-117", "new_password": "brand-new-pw"})
    assert resp.status_code == 200, resp.text
    assert session_env.rows(uid) == []
    assert a.get("/me").status_code == 401
    assert b.get("/me").status_code == 401


def test_force_logout_deletes_all_target_session_rows(session_env):
    """POST /users/{id}/force-logout as admin deletes all of the target's rows; the target's client gets 401 and the admin's session still works."""
    admin, target = _admin_pair(session_env)
    victim_a = session_env.login("bob")
    victim_b = session_env.login("bob")
    resp = admin.post(f"/users/{target}/force-logout")
    assert resp.status_code == 200, resp.text
    assert session_env.rows(target) == []
    assert victim_a.get("/me").status_code == 401
    assert victim_b.get("/me").status_code == 401
    assert admin.get("/me").status_code == 200


def test_cookie_with_unknown_sid_returns_401(session_env):
    """Failure path: a validly signed cookie {"sid": "<random token with no row>"} gets 401 on GET /me."""
    import secrets
    session_env.add_user()
    session_env.login()  # a real row exists, but not for this sid
    client = _replay(session_env, _signed_cookie({"sid": secrets.token_urlsafe(32)}))
    assert client.get("/me").status_code == 401


def test_legacy_sv_cookie_without_sid_returns_401(session_env):
    """Failure path: a pre-release #119 cookie {"user_id", "sv"} (signed with the test secret, no sid) gets 401 on GET /me."""
    uid = session_env.add_user()
    session_env.login()
    client = _replay(session_env, _signed_cookie({"user_id": uid, "sv": 0}))
    assert client.get("/me").status_code == 401


def test_twitch_connection_with_deleted_session_row_returns_401(session_env):
    """Failure path: GET /twitch/connection (session cookie, issue #160; replaced the retired POST /twitch/link-code here) gets the same checks — after the session row is deleted it returns 401."""
    uid = session_env.add_user()
    client = session_env.login()
    assert client.get("/twitch/connection").status_code == 200
    db = session_env.Session()
    db.query(UserSession).filter_by(user_id=uid).delete()
    db.commit()
    db.close()
    assert client.get("/twitch/connection").status_code == 401


def test_deck_with_deleted_session_row_treated_as_logged_out(session_env):
    """GET /deck with a cookie whose row was deleted returns the logged-out counts (session_user_or_none returns None)."""
    from models import Card, Player
    uid = session_env.add_user()
    db = session_env.Session()
    db.add(Player(id=501, name="P1"))
    db.add(Card(player_id=501, owner_id=uid, card_type="common", is_active=False, generation=1))
    db.commit()
    db.close()
    client = session_env.login()
    assert client.get("/deck").json()["common"] == 0
    db = session_env.Session()
    db.query(UserSession).filter_by(user_id=uid).delete()
    db.commit()
    db.close()
    assert client.get("/deck").json() == {"common": 1, "rare": 1, "epic": 1, "legendary": 1}


# ---------------------------------------------------------------------------
# Story 3 — New Session ID on Login and Privilege Change
# ---------------------------------------------------------------------------

def test_login_with_existing_valid_cookie_issues_new_sid(session_env):
    """POST /login from a client that already holds a valid session creates a new row and a new sid in the cookie."""
    uid = session_env.add_user()
    client = session_env.login()
    old_sid = _sid(client)
    old_cookie = client.cookies.get("session")
    old_row = session_env.row_for(client)
    assert client.post("/login", json={"username": "alice", "password": _PASSWORD}).status_code == 200
    new_sid = _sid(client)
    assert new_sid != old_sid
    new_row = session_env.row_for(client)
    assert new_row is not None and new_row["id"] != old_row["id"]
    assert client.get("/me").status_code == 200
    # The replaced session of this browser is ended, not left behind.
    assert [r["id"] for r in session_env.rows(uid)] == [new_row["id"]]
    assert _replay(session_env, old_cookie).get("/me").status_code == 401


def test_register_creates_session_row_and_sid_cookie(session_env):
    """POST /register creates a user_sessions row for the new user and sets a {"sid"} cookie; GET /me returns 200."""
    client = session_env.client()
    resp = client.post("/register", json={"username": "newbie", "email": "newbie@example.com",
                                          "password": _PASSWORD})
    assert resp.status_code == 200, resp.text
    assert set(_cookie_payload(client.cookies.get("session"))) == {"sid"}
    me = client.get("/me")
    assert me.status_code == 200
    assert len(session_env.rows(me.json()["user_id"])) == 1


def test_change_password_rotates_current_sid_and_deletes_others(session_env):
    """PUT /profile/password gives the requester a new sid (cookie value changes, old cookie replayed gets 401), keeps the requester logged in, and deletes the user's other rows (client B gets 401)."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    old_sid = _sid(a)
    old_cookie = a.cookies.get("session")
    resp = a.put("/profile/password", json={"current_password": _PASSWORD,
                                            "new_password": "brand-new-pw"})
    assert resp.status_code == 200, resp.text
    assert _sid(a) != old_sid
    assert a.get("/me").status_code == 200
    assert _replay(session_env, old_cookie).get("/me").status_code == 401
    assert b.get("/me").status_code == 401
    rows = session_env.rows(uid)
    assert len(rows) == 1 and rows[0]["id"] == session_env.row_for(a)["id"]


def test_change_password_wrong_current_password_keeps_all_sessions(session_env):
    """Failure path: PUT /profile/password with a wrong current password returns 401; the sid and every row of the user are unchanged."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    old_sid = _sid(a)
    before = session_env.rows(uid)
    resp = a.put("/profile/password", json={"current_password": "wrong-password",
                                            "new_password": "brand-new-pw"})
    assert resp.status_code == 401
    assert _sid(a) == old_sid
    assert [r["id"] for r in session_env.rows(uid)] == [r["id"] for r in before]
    assert a.get("/me").status_code == 200
    assert b.get("/me").status_code == 200


def test_toggle_admin_deletes_target_sessions(session_env):
    """POST /users/{id}/toggle-admin (by an admin with a recent /reauth) deletes all of the target's rows; the target's client gets 401 (patch sessions' clock helper only if needed)."""
    admin, target = _admin_pair(session_env)
    victim = session_env.login("bob")
    _reauth(admin)
    # Issue #150: the toggle also needs the typed confirmation.
    resp = admin.post(f"/users/{target}/toggle-admin", params={"confirm": "CHANGE ADMIN"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_admin"] is True
    assert session_env.rows(target) == []
    assert victim.get("/me").status_code == 401
    # Logging in again starts a fresh session with the new role's limits.
    again = session_env.login("bob")
    assert again.get("/me").json()["is_admin"] is True


def test_toggle_admin_non_admin_returns_403_and_target_sessions_kept(session_env):
    """Failure path: POST /users/{id}/toggle-admin as a non-admin returns 403 and the target's rows are untouched (client still 200 on GET /me)."""
    session_env.add_user("mallory")
    target = session_env.add_user("bob")
    mallory = session_env.login("mallory")
    victim = session_env.login("bob")
    _reauth(mallory)  # a recent re-auth does not make a non-admin an admin
    assert mallory.post(f"/users/{target}/toggle-admin").status_code == 403
    assert len(session_env.rows(target)) == 1
    assert session_env.user(target)["is_admin"] is False
    assert victim.get("/me").status_code == 200


def test_cookie_named_host_session_under_https_only(tmp_path):
    """With HTTPS_ONLY=true, main's SessionMiddleware uses session_cookie "__Host-session", https_only=True, path "/", same_site "lax" and no domain (subprocess `import main`, inspect main.app.user_middleware kwargs)."""
    result = _run_import_main(tmp_path, {}, code=_PRINT_SESSION_MIDDLEWARE)
    assert result.returncode == 0, result.stderr[-2000:]
    kw = _middleware_kwargs(result)
    assert kw["session_cookie"] == "__Host-session"
    assert kw["https_only"] is True
    assert kw.get("path", "/") == "/"
    assert kw["same_site"] == "lax"
    assert kw.get("domain") is None


def test_cookie_named_session_without_https_only(tmp_path):
    """Failure path for the prefix: without HTTPS_ONLY (DEBUG=true bypass) the cookie is named "session", since browsers reject __Host- cookies without Secure (subprocess `import main`)."""
    result = _run_import_main(tmp_path, {"HTTPS_ONLY": "false"}, code=_PRINT_SESSION_MIDDLEWARE)
    assert result.returncode == 0, result.stderr[-2000:]
    kw = _middleware_kwargs(result)
    assert kw["session_cookie"] == "session"
    assert kw["https_only"] is False


def test_set_cookie_header_has_host_prefix_attributes(tmp_path):
    """Under HTTPS_ONLY=true, the Set-Cookie header from POST /register on main.app is `__Host-session=...; path=/; ...; secure; httponly; samesite=lax` with no Domain (subprocess: TestClient(main.app, base_url="https://testserver") without the lifespan context)."""
    code = (
        "import database, main\n"
        "from fastapi.testclient import TestClient\n"
        "database.Base.metadata.create_all(database.engine)\n"
        "c = TestClient(main.app, base_url='https://testserver')\n"
        "r = c.post('/register', json={'username': 'cookieuser', 'email': 'c@example.com', "
        "'password': 'secret123'})\n"
        "print('STATUS=' + str(r.status_code))\n"
        "print('SETCOOKIE=' + r.headers.get('set-cookie', ''))\n"
    )
    result = _run_import_main(tmp_path, {}, code=code)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "STATUS=200" in result.stdout, result.stdout
    header = next(l for l in result.stdout.splitlines() if l.startswith("SETCOOKIE="))[10:]
    assert header.startswith("__Host-session=")
    attrs = [a.strip().lower() for a in header.split(";")[1:]]
    assert "path=/" in attrs
    assert "secure" in attrs
    assert "httponly" in attrs
    assert "samesite=lax" in attrs
    assert not any(a.startswith("domain") for a in attrs)


# ---------------------------------------------------------------------------
# Story 4 — Shorter Sessions and Re-Authentication for Admins
# ---------------------------------------------------------------------------

def test_admin_session_within_admin_limits_stays_valid(session_env, clock):
    """An admin making a request every hour stays logged in until just under ADMIN_SESSION_ABSOLUTE_SECONDS (default 43200) (patch sessions' clock helper)."""
    session_env.add_user("boss", is_admin=True)
    admin = session_env.login("boss")
    for _ in range(11):  # hours 1..11
        clock.advance(HOUR)
        assert admin.get("/me").status_code == 200
    clock.advance(HOUR - 1)  # 12 h minus one second
    assert admin.get("/me").status_code == 200


def test_admin_session_idle_three_hours_returns_401(session_env, clock):
    """Failure path: an admin idle for 3 hours (> ADMIN_SESSION_IDLE_SECONDS default 7200) gets 401; a player idle 3 hours still gets 200 (patch sessions' clock helper)."""
    admin_id = session_env.add_user("boss", is_admin=True)
    session_env.add_user("alice")
    admin = session_env.login("boss")
    player = session_env.login("alice")
    clock.advance(3 * HOUR)
    assert admin.get("/me").status_code == 401
    assert session_env.rows(admin_id) == []
    assert player.get("/me").status_code == 200


def test_admin_session_older_than_twelve_hours_returns_401(session_env, clock):
    """Failure path: an admin active every hour gets 401 once the session is older than 12 hours (patch sessions' clock helper)."""
    admin_id = session_env.add_user("boss", is_admin=True)
    admin = session_env.login("boss")
    for _ in range(12):  # hours 1..12
        clock.advance(HOUR)
        assert admin.get("/me").status_code == 200
    clock.advance(1)
    assert admin.get("/me").status_code == 401
    assert session_env.rows(admin_id) == []


def test_reauth_correct_password_sets_reauth_at_and_writes_audit(session_env, clock):
    """POST /reauth {"password"} with the right password returns 200, sets reauth_at on the current row only, and writes an admin_reauth audit entry for the caller."""
    admin_id = session_env.add_user("boss", is_admin=True)
    a = session_env.login("boss")
    b = session_env.login("boss")
    resp = a.post("/reauth", json={"password": _PASSWORD})
    assert resp.status_code == 200, resp.text
    assert session_env.row_for(a)["reauth_at"] == clock.t
    assert session_env.row_for(b)["reauth_at"] is None
    entries = session_env.audit("admin_reauth")
    assert len(entries) == 1
    assert entries[0][0] == admin_id
    assert "ok" in entries[0][1]
    assert _sid(a) not in resp.text


def test_reauth_wrong_password_rejected_counts_toward_lockout_and_audits(session_env):
    """Failure path: POST /reauth with a wrong password is rejected (401), leaves reauth_at unchanged, records a failed login for the username (routers.auth._failed_login_attempts) and writes an admin_reauth failure audit entry."""
    from routers import auth as auth_router
    admin_id = session_env.add_user("boss", is_admin=True)
    admin = session_env.login("boss")
    resp = admin.post("/reauth", json={"password": "wrong-password"})
    assert resp.status_code == 401
    assert session_env.row_for(admin)["reauth_at"] is None
    assert len(auth_router._failed_login_attempts["boss"]) == 1
    entries = session_env.audit("admin_reauth")
    assert len(entries) == 1
    assert entries[0][0] == admin_id and "failed" in entries[0][1]
    # The session itself survives a wrong password.
    assert admin.get("/me").status_code == 200


def test_reauth_locked_out_username_rejected_even_with_correct_password(session_env):
    """Failure path: when the username is locked out (seed _failed_login_attempts to LOGIN_LOCKOUT_THRESHOLD), POST /reauth with the correct password is refused like /login and reauth_at stays unset."""
    from routers import auth as auth_router
    session_env.add_user("boss", is_admin=True)
    admin = session_env.login("boss")
    auth_router._failed_login_attempts["boss"] = [time.time()] * auth_router._LOGIN_LOCKOUT_THRESHOLD
    resp = admin.post("/reauth", json={"password": _PASSWORD})
    login_resp = session_env.client().post("/login", json={"username": "boss", "password": _PASSWORD})
    assert resp.status_code == login_resp.status_code == 429
    assert resp.json()["detail"] == login_resp.json()["detail"]
    assert session_env.row_for(admin)["reauth_at"] is None


def test_reauth_without_session_returns_401(session_env):
    """Failure path: POST /reauth without a session cookie returns 401 and writes no admin_reauth success entry."""
    session_env.add_user("boss", is_admin=True)
    resp = session_env.client().post("/reauth", json={"password": _PASSWORD})
    assert resp.status_code == 401
    assert session_env.audit("admin_reauth") == []


def test_reauth_shares_login_rate_limit():
    """Static check: the /reauth route in backend/routers/auth.py is decorated with @limiter.limit(RATE_LIMIT_LOGIN)."""
    src = (_BACKEND_DIR / "routers" / "auth.py").read_text(encoding="utf-8")
    assert re.search(r'@router\.post\("/reauth"\)\s*\n@limiter\.limit\(RATE_LIMIT_LOGIN\)\s*\ndef reauth\(',
                     src)
    reauth_src = src[src.index("def reauth("):src.index("@router.get(\"/sessions\")")]
    assert "_is_locked_out(" in reauth_src and "_record_failed_login(" in reauth_src


_ENDPOINT_BODIES = {
    "/admin/season/end": {"season_label": "Season 117"},
    "/admin/season/reset": {"force": True},
}


@pytest.mark.parametrize("method,path", _REAUTH_ENDPOINTS)
def test_destructive_admin_endpoint_without_reauth_returns_403(session_env, method, path,
                                                               tmp_path, monkeypatch):
    """Failure path: each listed destructive endpoint, called by a logged-in admin without a recent /reauth, returns 403 {"detail": "reauth_required"} and performs nothing."""
    import database
    db_file = tmp_path / "fantasy.db"
    sqlite3.connect(str(db_file)).close()
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{db_file}")
    admin, target = _admin_pair(session_env)
    url = path.format(league_id=1, filename="fantasy.db.backup-20260101-000000", user_id=target)
    resp = admin.request(method, url, json=_ENDPOINT_BODIES.get(path))
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "reauth_required"}
    # Nothing happened: no admin audit entry, no backup file, target unchanged.
    db = session_env.Session()
    try:
        actions = {a.action for a in db.query(AuditLog).all()}
    finally:
        db.close()
    assert actions <= {"user_login"}
    assert list(tmp_path.glob("fantasy.db.backup-*")) == []
    assert session_env.user(target)["is_admin"] is False


def test_destructive_admin_endpoint_after_reauth_succeeds(session_env, tmp_path, monkeypatch):
    """After POST /reauth, GET /admin/backups (database.DATABASE_URL patched to tmp_path) and POST /admin/season/reset succeed for the admin."""
    import database
    db_file = tmp_path / "fantasy.db"
    sqlite3.connect(str(db_file)).close()
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{db_file}")
    admin, _ = _admin_pair(session_env)
    _reauth(admin)
    listing = admin.get("/admin/backups")
    assert listing.status_code == 200, listing.text
    assert listing.json()["backups"] == []
    # Issue #150: season reset also needs the typed confirmation.
    reset = admin.post("/admin/season/reset", json={"force": True, "confirm": "RESET SEASON"})
    assert reset.status_code == 200, reset.text
    assert reset.json()["status"] == "ok"


def test_reauth_expires_after_admin_reauth_seconds(session_env, clock, tmp_path, monkeypatch):
    """Failure path: 11 minutes after POST /reauth (> ADMIN_REAUTH_SECONDS default 600), a destructive endpoint returns 403 reauth_required again (patch sessions' clock helper)."""
    import database
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'fantasy.db'}")
    admin, _ = _admin_pair(session_env)
    _reauth(admin)
    clock.advance(9 * 60)
    assert admin.get("/admin/backups").status_code == 200
    clock.advance(2 * 60)  # 11 minutes after the re-auth
    resp = admin.get("/admin/backups")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "reauth_required"}


def test_reauth_on_one_session_does_not_cover_another(session_env, tmp_path, monkeypatch):
    """Failure path: reauth_at is per session row — after /reauth on admin client A, admin client B (same user) still gets 403 reauth_required."""
    import database
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'fantasy.db'}")
    session_env.add_user("boss", is_admin=True)
    a = session_env.login("boss")
    b = session_env.login("boss")
    _reauth(a)
    assert a.get("/admin/backups").status_code == 200
    resp = b.get("/admin/backups")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "reauth_required"}


def test_non_destructive_admin_endpoint_works_without_reauth(session_env):
    """Non-destructive admin endpoints (e.g. GET /users, POST /users/{id}/toggle-tester, GET /audit-logs) return 200 for an admin without /reauth."""
    admin, target = _admin_pair(session_env)
    assert admin.get("/users").status_code == 200
    assert admin.post(f"/users/{target}/toggle-tester").status_code == 200
    assert admin.get("/audit-logs").status_code == 200
    assert admin.get("/admin/leagues").status_code == 200


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


def _admin_js():
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted((_REPO_ROOT / "frontend").glob("app-admin*.js")))


def test_frontend_admin_fetch_handles_reauth_required_and_retries_once():
    """Static check: the shared adminFetch() wrapper in frontend/app-admin*.js catches 403 "reauth_required", shows the in-page password prompt, POSTs /reauth, and retries the original request exactly once."""
    js = _admin_js()
    assert len(re.findall(r"function\s+adminFetch\s*\(", js)) == 1
    body = _js_function(js, "adminFetch")
    assert "res.status !== 403" in body
    assert '"reauth_required"' in body
    assert "_promptReauth()" in body
    assert body.count("fetch(url, options)") == 2  # original request + one retry
    assert "while" not in body and "for (" not in body
    prompt = _js_function(js, "_promptReauth")
    assert '"reauthModal"' in prompt and 'classList.remove("hidden")' in prompt
    submit = _js_function(js, "submitReauth")
    assert "${API}/reauth" in submit and 'method: "POST"' in submit


def test_frontend_reauth_prompt_never_uses_confirm_or_prompt():
    """Failure path (static): the re-auth prompt code (adminFetch and its modal helpers) contains no confirm( or prompt( calls; the modal markup exists in frontend/index.html with a password input."""
    js = _admin_js()
    for name in ("adminFetch", "_promptReauth", "_finishReauth", "closeReauthModal", "submitReauth"):
        body = _js_function(js, name)
        assert not re.search(r"(?<![\w.])confirm\(", body), name
        assert not re.search(r"(?<![\w.])prompt\(", body), name
    html = _read("frontend/index.html")
    m = re.search(r'<div class="modal-overlay hidden" id="reauthModal"[^>]*>(.*?)</div>\s*</div>',
                  html, re.S)
    assert m, "reauthModal markup missing"
    assert 'data-close="closeReauthModal"' in html
    assert re.search(r'<input id="reauthPassword" type="password"', m.group(1))
    # Since #158 the prompt is <form id="reauthForm"> and submitReauth() runs from its
    # submit listener (app-admin.js), not from inline onclick/onkeydown handlers.
    assert '<form id="reauthForm"' in m.group(1)
    assert re.search(r'getElementById\("reauthForm"\)\.addEventListener\("submit",[^\n]*submitReauth\(\)', js)


def test_frontend_destructive_admin_calls_use_admin_fetch():
    """Static check: the season end/reset, league purge, backup create/list/download and toggle-admin calls in frontend/app-admin-*.js go through adminFetch(), not bare fetch()."""
    js = _admin_js()
    patterns = (
        r"`\$\{API\}/admin/season/end`",
        r"`\$\{API\}/admin/season/reset`",
        r"`\$\{API\}/admin/leagues/\$\{_purgeTargetLeagueId\}/data`",
        r"`\$\{API\}/admin/backups`",
        # Issue #150: these two carry the typed confirmation as ?confirm=.
        r"`\$\{API\}/admin/backups/\$\{encodeURIComponent\(filename\)\}\?confirm=",
        r"`\$\{API\}/users/\$\{userId\}/toggle-admin\?confirm=",
        r"`\$\{API\}/grant-tokens`",
        r"`\$\{API\}/admin/users/\$\{userId\}\?confirm=",
    )
    for pat in patterns:
        calls = re.findall(r"(\w+)\(" + pat, js)
        assert calls, pat
        assert set(calls) == {"adminFetch"}, (pat, calls)
    # Backups are downloaded through adminFetch, not a plain link the prompt cannot answer.
    assert "download=" not in _js_function(js, "loadBackups")


def test_frontend_reauth_wrong_password_shows_error():
    """Static check: when POST /reauth fails, the re-auth prompt shows the error message (textContent) instead of retrying the action."""
    submit = _js_function(_admin_js(), "submitReauth")
    failure = submit[submit.index("if (!res.ok)"):]
    failure = failure[:failure.index("return;") + len("return;")]
    assert "status.textContent" in failure
    assert "data.detail" in failure
    assert "_finishReauth(true)" not in failure
    assert "innerHTML" not in submit


# ---------------------------------------------------------------------------
# Story 5 — See and End My Sessions
# ---------------------------------------------------------------------------

def test_get_sessions_lists_callers_sessions_with_current_flag(session_env):
    """GET /sessions returns [{"id", "created_at", "last_seen_at", "current"}] for the caller only (two own clients + another user's client => 2 rows), with current=True on exactly the requesting device."""
    uid = session_env.add_user("alice")
    session_env.add_user("bob")
    a = session_env.login("alice")
    b = session_env.login("alice")
    session_env.login("bob")
    resp = a.get("/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for item in data:
        assert set(item) == {"id", "created_at", "last_seen_at", "current"}
    assert {item["id"] for item in data} == {r["id"] for r in session_env.rows(uid)}
    current = [item for item in data if item["current"]]
    assert len(current) == 1 and current[0]["id"] == session_env.row_for(a)["id"]
    other = b.get("/sessions").json()
    assert [i["id"] for i in other if i["current"]] == [session_env.row_for(b)["id"]]


def test_get_sessions_never_returns_sid_or_hash(session_env):
    """GET /sessions response contains neither the raw sid nor sid_hash (no sid/sid_hash keys and neither value anywhere in the response text)."""
    session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    resp = a.get("/sessions")
    assert resp.status_code == 200
    for item in resp.json():
        assert "sid" not in item and "sid_hash" not in item
    for client in (a, b):
        assert _sid(client) not in resp.text
    for row in session_env.rows():
        assert row["sid_hash"] not in resp.text


def test_get_sessions_without_login_returns_401(session_env):
    """Failure path: GET /sessions without a session returns 401."""
    assert session_env.client().get("/sessions").status_code == 401


def test_delete_session_ends_one_own_session(session_env):
    """DELETE /sessions/{handle} for the caller's other device deletes that row; that client gets 401 and the caller stays logged in."""
    uid = session_env.add_user()
    a = session_env.login()
    b = session_env.login()
    handle = session_env.row_for(b)["id"]
    resp = a.delete(f"/sessions/{handle}")
    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in session_env.rows(uid)] == [session_env.row_for(a)["id"]]
    assert b.get("/me").status_code == 401
    assert a.get("/me").status_code == 200


def test_delete_session_other_users_handle_returns_404(session_env):
    """Failure path: DELETE /sessions/{handle} with another user's handle returns 404 and that user's session keeps working."""
    session_env.add_user("alice")
    bob_id = session_env.add_user("bob")
    alice = session_env.login("alice")
    bob = session_env.login("bob")
    handle = session_env.row_for(bob)["id"]
    assert alice.delete(f"/sessions/{handle}").status_code == 404
    assert len(session_env.rows(bob_id)) == 1
    assert bob.get("/me").status_code == 200
    assert alice.delete("/sessions/999999").status_code == 404


def test_frontend_profile_sessions_list_with_sign_out_buttons():
    """Static check: frontend/app-profile.js loads GET /sessions and renders a row per session with a "Sign out" button calling DELETE /sessions/{id}; frontend/index.html places the list next to "Log out everywhere"."""
    js = _read("frontend/app-profile.js")
    load = _js_function(js, "loadSessions")
    assert "fetch(`${API}/sessions`)" in load
    assert "_renderSessions(" in load
    assert "loadSessions()" in _js_function(js, "loadProfile")
    render = _js_function(js, "_renderSessions")
    assert "rows.forEach" in render
    assert 'btn.textContent = "Sign out"' in render
    assert "signOutSession(s.id" in render
    sign_out = _js_function(js, "signOutSession")
    assert "`${API}/sessions/${encodeURIComponent(sessionId)}`" in sign_out
    assert 'method: "DELETE"' in sign_out
    html = _read("frontend/index.html")
    i_logout = html.index('onclick="logoutEverywhere()"')
    i_table = html.index('id="profileSessionsBody"')
    assert 0 < i_table - i_logout < 800


def test_frontend_profile_sessions_list_built_with_textcontent():
    """Failure path (static): the sessions-list renderer in frontend/app-profile.js builds cells with textContent/createElement and never assigns session data through innerHTML."""
    js = _read("frontend/app-profile.js")
    for name in ("loadSessions", "_renderSessions", "signOutSession"):
        assert "innerHTML" not in _js_function(js, name), name
    render = _js_function(js, "_renderSessions")
    assert "document.createElement(\"td\")" in render
    assert "created.textContent" in render and "lastSeen.textContent" in render


def test_cleanup_expired_sessions_deletes_only_expired_rows(db, monkeypatch):
    """The sessions module's expiry cleanup deletes rows past their role's idle or absolute limit and keeps valid player and admin rows (db fixture; patch sessions' clock helper)."""
    import sessions
    now = 2_000_000_000
    monkeypatch.setattr(sessions, "_now", lambda: now)
    player = User(username="p", email="p@example.com", password_hash="x", is_admin=False)
    admin = User(username="a", email="a@example.com", password_hash="x", is_admin=True)
    db.add_all([player, admin])
    db.flush()

    def row(name, user, created_ago, seen_ago):
        db.add(UserSession(sid_hash=hashlib.sha256(name.encode()).hexdigest(), user_id=user.id,
                           created_at=now - created_ago, last_seen_at=now - seen_ago))

    row("player-ok", player, 20 * DAY, 1 * DAY)
    row("player-idle", player, 20 * DAY, 15 * DAY)
    row("player-old", player, 31 * DAY, 1 * HOUR)
    row("admin-ok", admin, 11 * HOUR, 1 * HOUR)
    row("admin-idle", admin, 3 * HOUR, 3 * HOUR)
    row("admin-old", admin, 13 * HOUR, 1 * HOUR)
    row("orphan", User(id=999), 1 * HOUR, 1 * HOUR)
    db.commit()

    deleted = sessions.cleanup_expired(db)
    assert deleted == 5
    kept = {r.sid_hash for r in db.query(UserSession).all()}
    assert kept == {hashlib.sha256(b"player-ok").hexdigest(), hashlib.sha256(b"admin-ok").hexdigest()}


def test_week_maintenance_loop_runs_session_cleanup():
    """Static check: main._week_maintenance_loop (backend/main.py) calls the sessions expiry cleanup inside its try block."""
    src = (_BACKEND_DIR / "main.py").read_text(encoding="utf-8")
    start = src.index("def _week_maintenance_loop")
    body = src[start:src.index("\ndef ", start + 1)]
    try_block = body[body.index("try:"):body.index("except Exception")]
    assert "sessions.cleanup_expired(db)" in try_block
    assert "_SESSION_CLEANUP_INTERVAL" in try_block  # once a day, not every pass


# ---------------------------------------------------------------------------
# Story 6 — Operators Can Tune and Audit the Limits
# ---------------------------------------------------------------------------

_DEFAULT_VALUES = {
    "SESSION_IDLE_SECONDS": "1209600",
    "SESSION_ABSOLUTE_SECONDS": "2592000",
    "SESSION_TOUCH_SECONDS": "300",
    "ADMIN_SESSION_IDLE_SECONDS": "7200",
    "ADMIN_SESSION_ABSOLUTE_SECONDS": "43200",
    "ADMIN_REAUTH_SECONDS": "600",
}


def test_env_example_documents_session_settings_with_defaults():
    """.env.example documents all six settings with defaults: SESSION_IDLE_SECONDS=1209600, SESSION_ABSOLUTE_SECONDS=2592000, SESSION_TOUCH_SECONDS=300, ADMIN_SESSION_IDLE_SECONDS=7200, ADMIN_SESSION_ABSOLUTE_SECONDS=43200, ADMIN_REAUTH_SECONDS=600."""
    env_example = _read(".env.example")
    for name, value in _DEFAULT_VALUES.items():
        assert re.search(rf"^#?\s*{name}={value}\b", env_example, re.M), name
    assert "SESSION_MAX_AGE_SECONDS" in env_example


def test_docs_describe_session_settings_and_accepted_risk():
    """markdown/features/core/auth.md and markdown/features/reference/longer-sessions.md name all six settings and include the accepted-risk note for the 14-day player idle limit (OWASP / NIST references)."""
    for path in ("markdown/features/core/auth.md", "markdown/features/reference/longer-sessions.md"):
        doc = _read(path)
        for name in _SESSION_SETTINGS:
            assert name in doc, (path, name)
        assert "accepted risk" in doc.lower(), path
        assert "OWASP" in doc and "NIST" in doc, path
    feature = _read("markdown/features/reference/longer-sessions.md")
    assert "*(planned)*" not in feature


def test_startup_with_default_session_settings_starts(tmp_path):
    """With none of the six settings set, `import main` succeeds and SessionMiddleware max_age equals the larger absolute limit (2592000) (subprocess)."""
    result = _run_import_main(tmp_path, {}, code=_PRINT_SESSION_MIDDLEWARE)
    assert result.returncode == 0, result.stderr[-2000:]
    assert _middleware_kwargs(result)["max_age"] == 2592000
    assert "ABS=2592000" in result.stdout


@pytest.mark.parametrize("name", _SESSION_SETTINGS)
@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_startup_invalid_session_setting_fails(tmp_path, name, value):
    """Failure path: a non-integer or non-positive value for any of the six settings fails `import main` with a RuntimeError naming the variable (subprocess)."""
    result = _run_import_main(tmp_path, {name: value})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert name in result.stderr


@pytest.mark.parametrize("idle_name,abs_name", [
    ("SESSION_IDLE_SECONDS", "SESSION_ABSOLUTE_SECONDS"),
    ("ADMIN_SESSION_IDLE_SECONDS", "ADMIN_SESSION_ABSOLUTE_SECONDS"),
])
def test_startup_idle_larger_than_absolute_fails(tmp_path, idle_name, abs_name):
    """Failure path: an idle limit larger than its absolute limit fails `import main` with a RuntimeError naming both variables (subprocess)."""
    result = _run_import_main(tmp_path, {idle_name: "50000", abs_name: "40000"})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert idle_name in result.stderr and abs_name in result.stderr


def test_startup_touch_not_smaller_than_admin_idle_fails(tmp_path):
    """Failure path: SESSION_TOUCH_SECONDS >= ADMIN_SESSION_IDLE_SECONDS fails `import main` with a RuntimeError naming SESSION_TOUCH_SECONDS (subprocess)."""
    result = _run_import_main(tmp_path, {"SESSION_TOUCH_SECONDS": "7200",
                                         "ADMIN_SESSION_IDLE_SECONDS": "7200"})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "SESSION_TOUCH_SECONDS" in result.stderr


def test_session_max_age_alias_sets_absolute_limit_with_warning(tmp_path):
    """SESSION_MAX_AGE_SECONDS=1209600 (no SESSION_ABSOLUTE_SECONDS) is accepted as an alias: `import main` succeeds, the player absolute limit is 1209600, and a deprecation warning naming both variables is logged (subprocess)."""
    result = _run_import_main(tmp_path, {"SESSION_MAX_AGE_SECONDS": "1209600"},
                              code=_PRINT_SESSION_MIDDLEWARE)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ABS=1209600" in result.stdout
    assert _middleware_kwargs(result)["max_age"] == 1209600
    warning = next(l for l in result.stderr.splitlines() if "deprecated" in l)
    assert "SESSION_MAX_AGE_SECONDS" in warning and "SESSION_ABSOLUTE_SECONDS" in warning


def test_session_max_age_alias_invalid_value_fails_startup(tmp_path):
    """Failure path: an invalid SESSION_MAX_AGE_SECONDS alias value (e.g. "abc") still fails `import main` with a RuntimeError naming the variable (subprocess)."""
    result = _run_import_main(tmp_path, {"SESSION_MAX_AGE_SECONDS": "abc"})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "SESSION_MAX_AGE_SECONDS" in result.stderr
