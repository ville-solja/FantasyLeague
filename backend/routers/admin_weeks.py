import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from database import get_db
from deps import require_admin, _audit
from models import Week, WeeklyRosterEntry

router = APIRouter()


class WeekCreateBody(BaseModel):
    label:      str = Field(..., min_length=1, max_length=64)
    start_time: int | None = None
    end_time:   int | None = None
    start_date: str | None = Field(None, min_length=10, max_length=10)  # ISO date YYYY-MM-DD
    end_date:   str | None = Field(None, min_length=10, max_length=10)  # ISO date YYYY-MM-DD


class WeekEditBody(BaseModel):
    label:      str | None = Field(None, min_length=1, max_length=64)
    start_time: int | None = None
    end_time:   int | None = None
    start_date: str | None = Field(None, min_length=10, max_length=10)  # ISO date YYYY-MM-DD
    end_date:   str | None = Field(None, min_length=10, max_length=10)  # ISO date YYYY-MM-DD


def _derive_week_times(start_date: str | None, end_date: str | None) -> tuple[int | None, int | None]:
    """Derive week timestamps from date-only inputs.

    start_time = start_date 03:00:00 UTC
    end_time   = (end_date + 1 day) 02:59:59 UTC

    The 3-hour offset on both ends is the grace period that lets a match starting
    late on the chosen end date and running past midnight still count toward that
    week. Applying the same offset to start_time (rather than leaving it at
    midnight) means a normal Monday-start/Sunday-end week's end_time
    (following Monday 02:59:59 UTC) lands exactly one second before the next
    Monday-start week's start_time (that Monday 03:00:00 UTC) — contiguous, no
    gap, no overlap, with no admin workaround required for the standard cadence.
    """
    start_time = end_time = None
    try:
        if start_date:
            d = datetime.date.fromisoformat(start_date)
            start_time = int(datetime.datetime(
                d.year, d.month, d.day, 3, 0, 0,
                tzinfo=datetime.timezone.utc).timestamp())
        if end_date:
            d = datetime.date.fromisoformat(end_date) + datetime.timedelta(days=1)
            end_time = int(datetime.datetime(
                d.year, d.month, d.day, 2, 59, 59,
                tzinfo=datetime.timezone.utc).timestamp())
    except ValueError:
        raise HTTPException(status_code=422,
                            detail="Dates must be ISO format (YYYY-MM-DD)")
    return start_time, end_time


def _check_week_overlap(db, start_time: int, end_time: int, exclude_week_id: int | None = None):
    """Reject a [start_time, end_time) range that overlaps any other week's range,
    regardless of lock status. Exactly-abutting ranges (one's end_time equals the
    other's start_time) are not an overlap."""
    q = db.query(Week).filter(Week.start_time < end_time, Week.end_time > start_time)
    if exclude_week_id is not None:
        q = q.filter(Week.id != exclude_week_id)
    conflict = q.first()
    if conflict:
        raise HTTPException(
            status_code=409,
            detail=f'Overlaps existing week "{conflict.label}"',
        )


@router.get("/admin/weeks")
def list_weeks_admin(db=Depends(get_db), _: dict = Depends(require_admin)):
    weeks = db.query(Week).order_by(Week.start_time).all()
    roster_counts = {
        row[0]: row[1]
        for row in db.query(WeeklyRosterEntry.week_id, func.count(WeeklyRosterEntry.id))
                     .group_by(WeeklyRosterEntry.week_id).all()
    }
    return [
        {
            "id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time,
            "is_locked": w.is_locked, "roster_count": roster_counts.get(w.id, 0),
        }
        for w in weeks
    ]


@router.post("/admin/weeks")
def create_week(body: WeekCreateBody, db=Depends(get_db),
                admin: dict = Depends(require_admin)):
    date_start, date_end = _derive_week_times(body.start_date, body.end_date)
    start_time = date_start if date_start is not None else body.start_time
    end_time   = date_end   if date_end   is not None else body.end_time
    if start_time is None or end_time is None:
        raise HTTPException(status_code=422,
                            detail="Provide start/end as dates or timestamps")
    if end_time <= start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    _check_week_overlap(db, start_time, end_time)
    w = Week(label=body.label, start_time=start_time,
             end_time=end_time, is_locked=False)
    db.add(w)
    db.flush()
    _audit(db, "admin_week_created", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={w.id} label={w.label} end_time={w.end_time}")
    db.commit()
    return {"id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time}


@router.patch("/admin/weeks/{week_id}")
def edit_week(week_id: int, body: WeekEditBody, db=Depends(get_db),
              admin: dict = Depends(require_admin)):
    w = db.get(Week, week_id)
    if not w:
        raise HTTPException(status_code=404, detail="Week not found")
    if w.is_locked:
        raise HTTPException(status_code=409, detail="Cannot edit a locked week")
    date_start, date_end = _derive_week_times(body.start_date, body.end_date)
    if body.label is not None:
        w.label = body.label
    if date_start is not None:
        w.start_time = date_start
    elif body.start_time is not None:
        w.start_time = body.start_time
    if date_end is not None:
        w.end_time = date_end
    elif body.end_time is not None:
        w.end_time = body.end_time
    if w.end_time <= w.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    _check_week_overlap(db, w.start_time, w.end_time, exclude_week_id=w.id)
    _audit(db, "admin_week_edited", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={w.id} label={w.label} end_time={w.end_time}")
    db.commit()
    return {"id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time}


@router.delete("/admin/weeks/{week_id}")
def delete_week(week_id: int, db=Depends(get_db),
                admin: dict = Depends(require_admin)):
    w = db.get(Week, week_id)
    if not w:
        raise HTTPException(status_code=404, detail="Week not found")
    if w.is_locked:
        raise HTTPException(status_code=409, detail="Cannot delete a locked week")
    roster_count = db.query(WeeklyRosterEntry).filter_by(week_id=week_id).count()
    if roster_count > 0:
        raise HTTPException(status_code=409,
                            detail="Cannot delete a week that has roster entries")
    _audit(db, "admin_week_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"id={w.id} label={w.label}")
    db.delete(w)
    db.commit()
    return {"ok": True}
