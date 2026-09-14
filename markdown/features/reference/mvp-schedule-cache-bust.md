# MVP Schedule Cache Bust

Fixes a stale-schedule bug: setting a match's MVP (by an admin or via the Twitch extension)
didn't invalidate the Schedule tab's cached response, so the new MVP could take up to an hour
to appear.

*(see `markdown/plans/plan-issue-113-mvp-schedule-cache-bust.md`, resolves GitHub issue #113)*

---

## Why

`GET /schedule` caches its full response in-process for `CACHE_TTL` (3600 seconds —
`backend/schedule.py`), including each resolved series' per-game MVP
(`schedule.py::_build_games`, reading `PlayerMatchStats.is_mvp`). Both MVP-setting endpoints —
`POST /admin/matches/{match_id}/mvp` and `POST /twitch/mvp` — correctly update that field via
the shared `_apply_mvp_bonus` helper, so the underlying data is right immediately. Neither
endpoint called `schedule.bust_cache()` afterward, unlike `POST /schedule/refresh` and the
ingest pipeline, which already do — so the Schedule tab kept serving the pre-MVP cached response
until the TTL naturally expired.

## Behaviour

Both MVP-setting endpoints call `schedule.bust_cache()` right after their `db.commit()`, so the
next `GET /schedule` request recomputes fresh rather than waiting out the cache:

- `backend/routers/admin_matches.py::admin_set_mvp` — right after `db.commit()`, before
  returning the response body
- `backend/twitch.py::set_mvp` (`POST /twitch/mvp`) — right after `db.commit()`, before the
  PubSub broadcast and chat message are sent

Calling it when the cache is already empty/expired is a no-op (it's a plain dict clear:
`_cache["data"] = None; _cache["fetched_at"] = None`), matching the existing
`POST /schedule/refresh` behaviour. A failed MVP-set request (e.g. unknown `player_id`, which
raises `HTTPException(404)` before `db.commit()` is reached) never calls `bust_cache()`, so a
still-warm cache is left untouched.

Only cache invalidation was added — MVP storage (`TwitchMVP` upsert), the fantasy-score MVP
bonus (`_apply_mvp_bonus`), and the Twitch token-drop logic are unaffected.

See `backend/schedule.py` for the cache itself (`_cache`, `CACHE_TTL = 3600`) and its other
existing callers (`POST /schedule/refresh`, the ingest pipeline).
