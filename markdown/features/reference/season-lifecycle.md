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
    ↓  admin: POST /admin/season/reset      (clean slate; users retained; players/teams cleared)
Empty season state
    ↓  admin: add monitored league, add players (Player Management tab), create weeks (date-only forms)
Next season running
```

Week auto-generation is removed — weeks are created manually in the Week Management tab.
The background maintenance loop still auto-locks weeks whose start time has passed.

## Endpoints

### `POST /admin/season/end`
Body: `{"season_label": "Season 15"}`. Snapshots the current season leaderboard
(username, points, rank; testers excluded) into `season_archive`, computed via the shared
`compute_season_standings()` helper also used by `GET /leaderboard/season`. 409 if the label
is already archived. Logged as `admin_season_archived`.

### `POST /admin/season/reset`
Body: `{"force": false}`. Before any deletes, takes an automatic online backup of the live
SQLite database (`backup_sqlite_db()` in `backend/database.py`, using SQLite's online backup
API so it's safe against a WAL-mode connection). If the backup fails, the reset aborts with a
500 and **no deletes are performed** — there's no code path that wipes season data without a
fresh backup existing first. Deletes all rows from `player_match_stats`, `match_bans`,
`matches`, `weekly_roster_entries`, `weeks`, `twitch_mvp`, `twitch_token_drops`, `players`,
`teams`, `card_modifiers`, and `cards`. Resets every user's `tokens` to `INITIAL_TOKENS` and
unmonitors all leagues. Retains users, tags, audit logs, and `season_archive` rows. Returns 409
if any locked week exists with no `season_archive` row archived at or after that week's start
time (unless `force=true`) — the guard that makes skipping End Season difficult. Response
includes `{"status", "initial_tokens", "counts": {...}, "backup_path"}` with a per-table
deleted-row count and the path of the pre-reset backup file. Logged as `admin_season_reset`,
with the backup path prefixed to the counts in the detail string.

**Players, Teams, and Cards are wiped entirely — not just deactivated.** The `players` table
doubles as the admin-curated Player Pool (see `reference/admin-player-pool.md`), so reset
also empties the draft pool: the admin repopulates it via Player Management once the new
season's roster is known. Rosters fluctuate season to season, so retaining players/cards
tied to a roster that no longer exists is a real risk, not just clutter. Cards are deleted
(not soft-deactivated) for the same reason — a genuine clean slate means every user starts
the new season by drawing a fresh collection with their reset tokens, rather than keeping
cards for players who may no longer play. This is a deliberate trade-off, most relevant when
the same instance is reused for a different league.

### `GET /leaderboard/seasons`
Lists archived seasons, one row per distinct `season_label`, newest first:
`[{id, season_label, archived_at, user_count}]`. `id` is the lowest `season_archive.id` in
that label's group and is the identifier `GET /leaderboard/seasons/{season_id}` expects.

### `GET /leaderboard/seasons/{season_id}`
Returns the archived standings for the season containing that `season_archive` row:
`{id, season_label, archived_at, standings: [{user_id, username, points, rank}]}`. 404 if
`season_id` does not match any archived row.

### `GET /profile/{user_id}` (extended)
Response gains `past_seasons`: `[{season_label, points, rank}]`, one entry per archived
season the user appears in, most recent first.

### `POST /admin/weeks` and `PATCH /admin/weeks/{week_id}` (extended)
Accept `start_date` / `end_date` (ISO `YYYY-MM-DD`) alongside the existing `start_time`/
`end_time` integer fields (still accepted for backward compatibility; date fields take
precedence when both are present). Derivation: `start_time` = start date 00:00:00 UTC;
`end_time` = 03:00:00 UTC on the day **after** the end date, so matches running past
midnight still count toward the week. Existing validation (end after start, locked weeks
cannot be edited/deleted) is unchanged.

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

`SCHEDULE_SHEET_URL` remains supported but loses its hardcoded Kanaliiga fallback (default is
now `""`): unset means an empty schedule tab. Instances hosting Kanaliiga must set it
explicitly in `.env`.

## Admin UI

The Settings tab (admin panel) has a "Season Lifecycle" section: a season-label input with
an "End Season (Archive)" button, a "Reset Season…" button that opens a type-to-confirm
modal (must type `RESET`), and a table of previously archived seasons. The Leaderboard tab
shows a "Past Seasons" panel with a season selector once at least one archive exists. The
Profile view shows a "Past Seasons" line per archived season the user appears in
(e.g. "Season 15 — 3rd, 1240.0 pts"). Week Management's create/edit forms use `<input
type="date">` instead of `datetime-local`.
