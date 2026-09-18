# Plan: OpenDota Parse Retry

## Context

Roughly two thirds of an average game's fantasy points come from stats that OpenDota only
provides once it has *parsed* the replay (`teamfight_participation`, `stuns`, `obs_placed`,
`camps_stacked`, `rune_pickups`, `towers_killed`, `roshan_kills`, `firstblood_claimed`). The ingest
poll runs every 15 minutes (and every 30 seconds during a live match), so a match is routinely
ingested before OpenDota has parsed it — those fields come back as `0`/`null`, `fantasy_score()`
is computed on the crippled stat line, and because `ingest_league()` skips every match ID that
already exists in `matches`, the match is never fetched again. A support player in an unparsed
game scores 2–3 points instead of 12–15, which is the main driver behind the very low cards seen
in the production weekly standings.

OpenDota exposes `POST /request/{match_id}` to queue a replay parse (it counts as 10 calls
against the rate limit) and reports `"version": null` on `GET /matches/{match_id}` while a match
is unparsed. This plan keeps first-pass ingest unchanged (results should still appear in the
schedule immediately) and adds a re-check step to every poll cycle: matches that still look
unparsed are re-fetched, their stat rows replaced once a parsed version exists, and a parse is
requested once per match if OpenDota hasn't done it on its own.

Assumptions made here: "looks unparsed" is detected from the stored data (all stat rows for the
match have `teamfight_participation`, `stuns` and `obs_placed` summed to 0) rather than a new
`matches` column, so no migration is needed and matches already ingested wrong in production are
picked up automatically. The rare upstream-broken match (OpenDota itself returns zeros with a
non-null `version`) will be re-checked until it ages out of the retry window, which is harmless.

## User Stories

### Unparsed Matches Are Re-fetched Until Parsed
**User story**
As a player, I want a match that was ingested before OpenDota parsed it to be re-fetched and
re-scored once the parse is available, so that my cards get full fantasy points instead of the
partial ones a first-pass ingest produced.

**Acceptance criteria**
- Each ingest poll cycle re-checks every match whose `start_time` is within the last
  `INGEST_PARSE_RETRY_HOURS` hours (default `48`) and whose `player_match_stats` rows sum to 0 for
  `teamfight_participation`, `stuns` and `obs_placed`
- If `GET /matches/{match_id}` now returns a non-null `version`, the match's existing
  `player_match_stats` rows are deleted and re-inserted from the fresh payload, `fantasy_points`
  is recomputed with the current weights, and a previously confirmed Twitch MVP for that match
  keeps its `is_mvp` flag and bonus
- If the payload still has `version: null`, the stored rows are left untouched
- Matches older than the retry window are never re-fetched, so the extra OpenDota traffic is
  bounded by the number of recent unparsed matches, not the size of the database
- The re-check runs under `ingest.INGEST_LOCK` like the rest of the cycle and a failure on one
  match is logged and does not abort the cycle or the other matches

### A Parse Is Requested From OpenDota
**User story**
As an operator, I want the app to ask OpenDota to parse a match it has ingested unparsed, so
that the full stats become available without waiting for OpenDota to get to it on its own.

**Acceptance criteria**
- When first-pass ingest stores a match whose payload has `version: null`, it immediately submits
  `POST /request/{match_id}` and logs the returned job id
- The re-check step submits a parse request for any match that is still unparsed and has not had
  one submitted by this process yet; a match is requested at most once per process lifetime
- The request goes through `opendota_client` with the same `api_key` handling and throttle as
  every other OpenDota call, and is counted as 10 requests against the local RPM cap to mirror
  OpenDota's own accounting
- A failed request (non-2xx, timeout) is logged as a warning and does not raise; the match stays
  eligible for the next cycle's re-check

### Admin Can Trigger a Backfill On Demand
**User story**
As an admin, I want to trigger the unparsed-match re-check manually with a wider window, so that
matches ingested wrong before this feature was deployed can be repaired without waiting for the
next poll or changing environment variables.

**Acceptance criteria**
- `POST /ingest/retry-unparsed` (admin only) runs the re-check in a background thread and returns
  `{"status": "started"}` immediately, or 409 if an ingest is already running, mirroring
  `POST /ingest/league/{league_id}`
- An optional `max_age_hours` query parameter overrides `INGEST_PARSE_RETRY_HOURS` for that run
- The action is written to the audit log with the window used
- The completed run logs how many matches were checked, refreshed, requested and still unparsed

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/opendota_client.py` | `throttle(cost=1)` accepts a cost; new `post_json()` helper for `POST /request/{match_id}` |
| `backend/ingest.py` | Extract the per-player stat-row build from `ingest_match()` into a helper; add `find_unparsed_match_ids()`, `refresh_match_stats()`, `request_parse()`, `retry_unparsed_matches()`; request a parse on first-pass ingest of an unparsed match |
| `backend/main.py` | Call `retry_unparsed_matches()` from `_auto_ingest()` after the per-league ingest loop, inside the existing `INGEST_LOCK` block; read `INGEST_PARSE_RETRY_HOURS` |
| `backend/routers/admin_ingest.py` | `POST /ingest/retry-unparsed` background-thread endpoint with optional `max_age_hours` |
| `.env.example` | Document `INGEST_PARSE_RETRY_HOURS` |
| `markdown/features/reference/opendota-parse-retry.md` | Fill in the stub |
| `markdown/features/reference/ingest.md` | Add the re-check stage to the pipeline description |
| `backend/tests/test_opendota_parse_retry.py` | Tests (written by the test-planner stage) |

### Step 1 — OpenDota client: cost-aware throttle and a POST helper

```python
def throttle(cost: int = 1) -> None:
    # append `cost` timestamps instead of one so a 10-call parse request
    # consumes 10 slots of the rolling window

def post_json(url: str, *, timeout: float = 30, label: str = "", cost: int = 1) -> dict | None:
    """POST with api_key + headers; returns decoded JSON or None. No retries — the
    caller re-checks on the next cycle anyway."""
```

`request_parse()` calls `post_json(f"{OPEN_DOTA_URL}/request/{match_id}", cost=10)`.

### Step 2 — Detect and refresh unparsed matches in `ingest.py`

```python
_parse_requested: set[int] = set()   # once per process

def _is_unparsed(data: dict) -> bool:
    return data.get("version") is None

def find_unparsed_match_ids(db, max_age_hours: int) -> list[int]:
    # SELECT m.match_id FROM matches m JOIN player_match_stats s ON s.match_id = m.match_id
    # WHERE m.start_time >= :cutoff
    # GROUP BY m.match_id
    # HAVING SUM(s.teamfight_participation) = 0 AND SUM(s.stuns) = 0 AND SUM(s.obs_placed) = 0

def refresh_match_stats(db, match_id: int, weights: dict) -> str:
    """Re-fetch one match. Returns "refreshed" | "unparsed" | "unavailable"."""
    # data = opendota_get_json(f"{OPEN_DOTA_URL}/matches/{match_id}")
    # None -> "unavailable"; _is_unparsed(data) -> "unparsed"
    # else: delete PlayerMatchStats for match_id, re-insert via the shared row builder,
    #       update match.duration / radiant_win, commit, re-apply MVP bonus exactly as
    #       ingest_match() already does -> "refreshed"

def request_parse(match_id: int) -> bool:
    # skip if match_id in _parse_requested; POST; on success add to the set and log jobId

def retry_unparsed_matches(max_age_hours: int) -> dict:
    """Run one re-check pass. Returns {"checked", "refreshed", "requested", "still_unparsed"}."""
```

`ingest_match()` keeps its current behaviour for an unparsed payload (rows are stored so the
match appears immediately) and additionally calls `request_parse(match_id)` when
`_is_unparsed(data)`. The per-player `PlayerMatchStats(...)` construction is moved into a helper
so first-pass ingest and refresh build identical rows.

### Step 3 — Hook into the poll cycle

In `main.py::_auto_ingest()`, after the per-league `ingest_league()` loop and before enrichment:

```python
try:
    summary = retry_unparsed_matches(_INGEST_PARSE_RETRY_HOURS)
    logger.info("Parse retry: %s", summary)
except Exception:
    logger.exception("Parse retry step failed")
```

`_INGEST_PARSE_RETRY_HOURS = int(os.getenv("INGEST_PARSE_RETRY_HOURS", "48"))`; `0` disables
the step. The first poll cycle runs on startup, so deploying this backfills any recent
production matches without further action.

### Step 4 — Admin endpoint

`POST /ingest/retry-unparsed?max_age_hours=<int>` in `admin_ingest.py`, following
`ingest_league_endpoint()`: acquire `INGEST_LOCK` non-blocking (409 if held), spawn a daemon
thread that runs `retry_unparsed_matches()` and logs the summary, write an audit log entry
(`parse_retry_triggered`, with the window), return `{"status": "started"}`.

### Step 5 — Docs and config

- `.env.example`: `INGEST_PARSE_RETRY_HOURS=48` block next to the other `INGEST_*` variables
- `ingest.md`: new "Parse retry" stage between Match Ingest and Name & Avatar Backfill
- Fill in `opendota-parse-retry.md`

## Verification

- Unit: `find_unparsed_match_ids()` returns a match whose rows are all zero on the three
  signature stats, ignores a parsed match, and ignores an all-zero match older than the window
- Unit: `refresh_match_stats()` with a monkeypatched `opendota_get_json` returning
  `version: null` leaves rows untouched and returns `"unparsed"`; returning a parsed payload
  replaces the rows, recomputes `fantasy_points`, and keeps `is_mvp` + bonus on the MVP row
- Unit: `request_parse()` posts once per match per process and swallows a failed POST
- Unit: `retry_unparsed_matches()` summary counts; one raising match does not stop the others
- Unit: `throttle(cost=10)` consumes ten slots of the RPM window
- Endpoint: `POST /ingest/retry-unparsed` requires admin, returns 409 while `INGEST_LOCK` is
  held, and honours `max_age_hours`
- Manual: on a dev DB, run the production diagnostic query
  (`SELECT match_id, SUM(teamfight_participation), SUM(stuns), SUM(obs_placed) FROM player_match_stats GROUP BY match_id`)
  before and after a poll cycle and confirm the zero rows for recent matches disappear
- Check whether weekly summaries (`generate_weekly_summaries`) snapshot per-user points; if they
  do, a refreshed match inside an already-summarised week needs that week's summary regenerated
  and the plan should be extended before implementation
- No migration is required — no model columns are added
