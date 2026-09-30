import time

from fastapi import Depends, HTTPException, Request

from database import get_db
from models import AuditLog, User


SESSION_VERSION_KEY = "sv"


def _session_user(request: Request, db):
    """The User the session belongs to, or None. A session is valid only while its
    stored version matches users.session_version; bumping that number revokes every
    session of the user at once. An invalid session is cleared so the response drops
    the stale cookie."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or request.session.get(SESSION_VERSION_KEY) != (user.session_version or 0):
        request.session.clear()
        return None
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


def start_session(request: Request, user: User) -> None:
    """Write a freshly authenticated user into the session."""
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["is_admin"] = user.is_admin
    request.session[SESSION_VERSION_KEY] = user.session_version or 0


def bump_session_version(user: User) -> int:
    """Invalidate every existing session of `user`. The caller commits."""
    user.session_version = (user.session_version or 0) + 1
    return user.session_version


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


def _audit(db, action: str, actor_id=None, actor_username=None, detail=None):
    db.add(AuditLog(
        timestamp=int(time.time()),
        actor_id=actor_id,
        actor_username=actor_username,
        action=action,
        detail=detail,
    ))
    # Caller is responsible for committing
