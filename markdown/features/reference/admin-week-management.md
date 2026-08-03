# Admin Week Management

Admin CRUD over season week records: view all weeks, create weeks with date-only inputs,
edit unlocked weeks inline in the weeks table, and delete unused unlocked weeks. Weeks are
never auto-generated — an admin creates every week explicitly.

---

## Overview

The Week Management tab's create fields, and each unlocked row's inline edit fields, take a
start date and an end date (no time component) via a calendar-picker date input (click/focus
to open, or type a `d.m.yyyy`-style date directly — see
`reference/admin-week-management.md#date-entry` below). The backend derives full timestamps:

- `start_time` = start date, 00:00:00 UTC
- `end_time` = the day **after** the end date, 03:00:00 UTC

The 03:00 UTC buffer means a match starting late on the chosen end date and running past
midnight still counts toward that week — useful for LAN finals or irregular schedules (e.g.
a finals week spanning a single Saturday).

Locked weeks are read-only: they cannot be edited or deleted. Unlocked weeks with
no roster snapshots can be freely managed. *(planned)* Editing happens directly in the weeks
table — each unlocked row exposes editable label/start/end fields, and a single "Save Changes"
button below the table submits every changed row individually, so one row's rejection doesn't
block the others. There is no longer a separate edit form.

### Date entry

Date fields are plain text inputs paired with a small in-page calendar popup (no native
`<input type="date">`, whose display format is browser/locale-dependent). Typed input is parsed
and validated entirely client-side before a request is ever sent — the backend only ever
receives (and only ever requires) strict ISO `YYYY-MM-DD`. An unparseable typed value flags the
field invalid locally rather than reaching the backend's
`"Dates must be ISO format (YYYY-MM-DD)"` error.

### Overlap prevention *(planned)*

A week's `[start_time, end_time)` range may not overlap any other week's range, regardless of
lock status — otherwise a calendar day could belong to two weeks and be double-counted (or
missed) for scoring. Weeks that exactly abut (one's `end_time` equals the other's `start_time`)
are not considered overlapping.

---

## Endpoints

### `GET /admin/weeks`
Returns all weeks ordered by start time. Each row includes `roster_count` — the number
of weekly roster entry snapshots taken for that week.

### `POST /admin/weeks`
Body: `{ label: str, start_date: str, end_date: str }` (ISO `YYYY-MM-DD`). Admin only.
Creates a new unlocked week with timestamps derived per the rule above. The legacy
`start_time`/`end_time` integer fields are still accepted directly if dates are omitted.
Validates the derived `end_time > start_time`. *(planned)* Rejects with 409 if the range
overlaps an existing week, naming the conflicting week's label.

### `PATCH /admin/weeks/{id}`
Body: `{ label?, start_date?, end_date? }` (or legacy `start_time?`/`end_time?`). Admin only.
Updates any subset of fields on an unlocked week. Returns 409 if the week is locked.
Validates that the resulting `end_time > start_time`. *(planned)* Rejects with 409 if the
resulting range overlaps any other week's range.

### `DELETE /admin/weeks/{id}`
Admin only. Deletes an unlocked week with zero roster entries. Returns 409 if locked or
has roster snapshots. Returns 404 if not found.

---

See also `reference/season-lifecycle.md` for the End Season / Season Reset flow that
precedes creating the next season's weeks, and `plan-issue-84-week-management-editing.md`
for the inline-editing and overlap-guard implementation plan.
