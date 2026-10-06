"""Connect a Twitch account to a website account with Twitch sign-in (issue #160).

OpenID Connect, authorization code flow, used only to *connect* Twitch to a
logged-in website account (never as a login):

  GET  /auth/twitch/start      store a one-time sign-in attempt, redirect to Twitch
  GET  /auth/twitch/callback   check the attempt, swap the code, verify the ID token,
                               store its `sub` in users.twitch_account_id
  GET  /twitch/connection      Profile's Twitch state (never returns a Twitch id)
  POST /twitch/merge/confirm   move the waiting soft account into this account
  POST /twitch/disconnect      clear the connection

The access and refresh tokens Twitch returns are discarded: only the verified user
id is kept. Nothing here logs a code, token, ID token, state, nonce or the client
secret; failures log the exception class or HTTP status only.

Start and callback are top-level browser navigations, so they answer with redirects
back to the website's Profile (`/#profile?twitch=<key>`), never with Twitch data in
the URL. The callback relies on the session cookie being SameSite=Lax (main.py).

Configuration (all three required, read on each request; any missing turns
Connect Twitch off): TWITCH_OAUTH_CLIENT_ID, TWITCH_OAUTH_CLIENT_SECRET,
TWITCH_OAUTH_REDIRECT_URI (must exactly equal the address registered in the Twitch
developer console).
"""
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import jwt as pyjwt
import requests as _requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func

import sessions
import soft_accounts
from database import get_db
from deps import _audit, get_current_user, require_recent_player_reauth, session_user_or_none
from models import Card, TwitchOAuthState, TwitchPresence, User
from rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twitch-connection"])

AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
JWKS_URL = "https://id.twitch.tv/oauth2/keys"
ISSUER = "https://id.twitch.tv/oauth2"

# PKCE (S256) on the authorize request and the code swap. Switch off here, in one
# place, if the manual check shows Twitch ignores a wrong verifier (see
# markdown/features/reference/twitch-account-connection.md).
USE_PKCE = True

STATE_TTL = 600              # seconds a sign-in attempt stays valid
TOKEN_TIMEOUT = 10           # seconds for the server-side code swap
_QUERY_MAX = 2048            # longest code / state / error value accepted

RATE_LIMIT_TWITCH_OAUTH = os.getenv("RATE_LIMIT_TWITCH_OAUTH", "10/minute")

_ENV_KEYS = ("TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET", "TWITCH_OAUTH_REDIRECT_URI")

# Twitch's signing keys, fetched on first use and cached by PyJWKClient.
_jwks_client = None


class RedactSignInQuery(logging.Filter):
    """Drop the query string (code, state, error text) of /auth/twitch/* requests from
    uvicorn's access log lines. main.py installs it on the "uvicorn.access" logger."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith("/auth/twitch/") and "?" in path:
                record.args = args[:2] + (path.split("?", 1)[0] + "?[redacted]",) + args[3:]
        return True


def _now() -> int:
    return int(time.time())


def oauth_config() -> dict | None:
    """The three TWITCH_OAUTH_* values, or None when any is missing (kill switch)."""
    values = {k: os.getenv(k, "").strip() for k in _ENV_KEYS}
    if not all(values.values()):
        return None
    return {"client_id": values["TWITCH_OAUTH_CLIENT_ID"],
            "client_secret": values["TWITCH_OAUTH_CLIENT_SECRET"],
            "redirect_uri": values["TWITCH_OAUTH_REDIRECT_URI"]}


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = pyjwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600,
                                         timeout=TOKEN_TIMEOUT)
    return _jwks_client


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pkce_challenge(verifier: str) -> str:
    """base64url(sha256(verifier)) without padding (RFC 7636 S256)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _profile_redirect(key: str) -> RedirectResponse:
    """Back to the website's Profile with a message key the frontend maps to text."""
    return RedirectResponse(f"/#profile?twitch={key}", status_code=303)


class _SignInFailed(Exception):
    """A callback step failed; the message is a log-safe reason (no Twitch data)."""


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

def start(request: Request, db):
    cfg = oauth_config()
    if cfg is None:
        raise HTTPException(status_code=503, detail="twitch_connect_unavailable")
    user = session_user_or_none(request, db)
    if user is None:
        return _profile_redirect("login_required")
    if not sessions.reauth_is_recent(sessions.current_row(request, db)):
        return _profile_redirect("reauth_required")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(32) if USE_PKCE else None
    now = _now()
    # One live attempt per user; older unused ones are dropped.
    db.query(TwitchOAuthState).filter(TwitchOAuthState.user_id == user.id,
                                      TwitchOAuthState.used_at.is_(None)).delete(
        synchronize_session=False)
    db.add(TwitchOAuthState(state_hash=_hash(state), user_id=user.id, nonce=nonce,
                            code_verifier=verifier, expires_at=now + STATE_TTL))
    db.commit()

    params = {"client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"],
              "response_type": "code", "scope": "openid", "state": state, "nonce": nonce}
    if verifier:
        params["code_challenge"] = pkce_challenge(verifier)
        params["code_challenge_method"] = "S256"
    return RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}", status_code=303)


@router.get("/auth/twitch/start")
@limiter.limit(RATE_LIMIT_TWITCH_OAUTH)
def start_route(request: Request, db=Depends(get_db)):
    """Begin connecting Twitch (needs a recent password check on this session)."""
    return start(request, db)


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------

def _query(request: Request, name: str) -> str | None:
    value = request.query_params.get(name)
    if value is None or value == "" or len(value) > _QUERY_MAX:
        return None
    return value


def _exchange_code(cfg: dict, code: str, verifier: str | None) -> str:
    """Swap the code for tokens server-side; return only the ID token."""
    data = {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": cfg["redirect_uri"]}
    if verifier:
        data["code_verifier"] = verifier
    try:
        resp = _requests.post(TOKEN_URL, data=data, timeout=TOKEN_TIMEOUT)
    except Exception as exc:
        raise _SignInFailed(f"token request error ({type(exc).__name__})") from None
    if resp.status_code != 200:
        raise _SignInFailed(f"token endpoint returned HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:
        raise _SignInFailed("token endpoint returned a non-JSON body") from None
    id_token = body.get("id_token") if isinstance(body, dict) else None
    # The access and refresh tokens are dropped here and never stored or logged.
    del body
    if not isinstance(id_token, str) or not id_token:
        raise _SignInFailed("token response had no ID token")
    return id_token


def _verify_id_token(cfg: dict, id_token: str, expected_nonce: str) -> str:
    """Check the ID token's RS256 signature (Twitch's published keys), iss, aud, exp and
    nonce; return its `sub`."""
    try:
        key = _get_jwks_client().get_signing_key_from_jwt(id_token).key
        claims = pyjwt.decode(id_token, key, algorithms=["RS256"], audience=cfg["client_id"],
                              issuer=ISSUER, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except Exception as exc:
        raise _SignInFailed(f"ID token rejected ({type(exc).__name__})") from None
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not hmac.compare_digest(nonce, expected_nonce):
        raise _SignInFailed("ID token rejected (nonce mismatch)")
    sub = claims.get("sub")
    if not sub or not str(sub).isdigit():
        raise _SignInFailed("ID token rejected (bad sub)")
    return str(sub)


def callback(request: Request, db):
    cfg = oauth_config()
    if cfg is None:
        return _profile_redirect("unavailable")
    # 1. The website session that started the flow (needs SameSite=Lax, see main.py).
    user = session_user_or_none(request, db)
    if user is None:
        logger.warning("Twitch sign-in callback without a website session")
        return _profile_redirect("no_session")

    # 2. The one-time attempt: known, unexpired, unused, and this user's.
    state = _query(request, "state")
    row = db.get(TwitchOAuthState, _hash(state)) if state else None
    now = _now()
    if row is None or row.user_id != user.id or row.used_at is not None or row.expires_at < now:
        logger.warning("Twitch sign-in callback refused for user %s: invalid sign-in attempt", user.id)
        return _profile_redirect("failed")
    # 3. Consumed on first use, whatever happens next.
    row.used_at = now
    db.commit()

    if request.query_params.get("error"):
        logger.info("Twitch sign-in cancelled or refused by Twitch for user %s", user.id)
        return _profile_redirect("cancelled")
    code = _query(request, "code")
    if code is None:
        logger.warning("Twitch sign-in callback for user %s had no code", user.id)
        return _profile_redirect("failed")

    # 4-5. Code swap and ID token checks.
    try:
        id_token = _exchange_code(cfg, code, row.code_verifier)
        sub = _verify_id_token(cfg, id_token, row.nonce)
    except _SignInFailed as exc:
        logger.warning("Twitch sign-in failed for user %s: %s", user.id, exc)
        return _profile_redirect("failed")
    del id_token, code

    # 6-7. Conflicts, then store.
    return _profile_redirect(connect_account(db, user, sub))


def connect_account(db, user: User, sub: str) -> str:
    """Store a verified Twitch user id on a website account; return the Profile
    message key. Commits when something is stored.

    - this account already has a different id: "disconnect_first";
    - another website account has it: "in_use";
    - a soft account has it (identity share): the id moves to this account (the column
      is unique) and the soft account waits to be merged ("merge_ready"); it keeps its
      opaque id, so the panel acts as it until the merge."""
    if user.twitch_account_id:
        return "connected" if user.twitch_account_id == sub else "disconnect_first"
    holder = soft_accounts.find_by_twitch_account_id(db, sub)
    if holder is not None and holder.account_type != soft_accounts.SOFT:
        return "in_use"
    pending = None
    if holder is not None:
        holder.twitch_account_id = None
        db.flush()
        pending = holder.id
    user.twitch_account_id = sub
    user.pending_merge_user_id = pending
    _audit(db, "twitch_connected", actor_id=user.id, actor_username=user.display_name,
           detail=f"user_id={user.id}" + (f" pending_merge_user_id={pending}" if pending else ""))
    db.commit()
    return "merge_ready" if pending else "connected"


@router.get("/auth/twitch/callback")
@limiter.limit(RATE_LIMIT_TWITCH_OAUTH)
def callback_route(request: Request, db=Depends(get_db)):
    """Twitch returns here (code, state; or error) after the sign-in."""
    return callback(request, db)


# ---------------------------------------------------------------------------
# Connection status, merge, disconnect (session cookie)
# ---------------------------------------------------------------------------

def _pending_soft_account(db, user: User) -> User | None:
    if not user.pending_merge_user_id:
        return None
    soft = db.get(User, user.pending_merge_user_id)
    if soft is None or soft.account_type != soft_accounts.SOFT:
        return None
    return soft


def connection_status(db, user: User) -> dict:
    """Profile's Twitch state. Never includes a Twitch id."""
    soft = _pending_soft_account(db, user)
    pending = None
    if soft is not None:
        cards = db.query(func.count(Card.id)).filter(Card.owner_id == soft.id).scalar() or 0
        pending = {"cards": int(cards), "tokens": int(soft.tokens or 0)}
    return {
        "available": oauth_config() is not None,
        "connected": bool(user.twitch_account_id),
        "pending_merge": pending,
        "merge_used": user.merged_soft_account_at is not None,
        "last_twitch_activity_at": user.last_seen_at,
    }


@router.get("/twitch/connection")
def get_connection(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    return connection_status(db, db.get(User, current_user["user_id"]))


def merge_confirm(db, current_user: dict) -> dict:
    user = db.get(User, current_user["user_id"])
    if user.merged_soft_account_at is not None:
        raise HTTPException(status_code=409, detail="This account already added a Twitch collection")
    if not user.pending_merge_user_id:
        raise HTTPException(status_code=404, detail="No Twitch collection is waiting")
    soft = _pending_soft_account(db, user)
    if soft is None:
        user.pending_merge_user_id = None
        db.commit()
        raise HTTPException(status_code=404, detail="That Twitch collection is gone; refresh the page")
    try:
        result = soft_accounts.merge_soft_into(db, soft, user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"merged": True, "cards": result["cards"], "tokens": result["tokens"]}


@router.post("/twitch/merge/confirm")
def merge_confirm_route(current_user: dict = Depends(require_recent_player_reauth),
                        db=Depends(get_db)):
    """Add the waiting Twitch collection to this account (one merge per account, ever)."""
    return merge_confirm(db, current_user)


def disconnect(db, current_user: dict) -> dict:
    user = db.get(User, current_user["user_id"])
    if not (user.twitch_account_id or user.twitch_user_id or user.pending_merge_user_id):
        return {"connected": False, "changed": False}
    opaque_id = user.twitch_user_id
    user.twitch_account_id = None
    user.twitch_user_id = None
    user.pending_merge_user_id = None
    if opaque_id:
        db.query(TwitchPresence).filter(TwitchPresence.twitch_user_id == opaque_id).delete(
            synchronize_session=False)
    _audit(db, "twitch_disconnected", actor_id=user.id, actor_username=user.display_name,
           detail=f"user_id={user.id}")
    db.commit()
    return {"connected": False, "changed": True}


@router.post("/twitch/disconnect")
def disconnect_route(current_user: dict = Depends(require_recent_player_reauth),
                     db=Depends(get_db)):
    """Disconnect Twitch. The account keeps its cards and tokens; the one-merge limit stays."""
    return disconnect(db, current_user)


# ---------------------------------------------------------------------------
# Daily clean-up (main._week_maintenance_loop)
# ---------------------------------------------------------------------------

def cleanup(db, now: int | None = None) -> dict:
    """Delete expired or used sign-in attempts and undo-log rows older than 30 days. Commits."""
    now = int(now if now is not None else _now())
    states = (db.query(TwitchOAuthState)
              .filter((TwitchOAuthState.expires_at < now) | (TwitchOAuthState.used_at.isnot(None)))
              .delete(synchronize_session=False))
    logs = soft_accounts.purge_old_merge_logs(db, now)
    db.commit()
    return {"states": states, "merge_logs": logs}
