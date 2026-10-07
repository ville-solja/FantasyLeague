"""Server-side login sessions (issue #117).

The session cookie carries only {"sid": <random token>}. The `user_sessions` table
stores sha256(sid), never the token itself. Idle and absolute limits depend on the
user's role and are checked here on every authenticated request; `reauth_at`
records the last password re-entry for destructive admin actions.

Settings are read and validated once at import, so a bad value stops the app at
startup (`import main`) with a RuntimeError naming the variable.
"""
import hashlib
import logging
import os
import secrets
import time

from models import User, UserSession

logger = logging.getLogger(__name__)

SID_KEY = "sid"

_DEFAULTS = {
    "SESSION_IDLE_SECONDS": 1_209_600,           # 14 days
    "SESSION_ABSOLUTE_SECONDS": 2_592_000,       # 30 days
    "SESSION_TOUCH_SECONDS": 300,
    "ADMIN_SESSION_IDLE_SECONDS": 7_200,         # 2 hours
    "ADMIN_SESSION_ABSOLUTE_SECONDS": 43_200,    # 12 hours
    "ADMIN_REAUTH_SECONDS": 600,                 # 10 minutes
}
_ALIAS = "SESSION_MAX_AGE_SECONDS"  # issue #119 name for the player absolute limit


def _positive_int(name, raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer number of seconds (got {raw!r}).")
    return value


def load_settings(environ=os.environ) -> dict:
    """Read and validate the six session settings; raise RuntimeError on a bad value."""
    settings = {}
    for name, default in _DEFAULTS.items():
        raw = environ.get(name)
        settings[name] = default if raw is None else _positive_int(name, raw)

    alias_raw = environ.get(_ALIAS)
    if alias_raw is not None:
        alias_value = _positive_int(_ALIAS, alias_raw)
        if environ.get("SESSION_ABSOLUTE_SECONDS") is None:
            settings["SESSION_ABSOLUTE_SECONDS"] = alias_value
            logger.warning("%s is deprecated; use SESSION_ABSOLUTE_SECONDS instead "
                           "(using %d as SESSION_ABSOLUTE_SECONDS).", _ALIAS, alias_value)
        else:
            logger.warning("%s is deprecated and ignored because SESSION_ABSOLUTE_SECONDS "
                           "is set.", _ALIAS)

    for idle, absolute in (("SESSION_IDLE_SECONDS", "SESSION_ABSOLUTE_SECONDS"),
                           ("ADMIN_SESSION_IDLE_SECONDS", "ADMIN_SESSION_ABSOLUTE_SECONDS")):
        if settings[idle] > settings[absolute]:
            raise RuntimeError(f"{idle} ({settings[idle]}) must not be larger than "
                               f"{absolute} ({settings[absolute]}).")
    if settings["SESSION_TOUCH_SECONDS"] >= settings["ADMIN_SESSION_IDLE_SECONDS"]:
        raise RuntimeError(
            f"SESSION_TOUCH_SECONDS ({settings['SESSION_TOUCH_SECONDS']}) must be smaller than "
            f"ADMIN_SESSION_IDLE_SECONDS ({settings['ADMIN_SESSION_IDLE_SECONDS']}).")
    return settings


_settings = load_settings()
SESSION_IDLE_SECONDS = _settings["SESSION_IDLE_SECONDS"]
SESSION_ABSOLUTE_SECONDS = _settings["SESSION_ABSOLUTE_SECONDS"]
SESSION_TOUCH_SECONDS = _settings["SESSION_TOUCH_SECONDS"]
ADMIN_SESSION_IDLE_SECONDS = _settings["ADMIN_SESSION_IDLE_SECONDS"]
ADMIN_SESSION_ABSOLUTE_SECONDS = _settings["ADMIN_SESSION_ABSOLUTE_SECONDS"]
ADMIN_REAUTH_SECONDS = _settings["ADMIN_REAUTH_SECONDS"]
# The cookie must outlive the longest server-side limit; the server decides the rest.
COOKIE_MAX_AGE = max(SESSION_ABSOLUTE_SECONDS, ADMIN_SESSION_ABSOLUTE_SECONDS)


def _now() -> int:
    """The one clock every session check reads (tests patch this)."""
    return int(time.time())


def hash_sid(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def limits_for(user) -> tuple[int, int]:
    """(idle, absolute) limits in seconds for the user's role."""
    if user is not None and user.is_admin:
        return ADMIN_SESSION_IDLE_SECONDS, ADMIN_SESSION_ABSOLUTE_SECONDS
    return SESSION_IDLE_SECONDS, SESSION_ABSOLUTE_SECONDS


def is_expired(row: UserSession, user, now: int | None = None) -> bool:
    now = _now() if now is None else now
    idle, absolute = limits_for(user)
    return now - row.last_seen_at > idle or now - row.created_at > absolute


def _request_sid(request):
    session = getattr(request, "session", None)
    if not session:
        return None
    sid = session.get(SID_KEY)
    return sid if isinstance(sid, str) and sid else None


def current_row(request, db) -> UserSession | None:
    """The user_sessions row the request's cookie points at, or None (no expiry check)."""
    sid = _request_sid(request)
    if not sid:
        return None
    return db.query(UserSession).filter(UserSession.sid_hash == hash_sid(sid)).first()


def create_session(db, user) -> str:
    """Add a new session row for `user` and return its raw ID. The caller commits."""
    sid = secrets.token_urlsafe(32)
    now = _now()
    db.add(UserSession(sid_hash=hash_sid(sid), user_id=user.id,
                       created_at=now, last_seen_at=now))
    db.flush()
    return sid


def start_session(request, db, user) -> None:
    """Issue a fresh session for a newly authenticated user: any session the request
    already carried is deleted, and the cookie gets a new ID. The caller commits."""
    old = current_row(request, db)
    if old is not None:
        db.delete(old)
    sid = create_session(db, user)
    request.session.clear()
    request.session[SID_KEY] = sid


def end_current_session(request, db) -> None:
    """Delete the request's session row (if any) and clear the cookie. The caller commits."""
    row = current_row(request, db)
    if row is not None:
        db.delete(row)
    request.session.clear()


def delete_user_sessions(db, user_id: int, keep_id: int | None = None) -> int:
    """Delete every session row of `user_id` (except `keep_id`). The caller commits."""
    q = db.query(UserSession).filter(UserSession.user_id == user_id)
    if keep_id is not None:
        q = q.filter(UserSession.id != keep_id)
    return q.delete(synchronize_session=False)


def validate_request(request, db):
    """The User the request's session belongs to, or None.

    Rejects (and deletes) a session past its role's idle or absolute limit, and
    touches last_seen_at at most once per SESSION_TOUCH_SECONDS. An invalid session
    is cleared so the response drops the stale cookie."""
    session = getattr(request, "session", None)
    sid = _request_sid(request)
    if not sid:
        if session:
            session.clear()  # e.g. a pre-#117 {"user_id", "sv"} cookie
        return None
    row = db.query(UserSession).filter(UserSession.sid_hash == hash_sid(sid)).first()
    if row is None:
        session.clear()
        return None
    user = db.get(User, row.user_id)
    now = _now()
    if user is None or is_expired(row, user, now):
        db.delete(row)
        db.commit()
        session.clear()
        return None
    if now - row.last_seen_at >= SESSION_TOUCH_SECONDS:
        row.last_seen_at = now
        db.commit()
    return user


def mark_reauth(row: UserSession) -> None:
    """Record a fresh identity check on this session (POST /reauth with the password,
    or a Steam re-auth round trip, issue #150). The caller commits."""
    row.reauth_at = _now()


def reauth_is_recent(row: UserSession | None) -> bool:
    return (row is not None and row.reauth_at is not None
            and _now() - row.reauth_at <= ADMIN_REAUTH_SECONDS)


def cleanup_expired(db) -> int:
    """Delete every session row past its role's limits (or whose user is gone)."""
    now = _now()
    rows = (db.query(UserSession, User)
            .outerjoin(User, User.id == UserSession.user_id).all())
    expired_ids = [row.id for row, user in rows if user is None or is_expired(row, user, now)]
    if expired_ids:
        db.query(UserSession).filter(UserSession.id.in_(expired_ids)).delete(
            synchronize_session=False)
    db.commit()
    return len(expired_ids)
