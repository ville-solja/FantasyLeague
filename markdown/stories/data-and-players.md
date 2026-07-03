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

### Auto-ingest on Startup
**User story**
As an operator, I want the server to automatically fetch fresh match data when it starts so that the app stays up to date without manual intervention.

**Acceptance criteria**
- League IDs to ingest are configured via `AUTO_INGEST_LEAGUES` environment variable
- Ingestion runs in a background thread on startup; already-stored matches are skipped
- Setting `AUTO_INGEST_LEAGUES=` (empty) disables auto-ingest

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
