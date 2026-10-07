"""Steam sign-in through Steam OpenID 2.0 (issue #150).

  GET  /auth/steam/start      purpose=login | link | reauth; store a one-time attempt,
                              set the state cookie, redirect to steamcommunity.com
  GET  /auth/steam/callback   check the assertion (every check below), then sign in,
                              start a sign-up, link, or mark a re-auth
  POST /auth/steam/signup     a new Steam player picks a display name; creates the account
  POST /profile/steam/unlink  clear the link (accounts that also have a password only)

Every route answers 404 unless LOGIN_METHOD is `both` or `steam_signup`
(login_mode.py). The OpenID return address and realm are built from APP_BASE_URL,
never from the request; without APP_BASE_URL, start answers 503 steam_unavailable.

The callback accepts an assertion only when all of these hold (verify_assertion):
the OpenID 2.0 namespace and mode id_res; op_endpoint exactly STEAM_OPENID; a
claimed_id of the form https://steamcommunity.com/openid/id/<17 digits> equal to
identity; return_to equal to the callback address with this attempt's state; the
signed list covering the fields Steam signs; a response_nonce at most 5 minutes old
and never seen before; and a server-side check_authentication POST to the
hard-coded STEAM_OPENID answering a line exactly `is_valid:true`. Repeated
parameters, values over 2048 characters and query strings over 8 KB are refused.

Nothing here logs the callback query string, the signature, the nonce or the
assoc handle; failures log a reason only. RedactSignInQuery (twitch_oauth.py)
strips /auth/steam/* queries from uvicorn's access log. No Steam Web API key is
used and the Steam persona name is never fetched.
"""
import calendar
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from urllib.parse import urlencode

import requests as _requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

import login_mode
import sessions
from auth import check_reserved, check_username, username_taken
from database import get_db
from deps import _audit, require_recent_player_reauth, session_user_or_none
from models import SteamLoginState, SteamOpenIdNonce, SteamPendingSignup, User
from rate_limit import limiter
from seed import seed_admin_steam_ids

logger = logging.getLogger(__name__)

router = APIRouter(tags=["steam-login"])

STEAM_OPENID = "https://steamcommunity.com/openid/login"   # hard-coded, never from the request
NS = "http://specs.openid.net/auth/2.0"
IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
CLAIMED_RE = re.compile(r"https://steamcommunity\.com/openid/id/([0-9]{17})")
REQUIRED_SIGNED = {"op_endpoint", "claimed_id", "identity", "return_to",
                   "response_nonce", "assoc_handle"}
STEAM32_OFFSET = 76561197960265728

STATE_TTL = 600             # seconds a sign-in attempt stays valid
SIGNUP_TTL = 900            # seconds a pending sign-up stays valid
NONCE_MAX_AGE = 300         # seconds; also the allowed clock skew into the future
NONCE_RETENTION = 86400     # used nonces are pruned after a day
CHECK_TIMEOUT = 10          # seconds for check_authentication
_VALUE_MAX = 2048
_QUERY_MAX = 8192

PURPOSES = ("login", "link", "reauth")
RETURN_TABS = ("profile", "admin")   # re-auth may only return to these tabs

RATE_LIMIT_STEAM_CALLBACK = os.getenv("RATE_LIMIT_STEAM_CALLBACK", "10/minute")

_STATE_COOKIE = "kc_steam_state"
_SIGNUP_COOKIE = "kc_steam_signup"


class _SignInFailed(Exception):
    """A callback check failed; the message is a log-safe reason (no OpenID data)."""


class _SteamUnavailable(_SignInFailed):
    """check_authentication could not be completed (timeout, network, Steam error)."""


def _now() -> int:
    return int(time.time())


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _eq(a: str, b: str) -> bool:
    """Constant-time comparison that also accepts non-ASCII input."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _secure_cookies(base: str | None) -> bool:
    """__Host- prefix and Secure, except for plain-HTTP local development."""
    return not (base or "").startswith("http://localhost")


def _cookie_name(base: str | None, name: str) -> str:
    return f"__Host-{name}" if _secure_cookies(base) else name


def _set_cookie(response, base, name, value, max_age):
    response.set_cookie(_cookie_name(base, name), value, max_age=max_age, path="/",
                        secure=_secure_cookies(base), httponly=True, samesite="lax")


def _delete_cookie(response, base, name):
    response.delete_cookie(_cookie_name(base, name), path="/", secure=_secure_cookies(base),
                           httponly=True, samesite="lax")


def callback_url(base: str, state: str) -> str:
    return f"{base}/auth/steam/callback?{urlencode({'state': state})}"


def _redirect(tab: str, key: str) -> RedirectResponse:
    """Back to the website with a message key the frontend maps to text."""
    return RedirectResponse(f"/#{tab}?steam={key}", status_code=303)


def steam32(steam64: str) -> int:
    return int(steam64) - STEAM32_OFFSET


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

def start(request: Request, db, purpose: str, return_tab: str | None = None):
    base = login_mode.app_base_url()
    if base is None:
        return JSONResponse({"detail": "steam_unavailable"}, status_code=503)
    if purpose not in PURPOSES:
        return JSONResponse({"detail": "Unknown purpose"}, status_code=400)
    # The allowlist's own constant, never the request's string, goes into the redirect.
    tab = next((t for t in RETURN_TABS if t == return_tab), "profile")

    user = None
    if purpose in ("link", "reauth"):
        user = session_user_or_none(request, db)
        if user is None:
            return _redirect(tab, "login_required")
        if purpose == "link":
            if user.is_demo:
                return _redirect("profile", "not_allowed")
            if user.steam_id:
                return _redirect("profile", "linked")
            if not sessions.reauth_is_recent(sessions.current_row(request, db)):
                return _redirect("profile", "reauth_required")
        elif not user.steam_id:
            return _redirect(tab, "not_linked")

    state = secrets.token_urlsafe(32)
    now = _now()
    if user is not None:
        # One live attempt per user; older unused ones are dropped.
        db.query(SteamLoginState).filter(SteamLoginState.user_id == user.id,
                                         SteamLoginState.used_at.is_(None)).delete(
            synchronize_session=False)
    db.add(SteamLoginState(state_hash=_hash(state), purpose=purpose,
                           user_id=user.id if user else None,
                           return_tab=tab if purpose == "reauth" else None,
                           expires_at=now + STATE_TTL))
    db.commit()

    params = {
        "openid.ns": NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": callback_url(base, state),
        "openid.realm": f"{base}/",
        "openid.identity": IDENTIFIER_SELECT,
        "openid.claimed_id": IDENTIFIER_SELECT,
    }
    response = RedirectResponse(f"{STEAM_OPENID}?{urlencode(params)}", status_code=303)
    _set_cookie(response, base, _STATE_COOKIE, state, STATE_TTL)
    return response


@router.get("/auth/steam/start", dependencies=[Depends(login_mode.require_steam)])
@limiter.limit(RATE_LIMIT_STEAM_CALLBACK)
def start_route(request: Request, purpose: str = "login", return_tab: str | None = None,
                db=Depends(get_db)):
    """Begin a Steam sign-in, link (needs a recent check) or re-auth (needs a session)."""
    return start(request, db, purpose, return_tab)


# ---------------------------------------------------------------------------
# Assertion checks
# ---------------------------------------------------------------------------

def _query_params(request: Request) -> dict[str, str]:
    """The callback's parameters as a plain dict, refusing repeats and over-long input."""
    if len(request.scope.get("query_string", b"")) > _QUERY_MAX:
        raise _SignInFailed("query string too long")
    params: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key in params:
            raise _SignInFailed("repeated parameter")
        if len(value) > _VALUE_MAX:
            raise _SignInFailed("parameter value too long")
        params[key] = value
    return params


def _nonce_time(nonce: str) -> int:
    try:
        return calendar.timegm(time.strptime(nonce[:20], "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, OverflowError):
        raise _SignInFailed("malformed response nonce") from None


def _check_authentication(params: dict[str, str]) -> bool:
    """Ask Steam (the hard-coded endpoint) whether it really issued this assertion."""
    data = {k: v for k, v in params.items() if k.startswith("openid.")}
    data["openid.mode"] = "check_authentication"
    try:
        resp = _requests.post(STEAM_OPENID, data=data, timeout=CHECK_TIMEOUT,
                              allow_redirects=False)
    except Exception as exc:
        raise _SteamUnavailable(f"check_authentication error ({type(exc).__name__})") from None
    if resp.status_code >= 500:
        raise _SteamUnavailable(f"check_authentication returned HTTP {resp.status_code}")
    return resp.status_code == 200 and "is_valid:true" in (resp.text or "").splitlines()


def verify_assertion(db, params: dict[str, str], expected_return_to: str) -> str:
    """Every check from the story, in order; returns the Steam64 id or raises
    _SignInFailed (a log-safe reason, never the query). Records the nonce."""
    if params.get("openid.ns") != NS:
        raise _SignInFailed("wrong namespace")
    mode = params.get("openid.mode")
    if mode != "id_res":
        raise _SignInFailed("cancelled" if mode == "cancel" else "not a positive assertion")
    if params.get("openid.op_endpoint") != STEAM_OPENID:
        raise _SignInFailed("foreign op_endpoint")
    claimed = params.get("openid.claimed_id") or ""
    match = CLAIMED_RE.fullmatch(claimed)
    if match is None:
        raise _SignInFailed("malformed claimed_id")
    if params.get("openid.identity") != claimed:
        raise _SignInFailed("claimed_id and identity differ")
    if not _eq(params.get("openid.return_to") or "", expected_return_to):
        raise _SignInFailed("return_to mismatch")
    signed = set((params.get("openid.signed") or "").split(","))
    if not REQUIRED_SIGNED <= signed:
        raise _SignInFailed("required fields not signed")
    nonce = params.get("openid.response_nonce") or ""
    issued = _nonce_time(nonce)
    now = _now()
    if now - issued > NONCE_MAX_AGE or issued - now > NONCE_MAX_AGE:
        raise _SignInFailed("stale response nonce")
    # Recorded before the network call, so two concurrent replays can't both pass.
    db.add(SteamOpenIdNonce(nonce_hash=_hash(nonce), created_at=now))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _SignInFailed("replayed response nonce") from None
    if not _check_authentication(params):
        raise _SignInFailed("check_authentication did not confirm the assertion")
    return match.group(1)


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def _supersede_player_id_claims(db, user: User, player_id: int) -> None:
    """Clear the same self-reported player id on other accounts (audited)."""
    others = (db.query(User).filter(User.player_id == player_id, User.id != user.id).all())
    for other in others:
        other.player_id = None
        _audit(db, "player_id_claim_superseded", actor_id=user.id,
               actor_username=user.display_name,
               detail=f"user_id={other.id} verified_user_id={user.id} player_id={player_id}")


def _apply_admin_seed(db, user: User, steam64: str) -> None:
    """Promote a listed Steam id (SEED_ADMIN_STEAM_IDS) once per account. Never demotes;
    never a demo account. The first time a listed id signs in, the account is marked
    (admin_seed_applied_at) even if it is already an admin, so a later in-app demotion
    sticks while the id stays listed instead of being undone at the next sign-in."""
    if user.is_demo or user.admin_seed_applied_at is not None or steam64 not in seed_admin_steam_ids():
        return
    user.admin_seed_applied_at = int(time.time())
    if user.is_admin:
        return
    user.is_admin = True
    _audit(db, "admin_seeded_from_env", actor_id=user.id, actor_username=user.display_name,
           detail=f"user_id={user.id} source=SEED_ADMIN_STEAM_IDS")


def _find_by_steam_id(db, steam64: str) -> User | None:
    return (db.query(User).filter(User.steam_id == steam64, User.is_demo.is_(False),
                                  User.account_type != "twitch").first())


def link_account(db, user: User, steam64: str) -> str:
    """Store a verified Steam id on a logged-in account; return the Profile message key.
    Commits when something is stored."""
    if user.is_demo:
        return "not_allowed"
    if user.steam_id:
        return "linked" if user.steam_id == steam64 else "unlink_first"
    holder = db.query(User).filter(User.steam_id == steam64).first()
    if holder is not None:
        return "in_use"
    user.steam_id = steam64
    user.player_id = steam32(steam64)
    _supersede_player_id_claims(db, user, user.player_id)
    _audit(db, "steam_linked", actor_id=user.id, actor_username=user.display_name,
           detail=f"user_id={user.id}")
    _apply_admin_seed(db, user, steam64)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "in_use"
    return "linked"


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------

def _fail(response, base, reason: str):
    logger.warning("Steam sign-in failed: %s", reason)
    _delete_cookie(response, base, _STATE_COOKIE)
    return response


def callback(request: Request, db):
    base = login_mode.app_base_url()
    if base is None:
        return _redirect("login", "unavailable")

    # 1. The one-time attempt: the state in the query equals the cookie, and its hash
    #    is a known, unexpired, unused row. Used up on first use, whatever happens next.
    states = [v for k, v in request.query_params.multi_items() if k == "state"]
    state = states[0] if len(states) == 1 and 0 < len(states[0]) <= _VALUE_MAX else None
    cookie = request.cookies.get(_cookie_name(base, _STATE_COOKIE))
    if state is None or not cookie or not _eq(cookie, state):
        return _fail(_redirect("login", "failed"), base, "state missing or not matching the cookie")
    row = db.get(SteamLoginState, _hash(state))
    now = _now()
    if row is None or row.used_at is not None or row.expires_at < now:
        return _fail(_redirect("login", "failed"), base, "unknown, used or expired state")
    row.used_at = now
    db.commit()
    tab = {"login": "login", "link": "profile"}.get(row.purpose, row.return_tab or "profile")

    # 2. The assertion itself.
    try:
        params = _query_params(request)
        steam64 = verify_assertion(db, params, callback_url(base, state))
    except _SteamUnavailable as exc:
        return _fail(_redirect(tab, "unavailable"), base, str(exc))
    except _SignInFailed as exc:
        key = "cancelled" if str(exc) == "cancelled" else "failed"
        return _fail(_redirect(tab, key), base, str(exc))
    del params

    if row.purpose == "login":
        response = _login_or_pending(request, db, base, steam64)
    elif row.purpose == "link":
        response = _link(request, db, row, steam64)
    else:
        response = _reauth(request, db, row, steam64)
    _delete_cookie(response, base, _STATE_COOKIE)
    return response


def _login_or_pending(request: Request, db, base: str, steam64: str):
    user = _find_by_steam_id(db, steam64)
    if user is not None:
        _apply_admin_seed(db, user, steam64)
        # Always a new session ID (issue #117), even if a valid cookie was sent.
        sessions.start_session(request, db, user)
        _audit(db, "user_login", actor_id=user.id, actor_username=user.username,
               detail="method=steam")
        db.commit()
        return RedirectResponse("/", status_code=303)
    # An unknown Steam id never signs in to an existing account by player id,
    # username or email: it waits for the player to choose a display name.
    token = secrets.token_urlsafe(32)
    db.add(SteamPendingSignup(token_hash=_hash(token), steam_id=steam64,
                              expires_at=_now() + SIGNUP_TTL))
    db.commit()
    response = _redirect("welcome", "choose_name")
    _set_cookie(response, base, _SIGNUP_COOKIE, token, SIGNUP_TTL)
    return response


def _link(request: Request, db, row: SteamLoginState, steam64: str):
    user = session_user_or_none(request, db)
    if user is None:
        logger.warning("Steam link callback without a website session")
        return _redirect("profile", "no_session")
    if row.user_id != user.id:
        logger.warning("Steam link callback refused for user %s: attempt belongs to another user",
                       user.id)
        return _redirect("profile", "failed")
    return _redirect("profile", link_account(db, user, steam64))


def _reauth(request: Request, db, row: SteamLoginState, steam64: str):
    tab = row.return_tab if row.return_tab in RETURN_TABS else "profile"
    user = session_user_or_none(request, db)
    if user is None:
        return _redirect(tab, "no_session")
    session_row = sessions.current_row(request, db)
    action = "admin_reauth" if user.is_admin else "player_reauth"
    if row.user_id != user.id or session_row is None or not user.steam_id \
            or not _eq(user.steam_id, steam64):
        _audit(db, action, actor_id=user.id, actor_username=user.username,
               detail="failed: different Steam account (method=steam)")
        db.commit()
        return _redirect(tab, "reauth_failed")
    sessions.mark_reauth(session_row)
    _audit(db, action, actor_id=user.id, actor_username=user.username, detail="ok (method=steam)")
    db.commit()
    return _redirect(tab, "reauth_ok")


@router.get("/auth/steam/callback", dependencies=[Depends(login_mode.require_steam)])
@limiter.limit(RATE_LIMIT_STEAM_CALLBACK)
def callback_route(request: Request, db=Depends(get_db)):
    """Steam returns here with the OpenID assertion."""
    return callback(request, db)


# ---------------------------------------------------------------------------
# Sign-up (display-name step)
# ---------------------------------------------------------------------------

class SteamSignupBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)

    _username_chars = field_validator("username")(check_username)


def signup(request: Request, db, body: SteamSignupBody):
    base = login_mode.app_base_url()
    token = request.cookies.get(_cookie_name(base, _SIGNUP_COOKIE))
    pending = db.get(SteamPendingSignup, _hash(token)) if token and len(token) <= _VALUE_MAX else None
    now = _now()
    if pending is None or pending.used_at is not None or pending.expires_at < now:
        raise HTTPException(status_code=400, detail="signup_expired")
    check_reserved(body.username)
    if username_taken(db, body.username):
        raise HTTPException(status_code=409, detail="Username already taken")
    steam64 = pending.steam_id
    if db.query(User).filter(User.steam_id == steam64).first():
        pending.used_at = now
        db.commit()
        raise HTTPException(status_code=409,
                            detail="This Steam account is linked to another Kana Cards account")
    user = User(username=body.username, email=None, password_hash=None, is_admin=False,
                tokens=int(os.getenv("INITIAL_TOKENS", "5")), created_at=now,
                steam_id=steam64, player_id=steam32(steam64))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already taken") from None
    pending.used_at = now
    _supersede_player_id_claims(db, user, user.player_id)
    _audit(db, "user_register", actor_id=user.id, actor_username=user.username,
           detail="method=steam")
    _apply_admin_seed(db, user, steam64)
    sessions.start_session(request, db, user)
    db.commit()
    response = JSONResponse({"username": user.username, "is_admin": bool(user.is_admin),
                             "tokens": user.tokens})
    _delete_cookie(response, base, _SIGNUP_COOKIE)
    return response


@router.post("/auth/steam/signup", dependencies=[Depends(login_mode.require_steam)])
@limiter.limit(RATE_LIMIT_STEAM_CALLBACK)
def signup_route(request: Request, body: SteamSignupBody, db=Depends(get_db)):
    """Create the account for a verified Steam id waiting in a pending sign-up."""
    return signup(request, db, body)


# ---------------------------------------------------------------------------
# Unlink
# ---------------------------------------------------------------------------

def unlink(db, current_user: dict) -> dict:
    user = db.get(User, current_user["user_id"])
    if not user.steam_id:
        return {"steam_linked": False, "changed": False}
    if not user.password_hash:
        raise HTTPException(status_code=409,
                            detail="This account signs in only through Steam, so Steam can't be unlinked")
    user.steam_id = None
    _audit(db, "steam_unlinked", actor_id=user.id, actor_username=user.username,
           detail=f"user_id={user.id}")
    db.commit()
    return {"steam_linked": False, "changed": True}


@router.post("/profile/steam/unlink", dependencies=[Depends(login_mode.require_steam)])
def unlink_route(current_user: dict = Depends(require_recent_player_reauth), db=Depends(get_db)):
    """Unlink Steam (needs a recent check). The verified player id stays."""
    return unlink(db, current_user)


# ---------------------------------------------------------------------------
# Daily clean-up (main._week_maintenance_loop)
# ---------------------------------------------------------------------------

def cleanup(db, now: int | None = None) -> dict:
    """Delete expired or used attempts and pending sign-ups, and nonces older than a day."""
    now = int(now if now is not None else _now())
    states = (db.query(SteamLoginState)
              .filter((SteamLoginState.expires_at < now) | (SteamLoginState.used_at.isnot(None)))
              .delete(synchronize_session=False))
    nonces = (db.query(SteamOpenIdNonce)
              .filter(SteamOpenIdNonce.created_at < now - NONCE_RETENTION)
              .delete(synchronize_session=False))
    signups = (db.query(SteamPendingSignup)
               .filter((SteamPendingSignup.expires_at < now) | (SteamPendingSignup.used_at.isnot(None)))
               .delete(synchronize_session=False))
    db.commit()
    return {"states": states, "nonces": nonces, "signups": signups}
