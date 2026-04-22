# 15. Player Profile Enrichment

### 15.1 View Player Bio in Detail Modal
**User story**
As a user, I want to see a short bio for each player in the player browser so that I can understand who they are beyond raw statistics.

**Acceptance criteria**
- Player detail modal shows a "Player Bio" section with a 2–4 sentence AI-generated excerpt
- Bio highlights at least two notable facts (e.g. signature hero, consecutive seasons, match count)
- Bio is displayed even if only partially enriched; section is hidden if the player has not been enriched yet
- Bio text is fetched lazily when the modal opens, not bulk-loaded with the player list

---

### 15.2 Automatic Profile Enrichment After Ingestion
**User story**
As an operator, I want player profiles to be enriched automatically after match ingestion so that bios stay current without manual intervention.

**Acceptance criteria**
- Enrichment pass runs after every successful ingestion batch
- For each player with an `opendota_id`: fetches top heroes from OpenDota, counts local matches and distinct Kanaliiga seasons
- Facts and generated bio are stored in a `player_profile` table keyed by player ID
- LLM call is skipped for players whose facts have not changed since the last enrichment (24-hour cooldown)

---

### 15.3 Admin Manual Re-enrichment Trigger
**User story**
As an admin, I want to trigger a full profile enrichment pass from the admin tab so that I can refresh bios after changing the AI prompt or onboarding new players.

**Acceptance criteria**
- Admin tab has a "Re-enrich profiles" button that calls `POST /admin/enrich-profiles`
- Response reports number of players enriched and number of errors
- Action is logged in the audit log
