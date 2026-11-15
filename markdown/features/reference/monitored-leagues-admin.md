# Monitored Leagues Admin Panel

Admin interface for viewing and managing which OpenDota leagues the app polls for match data, with a purge path for rolling back an accidental ingest.

---

## Concept

The set of leagues to ingest is stored entirely in the `leagues` table (`is_monitored`
column) and managed at runtime via this admin panel — there is no environment-variable
bootstrap. The background poll loop reads monitored leagues from the database each cycle,
so adding or removing a league takes effect at the next poll interval without a restart.
A fresh instance starts with zero monitored leagues until an admin adds one.

## Endpoints

### `GET /admin/leagues`
Returns all leagues in the database. Response fields: `id`, `name`, `is_monitored`, `match_count`. Requires admin session.

### `GET /admin/opendota-status`
Admin only. `{"opendota": {...}, "leagues": [...]}`:
- `opendota`: `last_ok_at`, `last_problem` (`at`, `kind`: `rate_limited` / `server_error` / `network` / `client_error` / `gave_up`, `label`, `status`), `problems_24h` (count per kind), `rate_limited_now` (a 429 in the last 15 minutes with no success since), `failing_now` (any problem in the last 15 minutes with no success since), `api_key_set` (a flag only, never the key). A 404 is an answer and is not counted.
- `leagues`: each monitored league's last ingest check: `listed_at`, `listed`, `list_failed_at`, and `not_stored` (`[{match_id, reason}]`, reasons `fetch_failed`, `too_short`, `error`, or `not_stored` for a listed game the pass didn't try or store, shown as "not stored yet").

Both come from memory (`opendota_client`, `ingest.league_statuses()`), so they are empty after a restart until the next ingest pass. The League Management panel shows them: a line on OpenDota's health above the table (with a warning while it is rate-limiting or failing, and whether an API key is set), and **Last check** and **Not stored** columns, each game linking to OpenDota with its reason.

### `POST /admin/leagues/{league_id}/monitor`
Marks a league as monitored. Creates a placeholder league row (`name="(pending ingest)"`) if the ID is not yet known. Returns `{"status": "ok", "league_id": N}`. Returns 409 if already monitored.

### `DELETE /admin/leagues/{league_id}/monitor`
Unsets the monitored flag. Does not delete any match data. Returns `{"status": "ok", "league_id": N}`. Returns 404 if not currently monitored.

### `DELETE /admin/leagues/{league_id}/data`
Purges all `player_match_stats`, `match_bans`, and `matches` rows for the league. Sets `is_monitored = False`. Returns `{"status": "ok", "league_id": N, "deleted_matches": N, "deleted_stats": N, "deleted_bans": N, "note": "..."}`. Does not delete player records.

## Schema change

| Column | Table | Type | Default |
|---|---|---|---|
| `is_monitored` | `leagues` | `INTEGER NOT NULL` | `0` |

Migration: `_m017_leagues_is_monitored` in `backend/migrate.py`.

---

## Poll behaviour

The background poll thread (`_ingest_poll_loop`) queries `leagues WHERE is_monitored=True`
each cycle, so adding or removing leagues via this admin panel takes effect at the next poll
interval. `POST /admin/season/reset` (see `reference/season-lifecycle.md`) unmonitors every
league as part of clearing per-season state — add the new season's league(s) here afterward.
