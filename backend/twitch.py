"""Twitch Extension Backend Service (EBS) routes.

All endpoints are under /twitch/. Authentication is via Twitch-signed JWT
(validated by verify_twitch_jwt), except /twitch/link-code which requires
an active Fantasy session.

Set TWITCH_LOCAL_DEV=true in .env to bypass JWT validation and PubSub HTTP
calls for local development.
"""
import base64
import json
import os
import random
import string
import time

import jwt as pyjwt
import requests as _requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import (AuditLog, Match, Player, PlayerMatchStats,
                    Team, TwitchLinkCode, TwitchMVP, TwitchPresence,
                    TwitchTokenDrop, User, Week)

router = APIRouter(prefix="/twitch", tags=["twitch"])

_LINK_CODE_TTL    = 600   # seconds — 10 minutes
_PRESENCE_TTL     = 600   # seconds — viewers expire from pool after 10 min inactive
_TWITCH_DROP_MAX  = int(os.getenv("TWITCH_DROP_MAX", "20"))


# ---------------------------------------------------------------------------
# JWT validation
# ---------------------------------------------------------------------------

def verify_twitch_jwt(authorization: str = Header(...)) -> dict:
    """Validate Twitch extension JWT. Returns the decoded payload.

    Payload fields of interest:
      channel_id      — Twitch channel the extension is open on
      opaque_user_id  — Twitch's anonymised user identifier (starts with U for linked, A for anon)
      role            — "viewer", "broadcaster", or "external"
    """
    if os.getenv("TWITCH_LOCAL_DEV") == "true":
        # Bypass for local development — behaves as a broadcaster so all actions are accessible
        return {
            "channel_id": "dev_channel",
            "opaque_user_id": "Udev123",
            "role": "broadcaster",
        }
    token = authorization.removeprefix("Bearer ")
    secret_b64 = os.getenv("TWITCH_EXTENSION_SECRET", "")
    if not secret_b64:
        raise HTTPException(status_code=500, detail="TWITCH_EXTENSION_SECRET not configured")
    try:
        payload = pyjwt.decode(
            token,
            base64.b64decode(secret_b64),
            algorithms=["HS256"],
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Twitch token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid Twitch token")
    return payload


def _require_broadcaster(payload: dict):
    if payload.get("role") != "broadcaster":
        raise HTTPException(status_code=403, detail="Broadcaster role required")


def _pubsub_broadcast(channel_id: str, message: dict):
    """Send a broadcast PubSub message to all open extension panels on a channel."""
    if os.getenv("TWITCH_LOCAL_DEV") == "true":
        print(f"[TWITCH PUBSUB] {json.dumps(message)}")
        return
    secret_b64 = os.getenv("TWITCH_EXTENSION_SECRET", "")
    client_id  = os.getenv("TWITCH_EXTENSION_CLIENT_ID", "")
    if not secret_b64 or not client_id:
        return
    token = pyjwt.encode(
        {
            "exp": int(time.time()) + 60,
            "user_id": channel_id,
            "role": "external",
            "channel_id": channel_id,
            "pubsub_perms": {"send": ["broadcast"]},
        },
        base64.b64decode(secret_b64),
        algorithm="HS256",
    )
    try:
        _requests.post(
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
    except Exception as e:
        print(f"[TWITCH PUBSUB] broadcast failed: {e}")


# ---------------------------------------------------------------------------
# Account linking
# ---------------------------------------------------------------------------

class LinkCodeResponse(BaseModel):
    code: str
    expires_in: int


class LinkBody(BaseModel):
    code: str


def get_session_user(request: Request) -> dict:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user_id}


@router.post("/link-code", response_model=LinkCodeResponse)
def generate_link_code(
    current_user: dict = Depends(get_session_user),
    db: Session = Depends(get_db),
):
    """Generate a 6-character alphanumeric code the user enters in the extension to link accounts."""
    user_id = current_user["user_id"]
    # Invalidate any existing unexpired code for this user
    db.query(TwitchLinkCode).filter_by(user_id=user_id).delete()
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    expires_at = int(time.time()) + _LINK_CODE_TTL
    db.add(TwitchLinkCode(code=code, user_id=user_id, expires_at=expires_at))
    db.commit()
    return {"code": code, "expires_in": _LINK_CODE_TTL}


@router.post("/link")
def link_account(
    body: LinkBody,
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Consume a linking code and store the Twitch user ID on the matching Fantasy account."""
    twitch_user_id = payload.get("opaque_user_id", "")
    if not twitch_user_id or twitch_user_id.startswith("A"):
        raise HTTPException(status_code=400, detail="Twitch account must be logged in to link")

    now = int(time.time())
    link = db.query(TwitchLinkCode).filter_by(code=body.code.upper()).first()
    if not link or link.expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired linking code")

    # Detach this Twitch ID from any previous Fantasy account
    existing = db.query(User).filter_by(twitch_user_id=twitch_user_id).first()
    if existing:
        existing.twitch_user_id = None

    user = db.query(User).filter_by(id=link.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.twitch_user_id = twitch_user_id
    db.delete(link)
    db.commit()
    return {"linked": True, "username": user.username}


# ---------------------------------------------------------------------------
# Viewer presence (heartbeat)
# ---------------------------------------------------------------------------

@router.post("/heartbeat")
def heartbeat(
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Called by the extension panel to record viewer presence. Eligible for giveaway pool."""
    twitch_user_id = payload.get("opaque_user_id", "")
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


# ---------------------------------------------------------------------------
# Viewer status
# ---------------------------------------------------------------------------

@router.get("/status")
def viewer_status(
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Return whether the viewer has linked their Fantasy account, and their token balance."""
    twitch_user_id = payload.get("opaque_user_id", "")
    user = db.query(User).filter_by(twitch_user_id=twitch_user_id).first()
    if not user:
        return {"linked": False, "tokens": None, "username": None}
    return {"linked": True, "tokens": user.tokens, "username": user.username}


# ---------------------------------------------------------------------------
# Match data for MVP selection
# ---------------------------------------------------------------------------

@router.get("/matches/current")
def current_matches(
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Return matches from the current/most-recent week with player lists for MVP selection."""
    now = int(time.time())
    week = (
        db.query(Week)
        .filter(Week.start_time <= now, Week.end_time >= now)
        .first()
    )
    if not week:
        # Fall back to the most recently locked week
        week = (
            db.query(Week)
            .filter(Week.is_locked == True)  # noqa: E712
            .order_by(Week.start_time.desc())
            .first()
        )
    if not week:
        return {"week": None, "matches": []}

    matches = (
        db.query(Match)
        .filter(
            Match.start_time >= week.start_time,
            Match.start_time <= week.end_time,
        )
        .all()
    )

    result = []
    for m in matches:
        stats = (
            db.query(PlayerMatchStats, Player, Team)
            .join(Player, PlayerMatchStats.player_id == Player.id)
            .join(Team, PlayerMatchStats.team_id == Team.id)
            .filter(PlayerMatchStats.match_id == m.match_id)
            .all()
        )
        players = [
            {
                "player_id": pms.player_id,
                "player_name": p.name,
                "team_name": t.name,
                "fantasy_points": pms.fantasy_points,
            }
            for pms, p, t in stats
        ]
        existing_mvp = db.query(TwitchMVP).filter_by(match_id=m.match_id).first()
        result.append({
            "match_id": m.match_id,
            "start_time": m.start_time,
            "players": players,
            "mvp_player_id": existing_mvp.player_id if existing_mvp else None,
        })

    return {"week": {"id": week.id, "label": week.label}, "matches": result}


# ---------------------------------------------------------------------------
# MVP selection
# ---------------------------------------------------------------------------

class MVPBody(BaseModel):
    match_id: int
    player_id: int


@router.post("/mvp")
def set_mvp(
    body: MVPBody,
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Broadcaster sets the MVP for a match. Upserts one record per match."""
    _require_broadcaster(payload)
    channel_id = payload.get("channel_id", "")

    player = db.query(Player).filter_by(id=body.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    existing = db.query(TwitchMVP).filter_by(match_id=body.match_id).first()
    if existing:
        existing.player_id = body.player_id
        existing.channel_id = channel_id
        existing.selected_at = int(time.time())
    else:
        db.add(TwitchMVP(
            match_id=body.match_id,
            player_id=body.player_id,
            channel_id=channel_id,
            selected_at=int(time.time()),
        ))
    db.commit()
    _pubsub_broadcast(channel_id, {"type": "mvp", "player_name": player.name, "match_id": body.match_id})
    return {"match_id": body.match_id, "player_id": body.player_id, "player_name": player.name}


# ---------------------------------------------------------------------------
# Giveaway (single random winner)
# ---------------------------------------------------------------------------

def _active_pool(db: Session, channel_id: str) -> list[str]:
    """Linked viewers who sent a heartbeat within the presence TTL."""
    cutoff = int(time.time()) - _PRESENCE_TTL
    presences = (
        db.query(TwitchPresence)
        .filter(
            TwitchPresence.channel_id == channel_id,
            TwitchPresence.seen_at >= cutoff,
        )
        .all()
    )
    linked_ids = {
        u.twitch_user_id
        for u in db.query(User).filter(User.twitch_user_id.isnot(None)).all()
    }
    return [p.twitch_user_id for p in presences if p.twitch_user_id in linked_ids]


@router.post("/giveaway")
def trigger_giveaway(
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Pick a random linked viewer from the presence pool and grant +1 token."""
    _require_broadcaster(payload)
    channel_id = payload.get("channel_id", "")
    pool = _active_pool(db, channel_id)
    if not pool:
        raise HTTPException(status_code=400, detail="No eligible viewers in pool")

    winner_twitch_id = random.choice(pool)
    winner = db.query(User).filter_by(twitch_user_id=winner_twitch_id).first()
    if not winner:
        raise HTTPException(status_code=500, detail="Winner lookup failed")

    winner.tokens = (winner.tokens or 0) + 1
    db.add(AuditLog(
        timestamp=int(time.time()),
        actor_id=None,
        actor_username="twitch",
        action="twitch_giveaway",
        detail=f"channel={channel_id} winner={winner.username}",
    ))
    db.commit()
    _pubsub_broadcast(channel_id, {"type": "winner", "winner_username": winner.username})
    return {"winner_username": winner.username, "pool_size": len(pool)}


# ---------------------------------------------------------------------------
# Token drop (n random winners)
# ---------------------------------------------------------------------------

class TokenDropBody(BaseModel):
    count: int
    series_id: str = Field(min_length=1, max_length=64)


@router.post("/token-drop")
def token_drop(
    body: TokenDropBody,
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    """Grant +1 token to up to `count` random linked viewers. Once per series_id per channel."""
    _require_broadcaster(payload)
    channel_id = payload.get("channel_id", "")

    existing_drop = (
        db.query(TwitchTokenDrop)
        .filter_by(channel_id=channel_id, series_id=body.series_id)
        .first()
    )
    if existing_drop:
        raise HTTPException(
            status_code=409,
            detail=f"Token drop already performed for series '{body.series_id}' on this channel",
        )

    count = max(1, min(body.count, _TWITCH_DROP_MAX))
    pool = _active_pool(db, channel_id)
    if not pool:
        raise HTTPException(status_code=400, detail="No eligible viewers in pool")

    winners_ids = random.sample(pool, min(count, len(pool)))
    winner_names = []
    for twitch_id in winners_ids:
        user = db.query(User).filter_by(twitch_user_id=twitch_id).first()
        if user:
            user.tokens = (user.tokens or 0) + 1
            winner_names.append(user.username)

    db.add(TwitchTokenDrop(
        channel_id=channel_id,
        series_id=body.series_id,
        dropped_at=int(time.time()),
        count=len(winner_names),
    ))
    db.add(AuditLog(
        timestamp=int(time.time()),
        actor_id=None,
        actor_username="twitch",
        action="twitch_token_drop",
        detail=f"channel={channel_id} series={body.series_id} count={len(winner_names)} winners={','.join(winner_names)}",
    ))
    db.commit()
    _pubsub_broadcast(channel_id, {"type": "token_drop", "winners": winner_names})
    return {"winners": winner_names, "pool_size": len(pool)}
