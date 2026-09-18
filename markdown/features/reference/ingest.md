# Data Ingest Pipeline

The ingest pipeline is responsible for pulling Dota 2 match data from external sources and populating the local database. It runs automatically in the background and can also be triggered manually by an admin.

## Pipeline Stages

### 1. Match Ingest (OpenDota)

Source: `GET https://api.opendota.com/api/leagues/{league_id}/matchIds`

For each match ID not already in the database:
- Fetches full match data via `GET /api/matches/{match_id}`
- Stores team IDs, match result (`radiant_win`), and start timestamp
- Stores per-player stats: kills, deaths, GPM, observer wards, last hits, denies, towers destroyed, Roshan kills, teamfight participation, camps stacked, rune pickups, first blood, stuns
- Calculates and stores fantasy points for each player using current scoring weights
- Seeds the player's display name (`personaname`) into the `players` table if the player is new or had no name yet
- Matches shorter than 15 minutes (900 seconds) are skipped as invalid

Note: the `assists`, `sen_placed`, and `tower_damage` columns are retained in the database for historical records but are no longer included in fantasy scoring.

Rate limit handling: 429 responses trigger exponential backoff before retrying. Server errors (5xx) are retried up to 3 times.

### 2. Name & Avatar Backfill (OpenDota)

After ingest, any player who is still missing a display name or avatar is enriched via `GET /api/players/{account_id}`. Players are processed in batches of 50 until all have names. Enrichment runs up to 20 rounds per cycle to avoid blocking indefinitely.

Note: this stage handles only name/avatar fields. Hero stats, ban correlations, and AI bios are populated by the separate **Profile Enrichment** background loop — see `reference/player-profile-enrichment.md`.

### 3. Dotabuff Team Logo Scrape

Team logos are downloaded from Dotabuff league overview pages and stored as PNG files under `assets/dotabuff_league_logos/`. Only missing logos are downloaded — existing files are not re-fetched unless manually deleted.

Configure which Dotabuff pages to scrape via `DOTABUFF_LEAGUE_LOGO_PAGES` (comma-separated URLs, defaults to the two Kanaliiga division pages).

## Automatic Polling

The ingest pipeline runs in a background daemon thread on a configurable, three-tier interval:

- **Default interval:** 900 seconds (15 minutes) — `INGEST_POLL_INTERVAL`
- **Active-week interval:** 120 seconds (2 minutes) — `INGEST_LIVE_POLL_INTERVAL`, used whenever an unlocked week's match window is currently open
- **Live-match interval:** 30 seconds — `INGEST_LIVE_MATCH_POLL_INTERVAL`, used whenever any monitored league has a match currently in progress (see below); takes priority over the active-week interval since it's a stronger, more specific signal
- **Leagues polled:** whichever leagues are marked `is_monitored=true`, managed at runtime via the admin League Management panel (see `reference/monitored-leagues-admin.md`) — no env var or restart needed

Each cycle runs all three ingest stages in sequence, then triggers a toornament sync. The first cycle runs immediately on startup — there is no initial delay.

### Live-match enrichment gate

See `reference/opendota-query-prioritization.md` for the full mechanism. Each poll cycle, if any
monitored league has a currently-live match, `_ingest_poll_loop` makes one `GET /live` call
(`ingest.py::get_live_match_league_ids()`) to find out. Match ingestion always runs regardless,
but low-priority player name/avatar enrichment (`run_enrichment()`) is skipped for that cycle so
it doesn't compete with match ingestion for OpenDota's shared rate limit exactly when a
broadcaster is waiting on a finished match. The check itself is skipped entirely when no league
is currently monitored, so it costs nothing outside of an active broadcast. Enrichment resumes,
and the interval falls back to the active-week/default tiers, on the first cycle where no
monitored league is live. A failed or unreachable `GET /live` call degrades to "nothing live"
rather than crashing the poll loop.

## Manual Ingest

Admins can trigger an immediate ingest via:

```
POST /ingest/league/{league_id}
```

This starts the three pipeline stages (in order: Match Ingest → Dotabuff Team Logo Scrape →
Name & Avatar Backfill) for the specified league in a background thread and returns immediately
(`{"status": "started", "league_id": ...}`) — it does not trigger a toornament sync, unlike the
background poll cycle. `ingest.INGEST_LOCK` is shared with the poll loop, so a manual trigger and
the automatic cycle can never run concurrently; calling this endpoint while either is already
running returns 409 instead of queuing.

## Data Sources

| Source | What it provides |
|---|---|
| OpenDota API | Match IDs, match results, per-player stats, player names and avatars |
| Dotabuff | Team logo images (scraped from league overview pages) |

## OpenDota API Key

Without an API key, requests are rate-limited to ~60 requests/minute. With `OPENDOTA_API_KEY` set, the limit increases significantly. Set the key in the environment to avoid 429 delays during large initial ingests.

## What Gets Stored

| Table | Content |
|---|---|
| `leagues` | League ID and name |
| `matches` | Match ID, team IDs, result, start timestamp, league ID |
| `players` | OpenDota account ID, display name, avatar URL |
| `teams` | OpenDota team ID, team name |
| `player_match_stats` | Per-player per-match stats, calculated fantasy points, and `hero_id` (the hero picked by the player in that match) |
| `match_bans` | Hero bans extracted from `picks_bans` in the match response — used by profile enrichment ban correlation analysis |
