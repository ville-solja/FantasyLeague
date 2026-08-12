# Toornament Integration

The Kana Cards app automatically synchronises series results to [toornament.com](https://toornament.com), where the Kanaliiga tournament bracket is managed. This eliminates manual result entry by admins and keeps the bracket up to date shortly after each series concludes.

## Overview

```
OpenDota API
    ↓  (match IDs + per-player stats)
Kana Cards DB  ←──────────────────────────┐
    ↓  (resolve_series_result)               │
 series score (e.g. 2–1)                     │ poll every 15 min (2 min if a week is active)
    ↓                                        │
toornament.com  ←── PATCH /matches/{id}  ────┘
```

The integration is one-directional: Kana Cards pushes results to toornament; it never reads bracket state back.

## How a Result Gets Pushed

1. **Match ingestion** — The background ingest loop polls OpenDota every `INGEST_POLL_INTERVAL` seconds (default: 15 min) for new match IDs in the configured leagues — or every `INGEST_LIVE_POLL_INTERVAL` seconds (default: 2 min) while any week is currently active, so live-series results reach toornament faster. This is the same loop that runs the toornament sync described below, so the speedup applies to both. New matches are stored in the `matches` table.

2. **Series resolution** — For each match entry in toornament, the app looks up both participant names (e.g. `"Team A"` and `"Team B"`) and resolves them to team IDs in the local DB using fuzzy name normalisation (lowercase, parentheticals stripped, substring fallback). It then counts wins across all stored matches between those two teams.

3. **Idempotency check** — Before issuing a PATCH, the app compares the computed score against what toornament already shows. If they are identical, the match is skipped with no network call.

4. **Result push** — If the score differs, a `PATCH /tournaments/{id}/matches/{match_id}` request is sent with the updated `opponents` array, each entry carrying a `score` (number of maps won) and a `result` field (`"win"`, `"loss"`, or `"draw"`).

5. **Sync log** — A successful push is recorded in the `toornament_sync_log` table for audit purposes.

## Name Mapping

Toornament stores participant names as free-text strings entered by tournament organisers. The Kana Cards DB stores team names as extracted from OpenDota match data. The mapping relies on `norm_team_name()` in `schedule.py`:

- Converts to lowercase
- Strips parenthetical suffixes (e.g. `"Meta(no)core"` → `"metacore"`)
- Collapses whitespace

Exact match is tried first; if that fails, bidirectional substring containment is used as a fallback. If neither side can be matched to a DB team, the toornament match is skipped and a warning is logged.

## Trigger Points

| Trigger | Behaviour |
|---|---|
| Background poll (every 15 min by default, 2 min while a week is active) | Ingest new OpenDota matches, then run toornament sync |
| `POST /admin/sync-toornament` | Immediately run a toornament sync, returns `{pushed, skipped, errors}` |

The manual endpoint is useful immediately after a series finishes, or to verify the integration is working correctly.

## Dry Run

`sync_toornament_results(db, dry_run=True)` logs what would be pushed without making any PATCH requests. This is available for debugging from the Python shell when validating name mappings for a new season.

## Configuration

All four variables must be set for the integration to activate. If any is missing, the sync loop skips silently without affecting ingest or any other feature.

| Environment variable | Description |
|---|---|
| `TOORNAMENT_CLIENT_ID` | OAuth2 client ID from the toornament developer portal |
| `TOORNAMENT_CLIENT_SECRET` | OAuth2 client secret |
| `TOORNAMENT_API_KEY` | `X-Api-Key` header value (separate from OAuth2) |
| `TOORNAMENT_TOURNAMENT_ID` | UUID of the Kanaliiga tournament on toornament.com |
| `INGEST_POLL_INTERVAL` | Seconds between poll cycles when no week is active (default: `900`) |
| `INGEST_LIVE_POLL_INTERVAL` | Seconds between poll cycles while a week is active (default: `120`) — see `reference/twitch-mvp-series-window.md` |

## Audit Trail

Each successful push writes or updates a row in `toornament_sync_log`:

| Column | Content |
|---|---|
| `toornament_match_id` | The toornament match UUID (unique) |
| `team1_name` / `team2_name` | Names as they appear in toornament |
| `team1_score` / `team2_score` | Maps won at time of last push |
| `pushed_at` | Unix timestamp of the last successful push |

## Limitations

- **All-time win counts (Toornament only)**: `resolve_series_result` called by the Toornament sync has no date filter — it aggregates all stored matches between two teams across the season. If the same two teams meet in group stage and playoffs, both series are summed. The schedule view uses a separate call with a ±4-day window around the scheduled date (see schedule view note below).
- **One-directional**: bracket advancement, seeding, and group assignments in toornament are not read back into Kana Cards.
- **Toornament match scope**: only matches with `status` of `"running"` or `"completed"` and exactly two mapped participants are processed. Byes and TBD slots are skipped automatically.
