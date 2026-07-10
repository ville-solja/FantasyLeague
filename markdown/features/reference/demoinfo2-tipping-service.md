# Demoinfo2 Tipping Service

> **SHELVED (2026-07-08)** — Investigation confirmed that Dota 2 tip events are not
> recorded in `.dem` replay files. They go through the Steam Game Coordinator and are
> invisible to demo parsers. This feature cannot be built via demo parsing.
> See `markdown/plans/plan-demoinfo2-tipping-service.md` for full findings.

A proposed microservice that would download Dota 2 demo files from Valve's replay
servers, parse them using a Source 2 demo parser (`manta`), and extract in-game tip
events for a tipping leaderboard. **The approach was found to be infeasible.**

---

## Overview

In-game tips are not captured by the OpenDota API — they exist only in the match demo
file (`.dem.bz2`). The tipping service runs as a sidecar container alongside the main
backend. After each ingest cycle, the backend calls the service for any unanalyzed
matches; the service returns tip events and the backend stores them.

The service is optional: if `TIPPING_SERVICE_URL` is not configured, the analysis step
is silently skipped.

---

## Flow

```
Ingest cycle completes
    ↓
backend queries matches WHERE demo_analyzed = False
    ↓
for each match:
    POST /analyze/{match_id} → tipping service
        ↓
        service fetches replay_url from OpenDota
        downloads .dem.bz2 from Valve replay servers
        parses with demoinfo2/manta
        extracts tip events
        ↓
    returns { "events": [...] }
        ↓
    backend writes TipEvent rows, sets demo_analyzed = True
```

If the demo is expired (404) or the service is unavailable (503), `demo_analyzed` stays
`False` and the match is retried next cycle.

---

## Data Model *(planned)*

**`TipEvent`** table:

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | |
| `match_id` | Integer FK → matches | |
| `tipper_player_id` | Integer | OpenDota account ID of the tipper |
| `recipient_player_id` | Integer | OpenDota account ID of the recipient |
| `game_time` | Integer | Seconds into the match |
| `analyzed_at` | Integer | Unix timestamp when extracted |

**`Match.demo_analyzed`** (new column): Boolean, default False. Set to True once tip
events have been successfully extracted.

---

## Endpoints

### `POST /analyze/{match_id}` *(stub — tipping-service/main.py)*
Downloads and parses the demo for the given match. Returns extracted tip events.

```json
{
  "events": [
    { "tipper": 12345678, "recipient": 87654321, "game_time": 1820 }
  ]
}
```

Returns 404 if demo file is not found or has expired. Returns 503 if the parser fails.

### `GET /leaderboard/tipping` — `backend/routers/leaderboard.py`
Returns players ranked by tips received during the current season.

```json
[
  { "player_id": 12345678, "player_name": "SomePlayer", "tips_received": 14, "tips_sent": 3 }
]
```

---

## Prerequisites

Before implementation: confirm demo URL format and tip event accessibility by parsing a
real Kanaliiga demo file. See the investigation acceptance criteria in
`markdown/plans/plan-demoinfo2-tipping-service.md`.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TIPPING_SERVICE_URL` | *(empty)* | Base URL of the tipping microservice; if unset, tipping analysis is disabled |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
