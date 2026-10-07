"""
Tests for plan-issue-150-steam-login.md (resolves GitHub issue #150).

Steam sign-in through Steam OpenID 2.0, gated by a new `LOGIN_METHOD` env var
(`password` default / `both` / `steam_signup`): `GET /auth/steam/start`,
`GET /auth/steam/callback`, `POST /auth/steam/signup`, `POST /profile/steam/unlink`,
`users.steam_id` and `users.is_demo` (migration 033), Link/Unlink Steam on Profile,
Steam re-auth for accounts without a password, `SEED_ADMIN_STEAM_IDS`, and a typed
`confirm` field on destructive admin actions. One class per user story; one test per
acceptance criterion plus the primary failure path.

Developer notes
---------------

  Decisions applied (see the plan's "Decisions" section)
    - `POST /grant-tokens` now has `require_recent_reauth` plus the typed confirmation.
    - Backup download takes the confirmation as `?confirm=<phrase>`; every covered
      route accepts `confirm` as a query parameter or a JSON body field.
    - `users.is_demo` (migration 033) marks demo accounts: never admin, never Steam.
    - `DELETE /admin/users/{id}` is the sixth typed-confirmation action.
    - `LOGIN_METHOD=steam` (#172, not built) is logged and treated as `steam_signup`.
    - `POST /reauth` for an account without a password answers 409 use_steam_reauth.

  No network
    - Every call to steamcommunity.com is mocked: `_mock_steam` patches
      `steam_openid._requests.post`. Never hit Steam.
    - `_id_res_params(steam64, state, return_to, **overrides)` builds a valid
      positive assertion; tests forge one field at a time, or pass `drop=` to remove one.

  Reuse
    - `_Web` / `_params` / `_acting` from tests/test_issue_160 (underscore names only,
      so pytest doesn't collect the other module's tests twice). The `web` fixture is
      copied here with the Steam, profile, season and backup routers added.
"""

import hashlib
import json
import logging
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

# Registers every existing table on Base before the conftest db fixture runs
# create_all. New models/modules are imported inside tests.
import models  # noqa: F401

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"

_BASE_URL = "http://localhost:8000"
_CALLBACK = f"{_BASE_URL}/auth/steam/callback"
_STEAM_OPENID = "https://steamcommunity.com/openid/login"
_NS = "http://specs.openid.net/auth/2.0"
_STEAM64 = "76561198000000001"
_STEAM32 = int(_STEAM64) - 76561197960265728  # 39734273
_OTHER_STEAM64 = "76561198000000002"
_STATE = "test-state-value-abc123"
_PASSWORD = "secret160"     # _Web.add_user's password (tests/test_issue_160)
_SESSION_SECRET = "test-session-secret-150"
_STATE_COOKIE = "kc_steam_state"      # localhost name (no __Host- prefix)
_SIGNUP_COOKIE = "kc_steam_signup"
_SIG = "c2lnbmF0dXJlLWRvLW5vdC1sb2c="
_ASSOC = "assoc-HANDLE-150"


# ---------------------------------------------------------------------------
# OpenID helpers (no network)
# ---------------------------------------------------------------------------

def _nonce(now=None, suffix="aBcD1234"):
    """A Steam-style response_nonce: ISO-8601 UTC timestamp followed by random text."""
    ts = time.gmtime(now if now is not None else time.time())
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", ts) + suffix


def _return_to(state=_STATE, base=_CALLBACK):
    return f"{base}?{urlencode({'state': state})}"


def _id_res_params(steam64=_STEAM64, state=_STATE, return_to=None, *, now=None,
                   overrides=None, drop=()):
    """A valid positive assertion (openid.mode=id_res) as Steam would send it to the
    callback. Forge one field with `overrides`, remove fields with `drop`. The state
    is carried both in return_to and as a plain callback query parameter. Each call
    gets a fresh nonce suffix so two sign-ins in one test are not replays."""
    return_to = return_to if return_to is not None else _return_to(state)
    claimed = f"https://steamcommunity.com/openid/id/{steam64}"
    params = {
        "state": state,
        "openid.ns": _NS,
        "openid.mode": "id_res",
        "openid.op_endpoint": _STEAM_OPENID,
        "openid.claimed_id": claimed,
        "openid.identity": claimed,
        "openid.return_to": return_to,
        "openid.response_nonce": _nonce(now, suffix=secrets.token_hex(6)),
        "openid.assoc_handle": _ASSOC,
        "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,"
                         "response_nonce,assoc_handle",
        "openid.sig": _SIG,
    }
    params.update(overrides or {})
    for key in drop:
        params.pop(key, None)
    return params


class _FakeResponse:
    def __init__(self, status_code=200, text="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n",
                 headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def _mock_steam(monkeypatch, *, text="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n",
                status=200, raises=None, headers=None):
    """Patch the check_authentication POST. Returns the list of recorded calls
    ({"url", "data", "kwargs"}) so tests can assert the hard-coded URL, the exact
    fields sent, timeout=10, allow_redirects=False and that verify is not disabled."""
    import steam_openid
    calls = []

    def fake_post(url, data=None, **kwargs):
        calls.append({"url": url, "data": dict(data or {}), "kwargs": kwargs})
        if raises is not None:
            raise raises
        return _FakeResponse(status, text, headers)

    target = getattr(steam_openid, "_requests", None) or steam_openid.requests
    monkeypatch.setattr(target, "post", fake_post)
    return calls


def _params(location):
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


@pytest.fixture
def mode(monkeypatch):
    """Set LOGIN_METHOD for a test: `mode("both")`. login_mode reads it at call time."""
    def _set(value):
        monkeypatch.setenv("LOGIN_METHOD", value)
        monkeypatch.setenv("APP_BASE_URL", _BASE_URL)
    monkeypatch.delenv("SEED_ADMIN_STEAM_IDS", raising=False)
    return _set


# ---------------------------------------------------------------------------
# App fixture and flow helpers
# ---------------------------------------------------------------------------

from tests.test_issue_160_twitch_account_connection_oidc import _Web, _acting  # noqa: E402


@pytest.fixture
def web():
    import rate_limit
    import steam_openid
    import twitch_oauth
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from starlette.middleware.sessions import SessionMiddleware
    from database import Base, get_db
    from routers import admin_backups as admin_backups_router
    from routers import admin_season as admin_season_router
    from routers import admin_users as admin_users_router
    from routers import auth as auth_router
    from routers import profile as profile_router

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    modules = (auth_router, steam_openid, profile_router, twitch_oauth, admin_users_router,
               admin_season_router, admin_backups_router)
    limiters = {id(rate_limit.limiter): rate_limit.limiter}
    for m in modules:
        if hasattr(m, "limiter"):
            limiters[id(m.limiter)] = m.limiter
    was_enabled = {k: lim.enabled for k, lim in limiters.items()}
    for lim in limiters.values():
        lim.enabled = False
    auth_router._failed_login_attempts.clear()
    auth_router._last_forgot_password_request.clear()

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET, same_site="lax")
    app.state.limiter = rate_limit.limiter
    for m in modules:
        app.include_router(m.router)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield _Web(app, Session)
    finally:
        for k, lim in limiters.items():
            lim.enabled = was_enabled[k]
        engine.dispose()


def _add(web, username="alice", **fields):
    """A user with arbitrary columns (no password unless given)."""
    from models import User
    db = web.Session()
    try:
        fields.setdefault("tokens", 5)
        fields.setdefault("created_at", int(time.time()))
        user = User(username=username, **fields)
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def _user(web, user_id):
    from models import User
    return web.get(User, user_id)


def _user_by_name(web, username):
    from models import User
    rows = web.rows(User, username=username)
    return rows[0] if rows else None


def _count(web, model, **filters):
    return len(web.rows(model, **filters))


def _start(client, purpose="login", **extra):
    return client.get("/auth/steam/start", params={"purpose": purpose, **extra},
                      follow_redirects=False)


def _state_from(resp):
    assert resp.status_code == 303, resp.text
    location = resp.headers["location"]
    assert location.startswith(_STEAM_OPENID + "?"), location
    return _params(_params(location)["openid.return_to"])["state"]


def _callback(client, params):
    return client.get("/auth/steam/callback", params=params, follow_redirects=False)


def _round_trip(client, monkeypatch, steam64=_STEAM64, purpose="login", **extra):
    """Start + mocked Steam + callback. Returns (callback response, check calls)."""
    state = _state_from(_start(client, purpose, **extra))
    calls = _mock_steam(monkeypatch)
    return _callback(client, _id_res_params(steam64, state)), calls


def _plant(web, client, *, purpose="login", user_id=None, state=_STATE, expires_in=600,
           used=False, cookie=True, return_tab=None):
    """A sign-in attempt row for `state`, and (optionally) the matching state cookie."""
    from models import SteamLoginState
    db = web.Session()
    try:
        now = int(time.time())
        db.add(SteamLoginState(state_hash=hashlib.sha256(state.encode()).hexdigest(),
                               purpose=purpose, user_id=user_id, return_tab=return_tab,
                               expires_at=now + expires_in, used_at=now if used else None))
        db.commit()
    finally:
        db.close()
    if cookie:
        client.cookies.set(_STATE_COOKIE, state)


def _location(resp):
    assert resp.status_code in (302, 303, 307), resp.text
    return resp.headers["location"]


def _key(resp, tab):
    location = _location(resp)
    prefix = f"/#{tab}?steam="
    assert location.startswith(prefix), location
    return location[len(prefix):]


def _signup(web, client, monkeypatch, steam64=_STEAM64, username="newbie"):
    """A new Steam player all the way to a session. Returns the signup response."""
    resp, _ = _round_trip(client, monkeypatch, steam64)
    assert _key(resp, "welcome") == "choose_name"
    resp = client.post("/auth/steam/signup", json={"username": username})
    assert resp.status_code == 200, resp.text
    return resp


def _assert_no_sign_in(web, client, users_before):
    from models import SteamPendingSignup, User, UserSession
    assert client.get("/me").status_code == 401
    assert _count(web, User) == users_before
    assert _count(web, UserSession) == 0
    assert _count(web, SteamPendingSignup) == 0


def _forged(web, monkeypatch, *, steam64=_STEAM64, state=_STATE, return_to=None, **kw):
    """Plant a valid attempt, mock Steam as valid, and send one forged assertion.
    Returns (response, check calls, client)."""
    client = web.client()
    _plant(web, client, state=state)
    calls = _mock_steam(monkeypatch)
    resp = _callback(client, _id_res_params(steam64, state, return_to, **kw))
    return resp, calls, client


def _expect_failed(web, resp, client, keys=("failed",)):
    assert _key(resp, "login") in keys
    _assert_no_sign_in(web, client, 0)


def _admin_client(web, username="boss"):
    web.add_user(username, is_admin=True)
    return web.login(username)


def _function_source(src, name):
    m = re.search(r"function\s+%s\s*\(" % re.escape(name), src)
    assert m, f"{name}() not found"
    start = src.index("{", m.end())
    depth, i = 0, start
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():i + 1]
        i += 1


def _read(name):
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


def _steam_ui(login_method, me):
    """Run app-auth.js's pure steamUiState() under Node; None when Node is missing."""
    node = shutil.which("node")
    if node is None:
        return None
    src = _function_source(_read("app-auth.js"), "steamUiState")
    code = (src + "\nconsole.log(JSON.stringify(steamUiState("
            + json.dumps(login_method) + ", " + json.dumps(me) + ")));")
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _main_client():
    import main
    from fastapi.testclient import TestClient
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# Story 1 — Sign In with Steam
# ---------------------------------------------------------------------------

class TestSignInWithSteam:
    """Story: Sign In with Steam."""

    # --- Login page ---

    def test_login_page_shows_sign_in_with_steam_full_page_redirect(self):
        """AC: in both/steam_signup modes the login page shows Sign in with Steam as a full-page navigation to steamcommunity.com (no pop-up, no iframe)."""
        html = _read("index.html")
        auth = _read("app-auth.js")
        assert 'id="steamLoginBlock"' in html
        assert "Sign in with Steam" in html
        start = _function_source(auth, "startSteamLogin")
        assert "window.location.href" in start and "/auth/steam/start?purpose=login" in start
        for text in (html, auth):
            assert "window.open" not in text
            assert "<iframe" not in text.lower()
        assert "steamcommunity.com/public" not in html  # no hotlinked Steam assets
        for method in ("both", "steam_signup"):
            ui = _steam_ui(method, None)
            if ui is None:
                return
            assert ui["steamSignIn"] is True

    def test_login_page_shows_anti_phishing_line(self):
        """AC: the login page says "Sign-in happens on steamcommunity.com. Kana Cards never asks for your Steam password."."""
        html = _read("index.html")
        block = html[html.index('id="steamLoginBlock"'):]
        block = block[:block.index("</div>")]
        assert ("Sign-in happens on steamcommunity.com. Kana Cards never asks for your "
                "Steam password.") in block

    def test_login_page_hides_steam_button_in_password_mode(self, db, monkeypatch):
        """Failure path: in password mode the frontend shows no Sign in with Steam (mode exposed without leaking anything else)."""
        import main
        monkeypatch.delenv("LOGIN_METHOD", raising=False)
        cfg = main.get_config(db=db)
        assert cfg["login_method"] == "password"
        assert not any("steam_id" in k for k in cfg)
        html = _read("index.html")
        tag = re.search(r'<div[^>]*id="steamLoginBlock"[^>]*>', html).group(0)
        assert "display:none" in tag.replace(" ", "")
        ui = _steam_ui("password", None)
        if ui is not None:
            assert ui["steamSignIn"] is False
            assert ui["passwordRegistration"] is True

    # --- Start ---

    def test_steam_start_login_stores_hashed_state_and_redirects(self, web, mode):
        """AC: GET /auth/steam/start?purpose=login stores sha256(state) with purpose, optional user id and a 10-minute expiry, and 303-redirects to https://steamcommunity.com/openid/login with mode=checkid_setup, ns, identifier_select identity/claimed_id."""
        from models import SteamLoginState
        mode("both")
        before = int(time.time())
        resp = _start(web.client())
        state = _state_from(resp)
        p = _params(resp.headers["location"])
        assert p["openid.mode"] == "checkid_setup"
        assert p["openid.ns"] == _NS
        select = "http://specs.openid.net/auth/2.0/identifier_select"
        assert p["openid.identity"] == select and p["openid.claimed_id"] == select
        rows = web.rows(SteamLoginState)
        assert len(rows) == 1
        row = rows[0]
        assert row.state_hash == hashlib.sha256(state.encode()).hexdigest()
        assert row.state_hash != state
        assert row.purpose == "login" and row.user_id is None and row.used_at is None
        assert before + 600 <= row.expires_at <= int(time.time()) + 600

    def test_steam_start_sets_host_prefixed_state_cookie(self, web, mode, monkeypatch):
        """AC: the state is set in `__Host-kc_steam_state` (Secure, HttpOnly, SameSite=Lax, max-age 600) on an HTTPS APP_BASE_URL."""
        mode("both")
        monkeypatch.setenv("APP_BASE_URL", "https://cards.example.com")
        resp = _start(web.client())
        state = _state_from(resp)
        header = resp.headers["set-cookie"]
        assert header.startswith(f"__Host-kc_steam_state={state};")
        lower = header.lower()
        for attr in ("secure", "httponly", "samesite=lax", "max-age=600", "path=/"):
            assert attr in lower, header
        assert "domain=" not in lower

    def test_steam_start_localhost_cookie_drops_host_prefix_and_secure(self, web, mode, monkeypatch):
        """Assumption: with APP_BASE_URL=http://localhost… the state cookie drops the __Host- prefix and Secure; any other base URL keeps both."""
        mode("both")
        header = _start(web.client()).headers["set-cookie"]
        assert header.startswith(f"{_STATE_COOKIE}=")
        assert "secure" not in header.lower()
        monkeypatch.setenv("APP_BASE_URL", "http://cards.example.com")
        header = _start(web.client()).headers["set-cookie"]
        assert header.startswith("__Host-kc_steam_state=") and "secure" in header.lower()

    def test_steam_start_return_to_and_realm_built_from_app_base_url(self, web, mode):
        """AC: openid.return_to (with the state bound into it) and openid.realm are built from APP_BASE_URL, never from the request Host."""
        mode("both")
        resp = web.client().get("/auth/steam/start", params={"purpose": "login"},
                                headers={"host": "evil.example"}, follow_redirects=False)
        state = _state_from(resp)
        p = _params(resp.headers["location"])
        assert p["openid.return_to"] == _return_to(state)
        assert p["openid.realm"] == _BASE_URL + "/"
        assert "evil.example" not in resp.headers["location"]

    def test_steam_start_rejects_unknown_purpose(self, web, mode):
        """Failure path: purpose other than login/link/reauth stores no state and sets no cookie."""
        from models import SteamLoginState
        mode("both")
        resp = _start(web.client(), "admin")
        assert resp.status_code == 400
        assert "set-cookie" not in resp.headers
        assert _count(web, SteamLoginState) == 0

    # --- Callback: one forged-input test per check ---

    def test_steam_callback_valid_assertion_accepted(self, web, mode, monkeypatch):
        """AC: a fully valid id_res assertion with a matching cookie/state and is_valid:true signs in (baseline for every forged-input test below)."""
        mode("both")
        uid = _add(web, "steamer", steam_id=_STEAM64)
        resp, calls, client = _forged(web, monkeypatch)
        assert _location(resp) == "/"
        assert len(calls) == 1
        me = client.get("/me")
        assert me.status_code == 200 and me.json()["user_id"] == uid

    @pytest.mark.parametrize("overrides,drop", [
        ({"openid.ns": "http://specs.openid.net/auth/1.1"}, ()),
        ({}, ("openid.ns",)),
        ({"openid.mode": "cancel"}, ()),
        ({"openid.mode": "setup_needed"}, ()),
        ({"openid.mode": "check_authentication"}, ()),
        ({}, ("openid.mode",)),
    ])
    def test_steam_callback_wrong_ns_or_mode_fails(self, web, mode, monkeypatch, overrides, drop):
        """AC check: openid.ns must be the OpenID 2.0 namespace and openid.mode id_res; cancel, setup_needed or a missing mode is a failed sign-in (redirect steam=failed, no session, no account, no check_authentication POST needed)."""
        mode("both")
        resp, calls, client = _forged(web, monkeypatch, overrides=overrides, drop=drop)
        _expect_failed(web, resp, client, keys=("failed", "cancelled"))
        assert calls == []

    @pytest.mark.parametrize("endpoint", [
        "https://evil.example/openid/login",
        "http://steamcommunity.com/openid/login",
        "https://steamcommunity.com/openid/login/",
        "https://steamcommunity.com.evil.example/openid/login",
    ])
    def test_steam_callback_foreign_op_endpoint_fails(self, web, mode, monkeypatch, endpoint):
        """AC check: openid.op_endpoint must be exactly https://steamcommunity.com/openid/login; anything else fails, and the check_authentication POST still targets only the hard-coded URL."""
        mode("both")
        resp, calls, client = _forged(web, monkeypatch, overrides={"openid.op_endpoint": endpoint})
        _expect_failed(web, resp, client)
        assert all(c["url"] == _STEAM_OPENID for c in calls)
        assert calls == []

    @pytest.mark.parametrize("claimed", [
        "https://steamcommunity.com/openid/id/7656119800000000",      # 16 digits
        "https://steamcommunity.com/openid/id/765611980000000011",    # 18 digits
        "http://steamcommunity.com/openid/id/76561198000000001",      # http
        "https://evil.example/openid/id/76561198000000001",
        "https://steamcommunity.com/openid/id/76561198000000001/",
        "https://steamcommunity.com/openid/id/76561198000000001\n",
    ])
    def test_steam_callback_bad_claimed_id_format_fails(self, web, mode, monkeypatch, claimed):
        """AC check: openid.claimed_id must match ^https://steamcommunity.com/openid/id/(\\d{17})$ (identity forged to the same value)."""
        mode("both")
        resp, calls, client = _forged(web, monkeypatch, overrides={
            "openid.claimed_id": claimed, "openid.identity": claimed})
        _expect_failed(web, resp, client)
        assert calls == []

    def test_steam_callback_claimed_id_identity_mismatch_fails(self, web, mode, monkeypatch):
        """AC check: openid.claimed_id must equal openid.identity (two different well-formed Steam ids fail)."""
        mode("both")
        resp, calls, client = _forged(web, monkeypatch, overrides={
            "openid.identity": f"https://steamcommunity.com/openid/id/{_OTHER_STEAM64}"})
        _expect_failed(web, resp, client)
        assert calls == []

    @pytest.mark.parametrize("return_to", [
        "https://evil.example/auth/steam/callback?state=test-state-value-abc123",
        "http://localhost:8000/auth/steam/callback",                            # no state
        "http://localhost:8000/auth/steam/callback?state=other-state",
        "http://localhost:8000/auth/steam/callback?state=test-state-value-abc123&x=1",
        "http://localhost:8000/auth/twitch/callback?state=test-state-value-abc123",
    ])
    def test_steam_callback_wrong_return_to_fails(self, web, mode, monkeypatch, return_to):
        """AC check: openid.return_to must equal the callback URL built from APP_BASE_URL, including the state."""
        mode("both")
        resp, calls, client = _forged(web, monkeypatch, return_to=return_to)
        _expect_failed(web, resp, client)
        assert calls == []

    def test_steam_callback_missing_state_cookie_fails(self, web, mode, monkeypatch):
        """AC check: no state cookie fails the sign-in even when return_to and the state row are valid."""
        mode("both")
        client = web.client()
        _plant(web, client, cookie=False)
        calls = _mock_steam(monkeypatch)
        resp = _callback(client, _id_res_params())
        _expect_failed(web, resp, client)
        assert calls == []

    def test_steam_callback_cookie_state_mismatch_fails(self, web, mode, monkeypatch):
        """AC check: the state in return_to must equal the cookie value."""
        from models import SteamLoginState
        mode("both")
        client = web.client()
        _plant(web, client)
        client.cookies.set(_STATE_COOKIE, "another-state")
        calls = _mock_steam(monkeypatch)
        resp = _callback(client, _id_res_params())
        _expect_failed(web, resp, client)
        assert calls == []
        assert web.rows(SteamLoginState)[0].used_at is None  # an attacker can't burn it

    def test_steam_callback_unknown_state_fails(self, web, mode, monkeypatch):
        """AC check: a state whose sha256 has no row (cookie and return_to agree but were never issued) fails."""
        mode("both")
        client = web.client()
        client.cookies.set(_STATE_COOKIE, _STATE)
        calls = _mock_steam(monkeypatch)
        _expect_failed(web, _callback(client, _id_res_params()), client)
        assert calls == []

    def test_steam_callback_expired_state_fails(self, web, mode, monkeypatch):
        """AC check: a state row older than 10 minutes fails."""
        mode("both")
        client = web.client()
        _plant(web, client, expires_in=-1)
        calls = _mock_steam(monkeypatch)
        _expect_failed(web, _callback(client, _id_res_params()), client)
        assert calls == []

    def test_steam_callback_used_state_fails_and_is_single_use(self, web, mode, monkeypatch):
        """AC check: the state row is used up on first use and the cookie is deleted; replaying the same callback fails."""
        from models import SteamLoginState
        mode("both")
        _add(web, "steamer", steam_id=_STEAM64)
        client = web.client()
        _plant(web, client)
        _mock_steam(monkeypatch)
        params = _id_res_params()
        first = _callback(client, params)
        assert _location(first) == "/"
        assert web.rows(SteamLoginState)[0].used_at is not None
        cleared = first.headers["set-cookie"]
        assert cleared.startswith(f'{_STATE_COOKIE}=""') or "max-age=0" in cleared.lower()
        replay = web.client()
        replay.cookies.set(_STATE_COOKIE, _STATE)
        resp = _callback(replay, params)
        assert _key(resp, "login") == "failed"
        assert replay.get("/me").status_code == 401

    @pytest.mark.parametrize("missing", [
        "op_endpoint", "claimed_id", "identity", "return_to", "response_nonce", "assoc_handle",
    ])
    def test_steam_callback_signed_list_missing_field_fails(self, web, mode, monkeypatch, missing):
        """AC check: openid.signed must list at least op_endpoint, claimed_id, identity, return_to, response_nonce and assoc_handle."""
        mode("both")
        signed = [f for f in ("signed", "op_endpoint", "claimed_id", "identity", "return_to",
                              "response_nonce", "assoc_handle") if f != missing]
        resp, calls, client = _forged(web, monkeypatch, overrides={"openid.signed": ",".join(signed)})
        _expect_failed(web, resp, client)
        assert calls == []

    @pytest.mark.parametrize("nonce", [
        "2020-01-01T00:00:00Zold",   # far too old
        "not-a-timestamp",
        "",
    ])
    def test_steam_callback_old_or_malformed_nonce_fails(self, web, mode, monkeypatch, nonce):
        """AC check: openid.response_nonce older than 5 minutes (or unparseable) fails."""
        mode("both")
        resp, calls, client = _forged(web, monkeypatch, overrides={"openid.response_nonce": nonce})
        _expect_failed(web, resp, client)
        assert calls == []
        resp, calls, client = _forged(web, monkeypatch, state="state-two", now=time.time() - 301)
        _expect_failed(web, resp, client)

    def test_steam_callback_replayed_nonce_fails(self, web, mode, monkeypatch):
        """AC check: a response_nonce already seen (stored in steam_openid_nonces, unique) fails even with a fresh valid state."""
        from models import SteamOpenIdNonce
        mode("both")
        _add(web, "steamer", steam_id=_STEAM64)
        first = web.client()
        _plant(web, first, state="state-one")
        _mock_steam(monkeypatch)
        params = _id_res_params(state="state-one")
        assert _location(_callback(first, params)) == "/"
        stored = web.rows(SteamOpenIdNonce)
        assert len(stored) == 1
        assert stored[0].nonce_hash == hashlib.sha256(
            params["openid.response_nonce"].encode()).hexdigest()

        second = web.client()
        _plant(web, second, state="state-two")
        calls = _mock_steam(monkeypatch)
        replay = _id_res_params(state="state-two",
                                overrides={"openid.response_nonce": params["openid.response_nonce"]})
        assert _key(_callback(second, replay), "login") == "failed"
        assert second.get("/me").status_code == 401
        assert calls == []

    def test_steam_nonces_pruned_after_a_day(self, db):
        """AC: used nonces are pruned after a day by the daily cleanup."""
        import steam_openid
        from models import SteamLoginState, SteamOpenIdNonce, SteamPendingSignup
        now = 2_000_000_000
        db.add_all([SteamOpenIdNonce(nonce_hash="old", created_at=now - 86401),
                    SteamOpenIdNonce(nonce_hash="new", created_at=now - 100),
                    SteamLoginState(state_hash="a", purpose="login", expires_at=now - 1),
                    SteamLoginState(state_hash="b", purpose="login", expires_at=now + 100),
                    SteamPendingSignup(token_hash="p", steam_id=_STEAM64, expires_at=now - 1),
                    SteamPendingSignup(token_hash="q", steam_id=_STEAM64, expires_at=now + 100)])
        db.commit()
        result = steam_openid.cleanup(db, now)
        assert result == {"states": 1, "nonces": 1, "signups": 1}
        assert [r.nonce_hash for r in db.query(SteamOpenIdNonce).all()] == ["new"]
        assert [r.state_hash for r in db.query(SteamLoginState).all()] == ["b"]
        assert [r.token_hash for r in db.query(SteamPendingSignup).all()] == ["q"]
        import main
        src = open(main.__file__, encoding="utf-8").read()
        assert "steam_openid.cleanup(db" in src

    def test_steam_callback_repeated_openid_parameter_fails(self, web, mode, monkeypatch):
        """AC check: any openid.* parameter that repeats in the query (detected via query_params.multi_items()) fails the sign-in."""
        mode("both")
        client = web.client()
        _plant(web, client)
        calls = _mock_steam(monkeypatch)
        items = list(_id_res_params().items())
        items.append(("openid.claimed_id", f"https://steamcommunity.com/openid/id/{_OTHER_STEAM64}"))
        _expect_failed(web, _callback(client, items), client)
        assert calls == []

    def test_steam_callback_overlong_value_fails(self, web, mode, monkeypatch):
        """AC check: an openid.* value longer than 2048 characters fails."""
        mode("both")
        resp, calls, client = _forged(web, monkeypatch, overrides={"openid.assoc_handle": "a" * 2049})
        _expect_failed(web, resp, client)
        assert calls == []

    def test_steam_callback_query_string_over_8kb_fails(self, web, mode, monkeypatch):
        """AC check: a query string longer than 8 KB fails (each value under 2048)."""
        mode("both")
        padding = {f"openid.ext{i}": "b" * 2000 for i in range(5)}
        resp, calls, client = _forged(web, monkeypatch, overrides=padding)
        _expect_failed(web, resp, client)
        assert calls == []

    def test_steam_check_authentication_request_shape(self, web, mode, monkeypatch):
        """AC check: the server-side POST goes to the hard-coded https://steamcommunity.com/openid/login, sends exactly the received openid.* fields with only openid.mode replaced by check_authentication, timeout=10, allow_redirects=False, TLS verification not disabled."""
        mode("both")
        client = web.client()
        _plant(web, client)
        calls = _mock_steam(monkeypatch)
        params = _id_res_params()
        _callback(client, params)
        assert len(calls) == 1
        call = calls[0]
        assert call["url"] == _STEAM_OPENID
        expected = {k: v for k, v in params.items() if k.startswith("openid.")}
        expected["openid.mode"] = "check_authentication"
        assert call["data"] == expected
        assert call["kwargs"]["timeout"] == 10
        assert call["kwargs"]["allow_redirects"] is False
        assert call["kwargs"].get("verify", True) is True

    @pytest.mark.parametrize("response", [
        {"text": "ns:http://specs.openid.net/auth/2.0\nis_valid:false\n"},
        {"text": "is_valid:true \n"},
        {"text": "xis_valid:true\n"},
        {"text": "is_valid:TRUE\n"},
        {"text": ""},
        {"status": 302, "text": "is_valid:true\n", "headers": {"location": "https://evil.example/"}},
        {"status": 500, "text": "is_valid:true\n"},
    ])
    def test_steam_check_authentication_not_exactly_valid_fails(self, web, mode, monkeypatch, response):
        """AC check: the answer must be 200 and contain a line that is exactly is_valid:true; is_valid:false, near misses, redirects and errors fail closed."""
        mode("both")
        _add(web, "steamer", steam_id=_STEAM64)
        client = web.client()
        _plant(web, client)
        calls = _mock_steam(monkeypatch, **response)
        resp = _callback(client, _id_res_params())
        assert _key(resp, "login") in ("failed", "unavailable")
        assert len(calls) == 1
        assert client.get("/me").status_code == 401

    @pytest.mark.parametrize("exc_name", ["Timeout", "ConnectionError", "SSLError"])
    def test_steam_check_authentication_outage_fails_closed(self, web, mode, monkeypatch, exc_name):
        """AC Steam outage: a timeout or error on the check_authentication POST fails closed with "Steam sign-in is unavailable right now"; no session, no account."""
        import requests
        mode("both")
        client = web.client()
        _plant(web, client)
        _mock_steam(monkeypatch, raises=getattr(requests.exceptions, exc_name)("boom"))
        resp = _callback(client, _id_res_params())
        assert _key(resp, "login") == "unavailable"
        _assert_no_sign_in(web, client, 0)
        assert "Steam sign-in is unavailable right now" in _read("app-auth.js")

    def test_steam_outage_leaves_password_login_and_sessions_working(self, web, mode, monkeypatch):
        """AC Steam outage: password sign-in and existing sessions are unaffected while Steam answers errors."""
        import requests
        mode("both")
        web.add_user("alice")
        existing = web.login("alice", reauth=False)
        client = web.client()
        _plant(web, client)
        _mock_steam(monkeypatch, raises=requests.exceptions.ConnectionError("down"))
        assert _key(_callback(client, _id_res_params()), "login") == "unavailable"
        assert existing.get("/me").status_code == 200
        fresh = web.login("alice", reauth=False)
        assert fresh.get("/me").status_code == 200

    # --- Outcomes ---

    def test_steam_callback_known_steam_id_starts_new_session(self, web, mode, monkeypatch):
        """AC: a known users.steam_id starts a session with a new session id via sessions.start_session and redirects to / with no next= parameter."""
        from models import AuditLog, UserSession
        mode("both")
        uid = web.add_user("alice", steam_id=_STEAM64)
        client = web.login("alice", reauth=False)
        old_cookie = client.cookies.get("session")
        old_rows = {r.sid_hash for r in web.rows(UserSession)}
        resp, _ = _round_trip(client, monkeypatch)
        assert _location(resp) == "/"
        assert "next=" not in _location(resp)
        new_rows = {r.sid_hash for r in web.rows(UserSession)}
        assert len(new_rows) == 1 and not (new_rows & old_rows)
        assert client.cookies.get("session") != old_cookie
        assert client.get("/me").json()["user_id"] == uid
        assert any(a.detail == "method=steam" for a in web.rows(AuditLog, action="user_login"))

    def test_steam_callback_unknown_id_never_matches_by_player_id_username_or_email(self, web, mode, monkeypatch):
        """AC: an unknown Steam id never signs in to an existing account whose player_id equals its Steam32 id (nor by username/email); it creates a pending sign-up instead."""
        from models import SteamPendingSignup
        mode("both")
        web.add_user(_STEAM64, player_id=_STEAM32)   # username equal to the Steam64 id too
        client = web.client()
        resp, _ = _round_trip(client, monkeypatch)
        assert _key(resp, "welcome") == "choose_name"
        assert client.get("/me").status_code == 401
        assert _count(web, SteamPendingSignup) == 1

    def test_steam_callback_unknown_id_creates_pending_signup(self, web, mode, monkeypatch):
        """AC: an unknown Steam id stores a hashed pending sign-up token (15 minutes), sets its cookie and redirects to the display-name step, creating no user."""
        from models import SteamPendingSignup, User
        mode("both")
        client = web.client()
        resp, _ = _round_trip(client, monkeypatch)
        assert _key(resp, "welcome") == "choose_name"
        token = client.cookies.get(_SIGNUP_COOKIE)
        assert token
        rows = web.rows(SteamPendingSignup)
        assert len(rows) == 1
        assert rows[0].token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert rows[0].steam_id == _STEAM64
        assert abs(rows[0].expires_at - (int(time.time()) + 900)) <= 5
        cookie_header = [h for h in resp.headers.get_list("set-cookie") if h.startswith(_SIGNUP_COOKIE)][0]
        assert "max-age=900" in cookie_header.lower() and "httponly" in cookie_header.lower()
        assert _count(web, User) == 0

    def test_steam_signup_creates_account_without_password_or_email(self, web, mode, monkeypatch):
        """AC: POST /auth/steam/signup with a valid username creates the account with steam_id set, no password, no email, player_id = Steam64 - 76561197960265728, then starts the session; the pending row is used up."""
        from models import SteamPendingSignup
        mode("both")
        client = web.client()
        resp = _signup(web, client, monkeypatch, username="newbie")
        assert resp.json()["username"] == "newbie"
        user = _user_by_name(web, "newbie")
        assert user.steam_id == _STEAM64
        assert user.password_hash is None and user.email is None
        assert user.player_id == _STEAM32 == int(_STEAM64) - 76561197960265728
        assert user.is_admin is False
        me = client.get("/me").json()
        assert me["username"] == "newbie" and me["steam_linked"] is True and me["has_password"] is False
        assert web.rows(SteamPendingSignup)[0].used_at is not None
        again = client.post("/auth/steam/signup", json={"username": "second"})
        assert again.status_code == 400

    @pytest.mark.parametrize("username", ["", "a" * 65, "<script>", "taken"])
    def test_steam_signup_invalid_or_taken_username_rejected(self, web, mode, monkeypatch, username):
        """Failure path: sign-up with a username failing the existing username rules, or already taken, creates nothing and keeps the pending row usable."""
        from models import User
        mode("both")
        web.add_user("taken")
        client = web.client()
        resp, _ = _round_trip(client, monkeypatch)
        assert _key(resp, "welcome") == "choose_name"
        bad = client.post("/auth/steam/signup", json={"username": username})
        assert bad.status_code in (409, 422)
        assert _count(web, User) == 1
        assert client.get("/me").status_code == 401
        ok = client.post("/auth/steam/signup", json={"username": "fresh-name"})
        assert ok.status_code == 200, ok.text

    def test_steam_signup_without_valid_pending_token_rejected(self, web, mode, monkeypatch):
        """Failure path: POST /auth/steam/signup with no, unknown or expired (>15 min) pending token creates nothing."""
        from models import SteamPendingSignup, User
        mode("both")
        client = web.client()
        assert client.post("/auth/steam/signup", json={"username": "nobody"}).status_code == 400
        client.cookies.set(_SIGNUP_COOKIE, "never-issued")
        assert client.post("/auth/steam/signup", json={"username": "nobody"}).status_code == 400
        db = web.Session()
        try:
            db.add(SteamPendingSignup(token_hash=hashlib.sha256(b"expired").hexdigest(),
                                      steam_id=_STEAM64, expires_at=int(time.time()) - 1))
            db.commit()
        finally:
            db.close()
        client.cookies.set(_SIGNUP_COOKIE, "expired")
        assert client.post("/auth/steam/signup", json={"username": "nobody"}).status_code == 400
        assert _count(web, User) == 0

    # --- Rate limits, logging, mode gate ---

    @pytest.mark.parametrize("route", ["callback", "start", "signup"])
    def test_steam_routes_rate_limited_per_ip(self, mode, route):
        """AC rate limits: the callback (RATE_LIMIT_STEAM_CALLBACK, default 10/minute), start and sign-up are limited per IP and answer 429 past the limit."""
        import steam_openid
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from starlette.middleware.sessions import SessionMiddleware
        from database import get_db
        from tests.test_issue_157_twitch_extension_policy_compliance import _shared_db
        mode("both")
        assert os.getenv("RATE_LIMIT_STEAM_CALLBACK") or steam_openid.RATE_LIMIT_STEAM_CALLBACK == "10/minute"
        limit = int(steam_openid.RATE_LIMIT_STEAM_CALLBACK.split("/")[0])
        session = _shared_db()
        lim = steam_openid.limiter
        was = lim.enabled
        lim.enabled = True
        lim.reset()
        try:
            app = FastAPI()
            app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET)
            app.state.limiter = lim
            app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
            app.include_router(steam_openid.router)
            app.dependency_overrides[get_db] = lambda: session
            client = TestClient(app)

            def hit():
                if route == "callback":
                    return client.get("/auth/steam/callback", follow_redirects=False)
                if route == "start":
                    return client.get("/auth/steam/start", follow_redirects=False)
                return client.post("/auth/steam/signup", json={"username": "x"})
            for _ in range(limit):
                assert hit().status_code != 429
            assert hit().status_code == 429
        finally:
            lim.enabled = was
            lim.reset()
            session.close()

    def test_steam_callback_query_never_logged(self, web, mode, monkeypatch, caplog):
        """AC logging: no app log record contains the callback query string, signature, nonce or assoc handle; failures log a reason only (ignore httpx/httpcore client-side records)."""
        mode("both")
        _add(web, "steamer", steam_id=_STEAM64)
        caplog.set_level(logging.DEBUG)
        good = _id_res_params(state="state-good")
        client = web.client()
        _plant(web, client, state="state-good")
        _mock_steam(monkeypatch)
        assert _location(_callback(client, good)) == "/"
        bad = _id_res_params(state="state-bad", overrides={"openid.op_endpoint": "https://evil.example/"})
        client = web.client()
        _plant(web, client, state="state-bad")
        _callback(client, bad)
        app_records = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
        assert any("Steam sign-in failed" in r.getMessage() for r in app_records)
        secrets_ = {_SIG, _ASSOC, good["openid.response_nonce"], bad["openid.response_nonce"],
                    "state-good", "state-bad", "openid.", "evil.example"}
        for record in app_records:
            text = record.getMessage()
            for secret in secrets_:
                assert secret not in text, (record.name, text)

    def test_redact_sign_in_query_covers_auth_steam(self):
        """AC logging: RedactSignInQuery strips the query of /auth/steam/* access-log lines (and still covers /auth/twitch/*)."""
        from twitch_oauth import RedactSignInQuery
        f = RedactSignInQuery()
        for path in (f"/auth/steam/callback?openid.sig={_SIG}&state=x", "/auth/twitch/callback?code=abc"):
            record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                                       '%s - "%s %s HTTP/%s" %d',
                                       ("127.0.0.1:5000", "GET", path, "1.1", 303), None)
            assert f.filter(record) is True
            assert record.args[2] == path.split("?")[0] + "?[redacted]"
            assert _SIG not in record.getMessage()
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s %s %s",
                                   ("127.0.0.1:5000", "GET", "/leaderboard?week=1"), None)
        f.filter(record)
        assert record.args[2] == "/leaderboard?week=1"

    def test_steam_callback_failure_redirects_without_account_or_session(self, web, mode, monkeypatch):
        """Failure path: a failed check redirects to /#login?steam=failed, creates no account and starts no session."""
        mode("both")
        client = web.client()
        _plant(web, client)
        _mock_steam(monkeypatch, text="is_valid:false\n")
        resp = _callback(client, _id_res_params())
        assert _location(resp) == "/#login?steam=failed"
        _assert_no_sign_in(web, client, 0)

    @pytest.mark.parametrize("method,path", [
        ("GET", "/auth/steam/start?purpose=login"),
        ("GET", "/auth/steam/callback"),
        ("POST", "/auth/steam/signup"),
        ("POST", "/profile/steam/unlink"),
        ("POST", "/auth/steam/unknown"),
    ])
    def test_steam_routes_404_in_password_mode(self, monkeypatch, method, path):
        """Failure path: with LOGIN_METHOD=password every /auth/steam/* route answers 404 (not 405 from the static mount)."""
        monkeypatch.setenv("LOGIN_METHOD", "password")
        monkeypatch.setenv("APP_BASE_URL", _BASE_URL)
        client = _main_client()
        resp = client.request(method, path, json={"username": "x"} if method == "POST" else None,
                              follow_redirects=False)
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Story 2 — Link Steam to an Existing Account
# ---------------------------------------------------------------------------

class TestLinkSteamToExistingAccount:
    """Story: Link Steam to an Existing Account."""

    def test_profile_shows_link_steam_for_unlinked_player(self):
        """AC: in both/steam_signup modes Profile shows Link Steam for a logged-in player without steam_id (frontend driven by /me steam_linked)."""
        html = _read("index.html")
        assert 'id="steamProfilePanel"' in html and "Link Steam" in html
        profile = _read("app-profile.js")
        assert "steamUiState(" in profile and "/auth/steam/start?purpose=link" in profile
        me = {"steam_linked": False, "has_password": True, "is_demo": False}
        for method in ("both", "steam_signup"):
            ui = _steam_ui(method, me)
            if ui is None:
                return
            assert ui["profileSteamPanel"] and ui["linkSteam"] and not ui["unlinkSteam"]
        assert _steam_ui("password", me)["profileSteamPanel"] is False
        linked = _steam_ui("both", {"steam_linked": True, "has_password": True, "is_demo": False})
        assert not linked["linkSteam"] and linked["unlinkSteam"]
        steam_only = _steam_ui("both", {"steam_linked": True, "has_password": False, "is_demo": False})
        assert not steam_only["unlinkSteam"]
        demo = _steam_ui("both", {"steam_linked": False, "has_password": True, "is_demo": True})
        assert not demo["linkSteam"]

    def test_me_exposes_steam_linked_and_has_password_booleans_only(self, db):
        """AC: /me adds steam_linked and has_password booleans and never returns the Steam id."""
        from models import User
        from routers.profile import me
        user = User(username="alice", steam_id=_STEAM64, password_hash="x", tokens=0)
        db.add(user)
        db.commit()
        data = me(db=db, current_user=_acting(user))
        assert data["steam_linked"] is True and data["has_password"] is True
        assert _STEAM64 not in json.dumps(data)
        assert str(_STEAM32) not in json.dumps(data)

    def test_steam_start_link_without_recent_reauth_redirects_reauth_required(self, web, mode):
        """AC: GET /auth/steam/start?purpose=link without a recent check redirects to Profile with steam=reauth_required and stores no state; Profile opens the password prompt and starts again."""
        from models import SteamLoginState
        mode("both")
        web.add_user("alice")
        client = web.login("alice", reauth=False)
        resp = _start(client, "link")
        assert _key(resp, "profile") == "reauth_required"
        assert _count(web, SteamLoginState) == 0
        profile = _read("app-profile.js")
        assert "reauth_required" in _function_source(_read("app-auth.js"), "handleSteamReturn")
        assert "linkSteam()" in profile

    def test_steam_start_link_binds_state_to_user(self, web, mode):
        """AC: purpose=link with a recent check stores the state row bound to the logged-in user id."""
        from models import SteamLoginState
        mode("both")
        uid = web.add_user("alice")
        client = web.login("alice")
        _state_from(_start(client, "link"))
        rows = web.rows(SteamLoginState)
        assert len(rows) == 1 and rows[0].user_id == uid and rows[0].purpose == "link"

    def test_steam_link_success_sets_steam_id_and_verified_player_id(self, web, mode, monkeypatch):
        """AC: a successful link sets users.steam_id, replaces any self-reported player_id with the Steam32 id, audits steam_linked and redirects to /#profile?steam=<ok key>."""
        from models import AuditLog
        mode("both")
        uid = web.add_user("alice", player_id=12345)
        client = web.login("alice")
        resp, _ = _round_trip(client, monkeypatch, purpose="link")
        assert _location(resp) == "/#profile?steam=linked"
        user = _user(web, uid)
        assert user.steam_id == _STEAM64 and user.player_id == _STEAM32
        audits = web.rows(AuditLog, action="steam_linked")
        assert len(audits) == 1 and audits[0].actor_id == uid
        assert _STEAM64 not in (audits[0].detail or "")

    def test_steam_link_supersedes_other_accounts_player_id_claim(self, web, mode, monkeypatch):
        """AC: another account that self-reported the same player_id has it cleared, audited as player_id_claim_superseded with both user ids."""
        from models import AuditLog
        mode("both")
        other = web.add_user("squatter", player_id=_STEAM32)
        uid = web.add_user("alice")
        client = web.login("alice")
        resp, _ = _round_trip(client, monkeypatch, purpose="link")
        assert _key(resp, "profile") == "linked"
        assert _user(web, other).player_id is None
        assert _user(web, uid).player_id == _STEAM32
        audits = web.rows(AuditLog, action="player_id_claim_superseded")
        assert len(audits) == 1
        assert audits[0].detail == f"user_id={other} verified_user_id={uid} player_id={_STEAM32}"

    def test_admin_lists_superseded_player_id_claims(self, web, mode, monkeypatch):
        """AC: Admin > User Management lists the superseded claims (admin-only endpoint; 403 for players)."""
        mode("both")
        other = web.add_user("squatter", player_id=_STEAM32)
        uid = web.add_user("alice")
        _round_trip(web.login("alice"), monkeypatch, purpose="link")
        admin = _admin_client(web)
        rows = admin.get("/admin/player-id-claims").json()
        assert len(rows) == 1
        row = rows[0]
        assert row["superseded_user_id"] == other and row["superseded_username"] == "squatter"
        assert row["verified_user_id"] == uid and row["verified_username"] == "alice"
        assert row["player_id"] == _STEAM32
        assert web.login("alice", reauth=False).get("/admin/player-id-claims").status_code == 403
        assert "/admin/player-id-claims" in _read("app-admin-users.js")

    def test_steam_link_refused_when_steam_id_on_another_account(self, web, mode, monkeypatch):
        """AC: a Steam id already stored on another account is refused with "This Steam account is linked to another Kana Cards account"; nothing changes on either account."""
        mode("both")
        holder = web.add_user("holder", steam_id=_STEAM64, player_id=_STEAM32)
        uid = web.add_user("alice", player_id=777)
        client = web.login("alice")
        resp, _ = _round_trip(client, monkeypatch, purpose="link")
        assert _key(resp, "profile") == "in_use"
        assert _user(web, uid).steam_id is None and _user(web, uid).player_id == 777
        assert _user(web, holder).steam_id == _STEAM64
        assert "This Steam account is linked to another Kana Cards account" in _read("app-auth.js")

    def test_steam_unlink_clears_steam_id_keeps_player_id(self, web, mode):
        """AC: POST /profile/steam/unlink with a recent check clears steam_id, keeps player_id and audits steam_unlinked."""
        from models import AuditLog
        mode("both")
        uid = web.add_user("alice", steam_id=_STEAM64, player_id=_STEAM32)
        client = web.login("alice")
        resp = client.post("/profile/steam/unlink")
        assert resp.status_code == 200 and resp.json()["changed"] is True
        user = _user(web, uid)
        assert user.steam_id is None and user.player_id == _STEAM32
        assert len(web.rows(AuditLog, action="steam_unlinked")) == 1

    def test_steam_unlink_requires_recent_reauth(self, web, mode):
        """AC: Unlink Steam without a recent check answers 403 reauth_required and changes nothing."""
        mode("both")
        uid = web.add_user("alice", steam_id=_STEAM64)
        client = web.login("alice", reauth=False)
        resp = client.post("/profile/steam/unlink")
        assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"
        assert _user(web, uid).steam_id == _STEAM64

    def test_steam_unlink_refused_for_account_without_password(self, web, mode, monkeypatch):
        """AC: Unlink is refused for an account without a password (it would lock the player out)."""
        mode("both")
        client = web.client()
        _signup(web, client, monkeypatch, username="steamonly")
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth")
        assert _key(resp, "profile") == "reauth_ok"
        resp = client.post("/profile/steam/unlink")
        assert resp.status_code == 409
        assert _user_by_name(web, "steamonly").steam_id == _STEAM64

    def test_update_player_id_409_when_steam_linked(self, db):
        """AC: PUT /profile/player-id answers 409 for an account with a linked Steam id."""
        from fastapi import HTTPException
        from models import User
        from routers.profile import UpdatePlayerIdBody, update_player_id
        user = User(username="alice", steam_id=_STEAM64, player_id=_STEAM32, tokens=0)
        db.add(user)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            update_player_id(UpdatePlayerIdBody(player_id=1), db=db, current_user=_acting(user))
        assert exc.value.status_code == 409
        db.refresh(user)
        assert user.player_id == _STEAM32

    def test_update_player_id_still_works_without_steam(self, db):
        """AC: accounts without Steam can still set player_id via PUT /profile/player-id as today."""
        from models import User
        from routers.profile import UpdatePlayerIdBody, update_player_id
        user = User(username="alice", tokens=0)
        db.add(user)
        db.commit()
        result = update_player_id(UpdatePlayerIdBody(player_id=4242), db=db, current_user=_acting(user))
        assert result["player_id"] == 4242
        db.refresh(user)
        assert user.player_id == 4242

    def test_profile_s17_reminder_for_password_players_without_steam(self):
        """AC: from the start of S17 Profile shows "Link Steam now. Password sign-in will end in a later update." to password players without Steam."""
        html = _read("index.html")
        assert "Link Steam now. Password sign-in will end in a later update." in html
        me = {"steam_linked": False, "has_password": True, "is_demo": False}
        ui = _steam_ui("steam_signup", me)
        if ui is None:
            return
        assert ui["linkReminder"] is True
        assert _steam_ui("both", me)["linkReminder"] is False
        assert _steam_ui("steam_signup", dict(me, steam_linked=True))["linkReminder"] is False
        assert _steam_ui("steam_signup", dict(me, has_password=False))["linkReminder"] is False

    def test_steam_link_callback_with_other_users_state_changes_nothing(self, web, mode, monkeypatch):
        """Failure path: a link callback whose state row is bound to another user changes nothing and redirects with steam=failed."""
        mode("both")
        other = web.add_user("bob")
        uid = web.add_user("alice")
        client = web.login("alice")
        _plant(web, client, purpose="link", user_id=other)
        _mock_steam(monkeypatch)
        resp = _callback(client, _id_res_params())
        assert _key(resp, "profile") == "failed"
        assert _user(web, uid).steam_id is None and _user(web, other).steam_id is None

    def test_steam_link_callback_without_session_changes_nothing(self, web, mode, monkeypatch):
        """Failure path: a link callback with no session changes nothing and redirects with steam=no_session."""
        mode("both")
        uid = web.add_user("alice")
        client = web.client()
        _plant(web, client, purpose="link", user_id=uid)
        _mock_steam(monkeypatch)
        resp = _callback(client, _id_res_params())
        assert _key(resp, "profile") == "no_session"
        assert _user(web, uid).steam_id is None


# ---------------------------------------------------------------------------
# Story 3 — Steam Is the Only Way to Create Accounts in S17
# ---------------------------------------------------------------------------

class TestSteamOnlyAccountCreationS17:
    """Story: Steam Is the Only Way to Create Accounts in S17."""

    def test_login_method_defaults_to_password(self, monkeypatch):
        """Step 1: LOGIN_METHOD unset means password mode."""
        import login_mode
        monkeypatch.delenv("LOGIN_METHOD", raising=False)
        assert login_mode.current() == "password"
        assert login_mode.steam_enabled() is False
        for value in ("both", " BOTH ", "steam_signup"):
            monkeypatch.setenv("LOGIN_METHOD", value)
            assert login_mode.current() == value.strip().lower()

    @pytest.mark.parametrize("value,expected", [
        ("steam", "steam_signup"),     # issue #172's mode: not built, never reopens registration
        ("STEAM_ONLY", "password"),
        ("bogus", "password"),
        ("", "password"),              # empty is the same as unset: no warning
    ])
    def test_login_method_unknown_value_logged_and_treated_as_password(self, monkeypatch, caplog, value, expected):
        """Failure path: an unknown LOGIN_METHOD value is logged and treated as password; `steam` (#172, not built yet) is logged as not available and treated as steam_signup."""
        import login_mode
        login_mode._warned.clear()
        monkeypatch.setenv("LOGIN_METHOD", value)
        caplog.set_level(logging.WARNING, logger="login_mode")
        assert login_mode.current() == expected
        warnings = [r.getMessage() for r in caplog.records if r.name == "login_mode"]
        if value:
            assert len(warnings) == 1
            if value == "steam":
                assert "not available yet" in warnings[0]
        else:
            assert warnings == []
        login_mode.current()
        assert len([r for r in caplog.records if r.name == "login_mode"]) == len(warnings)

    @pytest.mark.parametrize("login_method", ["password", "both"])
    def test_register_works_in_password_and_both(self, web, mode, login_method):
        """AC: POST /register keeps working in password and both modes."""
        mode(login_method)
        resp = web.client().post("/register", json={"username": "newbie", "email": "n@example.com",
                                                    "password": "secret123"})
        assert resp.status_code == 200, resp.text
        assert _user_by_name(web, "newbie") is not None

    def test_register_404_in_steam_signup_creates_nothing(self, web, mode):
        """Failure path: a direct POST /register in steam_signup mode answers 404 and creates no user."""
        from models import User
        mode("steam_signup")
        resp = web.client().post("/register", json={"username": "newbie", "email": "n@example.com",
                                                    "password": "secret123"})
        assert resp.status_code == 404
        assert _count(web, User) == 0

    def test_login_page_hides_registration_in_steam_signup(self):
        """AC: in steam_signup the login page hides the registration form and says "New players: sign in with Steam to create your account."."""
        html = _read("index.html")
        assert "New players: sign in with Steam to create your account." in html
        assert 'id="steamSignupNotice"' in html and 'id="createAccountLink"' in html
        apply = _function_source(_read("app-auth.js"), "applyLoginMode")
        assert "createAccountLink" in apply and "steamSignupNotice" in apply
        ui = _steam_ui("steam_signup", None)
        if ui is None:
            return
        assert ui["passwordRegistration"] is False and ui["steamSignupNotice"] is True
        assert _steam_ui("both", None)["steamSignupNotice"] is False

    @pytest.mark.parametrize("login_method", ["password", "both", "steam_signup"])
    def test_password_login_reset_change_and_reauth_work_in_every_mode(self, web, mode, login_method):
        """AC: password sign-in, /forgot-password, /reset-password, PUT /profile/password and POST /reauth keep working for existing password accounts in all three modes."""
        from models import PasswordResetToken
        mode(login_method)
        web.add_user("alice")
        client = web.login("alice", reauth=True)
        assert client.post("/forgot-password", json={"username": "alice"}).status_code == 200
        token = web.rows(PasswordResetToken)[0].token
        assert client.post("/reset-password", json={"token": token,
                                                    "new_password": "newpass1"}).status_code == 200
        fresh = web.client()
        assert fresh.post("/login", json={"username": "alice", "password": "newpass1"}).status_code == 200
        resp = fresh.put("/profile/password", json={"current_password": "newpass1",
                                                    "new_password": _PASSWORD})
        assert resp.status_code == 200, resp.text
        assert fresh.post("/reauth", json={"password": _PASSWORD}).status_code == 200

    def test_reauth_refused_for_account_without_password(self, web, mode, monkeypatch):
        """Step 4: POST /reauth for an account without a password answers 409 use_steam_reauth (not 401) and does not count as a failed login."""
        from routers import auth as auth_router
        mode("both")
        client = web.client()
        _signup(web, client, monkeypatch, username="steamonly")
        resp = client.post("/reauth", json={"password": "anything"})
        assert resp.status_code == 409 and resp.json()["detail"] == "use_steam_reauth"
        assert "steamonly" not in auth_router._failed_login_attempts
        assert "use_steam_reauth" in _read("app-admin.js")

    def test_seed_admin_password_sets_skipped_in_steam_signup_with_one_warning(self, db, monkeypatch, caplog):
        """AC: in steam_signup mode SEED_ADMIN_USERNAME (and numbered sets) are ignored with exactly one start-up warning; no user is created."""
        import seed as seed_module
        from models import User
        monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)
        monkeypatch.setenv("LOGIN_METHOD", "steam_signup")
        for suffix in ("", "_2"):
            monkeypatch.setenv(f"SEED_ADMIN_USERNAME{suffix}", f"admin{suffix}")
            monkeypatch.setenv(f"SEED_ADMIN_EMAIL{suffix}", f"admin{suffix}@example.com")
            monkeypatch.setenv(f"SEED_ADMIN_PASSWORD{suffix}", "secret123")
        caplog.set_level(logging.INFO, logger="seed")
        seed_module.seed_admin_from_env()
        assert db.query(User).count() == 0
        warnings = [r for r in caplog.records if r.name == "seed" and r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "steam_signup" in warnings[0].getMessage()

    @pytest.mark.parametrize("login_method", ["password", "both"])
    def test_seed_admin_password_sets_still_work_in_password_and_both(self, db, monkeypatch, login_method):
        """Assumption: password admin seeding keeps working in password and both modes."""
        import seed as seed_module
        from models import User
        monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)
        monkeypatch.setenv("LOGIN_METHOD", login_method)
        monkeypatch.setenv("SEED_ADMIN_USERNAME", "admin")
        monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@example.com")
        monkeypatch.setenv("SEED_ADMIN_PASSWORD", "secret123")
        monkeypatch.delenv("SEED_ADMIN_USERNAME_2", raising=False)
        seed_module.seed_admin_from_env()
        user = db.query(User).filter_by(username="admin").one()
        assert user.is_admin is True

    def test_demo_seed_accounts_still_created_in_steam_signup(self, db, monkeypatch):
        """AC: demo accounts (DEMO_MODE only) are exempt and still created by POST /admin/demo/seed-accounts in steam_signup mode."""
        from models import User
        from routers.admin_demo import SeedDemoAccountsBody, seed_demo_accounts
        monkeypatch.setenv("LOGIN_METHOD", "steam_signup")
        monkeypatch.setenv("DEMO_MODE", "true")
        admin = User(username="boss", is_admin=True, tokens=0)
        db.add(admin)
        db.commit()
        result = seed_demo_accounts(SeedDemoAccountsBody(count=2, cards_per_account=0), db=db,
                                    admin=_acting(admin))
        assert [a["username"] for a in result["accounts"]] == ["demo1", "demo2"]
        demos = db.query(User).filter(User.username.like("demo%")).all()
        assert len(demos) == 2 and all(u.is_demo and u.password_hash for u in demos)
        assert db.get(User, admin.id).is_demo is False

    def test_switching_both_to_steam_signup_needs_no_data_change(self, web, mode, monkeypatch):
        """AC: switching LOGIN_METHOD from both to steam_signup needs only the env var: the same DB keeps working, linked and password accounts sign in."""
        mode("both")
        web.add_user("alice")
        linker = web.add_user("bob")
        resp, _ = _round_trip(web.login("bob"), monkeypatch, purpose="link")
        assert _key(resp, "profile") == "linked"
        mode("steam_signup")
        assert web.login("alice", reauth=False).get("/me").status_code == 200
        client = web.client()
        resp, _ = _round_trip(client, monkeypatch)
        assert _location(resp) == "/"
        assert client.get("/me").json()["user_id"] == linker

    def test_migration_033_adds_users_steam_id_unique(self):
        """Step 1: migration 033_users_steam_id adds users.steam_id (PRAGMA-guarded, unique index) and users.is_demo to a legacy DB; existing users have NULL steam_id; earlier demo accounts are flagged; running twice is a no-op."""
        import migrate
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from tests.test_issue_157_twitch_extension_policy_compliance import _legacy_users_engine
        ids = [m[0] for m in migrate.MIGRATIONS]
        assert ids.index("033_users_steam_id") == ids.index("032_users_merged_soft_account_at") + 1
        engine = _legacy_users_engine()
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO users (id, username, email, tokens) VALUES "
                              "(3, 'demo1', 'demo1@demo.local', 0), (4, 'demolition', 'd@x.fi', 0)"))
            conn.commit()
            migrate._m033_users_steam_id(conn)
            migrate._m033_users_steam_id(conn)  # idempotent
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
            assert {"steam_id", "is_demo"} <= cols
            rows = dict(conn.execute(text("SELECT id, is_demo FROM users")).fetchall())
            assert rows == {1: 0, 2: 0, 3: 1, 4: 0}
            assert conn.execute(text("SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL")).scalar() == 0
            conn.execute(text(f"UPDATE users SET steam_id = '{_STEAM64}' WHERE id = 1"))
            with pytest.raises(IntegrityError):
                conn.execute(text(f"UPDATE users SET steam_id = '{_STEAM64}' WHERE id = 2"))


# ---------------------------------------------------------------------------
# Story 4 — Admins Come In Through Steam
# ---------------------------------------------------------------------------

def _destructive_request(web, client, action, monkeypatch, tmp_path, confirm=None):
    """Send one covered admin action, with `confirm` when given."""
    from routers import admin_backups, admin_season
    phrase = {} if confirm is None else {"confirm": confirm}
    if action == "season_end":
        return client.post("/admin/season/end", json={"season_label": "S16", **phrase})
    if action == "season_reset":
        monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda: str(tmp_path / "pre-reset.db"))
        return client.post("/admin/season/reset", json={"force": True, **phrase})
    if action == "toggle_admin":
        target = web.add_user(f"target-{secrets.token_hex(3)}")
        return client.post(f"/users/{target}/toggle-admin", params=phrase)
    if action == "grant_tokens":
        target = web.add_user(f"target-{secrets.token_hex(3)}")
        return client.post("/grant-tokens", json={"target_user_id": target, "amount": 3, **phrase})
    if action == "backup_download":
        backup = tmp_path / "fantasy.db.backup-20261007"
        backup.write_bytes(b"SQLite format 3\x00")
        monkeypatch.setattr(admin_backups, "list_sqlite_backups", lambda: [backup])
        return client.get(f"/admin/backups/{backup.name}", params=phrase)
    if action == "delete_user":
        soft = _add(web, None, account_type="twitch")
        return client.delete(f"/admin/users/{soft}", params=phrase)
    raise AssertionError(action)


_ACTIONS = ["season_end", "season_reset", "toggle_admin", "grant_tokens", "backup_download",
            "delete_user"]


class TestAdminsComeInThroughSteam:
    """Story: Admins Come In Through Steam."""

    def test_seed_admin_steam_ids_parsed(self, monkeypatch):
        """AC: SEED_ADMIN_STEAM_IDS is a comma-separated list of 17-digit Steam64 ids (whitespace tolerated)."""
        from seed import seed_admin_steam_ids
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", f" {_STEAM64} ,{_OTHER_STEAM64},, ")
        assert seed_admin_steam_ids() == {_STEAM64, _OTHER_STEAM64}
        monkeypatch.delenv("SEED_ADMIN_STEAM_IDS")
        assert seed_admin_steam_ids() == set()

    @pytest.mark.parametrize("bad", ["123", "7656119800000000x", "765611980000000011", "abc"])
    def test_seed_admin_steam_ids_invalid_entry_logged_and_skipped(self, monkeypatch, caplog, bad):
        """AC: an entry that is not exactly 17 digits is logged and skipped; valid entries still apply and start-up continues."""
        from seed import seed_admin_steam_ids
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", f"{bad},{_STEAM64}")
        caplog.set_level(logging.WARNING, logger="seed")
        assert seed_admin_steam_ids() == {_STEAM64}
        warnings = [r.getMessage() for r in caplog.records if r.name == "seed"]
        assert len(warnings) == 1 and "entry 1" in warnings[0]

    def test_listed_steam_id_first_signup_created_as_admin(self, web, mode, monkeypatch):
        """AC: a first-time listed Steam id is created as an admin after the display-name step, audited admin_seeded_from_env."""
        from models import AuditLog
        mode("steam_signup")
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", _STEAM64)
        client = web.client()
        resp = _signup(web, client, monkeypatch, username="newchief")
        assert resp.json()["is_admin"] is True
        user = _user_by_name(web, "newchief")
        assert user.is_admin is True
        audits = web.rows(AuditLog, action="admin_seeded_from_env")
        assert len(audits) == 1 and audits[0].actor_id == user.id

    def test_listed_steam_id_existing_account_promoted_on_signin_or_link(self, web, mode, monkeypatch):
        """AC: an existing account whose verified Steam sign-in or link matches the list is promoted, audited admin_seeded_from_env."""
        from models import AuditLog
        mode("both")
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", f"{_STEAM64},{_OTHER_STEAM64}")
        signer = _add(web, "signer", steam_id=_STEAM64)
        resp, _ = _round_trip(web.client(), monkeypatch, _STEAM64)
        assert _location(resp) == "/"
        assert _user(web, signer).is_admin is True
        linker = web.add_user("linker")
        resp, _ = _round_trip(web.login("linker"), monkeypatch, _OTHER_STEAM64, purpose="link")
        assert _key(resp, "profile") == "linked"
        assert _user(web, linker).is_admin is True
        actors = {a.actor_id for a in web.rows(AuditLog, action="admin_seeded_from_env")}
        assert actors == {signer, linker}

    def test_unlisted_steam_id_signs_in_as_normal_player(self, web, mode, monkeypatch):
        """Failure path: an unlisted Steam id signs in as a normal player (is_admin false)."""
        from models import AuditLog
        mode("both")
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", _OTHER_STEAM64)
        client = web.client()
        assert _signup(web, client, monkeypatch, username="player").json()["is_admin"] is False
        assert _user_by_name(web, "player").is_admin is False
        assert web.rows(AuditLog, action="admin_seeded_from_env") == []

    def test_removing_id_from_list_does_not_demote(self, web, mode, monkeypatch):
        """AC: removing an id from SEED_ADMIN_STEAM_IDS does not demote the account on its next sign-in."""
        mode("both")
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", _STEAM64)
        _signup(web, web.client(), monkeypatch, username="chief1")
        monkeypatch.delenv("SEED_ADMIN_STEAM_IDS")
        client = web.client()
        resp, _ = _round_trip(client, monkeypatch)
        assert _location(resp) == "/"
        assert client.get("/me").json()["is_admin"] is True

    def test_password_admin_linking_steam_keeps_admin(self, web, mode, monkeypatch):
        """AC: a password admin who links Steam keeps admin rights."""
        mode("both")
        uid = web.add_user("boss", is_admin=True)
        resp, _ = _round_trip(web.login("boss"), monkeypatch, purpose="link")
        assert _key(resp, "profile") == "linked"
        assert _user(web, uid).is_admin is True

    def test_demo_account_can_never_become_admin(self, web, mode, monkeypatch, db):
        """Failure path: a demo account is never promoted, neither by SEED_ADMIN_STEAM_IDS on link nor by the admin toggle."""
        import deps
        import steam_openid
        from models import User
        mode("both")
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", _STEAM64)
        demo = web.add_user("demo1", is_demo=True)
        client = web.login("demo1")
        assert _key(_start(client, "link"), "profile") == "not_allowed"
        demo_user = User(username="demo2", is_demo=True, tokens=0)
        db.add(demo_user)
        db.commit()
        assert steam_openid.link_account(db, demo_user, _STEAM64) == "not_allowed"
        steam_openid._apply_admin_seed(db, demo_user, _STEAM64)
        assert demo_user.is_admin is not True and demo_user.steam_id is None
        admin = _admin_client(web)
        resp = admin.post(f"/users/{demo}/toggle-admin",
                          params={"confirm": deps.CONFIRM_PHRASES["toggle_admin"]})
        assert resp.status_code == 409
        assert _user(web, demo).is_admin is False

    @pytest.mark.parametrize("action", _ACTIONS)
    def test_destructive_admin_action_requires_typed_confirmation(self, web, mode, monkeypatch, tmp_path, action):
        """AC: season end, season reset, admin toggle, token grant, DB backup download and user deletion answer 400 confirmation_required without a confirm field equal to the action name (with a recent re-auth)."""
        mode("both")
        client = _admin_client(web)
        for confirm in (None, "yes", "RESET"):
            resp = _destructive_request(web, client, action, monkeypatch, tmp_path, confirm)
            assert resp.status_code == 400, (confirm, resp.text)
            assert resp.json()["detail"] == "confirmation_required"

    @pytest.mark.parametrize("action", _ACTIONS)
    def test_destructive_admin_action_succeeds_with_typed_confirmation(self, web, mode, monkeypatch, tmp_path, action):
        """AC: each covered action succeeds with a recent re-auth and confirm equal to its action name."""
        import deps
        mode("both")
        client = _admin_client(web)
        resp = _destructive_request(web, client, action, monkeypatch, tmp_path,
                                    deps.CONFIRM_PHRASES[action].lower())
        assert resp.status_code == 200, resp.text
        web.add_user("boss2", is_admin=True)
        stale_client = web.login("boss2", reauth=False)
        resp = _destructive_request(web, stale_client, action, monkeypatch, tmp_path,
                                    deps.CONFIRM_PHRASES[action])
        assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"

    def test_steam_reauth_marks_session_for_matching_admin(self, web, mode, monkeypatch):
        """AC: an admin without a password re-authenticates through Steam (purpose=reauth); the session's recent check is set via sessions.mark_reauth and require_recent_reauth then passes."""
        import deps
        from models import UserSession
        mode("both")
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", _STEAM64)
        client = web.client()
        _signup(web, client, monkeypatch, username="steamchief")
        target = web.add_user("target")
        grant = {"target_user_id": target, "amount": 1, "confirm": deps.CONFIRM_PHRASES["grant_tokens"]}
        assert client.post("/grant-tokens", json=grant).status_code == 403
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth", return_tab="admin")
        assert _location(resp) == "/#admin?steam=reauth_ok"
        assert web.rows(UserSession)[0].reauth_at is not None
        assert client.post("/grant-tokens", json=grant).status_code == 200

    def test_steam_reauth_return_tab_is_allowlisted(self, web, mode, monkeypatch):
        """Decision 7: return_tab only accepts profile or admin; anything else returns to Profile, never a free URL."""
        mode("both")
        client = web.client()
        _signup(web, client, monkeypatch, username="steamonly")
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth", return_tab="https://evil.example/")
        assert _location(resp) == "/#profile?steam=reauth_ok"

    def test_steam_reauth_satisfies_connect_twitch(self, web, mode, monkeypatch):
        """Assumption: Steam re-auth sets the same per-session check, so require_recent_player_reauth (Connect Twitch) passes for a Steam-created player."""
        import twitch_oauth
        mode("both")
        monkeypatch.setenv("TWITCH_OAUTH_CLIENT_ID", "cid")
        monkeypatch.setenv("TWITCH_OAUTH_CLIENT_SECRET", "secret")
        monkeypatch.setenv("TWITCH_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/twitch/callback")
        client = web.client()
        _signup(web, client, monkeypatch, username="viewer")
        before = client.get("/auth/twitch/start", follow_redirects=False)
        assert before.headers["location"] == "/#profile?twitch=reauth_required"
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth")
        assert _location(resp) == "/#profile?steam=reauth_ok"
        after = client.get("/auth/twitch/start", follow_redirects=False)
        assert after.status_code == 303
        assert after.headers["location"].startswith(twitch_oauth.AUTHORIZE_URL)

    def test_steam_reauth_with_different_steam_id_does_not_mark_session(self, web, mode, monkeypatch):
        """Failure path: a Steam re-auth whose verified Steam id differs from the session user's leaves the session unmarked."""
        from models import UserSession
        mode("both")
        client = web.client()
        _signup(web, client, monkeypatch, username="steamonly")
        resp, _ = _round_trip(client, monkeypatch, _OTHER_STEAM64, purpose="reauth")
        assert _location(resp) == "/#profile?steam=reauth_failed"
        assert web.rows(UserSession)[0].reauth_at is None

    def test_docs_require_steam_guard_and_describe_quick_demotion(self):
        """AC: the docs require Steam Guard's mobile authenticator for listed admins, say removal from the list does not demote, and describe quick demotion."""
        doc = (REPO_ROOT / "markdown" / "features" / "reference" / "steam-login.md").read_text(encoding="utf-8")
        assert "Steam Guard" in doc and "mobile authenticator" in doc
        assert "does not demote" in doc
        assert "Demote an admin quickly" in doc
        assert "*(planned)*" not in doc


class TestAdminSeedAppliesOnce:
    """Security review follow-up: SEED_ADMIN_STEAM_IDS promotes an account at most once,
    so an in-app demotion of a listed admin holds at the next Steam sign-in."""

    def test_demoted_listed_admin_is_not_promoted_again(self, db, monkeypatch):
        """A listed id is promoted on first sign-in; after an in-app demotion, the next sign-in leaves it demoted."""
        import steam_openid
        from models import User
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", _STEAM64)
        user = User(username="listedone", tokens=0, steam_id=_STEAM64)
        db.add(user)
        db.commit()
        steam_openid._apply_admin_seed(db, user, _STEAM64)
        assert user.is_admin is True and user.admin_seed_applied_at is not None
        user.is_admin = False  # demoted in-app
        db.commit()
        steam_openid._apply_admin_seed(db, user, _STEAM64)
        assert user.is_admin is False

    def test_already_admin_listed_account_is_marked_so_demotion_sticks(self, db, monkeypatch):
        """A listed account that is already an admin is marked on its first sign-in, so a later demotion also holds."""
        import steam_openid
        from models import User
        monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", _STEAM64)
        user = User(username="alreadyboss", tokens=0, steam_id=_STEAM64, is_admin=True)
        db.add(user)
        db.commit()
        steam_openid._apply_admin_seed(db, user, _STEAM64)
        assert user.is_admin is True and user.admin_seed_applied_at is not None
        user.is_admin = False
        db.commit()
        steam_openid._apply_admin_seed(db, user, _STEAM64)
        assert user.is_admin is False

    def test_migration_035_adds_admin_seed_applied_at(self):
        """Migration 035 adds users.admin_seed_applied_at on the legacy schema."""
        import migrate
        assert "035_users_admin_seed_applied_at" in [name for name, _ in migrate.MIGRATIONS]
