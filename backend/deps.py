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


def require_admin(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """Admin gate for destructive/admin-only endpoints. Re-checks `is_admin` against the
    database on every call rather than trusting the session's cached value — the session is
    only refreshed at login, so without this a demoted admin would keep destructive access
    (season reset, league purge, user management) for the rest of their session lifetime."""
    user = db.query(User).filter_by(id=current_user["user_id"]).first()
    if not user or not user.is_admin:
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
