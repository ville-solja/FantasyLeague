# Admin Week Management

Admin CRUD over season week records: view all weeks, create custom-timed weeks, adjust
the end time (lock deadline) of unlocked weeks, and delete unused unlocked weeks.

---

## Overview

Weeks are normally auto-generated from the `SEASON_LOCK_START` anchor with fixed
Sunday 23:59:59 lock times. This feature lets admins override that for irregular
tournament schedules — e.g. setting a finals week that locks on Friday at 14:00.

Locked weeks are read-only: they cannot be edited or deleted. Unlocked weeks with
no roster snapshots can be freely managed.

---

## Endpoints

### `GET /admin/weeks` Returns all weeks ordered by start time. Each row includes `roster_count` — the number
of weekly roster entry snapshots taken for that week.

### `POST /admin/weeks` Body: `{ label: str, start_time: int, end_time: int }`. Admin only. Creates a new
unlocked week. Validates `end_time > start_time`.

### `PATCH /admin/weeks/{id}` Body: `{ label?, start_time?, end_time? }`. Admin only. Updates any subset of fields
on an unlocked week. Returns 409 if the week is locked. Validates that the resulting
`end_time > start_time`.

### `DELETE /admin/weeks/{id}` Admin only. Deletes an unlocked week with zero roster entries. Returns 409 if locked or
has roster snapshots. Returns 404 if not found.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
