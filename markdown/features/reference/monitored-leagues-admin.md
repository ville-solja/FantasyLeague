# Monitored Leagues Admin Panel

Admin interface for viewing and managing which OpenDota leagues the app polls for match data, with a purge path for rolling back an accidental ingest.

---

## Concept

League IDs to auto-ingest are seeded from the `AUTO_INGEST_LEAGUES` environment variable on startup, but the live set is stored in the `leagues` table (`is_monitored` column). The background poll loop reads monitored leagues from the database each cycle, so changes take effect without a restart.

## Endpoints

### `GET /admin/leagues`
Returns all leagues in the database. Response fields: `id`, `name`, `is_monitored`, `match_count`. Requires admin session.

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

## Configuration

| Variable | Default | Description |
|---|---|---|
| `AUTO_INGEST_LEAGUES` | `19368,19369` | Comma-separated league IDs seeded as monitored on startup |

---

## Startup behaviour

On startup, `_seed_monitored_leagues(league_ids)` upserts each ID from `AUTO_INGEST_LEAGUES` into the `leagues` table with `is_monitored=True`. The background poll thread (`_ingest_poll_loop`) then queries `leagues WHERE is_monitored=True` each cycle, so adding or removing leagues via the admin panel takes effect at the next poll interval without a restart.
