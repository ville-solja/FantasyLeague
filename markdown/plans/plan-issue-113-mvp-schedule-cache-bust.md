# Plan: MVP Schedule Cache Bust

## Context
Issue #113 reports a "huge delay" before a newly-set match MVP shows up on the Schedule tab —
both the admin-set and Twitch-streamer-set paths are affected equally, while older matches
display their MVP correctly. Traced to the exact cause: `GET /schedule`'s response (including
each resolved series' per-game MVP, built by `schedule.py::_build_games` reading
`PlayerMatchStats.is_mvp`) is cached in-process for up to `CACHE_TTL` (3600 seconds — see
`schedule.py`). Both MVP-setting endpoints — `POST /admin/matches/{match_id}/mvp`
(`backend/routers/admin_matches.py`) and `POST /twitch/mvp` (`backend/twitch.py`) — correctly
update `PlayerMatchStats.is_mvp` via the shared `_apply_mvp_bonus` helper, so the underlying
data is right immediately. Neither endpoint calls `schedule.bust_cache()` afterward, though —
unlike `POST /schedule/refresh` and the ingest pipeline, which already do — so the Schedule tab
keeps serving the pre-MVP cached response for up to a full hour after the MVP was actually set,
exactly matching the reported "huge delay" and explaining why only older matches (whose cache
entry has since naturally expired) show correctly.

*Resolves GitHub issue #113.*

## User Stories

### MVP Selection Immediately Reflects on the Schedule Tab
**User story**
As a user, I want a match's MVP to show up on the Schedule tab right after the broadcaster or
an admin sets it, so I don't have to wait up to an hour for the cached schedule to catch up.

**Acceptance criteria**
- `POST /admin/matches/{match_id}/mvp` busts the schedule cache after successfully setting the
  MVP, so the next `GET /schedule` call recomputes fresh data instead of serving a stale cached
  response
- `POST /twitch/mvp` (the streamer-facing MVP flow) does the same
- A `GET /schedule` call made immediately after either endpoint succeeds shows the new MVP on
  the corresponding game row, with no waiting period
- Setting/changing the MVP for a match that isn't part of any currently-cached schedule response
  (e.g. the cache is already stale/unset) doesn't error — busting an already-clear cache is a
  no-op, matching `bust_cache()`'s existing behaviour used elsewhere (`POST /schedule/refresh`)
- No change to how the MVP itself is selected, stored, or scored — this only fixes how promptly
  the Schedule tab's read-side cache reflects it

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/admin_matches.py` | Import `bust_cache` from `schedule`; call it in `admin_set_mvp` after the MVP is set/updated and committed |
| `backend/twitch.py` | Import `bust_cache` from `schedule`; call it in the `POST /mvp` handler after the MVP is set/updated and committed |
| `markdown/features/core/weekly-summary.md` or `markdown/features/reference/ingest.md` — n/a; no feature doc currently owns schedule caching behaviour on its own, so document this in-line where the endpoints already are (see Step 2) | — |

### Step 1 — Bust the cache after setting the MVP
In `backend/routers/admin_matches.py`, add the import and call `bust_cache()` right after
`db.commit()` in `admin_set_mvp` (mirroring the existing pattern in
`backend/routers/admin_ingest.py::schedule_refresh`):
```python
from schedule import bust_cache
...
    db.commit()
    bust_cache()
    return {...}
```
In `backend/twitch.py`, add the same import and call `bust_cache()` after the `POST /mvp`
handler's commit (after `_apply_mvp_bonus` and the token-drop/audit-log logic, once the
transaction is committed), so the next `GET /schedule` request recomputes with the new MVP
already in place.

### Step 2 — Documentation
Add a short note to `markdown/features/reference/admin-router-organization.md` or wherever
`schedule.py`'s cache is already documented (check `reference/ingest.md`/`core/weekly-summary.md`
for the existing cache-bust callouts and follow the same pattern) stating that both MVP-setting
endpoints now bust the schedule cache, alongside ingest and manual refresh.

## Verification
- Set a match's MVP via `POST /admin/matches/{match_id}/mvp`, then immediately call
  `GET /schedule` — the new MVP appears on that match's game row without needing
  `POST /schedule/refresh` or waiting for the cache TTL
- Same check via `POST /twitch/mvp` (the streamer flow)
- Confirm `PlayerMatchStats.is_mvp` and fantasy point adjustments are unchanged — this plan only
  touches cache invalidation, not scoring
- Confirm calling either MVP endpoint when the schedule cache is already empty/expired doesn't
  raise — `bust_cache()` is a plain dict-clear, safe to call unconditionally
- Run `cd backend && python -m pytest tests/ -v` — full suite passes
