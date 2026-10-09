"""
Tests for plan-issue-160-twitch-account-connection-oidc.md (resolves GitHub
issue #160, Part 2 of 2; Part 1 is #157).

Twitch sign-in (OpenID Connect, authorization code flow) on the website replaces
the 6-character link code: `GET /auth/twitch/start` / `GET /auth/twitch/callback`
store the verified Twitch user id (`sub`) in `users.twitch_account_id`; a waiting
soft account with the same id can be merged with `POST /twitch/merge/confirm`;
the panel recognises the website account by the JWT's `user_id`;
`POST /twitch/disconnect`; the link-code endpoints and `GET /twitch/status` are
retired; a merge undo log with admin reversal; kill switches; no Twitch ids or
secrets exposed. One stub per acceptance criterion, plus the primary failure
path per story. Every stub body is `pytest.fail("not yet implemented")`.

Developer notes
---------------

  What already exists (do not re-implement)
    - #157 (Part 1) is implemented: `backend/soft_accounts.py`
      (`get_or_create_soft_account`, `record_twitch_account_id`,
      `delete_soft_account`, `purge_inactive_soft_accounts`, `find_by_opaque_id`,
      `touch_last_seen`), `User.account_type` / `last_seen_at` /
      `twitch_account_id` (migration 031), `POST /twitch/join` (`twitch.join`),
      `GET /twitch/me` (`twitch.me`), `twitch._joined_user`, admin
      `GET /users?account_type=` and `DELETE /admin/users/{id}`,
      `TWITCH_DROPS_ENABLED`. This plan's migration is
      `032_users_merged_soft_account_at`.
    - The plan was updated after #157: lookup order in join/me/_joined_user
      (Step 4), the merge reuses `soft_accounts.delete_soft_account` (extend it
      there, never a second list), and `GET /twitch/status` is retired.
    - #161 is implemented (`steam_live.py`, `match_timings`, the live poll
      thread). Don't break test_issue_161_* / test_issue_139_*.
    - `POST /twitch/mvp` returns only a winner count, never names.

  No network
    - Every Twitch OAuth/OIDC HTTP call must be mocked: the token exchange
      (patch the `requests.post` the new module uses, e.g.
      `monkeypatch.setattr(twitch_oauth._requests, "post", fake)`), and the JWKS
      fetch (patch `PyJWKClient.get_signing_key_from_jwt`, or the module-level
      client object, to return the local test key). Never hit id.twitch.tv.
    - Test ID tokens: `_rsa_keypair()` and `_id_token()` below build a local
      RS256 key and sign a token with it; `_FakeSigningKey(public_key)` mimics
      `PyJWK` (`.key`) for a patched `get_signing_key_from_jwt`. A "wrong
      signature" test signs with a second key pair. `cryptography` is installed
      locally (3.4.8) but not in requirements.txt: add `PyJWT[crypto]` or a
      pinned `cryptography` as the plan says.

  Reuse from existing tests (import underscore names only, so pytest doesn't
  collect the other module's tests twice)
    - From test_issue_157_twitch_extension_policy_compliance: `_viewer`,
      `_join`, `_card`, `_website_user`, `_user_by_opaque`, `_raises`,
      `_shared_db`, `_twitch_app`, `_signed`, `_no_twitch_ids`, `_SECRET_B64`;
      the `twitch_env` / `twitch_prod_env` fixtures must be copied (fixtures are
      not picked up by import unless re-declared).
    - Re-auth: `deps.require_recent_reauth` is admin-only; this plan adds
      `require_recent_player_reauth`. HTTP tests must `POST /reauth` first (see
      `_reauth` and the `session_env` / `clock` fixtures in
      test_issue_117_longer_sessions.py; `sessions._now` is the clock).
      `POST /reauth` already accepts any logged-in user but audits as
      `admin_reauth`; decide whether that action name is acceptable for players.
    - For a website session in a TestClient, log in with `POST /login` or build
      the cookie with `sessions.create_session(db, user)` (lessons-learned
      2026-10-01).
    - Rate limits: build a small FastAPI app with `app.state.limiter =
      <module>.limiter` (lessons-learned 2026-10-06, `_twitch_app` precedent).

  New model fields / modules
    - `TwitchOAuthState`, `TwitchMergeLog`, `User.merged_soft_account_at` and
      `backend/twitch_oauth.py` don't exist yet: import them inside each test,
      never at module level, or every stub fails collection.

  Plan vs current code (resolve before implementing)
    - `users.twitch_account_id` is UNIQUE (#157), but the plan has the
      callback store `sub` on W while soft account S still holds the same id,
      and the merge prompt finds S by W's id. As written the callback write
      fails. Decide where the pending link lives and update the plan; the
      stubs below describe outcomes, not the storage choice.
    - `GET /auth/twitch/start` is a top-level redirect, but "requires a recent
      password check" means a 403 JSON on a navigation. The frontend must check
      (or /reauth) before navigating; the start route should still enforce it.

  Existing tests this plan will break (update them in the same change)
    - Link-code endpoint tests: test_issue_117_longer_sessions.py (~l.540),
      test_issue_119_session_revocation.py (~l.584-597),
      test_issue_135_security_review_fixes.py (~l.396-414,
      `twitch.generate_link_code`), test_issue_136_security_audit_3.py
      (~l.306-317 Origin check on /twitch/link-code, and the CORS preflight
      helper `_preflight` at ~l.452 targets `/twitch/status`, which is retired:
      point it at a surviving `/twitch/*` route).
    - test_issue_123_password_reset_token_flow.py only mentions
      `generate_link_code` in docstrings; reword if you like.
    - test_issue_85_split_admin_router.py: bump the "N passed" tripwire.
"""

import pathlib

import pytest

# Registers every existing table on Base before the conftest db fixture runs
# create_all. New models/modules are imported inside tests.
import models  # noqa: F401

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"

_CLIENT_ID = "test-oauth-client-id"
_CLIENT_SECRET = "test-oauth-client-secret-do-not-log"
_REDIRECT_URI = "http://localhost:8000/auth/twitch/callback"
_ISSUER = "https://id.twitch.tv/oauth2"
_TWITCH_ID = "123456789"  # the real Twitch user id (`sub` / extension JWT `user_id`)


@pytest.fixture
def oauth_env(monkeypatch):
    """All three TWITCH_OAUTH_* variables set (Connect Twitch available)."""
    monkeypatch.setenv("TWITCH_OAUTH_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("TWITCH_OAUTH_CLIENT_SECRET", _CLIENT_SECRET)
    monkeypatch.setenv("TWITCH_OAUTH_REDIRECT_URI", _REDIRECT_URI)


@pytest.fixture
def twitch_env(monkeypatch):
    """No real Twitch calls: PubSub/chat short-circuit under TWITCH_LOCAL_DEV
    (copied from test_issue_157; only for direct function calls)."""
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)


# ---------------------------------------------------------------------------
# ID token helpers (local RS256 key; no network)
# ---------------------------------------------------------------------------

def _rsa_keypair():
    """(private_key, public_key) for signing fake Twitch ID tokens."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048,
                                       backend=default_backend())
    return private, private.public_key()


def _id_token(private_key, *, sub=_TWITCH_ID, nonce="nonce", aud=_CLIENT_ID,
              iss=_ISSUER, exp_offset=600, kid="test-kid"):
    """An RS256 ID token as Twitch would issue it. Override a claim to fail one check."""
    import time
    import jwt as pyjwt
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": sub, "nonce": nonce,
              "iat": now, "exp": now + exp_offset}
    return pyjwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


class _FakeSigningKey:
    """Stands in for PyJWT's PyJWK: `PyJWKClient.get_signing_key_from_jwt` returns
    an object whose `.key` is the public key."""
    def __init__(self, public_key):
        self.key = public_key


def _token_response(id_token, access_token="access-SECRET-xyz", refresh_token="refresh-SECRET-xyz"):
    """Body of a mocked Twitch token endpoint response."""
    return {"access_token": access_token, "refresh_token": refresh_token,
            "id_token": id_token, "expires_in": 3600, "scope": ["openid"],
            "token_type": "bearer"}




# ---------------------------------------------------------------------------
# Shared helpers (implementation)
# ---------------------------------------------------------------------------
#
# Developer decisions applied here (see the plan's "Decisions" section):
#   - users.twitch_account_id stays unique. At connect time the id moves from a
#     soft account to the website account, and users.pending_merge_user_id (also
#     migration 032) records the soft account waiting to be merged.
#   - GET /auth/twitch/start is a navigation: a missing password check redirects to
#     /#profile?twitch=reauth_required instead of answering 403 JSON.
#   - Every callback outcome redirects to /#profile?twitch=<key>.

import base64  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from tests.test_issue_157_twitch_extension_policy_compliance import (  # noqa: E402
    _card, _chat_recorder, _join, _legacy_users_engine, _no_twitch_ids, _present, _raises,
    _seed_series_match, _seed_world, _set_mvp, _user_by_opaque, _viewer, _website_user)

BACKEND_DIR = REPO_ROOT / "backend"
_PASSWORD = "secret160"
_SESSION_SECRET = "test-session-secret-160"
_CODE = "authcode-SECRET-160"
_OPAQUE = "Uviewer1"
_WEB_OPAQUE = "Uwebsite1"
_ACCESS = "access-SECRET-xyz"
_REFRESH = "refresh-SECRET-xyz"
_PROFILE_PREFIX = "/#profile?twitch="
_KEYS = {}


def _keys(name="twitch"):
    """A cached RSA key pair (generating one per test is slow)."""
    if name not in _KEYS:
        _KEYS[name] = _rsa_keypair()
    return _KEYS[name]


class _FakeJWKS:
    """Stands in for twitch_oauth's PyJWKClient."""
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self.public_key)


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def _mock_twitch(monkeypatch, id_token=None, *, status=200, raises=None, body=None):
    """Patch the token endpoint (twitch_oauth._requests.post) and the JWKS client.
    Returns the list of recorded token requests."""
    import twitch_oauth
    calls = []

    def fake_post(url, data=None, **kwargs):
        calls.append({"url": url, "data": dict(data or {}), "kwargs": kwargs})
        if raises is not None:
            raise raises
        return _FakeResponse(status, body if body is not None else _token_response(id_token))

    monkeypatch.setattr(twitch_oauth._requests, "post", fake_post)
    monkeypatch.setattr(twitch_oauth, "_jwks_client", _FakeJWKS(_keys()[1]))
    return calls


def _params(location):
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def _key(resp):
    assert resp.status_code in (302, 303, 307), resp.text
    location = resp.headers["location"]
    assert location.startswith(_PROFILE_PREFIX), location
    return location[len(_PROFILE_PREFIX):]


def _acting(user):
    return {"user_id": user.id, "username": user.username, "is_admin": bool(user.is_admin)}


class _Web:
    """A small app (auth, twitch_oauth, twitch, admin_users, admin_twitch) on a thread-safe in-memory DB."""

    def __init__(self, app, Session):
        self.app = app
        self.Session = Session

    def client(self):
        from fastapi.testclient import TestClient
        return TestClient(self.app)

    def add_user(self, username="alice", is_admin=False, **fields):
        from auth import hash_password
        from models import User
        db = self.Session()
        try:
            user = User(username=username, email=f"{username}@example.com",
                        password_hash=hash_password(_PASSWORD), is_admin=is_admin,
                        tokens=5, created_at=int(time.time()), **fields)
            db.add(user)
            db.commit()
            return user.id
        finally:
            db.close()

    def login(self, username="alice", reauth=True):
        client = self.client()
        resp = client.post("/login", json={"username": username, "password": _PASSWORD})
        assert resp.status_code == 200, resp.text
        if reauth:
            assert client.post("/reauth", json={"password": _PASSWORD}).status_code == 200
        return client

    def start(self, client):
        resp = client.get("/auth/twitch/start", follow_redirects=False)
        assert resp.status_code == 303, resp.text
        return resp, _params(resp.headers["location"])

    def callback(self, client, **params):
        return client.get("/auth/twitch/callback", params=params, follow_redirects=False)

    def connect(self, client, monkeypatch, *, sub=_TWITCH_ID, code=_CODE, **claims):
        """Start + mocked Twitch + callback. Returns (callback response, token calls, start params, id token)."""
        _, params = self.start(client)
        id_token = _id_token(_keys()[0], sub=sub, nonce=params["nonce"], **claims)
        calls = _mock_twitch(monkeypatch, id_token)
        resp = self.callback(client, code=code, state=params["state"])
        return resp, calls, params, id_token

    def get(self, model, key):
        db = self.Session()
        try:
            obj = db.get(model, key)
            if obj is not None:
                db.expunge(obj)
            return obj
        finally:
            db.close()

    def rows(self, model, **filters):
        db = self.Session()
        try:
            rows = db.query(model).filter_by(**filters).all()
            for r in rows:
                db.expunge(r)
            return rows
        finally:
            db.close()

    def run(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def all_text(self):
        from database import Base
        db = self.Session()
        try:
            out = []
            for table in Base.metadata.sorted_tables:
                for row in db.execute(table.select()).fetchall():
                    out.append(json.dumps([str(v) for v in row]))
            return "\n".join(out)
        finally:
            db.close()


@pytest.fixture
def web():
    import rate_limit
    import twitch
    import twitch_oauth
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from starlette.middleware.sessions import SessionMiddleware
    from database import Base, get_db
    from routers import admin_twitch as admin_twitch_router
    from routers import admin_users as admin_users_router
    from routers import auth as auth_router

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

    modules = (auth_router, twitch_oauth, twitch, admin_users_router, admin_twitch_router)
    limiters = {id(rate_limit.limiter): rate_limit.limiter}
    for m in modules:
        if hasattr(m, "limiter"):
            limiters[id(m.limiter)] = m.limiter
    was_enabled = {k: lim.enabled for k, lim in limiters.items()}
    for lim in limiters.values():
        lim.enabled = False
    auth_router._failed_login_attempts.clear()
    auth_router._failed_login_attempts_by_ip.clear()

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


def _soft_with_identity(db, opaque=_OPAQUE, real_id=_TWITCH_ID, cards=(101, 101), tokens=7):
    """A soft account that joined with the identity share, with cards (duplicates allowed)."""
    _join(db, opaque, user_id=real_id)
    soft = _user_by_opaque(db, opaque)
    soft.tokens = tokens
    db.commit()
    made = [_card(db, soft.id, pid, active=(i == 0), slot=(0 if i == 0 else None))
            for i, pid in enumerate(cards)]
    return soft, made


def _pending_pair(db, **kwargs):
    """(website account W, soft account S, S's cards) after W connected the id S shared."""
    import twitch_oauth
    from models import Player
    for pid in (101, 102, 103):
        if not db.get(Player, pid):
            db.add(Player(id=pid, name=f"Player{pid}"))
    db.commit()
    soft, cards = _soft_with_identity(db, **kwargs)
    web_user = _website_user(db, "alice", tokens=5)
    assert twitch_oauth.connect_account(db, web_user, _TWITCH_ID) == "merge_ready"
    return web_user, soft, cards


def _merge(db, user):
    import twitch_oauth
    return twitch_oauth.merge_confirm(db, _acting(user))


def _audits(db, action):
    from models import AuditLog
    return [a.detail for a in db.query(AuditLog).filter_by(action=action).all()]


# ---------------------------------------------------------------------------
# Story 1 — Connect Twitch on the Website
# ---------------------------------------------------------------------------

class TestConnectTwitchOnWebsite:
    """Story: Connect Twitch on the Website."""

    def test_connection_status_not_connected_shows_connect(self, db, oauth_env):
        """AC Profile section: GET /twitch/connection returns connected=false, pending_merge=null, available=true for an account with no twitch_account_id."""
        import twitch_oauth
        user = _website_user(db, "alice")
        status = twitch_oauth.connection_status(db, user)
        assert status["available"] is True
        assert status["connected"] is False
        assert status["pending_merge"] is None
        assert status["merge_used"] is False

    def test_connection_status_connected_and_pending_merge(self, db, oauth_env):
        """AC Profile section: connected=true when twitch_account_id is set; pending_merge={cards, tokens} when a soft account with the same id waits."""
        import twitch_oauth
        web_user, soft, cards = _pending_pair(db)
        status = twitch_oauth.connection_status(db, web_user)
        assert status["connected"] is True
        assert status["pending_merge"] == {"cards": 2, "tokens": 7}
        # Decision 1: the id moved to W; S keeps its opaque id until the merge.
        db.refresh(soft)
        assert soft.twitch_account_id is None and soft.twitch_user_id == _OPAQUE
        assert web_user.twitch_account_id == _TWITCH_ID and web_user.pending_merge_user_id == soft.id

    def test_profile_twitch_section_markup_states(self):
        """AC Profile section: frontend renders Connect Twitch, "Connected to Twitch" + Disconnect, and the merge prompt from GET /twitch/connection; the old code UI is gone."""
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        for needle in ('id="btnConnectTwitch"', "Connect Twitch", "Connected to Twitch",
                       'id="btnDisconnectTwitch"', "Disconnect", 'id="twitchMergePrompt"',
                       "Add to my account", "Not now"):
            assert needle in html, needle
        assert "/twitch/connection" in js
        assert "/auth/twitch/start" in js
        assert "/twitch/merge/confirm" in js and "/twitch/disconnect" in js
        assert "Add it to this account?" in js
        for gone in ("Generate Twitch Code", "/twitch/link-code", "generateTwitchCode",
                     'id="twitchLinked"', 'id="twitchUnlinked"', "coming soon"):
            assert gone not in html.split('id="tab-team"')[0].split('id="tab-profile"')[1] + js, gone

    def test_auth_twitch_start_stores_hashed_state_and_redirects(self, db, oauth_env, web):
        """AC Starting: after /reauth, GET /auth/twitch/start stores sha256(state), user id, nonce, verifier and expiry now+600 in twitch_oauth_states and redirects to id.twitch.tv/oauth2/authorize with response_type=code, scope=openid, redirect_uri, state, nonce."""
        from models import TwitchOAuthState
        uid = web.add_user()
        client = web.login()
        before = int(time.time())
        resp, params = web.start(client)
        after = int(time.time())
        assert resp.headers["location"].startswith("https://id.twitch.tv/oauth2/authorize?")
        assert params["response_type"] == "code" and params["scope"] == "openid"
        assert params["client_id"] == _CLIENT_ID and params["redirect_uri"] == _REDIRECT_URI
        rows = web.rows(TwitchOAuthState)
        assert len(rows) == 1
        row = rows[0]
        assert row.state_hash == hashlib.sha256(params["state"].encode()).hexdigest()
        assert params["state"] not in web.all_text()  # only the hash is stored
        assert row.user_id == uid and row.nonce == params["nonce"]
        assert row.code_verifier and row.used_at is None
        assert before + 600 <= row.expires_at <= after + 600

    def test_auth_twitch_start_without_recent_reauth_returns_403(self, db, oauth_env, web):
        """Failure path: GET /auth/twitch/start without a recent password check stores no state.
        Decision 3: a top-level navigation, so it redirects to Profile with
        twitch=reauth_required (the frontend opens the password prompt) instead of 403 JSON."""
        from models import TwitchOAuthState
        web.add_user()
        client = web.login(reauth=False)
        resp = client.get("/auth/twitch/start", follow_redirects=False)
        assert _key(resp) == "reauth_required"
        assert web.rows(TwitchOAuthState) == []
        # Logged out: back to Profile as well, nothing stored.
        assert _key(web.client().get("/auth/twitch/start", follow_redirects=False)) == "login_required"
        assert web.rows(TwitchOAuthState) == []
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        assert "reauth_required" in js and "_promptReauth(" in js

    def test_auth_twitch_start_pkce_parameters(self, db, oauth_env, web):
        """Step 7 PKCE: while PKCE is on, the redirect carries code_challenge = base64url(sha256(stored verifier)) without padding and code_challenge_method=S256."""
        import twitch_oauth
        from models import TwitchOAuthState
        assert twitch_oauth.USE_PKCE is True
        web.add_user()
        _, params = web.start(web.login())
        verifier = web.rows(TwitchOAuthState)[0].code_verifier
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert params["code_challenge"] == expected and "=" not in params["code_challenge"]
        assert params["code_challenge_method"] == "S256"

    def test_redirect_uri_used_exactly_in_authorize_and_code_swap(self, db, oauth_env, monkeypatch, web):
        """Step 7 Redirect address: the authorize redirect and the mocked code swap both use exactly TWITCH_OAUTH_REDIRECT_URI."""
        web.add_user()
        resp, calls, params, _ = web.connect(web.login(), monkeypatch)
        assert _key(resp) == "connected"
        assert params["redirect_uri"] == _REDIRECT_URI
        assert calls[0]["data"]["redirect_uri"] == _REDIRECT_URI

    def test_auth_twitch_callback_success_stores_sub_and_audits(self, db, oauth_env, monkeypatch, web):
        """AC Finishing: a valid state + mocked token exchange + valid ID token sets twitch_account_id = sub, consumes the state, audits twitch_connected and redirects to / with a Profile message key (no Twitch data in the URL)."""
        from models import AuditLog, TwitchOAuthState, User
        uid = web.add_user()
        resp, calls, params, _ = web.connect(web.login(), monkeypatch)
        assert resp.headers["location"] == "/#profile?twitch=connected"
        assert _TWITCH_ID not in resp.headers["location"]
        assert web.get(User, uid).twitch_account_id == _TWITCH_ID
        assert web.rows(TwitchOAuthState)[0].used_at is not None
        audits = web.rows(AuditLog, action="twitch_connected")
        assert len(audits) == 1 and audits[0].actor_id == uid
        assert _TWITCH_ID not in (audits[0].detail or "")

    def test_auth_twitch_callback_code_swap_sends_secret_and_verifier(self, db, oauth_env, monkeypatch, web):
        """AC Finishing step 2 / Step 7 PKCE: the server-side code swap posts the client secret, the code, the redirect_uri and the stored code_verifier, with a timeout."""
        from models import TwitchOAuthState
        web.add_user()
        resp, calls, _, _ = web.connect(web.login(), monkeypatch)
        assert len(calls) == 1
        call = calls[0]
        assert call["url"] == "https://id.twitch.tv/oauth2/token"
        assert call["data"]["client_id"] == _CLIENT_ID
        assert call["data"]["client_secret"] == _CLIENT_SECRET
        assert call["data"]["code"] == _CODE
        assert call["data"]["grant_type"] == "authorization_code"
        assert call["data"]["code_verifier"] == web.rows(TwitchOAuthState)[0].code_verifier
        assert call["kwargs"].get("timeout")

    def test_auth_twitch_callback_tokens_not_stored(self, db, oauth_env, monkeypatch, web):
        """AC Finishing step 4: the access, refresh and ID tokens appear in no DB column after a successful callback."""
        web.add_user()
        resp, _, _, id_token = web.connect(web.login(), monkeypatch)
        assert _key(resp) == "connected"
        text = web.all_text()
        for secret in (_ACCESS, _REFRESH, id_token, _CODE, _CLIENT_SECRET):
            assert secret not in text

    def test_auth_twitch_callback_with_waiting_soft_account_opens_merge_prompt(self, db, oauth_env, monkeypatch, web):
        """AC Finishing step 6: when a soft account with the same twitch_account_id exists, the callback returns to Profile and GET /twitch/connection reports pending_merge."""
        from models import User
        web.run(lambda d: _soft_with_identity(d, cards=()))
        web.add_user()
        client = web.login()
        resp, _, _, _ = web.connect(client, monkeypatch)
        assert _key(resp) == "merge_ready"
        data = client.get("/twitch/connection").json()
        assert data["connected"] is True
        assert data["pending_merge"] == {"cards": 0, "tokens": 7}
        soft = web.rows(User, twitch_user_id=_OPAQUE)[0]
        assert soft.account_type == "twitch" and soft.twitch_account_id is None

    def test_auth_twitch_callback_id_held_by_other_website_account_conflict(self, db, oauth_env, monkeypatch, web):
        """AC Conflicts: sub already on another website account stores nothing and redirects with the "connected to another Kana Cards account" message key."""
        from models import User
        web.add_user("bob", twitch_account_id=_TWITCH_ID)
        uid = web.add_user()
        resp, _, _, _ = web.connect(web.login(), monkeypatch)
        assert _key(resp) == "in_use"
        assert web.get(User, uid).twitch_account_id is None
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        assert "This Twitch account is connected to another Kana Cards account" in js

    def test_auth_twitch_callback_account_has_different_id_conflict(self, db, oauth_env, monkeypatch, web):
        """AC Conflicts: this account already has a different twitch_account_id; nothing is stored and the redirect carries the "Disconnect your current Twitch account first" key."""
        from models import User
        uid = web.add_user(twitch_account_id="999")
        resp, _, _, _ = web.connect(web.login(), monkeypatch)
        assert _key(resp) == "disconnect_first"
        assert web.get(User, uid).twitch_account_id == "999"
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        assert "Disconnect your current Twitch account first" in js

    @pytest.mark.parametrize("case", ["missing", "unknown", "expired", "reused", "other_users"])
    def test_auth_twitch_callback_bad_state_stores_nothing(self, db, oauth_env, monkeypatch, web, case):
        """Failure path: a missing, unknown, expired, reused or someone else's state returns to Profile with a neutral error, never calls the token endpoint and stores nothing."""
        from models import AuditLog, TwitchOAuthState, User
        uid = web.add_user()
        client = web.login()
        if case == "reused":
            # A first, successful callback consumes the state.
            resp, _, params, _ = web.connect(client, monkeypatch, sub="111")
            assert _key(resp) == "connected"
            web.run(lambda d: (setattr(d.get(User, uid), "twitch_account_id", None), d.commit()))
        else:
            _, params = web.start(client)
        state = params["state"]
        if case == "other_users":
            web.add_user("bob")
            _, bob_params = web.start(web.login("bob"))
            state = bob_params["state"]
        if case == "expired":
            web.run(lambda d: (d.query(TwitchOAuthState).update({TwitchOAuthState.expires_at: int(time.time()) - 1}),
                               d.commit()))
        calls = _mock_twitch(monkeypatch, _id_token(_keys()[0], nonce=params["nonce"]))
        query = {"code": _CODE}
        if case != "missing":
            query["state"] = "not-a-real-state" if case == "unknown" else state
        audits_before = len(web.rows(AuditLog, action="twitch_connected"))
        resp = web.callback(client, **query)
        assert _key(resp) == "failed"
        assert calls == []  # the token endpoint is never called
        assert web.get(User, uid).twitch_account_id is None
        assert len(web.rows(AuditLog, action="twitch_connected")) == audits_before
        if case == "other_users":
            assert all(r.used_at is None for r in web.rows(TwitchOAuthState) if r.state_hash ==
                       hashlib.sha256(state.encode()).hexdigest())

    def test_auth_twitch_callback_twitch_error_param_stores_nothing(self, db, oauth_env, monkeypatch, web):
        """Failure path: ?error=access_denied (user cancelled) returns a neutral error and stores nothing."""
        from models import TwitchOAuthState, User
        uid = web.add_user()
        client = web.login()
        _, params = web.start(client)
        calls = _mock_twitch(monkeypatch, "unused")
        resp = web.callback(client, error="access_denied", error_description="The user denied you access",
                            state=params["state"])
        assert _key(resp) == "cancelled"
        assert "denied" not in resp.headers["location"]
        assert calls == []
        assert web.get(User, uid).twitch_account_id is None
        assert web.rows(TwitchOAuthState)[0].used_at is not None  # consumed

    def test_auth_twitch_callback_failed_code_exchange_stores_nothing(self, db, oauth_env, monkeypatch, web):
        """Failure path: a non-200 or raising token endpoint returns a neutral error and stores nothing."""
        import requests
        from models import User
        uid = web.add_user()
        client = web.login()
        for kwargs in ({"status": 400, "body": {"status": 400, "message": "Invalid authorization code"}},
                       {"raises": requests.Timeout("timed out")},
                       {"body": {"access_token": _ACCESS}}):  # 200 without an ID token
            _, params = web.start(client)
            calls = _mock_twitch(monkeypatch, None, **kwargs)
            resp = web.callback(client, code=_CODE, state=params["state"])
            assert _key(resp) == "failed"
            assert len(calls) == 1
            assert web.get(User, uid).twitch_account_id is None

    @pytest.mark.parametrize("bad", ["iss", "aud", "nonce", "signature", "expired"])
    def test_auth_twitch_callback_invalid_id_token_stores_nothing(self, db, oauth_env, monkeypatch, web, bad):
        """Failure path: an ID token with a wrong iss, aud or nonce, a signature from another key, or an expired exp is rejected; nothing is stored."""
        from models import AuditLog, User
        uid = web.add_user()
        client = web.login()
        _, params = web.start(client)
        private = _keys()[0]
        claims = {"sub": _TWITCH_ID, "nonce": params["nonce"]}
        if bad == "iss":
            claims["iss"] = "https://evil.example/oauth2"
        elif bad == "aud":
            claims["aud"] = "some-other-client"
        elif bad == "nonce":
            claims["nonce"] = "not-the-stored-nonce"
        elif bad == "signature":
            private = _keys("attacker")[0]
        elif bad == "expired":
            claims["exp_offset"] = -600
        _mock_twitch(monkeypatch, _id_token(private, **claims))
        resp = web.callback(client, code=_CODE, state=params["state"])
        assert _key(resp) == "failed"
        assert web.get(User, uid).twitch_account_id is None
        assert web.rows(AuditLog, action="twitch_connected") == []

    def test_auth_twitch_callback_without_session_stores_nothing(self, db, oauth_env, monkeypatch, web):
        """Failure path: a callback without a website session returns a neutral error and stores nothing (state is not consumed by a stranger)."""
        from models import TwitchOAuthState, User
        uid = web.add_user()
        _, params = web.start(web.login())
        calls = _mock_twitch(monkeypatch, "unused")
        stranger = web.client()
        resp = web.callback(stranger, code=_CODE, state=params["state"])
        assert _key(resp) == "no_session"
        assert calls == []
        assert web.rows(TwitchOAuthState)[0].used_at is None
        assert web.get(User, uid).twitch_account_id is None

    def test_session_cookie_samesite_lax_with_twitch_comment(self):
        """Step 7 Cookie: SessionMiddleware is configured with same_site="lax" (not strict) and a comment next to it names the Twitch sign-in callback."""
        import main
        kwargs = [m.kwargs for m in main.app.user_middleware if m.cls.__name__ == "SessionMiddleware"][0]
        assert kwargs["same_site"] == "lax"
        src = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")
        i = src.index('same_site="lax"')
        nearby = src[max(0, i - 600):i]
        assert "Twitch" in nearby and "callback" in nearby and "strict" in nearby.lower()

    def test_auth_twitch_callback_reads_session_without_origin_header(self, db, oauth_env, monkeypatch, web):
        """Step 7 Cookie: the callback, a GET with no Origin header, resolves the website session and succeeds."""
        from models import User
        uid = web.add_user()
        client = web.login()
        _, params = web.start(client)
        _mock_twitch(monkeypatch, _id_token(_keys()[0], nonce=params["nonce"]))
        resp = client.get("/auth/twitch/callback", params={"code": _CODE, "state": params["state"]},
                          headers={"Referer": "https://id.twitch.tv/"}, follow_redirects=False)
        assert "origin" not in {k.lower() for k in resp.request.headers.keys()}
        assert _key(resp) == "connected"
        assert web.get(User, uid).twitch_account_id == _TWITCH_ID

    def test_auth_twitch_endpoints_rate_limited(self, db, oauth_env):
        """Step 2 Rate limits: start and callback are both rate-limited (429 past the limit)."""
        import twitch_oauth
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from starlette.middleware.sessions import SessionMiddleware
        from database import get_db
        from tests.test_issue_157_twitch_extension_policy_compliance import _shared_db
        limit = int(twitch_oauth.RATE_LIMIT_TWITCH_OAUTH.split("/")[0])
        session = _shared_db()
        lim = twitch_oauth.limiter
        was = lim.enabled
        lim.enabled = True
        lim.reset()
        try:
            app = FastAPI()
            app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET)
            app.state.limiter = lim
            app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
            app.include_router(twitch_oauth.router)
            app.dependency_overrides[get_db] = lambda: session
            client = TestClient(app)
            for path in ("/auth/twitch/start", "/auth/twitch/callback"):
                for _ in range(limit):
                    assert client.get(path, follow_redirects=False).status_code == 303
                assert client.get(path, follow_redirects=False).status_code == 429
        finally:
            lim.enabled = was
            lim.reset()
            session.close()


# ---------------------------------------------------------------------------
# Story 2 — Merge My Twitch Collection
# ---------------------------------------------------------------------------

def _locked_week_with_points(db, web_user, soft, soft_card):
    """A locked week in progress: W and S each have a roster entry whose card scored in
    match 5001 (seed it first with _seed_world)."""
    from models import CardMatchPoints, Week, WeeklyRosterEntry
    now = int(time.time())
    week = Week(label="Week 3", start_time=now - 7200, end_time=now + 3600, is_locked=True)
    db.add(week)
    db.commit()
    w_card = _card(db, web_user.id, 102)
    db.add(CardMatchPoints(card_id=w_card.id, match_id=5001, player_id=102, points=12.0))
    db.add(CardMatchPoints(card_id=soft_card.id, match_id=5001, player_id=101, points=30.0))
    db.add(WeeklyRosterEntry(week_id=week.id, user_id=web_user.id, card_id=w_card.id))
    db.add(WeeklyRosterEntry(week_id=week.id, user_id=soft.id, card_id=soft_card.id, is_bench=False))
    db.commit()
    return week


def _week_points(db, week, user_id):
    from routers.leaderboard import weekly_leaderboard
    rows = {r["id"]: r["week_points"] for r in weekly_leaderboard(week_id=week.id, db=db)}
    return rows.get(user_id)


class TestMergeTwitchCollection:
    """Story: Merge My Twitch Collection."""

    def test_connection_pending_merge_counts(self, db, oauth_env):
        """AC Prompt: pending_merge reports S's card count and token count for W."""
        import twitch_oauth
        web_user, soft, _ = _pending_pair(db, cards=(101, 102, 103), tokens=4)
        assert twitch_oauth.connection_status(db, web_user)["pending_merge"] == {"cards": 3, "tokens": 4}
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        assert "Your Twitch collection: ${pending.cards} cards, ${pending.tokens} tokens. Add it to this account?" in js

    def test_merge_confirm_moves_cards_to_bench_and_adds_tokens(self, db):
        """AC Call: every card of S (duplicates kept) moves to W with is_active=false, slot_index=NULL; card_match_points follow the card; S's tokens are added to W; the reply has the counts."""
        from models import Card, CardMatchPoints
        web_user, soft, cards = _pending_pair(db)  # two cards of player 101, one active in slot 0
        db.add(CardMatchPoints(card_id=cards[0].id, match_id=5001, player_id=101, points=9.0))
        db.commit()
        result = _merge(db, web_user)
        assert result == {"merged": True, "cards": 2, "tokens": 7}
        moved = db.query(Card).filter(Card.id.in_([c.id for c in cards])).all()
        assert len(moved) == 2 and {c.player_id for c in moved} == {101}
        for card in moved:
            assert card.owner_id == web_user.id and card.is_active is False and card.slot_index is None
        assert db.query(CardMatchPoints).filter_by(card_id=cards[0].id).one().points == 9.0
        db.refresh(web_user)
        assert web_user.tokens == 12
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        assert "cards and ${data.tokens} tokens added" in js

    def test_merge_confirm_deletes_locked_week_entries_and_keeps_w_scores(self, db):
        """AC Call: S's locked-week weekly_roster_entries are deleted; W's past weekly scores and the leaderboards are unchanged."""
        from models import WeeklyRosterEntry
        from routers.cards import _build_roster_response
        from routers.leaderboard import compute_season_standings
        _seed_world(db)  # players 101-203 and match 5001 one hour ago
        web_user, soft, cards = _pending_pair(db)
        week = _locked_week_with_points(db, web_user, soft, cards[0])
        before_week = _week_points(db, week, web_user.id)
        before_roster = _build_roster_response(db, web_user.id, week.id)["combined_value"]
        before_season = {r["id"]: r["points"] for r in compute_season_standings(db)}
        assert before_week == 12.0
        soft_id = soft.id
        _merge(db, web_user)
        assert db.query(WeeklyRosterEntry).filter_by(user_id=soft_id).count() == 0
        assert _week_points(db, week, web_user.id) == before_week
        assert _build_roster_response(db, web_user.id, week.id)["combined_value"] == before_roster
        assert {r["id"]: r["points"] for r in compute_season_standings(db)} == before_season

    def test_merge_confirm_deletes_soft_account_via_delete_soft_account(self, db, monkeypatch):
        """AC Call / Step 7 Merge cleanup: S is deleted through soft_accounts.delete_soft_account after the cards moved; no row of any table in its list still references S, and its presence row is gone."""
        import soft_accounts
        from models import (Card, CodeRedemption, NotificationDismissal, PasswordResetToken,
                            TokenGrantClaim, TwitchLinkCode, TwitchPresence, User, UserSession,
                            UserTag, WeeklyRosterEntry, WeeklySummaryReveal, WeeklySummarySeen)
        web_user, soft, cards = _pending_pair(db)
        sid = soft.id
        db.add_all([
            WeeklyRosterEntry(week_id=1, user_id=sid, card_id=cards[0].id),
            WeeklySummaryReveal(week_id=1, user_id=sid, revealed_at=1),
            WeeklySummarySeen(user_id=sid, last_seen_week_id=1),
            CodeRedemption(code_id=1, user_id=sid, redeemed_at=1),
            TokenGrantClaim(event_id=1, user_id=sid, claimed_at=1),
            NotificationDismissal(notification_id=1, user_id=sid, dismissed_at=1),
            UserSession(sid_hash="a" * 64, user_id=sid, created_at=1, last_seen_at=1),
            UserTag(user_id=sid, tag_id=1, granted_at=1),
            TwitchLinkCode(code="ABC123", user_id=sid, expires_at=1),
            PasswordResetToken(token="reset-token-160", user_id=sid, expires_at=1),
        ])
        _present(db, _OPAQUE)
        calls = []
        real = soft_accounts.delete_soft_account

        def spy(db_, account):
            calls.append((account.id, db_.query(Card).filter(Card.owner_id == account.id).count()))
            return real(db_, account)

        monkeypatch.setattr(soft_accounts, "delete_soft_account", spy)
        _merge(db, web_user)
        assert calls == [(sid, 0)]  # called once for S, after its cards moved
        assert db.get(User, sid) is None
        for model in (WeeklyRosterEntry, WeeklySummaryReveal, WeeklySummarySeen, CodeRedemption,
                      TokenGrantClaim, NotificationDismissal, UserSession, UserTag, TwitchLinkCode,
                      PasswordResetToken):
            assert db.query(model).filter(model.user_id == sid).count() == 0, model.__name__
        assert db.query(TwitchPresence).filter_by(twitch_user_id=_OPAQUE).count() == 0

    def test_merge_confirm_moves_twitch_user_id_and_audits(self, db):
        """AC Call: W.twitch_user_id = S's former opaque id (cleared on S first), merged_soft_account_at is set, and twitch_account_merged is audited with both ids and the counts."""
        web_user, soft, _ = _pending_pair(db)
        sid = soft.id
        _merge(db, web_user)
        db.refresh(web_user)
        assert web_user.twitch_user_id == _OPAQUE
        assert web_user.twitch_account_id == _TWITCH_ID
        assert web_user.merged_soft_account_at is not None
        assert web_user.pending_merge_user_id is None
        details = _audits(db, "twitch_account_merged")
        assert len(details) == 1
        for part in (f"full_user_id={web_user.id}", f"soft_user_id={sid}", "cards=2", "tokens=7"):
            assert part in details[0]
        assert _OPAQUE not in details[0] and _TWITCH_ID not in details[0]

    def test_merge_confirm_second_merge_returns_409(self, db):
        """AC One merge ever: a website account with merged_soft_account_at set gets 409 for any further merge, even after a disconnect."""
        web_user, _, _ = _pending_pair(db)
        _merge(db, web_user)
        _join(db, "Uother", user_id="222")
        other = _user_by_opaque(db, "Uother")
        web_user.pending_merge_user_id = other.id
        db.commit()
        _raises(lambda: _merge(db, web_user), 409)
        assert db.get(type(other), other.id) is not None

    def test_merge_not_now_keeps_both_accounts(self, db):
        """AC Not now: without calling confirm both accounts are unchanged and GET /twitch/connection still reports pending_merge on the next visit."""
        import twitch_oauth
        from models import Card
        web_user, soft, cards = _pending_pair(db)
        first = twitch_oauth.connection_status(db, web_user)
        second = twitch_oauth.connection_status(db, web_user)
        assert first["pending_merge"] == second["pending_merge"] == {"cards": 2, "tokens": 7}
        db.refresh(soft)
        assert soft.twitch_user_id == _OPAQUE and soft.tokens == 7
        assert db.query(Card).filter_by(owner_id=soft.id).count() == 2
        assert web_user.tokens == 5 and web_user.merged_soft_account_at is None
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        body = js[js.index("function dismissTwitchMerge"):]
        body = body[:body.index("\n}\n")]
        assert "fetch" not in body  # Not now never calls the server

    def test_merge_confirm_no_soft_account_returns_404(self, db):
        """Failure path: no soft account with W's twitch_account_id gives 404."""
        import twitch_oauth
        web_user = _website_user(db, "alice")
        assert twitch_oauth.connect_account(db, web_user, _TWITCH_ID) == "connected"
        _raises(lambda: _merge(db, web_user), 404)

    def test_merge_confirm_stale_prompt_returns_404(self, db):
        """Failure path: S already merged or deleted between prompt and confirm gives 404."""
        import twitch
        from models import User
        web_user, soft, _ = _pending_pair(db)
        sid = soft.id
        twitch.leave(_viewer(_OPAQUE), db)  # S leaves in the panel (deleted)
        assert db.get(User, sid) is None
        _raises(lambda: _merge(db, web_user), 404)
        db.refresh(web_user)
        assert web_user.pending_merge_user_id is None  # the stale prompt is cleared
        assert web_user.merged_soft_account_at is None

    def test_merge_confirm_error_midway_rolls_back(self, db, monkeypatch):
        """Failure path: an exception injected part-way (e.g. in delete_soft_account) rolls the whole merge back: cards, tokens, roster entries, S and the log row are unchanged."""
        import soft_accounts
        from models import Card, TwitchMergeLog, User, WeeklyRosterEntry
        web_user, soft, cards = _pending_pair(db)
        db.add(WeeklyRosterEntry(week_id=1, user_id=soft.id, card_id=cards[0].id))
        db.commit()
        sid, wid = soft.id, web_user.id

        def boom(db_, account):
            raise RuntimeError("injected failure")

        monkeypatch.setattr(soft_accounts, "delete_soft_account", boom)
        with pytest.raises(RuntimeError):
            _merge(db, web_user)
        soft = db.get(User, sid)
        web_user = db.get(User, wid)
        assert soft is not None and soft.twitch_user_id == _OPAQUE and soft.tokens == 7
        assert {c.owner_id for c in db.query(Card).filter(Card.id.in_([c.id for c in cards]))} == {sid}
        assert web_user.tokens == 5 and web_user.twitch_user_id is None
        assert web_user.merged_soft_account_at is None and web_user.pending_merge_user_id == sid
        assert db.query(WeeklyRosterEntry).filter_by(user_id=sid).count() == 1
        assert db.query(TwitchMergeLog).count() == 0

    def test_merge_confirm_without_recent_reauth_returns_403(self, db, web):
        """Failure path: POST /twitch/merge/confirm without a recent password check returns 403 reauth_required."""
        from models import User
        web.run(lambda d: _soft_with_identity(d, cards=()))
        uid = web.add_user()
        web.run(lambda d: __import__("twitch_oauth").connect_account(d, d.get(User, uid), _TWITCH_ID))
        client = web.login(reauth=False)
        resp = client.post("/twitch/merge/confirm")
        assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"
        assert web.get(User, uid).merged_soft_account_at is None
        # After the password check the same call merges.
        assert client.post("/reauth", json={"password": _PASSWORD}).status_code == 200
        resp = client.post("/twitch/merge/confirm")
        assert resp.status_code == 200 and resp.json() == {"merged": True, "cards": 0, "tokens": 7}

    def test_users_merged_soft_account_at_migration_032(self):
        """Critical files: migration 032_users_merged_soft_account_at adds the nullable integer column to a legacy users table."""
        import migrate
        from sqlalchemy import text
        ids = [m[0] for m in migrate.MIGRATIONS]
        assert ("032_users_merged_soft_account_at", migrate._m032_users_merged_soft_account_at) in migrate.MIGRATIONS
        assert ids.index("032_users_merged_soft_account_at") == ids.index("031_users_twitch_soft_accounts") + 1
        engine = _legacy_users_engine()
        with engine.connect() as conn:
            migrate._m031_users_twitch_soft_accounts(conn)
            migrate._m032_users_merged_soft_account_at(conn)
            cols = {r[1]: r for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
            for name in ("merged_soft_account_at", "pending_merge_user_id"):
                assert name in cols
                assert cols[name][2].upper() == "INTEGER"
                assert cols[name][3] == 0  # nullable
            migrate._m032_users_merged_soft_account_at(conn)  # idempotent
            rows = conn.execute(text("SELECT merged_soft_account_at, pending_merge_user_id FROM users")).fetchall()
            assert all(tuple(r) == (None, None) for r in rows)


# ---------------------------------------------------------------------------
# Story 3 — Recognised in the Panel After Connecting
# ---------------------------------------------------------------------------

def _connected_website_user(db, tokens=5):
    import twitch_oauth
    user = _website_user(db, "alice", tokens=tokens)
    assert twitch_oauth.connect_account(db, user, _TWITCH_ID) == "connected"
    return user


class TestRecognisedInPanel:
    """Story: Recognised in the Panel After Connecting."""

    def test_join_returns_connected_website_account_not_409(self, db, twitch_env):
        """AC Lookup order: W holds twitch_account_id=X, no account on the opaque id; POST /twitch/join with user_id=X returns W (created=false, website_account=true, no new row, no 409 twitch_identity_in_use)."""
        from models import User
        web_user = _connected_website_user(db, tokens=9)
        count = db.query(User).count()
        data = _join(db, _WEB_OPAQUE, user_id=_TWITCH_ID)
        assert data["created"] is False and data["website_account"] is True and data["tokens"] == 9
        assert db.query(User).count() == count
        db.refresh(web_user)
        assert web_user.twitch_user_id == _WEB_OPAQUE
        _no_twitch_ids(data, _WEB_OPAQUE, _TWITCH_ID)

    def test_me_reports_connected_website_account_joined(self, db, twitch_env):
        """AC Lookup order: GET /twitch/me with user_id=X returns joined=true for W."""
        import twitch
        web_user = _connected_website_user(db, tokens=9)
        data = twitch.me(payload=_viewer(_WEB_OPAQUE, user_id=_TWITCH_ID), db=db)
        assert data["joined"] is True and data["website_account"] is True and data["tokens"] == 9
        db.refresh(web_user)
        assert web_user.twitch_user_id == _WEB_OPAQUE

    def test_joined_user_attaches_opaque_id_to_website_account(self, db, twitch_env):
        """AC Recognising: a panel game route (_joined_user, e.g. draw) with user_id=X and no soft account on the opaque id sets W.twitch_user_id to the opaque id and acts as W (W's tokens are spent)."""
        import twitch
        from models import Card
        _seed_world(db)
        web_user = _connected_website_user(db, tokens=5)
        twitch.draw(_viewer(_WEB_OPAQUE, user_id=_TWITCH_ID), db)
        db.refresh(web_user)
        assert web_user.twitch_user_id == _WEB_OPAQUE
        assert web_user.tokens == 4
        assert db.query(Card).filter_by(owner_id=web_user.id).count() == 1
        assert _audits(db, "twitch_panel_recognised") == [f"user_id={web_user.id}"]

    def test_drop_goes_to_recognised_website_account(self, db, twitch_env, monkeypatch):
        """AC Recognising: once W holds the opaque id, an MVP token drop for that viewer credits W."""
        import twitch
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        web_user = _connected_website_user(db, tokens=5)
        twitch.me(payload=_viewer(_WEB_OPAQUE, user_id=_TWITCH_ID), db=db)
        _present(db, _WEB_OPAQUE)
        result = _set_mvp(db)
        assert result["token_drop"]["winner_count"] == 1
        assert "winners" not in result["token_drop"] and "alice" not in json.dumps(result)
        db.refresh(web_user)
        assert web_user.tokens == 6

    def test_panel_keeps_acting_as_soft_account_until_merge(self, db, twitch_env):
        """AC Recognising: when a soft account S still uses the opaque id, join/me/game routes act as S and W.twitch_user_id is not set; the response says nothing about the website."""
        import twitch
        web_user, soft, _ = _pending_pair(db)
        v = _viewer(_OPAQUE, user_id=_TWITCH_ID)
        joined = _join(db, _OPAQUE, user_id=_TWITCH_ID)
        me = twitch.me(payload=v, db=db)
        teams = twitch.teams(payload=v, db=db)
        for out in (joined, me):
            assert out["website_account"] is False and out["tokens"] == 7
            text = json.dumps(out).lower()
            assert "alice" not in text and "merge" not in text and "website_user" not in text
        assert teams["tokens"] == 7
        db.refresh(web_user)
        db.refresh(soft)
        assert web_user.twitch_user_id is None
        assert soft.twitch_user_id == _OPAQUE and soft.twitch_account_id is None

    def test_profile_guidance_for_unshared_identity(self):
        """AC Website guidance: Profile carries "Joined on Twitch first? In the Kana Cards Twitch panel, open Settings and choose Share your Twitch identity, then reload this page."; the extension files don't."""
        line = ("Joined on Twitch first? In the Kana Cards Twitch panel, open Settings and choose "
                "Share your Twitch identity, then reload this page.")
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        assert line in html
        for path in (REPO_ROOT / "twitch-extension").glob("*.*"):
            if path.suffix in (".html", ".js", ".css"):
                assert "Joined on Twitch first?" not in path.read_text(encoding="utf-8"), path.name

    def test_unshared_soft_account_becomes_pending_after_identity_share(self, db, twitch_env):
        """Website guidance follow-up: a soft account that shares its identity after W connected becomes W's pending merge (so "reload this page" shows the prompt)."""
        import twitch
        import twitch_oauth
        _join(db, _OPAQUE)  # joined without the identity share
        soft = _user_by_opaque(db, _OPAQUE)
        web_user = _connected_website_user(db)
        assert twitch_oauth.connection_status(db, web_user)["pending_merge"] is None
        me = twitch.me(payload=_viewer(_OPAQUE, user_id=_TWITCH_ID), db=db)
        assert me["website_account"] is False  # still S
        db.refresh(web_user)
        assert web_user.pending_merge_user_id == soft.id
        assert twitch_oauth.connection_status(db, web_user)["pending_merge"] == {"cards": 0, "tokens": 5}

    def test_jwt_without_user_id_never_switches_account(self, db, twitch_env):
        """Failure path: a JWT without user_id never attaches the opaque id to W; join creates a soft account as in Part 1 and me without an account returns joined=false."""
        import twitch
        web_user = _connected_website_user(db)
        assert twitch.me(payload=_viewer(_WEB_OPAQUE), db=db) == {"joined": False, "can_join": True}
        data = _join(db, _WEB_OPAQUE)
        assert data["created"] is True and data["website_account"] is False
        db.refresh(web_user)
        assert web_user.twitch_user_id is None
        assert _user_by_opaque(db, _WEB_OPAQUE).account_type == "twitch"


# ---------------------------------------------------------------------------
# Story 4 — Disconnect and Retire Link Codes
# ---------------------------------------------------------------------------

def _disconnect(db, user):
    import twitch_oauth
    return twitch_oauth.disconnect(db, _acting(user))


class TestDisconnectAndRetireLinkCodes:
    """Story: Disconnect and Retire Link Codes."""

    def test_disconnect_clears_ids_keeps_cards_and_audits(self, db, twitch_env):
        """AC Disconnect: POST /twitch/disconnect clears twitch_account_id and twitch_user_id, keeps W's cards and tokens, and audits twitch_disconnected."""
        import twitch
        from models import Card, Player
        db.add(Player(id=101, name="Player101"))
        db.commit()
        web_user = _connected_website_user(db, tokens=8)
        _card(db, web_user.id, 101)
        twitch.me(payload=_viewer(_WEB_OPAQUE, user_id=_TWITCH_ID), db=db)
        _present(db, _WEB_OPAQUE)
        assert _disconnect(db, web_user) == {"connected": False, "changed": True}
        db.refresh(web_user)
        assert web_user.twitch_account_id is None and web_user.twitch_user_id is None
        assert web_user.tokens == 8 and db.query(Card).filter_by(owner_id=web_user.id).count() == 1
        assert _audits(db, "twitch_disconnected") == [f"user_id={web_user.id}"]

    def test_disconnect_panel_not_joined_then_new_soft_account(self, db, twitch_env):
        """AC Disconnect: afterwards GET /twitch/me returns joined=false for the viewer, and Join creates a new soft account."""
        import twitch
        web_user = _connected_website_user(db)
        v = _viewer(_WEB_OPAQUE, user_id=_TWITCH_ID)
        assert twitch.me(payload=v, db=db)["joined"] is True
        _disconnect(db, web_user)
        assert twitch.me(payload=v, db=db)["joined"] is False
        data = twitch.join(v, db)
        assert data["created"] is True and data["website_account"] is False
        new = _user_by_opaque(db, _WEB_OPAQUE)
        assert new.account_type == "twitch" and new.id != web_user.id
        assert new.twitch_account_id == _TWITCH_ID

    def test_disconnect_requires_recent_reauth(self, db, web):
        """AC Disconnect: POST /twitch/disconnect without a recent password check returns 403 reauth_required."""
        from models import User
        uid = web.add_user(twitch_account_id=_TWITCH_ID)
        client = web.login(reauth=False)
        resp = client.post("/twitch/disconnect")
        assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"
        assert web.get(User, uid).twitch_account_id == _TWITCH_ID
        assert client.post("/reauth", json={"password": _PASSWORD}).status_code == 200
        assert client.post("/twitch/disconnect").json() == {"connected": False, "changed": True}
        assert web.get(User, uid).twitch_account_id is None

    def test_disconnect_keeps_one_merge_limit(self, db):
        """AC Disconnect: merged_soft_account_at survives a disconnect, so a reconnect + merge still gets 409."""
        import twitch_oauth
        web_user, _, _ = _pending_pair(db)
        _merge(db, web_user)
        _disconnect(db, web_user)
        db.refresh(web_user)
        assert web_user.merged_soft_account_at is not None
        _join(db, "Usecond", user_id=_TWITCH_ID)  # a new soft account with the same Twitch id
        assert twitch_oauth.connect_account(db, web_user, _TWITCH_ID) == "merge_ready"
        assert twitch_oauth.connection_status(db, web_user)["merge_used"] is True
        _raises(lambda: _merge(db, web_user), 409)

    @pytest.mark.parametrize("method,path", [("post", "/twitch/link-code"), ("post", "/twitch/link"),
                                             ("get", "/twitch/status")])
    def test_retired_endpoints_return_404(self, method, path):
        """AC Retired: POST /twitch/link-code, POST /twitch/link and GET /twitch/status return 404 on the app."""
        import main
        from fastapi.testclient import TestClient
        resp = getattr(TestClient(main.app), method)(path, headers={"Authorization": "Bearer x"})
        assert resp.status_code == 404, resp.text

    def test_link_code_code_removed_table_kept(self, db):
        """AC Retired: twitch.py has no TwitchLinkCode usage or generate_link_code/link_account; the twitch_link_codes table still exists; Profile has no code UI."""
        import twitch
        from sqlalchemy import inspect
        src = (BACKEND_DIR / "twitch.py").read_text(encoding="utf-8")
        for gone in ("TwitchLinkCode", "def generate_link_code", "def link_account", '"/link-code"',
                     '"/link"', '"/status"', "RATE_LIMIT_TWITCH_LINK"):
            assert gone not in src, gone
        for name in ("generate_link_code", "link_account", "link_account_route", "viewer_status"):
            assert not hasattr(twitch, name), name
        assert "twitch_link_codes" in inspect(db.get_bind()).get_table_names()
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        for gone in ("Generate Twitch Code", "/twitch/link-code", "link-code-input"):
            assert gone not in html + js, gone

    def test_env_example_lists_oauth_variables(self):
        """AC Configuration: .env.example lists TWITCH_OAUTH_CLIENT_ID, TWITCH_OAUTH_CLIENT_SECRET and TWITCH_OAUTH_REDIRECT_URI with comments (redirect must equal the registered address)."""
        env = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        for name in ("TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET", "TWITCH_OAUTH_REDIRECT_URI"):
            assert f"# {name}=" in env, name
        block = env[env.index("Connect Twitch on the website"):env.index("# TWITCH_OAUTH_REDIRECT_URI=")]
        assert "registered" in block and "exactly" in block
        assert "TWITCH_EXTENSION_SECRET" in block  # the client secret is a separate secret

    @pytest.mark.parametrize("missing", ["TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET",
                                         "TWITCH_OAUTH_REDIRECT_URI"])
    def test_missing_config_start_503_and_connect_unavailable(self, db, oauth_env, monkeypatch, missing, web, tmp_path):
        """AC Configuration: with any TWITCH_OAUTH_* unset, GET /auth/twitch/start returns 503, GET /twitch/connection reports available=false, and `import main` still works."""
        from models import TwitchOAuthState
        monkeypatch.delenv(missing)
        web.add_user()
        client = web.login()
        resp = client.get("/auth/twitch/start", follow_redirects=False)
        assert resp.status_code == 503
        assert web.rows(TwitchOAuthState) == []
        assert client.get("/twitch/connection").json()["available"] is False
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        assert 'data.available ? "twitchConnectState" : "twitchUnavailableState"' in js
        if missing == "TWITCH_OAUTH_CLIENT_ID":
            env = {k: v for k, v in os.environ.items() if not k.startswith("TWITCH_OAUTH_")}
            env.update({"DEBUG": "true", "BACKGROUND_TASKS_ENABLED": "false",
                        "DATABASE_URL": f"sqlite:///{tmp_path / 'fantasy.db'}"})
            result = subprocess.run([sys.executable, "-c", "import main"], cwd=str(BACKEND_DIR),
                                    env=env, capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, result.stderr[-2000:]

    def test_privacy_page_describes_twitch_connection(self):
        """AC Docs: privacy.html describes the stored Twitch user id and that Twitch tokens aren't stored."""
        privacy = " ".join(re.sub(r"<[^>]+>", "", (FRONTEND_DIR / "privacy.html").read_text(encoding="utf-8")).split())
        assert "Connect Twitch" in privacy
        assert "We store only that Twitch user id" in privacy
        assert "The sign-in tokens Twitch returns are not stored" in privacy
        assert "Disconnecting on your Profile removes both ids" in privacy

    def test_disconnect_without_connection_is_noop_200(self, db, web):
        """Failure path: POST /twitch/disconnect for an account with no Twitch connection returns 200 and changes nothing (no audit entry required)."""
        from models import AuditLog
        web.add_user()
        client = web.login()
        resp = client.post("/twitch/disconnect")
        assert resp.status_code == 200 and resp.json() == {"connected": False, "changed": False}
        assert web.rows(AuditLog, action="twitch_disconnected") == []


# ---------------------------------------------------------------------------
# Story 5 — Recoverable and Contained
# ---------------------------------------------------------------------------

_ADMIN = {"user_id": 999, "username": "boss", "is_admin": True}


def _merged(db, with_week=True):
    """W merged S (two cards, 7 tokens, one locked-week roster row). Returns (W, log, card ids, week)."""
    from models import TwitchMergeLog
    week = None
    if with_week:
        _seed_world(db)
    web_user, soft, cards = _pending_pair(db)
    if with_week:
        week = _locked_week_with_points(db, web_user, soft, cards[0])
    _merge(db, web_user)
    log = db.query(TwitchMergeLog).one()
    return web_user, log, [c.id for c in cards], week


class TestRecoverableAndContained:
    """Story: Recoverable and Contained."""

    def test_merge_writes_complete_merge_log_row(self, db):
        """AC Undo log: a merge writes one twitch_merge_log row with full_user_id, merged_at, soft_snapshot (twitch_user_id, twitch_account_id, created_at, last_seen_at, tokens), card_ids, tokens_moved, roster_entries and reversed_at=NULL, before S is deleted."""
        from models import TwitchMergeLog
        _seed_world(db)
        web_user, soft, cards = _pending_pair(db)
        week = _locked_week_with_points(db, web_user, soft, cards[0])
        created, last_seen = soft.created_at, soft.last_seen_at
        before = int(time.time())
        _merge(db, web_user)
        log = db.query(TwitchMergeLog).one()
        assert log.full_user_id == web_user.id and before <= log.merged_at <= int(time.time())
        snapshot = json.loads(log.soft_snapshot)
        assert snapshot == {"twitch_user_id": _OPAQUE, "twitch_account_id": _TWITCH_ID,
                            "created_at": created, "last_seen_at": last_seen, "tokens": 7}
        assert json.loads(log.card_ids) == [c.id for c in cards]
        assert log.tokens_moved == 7
        entries = json.loads(log.roster_entries)
        assert len(entries) == 1
        assert entries[0]["week_id"] == week.id and entries[0]["card_id"] == cards[0].id
        assert entries[0]["is_bench"] is False and entries[0]["subbed_in"] is False
        assert log.reversed_at is None
        assert f"log_id={log.id}" in _audits(db, "twitch_account_merged")[0]

    def test_merge_log_purge_deletes_rows_older_than_30_days(self, db):
        """AC Undo log: the daily clean-up deletes twitch_merge_log rows older than 30 days (and expired twitch_oauth_states) and keeps newer rows."""
        import twitch_oauth
        from models import TwitchMergeLog, TwitchOAuthState
        now = int(time.time())
        for days in (31, 29):
            db.add(TwitchMergeLog(full_user_id=1, merged_at=now - days * 86400, soft_snapshot="{}",
                                  card_ids="[]", tokens_moved=0, roster_entries="[]"))
        db.add(TwitchOAuthState(state_hash="a" * 64, user_id=1, nonce="n", expires_at=now - 1))
        db.add(TwitchOAuthState(state_hash="b" * 64, user_id=1, nonce="n", expires_at=now + 600))
        db.add(TwitchOAuthState(state_hash="c" * 64, user_id=1, nonce="n", expires_at=now + 600, used_at=now))
        db.commit()
        assert twitch_oauth.cleanup(db, now) == {"states": 2, "merge_logs": 1}
        assert [l.merged_at for l in db.query(TwitchMergeLog).all()] == [now - 29 * 86400]
        assert [s.state_hash for s in db.query(TwitchOAuthState).all()] == ["b" * 64]
        main_src = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")
        loop = main_src[main_src.index("def _week_maintenance_loop"):main_src.index("def _profile_enrichment_loop")]
        assert "twitch_oauth.cleanup(" in loop

    def test_reverse_merge_restores_soft_account(self, db):
        """AC Admin reverse: reverse_merge recreates the soft account (new id) from the snapshot, moves the logged cards still on W back, restores the roster entries, clears W's twitch_account_id, twitch_user_id and merged_soft_account_at, sets reversed_at and audits twitch_merge_reversed."""
        import soft_accounts
        from models import Card, User, WeeklyRosterEntry
        web_user, log, card_ids, week = _merged(db)
        old_soft_ids = {u.id for u in db.query(User).all()}
        result = soft_accounts.reverse_merge(db, log, actor=_ADMIN)
        db.commit()
        soft = _user_by_opaque(db, _OPAQUE)
        assert soft is not None and soft.account_type == "twitch" and soft.id not in old_soft_ids
        assert soft.twitch_account_id == _TWITCH_ID and soft.tokens == 7
        assert result["soft_user_id"] == soft.id and result["cards_returned"] == 2
        assert {c.owner_id for c in db.query(Card).filter(Card.id.in_(card_ids))} == {soft.id}
        entries = db.query(WeeklyRosterEntry).filter_by(user_id=soft.id).all()
        assert [(e.week_id, e.card_id) for e in entries] == [(week.id, card_ids[0])]
        db.refresh(web_user)
        assert web_user.twitch_account_id is None and web_user.twitch_user_id is None
        assert web_user.merged_soft_account_at is None
        assert log.reversed_at is not None
        details = _audits(db, "twitch_merge_reversed")
        assert len(details) == 1 and f"log_id={log.id}" in details[0]
        # The legitimate owner can connect and merge again.
        import twitch_oauth
        assert twitch_oauth.connect_account(db, web_user, _TWITCH_ID) == "merge_ready"

    def test_reverse_merge_token_shortfall_reported(self, db):
        """AC Admin reverse: tokens_moved is subtracted from W never below 0; the shortfall is in the reply and the audit detail."""
        import soft_accounts
        web_user, log, _, _ = _merged(db, with_week=False)
        web_user.tokens = 2  # spent 10 of the 12 since the merge
        db.commit()
        result = soft_accounts.reverse_merge(db, log, actor=_ADMIN)
        db.commit()
        db.refresh(web_user)
        assert web_user.tokens == 0
        assert result["tokens_returned"] == 7 and result["token_shortfall"] == 5
        assert "token_shortfall=5" in _audits(db, "twitch_merge_reversed")[0]

    def test_admin_reverse_endpoint_requires_admin_and_reauth(self, db, web):
        """AC Admin reverse: POST /admin/twitch/merges/{log_id}/reverse returns 403 for a non-admin and 403 reauth_required for an admin without a recent /reauth."""
        web.add_user("alice")
        web.add_user("boss", is_admin=True)
        player = web.login("alice")
        for call in (lambda c: c.post("/admin/twitch/merges/1/reverse"),
                     lambda c: c.get("/admin/twitch/merges")):
            assert call(player).status_code == 403
            admin = web.login("boss", reauth=False)
            resp = call(admin)
            assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"
        admin = web.login("boss")
        assert admin.post("/admin/twitch/merges/12345/reverse").status_code == 404
        assert admin.get("/admin/twitch/merges").status_code == 200

    def test_admin_users_lists_recent_merges(self, db, web):
        """AC Admin reverse: the admin user list (or its merges endpoint) returns recent merges with log ids, and no Twitch ids."""
        from models import TwitchMergeLog
        web.run(lambda d: _merge(d, _pending_pair(d)[0]))
        web.add_user("boss", is_admin=True)
        admin = web.login("boss")
        rows = admin.get("/admin/twitch/merges").json()
        log = web.rows(TwitchMergeLog)[0]
        assert [r["id"] for r in rows] == [log.id]
        assert rows[0]["username"] == "alice" and rows[0]["cards"] == 2 and rows[0]["tokens_moved"] == 7
        assert rows[0]["reversible"] is True and rows[0]["reversed_at"] is None
        _no_twitch_ids(rows, _OPAQUE, _TWITCH_ID)
        resp = admin.post(f"/admin/twitch/merges/{log.id}/reverse")
        assert resp.status_code == 200 and resp.json()["cards_returned"] == 2
        rows = admin.get("/admin/twitch/merges").json()
        assert rows[0]["reversible"] is False and rows[0]["reversed_at"] is not None
        js = (FRONTEND_DIR / "app-admin-users.js").read_text(encoding="utf-8")
        assert "/admin/twitch/merges" in js and "Reverse" in js and "adminFetch" in js
        assert 'id="twitchMergesTable"' in (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    @pytest.mark.parametrize("case", ["older_than_30_days", "already_reversed", "after_season_reset"])
    def test_reverse_merge_failures_return_409_no_change(self, db, case):
        """Failure path: reversing a log row older than 30 days, already reversed, or whose cards no longer exist (season reset) returns 409 with a clear message and changes nothing."""
        import soft_accounts
        from models import Card, User
        from routers.admin_twitch import reverse_twitch_merge
        web_user, log, card_ids, _ = _merged(db, with_week=False)
        if case == "older_than_30_days":
            log.merged_at = int(time.time()) - 31 * 86400
        elif case == "already_reversed":
            soft_accounts.reverse_merge(db, log, actor=_ADMIN)
        else:
            db.query(Card).delete()
        db.commit()
        users_before = sorted((u.id, u.tokens, u.twitch_user_id, u.twitch_account_id)
                              for u in db.query(User).all())
        reversed_before = log.reversed_at
        exc = _raises(lambda: reverse_twitch_merge(log.id, admin=_ADMIN, db=db), 409)
        expected = {"older_than_30_days": "older than 30 days", "already_reversed": "already reversed",
                    "after_season_reset": "season reset"}[case]
        assert expected in exc.detail
        assert sorted((u.id, u.tokens, u.twitch_user_id, u.twitch_account_id)
                      for u in db.query(User).all()) == users_before
        db.refresh(log)
        assert log.reversed_at == reversed_before

    def test_kill_switches_documented_in_runbook(self):
        """AC Kill switches / runbook: markdown/features/reference/twitch-incident-runbook.md covers the TWITCH_OAUTH_* and TWITCH_DROPS_ENABLED switches, secret rotation, audit review (twitch_connected, twitch_account_merged, twitch_disconnected), reversal/backup restore, redirect address check and player communication."""
        doc = (REPO_ROOT / "markdown" / "features" / "reference" / "twitch-incident-runbook.md").read_text(encoding="utf-8")
        for needle in ("TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET", "TWITCH_OAUTH_REDIRECT_URI",
                       "TWITCH_DROPS_ENABLED", "TWITCH_EXTENSION_SECRET", "twitch_connected",
                       "twitch_account_merged", "twitch_disconnected", "/admin/twitch/merges",
                       "scripts/backup-db.sh", "redirect", "players"):
            assert needle in doc, needle
        assert "rotate" in doc.lower()

    def test_oauth_kill_switch_keeps_existing_connections_and_panel(self, db, twitch_env, monkeypatch):
        """AC Kill switches: with TWITCH_OAUTH_CLIENT_ID unset, an already connected W keeps its ids and the panel still recognises it."""
        import twitch
        import twitch_oauth
        web_user = _connected_website_user(db)
        monkeypatch.delenv("TWITCH_OAUTH_CLIENT_ID", raising=False)
        assert twitch_oauth.oauth_config() is None
        data = twitch.me(payload=_viewer(_WEB_OPAQUE, user_id=_TWITCH_ID), db=db)
        assert data["joined"] is True and data["website_account"] is True
        db.refresh(web_user)
        assert web_user.twitch_account_id == _TWITCH_ID and web_user.twitch_user_id == _WEB_OPAQUE
        status = twitch_oauth.connection_status(db, web_user)
        assert status["available"] is False and status["connected"] is True

    def test_no_route_response_schema_exposes_twitch_ids(self):
        """AC No public Twitch ids: no route's response model or schema has a twitch_user_id or twitch_account_id field."""
        import main
        from fastapi.routing import APIRoute
        from pydantic import TypeAdapter
        for route in main.app.routes:
            if isinstance(route, APIRoute) and route.response_model is not None:
                schema = json.dumps(TypeAdapter(route.response_model).json_schema())
                assert "twitch_user_id" not in schema and "twitch_account_id" not in schema, route.name
        # Routes return plain dicts: none names these fields as a key.
        paths = list((BACKEND_DIR / "routers").glob("*.py")) + [
            BACKEND_DIR / n for n in ("twitch.py", "twitch_oauth.py", "main.py")]
        for path in paths:
            assert not re.search(r"[\"']twitch_(user|account)_id[\"']\s*:", path.read_text(encoding="utf-8")), path.name

    def test_twitch_connection_and_admin_users_return_no_ids(self, db, twitch_env):
        """AC No public Twitch ids: GET /twitch/connection, GET /twitch/me and admin GET /users responses contain no Twitch id field names or values (booleans only)."""
        import twitch
        import twitch_oauth
        from routers.admin_users import list_users
        web_user, soft, _ = _pending_pair(db)
        _connected = _website_user(db, "carol")
        twitch_oauth.connect_account(db, _connected, "4242")
        twitch.me(payload=_viewer("Ucarol", user_id="4242"), db=db)
        outputs = [twitch_oauth.connection_status(db, web_user),
                   twitch_oauth.connection_status(db, _connected),
                   twitch.me(payload=_viewer(_OPAQUE, user_id=_TWITCH_ID), db=db),
                   twitch.me(payload=_viewer("Ucarol", user_id="4242"), db=db),
                   list_users(account_type="all", db=db, _=_ADMIN)]
        for out in outputs:
            _no_twitch_ids(out, _OPAQUE, _TWITCH_ID, "Ucarol", "4242")
        rows = {r["username"]: r for r in outputs[-1]}
        assert rows["carol"]["twitch_linked"] is True and rows["carol"]["twitch_identity_shared"] is True

    def test_leave_for_website_linked_account_only_unlinks(self, db, twitch_env):
        """AC Takeover containment: Leave for a website account recognised via user_id only clears twitch_user_id; cards, tokens, credentials and twitch_account_id are unchanged."""
        import twitch
        from models import Card, Player
        db.add(Player(id=101, name="Player101"))
        db.commit()
        web_user = _connected_website_user(db, tokens=6)
        _card(db, web_user.id, 101)
        v = _viewer(_WEB_OPAQUE, user_id=_TWITCH_ID)
        twitch.me(payload=v, db=db)
        password_hash, email = web_user.password_hash, web_user.email
        assert twitch.leave(v, db) == {"left": True, "deleted": False}
        db.refresh(web_user)
        assert web_user.twitch_user_id is None and web_user.twitch_account_id == _TWITCH_ID
        assert web_user.tokens == 6 and db.query(Card).filter_by(owner_id=web_user.id).count() == 1
        assert web_user.password_hash == password_hash and web_user.email == email

    def test_profile_shows_last_twitch_activity(self, db):
        """AC Takeover containment: Profile shows "Last Twitch activity: {date}" from last_seen_at (GET /twitch/connection or the profile endpoint returns it)."""
        import twitch_oauth
        web_user = _connected_website_user(db)
        web_user.last_seen_at = 1_790_000_000
        db.commit()
        assert twitch_oauth.connection_status(db, web_user)["last_twitch_activity_at"] == 1_790_000_000
        js = (FRONTEND_DIR / "app-profile.js").read_text(encoding="utf-8")
        assert "Last Twitch activity: ${" in js and "last_twitch_activity_at" in js
        assert 'id="twitchLastActivity"' in (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    def test_callback_never_logs_secrets_on_any_path(self, db, oauth_env, monkeypatch, caplog, web):
        """AC Secrets: driving the callback through success and every failure path with caplog at DEBUG, the authorization code, ID token, access token, refresh token and client secret never appear in any record."""
        import requests
        import main
        caplog.set_level(logging.DEBUG)
        web.add_user()
        client = web.login()
        secrets_seen = [_CODE, _ACCESS, _REFRESH, _CLIENT_SECRET]
        bad_body = {"access_token": _ACCESS, "refresh_token": _REFRESH, "message": f"bad code {_CODE}"}

        def run(mock_kwargs=None, claims=None, query=None, use_client=None):
            _, params = web.start(client)
            secrets_seen.extend([params["state"], params["nonce"]])
            token = _id_token(_keys()[0], nonce=params["nonce"], **(claims or {}))
            secrets_seen.append(token)
            _mock_twitch(monkeypatch, token, **(mock_kwargs or {}))
            q = {"code": _CODE, "state": params["state"], **(query or {})}
            return web.callback(use_client or client, **q)

        assert _key(run()) == "connected"
        web.run(lambda d: (setattr(d.query(__import__("models").User).first(), "twitch_account_id", None), d.commit()))
        assert _key(run(query={"state": "forged-state"})) == "failed"
        assert _key(run(query={"error": "access_denied", "error_description": f"denied {_CODE}"})) == "cancelled"
        assert _key(run(mock_kwargs={"status": 400, "body": bad_body})) == "failed"
        assert _key(run(mock_kwargs={"raises": requests.ConnectionError(f"boom {_CLIENT_SECRET}")})) == "failed"
        assert _key(run(claims={"aud": "other"})) == "failed"
        assert _key(run(claims={"exp_offset": -60})) == "failed"
        assert _key(run(use_client=web.client())) == "no_session"
        # httpx/httpcore records are the TestClient's own request lines (the browser
        # side), not the app's logs.
        app_records = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
        logged = "\n".join(f"{r.getMessage()} {r.args!r} {r.exc_text or ''}" for r in app_records)
        assert "Twitch sign-in" in logged  # the failures were logged, just without secrets
        for secret in secrets_seen:
            assert secret not in logged
        # uvicorn's access log line drops the callback's query string.
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                   ("1.2.3.4:5", "GET", f"/auth/twitch/callback?code={_CODE}&state=s1", "1.1", 303),
                                   None)
        assert any(isinstance(f, __import__("twitch_oauth").RedactSignInQuery)
                   for f in logging.getLogger("uvicorn.access").filters)
        for f in logging.getLogger("uvicorn.access").filters:
            f.filter(record)
        assert _CODE not in record.getMessage() and "/auth/twitch/callback" in record.getMessage()

    def test_backup_script_never_copies_env(self):
        """AC Secrets: scripts/backup-db.sh copies only the database file and never references .env."""
        src = (REPO_ROOT / "scripts" / "backup-db.sh").read_text(encoding="utf-8")
        assert ".env" not in src
        copies = [line for line in src.splitlines() if re.search(r"\b(cp|rsync|tar|scp)\b", line)
                  and not line.lstrip().startswith("#")]
        assert len(copies) == 1 and '"$DB"' in copies[0], copies

    def test_never_asks_for_passwords_text(self):
        """AC We never ask: Profile's Twitch section and privacy.html say "Kana Cards never asks for your Twitch or website password inside Twitch."."""
        line = "Kana Cards never asks for your Twitch or website password inside Twitch."
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        section = html[html.index('id="profileTwitchPanel"'):html.index("<!-- TAB: MY TEAM -->")]
        assert line in section
        privacy = " ".join(re.sub(r"<[^>]+>", "", (FRONTEND_DIR / "privacy.html").read_text(encoding="utf-8")).split())
        assert line in privacy
