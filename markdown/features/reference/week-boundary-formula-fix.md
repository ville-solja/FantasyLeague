# Week Boundary Formula Fix

A correction to how `backend/routers/admin_weeks.py::_derive_week_times` converts a week's
date-only `start_date`/`end_date` input into stored timestamps, so a normal Monday-start,
Sunday-end week never collides with the next one by default.

*(see `markdown/plans/plan-issue-111-week-boundary-formula.md`, resolves GitHub issue #111)*

---

## Why

`reference/admin-week-management.md`'s overlap guard (from
`plan-issue-84-week-management-editing.md`) correctly *rejects* a week whose derived range
overlaps another — but the date-only formula itself, before this fix, still *produced* an
overlapping range for the standard weekly cadence: `start_time` was midnight on the chosen
start date, while the previous week's `end_time` (the day after its own end date, plus a
3-hour grace period) landed 3 hours into that same calendar day. An admin picking a normal
"next Monday" start would hit the guard's rejection and have to work around it with a raw
timestamp — observed directly on a real Week 3 → Week 4 boundary.

## Behaviour

`_derive_week_times` (`backend/routers/admin_weeks.py`) applies the same 3-hour grace offset to
*both* ends instead of only the end:

- `start_time` = `start_date` at `03:00:00 UTC` (was `00:00:00 UTC`)
- `end_time` = `(end_date + 1 day)` at `02:59:59 UTC` (was `03:00:00 UTC`)

For a normal Monday-start/Sunday-end week immediately followed by another Monday-start week,
this makes the first week's `end_time` (next Monday `02:59:59 UTC`) exactly one second before
the second week's `start_time` (that Monday `03:00:00 UTC`) — contiguous, no gap, no overlap,
with no manual workaround needed. The grace-period intent (a match starting late on the last day
and running past midnight still counts) is preserved on both weeks' boundaries, not just one.
The change is a blanket formula change, not conditional on which weekday is selected — a
non-Monday start / non-Sunday end still gets the same `03:00:00` / `+1 day 02:59:59` treatment.

Only affects newly created/edited weeks going forward — weeks already created under the old
formula (including any already locked) keep their existing stored values, since no migration is
run against already-stored rows.

`create_week`/`edit_week` (`POST /admin/weeks`, `PATCH /admin/weeks/{id}`) consume whichever
`start_time`/`end_time` this function returns unchanged, and the existing `_check_week_overlap`
guard still rejects genuinely overlapping (non-contiguous) ranges exactly as before — this fix
only changes what a routine Monday–Sunday selection produces, not the overlap check itself. The
frontend's reverse date-display conversion in `frontend/app-admin-weeks.js`
(`_utcDateStr(w.start_time)` and `_utcDateStr(w.end_time - 24 * 3600)`) needed no change: neither
`03:00:00` nor `02:59:59` crosses a UTC midnight boundary relative to the date it belongs to, so
both still recover the calendar date the admin originally picked.

See `reference/admin-week-management.md` for the full Week Management feature this formula is
part of.
