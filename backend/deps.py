import time

from fastapi import Depends, HTTPException, Request

from database import get_db
from models import AuditLog, User


def get_current_user(request: Request) -> dict:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user_id, "username": request.session.get("username"),
            "is_admin": request.session.get("is_admin", False)}


def is_admin_fresh(db, user_id: int) -> bool:
    """DB-authoritative admin check. Use this — not `current_user["is_admin"]` — for any
    "owner OR admin" access check outside require_admin, since the session's is_admin value
    is only refreshed at login and would otherwise let a demoted admin keep cross-user access
    for the rest of their session."""
    user = db.query(User).filter_by(id=user_id).first()
    return bool(user and user.is_admin)


def require_admin(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """Admin gate for destructive/admin-only endpoints. Re-checks `is_admin` against the
    database on every call rather than trusting the session's cached value — the session is
    only refreshed at login, so without this a demoted admin would keep destructive access
    (season reset, league purge, user management) for the rest of their session lifetime."""
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
