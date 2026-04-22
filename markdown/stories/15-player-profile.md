# 15. Player Profile Enrichment

### 15.1 View Player Stats and Bio in Detail Modal
**User story**
As a user, I want to see key performance stats and an optional AI bio for each player in the player browser so I can understand who they are beyond raw match scores.

**Acceptance criteria**
- Player detail modal shows: Kanaliiga match count, seasons, avg fantasy points, avg K/D/A, avg GPM, avg wards/match, best match score, role tendency
- Hero section shows: top pub/career heroes (up to full pool), tournament heroes played, and ban correlation — which of the player's common heroes were targeted in their matches
- AI bio (2–4 sentences) appears if generated; section hidden entirely if no profile exists
- Stats block visible even when `ANTHROPIC_API_KEY` is unset (bio omitted)
- Fetched lazily via `GET /players/{id}/profile` when the modal opens

---

### 15.2 Automatic Background Profile Enrichment
**User story**
As an operator, I want player profiles to be enriched automatically in the background so hero stats, bans, and bios stay current without manual intervention or app performance impact.

**Acceptance criteria**
- A dedicated background loop (independent of ingest) runs every `ENRICHMENT_CHECK_INTERVAL` seconds (default 300)
- Each cycle processes up to `ENRICHMENT_BATCH_SIZE` players (default 3) whose `facts_fetched_at` is null or older than `PROFILE_ENRICHMENT_COOLDOWN_HOURS`
- Facts phase runs first (API calls + local queries); bio phase only if facts succeed and `ANTHROPIC_API_KEY` is set
- On restart, loop resumes from un-enriched players (fully resumable)
- Players with no ingested matches are skipped

---

### 15.3 Admin Manual Re-enrichment Trigger
**User story**
As an admin, I want to trigger a full profile enrichment pass from the admin tab so I can refresh bios after changing the AI prompt or onboarding new players.

**Acceptance criteria**
- Admin tab "Re-enrich profiles" button calls `POST /admin/enrich-profiles`
- Response: `{"enriched": N, "skipped": M, "errors": K}`
- Logged to audit log as `admin_enrich_profiles`
