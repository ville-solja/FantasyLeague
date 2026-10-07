"""Twitch Extension Backend Service (EBS) routes.

All endpoints here are under /twitch/ and authenticate with the Twitch-signed
extension JWT (validated by verify_twitch_jwt). The website-side Twitch connection
routes (session cookie) live in twitch_oauth.py (issue #160).

Issue #157: the panel is a self-contained game. GET /twitch/panel serves live
fantasy data to every viewer; POST /twitch/join creates a soft account
(soft_accounts.py) keyed by the viewer's opaque Twitch id; the draw, team and
roster routes run the website's own card functions (routers/cards.py) for that
account; POST /twitch/leave deletes a soft account or unlinks a website account.

Issue #160: the 6-character link code (POST /twitch/link-code, POST /twitch/link)
and the legacy GET /twitch/status are retired. A website account connected with
Twitch sign-in is recognised in the panel by the JWT's `user_id` (_panel_account).

Set TWITCH_LOCAL_DEV=true in .env to bypass JWT validation and PubSub HTTP
calls for local development.
"""
import base64
import json
import logging
import math
import os
import random
import time
from types import SimpleNamespace

logger = logging.getLogger(__name__)

import jwt as pyjwt
import requests as _requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.orm import Session

import card_points
import clock
import steam_live
from database import get_db
from ingest import record_timing
from deps import _audit
from models import (AuditLog, LiveMatch, Match, Player, PlayerMatchStats,
                    Team, TwitchChannelApproval, TwitchMVP, TwitchPresence,
                    TwitchTokenDrop, User, Week, Weight)
from rate_limit import key_by_twitch_viewer_or_ip, limiter
from schedule import bust_cache
from scoring import apply_mvp_bonus_to_row, display_points
import soft_accounts
import text_safety
import twitch_channels
from routers.cards import SwapRequest

router = APIRouter(prefix="/twitch", tags=["twitch"])

_PRESENCE_TTL     = 600   # seconds — viewers expire from pool after 10 min inactive
_TWITCH_DROP_MAX  = int(os.getenv("TWITCH_DROP_MAX", "20"))

# Issue #171: pool-size spike watch. A drop whose pool is more than
# _POOL_SPIKE_FACTOR times the median of the channel's last _POOL_SPIKE_WINDOW drops
# (with at least _POOL_SPIKE_MIN_HISTORY of them) is logged and audited.
_POOL_SPIKE_FACTOR      = 3
_POOL_SPIKE_WINDOW      = 10
_POOL_SPIKE_MIN_HISTORY = 5


def drop_min_account_age_seconds() -> int:
    """TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS (default 24) in seconds: how old a soft
    account must be to be in a drop pool (issue #171). 0 turns the rule off; an
    invalid or negative value falls back to the default."""
    raw = os.getenv("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", "24").strip()
    try:
        hours = float(raw)
    except ValueError:
        hours = 24.0
    if not math.isfinite(hours) or hours < 0:
        hours = 24.0
    return int(hours * 3600)


def drops_from(user: User, now: int | None = None) -> int | None:
    """Unix time from which a soft account is in drop pools, while that is still in
    the future; None for website accounts, old-enough soft accounts, or when the
    age rule is off."""
    min_age = drop_min_account_age_seconds()
    if min_age <= 0 or user.account_type != soft_accounts.SOFT or user.created_at is None:
        return None
    eligible_at = int(user.created_at) + min_age
    now = int(time.time()) if now is None else now
    return eligible_at if eligible_at > now else None

# Issue #157 panel game routes: Join and draws are limited per viewer (opaque id)
# and per IP; roster changes and Leave per viewer only. Plain functions stay
# directly callable; the `*_route` wrappers carry slowapi's `request`.
RATE_LIMIT_TWITCH_JOIN    = os.getenv("RATE_LIMIT_TWITCH_JOIN", "10/minute")
RATE_LIMIT_TWITCH_JOIN_IP = os.getenv("RATE_LIMIT_TWITCH_JOIN_IP", "60/minute")
RATE_LIMIT_TWITCH_ACTION  = os.getenv("RATE_LIMIT_TWITCH_ACTION", "30/minute")

_CHAT_TEXT_MAX         = 280  # Twitch Send Extension Chat Message limit
_TWITCH_ERROR_BODY_MAX = 300  # chars of a failed Twitch response kept in the log
_chat_version_warned   = False  # TWITCH_EXTENSION_VERSION warning logged once per process


# ---------------------------------------------------------------------------
# JWT validation
# ---------------------------------------------------------------------------

def _remember_viewer(request: Request | None, payload: dict) -> dict:
    """Expose the opaque id to the per-viewer rate-limit key (rate_limit.key_by_twitch_viewer_or_ip)."""
    if request is not None:
        try:
            request.state.twitch_opaque_id = payload.get("opaque_user_id") or None
        except AttributeError:
            pass
    return payload


def verify_twitch_jwt(request: Request = None, authorization: str = Header(...)) -> dict:
    """Validate Twitch extension JWT. Returns the decoded payload.

    Payload fields of interest:
      channel_id      — Twitch channel the extension is open on
      opaque_user_id  — Twitch's anonymised user identifier (starts with U for a viewer logged in to Twitch, A for logged out)
      user_id         — the real Twitch user id, only after the viewer accepted the identity share
      role            — "viewer", "broadcaster", "moderator" or "external"
    """
    if os.getenv("TWITCH_LOCAL_DEV") == "true":
        if os.getenv("ENV", "").lower() == "production":
            raise HTTPException(
                status_code=500,
                detail="TWITCH_LOCAL_DEV must not be set in production",
            )
        return _remember_viewer(request, {
            "channel_id": "dev_channel",
            "opaque_user_id": "Udev123",
            "role": "broadcaster",
        })
    token = authorization.removeprefix("Bearer ")
    secret_b64 = os.getenv("TWITCH_EXTENSION_SECRET", "").strip().strip('"').strip("'")
    if not secret_b64:
        raise HTTPException(status_code=500, detail="TWITCH_EXTENSION_SECRET not configured")
    try:
        # Twitch extension secrets are URL-safe base64; add padding and use urlsafe decoder
        padded = secret_b64 + "=" * (-len(secret_b64) % 4)
        secret_bytes = base64.urlsafe_b64decode(padded)
        payload = pyjwt.decode(
            token,
            secret_bytes,
            algorithms=["HS256"],
            options={"require": ["exp"]},
        )
    except pyjwt.ExpiredSignatureError:
        logger.error("Twitch JWT expired")
        raise HTTPException(status_code=401, detail="Twitch token expired")
    except pyjwt.InvalidTokenError as exc:
        # Exception class only (issue #165): nothing about the secret or the token.
        logger.error("Twitch JWT invalid: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid Twitch token")
    except Exception as exc:
        logger.error("Twitch JWT decode unexpected error: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="JWT decode error")
    # role "external" is what this server signs for Twitch's own APIs (PubSub, chat);
    # no viewer or broadcaster route ever needs one (issue #165).
    if payload.get("role") == "external":
        raise HTTPException(status_code=403, detail="Viewer token required")
    return _remember_viewer(request, payload)


def _require_broadcaster(payload: dict):
    if payload.get("role") != "broadcaster":
        raise HTTPException(status_code=403, detail="Broadcaster role required")


def _pubsub_broadcast(channel_id: str, message: dict):
    """Send a broadcast PubSub message to all open extension panels on a channel."""
    if os.getenv("TWITCH_LOCAL_DEV") == "true":
        logger.info("Twitch PubSub (dev): %s", json.dumps(message))
        return
    secret_b64 = os.getenv("TWITCH_EXTENSION_SECRET", "")
    client_id  = os.getenv("TWITCH_EXTENSION_CLIENT_ID", "")
    if not secret_b64 or not client_id:
        return
    padded = secret_b64 + "=" * (-len(secret_b64) % 4)
    token = pyjwt.encode(
        {
            "exp": int(time.time()) + 60,
            "user_id": channel_id,
            "role": "external",
            "channel_id": channel_id,
            "pubsub_perms": {"send": ["broadcast"]},
        },
        base64.urlsafe_b64decode(padded),
        algorithm="HS256",
    )
    try:
        resp = _requests.post(
            "https://api.twitch.tv/helix/extensions/pubsub",
            headers={
                "Authorization": f"Bearer {token}",
                "Client-Id": client_id,
                "Content-Type": "application/json",
            },
            json={
                "target": ["broadcast"],
                "broadcaster_id": channel_id,
                "is_global_broadcast": False,
                "message": json.dumps(message),
            },
            timeout=5,
        )
        if not resp.ok:
            logger.warning("Twitch PubSub broadcast failed: %s %s",
                           resp.status_code, (resp.text or "")[:_TWITCH_ERROR_BODY_MAX])
    except Exception:
        logger.exception("Twitch PubSub broadcast failed")


_CHAT_NAME_MAX = 32


def chat_safe_name(name, account_id) -> str:
    """The player name as the league repeats it to a channel (issue #166): no control,
    zero-width or bidi characters, at most 32 characters, and "Player {id}" when the
    player-chosen name looks like a link."""
    cleaned = text_safety.clean_display_text(name, _CHAT_NAME_MAX)
    if not cleaned or text_safety.looks_like_url(cleaned):
        return f"Player {account_id}"
    return cleaned
def _min_age_hours_text() -> str:
    """The drop age as chat copy: "24 hours", "1 hour", "1.5 hours"."""
    hours = drop_min_account_age_seconds() / 3600
    number = f"{hours:g}"
    return f"{number} hour" if number == "1" else f"{number} hours"


def _mvp_chat_text(player_name: str, winner_count: int, pool_empty: bool,
                   drops_enabled: bool = True, only_new_accounts: bool = False) -> str:
    """Build the MVP chat announcement within Twitch's 280-character limit.

    Names the MVP and, for a token drop, only how many viewers received a token:
    soft accounts have no username, and a linked player's website username is
    never revealed in chat (issue #157). `only_new_accounts`: the pool was empty
    only because every present account was too new for drops (issue #171).
    """
    base = f"Match MVP: {player_name}!"
    if not drops_enabled:
        text = base
    elif winner_count > 0:
        noun = "viewer" if winner_count == 1 else "viewers"
        text = f"{base} {winner_count} {noun} received a token."
    elif pool_empty and only_new_accounts:
        text = (f"{base} No tokens were dropped: new accounts join drops "
                f"{_min_age_hours_text()} after joining.")
    elif pool_empty:
        text = f"{base} No tokens were dropped: no joined viewers were watching."
    else:
        text = base
    return text[:_CHAT_TEXT_MAX]


def _post_chat_message(channel_id: str, message: str):
    """Post a message to Twitch chat using the Extension Chat capability.

    Uses an extension-signed JWT (role=external) — no bot account required.
    Twitch requires text, extension_id and extension_version in the body, and
    the Chat capability enabled on that extension version in the developer
    console. Logs instead of posting in local dev; skips when extension
    credentials are absent, and skips with one warning per process when
    TWITCH_EXTENSION_VERSION is unset. Never raises.
    """
    global _chat_version_warned
    if os.getenv("TWITCH_LOCAL_DEV") == "true":
        logger.info("Twitch chat (dev): %s", message)
        return
    secret_b64 = os.getenv("TWITCH_EXTENSION_SECRET", "")
    client_id  = os.getenv("TWITCH_EXTENSION_CLIENT_ID", "")
    if not secret_b64 or not client_id:
        return
    version = os.getenv("TWITCH_EXTENSION_VERSION", "").strip()
    if not version:
        if not _chat_version_warned:
            _chat_version_warned = True
            logger.warning("Twitch chat skipped: TWITCH_EXTENSION_VERSION is not set")
        return
    padded = secret_b64 + "=" * (-len(secret_b64) % 4)
    token = pyjwt.encode(
        {
            "exp": int(time.time()) + 60,
            "user_id": channel_id,
            "role": "external",
            "channel_id": channel_id,
        },
        base64.urlsafe_b64decode(padded),
        algorithm="HS256",
    )
    try:
        resp = _requests.post(
            f"https://api.twitch.tv/helix/extensions/chat?broadcaster_id={channel_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Client-Id": client_id,
                "Content-Type": "application/json",
            },
            json={
                "text": message,
                "extension_id": client_id,
                "extension_version": version,
            },
            timeout=5,
        )
        if not resp.ok:
            logger.warning("Twitch chat failed: %s %s",
                           resp.status_code, (resp.text or "")[:_TWITCH_ERROR_BODY_MAX])
    except Exception:
        logger.exception("Twitch chat message failed")


# ---------------------------------------------------------------------------
# Viewer presence (heartbeat)
# ---------------------------------------------------------------------------

def heartbeat(payload: dict, db: Session) -> dict:
    """Record a logged-in viewer's presence for the drop pool.

    Issue #171: logged-out viewers (opaque id not starting with U) can't join or
    win, so their heartbeats are acknowledged without writing anything."""
    twitch_user_id = str(payload.get("opaque_user_id") or "")
    if not twitch_user_id.startswith("U"):
        return {"ok": True}
    channel_id = payload.get("channel_id", "")
    now = int(time.time())

    presence = db.query(TwitchPresence).filter_by(twitch_user_id=twitch_user_id).first()
    if presence:
        presence.seen_at = now
        presence.channel_id = channel_id
    else:
        db.add(TwitchPresence(twitch_user_id=twitch_user_id, channel_id=channel_id, seen_at=now))
    db.commit()
    return {"ok": True}


@router.post("/heartbeat")
@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
@limiter.limit(RATE_LIMIT_TWITCH_JOIN_IP)
def heartbeat_route(
    request: Request,
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Called by the extension panel every few minutes while the viewer is joined."""
    return heartbeat(payload, db)


# ---------------------------------------------------------------------------
# Panel game (issue #157): live data, Join, draws, collection, roster, Leave
# ---------------------------------------------------------------------------

_PANEL_LATEST_MATCHES = 5   # "latest games" for the Live tab's top performers
_PANEL_TOP_PERFORMERS = 3
_JOIN_ROLES = {"viewer", "broadcaster", "moderator"}


def _opaque_id(payload: dict) -> str:
    return str(payload.get("opaque_user_id") or "")


def _logged_in_opaque_id(payload: dict) -> str:
    """The opaque id of a viewer logged in to Twitch (U...); 403 for logged-out (A...) viewers."""
    opaque_id = _opaque_id(payload)
    if not opaque_id.startswith("U"):
        raise HTTPException(status_code=403, detail="twitch_login_required")
    return opaque_id


def _record_identity_share(db: Session, user: User, payload: dict) -> None:
    """Store the real Twitch id when the JWT carries one (identity share). A conflict
    is logged, not raised, so the panel keeps working.

    Issue #160: when the id is held by a website account connected with Twitch sign-in
    and this is a soft account, the soft account becomes that website account's
    pending merge (Profile then offers it), unless one is already pending or the
    website account has used its one merge."""
    real_id = payload.get("user_id")
    if not real_id or user.twitch_account_id:
        return
    try:
        soft_accounts.record_twitch_account_id(db, user, real_id)
    except HTTPException:
        holder = soft_accounts.find_by_twitch_account_id(db, real_id)
        if (user.account_type == soft_accounts.SOFT and holder is not None
                and holder.account_type != soft_accounts.SOFT
                and not holder.pending_merge_user_id and holder.merged_soft_account_at is None):
            holder.pending_merge_user_id = user.id
            logger.info("Twitch identity share: soft account %s is now pending merge into user %s",
                        user.id, holder.id)
        else:
            logger.warning("Twitch identity share for user %s refused: id already held by another account", user.id)


def _panel_account(db: Session, payload: dict) -> User | None:
    """The account the panel acts as (issue #160 lookup order):

    (a) the account holding the viewer's opaque id (a soft account, or a website
        account already recognised);
    (b) else the account whose twitch_account_id equals the JWT's `user_id` (a
        website account connected with Twitch sign-in, after the identity share):
        the opaque id is attached to it and committed, so drops reach it too;
    (c) else None (Join creates a soft account).

    A JWT without `user_id` never switches accounts. Logged-out viewers get None."""
    opaque_id = _opaque_id(payload)
    if not opaque_id.startswith("U"):
        return None
    user = soft_accounts.find_by_opaque_id(db, opaque_id)
    if user is not None:
        return user
    holder = soft_accounts.find_by_twitch_account_id(db, payload.get("user_id"))
    if holder is None:
        return None
    holder.twitch_user_id = opaque_id
    _audit(db, "twitch_panel_recognised", actor_id=holder.id, actor_username=holder.display_name,
           detail=f"user_id={holder.id}")
    db.commit()
    return holder


def _joined_user(db: Session, payload: dict) -> User:
    """The caller's account (see _panel_account); 404 not_joined otherwise."""
    user = _panel_account(db, payload)
    if user is None:
        raise HTTPException(status_code=404, detail="not_joined")
    _record_identity_share(db, user, payload)
    soft_accounts.touch_last_seen(db, user)
    return user


def _acting_user(user: User) -> dict:
    """The current_user dict the website's card functions take (deps.get_current_user shape)."""
    return {"user_id": user.id, "username": user.username, "is_admin": False}


def _roster_week_state(db: Session) -> tuple[int | None, bool]:
    """(week_id, locked) for the panel roster: the next editable week when there is one;
    otherwise a locked week in progress is shown read-only."""
    from weeks import get_current_week, get_next_editable_week
    if get_next_editable_week(db) is not None:
        return None, False
    current = get_current_week(db)
    if current is not None and current.is_locked:
        return current.id, True
    return None, False


def _require_editable_roster(db: Session) -> None:
    if _roster_week_state(db)[1]:
        raise HTTPException(status_code=409, detail="Roster locked for this week")


def _week_points(db: Session, user_id: int) -> dict | None:
    """Points so far in the week in progress (locked snapshot), or None between weeks."""
    from routers.cards import _build_roster_response
    from weeks import get_current_week
    current = get_current_week(db)
    if current is None or not current.is_locked:
        return None
    data = _build_roster_response(db, user_id, current.id)
    return {"week_id": current.id, "label": current.label, "points": data["combined_value"]}


def _me_state(db: Session, user: User) -> dict:
    """Game state of the caller's own account. Never includes Twitch ids, email,
    username or another user's data."""
    from routers.cards import ROSTER_LIMIT, _build_roster_response, collection_for_user
    week_id, locked = _roster_week_state(db)
    roster = _build_roster_response(db, user.id, week_id)
    weights = {w.key: w.value for w in db.query(Weight).filter(Weight.key == "team_booster_cost").all()}
    return {
        "joined": True,
        "tokens": user.tokens if user.tokens is not None else 0,
        "collection": collection_for_user(db, user.id),
        "roster": roster,
        "roster_locked": locked,
        "roster_limit": ROSTER_LIMIT,
        "week_points": _week_points(db, user.id),
        "team_draw_cost": int(weights.get("team_booster_cost", 3)),
        "identity_shared": bool(user.twitch_account_id),
        "website_account": user.account_type != soft_accounts.SOFT,
        "drops_from": drops_from(user),
    }


@router.get("/panel")
def panel_live(
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Live tab data for every viewer, logged in to Twitch or not: the top fantasy
    performers of the latest games (GET /top's query) and the next scheduled match
    (GET /schedule's data). Public data only."""
    from routers.leaderboard import top_performance_rows
    from match_scoring import scored_match_sql
    from sqlalchemy import text as _text
    latest = [r[0] for r in db.execute(_text(f"""
        SELECT m.match_id FROM matches m
        WHERE {scored_match_sql()}
          AND EXISTS (SELECT 1 FROM player_match_stats s WHERE s.match_id = m.match_id)
        ORDER BY m.start_time DESC, m.match_id DESC
        LIMIT :n
    """), {"n": _PANEL_LATEST_MATCHES}).fetchall()]
    top = [{"player_id": r["id"], "player_name": r["name"], "fantasy_points": r["fantasy_points"]}
           for r in top_performance_rows(db, limit=_PANEL_TOP_PERFORMERS, match_ids=latest)]
    try:
        from schedule import next_scheduled_match
        next_match = next_scheduled_match(db)
    except Exception:
        logger.exception("Twitch panel: next match lookup failed")
        next_match = None
    return {"top_performers": top, "next_match": next_match}


def join(payload: dict, db: Session) -> dict:
    """Create (or return) the viewer's account. Idempotent: an existing soft account,
    or a website account recognised by opaque id or by the JWT's user_id (connected
    with Twitch sign-in, issue #160), is returned and nothing is created."""
    opaque_id = _logged_in_opaque_id(payload)
    if payload.get("role") not in _JOIN_ROLES:
        raise HTTPException(status_code=403, detail="Viewer role required")
    user = _panel_account(db, payload)
    if user is not None:
        _record_identity_share(db, user, payload)
        soft_accounts.touch_last_seen(db, user)
        db.commit()
        return {**_me_state(db, user), "created": False}
    user, created = soft_accounts.get_or_create_soft_account(db, opaque_id, payload.get("user_id"))
    if soft_accounts.touch_last_seen(db, user):
        db.commit()
    return {**_me_state(db, user), "created": created}


@router.post("/join")
@limiter.limit(RATE_LIMIT_TWITCH_JOIN, key_func=key_by_twitch_viewer_or_ip)
@limiter.limit(RATE_LIMIT_TWITCH_JOIN_IP)
def join_route(
    request: Request,
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    return join(payload, db)


@router.get("/me")
def me(
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """The caller's own game state, or {joined: false} without an account."""
    opaque_id = _opaque_id(payload)
    user = _panel_account(db, payload)
    if user is None:
        return {"joined": False, "can_join": opaque_id.startswith("U")}
    _record_identity_share(db, user, payload)
    soft_accounts.touch_last_seen(db, user)
    db.commit()
    return _me_state(db, user)


def draw(payload: dict, db: Session) -> dict:
    from routers.cards import draw_card
    user = _joined_user(db, payload)
    return draw_card(db=db, current_user=_acting_user(user))


@router.post("/draw")
@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
@limiter.limit(RATE_LIMIT_TWITCH_JOIN_IP)
def draw_route(request: Request, payload: dict = Depends(verify_twitch_jwt),
               db: Session = Depends(get_db)):
    return draw(payload, db)


def draw_team(team_id: int, payload: dict, db: Session) -> dict:
    """Team draw for the caller. A team whose players the caller already owns is
    refused (its tile is disabled in the panel; this catches a stale request)."""
    from routers.cards import booster_deck_for_user, draw_booster
    user = _joined_user(db, payload)
    team = next((t for t in booster_deck_for_user(db, user.id) if t["team_id"] == team_id), None)
    if team is not None and team["remaining"] == 0:
        raise HTTPException(status_code=409, detail="No players available for this team")
    return draw_booster(team_id, db=db, current_user=_acting_user(user))


@router.post("/draw/booster/{team_id}")
@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
@limiter.limit(RATE_LIMIT_TWITCH_JOIN_IP)
def draw_team_route(request: Request, team_id: int, payload: dict = Depends(verify_twitch_jwt),
                    db: Session = Depends(get_db)):
    return draw_team(team_id, payload, db)


@router.get("/teams")
def teams(
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Team draw picker: the website's GET /deck/booster data for the caller."""
    from routers.cards import booster_deck_for_user
    user = _joined_user(db, payload)
    db.commit()
    cost = db.query(Weight.value).filter(Weight.key == "team_booster_cost").scalar()
    return {"teams": booster_deck_for_user(db, user.id),
            "cost": int(cost if cost is not None else 3),
            "tokens": user.tokens if user.tokens is not None else 0}


def roster_activate(card_id: int, payload: dict, db: Session, slot: int | None = None) -> dict:
    """Bench card into an empty roster slot (activate_card); `slot` places it in the
    slot the viewer picked."""
    from models import Card
    from routers.cards import ROSTER_LIMIT, activate_card
    user = _joined_user(db, payload)
    _require_editable_roster(db)
    result = activate_card(card_id, db=db, current_user=_acting_user(user))
    if slot is not None and 0 <= slot < ROSTER_LIMIT:
        card = db.get(Card, card_id)
        if card is not None and card.owner_id == user.id:
            card.slot_index = slot
            db.commit()
    return result


@router.post("/roster/activate/{card_id}")
@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
def roster_activate_route(request: Request, card_id: int, slot: int | None = None,
                          payload: dict = Depends(verify_twitch_jwt),
                          db: Session = Depends(get_db)):
    return roster_activate(card_id, payload, db, slot)


def roster_deactivate(card_id: int, payload: dict, db: Session) -> dict:
    from routers.cards import deactivate_card
    user = _joined_user(db, payload)
    _require_editable_roster(db)
    return deactivate_card(card_id, db=db, current_user=_acting_user(user))


@router.post("/roster/deactivate/{card_id}")
@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
def roster_deactivate_route(request: Request, card_id: int, payload: dict = Depends(verify_twitch_jwt),
                            db: Session = Depends(get_db)):
    return roster_deactivate(card_id, payload, db)


def roster_swap(body, payload: dict, db: Session) -> dict:
    """Bench card into a roster slot, the slot's card to the bench: the website's
    drag-and-drop swap (swap_roster)."""
    from routers.cards import swap_roster
    user = _joined_user(db, payload)
    _require_editable_roster(db)
    return swap_roster(body, user=_acting_user(user), db=db)


@router.post("/roster/swap")
@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
def roster_swap_route(request: Request, body: SwapRequest,
                      payload: dict = Depends(verify_twitch_jwt),
                      db: Session = Depends(get_db)):
    return roster_swap(body, payload, db)


def leave(payload: dict, db: Session) -> dict:
    """Leave Kana Cards. A soft account is deleted with all its rows; a website
    account is only unlinked (twitch_user_id cleared) and keeps everything, including
    its Twitch connection (twitch_account_id): Disconnect is on the website. While
    connected and sharing identity, the panel recognises it again on the next call.
    Without an account it is a no-op, so leaving twice is safe."""
    opaque_id = _opaque_id(payload)
    user = soft_accounts.find_by_opaque_id(db, opaque_id) if opaque_id.startswith("U") else None
    if user is None:
        return {"left": False, "deleted": False}
    uid = user.id
    if user.account_type == soft_accounts.SOFT:
        soft_accounts.delete_soft_account(db, user)
        _audit(db, "twitch_soft_account_deleted", actor_id=None, actor_username="twitch",
               detail=f"user_id={uid} reason=leave")
        db.commit()
        return {"left": True, "deleted": True}
    user.twitch_user_id = None
    db.query(TwitchPresence).filter(TwitchPresence.twitch_user_id == opaque_id).delete(
        synchronize_session=False)
    _audit(db, "twitch_account_unlinked", actor_id=uid, actor_username=user.display_name,
           detail=f"user_id={uid} reason=leave")
    db.commit()
    return {"left": True, "deleted": False}


@router.post("/leave")
@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
def leave_route(request: Request, payload: dict = Depends(verify_twitch_jwt),
                db: Session = Depends(get_db)):
    return leave(payload, db)


# ---------------------------------------------------------------------------
# Match data for MVP selection
# ---------------------------------------------------------------------------

_CURRENT_SERIES_LIMIT = 5


def _live_players(live_row: LiveMatch) -> list[dict]:
    try:
        players = json.loads(live_row.players_json or "[]")
    except ValueError:
        return []
    return [p for p in players if isinstance(p, dict) and p.get("account_id")]


def _live_display_name(account_id: int, live_name: str | None, known_names: dict[int, str]) -> str:
    """Known players name, else the live name, else "Player {account_id}"."""
    return known_names.get(account_id) or live_name or f"Player {account_id}"


def _known_player_names(db: Session, account_ids) -> dict[int, str]:
    ids = set(account_ids)
    if not ids:
        return {}
    return {pid: name for pid, name in db.query(Player.id, Player.name).filter(Player.id.in_(ids)).all() if name}


def _current_series(db: Session) -> list[tuple[tuple, list]]:
    """The series GET /twitch/matches/current offers, most recently played first.

    A series is the started matches that share a normalised team pair, sorted by
    start_time. Matches with ingested stats are Match rows; a stored live match
    (live_matches) with no stats yet is added as a provisional stand-in whose
    start_time is when it was first seen live. Provisional matches with no team
    ids are grouped by their team names instead. Only the 5 most recent series
    are returned. POST /twitch/mvp uses the same selection (via
    _eligible_mvp_match_ids) so a broadcaster can only pick an MVP for a match
    the extension actually offers.
    """
    now = clock.now(db)

    ingested_match_ids = {
        r.match_id
        for r in db.query(PlayerMatchStats.match_id).distinct().all()
    }

    matches: list = []
    if ingested_match_ids:
        matches = (
            db.query(Match)
            .filter(
                Match.match_id.in_(ingested_match_ids),
                Match.start_time <= now,
            )
            .all()
        )

    for row in db.query(LiveMatch).all():
        if row.match_id in ingested_match_ids:
            continue
        matches.append(SimpleNamespace(
            match_id=row.match_id,
            radiant_team_id=row.radiant_team_id,
            dire_team_id=row.dire_team_id,
            start_time=row.first_seen_at,
            provisional=True,
            live=row.ended_at is None,
            live_row=row,
        ))

    # Group by normalised team pair so Bo2/Bo3 games appear as one series
    series_map: dict = {}
    for m in matches:
        t1 = m.radiant_team_id or 0
        t2 = m.dire_team_id or 0
        if not t1 and not t2 and getattr(m, "provisional", False):
            n1 = m.live_row.radiant_name or ""
            n2 = m.live_row.dire_name or ""
            if n1 or n2:
                t1, t2 = n1, n2
        key = (min(t1, t2), max(t1, t2))
        series_map.setdefault(key, []).append(m)

    for series_matches in series_map.values():
        series_matches.sort(key=lambda m: m.start_time or 0)

    # Most-recently-played series first
    ordered = sorted(
        series_map.items(),
        key=lambda item: (item[1][-1].start_time or 0) if item[1] else 0,
        reverse=True,
    )
    return ordered[:_CURRENT_SERIES_LIMIT]


def _eligible_mvp_match_ids(db: Session) -> set[int]:
    """Match IDs a broadcaster may set an MVP for: exactly those current_matches() offers."""
    return {m.match_id for _, series_matches in _current_series(db) for m in series_matches}


@router.get("/matches/current")
def current_matches(
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Return the 5 most recent series with ingested or live match data, across any week,
    and how fresh the live-game list is (live_checked_at, live_source_configured).

    Issue #175: also whether this channel may set MVPs (mvp_allowed, approval). A
    broadcaster on a channel that may not gets an empty series list and leaves an
    approval request; viewers still see the series (the panel shows MVP results)."""
    channel_id = payload.get("channel_id", "")
    mvp_allowed, approval = channel_approval(channel_id, db)
    freshness = {
        "live_checked_at": steam_live.live_checked_at,
        "live_source_configured": bool(steam_live.STEAM_API_KEY),
        "mvp_allowed": mvp_allowed,
        "approval": approval,
    }
    if not mvp_allowed and payload.get("role") == "broadcaster":
        if twitch_channels.record_request(db, channel_id) is not None:
            db.commit()
        return {"series": [], **freshness}
    series = _current_series(db)
    if not series:
        return {"series": [], **freshness}
    series_map = dict(series)
    matches = [m for _, series_matches in series for m in series_matches]
    provisional = [m for m in matches if getattr(m, "provisional", False)]
    live_players_by_match = {m.match_id: _live_players(m.live_row) for m in provisional}

    # Bulk-fetch all teams and MVPs needed for this week in two queries
    all_team_ids = {tid for pair in series_map for tid in pair if tid and isinstance(tid, int)}
    all_team_ids |= {tid for m in provisional for tid in (m.radiant_team_id, m.dire_team_id) if tid}
    teams_by_id: dict[int, Team] = {
        t.id: t for t in db.query(Team).filter(Team.id.in_(all_team_ids)).all()
    } if all_team_ids else {}

    # Team names seen live, for teams not in the teams table yet
    live_team_names: dict[int, str] = {}
    for m in provisional:
        for tid, name in ((m.radiant_team_id, m.live_row.radiant_name),
                          (m.dire_team_id, m.live_row.dire_name)):
            if tid and name:
                live_team_names.setdefault(tid, name)

    def _team_name(tid) -> str:
        if isinstance(tid, str):
            return tid or "TBD"
        team = teams_by_id.get(tid) if tid else None
        if team:
            return team.name
        return live_team_names.get(tid) or f"Team {tid}"

    match_ids = [m.match_id for m in matches]
    mvps_by_match: dict[int, TwitchMVP] = {
        mv.match_id: mv
        for mv in db.query(TwitchMVP).filter(TwitchMVP.match_id.in_(match_ids)).all()
    } if match_ids else {}

    mvp_player_ids = {mv.player_id for mv in mvps_by_match.values()}
    live_account_ids = {p["account_id"] for players in live_players_by_match.values() for p in players}
    known_names = _known_player_names(db, mvp_player_ids | live_account_ids)

    # Bulk-fetch all player stats for the window's matches in one query
    stats_by_match: dict[int, list] = {}
    if match_ids:
        all_stats = (
            db.query(PlayerMatchStats, Player, Team)
            .join(Player, PlayerMatchStats.player_id == Player.id)
            .join(Team, PlayerMatchStats.team_id == Team.id)
            .filter(PlayerMatchStats.match_id.in_(match_ids))
            .all()
        )
        for pms, p, t in all_stats:
            stats_by_match.setdefault(pms.match_id, []).append((pms, p, t))

    result_series = []
    for (tid_lo, tid_hi), series_matches in series_map.items():
        match_list = []
        for i, m in enumerate(series_matches):  # already sorted by start_time
            existing_mvp = mvps_by_match.get(m.match_id)
            is_provisional = getattr(m, "provisional", False)
            if is_provisional:
                side_names = {
                    "radiant": m.live_row.radiant_name or (_team_name(m.radiant_team_id) if m.radiant_team_id else "Radiant"),
                    "dire": m.live_row.dire_name or (_team_name(m.dire_team_id) if m.dire_team_id else "Dire"),
                }
                live_players = live_players_by_match.get(m.match_id, [])
                players = [
                    {
                        "player_id": p["account_id"],
                        "player_name": _live_display_name(p["account_id"], p.get("name"), known_names),
                        "chat_name": chat_safe_name(
                            _live_display_name(p["account_id"], p.get("name"), known_names),
                            p["account_id"]),
                        "team_name": side_names.get(p.get("side"), ""),
                        "fantasy_points": 0,
                    }
                    for p in live_players
                ]
                mvp_name = None
                if existing_mvp:
                    live_name = next((p.get("name") for p in live_players
                                      if p["account_id"] == existing_mvp.player_id), None)
                    mvp_name = _live_display_name(existing_mvp.player_id, live_name, known_names)
            else:
                stats = stats_by_match.get(m.match_id, [])
                players = [
                    {
                        "player_id": pms.player_id,
                        "player_name": p.name,
                        "chat_name": chat_safe_name(p.name, pms.player_id),
                        "team_name": t.name,
                        "fantasy_points": display_points(pms.fantasy_points),
                    }
                    for pms, p, t in stats
                ]
                mvp_name = known_names.get(existing_mvp.player_id) if existing_mvp else None
            match_list.append({
                "match_id": m.match_id,
                "match_number": i + 1,
                "start_time": m.start_time,
                "provisional": is_provisional,
                "live": bool(getattr(m, "live", False)),
                "players": players,
                "mvp_player_id": existing_mvp.player_id if existing_mvp else None,
                "mvp_player_name": mvp_name,
            })

        result_series.append({
            "team1_name": _team_name(tid_lo),
            "team2_name": _team_name(tid_hi),
            "matches": match_list,
        })

    return {"series": result_series, **freshness}


# ---------------------------------------------------------------------------
# Race-safe MVP and token-drop writes
# ---------------------------------------------------------------------------

def _dialect_insert(db: Session):
    """INSERT construct with ON CONFLICT support for the session's database."""
    return _pg_insert if db.get_bind().dialect.name == "postgresql" else _sqlite_insert


def upsert_mvp(db: Session, match_id: int, player_id: int, channel_id: str) -> int | None:
    """Set the MVP for a match and return the previous MVP's player_id (or None).

    A single INSERT ... ON CONFLICT(match_id) DO UPDATE, so two confirmations
    arriving together update one row instead of creating two
    (uq_twitch_mvp_match)."""
    previous = db.query(TwitchMVP.player_id).filter(TwitchMVP.match_id == match_id).first()
    now = int(time.time())
    insert = _dialect_insert(db)
    stmt = insert(TwitchMVP).values(
        match_id=match_id, player_id=player_id, channel_id=channel_id, selected_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[TwitchMVP.match_id],
        set_={"player_id": player_id, "channel_id": channel_id, "selected_at": now},
    )
    db.execute(stmt)
    return previous[0] if previous else None


def _claim_drop(db: Session, channel_id: str, drop_key: str) -> bool:
    """Atomically claim the one token drop allowed per channel and match.

    Returns True only for the request whose row was inserted. A concurrent or
    repeated confirmation hits uq_twitch_token_drop_channel_series and gets
    False, so it must not grant tokens."""
    insert = _dialect_insert(db)
    stmt = insert(TwitchTokenDrop).values(
        channel_id=channel_id, series_id=drop_key, dropped_at=int(time.time()), count=0,
    ).on_conflict_do_nothing(index_elements=[TwitchTokenDrop.channel_id, TwitchTokenDrop.series_id])
    return db.execute(stmt).rowcount == 1


# ---------------------------------------------------------------------------
# MVP bonus helpers
# ---------------------------------------------------------------------------

def _apply_mvp_bonus(db: Session, player_id: int, match_id: int, apply: bool, weights: dict):
    """Set or clear the MVP flag and adjust fantasy_points on a PlayerMatchStats row.

    Thin DB-lookup wrapper around scoring.apply_mvp_bonus_to_row() for the two
    callers here that only have (player_id, match_id), not an already-loaded row.
    """
    row = db.query(PlayerMatchStats).filter_by(player_id=player_id, match_id=match_id).first()
    if not row:
        return
    apply_mvp_bonus_to_row(row, weights, apply)


# ---------------------------------------------------------------------------
# Presence pool helper
# ---------------------------------------------------------------------------

# A website account (any account_type other than soft) is always old enough; a
# soft account needs created_at at least the minimum age ago (NULL counts as new).
_OLD_ENOUGH_SQL = ("(u.account_type IS NULL OR u.account_type <> :soft"
                   " OR (u.created_at IS NOT NULL AND u.created_at <= :min_created))")


def _present_accounts(db: Session, channel_id: str, old_enough: bool) -> list[str]:
    from sqlalchemy import text as _text
    now = int(time.time())
    rows = db.execute(_text(f"""
        SELECT p.twitch_user_id
        FROM twitch_presence p
        JOIN users u ON u.twitch_user_id = p.twitch_user_id
        WHERE p.channel_id = :channel_id
          AND p.seen_at >= :cutoff
          AND {"" if old_enough else "NOT "}{_OLD_ENOUGH_SQL}
    """), {"channel_id": channel_id, "cutoff": now - _PRESENCE_TTL, "soft": soft_accounts.SOFT,
           "min_created": now - drop_min_account_age_seconds()}).fetchall()
    return [r[0] for r in rows]


def _active_pool(db: Session, channel_id: str) -> list[str]:
    """Viewers with an account (soft account or recognised website account, both via
    users.twitch_user_id) who sent a heartbeat within the presence TTL. A soft
    account must also be TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS old (issue #171)."""
    return _present_accounts(db, channel_id, old_enough=True)


def _excluded_new_count(db: Session, channel_id: str) -> int:
    """Present soft accounts left out of the pool for being too new (issue #171)."""
    return len(_present_accounts(db, channel_id, old_enough=False))


def _recent_pool_sizes(db: Session, channel_id: str) -> list[int]:
    """pool_size of the channel's last _POOL_SPIKE_WINDOW token drops, newest first.
    Entries without pool_size= (written before issue #171) and empty pools are skipped."""
    prefix = f"channel={channel_id} "
    rows = (db.query(AuditLog.detail)
              .filter(AuditLog.action == "twitch_token_drop", AuditLog.detail.like(f"{prefix}%"))
              .order_by(AuditLog.id.desc())
              .limit(_POOL_SPIKE_WINDOW * 10)
              .all())
    sizes: list[int] = []
    for (detail,) in rows:
        if not detail or not detail.startswith(prefix):
            continue
        for part in detail.split(" "):
            if part.startswith("pool_size="):
                try:
                    size = int(part[len("pool_size="):])
                except ValueError:
                    break
                if size > 0:
                    sizes.append(size)
                break
        if len(sizes) >= _POOL_SPIKE_WINDOW:
            break
    return sizes


def _is_pool_spike(db: Session, channel_id: str, pool_size: int) -> bool:
    import statistics
    earlier = _recent_pool_sizes(db, channel_id)
    if len(earlier) < _POOL_SPIKE_MIN_HISTORY:
        return False
    median = statistics.median(earlier)
    if pool_size > _POOL_SPIKE_FACTOR * median:
        logger.warning("Twitch token drop pool spike on channel %s: pool_size=%d, median of last %d drops=%s",
                       channel_id, pool_size, len(earlier), median)
        return True
    return False


def _drop_audit_detail(channel_id: str, match_id: int, count: int, pool_size: int,
                       excluded_new: int, spike: bool, winner_names: list[str]) -> str:
    return (f"channel={channel_id} match={match_id} count={count} pool_size={pool_size}"
            f" excluded_new={excluded_new}" + (" pool_spike=true" if spike else "")
            + f" winners={','.join(winner_names)}")


# ---------------------------------------------------------------------------
# MVP selection — also triggers a one-time token drop for the match
# ---------------------------------------------------------------------------

def _execute_token_drop(
    db: Session, channel_id: str, match_id: int, weights: dict
) -> tuple[list[str], int, bool]:
    """Grant tokens to a random sample of present joined viewers. Returns (winner_names, pool_size, already_dropped).

    winner_names are for the broadcaster's response and the audit log only (a soft
    account's is "Twitch viewer #id"); chat and PubSub carry the count alone."""
    drop_key = str(match_id)
    already_dropped = bool(
        db.query(TwitchTokenDrop).filter_by(channel_id=channel_id, series_id=drop_key).first()
    )
    winner_names: list[str] = []
    pool_size = 0

    if not already_dropped:
        pool = _active_pool(db, channel_id)
        pool_size = len(pool)
        excluded_new = _excluded_new_count(db, channel_id)
        if not pool and excluded_new:
            # Only too-new soft accounts were watching: record it, claim nothing.
            db.add(AuditLog(
                timestamp=int(time.time()), actor_id=None, actor_username="twitch",
                action="twitch_token_drop",
                detail=_drop_audit_detail(channel_id, match_id, 0, 0, excluded_new, False, []),
            ))
        if pool and not _claim_drop(db, channel_id, drop_key):
            # Another confirmation claimed this drop between the check above and now.
            return winner_names, pool_size, True
        if pool:
            spike = _is_pool_spike(db, channel_id, pool_size)
            count = min(_TWITCH_DROP_MAX, len(pool))
            winner_ids = random.sample(pool, count)
            users_by_twitch_id = {
                u.twitch_user_id: u
                for u in db.query(User).filter(User.twitch_user_id.in_(winner_ids)).all()
            }
            for twitch_id in winner_ids:
                user = users_by_twitch_id.get(twitch_id)
                if user:
                    user.tokens = (user.tokens or 0) + 1
                    winner_names.append(user.display_name)
            db.query(TwitchTokenDrop).filter_by(channel_id=channel_id, series_id=drop_key).update(
                {TwitchTokenDrop.count: len(winner_names)}, synchronize_session=False)
            db.add(AuditLog(
                timestamp=int(time.time()),
                actor_id=None,
                actor_username="twitch",
                action="twitch_token_drop",
                detail=_drop_audit_detail(channel_id, match_id, len(winner_names), pool_size,
                                          excluded_new, spike, winner_names),
            ))

    return winner_names, pool_size, already_dropped


def drops_enabled() -> bool:
    """TWITCH_DROPS_ENABLED (default true): kill switch for MVP token drops (issue #157).
    Off, confirming an MVP sets the MVP and the fantasy bonus only."""
    return os.getenv("TWITCH_DROPS_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


def _mvp_allowed_channels() -> set[str]:
    """Channel IDs from TWITCH_MVP_CHANNEL_IDS (comma-separated)."""
    return twitch_channels.env_channels()


def _is_production() -> bool:
    return os.getenv("ENV", "").strip().lower() == "production"


def mvp_channel_allowed(channel_id: str, db: Session | None = None) -> bool:
    """Whether a channel may set MVPs: it is in TWITCH_MVP_CHANNEL_IDS or approved in
    the admin portal (issue #175; the portal only counts when `db` is given). With
    both lists empty, any channel may outside production only (issue #165: fail closed)."""
    allowed = twitch_channels.approved_channels(db) if db is not None else _mvp_allowed_channels()
    if allowed:
        return channel_id in allowed
    return not _is_production()


def channel_approval(channel_id: str, db: Session) -> tuple[bool, str]:
    """(mvp_allowed, approval) for the MVP tool: approval is approved, pending or rejected."""
    if mvp_channel_allowed(channel_id, db):
        return True, twitch_channels.APPROVED
    row = db.get(TwitchChannelApproval, channel_id) if channel_id else None
    if row is not None and row.status == twitch_channels.REJECTED:
        return False, twitch_channels.REJECTED
    return False, twitch_channels.PENDING


def warn_if_mvp_channels_unset() -> None:
    """Startup warning (main.lifespan): production with an empty TWITCH_MVP_CHANNEL_IDS.
    Portal approvals (issue #175) are not counted here, so the text names both places."""
    if _is_production() and not _mvp_allowed_channels():
        logger.warning("TWITCH_MVP_CHANNEL_IDS is empty: with ENV=production only channels approved "
                       "under Approved streamers in the admin portal can set match MVPs; with none "
                       "approved there either, no channel can")


class MVPBody(BaseModel):
    match_id: int
    player_id: int


@router.post("/mvp")
def set_mvp(
    body: MVPBody,
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Set match MVP and trigger a one-time token drop to the presence pool.

    The token drop fires once per match (keyed by match_id). Re-setting the MVP
    on the same match updates the player record but does not re-drop tokens.
    """
    _require_broadcaster(payload)
    channel_id = payload.get("channel_id", "")

    # Every check runs before any MVP row, bonus or token drop is written. The
    # channel allowlist goes first so other channels learn nothing about IDs. A
    # refused channel leaves an approval request for the admins (issue #175).
    if not mvp_channel_allowed(channel_id, db):
        if twitch_channels.record_request(db, channel_id) is not None:
            db.commit()
        raise HTTPException(status_code=403, detail="This channel cannot set match MVPs")
    match = db.get(Match, body.match_id)
    live_row = db.get(LiveMatch, body.match_id)
    if not match and not live_row:
        raise HTTPException(status_code=404, detail="Match not found")
    if body.match_id not in _eligible_mvp_match_ids(db):
        raise HTTPException(status_code=403, detail="Match is not in the current series window")

    # A stored live match with no ingested stats yet: the player must be one of
    # its live players, and the bonus is applied later by ingest._reapply_mvp_bonus.
    has_stats = db.query(PlayerMatchStats.id).filter_by(match_id=body.match_id).first() is not None
    provisional = live_row is not None and not has_stats
    if provisional:
        live_player = next((p for p in _live_players(live_row)
                            if p["account_id"] == body.player_id), None)
        if not live_player:
            raise HTTPException(status_code=404, detail="Player did not play in this match")
        player_name = _live_display_name(
            body.player_id, live_player.get("name"), _known_player_names(db, [body.player_id]))
    else:
        played = db.query(PlayerMatchStats.id).filter_by(
            match_id=body.match_id, player_id=body.player_id).first()
        if not played:
            raise HTTPException(status_code=404, detail="Player did not play in this match")

        player = db.query(Player).filter_by(id=body.player_id).first()
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        player_name = player.name

    weights = {w.key: w.value for w in db.query(Weight).all()}

    old_player_id = upsert_mvp(db, body.match_id, body.player_id, channel_id)
    existing = old_player_id is not None
    record_timing(db, body.match_id, mvp_confirmed_at=int(time.time()), mvp_provisional=provisional)

    if not provisional:
        # Clear bonus from previous MVP if different player
        if old_player_id and old_player_id != body.player_id:
            _apply_mvp_bonus(db, old_player_id, body.match_id, apply=False, weights=weights)
        # Apply bonus to new MVP
        _apply_mvp_bonus(db, body.player_id, body.match_id, apply=True, weights=weights)
        card_points.refresh_card_points(db, match_ids=[body.match_id])

    # Token drop — once per match, unless the kill switch is off
    enabled = drops_enabled()
    if enabled:
        winner_names, pool_size, already_dropped = _execute_token_drop(
            db, channel_id, body.match_id, weights
        )
    else:
        winner_names, pool_size, already_dropped = [], 0, False

    db.add(AuditLog(
        timestamp=int(time.time()),
        actor_id=None,
        actor_username="twitch",
        action="twitch_mvp_set",
        detail=(f"channel={channel_id} match={body.match_id} player={player_name} re_select={bool(existing)}"
                + (" provisional=True" if provisional else "")),
    ))
    db.commit()
    bust_cache()
    # No winner names or ids go to the channel: every joined panel re-reads its own
    # balance from GET /twitch/me and shows the drop when it went up.
    announced_name = chat_safe_name(player_name, body.player_id)
    _pubsub_broadcast(channel_id, {
        "type": "mvp",
        "player_name": announced_name,
        "match_id": body.match_id,
        "token_drop": {"count": len(winner_names), "refresh": bool(winner_names)},
    })

    pool_empty = enabled and not already_dropped and pool_size == 0
    chat_msg = _mvp_chat_text(announced_name, len(winner_names),
                              pool_empty=pool_empty,
                              drops_enabled=enabled,
                              only_new_accounts=pool_empty and _excluded_new_count(db, channel_id) > 0)
    _post_chat_message(channel_id, chat_msg)

    return {
        "match_id": body.match_id,
        "player_id": body.player_id,
        "player_name": player_name,
        "token_drop": {
            "enabled": enabled,
            # Count only: a winner's display name is a website username for a
            # connected viewer, and is not shown to the channel (issue #157).
            "winner_count": len(winner_names),
            "pool_size": pool_size,
            "already_dropped": already_dropped,
        },
    }
