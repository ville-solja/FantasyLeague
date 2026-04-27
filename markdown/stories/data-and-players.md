# Data and Players

## Dota Data Integration

### Fetch Player Data
**Acceptance criteria**
- Player names and avatar images fetched from OpenDota after ingestion
- Missing or unknown players are handled gracefully

---

### Import Match Data
**Acceptance criteria**
- Match data (kills, assists, deaths, GPM, wards, tower damage) fetched per player per match
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
- Player detail modal shows: Kanaliiga match count, avg fantasy points, avg K/D/A, avg GPM, avg wards/match, best match score
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
