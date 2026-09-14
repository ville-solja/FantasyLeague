# Plan: Week Boundary Formula Fix

## Context
Issue #111 asks to check Week Management against its original intent and the local changes
made this session, and specifies the exact timestamps a normal Monday–Sunday week should
produce: selecting **Monday** as the start date should store `03:00 UTC that Monday`, and
selecting **Sunday** as the end date should store `02:59 UTC the following Monday` — not
midnight on either side. The stated reason matches this app's existing grace-period rationale
(a match starting late Sunday night can run past midnight and still count toward the week that's
ending) but goes further: it eliminates the overlap *by construction* for the standard weekly
cadence, rather than relying on the overlap guard to reject it and an admin to manually work
around the rejection with a raw timestamp.

**Comparing against what's already shipped** (`plan-issue-84-week-management-editing.md`,
implemented and merged): date-only label/start/end week creation, inline table editing with a
Save Changes flow, per-row Delete, and the overlap-rejection guard are all already built and
match the issue's description of "add weeks by setting label, start date and end date" and
"weeks that are not locked should have buttons for edit... and then saving or deleting."
**What is not yet built** is the specific timestamp formula above. The current
`_derive_week_times` (`backend/routers/admin_weeks.py`) produces `start_time` = start date at
`00:00:00 UTC` and `end_time` = the day after end date at `03:00:00 UTC`. For a normal
Monday-start/Sunday-end week, that makes `end_time` land 3 hours into the *same* calendar day
the next week's Monday selection would also claim from `00:00:00 UTC` — a guaranteed 3-hour
overlap, caught (correctly) by the guard, but only after the admin hits a confusing rejection
and has to fall back to a raw-timestamp workaround (observed directly this session on the
Week 3 → Week 4 boundary). The formula in this plan removes that collision for the standard
case entirely — no admin workaround needed for a normal Monday–Sunday week ever again.

This does not touch already-created weeks (including the currently-locked Week 1 in prod, whose
boundary predates any of this and remains a historical fact) — only how new/edited weeks are
computed going forward.

*Resolves GitHub issue #111.*

## User Stories

### Monday-Start, Sunday-End Weeks Never Overlap by Default
**User story**
As an admin, I want a normal week I create by picking a Monday start date and a Sunday end date
to never collide with the next Monday-starting week, so I don't have to fight the overlap guard
or compute a raw timestamp for routine weekly scheduling.

**Acceptance criteria**
- Selecting a Monday as `start_date` stores `start_time` = that Monday at `03:00:00 UTC` (not
  `00:00:00 UTC`)
- Selecting a Sunday as `end_date` stores `end_time` = the *following* Monday at `02:59:59 UTC`
  (not `03:00:00 UTC`) — one second before the next Monday-start week's `start_time`, so the two
  ranges are contiguous with no gap and no overlap
- A week created this way for a normal Monday–Sunday span, immediately followed by another
  Monday-start week, is accepted by `POST /admin/weeks` without triggering the overlap guard —
  no manual raw-timestamp workaround needed
- A match starting any time up to `02:59:59 UTC` the Monday after the nominal end date (i.e. one
  that runs past midnight from a Sunday-night start) still falls inside the ending week's range,
  preserving the existing grace-period intent
- Non-Monday/non-Sunday selections still work exactly as before — this is a formula change, not
  a restriction on which days can be chosen
- Already-existing weeks (created under the old formula, including any currently locked) are
  unaffected — this only changes how *new* `start_date`/`end_date` input is converted going
  forward

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/admin_weeks.py` | `_derive_week_times`: change `start_time` from `start_date 00:00:00 UTC` to `start_date 03:00:00 UTC`; change `end_time` from `(end_date + 1 day) 03:00:00 UTC` to `(end_date + 1 day) 02:59:59 UTC` |
| `markdown/features/reference/admin-week-management.md` | Update the documented formula (`start_time` / `end_time` derivation) and the "03:00 UTC buffer" explanation |

### Step 1 — Update the formula
In `backend/routers/admin_weeks.py::_derive_week_times`:
```python
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
```
No other call site needs to change: `create_week`/`edit_week` already just use whichever of
`date_start`/`date_end` this returns, and `frontend/app-admin-weeks.js`'s reverse conversion
(`_utcDateStr(w.start_time)` and `_utcDateStr(w.end_time - 24 * 3600)`, used to redisplay a
stored week's dates in the edit inputs) still recovers the correct calendar date either way,
since neither `03:00:00` nor `02:59:59` crosses a UTC midnight boundary relative to the date it
belongs to.

### Step 2 — Documentation
Update `markdown/features/reference/admin-week-management.md`'s Overview to state the new
formula and explain why both ends are offset by the same 3-hour grace period (not just the end),
with the worked Monday/Sunday example from the issue.

## Verification
- `_derive_week_times("2026-09-14", "2026-09-20")` (a Monday start, Sunday end) →
  `start_time` = `2026-09-14 03:00:00 UTC`, `end_time` = `2026-09-21 02:59:59 UTC`
- Creating that week, then immediately creating a second week with `start_date="2026-09-21"`
  (the following Monday) succeeds with no overlap rejection
- A synthetic match with `start_time` = `2026-09-21 02:59:59 UTC` (one second before the next
  week's start) still resolves to the *first* week under the existing
  `m.start_time BETWEEN wk.start_time AND wk.end_time` scoring queries
- A week created with a non-Monday start / non-Sunday end still gets the same `03:00:00` /
  `+1 day 02:59:59` treatment — this is a blanket formula change, not day-of-week-conditional
- Existing already-created weeks (query them directly) are untouched by this change — their
  stored `start_time`/`end_time` don't change until/unless explicitly edited again
- Run `cd backend && python -m pytest tests/ -v` — full suite passes, including
  `test_issue_84_week_management_editing.py`'s overlap-guard and `_derive_week_times`-adjacent
  coverage
