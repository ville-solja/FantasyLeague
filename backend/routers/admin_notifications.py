import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from database import get_db
from deps import require_admin, require_recent_reauth, _audit
from models import Notification, NotificationDismissal
from text_safety import foreign_urls, strip_invisible

router = APIRouter()


class NotificationBody(BaseModel):
    message:    str = Field(..., min_length=1, max_length=500)
    start_time: int
    end_time:   int


@router.get("/admin/notifications")
def list_notifications(db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = db.query(Notification).order_by(Notification.start_time.desc()).all()
    dismiss_counts = {
        row[0]: row[1]
        for row in db.query(NotificationDismissal.notification_id, func.count(NotificationDismissal.id))
                     .group_by(NotificationDismissal.notification_id).all()
    }
    return [
        {"id": n.id, "message": n.message,
         "start_time": n.start_time, "end_time": n.end_time,
         "dismiss_count": dismiss_counts.get(n.id, 0)}
        for n in rows
    ]


# A notification pops up for every player with the league's own authority, so it
# needs a recent password check and may link only to this site (issue #166, #167).
@router.post("/admin/notifications", dependencies=[Depends(require_recent_reauth)])
def create_notification(body: NotificationBody, db=Depends(get_db),
                        admin: dict = Depends(require_admin)):
    if body.end_time <= body.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    message = strip_invisible(body.message)
    if not message:
        raise HTTPException(status_code=422, detail="Message cannot be empty")
    if foreign_urls(message, os.getenv("APP_BASE_URL", "")):
        raise HTTPException(status_code=422,
                            detail="Notifications may only link to this site (APP_BASE_URL)")
    n = Notification(message=message, start_time=body.start_time,
                     end_time=body.end_time, created_by=admin["user_id"],
                     created_at=int(time.time()))
    db.add(n)
    db.flush()
    _audit(db, "admin_notification_created", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"id={n.id}")
    db.commit()
    return {"id": n.id}


@router.delete("/admin/notifications/{notification_id}", dependencies=[Depends(require_recent_reauth)])
def delete_notification(notification_id: int, db=Depends(get_db),
                        admin: dict = Depends(require_admin)):
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    _audit(db, "admin_notification_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"id={n.id}")
    db.delete(n)
    db.commit()
    return {"ok": True}
