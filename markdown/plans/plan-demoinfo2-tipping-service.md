# Plan: Demoinfo2 Tipping Service

> **STATUS: CLOSED — NOT VIABLE**
> Investigation completed 2026-07-08. Tip events are not recorded in Dota 2 `.dem` replay
> files. They are delivered via the Steam Game Coordinator (shard economy layer) and do
> not appear in the replay stream. Demo parsing cannot capture them. The tipping leaderboard
> feature cannot be built via this approach. See Investigation Findings below.

## Context
In-game tips (players tipping other players during a Dota 2 match) are not captured by
the OpenDota API — they exist only in the match demo file. Extracting them requires
downloading the `.dem.bz2` replay from Valve's servers and parsing it with a demo parser
such as `demoinfo2` or `manta` (Go libraries for the Source 2 demo format). The proposal
is a separate microservice that receives a match ID after ingest, downloads and parses the
demo, extracts tip events, and returns them to the Fantasy League backend. This plan
covers the investigation phase and, if feasible, the design of the microservice and its
integration. The feature eventually powers a tipping leaderboard and may feed into
scoring. Processing delays are acceptable — this is a background service. *Resolves
GitHub issue #68.*

## Investigation Findings (2026-07-08)

**Result: not viable via demo parsing.**

### What was tested
- manta v1.5.0 (Go, Source 2 demo parser) was used to parse `.dem.bz2` replay files
- Match 8878904467 confirmed: `replay_url`, `cluster`, and `replay_salt` are present in
  the OpenDota API response. Demo URL pattern:
  `http://replay{cluster}.valve.net/570/{match_id}_{replay_salt}.dem.bz2`
- The `CDOTAUserMsg_TipAlert` message type exists in the manta proto definitions
  (fields: `PlayerId int32`, `TipText string`) and manta exposes
  `p.Callbacks.OnCDOTAUserMsg_TipAlert(...)` correctly
- Multiple demos were parsed — both public matchmaking and Kanaliiga private lobby
  matches — across matches known to contain trash talk and high engagement

### Result
Zero tip events found across all tested demos. The `CDOTAUserMsg_TipAlert` callback
never fires. Tips are processed by the **Steam Game Coordinator** (the same layer that
handles shard grants, item gifting, and cosmetic transactions) and are not written into
the `.dem` replay stream. No demo parser can extract them.

### Conclusion
The demo-parsing approach is infeasible. No viable alternative has been identified:
the Steam Web API has no public endpoint for tip history, and Valve does not expose GC
transaction logs. The tipping leaderboard feature is shelved unless Valve adds tip
data to the OpenDota API or publishes a GC query endpoint.

## User Stories

### Demo Tip Event Extraction
**User story**
As an operator, I want the system to automatically extract in-game tip events from Dota 2
demo files after each match is ingested, so that tipping activity is captured without
manual work.

**Acceptance criteria**
- After a new match is ingested, the tipping service is invoked in the background with
  the match ID
- The service downloads the demo file, parses tip events, and returns them to the main
  app
- Tip events are stored as `(match_id, tipper_player_id, recipient_player_id, game_time)`
- Matches that have been demo-analyzed are flagged so they are not reprocessed
- If the demo file is unavailable (expired, not yet uploaded), the match is skipped
  gracefully and retried on the next cycle
- If the tipping service is offline or returns an error, ingest continues normally and
  the match is queued for retry

### Tipping Leaderboard
**User story**
As a user, I want to view a tipping leaderboard showing tips sent and received per player
during the season, so that generous or well-regarded players are recognised.

**Acceptance criteria**
- A leaderboard view (new tab or section) shows players ranked by tips received, with a
  secondary column for tips sent
- The leaderboard is scoped to the current season's match data
- Only players with at least one tip event appear on the leaderboard
- The leaderboard updates as new matches are analyzed

### Feasibility Investigation *(prerequisite — must complete before implementation)*
**User story**
As a developer, I want to evaluate `demoinfo2` (or an equivalent Dota 2 demo parser) for
extracting tip events so that I can determine whether this approach is viable before
committing to implementation.

**Acceptance criteria**
- Demo file URL format is confirmed (`http://replay{cluster}.valve.net/570/{match_id}_{salt}.dem.bz2`);
  the `cluster` and `replay_salt` fields are confirmed available from OpenDota `GET /matches/{match_id}`
- A test parse of one demo file produces at least one recognisable tip event, confirming
  the parser can find the right event type in the Source 2 replay format
- Demo file size and download time are documented (typical sizes range 100–500 MB;
  latency implications for the background service are noted)
- A decision is recorded: Go microservice using `manta` or `demoinfo2`, Python wrapper
  calling a CLI binary, or another approach

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | Add `TipEvent` model; add `demo_analyzed` boolean to `Match` |
| `backend/migrate.py` | Migration for `tip_events` table and `matches.demo_analyzed` column |
| `backend/routers/leaderboard.py` | Add `GET /leaderboard/tipping` endpoint |
| `backend/main.py` | Call tipping service after each ingest cycle (background) |
| `tipping-service/` | New directory — separate microservice (Go or Python) |
| `.env.example` | Add `TIPPING_SERVICE_URL` env var |

### Step 1 — Investigation (prerequisite)

Before writing any code, confirm:

1. **Demo URL availability**: Call `GET https://api.opendota.com/api/matches/{match_id}`
   on a known recent Kanaliiga match. Confirm `replay_url` or `cluster` + `replay_salt`
   fields are present. The demo download URL pattern is:
   ```
   http://replay{cluster}.valve.net/570/{match_id}_{replay_salt}.dem.bz2
   ```

2. **Parser selection**: Evaluate options:
   - [`manta`](https://github.com/dotabuff/manta) — Go library, actively maintained for Source 2
   - [`demoinfo2`](https://github.com/ValveSoftware/demoinfo2) — Valve's own CLI tool
   - Python: no mature Source 2 parser exists; wrapping a Go CLI is the realistic Python path

3. **Tip event identification**: Parse one demo and locate the tip event type in the
   event stream. The Source 2 event is likely `CDOTAUserMsg_ChatEvent` with type
   `CHAT_MESSAGE_GLYPH_USED` or a dedicated tip message — confirm the exact event name.

4. **Demo file age**: Confirm how long Valve keeps demo files available (typically ~10
   days after the match). This determines the replay window for the background service.

### Step 2 — Data model

Add to `backend/models.py`:

```python
class TipEvent(Base):
    __tablename__ = "tip_events"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    match_id            = Column(Integer, ForeignKey("matches.match_id"), nullable=False)
    tipper_player_id    = Column(Integer, nullable=False)   # OpenDota account_id
    recipient_player_id = Column(Integer, nullable=False)   # OpenDota account_id
    game_time           = Column(Integer)                   # seconds into the match
    analyzed_at         = Column(Integer)                   # unix timestamp
```

Add to `Match`:
```python
demo_analyzed = Column(Boolean, default=False, nullable=False)
```

Add migration `019_tip_events` to `backend/migrate.py`:
- `ALTER TABLE matches ADD COLUMN demo_analyzed BOOLEAN DEFAULT 0`
- `CREATE TABLE tip_events (...)`

### Step 3 — Tipping microservice

Create `tipping-service/` in the repo root. The service exposes one endpoint:

```
POST /analyze/{match_id}
  → downloads demo, parses tip events
  → returns: { "events": [{ "tipper": int, "recipient": int, "game_time": int }] }
  → returns 404 if demo file not found / expired
  → returns 503 if parser fails
```

The microservice is added to `docker-compose.yml` as a second service alongside `backend`.
It only needs outbound internet access (to download demos from Valve).

### Step 4 — Integration with ingest

In `backend/main.py`, after each ingest cycle completes, query for matches where
`demo_analyzed = False` and call `POST /analyze/{match_id}` on the tipping service for
each. On success, store returned tip events and set `demo_analyzed = True`. On 404 or
503, leave `demo_analyzed = False` for retry next cycle.

Configure the tipping service URL via `TIPPING_SERVICE_URL` env var; if unset, skip the
analysis step silently (allows running without the microservice).

### Step 5 — Tipping leaderboard endpoint

Add `GET /leaderboard/tipping` to `backend/routers/leaderboard.py`:

```python
# Returns top players by tips received, with tips_sent as a secondary column
# Scope: current season (matches within SEASON_LOCK_START window)
# Response: [{ "player_id": int, "player_name": str, "tips_received": int, "tips_sent": int }]
```

---

## Verification
- Run `GET /matches/{id}` on a recent match via OpenDota; confirm `replay_url` or
  `cluster`/`replay_salt` are present
- Download one demo file manually; run the parser CLI; confirm tip events appear in output
- Ingest a match; call the tipping service endpoint manually; confirm tip events are
  stored and `demo_analyzed` flips to `True`
- Ingest a match whose demo has expired; confirm the match is skipped and ingest
  continues normally
- Call `GET /leaderboard/tipping`; confirm output is ordered by `tips_received` descending
- Restart the tipping service mid-cycle; confirm ingest loop logs the error and continues
