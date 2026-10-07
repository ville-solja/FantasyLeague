"""Approved streamers (issue #175).

Channels that may set match MVPs are those in TWITCH_MVP_CHANNEL_IDS plus the
`twitch_channel_approvals` rows with status "approved". A broadcaster opening the
MVP tool on any other channel leaves a pending request, which an admin approves or
rejects in the portal (routers/admin_twitch.py). Twitch display names come from
Helix with an app access token, best effort: any failure leaves them empty.
"""
import logging
import os
import re
import threading
import time

import requests as _requests
from sqlalchemy.orm import Session

from models import TwitchChannelApproval

logger = logging.getLogger(__name__)

PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
PENDING_CAP = 200
HELIX_USERS_URL = "https://api.twitch.tv/helix/users"
HELIX_TIMEOUT = 5          # seconds
HELIX_BATCH = 100          # Helix accepts at most 100 ids per call

_CHANNEL_ID_RE = re.compile(r"[0-9]{1,20}")

_token_lock = threading.Lock()
_app_token: str | None = None
_app_token_expires_at = 0.0


def env_channels() -> set[str]:
    """Channel IDs from TWITCH_MVP_CHANNEL_IDS (comma-separated)."""
    raw = os.getenv("TWITCH_MVP_CHANNEL_IDS", "")
    return {c.strip() for c in raw.split(",") if c.strip()}


def portal_approved(db: Session) -> set[str]:
    return {cid for (cid,) in db.query(TwitchChannelApproval.channel_id)
            .filter(TwitchChannelApproval.status == APPROVED).all()}


def approved_channels(db: Session) -> set[str]:
    return env_channels() | portal_approved(db)


def valid_channel_id(channel_id) -> bool:
    return isinstance(channel_id, str) and _CHANNEL_ID_RE.fullmatch(channel_id) is not None


def record_request(db: Session, channel_id: str, now: int | None = None) -> TwitchChannelApproval | None:
    """Insert a pending request or bump last_seen_at on an existing row (any status:
    a rejected channel stays rejected). Invalid ids are ignored. Keeps at most
    PENDING_CAP pending rows, dropping the oldest by last_seen_at. Caller commits."""
    if not valid_channel_id(channel_id):
        return None
    now = int(time.time()) if now is None else now
    row = db.get(TwitchChannelApproval, channel_id)
    if row is not None:
        row.last_seen_at = now
        return row
    pending = db.query(TwitchChannelApproval).filter(TwitchChannelApproval.status == PENDING)
    excess = pending.count() - (PENDING_CAP - 1)
    if excess > 0:
        for old in pending.order_by(TwitchChannelApproval.last_seen_at.asc()).limit(excess).all():
            db.delete(old)
    row = TwitchChannelApproval(channel_id=channel_id, status=PENDING,
                                first_seen_at=now, last_seen_at=now)
    db.add(row)
    return row


# ---------------------------------------------------------------------------
# Helix name lookup (best effort)
# ---------------------------------------------------------------------------

def _helix_credentials() -> tuple[str, str] | None:
    import twitch_oauth
    cfg = twitch_oauth.oauth_config()
    if not cfg:
        return None
    return cfg["client_id"], cfg["client_secret"]


def _get_app_token(client_id: str, client_secret: str) -> str:
    """Client-credentials app access token, cached in memory until shortly before expiry."""
    global _app_token, _app_token_expires_at
    import twitch_oauth
    with _token_lock:
        if _app_token and time.time() < _app_token_expires_at:
            return _app_token
        resp = _requests.post(twitch_oauth.TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        }, timeout=HELIX_TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(f"app token request failed ({resp.status_code})")
        data = resp.json()
        _app_token = data["access_token"]
        _app_token_expires_at = time.time() + max(0, int(data.get("expires_in", 0)) - 60)
        return _app_token


def fetch_twitch_users(channel_ids: list[str]) -> dict[str, dict]:
    """{channel_id: {"display_name", "login"}} from Helix GET /users (one call, at
    most HELIX_BATCH ids). Raises on any failure; callers treat that as no names."""
    creds = _helix_credentials()
    if not creds or not channel_ids:
        return {}
    client_id, client_secret = creds
    token = _get_app_token(client_id, client_secret)
    resp = _requests.get(HELIX_USERS_URL,
                         params=[("id", cid) for cid in channel_ids[:HELIX_BATCH]],
                         headers={"Client-Id": client_id, "Authorization": f"Bearer {token}"},
                         timeout=HELIX_TIMEOUT)
    if resp.status_code != 200:
        if resp.status_code == 401:
            _forget_app_token()
        raise RuntimeError(f"Helix users request failed ({resp.status_code})")
    return {str(u["id"]): {"display_name": u.get("display_name"), "login": u.get("login")}
            for u in resp.json().get("data", [])}


def _forget_app_token() -> None:
    global _app_token, _app_token_expires_at
    with _token_lock:
        _app_token, _app_token_expires_at = None, 0.0


def _lookup_names(channel_ids: list[str]) -> dict[str, dict]:
    if not channel_ids or _helix_credentials() is None:
        return {}
    try:
        return fetch_twitch_users(channel_ids[:HELIX_BATCH])
    except Exception as exc:
        logger.warning("Twitch channel name lookup failed: %s", type(exc).__name__)
        return {}


# ---------------------------------------------------------------------------
# Admin list and decisions
# ---------------------------------------------------------------------------

def _row_dict(row: TwitchChannelApproval | None, channel_id: str, from_env: bool) -> dict:
    return {
        "channel_id": channel_id,
        "display_name": row.display_name if row else None,
        "login": row.login if row else None,
        "status": APPROVED if from_env else row.status,
        "first_seen_at": row.first_seen_at if row else None,
        "last_seen_at": row.last_seen_at if row else None,
        "decided_at": row.decided_at if row else None,
        "from_env": from_env,
    }


def list_channels(db: Session) -> dict:
    """{env, approved, pending, rejected}. Env channels appear only under env (they are
    approved from server settings); missing names are filled from Helix and stored."""
    env = env_channels()
    rows = {r.channel_id: r for r in db.query(TwitchChannelApproval).all()}
    # Env channels first, then the most recently seen rows, within one Helix batch.
    missing = [cid for cid in sorted(env) if cid not in rows or not rows[cid].display_name]
    missing += [r.channel_id for r in sorted(rows.values(), key=lambda r: r.last_seen_at, reverse=True)
                if not r.display_name and r.channel_id not in env]
    env_names: dict[str, dict] = {}
    if missing:
        found = _lookup_names(missing)
        for cid, names in found.items():
            if cid in rows:
                rows[cid].display_name = names.get("display_name")
                rows[cid].login = names.get("login")
            else:
                env_names[cid] = names
        if any(cid in rows for cid in found):
            db.commit()

    result = {"env": [], APPROVED: [], PENDING: [], REJECTED: []}
    for cid in sorted(env):
        item = _row_dict(rows.get(cid), cid, from_env=True)
        if cid in env_names:
            item.update(display_name=env_names[cid].get("display_name"), login=env_names[cid].get("login"))
        result["env"].append(item)
    for cid, row in rows.items():
        if cid in env or row.status not in (APPROVED, PENDING, REJECTED):
            continue
        result[row.status].append(_row_dict(row, cid, from_env=False))
    for key in (APPROVED, PENDING, REJECTED):
        result[key].sort(key=lambda r: r["last_seen_at"] or 0, reverse=True)
    return result


class ChannelNotFound(Exception):
    pass


class ChannelConflict(Exception):
    pass


_ACTIONS = {
    # action: (statuses it applies to, new status, audit action)
    "approve": ((PENDING, REJECTED, APPROVED), APPROVED, "twitch_channel_approved"),
    "reject": ((PENDING,), REJECTED, "twitch_channel_rejected"),
    "remove": ((APPROVED,), REJECTED, "twitch_channel_removed"),
}


def decide(db: Session, channel_id: str, action: str, admin: dict) -> dict:
    """Approve, reject or remove a channel and write the audit entry. Caller commits.
    Raises ChannelNotFound (no row) or ChannelConflict (env channel, wrong status)."""
    from deps import _audit
    allowed_from, new_status, audit_action = _ACTIONS[action]
    in_env = channel_id in env_channels()
    if in_env and action in ("reject", "remove"):
        raise ChannelConflict("This channel is approved in server settings (TWITCH_MVP_CHANNEL_IDS)")
    row = db.get(TwitchChannelApproval, channel_id)
    if row is None:
        if in_env:
            raise ChannelConflict("This channel is approved in server settings (TWITCH_MVP_CHANNEL_IDS)")
        raise ChannelNotFound("Channel not found")
    if row.status not in allowed_from:
        raise ChannelConflict(f"Channel is {row.status}")
    old_status = row.status
    row.status = new_status
    row.decided_at = int(time.time())
    row.decided_by = admin["user_id"]
    _audit(db, audit_action, actor_id=admin["user_id"], actor_username=admin.get("username"),
           detail=f"channel={channel_id} status={old_status}->{new_status}")
    return _row_dict(row, channel_id, from_env=False)
