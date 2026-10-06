# Plan: MVP Selection Delays

## Context
Casters report that a match they are casting can take upwards of an hour to appear in the Twitch extension's MVP picker. Early MVP selection (#139) was meant to fix this. Every ingest poll calls OpenDota's `/live`, stores monitored-league games in `live_matches`, and `GET /twitch/matches/current` offers them as provisional matches. In practice it isn't reaching casters in time.

**Why it takes an hour:**
1. **OpenDota's `/live` doesn't list Kanaliiga games.** `/live` mirrors Steam's list of top live games: high-MMR, pro and well-watched games. Kanaliiga is an amateur league, so its games are generally missing. Nothing reaches `live_matches`, and the match appears only after OpenDota has processed it and our ingest has picked it up from `/leagues/{id}/matchIds`. That route easily takes an hour.
2. **The live check waits behind everything else.** `_ingest_poll_loop` in `backend/main.py` does all of this in one thread, in order:
   - the live check,
   - `_auto_ingest()`: `ingest_league()` for every league, `run_enrichment()` and `retry_unparsed_matches()`,
   - `_run_toornament_sync()`.

   OpenDota calls share a cap of 55 requests a minute. A parse request costs 10 of them, and failing calls back off for up to about 5 minutes in the same thread. Even with a working source, the next live check can wait many minutes.
3. **Slow polling outside fantasy weeks.** With no active fantasy week and nothing known to be live, the loop sleeps `INGEST_POLL_INTERVAL` (900 s).

**Decision:** Steam's own Web API is the source of truth for live games. `IDOTA2Match_570/GetLiveLeagueGames` lists every live game in a league, with team ids and player account ids. OpenDota's `/live` is dropped as a live source. OpenDota remains the source for finished-match stats (ingest) only.

**The fix:**
1. **Steam as the only live source,** using a new `STEAM_API_KEY`.
2. **Live check in its own thread,** on a short fixed interval, with one attempt and a short timeout, so ingest and enrichment can't hold it up.
3. **Per-match timings for admins,** so the next match night shows whether the fix worked.
4. **A freshness line and a Refresh button** in the MVP picker for casters.

**Assumptions** (flagged for review):
- **`STEAM_API_KEY` is a new env var.** The Steam login (#150) will need a Steam Web API key too and should reuse this one. Without a key, live detection is off: matches reach the MVP picker only after ingest, the panel says so, and a warning is logged once at start-up.
- **The `GetLiveLeagueGames` response shape is verified against a real response before parsing is written** (Step 1), with a copy saved as a test fixture.
  - Expected from Steam's documentation: `result.games[]` with `match_id`, `league_id`, `radiant_team{team_id, team_name}`, `dire_team{…}`, and `players[]{account_id, name, team}`.
  - In `players[].team`, 0 is radiant, 1 is dire, and 2 or more are casters or spectators, who must be skipped.
- **Ids for the check:** the monitored leagues are 20162 (Kanaliiga Season 16) and 20163 (Season 16 Lower) in the current database.
- **Removing OpenDota `/live` changes #139's design.** `get_live_matches()` and its `/live` call go. `store_live_matches()` keeps its contract, because the Steam parser produces the same entry shape, so `live_matches`, `GET /twitch/matches/current`, `POST /twitch/mvp` and the Schedule tab's live state are unchanged.
- **No migration is needed.** `live_matches` keeps its columns, and timings go in a new `match_timings` table created by `create_all`. `live_matches` rows are deleted on ingest, so they can't hold this history.
- **No manual "add this match" fallback for casters.** If Steam doesn't list a game, the match still appears after ingest. The timings will show whether that ever happens.

Resolves GitHub issue #161.

## User Stories

### Live Games Come From Steam
**User story**
As a caster for Kanaliiga, I want the app to detect my live game from Steam's league list, so that early MVP selection works for amateur matches that OpenDota's live list doesn't show.

**Acceptance criteria**
- With `STEAM_API_KEY` set, each live check calls Steam's `IDOTA2Match_570/GetLiveLeagueGames` once, and keeps only games whose `league_id` is monitored.
- Each game is normalised to the entry shape `store_live_matches()` reads:
  - `match_id`, `league_id`,
  - team ids (0 or missing stored as `NULL`), team names (`""` stored as `NULL`),
  - `players` with `account_id`, `name`, and `team` (0 radiant, 1 dire).
- Players with a `team` other than 0 or 1, and players without an `account_id`, are skipped.
- OpenDota's `/live` is no longer called anywhere. `get_live_matches()` is removed, and the ingest loop and its tests no longer use it.
- The Steam key is never logged, stored or returned in a response. Request errors are logged with the HTTP status or exception class only, never the URL.
- Failure path: with `STEAM_API_KEY` unset, no live check runs. A warning is logged once at start-up, and `GET /twitch/matches/current` reports `live_source_configured: false`.

### Live Matches Appear in the MVP Picker Within a Minute
**User story**
As a caster, I want the match I'm casting to appear in the Twitch MVP picker within about a minute of the game starting, so that I can pick the MVP when the game ends instead of an hour later.

**Acceptance criteria**
- Live games are checked by a background thread of their own, `_live_poll_loop`, every `LIVE_POLL_INTERVAL` seconds (default 60) whenever at least one league is monitored and `STEAM_API_KEY` is set. It never waits on ingest, enrichment, parse retries or the Toornament sync.
- Each check makes one Steam request with a timeout of 10 s and no retries or backoff sleeps. A failed check is logged and retried on the next tick.
- `_ingest_poll_loop` makes no live calls. To choose its interval, and whether to skip enrichment, it reads `live_matches`: a game with `ended_at IS NULL` that was seen in the last 15 minutes counts as live.
- In `DEMO_MODE` the live thread doesn't start, as for the ingest thread.
- Failure path: a failed Steam request leaves `live_matches` unchanged. It doesn't mark stored games ended.

### See Where the Delay Comes From
**User story**
As an admin, I want to see for each recent match when it was first seen live, when its stats arrived and when its MVP was picked, so that I can tell whether casters are waiting on live detection, on OpenDota or on something else.

**Acceptance criteria**
- A `match_timings` row per match records:
  - `live_first_seen_at`, set by the live thread on first sight,
  - `ingested_at`, set by `ingest_match()` when stats are written,
  - `mvp_confirmed_at` and `mvp_provisional` (true when the MVP was confirmed before ingest), set by `POST /twitch/mvp`.
  
  Each field is set only while it's empty, so `mvp_confirmed_at` is the first confirmation.
- `GET /admin/matches` includes `live_first_seen_at`, `ingested_at` and `mvp_confirmed_at` for each match.
- The admin Matches table shows "Live seen", "Stats in" and "MVP picked", each as minutes after the match's `start_time` (e.g. "+2 min", "+58 min"), with "—" when unknown. Hovering a value shows the exact time.
- Failure path: a match that was never seen live shows "—" under "Live seen", which marks it as missed by live detection.

### Casters Can See How Fresh the Match List Is
**User story**
As a caster, I want the MVP picker to tell me when it last checked for live games and let me refresh it, so that I know whether to wait or whether something is wrong.

**Acceptance criteria**
- `GET /twitch/matches/current` returns:
  - `live_checked_at`: the Unix time of the last successful live check, or `null` if there hasn't been one since start-up;
  - `live_source_configured`: whether `STEAM_API_KEY` is set.
- The panel's series list shows "Live games checked N s ago" (or "N min ago"), and a Refresh button that fetches the list again.
- When `live_checked_at` is more than 5 minutes old or `null`, or the source isn't configured, the line reads "Live games not checked recently — your match will appear once its stats are in" in the warning colour.
- Failure path: if the request fails, the panel shows its existing error state and the Refresh button stays usable.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/steam_live.py` *(new)* | `get_live_league_games(league_ids)` calls `GetLiveLeagueGames` with `STEAM_API_KEY`, one attempt and a 10 s timeout. It returns `None` on failure, or a list of normalised entries. `STEAM_API_KEY` is read here. |
| `backend/main.py` | New `_live_poll_loop` / `_live_poll_once` thread, `LIVE_POLL_INTERVAL` and `_live_checked_at`. `_ingest_poll_loop` drops its live calls and reads live state from `live_matches`. The live thread isn't started in demo mode or without a key, and a start-up warning is logged when the key is missing. |
| `backend/ingest.py` | Remove `get_live_matches()`. `store_live_matches()` is unchanged apart from writing `match_timings.live_first_seen_at` on first sight. `ingest_match()` writes `match_timings.ingested_at`. |
| `backend/models.py` | New `MatchTiming` model (`match_timings`, created by `create_all`). |
| `backend/twitch.py` | `GET /twitch/matches/current` adds `live_checked_at` and `live_source_configured`. `POST /twitch/mvp` writes `mvp_confirmed_at` and `mvp_provisional` on first confirmation. |
| `backend/routers/admin_matches.py` | `GET /admin/matches` joins `match_timings`. |
| `frontend/app-admin-matches.js` | Three timing columns, as minutes after start, with the exact time on hover. |
| `twitch-extension/live_config.js`, `twitch-extension/live_config.html` | Freshness line, warning state and a Refresh button in the series step. |
| `.env.example` | `STEAM_API_KEY=` (commented, noting that the Steam login, #150, will reuse it) and `LIVE_POLL_INTERVAL=60`. |
| `markdown/features/reference/early-mvp-selection.md`, `markdown/features/reference/mvp-selection-delays.md` | Live source changed to Steam; fill in this feature's doc. |
| `backend/tests/test_issue_161_mvp_selection_delays.py`, existing #139 tests | New tests. Tests that mock `get_live_matches` / OpenDota `/live` are moved to the Steam source. |

### Step 1 — Verify the Steam response
During a live Kanaliiga game, call:
```bash
curl -s "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/?key=$STEAM_API_KEY&league_id=20162"
```
Save a trimmed copy, with ids kept and no key, as `backend/tests/fixtures/steam_live_league_games.json`.

Confirm these before writing the parser:
- the field names,
- the `players[].team` values,
- whether the `league_id` parameter filters on the server, or the full list must be filtered locally (with one call per check either way).

If the game is missing while it's live, stop and report back on the issue before going further.

### Step 2 — Steam source
```python
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "").strip()
_URL = "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/"

def get_live_league_games(league_ids) -> list[dict] | None:
    """Live games of the given leagues, normalised to the store_live_matches() entry
    shape; None when the request fails (never raises, never logs the key)."""
```
- Filter to `league_ids`, and normalise team ids (0 → `None`), names (`""` → `None`) and players (team 0/1 only, `account_id` required).
- On a request error, log the status or exception class only.

### Step 3 — Separate live thread
```python
_LIVE_POLL_INTERVAL = int(os.getenv("LIVE_POLL_INTERVAL", "60"))
_live_checked_at: int | None = None

def _live_poll_once():
    monitored = _get_monitored_league_ids()
    if not monitored or not steam_live.STEAM_API_KEY:
        return
    games = steam_live.get_live_league_games(monitored)
    if games is None:
        return                          # keep previous rows; don't mark them ended
    store_live_matches(games, monitored)
    global _live_checked_at
    _live_checked_at = int(time.time())

def _live_poll_loop():
    while not _stop_event.is_set():
        try:
            _live_poll_once()
        except Exception:
            logger.exception("Live poll failed")
        _stop_event.wait(timeout=_LIVE_POLL_INTERVAL)
```

`_ingest_poll_loop` no longer calls `get_live_matches()` or `store_live_matches()`. The set of leagues currently live, used to skip enrichment and to choose the fast interval, comes from `live_matches` rows with `ended_at IS NULL` seen in the last 15 minutes, together with `_has_recently_ended_live_match()`.

### Step 4 — Timings
`MatchTiming(match_id PK, live_first_seen_at, ingested_at, mvp_confirmed_at, mvp_provisional)`. A helper `record_timing(db, match_id, **fields)` sets only the fields that are still `NULL`.

Call it from:
- `store_live_matches()` (first sight),
- `ingest_match()` (stats written),
- `POST /twitch/mvp` (first confirmation).

### Step 5 — Admin columns and panel freshness
- **Admin:** `GET /admin/matches` adds the three timing fields. `app-admin-matches.js` shows each as `+N min` after `start_time`, with the exact time in `title`.
- **Twitch:** `GET /twitch/matches/current` adds `live_checked_at` and `live_source_configured`. In `live_config.js`, the series step shows the "checked N s ago" line or the warning, plus a Refresh button that calls `loadSeries()` again, following the panel's existing styling.

### Step 6 — Documentation
- Update `early-mvp-selection.md`: Steam as the live source, the separate thread, the OpenDota `/live` field table replaced by the Steam fields, and the freshness fields.
- Fill in `mvp-selection-delays.md`.
- Document `STEAM_API_KEY` and `LIVE_POLL_INTERVAL` in `.env.example` and the feature docs.
- Update the Early MVP Selection stories in `markdown/stories/twitch.md` where they name OpenDota `/live`.

## Verification
- **Unit tests:**
  - The Steam parser, against the saved fixture: games from leagues that aren't monitored are dropped, casters and spectators (team ≥ 2) are skipped, players without an account id are skipped, and team ids of 0 are stored as `NULL`.
  - `get_live_league_games` returns `None` on a timeout or error status, and the key doesn't appear in logged output.
  - `_live_poll_once` stores games and sets `_live_checked_at`. When Steam fails it changes no rows and doesn't set `ended_at`. Without `STEAM_API_KEY` it makes no request.
  - `store_live_matches` writes `live_first_seen_at` once; `ingest_match` writes `ingested_at`; `POST /twitch/mvp` writes `mvp_confirmed_at` once, with `mvp_provisional` correct.
  - `GET /twitch/matches/current` includes `live_checked_at` and `live_source_configured`. `GET /admin/matches` includes the timing fields.
  - Static checks:
    - `_ingest_poll_loop` doesn't call `store_live_matches`, and nothing calls OpenDota `/live`;
    - the live thread doesn't start in demo mode or without a key.
- **Manual, on the next match night, with `STEAM_API_KEY` set:**
  - The casted game appears in the MVP picker within about a minute of starting, and the picker shows "Live games checked … ago".
  - In the admin Matches table, "Live seen" is a few minutes after the start and "Stats in" comes later.
- **Manual, without a key:** the start-up warning is logged, the picker shows the warning line, and matches still appear after ingest.
- Run the full suite and update the suite-size check in `tests/test_issue_85_split_admin_router.py`.
