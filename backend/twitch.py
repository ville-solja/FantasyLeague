"""Twitch Extension Backend Service (EBS) routes.

All endpoints are under /twitch/. Authentication is via Twitch-signed JWT
(validated by verify_twitch_jwt), except /twitch/link-code which requires
an active Fantasy session.

Set TWITCH_LOCAL_DEV=true in .env to bypass JWT validation and PubSub HTTP
calls for local development.
"""
import base64
import json
import logging
import os
import random
import secrets
import string
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
from database import get_db
from deps import get_current_user
from models import (AuditLog, LiveMatch, Match, Player, PlayerMatchStats,
                    Team, TwitchLinkCode, TwitchMVP, TwitchPresence,
                    TwitchTokenDrop, User, Week, Weight)
from rate_limit import limiter
from schedule import bust_cache
from scoring import apply_mvp_bonus_to_row, display_points

router = APIRouter(prefix="/twitch", tags=["twitch"])

_LINK_CODE_TTL    = 600   # seconds — 10 minutes
_PRESENCE_TTL     = 600   # seconds — viewers expire from pool after 10 min inactive
_TWITCH_DROP_MAX  = int(os.getenv("TWITCH_DROP_MAX", "20"))

# Per-IP limit on link-code guessing (issue #135). link_account stays a plain
# function so direct calls keep working; link_account_route carries the
# `request` parameter slowapi needs (same split as routers/cards.py).
RATE_LIMIT_TWITCH_LINK = os.getenv("RATE_LIMIT_TWITCH_LINK", "10/minute")

_LINK_CODE_ALPHABET = string.ascii_uppercase + string.digits

_CHAT_TEXT_MAX         = 280  # Twitch Send Extension Chat Message limit
_TWITCH_ERROR_BODY_MAX = 300  # chars of a failed Twitch response kept in the log
_chat_version_warned   = False  # TWITCH_EXTENSION_VERSION warning logged once per process


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
        if os.getenv("ENV", "").lower() == "production":
            raise HTTPException(
                status_code=500,
                detail="TWITCH_LOCAL_DEV must not be set in production",
            )
        return {
            "channel_id": "dev_channel",
            "opaque_user_id": "Udev123",
            "role": "broadcaster",
        }
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
        )
    except pyjwt.ExpiredSignatureError:
        logger.error("Twitch JWT expired")
        raise HTTPException(status_code=401, detail="Twitch token expired")
    except pyjwt.InvalidTokenError as exc:
        logger.error("Twitch JWT invalid (secret len=%d decoded_bytes=%d): %s",
                     len(secret_b64), len(secret_bytes), exc)
        raise HTTPException(status_code=401, detail="Invalid Twitch token")
    except Exception as exc:
        logger.error("Twitch JWT decode unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="JWT decode error")
    return payload


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


def _mvp_chat_text(player_name: str, winner_names: list[str], token_name: str,
                   pool_empty: bool) -> str:
    """Build the MVP chat announcement within Twitch's 280-character limit.

    The MVP name is always kept in full; winners are listed until the next one
    (plus ", and N more") would pass the limit.
    """
    base = f"Match MVP: {player_name}!"
    if not winner_names:
        return base + (" (No linked viewers in the drop pool.)" if pool_empty else "")
    prefix = f"{base} Token drop winners (+1 {token_name}): "
    full = prefix + ", ".join(winner_names)
    if len(full) <= _CHAT_TEXT_MAX:
        return full
    listed: list[str] = []
    for name in winner_names:
        remaining = len(winner_names) - len(listed) - 1
        candidate = prefix + ", ".join(listed + [name]) + f", and {remaining} more"
        if len(candidate) > _CHAT_TEXT_MAX:
            break
        listed.append(name)
    remaining = len(winner_names) - len(listed)
    if not listed:
        return f"{base} {remaining} viewers won +1 {token_name}."
    return prefix + ", ".join(listed) + f", and {remaining} more"


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
# Account linking
# ---------------------------------------------------------------------------

class LinkCodeResponse(BaseModel):
    code: str
    expires_in: int


class LinkBody(BaseModel):
    code: str = Field(min_length=1, max_length=6)


def get_session_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Session-cookie auth for the /twitch/* routes that do not use a Twitch JWT."""
    return current_user


@router.post("/link-code", response_model=LinkCodeResponse)
def generate_link_code(
    current_user: dict = Depends(get_session_user),
    db: Session = Depends(get_db),
):
    """Generate a 6-character alphanumeric code the user enters in the extension to link accounts."""
    user_id = current_user["user_id"]
    # Invalidate any existing unexpired code for this user
    db.query(TwitchLinkCode).filter_by(user_id=user_id).delete()
    code = "".join(secrets.choice(_LINK_CODE_ALPHABET) for _ in range(6))
    expires_at = int(time.time()) + _LINK_CODE_TTL
    db.add(TwitchLinkCode(code=code, user_id=user_id, expires_at=expires_at))
    db.commit()
    return {"code": code, "expires_in": _LINK_CODE_TTL}


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


@router.post("/link")
@limiter.limit(RATE_LIMIT_TWITCH_LINK)
def link_account_route(
    request: Request,
    body: LinkBody,
    payload: dict = Depends(verify_twitch_jwt),
    db: Session = Depends(get_db),
):
    return link_account(body, payload, db)


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

_CURRENT_SERIES_LIMIT = 5


def _live_players(live_row: LiveMatch) -> list[dict]:
    try:
        players = json.loads(live_row.players_json or "[]")
    except ValueError:
        return []
    return [p for p in players if isinstance(p, dict) and p.get("account_id")]


def _live_display_name(account_id: int, live_name: str | None, known_names: dict[int, str]) -> str:
    """Known players name, else the /live name, else "Player {account_id}"."""
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
    """Return the 5 most recent series with ingested or live match data, across any week."""
    series = _current_series(db)
    if not series:
        return {"series": []}
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

    return {"series": result_series}


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

def _active_pool(db: Session, channel_id: str) -> list[str]:
    """Linked viewers who sent a heartbeat within the presence TTL."""
    cutoff = int(time.time()) - _PRESENCE_TTL
    from sqlalchemy import text as _text
    rows = db.execute(_text("""
        SELECT p.twitch_user_id
        FROM twitch_presence p
        JOIN users u ON u.twitch_user_id = p.twitch_user_id
        WHERE p.channel_id = :channel_id
          AND p.seen_at >= :cutoff
    """), {"channel_id": channel_id, "cutoff": cutoff}).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# MVP selection — also triggers a one-time token drop for the match
# ---------------------------------------------------------------------------

def _execute_token_drop(
    db: Session, channel_id: str, match_id: int, weights: dict
) -> tuple[list[str], int, bool]:
    """Grant tokens to a random sample of present linked viewers. Returns (winner_names, pool_size, already_dropped)."""
    drop_key = str(match_id)
    already_dropped = bool(
        db.query(TwitchTokenDrop).filter_by(channel_id=channel_id, series_id=drop_key).first()
    )
    winner_names: list[str] = []
    pool_size = 0

    if not already_dropped:
        pool = _active_pool(db, channel_id)
        pool_size = len(pool)
        if pool and not _claim_drop(db, channel_id, drop_key):
            # Another confirmation claimed this drop between the check above and now.
            return winner_names, pool_size, True
        if pool:
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
                    winner_names.append(user.username)
            db.query(TwitchTokenDrop).filter_by(channel_id=channel_id, series_id=drop_key).update(
                {TwitchTokenDrop.count: len(winner_names)}, synchronize_session=False)
            db.add(AuditLog(
                timestamp=int(time.time()),
                actor_id=None,
                actor_username="twitch",
                action="twitch_token_drop",
                detail=f"channel={channel_id} match={match_id} count={len(winner_names)} winners={','.join(winner_names)}",
            ))

    return winner_names, pool_size, already_dropped


def _mvp_allowed_channels() -> set[str]:
    """Channel IDs from TWITCH_MVP_CHANNEL_IDS (comma-separated). Empty set = any channel."""
    raw = os.getenv("TWITCH_MVP_CHANNEL_IDS", "")
    return {c.strip() for c in raw.split(",") if c.strip()}


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
    # channel allowlist goes first so other channels learn nothing about IDs.
    allowed_channels = _mvp_allowed_channels()
    if allowed_channels and channel_id not in allowed_channels:
        raise HTTPException(status_code=403, detail="This channel cannot set match MVPs")
    match = db.get(Match, body.match_id)
    live_row = db.get(LiveMatch, body.match_id)
    if not match and not live_row:
        raise HTTPException(status_code=404, detail="Match not found")
    if body.match_id not in _eligible_mvp_match_ids(db):
        raise HTTPException(status_code=403, detail="Match is not in the current series window")

    # A stored live match with no ingested stats yet: the player must be one of
    # its /live players, and the bonus is applied later by ingest._reapply_mvp_bonus.
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

    if not provisional:
        # Clear bonus from previous MVP if different player
        if old_player_id and old_player_id != body.player_id:
            _apply_mvp_bonus(db, old_player_id, body.match_id, apply=False, weights=weights)
        # Apply bonus to new MVP
        _apply_mvp_bonus(db, body.player_id, body.match_id, apply=True, weights=weights)
        card_points.refresh_card_points(db, match_ids=[body.match_id])

    # Token drop — once per match
    winner_names, pool_size, already_dropped = _execute_token_drop(
        db, channel_id, body.match_id, weights
    )

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
    _pubsub_broadcast(channel_id, {
        "type": "mvp",
        "player_name": player_name,
        "match_id": body.match_id,
        "token_drop_winners": winner_names,
    })

    token_name = os.getenv("TOKEN_NAME", "tokens")
    chat_msg = _mvp_chat_text(player_name, winner_names, token_name,
                              pool_empty=not already_dropped and pool_size == 0)
    _post_chat_message(channel_id, chat_msg)

    return {
        "match_id": body.match_id,
        "player_id": body.player_id,
        "player_name": player_name,
        "token_drop": {
            "winners": winner_names,
            "pool_size": pool_size,
            "already_dropped": already_dropped,
        },
    }
