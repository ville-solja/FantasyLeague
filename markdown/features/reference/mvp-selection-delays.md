# MVP Selection Delays

Makes a live match show up in the Twitch MVP picker within about a minute of the game starting, and shows admins where any delay comes from. It changes the live source used by [Early MVP Selection](early-mvp-selection.md). Resolves issue #161.

---

## Why matches were late

1. **OpenDota's `/live` doesn't list Kanaliiga games.** It mirrors Steam's top-live-games list (high-MMR, pro and well-watched games), so amateur-league games were generally missing. They appeared only after ingest, often an hour later.
2. **The live check waited on the ingest cycle,** which also runs enrichment, parse retries and the Toornament sync, all sharing the 55-per-minute OpenDota limit, with backoff sleeps.
3. **Slow polling outside fantasy weeks** (15 minutes).

## How it works

### Steam is the live source
`backend/steam_live.py::get_live_league_games(league_ids)` calls `IDOTA2Match_570/GetLiveLeagueGames/v1/` with `STEAM_API_KEY`:
- one request per check, with no league filter (the list is filtered locally to the monitored leagues), a 10 s timeout, no retries and no backoff sleeps;
- each game is normalised to the entry keys `ingest.store_live_matches()` already reads (`team_id_radiant`, `team_name_radiant`, `players[].team` …), so `live_matches`, `GET /twitch/matches/current`, `POST /twitch/mvp` and the Schedule tab's live state are unchanged. The field mapping is in [Early MVP Selection](early-mvp-selection.md#steam-getliveleaguegames-fields-used);
- casters and spectators (`players[].team` 2 or more) and players without an `account_id` are skipped;
- it returns `None` on any failure (timeout, connection error, non-200 status, invalid JSON, unexpected shape) and never raises.

The key is sent only as the `key` query parameter. Failures are logged with the status code or the exception class name only, never the exception text, because that can contain the request URL. The key is never stored or returned. `main.py` also pins the `urllib3` logger at INFO, because its DEBUG line logs the full request URL, key included, whenever `DEBUG=true` puts the root logger at DEBUG (this covers `OPENDOTA_API_KEY` too).

OpenDota's `/live` and `ingest.get_live_matches()` are gone. OpenDota remains the source for finished-match stats.

### Live thread
`main._live_poll_loop` runs `_live_poll_once()` every `LIVE_POLL_INTERVAL` seconds, apart from the ingest loop, so ingest, enrichment, parse retries, the Toornament sync and their backoffs never delay it. Each tick:
1. returns at once when no league is monitored or `STEAM_API_KEY` is unset;
2. calls `get_live_league_games(monitored)`; on `None` it returns, leaving `live_matches` as it is (no row is marked ended);
3. otherwise calls `store_live_matches(games, monitored)` and sets `steam_live.live_checked_at` to now.

An exception is logged ("Live poll failed") and the next tick runs as usual.

The thread starts with the others unless `DEMO_MODE=true` or `STEAM_API_KEY` is unset. Without a key a warning is logged once at start-up: matches then reach the MVP picker only after ingest.

### Ingest loop
`_ingest_poll_loop` makes no live calls. A monitored league counts as live when it has a `live_matches` row with `ended_at IS NULL` seen in the last 15 minutes (`main._live_league_ids`). That set still skips enrichment and selects `INGEST_LIVE_MATCH_POLL_INTERVAL` (see [OpenDota Query Prioritization](opendota-query-prioritization.md)). A failure reading it is logged and counts as nothing live.

### Timings
New table `match_timings` (model `MatchTiming`, created by `create_all`, no migration), one row per match:

| Column | Set by |
|---|---|
| `match_id` | Primary key (no foreign key: a match is seen live before its `matches` row exists) |
| `live_first_seen_at` | `store_live_matches()`, on first sight |
| `ingested_at` | `ingest_match()`, when the stats are written |
| `mvp_confirmed_at` | `POST /twitch/mvp` |
| `mvp_provisional` | `POST /twitch/mvp`: `true` when the MVP was confirmed before ingest |

`ingest.record_timing(db, match_id, **fields)` inserts the row if missing (`ON CONFLICT DO NOTHING`) and sets each field only while it is `NULL`, so every value is the first one: re-selecting an MVP doesn't move `mvp_confirmed_at`. The caller commits. The admin MVP endpoint doesn't record timings.

### Freshness in the MVP picker
`twitch-extension/live_config.js`, series step (step 1):
- a line above the list: "Live games checked N s ago" (under a minute) or "N min ago";
- when `live_checked_at` is `null` or more than 5 minutes old, or `live_source_configured` is `false`, the line reads "Live games not checked recently — your match will appear once its stats are in" in amber (`#d29922`);
- a **Refresh** button calls `loadSeries()` again. It is disabled while a request is in flight and enabled again whether it succeeds or fails; on failure the list shows the existing "Failed to load matches." state and the line is cleared.

The age is measured against the caster's clock, so a skewed clock shifts it.

### Admin Matches table
"Live seen", "Stats in" and "MVP picked" columns after Start Time show each timing as minutes after the match's `start_time` ("+2 min", "−1 min" when before the start), with the exact time in the cell's `title`. Unknown values show "—"; a dash under Live seen means live detection missed the match.

## Endpoints

### `GET /twitch/matches/current`
Adds two top-level fields next to `series`, also when `series` is empty:
- `live_checked_at`: Unix time of the last successful live check, or `null` if there hasn't been one since start-up;
- `live_source_configured`: whether `STEAM_API_KEY` is set.

### `GET /admin/matches`
Each match adds `live_first_seen_at`, `ingested_at` and `mvp_confirmed_at` (Unix times, or `null`).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `STEAM_API_KEY` | *(empty)* | Steam Web API key; required for live-game detection. Steam sign-in (#150) needs no Steam Web API key |
| `LIVE_POLL_INTERVAL` | `60` | Seconds between live-game checks while a league is monitored |

## Manual follow-up

- **Check the Steam response shape (plan Step 1).** The parser follows Steam's documented `GetLiveLeagueGames` shape. `backend/tests/fixtures/steam_live_league_games.json` is a stand-in (it has a top-level `_stand_in` key), not a real capture. During a live Kanaliiga game, run `curl -s "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/?key=$STEAM_API_KEY&league_id=20162"`, confirm the field names, the `players[].team` values and whether `league_id` filters on the server, then replace the fixture with a trimmed copy (ids kept, key removed, `_stand_in` dropped). If the game is missing while live, report it on issue #161.
- **Match night, with `STEAM_API_KEY` set:** the casted game appears in the MVP picker within about a minute and the picker shows "Live games checked … ago"; in the admin Matches table "Live seen" is a few minutes after the start and "Stats in" later.
- **Without a key:** the start-up warning is logged, the picker shows the warning line, and matches still appear after ingest.
- The extension change ships only with a new extension version uploaded to Twitch.

## Tests

`backend/tests/test_issue_161_mvp_selection_delays.py`.
