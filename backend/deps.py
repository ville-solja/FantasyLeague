import time

from fastapi import Depends, HTTPException, Request

import sessions
from database import get_db
from models import AuditLog, User


def _session_user(request: Request, db):
    """The User the request's server-side session belongs to, or None (issue #117).
    See sessions.validate_request: the cookie's session ID must have a
    user_sessions row within the role's idle and absolute limits."""
    user = sessions.validate_request(request, db)
    if user is not None and getattr(user, "account_type", None) == "twitch":
        return None  # soft accounts (issue #157) never sign in on the website
    if user is not None:
        try:
            # Per-user rate-limit key (rate_limit.key_by_user_or_ip); the cookie
            # no longer carries the user id.
            request.state.session_user_id = user.id
        except AttributeError:
            pass
    return user


def session_user_or_none(request: Request, db):
    """For optional-login routes: the valid session's User, or None when logged out or revoked."""
    if not hasattr(request, "session"):
        return None
    return _session_user(request, db)


def get_current_user(request: Request, db=Depends(get_db)) -> dict:
    user = _session_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user.id, "username": user.username, "is_admin": bool(user.is_admin)}


def is_admin_fresh(db, user_id: int) -> bool:
    """DB-authoritative admin check. Use this — not `current_user["is_admin"]` — for any
    "owner OR admin" access check outside require_admin, since the session's is_admin value
    is only refreshed at login and would otherwise let a demoted admin keep cross-user access
    for the rest of their session."""
    user = db.query(User).filter_by(id=user_id).first()
    return bool(user and user.is_admin)


def require_admin(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """Admin gate for destructive/admin-only endpoints. Checks `is_admin` against the
    database, so a demotion takes effect on the next request."""
    if not is_admin_fresh(db, current_user["user_id"]):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_recent_reauth(request: Request, admin: dict = Depends(require_admin),
                          db=Depends(get_db)):
    """Destructive admin actions need a POST /reauth on this session within
    ADMIN_REAUTH_SECONDS; otherwise 403 {"detail": "reauth_required"}. Add it as a
    route-level dependency so direct function calls in tests are unaffected."""
    if not sessions.reauth_is_recent(sessions.current_row(request, db)):
        raise HTTPException(status_code=403, detail="reauth_required")
    return admin


def require_recent_player_reauth(request: Request, current_user: dict = Depends(get_current_user),
                                 db=Depends(get_db)):
    """Like require_recent_reauth, for any logged-in user (issue #160: connecting,
    merging and disconnecting Twitch). POST /reauth works for players too."""
    if not sessions.reauth_is_recent(sessions.current_row(request, db)):
        raise HTTPException(status_code=403, detail="reauth_required")
    return current_user


def _audit(db, action: str, actor_id=None, actor_username=None, detail=None):
    db.add(AuditLog(
        timestamp=int(time.time()),
        actor_id=actor_id,
        actor_username=actor_username,
        action=action,
        detail=detail,
    ))
    # Caller is responsible for committing
