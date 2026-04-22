# 7. Dota Data Integration

### 7.1 Fetch Player Data
**Acceptance criteria**
- Player names and avatar images fetched from OpenDota after ingestion
- Missing or unknown players are handled gracefully

---

### 7.2 Import Match Data
**Acceptance criteria**
- Match data (kills, assists, deaths, GPM, wards, tower damage) fetched per player per match
- Fantasy points calculated and stored per player-match record

---

### 7.3 Handle API Failures
**Acceptance criteria**
- API failures are logged
- Partial ingestion does not corrupt existing data
- Admin can re-trigger ingestion to recover

---

### 7.4 Auto-ingest on Startup
**User story**
As an operator, I want the server to automatically fetch fresh match data when it starts so that the app stays up to date without manual intervention.

**Acceptance criteria**
- League IDs to ingest are configured via `AUTO_INGEST_LEAGUES` environment variable
- Ingestion runs in a background thread on startup; already-stored matches are skipped
- Setting `AUTO_INGEST_LEAGUES=` (empty) disables auto-ingest
