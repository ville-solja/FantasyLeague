# Season Lifecycle Management

Admin-driven flow for ending a season and starting the next one: archive final standings,
reset per-season data, and create the new season's weeks manually — no env edits or redeploys
between seasons.

---

## Lifecycle Flow

```
Season running
    ↓  admin: POST /admin/season/end        (archive standings)
Standings snapshotted to season_archive
    ↓  admin: POST /admin/season/reset      (clean slate; users retained)
Empty season state
    ↓  admin: add monitored league, create weeks (date-only forms)
Next season running
```

Week auto-generation is removed — weeks are created manually in the Week Management tab.
The background maintenance loop still auto-locks weeks whose start time has passed.

## Endpoints

### `POST /admin/season/end` *(planned)*
Body: `{"season_label": "Season 15"}`. Snapshots the current season leaderboard
(username, points, rank; testers excluded) into `season_archive`. 409 on duplicate label.
Logged as `admin_season_archived`.

### `POST /admin/season/reset` *(planned)*
Body: `{"force": false}`. Deletes matches, stats, bans, weeks, roster entries, Twitch MVP and
token drop rows. Deactivates all cards, resets token balances to `INITIAL_TOKENS`, unmonitors
all leagues. Retains users, tags, audit logs, and archives. 409 if locked weeks exist without
a newer archive unless `force=true`. Logged as `admin_season_reset`.

### `GET /leaderboard/seasons` *(planned)*
Lists archived seasons: `[{id, season_label, archived_at, user_count}]`.

### `GET /leaderboard/seasons/{season_id}` *(planned)*
Returns archived standings for one season: `[{username, points, rank}]`.

### `GET /profile/{user_id}` *(extended, planned)*
Response gains `past_seasons`: `[{season_label, points, rank}]`.

### `POST /admin/weeks` and `PATCH /admin/weeks/{week_id}` *(extended, planned)*
Accept `start_date` / `end_date` (ISO dates). Derivation: `start_time` = start date
00:00:00 UTC; `end_time` = 03:00:00 UTC on the day **after** the end date, so matches
running past midnight still count toward the week.

## Database

| Table | Purpose |
|---|---|
| `season_archive` | One row per user per archived season: label, user_id, username (denormalised), points, rank, archived_at. Unique on (season_label, user_id). |

## Retired Configuration

| Variable | Replacement |
|---|---|
| `SEASON_LOCK_START` | Manual week creation (Week Management tab) |
| `SEASON_END` | No auto-generation — nothing to stop |
| `AUTO_INGEST_LEAGUES` | Monitored leagues admin (`/admin/leagues/*`) |

Deployments that still set these vars start cleanly; the values are ignored.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
