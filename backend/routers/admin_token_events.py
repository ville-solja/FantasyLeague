"""Admin token-grant events: time-boxed token grants players claim with POST /claim-events
(routers/auth.py). Moved out of routers/admin_users.py (issue #185) to keep that module
under the size budget of tests/test_issue_85_split_admin_router.py."""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from database import get_db
from deps import require_admin, require_recent_reauth, _audit
from models import TokenGrantClaim, TokenGrantEvent

router = APIRouter()


class TokenGrantEventBody(BaseModel):
    amount:     int = Field(..., ge=1)
    start_time: int
    end_time:   int


@router.get("/admin/token-grant-events")
def list_token_grant_events(db=Depends(get_db), _: dict = Depends(require_admin)):
    events = db.query(TokenGrantEvent).order_by(TokenGrantEvent.start_time.desc()).all()
    claim_counts = {
        row[0]: row[1]
        for row in db.query(TokenGrantClaim.event_id, func.count(TokenGrantClaim.id))
                     .group_by(TokenGrantClaim.event_id).all()
    }
    return [
        {
            "id": ev.id, "amount": ev.amount,
            "start_time": ev.start_time, "end_time": ev.end_time,
            "created_at": ev.created_at, "claim_count": claim_counts.get(ev.id, 0),
        }
        for ev in events
    ]


@router.post("/admin/token-grant-events", dependencies=[Depends(require_recent_reauth)])
def create_token_grant_event(
    body: TokenGrantEventBody,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    if body.end_time <= body.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    ev = TokenGrantEvent(
        amount=body.amount,
        start_time=body.start_time,
        end_time=body.end_time,
        created_by=admin["user_id"],
        created_at=int(time.time()),
    )
    db.add(ev)
    db.flush()
    _audit(db, "admin_token_grant_event_created", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={ev.id} amount={ev.amount} start={ev.start_time} end={ev.end_time}")
    db.commit()
    return {"id": ev.id, "amount": ev.amount, "start_time": ev.start_time, "end_time": ev.end_time}


@router.delete("/admin/token-grant-events/{event_id}", dependencies=[Depends(require_recent_reauth)])
def delete_token_grant_event(
    event_id: int,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    ev = db.get(TokenGrantEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    _audit(db, "admin_token_grant_event_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={ev.id} amount={ev.amount}")
    db.delete(ev)
    db.commit()
    return {"ok": True}
