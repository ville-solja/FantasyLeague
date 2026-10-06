# OpenDota Query Prioritization

Live-match-aware gating for the background ingest pipeline (`reference/ingest.md`): while a
monitored league has a match in progress, low-priority player enrichment is skipped and the poll
interval tightens, so the one query that matters most — "has the match finished yet?" — isn't
stuck behind bulk background work sharing the same OpenDota rate limit.

*(see `markdown/plans/plan-issue-109-opendota-query-prioritization.md`, resolves GitHub issue #109)*

---

## Why not a general priority queue

Considered and rejected as over-engineering for this workload: this app ingests one league (or a
small handful) at a time from a single background thread, all sharing one process-wide OpenDota
rate limit (`OPENDOTA_MAX_RPM`). The actual problem observed in production — a single new match
taking several minutes to ingest — traced back to `run_enrichment()`'s player backfill (up to 20
rounds of 50 players) running sequentially before/alongside match ingestion, and any OpenDota
429/5xx along the way triggering `opendota_client.get_json`'s exponential backoff (up to ~160s per
failed call), which blocks the *entire* next poll cycle in a single-threaded loop. A per-call
priority queue would add real complexity without addressing that specific mechanism. A cheap,
targeted signal does: knowing, once per poll cycle, whether *any* monitored league has a live
match right now. This was first a single OpenDota `GET /live` request per cycle; since issue #161
the live games come from Steam's league list, checked by a separate thread (see
`reference/mvp-selection-delays.md`), and the poll loop only reads the stored result.

## Behaviour

- `backend/main.py::_live_league_ids(monitored)` — the monitored leagues with a `live_matches` row
  that has not ended and was seen in the last 15 minutes. The rows are written by the live thread
  (`_live_poll_loop`, Steam `GetLiveLeagueGames`), so this check makes no OpenDota or Steam
  request. Before #161 it was `ingest.get_live_matches()`, one OpenDota `GET /live` call per cycle.
- `backend/main.py::_ingest_poll_loop` uses that set; if any monitored league is live:
  - `run_enrichment()` is skipped for that cycle (match ingestion itself is never skipped) —
    `_auto_ingest(league_ids, live_league_ids)` logs which outcome applied to each league
  - the next poll uses `INGEST_LIVE_MATCH_POLL_INTERVAL` (tighter than the existing
    `INGEST_LIVE_POLL_INTERVAL` "active week" cadence) instead of the normal interval
- Once no monitored league is live, both enrichment and the normal interval selection resume,
  and a log line confirms enrichment is running again for that league
- A failure reading `live_matches` is logged and treated as "nothing live" for that cycle: match
  ingest and enrichment run and the active-week/default interval applies, without crashing the
  loop. A failed Steam request in the live thread changes no rows (see
  `reference/mvp-selection-delays.md`); after 15 minutes without a sighting a stored game no
  longer counts as live

## Configuration

| Variable | Default | Description |
|---|---|---|
| `INGEST_LIVE_MATCH_POLL_INTERVAL` | `30` | Poll interval (seconds) while a monitored league has a live match (per `live_matches`), and for `INGEST_POST_MATCH_FAST_POLL_MINUTES` after one ends |

---

See `reference/ingest.md` for the full three-tier polling interval and pipeline stages this gate
sits within.
