# Plan: Admin Week Management

## Context
Weeks are currently generated automatically from a fixed Sunday anchor date, with lock
times hardcoded at Sunday 23:59:59 UTC. Tournament schedules do not always align — the
specific trigger for this feature is a finals week that begins on Friday at 14:00, meaning
the roster window must close at that time rather than two days later. Admins need a UI
to view all weeks, create custom-timed weeks, adjust the end time (lock deadline) of any
unlocked week, and delete unlocked weeks that have not yet had rosters snapshotted.
Locked weeks remain fully visible but cannot be edited or deleted. *Resolves GitHub issue #48.*

## User Stories

### View All Weeks
**User story**
As an admin, I want to see all week records in a table so that I can understand the
current season structure at a glance.

**Acceptance criteria**
- Admin panel shows a table with columns: label, start time, end time, locked status, roster snapshot count
- All weeks are listed, including past locked weeks
- Locked weeks are visually distinguished (e.g. row style or badge)

### Create a Custom Week
**User story**
As an admin, I want to create a week with a specific label, start time, and end time so
that tournament rounds with irregular schedules (e.g. a finals week) fit into the season.

**Acceptance criteria**
- Admin can submit a label, start\_time (datetime), and end\_time (datetime)
- `end_time` must be strictly after `start_time`; invalid input is rejected with a clear error
- The new week appears in the weeks table immediately
- Creation is logged to the audit log

### Edit an Unlocked Week
**User story**
As an admin, I want to change the end time (and optionally label or start time) of an
unlocked week so that the lock deadline matches the actual tournament schedule.

**Acceptance criteria**
- Editing is only allowed on weeks where `is_locked = false`
- Admin can update label, start\_time, and/or end\_time individually
- `end_time` must remain strictly after `start_time` after the edit
- Changes are saved and reflected in the weeks table immediately
- Edit is logged to the audit log

### Delete an Unlocked Week
**User story**
As an admin, I want to delete an unlocked week that has no roster entries so that
auto-generated placeholder weeks can be removed when the schedule changes.

**Acceptance criteria**
- Delete is only allowed on weeks where `is_locked = false` and `WeeklyRosterEntry` count is 0
- Attempting to delete a locked week returns a 409 error
- Attempting to delete a week that has roster entries returns a 409 error
- Deletion is logged to the audit log
- Deleted weeks disappear from the table

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/admin.py` | Add `GET/POST/PATCH/DELETE /admin/weeks` |
| `frontend/app-admin.js` | `loadAdminWeeks()`, `createWeek()`, `editWeek()`, `deleteWeek()` |
| `frontend/index.html` | Week management panel in admin tab |
| `frontend/app-globals.js` | `loadAdminWeeks()` added to admin tab init |

No model changes needed — `Week` already has `label`, `start_time`, `end_time`, `is_locked`.

### Step 1 — Admin endpoints

Add to `backend/routers/admin.py`:

```python
class WeekCreateBody(BaseModel):
    label:      str = Field(..., min_length=1, max_length=64)
    start_time: int
    end_time:   int

class WeekEditBody(BaseModel):
    label:      str | None = Field(None, min_length=1, max_length=64)
    start_time: int | None = None
    end_time:   int | None = None

@router.get("/admin/weeks")
def list_weeks_admin(db=Depends(get_db), _: dict = Depends(require_admin)):
    weeks = db.query(Week).order_by(Week.start_time).all()
    result = []
    for w in weeks:
        from models import WeeklyRosterEntry
        roster_count = db.query(WeeklyRosterEntry).filter_by(week_id=w.id).count()
        result.append({
            "id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time,
            "is_locked": w.is_locked, "roster_count": roster_count,
        })
    return result

@router.post("/admin/weeks")
def create_week(body: WeekCreateBody, db=Depends(get_db),
                admin: dict = Depends(require_admin)):
    if body.end_time <= body.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    w = Week(label=body.label, start_time=body.start_time,
             end_time=body.end_time, is_locked=False)
    db.add(w); db.flush()
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
    if body.label is not None:
        w.label = body.label
    if body.start_time is not None:
        w.start_time = body.start_time
    if body.end_time is not None:
        w.end_time = body.end_time
    if w.end_time <= w.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    _audit(db, "admin_week_edited", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={w.id} label={w.label} end_time={w.end_time}")
    db.commit()
    return {"id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time}

@router.delete("/admin/weeks/{week_id}")
def delete_week(week_id: int, db=Depends(get_db),
                admin: dict = Depends(require_admin)):
    from models import WeeklyRosterEntry
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
    db.delete(w); db.commit()
    return {"ok": True}
```

### Step 2 — Admin panel UI

In `frontend/index.html`, add a "Week Management" panel to the admin tab (first column,
below Token Balances). Include:
- A "Refresh" button and a create-week form: label input, start datetime, end datetime,
  Create button
- A table: Label | Start | End | Locked | Rosters | Actions
- Each unlocked row gets an "Edit" button (inline, expands the row to editable inputs)
  and a "Delete" button
- Locked rows show "—" in the Actions column

In `frontend/app-admin.js`, add:
- `loadAdminWeeks()` — fetches `GET /admin/weeks` and renders the table
- `createWeek()` — validates inputs and calls `POST /admin/weeks`
- `editWeek(weekId)` — inline expand, then `PATCH /admin/weeks/{id}` on save
- `deleteWeek(weekId)` — calls `DELETE /admin/weeks/{id}` with confirmation

In `frontend/app-globals.js`, add `loadAdminWeeks()` to the admin tab init call.

---

## Verification
- As admin, open the admin tab — weeks table shows all weeks including locked past weeks
- Create a week with a custom label and end time 30 minutes from now — it appears in the table
- Edit the new week's end time — change is reflected immediately
- Attempt to edit a locked week — 409 returned by API; edit button not shown in UI
- Delete an unlocked week with no roster entries — it disappears from the table
- Attempt to delete a locked week — rejected with 409
- Create a week with `end_time <= start_time` — rejected with 422
