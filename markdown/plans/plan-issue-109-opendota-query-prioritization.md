# Plan: OpenDota Query Prioritization

## Context
During the first ingest of a new league (issue #107/#101's league 20163), fetching a single
just-finished match took several minutes. The cause, confirmed while diagnosing that incident,
isn't really "query ordering" in the abstract — it's that `_auto_ingest()` runs match ingestion
and `run_enrichment()` (player name/avatar backfill, up to 20 rounds of 50 players each) fully
sequentially in a single background thread, all sharing one process-wide OpenDota rate limit
(`OPENDOTA_MAX_RPM`, default 55/min). If any call in that sequence gets rate-limited or errors,
`opendota_client.get_json`'s exponential backoff (10s → 20s → 40s → 80s → 160s, up to 5 attempts)
can block the *entire* next poll cycle — including the one check that actually matters when a
broadcaster is waiting to select an MVP: "has this match finished yet?" A bulk player-enrichment
backlog competing for the same budget at the same moment makes this materially worse.

**Feasibility assessment (per the issue's own ask):** a general-purpose priority queue for
OpenDota calls would be over-engineering for a single-process, single-league-at-a-time workload.
A much simpler, genuinely practical mechanism exists instead: OpenDota's `GET /live` endpoint
returns all currently-live tracked matches with a `league_id` field, in one cheap call — verified
directly against the live API, response includes `league_id`, `match_id`, `team_id_radiant`,
`team_id_dire`, `team_name_radiant`, `team_name_dire`, `game_time` per entry. This lets the app
cheaply answer "does any monitored league have a match in progress right now?" without guessing
from schedule data or spending per-match budget. That single fact is enough to implement the
issue's actual request: while true, skip the low-priority enrichment pass and poll the league's
match list on a tighter interval; once false, resume normal-priority background work. This plan
is scoped to that mechanism — **feasible and practical**, without introducing a general priority
queue, worker pool, or per-call priority tagging that the current architecture doesn't need.

*Resolves GitHub issue #109.*

## User Stories

### Defer Low-Priority Enrichment While a Monitored Match Is Live
**User story**
As an operator, I want low-priority background work (player name/avatar backfill) to pause
automatically while a monitored league has a match in progress, so OpenDota's rate limit isn't
spent on non-urgent work exactly when a broadcaster is waiting to select an MVP.

**Acceptance criteria**
- A single `GET /live` call, filtered to leagues currently marked `is_monitored`, determines
  whether any monitored league has a match in progress this poll cycle
- While at least one monitored league has a live match, `run_enrichment()` is skipped for that
  cycle — ingestion of new match data for monitored leagues is never paused, only enrichment
- Once no monitored league has a live match, enrichment resumes on its normal cadence the next
  cycle
- The live-match check costs exactly one OpenDota request per poll cycle regardless of how many
  leagues are monitored, so it never meaningfully competes for rate-limit budget itself

---

### Poll Faster While a Monitored Match Is Live
**User story**
As a broadcaster, I want the app to notice quickly once a match I just finished has been
processed, so I'm not stuck waiting on the standard poll interval before I can select the MVP.

**Acceptance criteria**
- While the live-match check finds a monitored league's match in progress, the ingest poll loop
  uses a shorter interval than the existing `INGEST_LIVE_POLL_INTERVAL` "active week" cadence —
  a match actively being played is a stronger, more specific signal than "some week is open"
- As soon as the live match disappears from `GET /live` (i.e. has ended), the next poll's normal
  match-ingest step picks it up, subject only to OpenDota having finished processing it
- `GET /twitch/matches/current` reflects the newly-ingested match (with player stats) as soon as
  ingestion completes, so `live_config.js`'s MVP flow lists it without a manual "Ingest Now" click

---

### Operator Visibility into Prioritization State
**User story**
As an operator, I want to see whether the live-match priority gate is currently active, so I can
confirm the feature is engaged during a live event instead of guessing from ingest duration alone.

**Acceptance criteria**
- Log lines clearly state when enrichment is skipped for a cycle because a monitored league has
  a live match, and when it resumes because none do
- The existing `/schedule/debug`-style admin debug tooling pattern is followed: a lightweight
  field or log line reports the outcome of the most recent live-match check and its timestamp,
  so an operator mid-event doesn't have to guess whether the gate fired

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/ingest.py` | Add `get_live_match_league_ids() -> set[int]` — one `GET /live` call, returns the set of `league_id`s currently live (mirrors `get_league_matches`/`get_league_info`'s existing pattern) |
| `backend/main.py` | `_ingest_poll_loop`/`_auto_ingest`: check live-match state once per cycle against monitored league IDs; skip `run_enrichment()` and select the tighter poll interval when any are live; log the outcome |
| `.env.example` | Document `INGEST_LIVE_MATCH_POLL_INTERVAL` (or similar) alongside the existing `INGEST_LIVE_POLL_INTERVAL` |
| `markdown/features/reference/ingest.md` | Update "Automatic Polling" to describe the live-match gate and the new tighter interval |

### Step 1 — Live-match check
In `backend/ingest.py`, alongside `get_league_matches`/`get_league_info`:
```python
def get_live_match_league_ids() -> set[int]:
    """League IDs with a match currently in progress, per OpenDota's live endpoint.
    One request regardless of how many leagues are monitored."""
    data = opendota_get_json(f"{OPEN_DOTA_URL}/live", label="live matches") or []
    return {m.get("league_id") for m in data if m.get("league_id")}
```

### Step 2 — Gate enrichment and tighten the poll interval
In `backend/main.py`, extend `_auto_ingest`/`_ingest_poll_loop`:
```python
_INGEST_LIVE_MATCH_POLL_INTERVAL = int(os.getenv("INGEST_LIVE_MATCH_POLL_INTERVAL", "30"))

def _auto_ingest(league_ids: list[int], live_league_ids: set[int]):
    for league_id in league_ids:
        try:
            logger.info("Auto-ingest: league %d starting", league_id)
            ingest_league(league_id)
            if league_id in live_league_ids:
                logger.info("Auto-ingest: league %d has a live match — skipping enrichment this cycle", league_id)
            else:
                run_enrichment()
            logger.info("Auto-ingest: league %d done", league_id)
        except Exception:
            logger.exception("Auto-ingest: league %d failed", league_id)


def _ingest_poll_loop():
    while not _stop_event.is_set():
        try:
            monitored = _get_monitored_league_ids()
            live = get_live_match_league_ids() & set(monitored)
            _auto_ingest(monitored, live)
            _run_toornament_sync()
            if live:
                interval = _INGEST_LIVE_MATCH_POLL_INTERVAL
            elif _has_active_week():
                interval = _INGEST_LIVE_POLL_INTERVAL
            else:
                interval = _INGEST_POLL_INTERVAL
        except Exception:
            logger.exception("Unexpected error in ingest poll loop")
            interval = _INGEST_POLL_INTERVAL
        _stop_event.wait(timeout=interval)
```
A failure in `get_live_match_league_ids()` (network error, OpenDota down) must not crash the
loop — `opendota_get_json` already returns `None`/`[]` rather than raising on exhausted retries,
so `live` degrades to an empty set and the loop falls back to existing interval selection.

### Step 3 — Docs and env
- `.env.example`: document `INGEST_LIVE_MATCH_POLL_INTERVAL` (default `30`) next to the existing
  `INGEST_POLL_INTERVAL`/`INGEST_LIVE_POLL_INTERVAL` entries.
- `markdown/features/reference/ingest.md`, "Automatic Polling": add a paragraph describing the
  live-match gate and the three-tier interval (`INGEST_POLL_INTERVAL` → `INGEST_LIVE_POLL_INTERVAL`
  during an active week → `INGEST_LIVE_MATCH_POLL_INTERVAL` while a monitored league is live).

## Verification
- With a monitored league that has a currently-live match (per `GET /live`), confirm
  `run_enrichment()` is not called for that league's cycle and a log line says why
- With no monitored league live, confirm enrichment runs exactly as it does today (no regression)
- Confirm the poll loop uses `INGEST_LIVE_MATCH_POLL_INTERVAL` while a monitored league is live,
  falls back to `INGEST_LIVE_POLL_INTERVAL` during an active week with nothing live, and
  `INGEST_POLL_INTERVAL` otherwise
- Simulate `get_live_match_league_ids()` raising/returning `None` (OpenDota unreachable) — the
  poll loop does not crash and falls back to normal interval selection
- End-to-end: with a real match in progress on a monitored league, confirm the match is ingested
  and visible via `GET /twitch/matches/current` within one `INGEST_LIVE_MATCH_POLL_INTERVAL`
  cycle after it ends, without needing a manual `POST /ingest/league/{id}` call
- Run `cd backend && python -m pytest tests/ -v` — full suite passes
