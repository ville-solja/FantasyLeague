# Tipping

> **Shelved (2026-07-08):** Investigation found that Dota 2 tip events are not present
> in `.dem` replay files. Stories below are kept for historical reference only.

## Demoinfo2 Tipping Service

### Feasibility Investigation *(prerequisite — must complete before implementation)*
**User story**
As a developer, I want to evaluate `demoinfo2` (or an equivalent Dota 2 demo parser) for
extracting tip events so that I can determine whether this approach is viable before
committing to implementation.

**Acceptance criteria**
- Demo file URL format is confirmed; `cluster` and `replay_salt` fields are confirmed
  available from OpenDota `GET /matches/{match_id}`
- A test parse of one demo file produces at least one recognisable tip event, confirming
  the parser can find the right event type in the Source 2 replay format
- Demo file size and download time are documented (typical sizes 100–500 MB)
- A decision is recorded: Go microservice using `manta` or `demoinfo2`, Python CLI
  wrapper, or another approach

### Demo Tip Event Extraction
**User story**
As an operator, I want the system to automatically extract in-game tip events from Dota 2
demo files after each match is ingested, so that tipping activity is captured without
manual work.

**Acceptance criteria**
- After a new match is ingested, the tipping service is invoked in the background with
  the match ID
- The service downloads the demo file, parses tip events, and returns them to the main app
- Tip events are stored as `(match_id, tipper_player_id, recipient_player_id, game_time)`
- Matches that have been demo-analyzed are flagged so they are not reprocessed
- If the demo file is unavailable (expired, not yet uploaded), the match is skipped
  gracefully and retried on the next cycle
- If the tipping service is offline or returns an error, ingest continues normally

### Tipping Leaderboard
**User story**
As a user, I want to view a tipping leaderboard showing tips sent and received per player
during the season, so that generous or well-regarded players are recognised.

**Acceptance criteria**
- A leaderboard view shows players ranked by tips received, with a secondary column for
  tips sent
- The leaderboard is scoped to the current season's match data
- Only players with at least one tip event appear
- The leaderboard updates as new matches are analyzed
