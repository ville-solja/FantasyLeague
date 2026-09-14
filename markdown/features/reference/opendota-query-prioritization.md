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
targeted signal does: OpenDota's `GET /live` endpoint returns every currently-live tracked match
with its `league_id`, in one request — enough to know, once per poll cycle, whether *any*
monitored league needs urgent attention right now.

## Behaviour

- `backend/ingest.py::get_live_match_league_ids()` — one `GET /live` call per poll cycle, returns
  the set of `league_id`s with a match currently in progress. Called only when at least one
  league is currently monitored, so an idle app makes no extra requests.
- `backend/main.py::_ingest_poll_loop` intersects that set with the currently-monitored league
  IDs; if any monitored league is live:
  - `run_enrichment()` is skipped for that cycle (match ingestion itself is never skipped) —
    `_auto_ingest(league_ids, live_league_ids)` logs which outcome applied to each league
  - the next poll uses `INGEST_LIVE_MATCH_POLL_INTERVAL` (tighter than the existing
    `INGEST_LIVE_POLL_INTERVAL` "active week" cadence) instead of the normal interval
- Once no monitored league is live, both enrichment and the normal interval selection resume,
  and a log line confirms enrichment is running again for that league
- A failed/unreachable `GET /live` call raises inside `_ingest_poll_loop`'s per-cycle try/except,
  which falls back to the plain default interval (`INGEST_POLL_INTERVAL`) for that cycle only —
  not the active-week interval, since the `except` block doesn't re-check `_has_active_week()` —
  without crashing the loop; `get_live_match_league_ids()` itself also degrades to an empty set
  rather than raising when the underlying `opendota_get_json` call is exhausted, matching that helper's
  existing None-on-exhausted-retries contract

## Configuration

| Variable | Default | Description |
|---|---|---|
| `INGEST_LIVE_MATCH_POLL_INTERVAL` | `30` | Poll interval (seconds) while a monitored league has a live match, per `GET /live` |

---

See `reference/ingest.md` for the full three-tier polling interval and pipeline stages this gate
sits within.
