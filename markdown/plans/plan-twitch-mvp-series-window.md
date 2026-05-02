# Plan: Twitch MVP Series Window

## Context

The MVP selection panel in the Twitch Quick Actions view currently scopes match data to the
current or most-recently-locked week. This causes two problems: if a match is played at a
week boundary, or if the current week has no ingested matches yet, the series list is empty
and the broadcaster cannot appoint MVP. Additionally, the ingest polling interval defaults to
900 seconds (15 minutes), meaning a broadcaster may wait up to 25 minutes after a match ends
before its player stats appear in the panel — too long for a live broadcast workflow.

This plan changes the endpoint to return the 5 most recent series that have at least one
ingested match (ignoring week boundaries), and adds a faster ingest polling interval for
use during active weeks.

*Resolves GitHub issue #42.*

---

## User Stories

### MVP Panel Shows 5 Most Recent Series with Ingested Data
**User story**
As a broadcaster, I want the MVP selection panel to always show the 5 most recent series
that have completed match data so I can appoint MVP even when no matches have been ingested
for the current week or the series spans a week boundary.

**Acceptance criteria**
- `GET /twitch/matches/current` returns the 5 most recent series (by latest match `start_time`)
  that have at least one match with ingested player stats (`player_match_stats` rows exist)
- Series are not limited to the current or any single week
- Series are sorted most-recently-played first
- If fewer than 5 qualifying series exist, all available are returned
- Matches within each series are still limited to those that have already started (`start_time ≤ now`)
- The extension panel shows correct match and player data regardless of week boundary

---

### Faster Ingest Polling During Active Weeks
**User story**
As a broadcaster, I want match data to appear in the MVP panel within a few minutes of a
match ending so I can appoint MVP promptly after the game concludes.

**Acceptance criteria**
- A new `INGEST_LIVE_POLL_INTERVAL` env var (default: `120`) controls the polling interval
  used when an active (unlocked, currently-running) week exists
- When no active week is in progress, the existing `INGEST_POLL_INTERVAL` (default: 900)
  is used instead — avoiding unnecessary API churn during off-season
- `.env.example` documents `INGEST_LIVE_POLL_INTERVAL` with a description

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/twitch.py` | Replace week-scoped match query with an ingested-series query; cap at 5 series |
| `backend/main.py` | Use `INGEST_LIVE_POLL_INTERVAL` in the ingest poll loop when an active week exists |
| `twitch-extension/live_config.js` | Update the "no matches found" empty-state message to remove week reference |
| `.env.example` | Add `INGEST_LIVE_POLL_INTERVAL` |

---

### Step 1 — Replace the week-scoped query in `GET /twitch/matches/current`

Current behaviour: finds the current or most-recently-locked week, then fetches matches
within that week's time window.

New behaviour: find all matches that have at least one `player_match_stats` row (i.e. data
has been ingested), started before `now`, within a rolling lookback window (default 30 days
or the entire match table if shorter). Group by team pair into series. Sort by most recent
match. Return the top 5 series.

Replace the week resolution + match query block with:

```python
now = int(time.time())
lookback = now - 30 * 86400  # 30-day rolling window

# Only matches that have started and have ingested stats
from sqlalchemy import exists
ingested_match_ids = [
    r.match_id
    for r in db.execute(
        text("SELECT DISTINCT match_id FROM player_match_stats")
    ).fetchall()
]
if not ingested_match_ids:
    return {"series": []}

matches = (
    db.query(Match)
    .filter(
        Match.match_id.in_(ingested_match_ids),
        Match.start_time <= now,
        Match.start_time >= lookback,
    )
    .order_by(Match.start_time)
    .all()
)
```

Group into series, build the response, sort by most-recent match, then slice to 5:

```python
result_series.sort(key=lambda s: s["matches"][-1]["start_time"] if s["matches"] else 0, reverse=True)
return {"series": result_series[:5]}
```

Remove the `week` key from the response (no longer meaningful). Update `live_config.js`
if it references `data.week`.

---

### Step 2 — Add `INGEST_LIVE_POLL_INTERVAL` to the ingest loop

In `backend/main.py`, read the new env var alongside the existing one:

```python
_INGEST_POLL_INTERVAL      = int(os.getenv("INGEST_POLL_INTERVAL",      "900"))
_INGEST_LIVE_POLL_INTERVAL = int(os.getenv("INGEST_LIVE_POLL_INTERVAL", "120"))
```

In `_ingest_poll_loop`, choose the interval based on whether an active week currently exists:

```python
def _ingest_poll_loop():
    while True:
        try:
            run_ingest()
        except Exception:
            logger.exception("Ingest poll failed")
        with SessionLocal() as db:
            now_ts = int(time.time())
            active = db.query(Week).filter(
                Week.start_time <= now_ts, Week.end_time >= now_ts
            ).first()
        interval = _INGEST_LIVE_POLL_INTERVAL if active else _INGEST_POLL_INTERVAL
        logger.info("Next ingest poll in %ds (live=%s)", interval, active is not None)
        time.sleep(interval)
```

---

### Step 3 — Update `.env.example`

Add after the `INGEST_POLL_INTERVAL` line:

```
# Seconds between ingest poll cycles during an active (unlocked) week. Default: 120 (2 min).
# Keeps MVP panel data fresh during live streams without churning the API off-season.
# INGEST_LIVE_POLL_INTERVAL=120
```

---

### Step 4 — Update extension empty-state copy

In `twitch-extension/live_config.js`, change the empty-state message from:

```js
container.innerHTML = '<p class="muted">No started matches found for the current week.</p>';
```

to:

```js
container.innerHTML = '<p class="muted">No recent matches with stats found. Check back after the next ingest cycle.</p>';
```

Also remove any reference to `data.week` in the series-loading callback if present.

---

## Verification

- With no ingested matches in the current week but ingested matches in a prior week:
  `GET /twitch/matches/current` returns those prior-week series
- With more than 5 qualifying series, exactly 5 are returned (most recent first)
- With 0 ingested matches anywhere, endpoint returns `{"series": []}`
- `INGEST_LIVE_POLL_INTERVAL=120` appears in server logs during an active week
- `INGEST_POLL_INTERVAL=900` is used when no active week exists
- Extension panel shows updated empty-state copy when no series are available
- Existing MVP selection flow (steps 1–3, confirm, token drop) is unaffected
