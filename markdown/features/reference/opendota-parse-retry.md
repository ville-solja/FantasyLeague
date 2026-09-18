# OpenDota Parse Retry

Re-fetches matches that were ingested before OpenDota parsed their replay, replaces their stat
rows once the parsed version exists, and asks OpenDota to parse any match it hasn't got to yet.
Runs as part of every ingest poll cycle; admins can also trigger it on demand.

*(see `markdown/plans/plan-opendota-parse-retry.md`)*

---

## Why

Most of a game's fantasy points come from replay-parsed stats (`teamfight_participation`,
`stuns`, `obs_placed`, `camps_stacked`, `rune_pickups`, `towers_killed`, `roshan_kills`,
`firstblood_claimed`). OpenDota returns them as `0`/`null` until the replay is parsed and reports
`"version": null` on the match. First-pass ingest happens minutes after a match ends, so those
rows are often stored unparsed — and `ingest_league()` never re-fetches a match ID it already
has, so the partial score was permanent.

## Detection

"Looks unparsed" is derived from stored data, not a new column: a match qualifies when the
`SUM` over its `player_match_stats` rows is `0` for all three of `teamfight_participation`,
`stuns` and `obs_placed`. No migration was needed, and matches already ingested wrong before
this feature shipped are picked up automatically on the first poll cycle after deploy.

## Re-check flow (`backend/ingest.py`)

| Function | Role |
|---|---|
| `find_unparsed_match_ids(db, max_age_hours) -> list[int]` | Match IDs with `start_time` within the window whose rows are signature-zero; `max_age_hours <= 0` returns `[]` |
| `refresh_match_stats(db, match_id, weights) -> str` | Re-fetches `GET /matches/{id}`. Returns `"unavailable"` (fetch failed), `"unparsed"` (`version` still null, rows untouched) or `"refreshed"` (rows deleted and re-inserted from the fresh payload via the same `_build_stat_row()` helper first-pass ingest uses, `fantasy_points` recomputed with the current weights, `duration`/`radiant_win` updated, Twitch MVP flag + bonus re-applied via `_reapply_mvp_bonus()`) |
| `request_parse(match_id) -> bool` | `POST /request/{match_id}` through `opendota_client.post_json(..., cost=10)`; at most once per match per `INGEST_PARSE_REREQUEST_HOURS` (`ingest._parse_requested` maps match_id → time of the last successful request). A failed POST is logged as a warning, returns `False`, and leaves the match eligible next cycle |
| `retry_unparsed_matches(max_age_hours) -> dict` | One pass over `find_unparsed_match_ids()`: refreshes each match, and requests a parse for every one still unparsed that hasn't been requested yet. Returns `{"checked", "refreshed", "requested", "still_unparsed"}`; an `"unavailable"` match counts toward `still_unparsed`. A failure on one match is logged (`logger.exception`) and does not stop the others |

First-pass `ingest_match()` is unchanged in what it stores (an unparsed match still appears in
the schedule immediately) but now calls `request_parse(match_id)` when the payload has
`version: null`.

`WeeklySummary` rows only gate report visibility — points are computed live from
`player_match_stats` — so a refreshed match needs no summary regeneration.

### Poll-cycle hook (`backend/main.py::_auto_ingest`)

After the per-league `ingest_league()` loop, still inside the poll loop's `INGEST_LOCK` block:

```python
if league_ids and _INGEST_PARSE_RETRY_HOURS > 0:
    try:
        summary = retry_unparsed_matches(_INGEST_PARSE_RETRY_HOURS)
        logger.info("Parse retry: %s", summary)
    except Exception:
        logger.exception("Parse retry step failed")
```

The step is skipped when no league is monitored, so a fresh or test database never makes
OpenDota calls from the background thread.

### Rate-limit accounting (`backend/opendota_client.py`)

`throttle(cost: int = 1)` appends `cost` timestamps to the rolling 60 s window and only admits
the call when `len(window) + cost <= OPENDOTA_MAX_RPM` (an empty window always admits it, so
a single expensive call can never starve). `post_json(url, *, timeout=30, label="", cost=1)`
is the POST counterpart of `get_json()`: same `api_key` query parameter and headers, no retries,
returns the decoded JSON object or `None` on a non-2xx/timeout.

## Endpoints

### `POST /ingest/retry-unparsed?max_age_hours=<int>`
Admin only (`Depends(require_admin)`). Acquires `ingest.INGEST_LOCK` non-blocking — 409 if the
poll loop or a manual league ingest is running — writes a `parse_retry_triggered` audit row
(`detail="max_age_hours=<N>"`), then runs `retry_unparsed_matches()` in a daemon thread and
returns `{"status": "started", "max_age_hours": <N>}` immediately. `max_age_hours` (1–8760)
overrides `INGEST_PARSE_RETRY_HOURS` for that run so matches ingested wrong before deploy can be
backfilled without changing env vars. The finished run logs
`Parse retry complete (max_age_hours=N): checked=… refreshed=… requested=… still_unparsed=…`
on the `routers.admin_ingest` logger.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `INGEST_PARSE_RETRY_HOURS` | `48` | How far back the poll cycle looks for unparsed matches; `0` disables the step (and, absent a `max_age_hours` override, makes the admin endpoint a no-op) |
| `INGEST_PARSE_REREQUEST_HOURS` | `6` | Minimum time between two parse requests for the same match — OpenDota drops a job whose replay download failed (Valve replay server 5xx), so a still-unparsed match is asked for again after the cooldown |

## Operator notes

- Diagnostic query for a dev/prod DB, before and after a poll cycle:
  `SELECT match_id, SUM(teamfight_participation), SUM(stuns), SUM(obs_placed) FROM player_match_stats GROUP BY match_id`
  — zero rows for recent matches should disappear once OpenDota has parsed them.
- A match OpenDota itself never parses (or parses to genuine zeros) is re-checked once per
  cycle until it ages out of the window; that costs one `GET` per cycle and one 10-slot `POST`
  per `INGEST_PARSE_REREQUEST_HOURS`.
- `GET /request/{jobId}` returns `null` once OpenDota has processed the job, whether or not the
  parse succeeded; a match still reporting `version: null` afterwards usually means the replay
  could not be downloaded from Valve (check the `replay_url` from `GET /matches/{id}`), which
  is exactly the case the re-request cooldown exists for.
- Tests: `backend/tests/test_opendota_parse_retry.py` (22 tests, no network).
