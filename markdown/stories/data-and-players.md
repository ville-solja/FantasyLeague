# Data and Players

## Dota Data Integration

### Fetch Player Data
**Acceptance criteria**
- Player names and avatar images fetched from OpenDota after ingestion
- Missing or unknown players are handled gracefully

---

### Import Match Data
**Acceptance criteria**
- Match data fetched per player per match includes the full stored stat set used by the app (core box-score fields like kills/assists/deaths/GPM plus expanded stats like last hits/denies/towers/Roshan/teamfight participation/camps stacked/runes/first blood/stuns, plus observer/sentry wards placed and tower damage where available)
- Only the scoring stat subset participates in fantasy scoring; non-scoring stored fields (e.g. assists, sentry wards, tower damage) are retained for display/profile context but do not contribute points
- Fantasy points calculated and stored per player-match record

---

### Handle API Failures
**Acceptance criteria**
- API failures are logged
- Partial ingestion does not corrupt existing data
- Admin can re-trigger ingestion to recover

---

### Auto-ingest Monitored Leagues
**User story**
As an operator, I want the server to automatically fetch fresh match data for admin-selected leagues so that the app stays up to date without manual intervention.

**Acceptance criteria**
- League IDs to ingest are managed at runtime via the admin League Management panel (`is_monitored` flag), not an environment variable
- Ingestion runs in a background thread on a recurring interval; already-stored matches are skipped
- A fresh instance with no leagues marked monitored performs no automatic ingestion

---

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

## Player Profiles

### View Player Stats and Bio
**User story**
As a user, I want to see key performance stats and an optional AI bio for each player in the player browser so I can understand who they are beyond raw match scores.

**Acceptance criteria**
- Player detail modal shows: Kanaliiga match count, avg fantasy points, avg K/D/A, avg GPM, avg wards/match (profile/enrichment context), best match score
- Match history table shows fantasy points, K/A/D, and GPM (not every stored raw stat column)
- Hero section shows top career heroes, tournament heroes played, and recent pub heroes (up to 5 per category)
- AI bio appears if generated; section hidden entirely if no profile exists
- Stats block visible even when `ANTHROPIC_API_KEY` is unset (bio omitted)
- Fetched lazily via `GET /players/{id}/profile` when the modal opens

---

### Automatic Background Enrichment
**User story**
As an operator, I want player profiles to be enriched automatically in the background so hero stats and bios stay current without manual intervention.

**Acceptance criteria**
- A dedicated background loop runs every `ENRICHMENT_CHECK_INTERVAL` seconds (default 300)
- Each cycle processes up to `ENRICHMENT_BATCH_SIZE` players (default 3) whose facts are null or stale
- Facts phase runs first; bio phase only if facts succeed and `ANTHROPIC_API_KEY` is set
- On restart, loop resumes from un-enriched players (fully resumable)
- Players with no ingested matches are skipped

---

### Admin Manual Re-enrichment
**User story**
As an admin, I want to trigger a full profile enrichment pass from the admin tab so I can refresh bios after changing the AI prompt or onboarding new players.

**Acceptance criteria**
- Admin tab "Re-enrich profiles" button calls `POST /admin/enrich-profiles`
- Response: `{"enriched": N, "skipped": M, "errors": K}`
- Logged to audit log

---

## Monitored Leagues Admin Panel

### View Monitored Leagues
**User story**
As an admin, I want to see a list of leagues currently being auto-ingested so that I can verify the correct leagues are configured without reading environment variables.

**Acceptance criteria**
- The admin tab contains a "League Management" panel listing all leagues known to the database
- Each row shows: league ID, league name, match count, and whether the league is currently monitored
- The list refreshes when the Refresh button is clicked

### Add or Remove a League from Monitoring
**User story**
As an admin, I want to add or remove a league from the monitored set at runtime so that I can fix a configuration mistake without restarting the service.

**Acceptance criteria**
- An "Add" flow lets the admin enter an OpenDota league ID and marks it as monitored; the next poll cycle will ingest it
- A "Remove" button on each monitored league unsets the monitored flag; future poll cycles will not ingest it
- Adding a league that is already monitored returns a clear error
- Removing a league does not delete its existing match data — it only stops future polling

### Purge Wrongly Ingested League Data
**User story**
As an admin, I want to purge all match data ingested for a specific league so that I can roll back an accidental ingest of the wrong league.

**Acceptance criteria**
- A "Purge data" action is available for any league that has match data in the database
- The purge deletes all `player_match_stats`, `match_bans`, and `matches` rows for that league and sets `is_monitored = False`
- The purge does NOT delete player records (they may appear in other leagues)
- The purge returns counts of deleted rows so the admin can confirm scope
- After purge, the admin is reminded to use the existing Recalculate endpoint to refresh fantasy scores
- A confirmation modal is shown before the purge executes

---

## OpenDota Parse Retry

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
- The re-check step submits a parse request for any match that is still unparsed and has not
  been requested within the last `INGEST_PARSE_REREQUEST_HOURS` (default `6`); a match is
  requested at most once per cooldown so a parse job OpenDota dropped (replay unavailable) is
  retried without a restart
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

---

## Unparseable Match Handling

### See When a Match Score Is Partial
**User story**
As a fantasy player, I want matches with incomplete stats to be marked so that I don't mistake a missing replay for a bad performance.

**Acceptance criteria**
- A player's match history, in the player popup, shows a "Partial stats" marker on every match the app considers unparsed
- The marker's tooltip says the replay has not been parsed, so wards, stuns, teamfight, runes and camps count as 0
- A match marked excluded from scoring shows "Not scored" instead, and its points display as a dash
- Parsed matches show no marker


---

### Track Parse Status in the Admin Match Table
**User story**
As an admin, I want to see each match's parse status and retry a parse on demand so that I can fix partial scores without waiting for the background pass.

**Acceptance criteria**
- The admin Matches table has a Parse column showing Parsed, Unparsed, or Unparseable
- Each unparsed match has a "Retry parse" button that calls `POST /admin/matches/{match_id}/retry-parse`
- Retry re-fetches the match from OpenDota. If it is now parsed, its stat rows and fantasy points are replaced, as the background pass does. If not, a parse is requested from OpenDota, subject to the existing re-request cooldown
- The response says what happened: `refreshed` (now parsed, stats replaced), `requested` (parse requested), `cooldown` (a request was sent too recently, none sent) or `request_failed` (OpenDota rejected the request). The table refreshes
- Each retry is written to the audit log as `admin_match_retry_parse`
- The endpoint is admin-only and returns 404 for an unknown match


---

### Mark a Match Unparseable and Choose How It Scores
**User story**
As an admin, I want to mark a match as unparseable and decide whether it still counts, so that one lost replay does not unfairly sink ten players' fantasy points.

**Acceptance criteria**
- `PATCH /admin/matches/{match_id}/scoring` accepts `{"unparseable": bool, "excluded_from_scoring": bool}` and is admin-only
- A match marked unparseable is skipped by the background parse-retry pass, which never requests a parse for it again. An admin can still request one with Retry parse
- A match excluded from scoring contributes nothing to weekly and season leaderboards, the roster leaderboard, card points in rosters, or the weekly summary's points
- An excluded match still appears in schedules, match lists and player match history, labelled "Not scored"
- Clearing either flag restores normal behaviour, and the parse retry picks the match up again if it is still unparsed. A match older than the retry window that is still unparsed is flagged unparseable again on the next pass
- Every change is written to the audit log as `admin_match_scoring` with the old and new values


---

### Flag Stuck Matches Automatically
**User story**
As an admin, I want matches that stay unparsed after repeated parse requests to be flagged for me, so that I notice lost replays without checking each match by hand.

**Acceptance criteria**
- When the parse-retry pass finds a match still unparsed and older than `INGEST_PARSE_RETRY_HOURS`, it marks the match unparseable instead of dropping it silently
- Auto-marking never sets `excluded_from_scoring`. That stays an admin decision
- The auto-mark is written to the audit log as `match_marked_unparseable` with the match ID
- The admin Matches table can filter to unparseable matches
