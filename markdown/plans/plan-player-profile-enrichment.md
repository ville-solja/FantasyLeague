# Plan: Player Profile Enrichment

## Context
Currently all players look alike beyond raw fantasy stats — there is no narrative context to make one player stand out from another. This feature adds a two-phase pipeline: a fact-finder crawler that pulls structured data about each player (signature heroes, season count, match totals) from OpenDota and the local DB, and an LLM agent that turns those facts into a short human-readable bio. Bios are stored per player and surfaced in the player detail modal so users can make more meaningful card choices. The AI bio generation requires `ANTHROPIC_API_KEY` to be set in the environment; this is noted as an assumed dependency since the project already uses the Claude agent system.

## User Stories

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

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | Add `PlayerProfile` model |
| `backend/enrich.py` | Add `crawl_player_facts()` and `generate_player_bio()` |
| `backend/migrate.py` | Add `player_profile` table migration |
| `backend/ingest.py` | Call enrichment pipeline after ingestion batch |
| `backend/main.py` | Add `GET /players/{player_id}/profile` and `POST /admin/enrich-profiles` |
| `frontend/app.js` | Fetch and render bio in the player detail modal |
| `.env.example` | Document `ANTHROPIC_API_KEY` and `PROFILE_ENRICHMENT_COOLDOWN_HOURS` |

### Step 1 — Add `PlayerProfile` model
Add a SQLAlchemy model to `backend/models.py`:

```python
class PlayerProfile(Base):
    __tablename__ = "player_profile"
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, nullable=False)
    facts_json = Column(Text, nullable=True)   # raw structured facts as JSON string
    bio_text = Column(Text, nullable=True)     # AI-generated excerpt
    enriched_at = Column(DateTime, nullable=True)
```

Add the corresponding `CREATE TABLE IF NOT EXISTS` block to `backend/migrate.py`.

### Step 2 — Implement the fact-finder crawler
Add `crawl_player_facts(opendota_id: int, db: Session) -> dict` to `backend/enrich.py`:

- Call `GET https://api.opendota.com/api/players/{opendota_id}/heroes` — pick top 5 heroes by `games` played, include hero name and game count.
- Query local DB for total ingested matches and distinct league/season groupings for this player.
- Return a structured dict:
  ```python
  {
      "top_heroes": [{"name": "Treant Protector", "games": 512}, ...],
      "total_matches": 47,
      "kanaliiga_seasons": 6,
      "opendota_id": 123456789,
  }
  ```
- On OpenDota HTTP error, return partial facts from local DB only (bio generation still proceeds).

### Step 3 — Implement AI bio generation
Add `generate_player_bio(facts: dict) -> str | None` to `backend/enrich.py`:

- Use the Anthropic Python SDK (`anthropic.Anthropic(api_key=...)`) with model `claude-haiku-4-5-20251001` (fast, low cost for batch runs).
- System prompt: *"You write short, punchy fantasy sports player bios. Given structured facts about a Dota 2 player, write 2–4 sentences in English that highlight the most interesting details. Focus on what makes this player memorable — avoid generic phrases."*
- User message: JSON dump of `facts`.
- Return the bio string, or `None` on API error (section hidden in frontend).

### Step 4 — Wire enrichment into ingest
In `backend/ingest.py`, after `ingest_match()` completes a batch, call `enrich_all_players(db)` which:
1. Queries all `Player` rows with a non-null `opendota_id`.
2. For each player, loads or creates their `PlayerProfile`.
3. Skips if `enriched_at` is within the cooldown window (`PROFILE_ENRICHMENT_COOLDOWN_HOURS`, default 24).
4. Calls `crawl_player_facts()` → `generate_player_bio()` → updates `PlayerProfile`.

Run enrichment in a background thread so it does not block the ingest response.

### Step 5 — Add API endpoints
In `backend/main.py`:

```python
@app.get("/players/{player_id}/profile")
def get_player_profile(player_id: int, db=Depends(get_db)):
    profile = db.query(PlayerProfile).filter_by(player_id=player_id).first()
    if not profile or not profile.bio_text:
        raise HTTPException(404, "Profile not enriched yet")
    return {"bio": profile.bio_text, "facts": json.loads(profile.facts_json or "{}")}

@app.post("/admin/enrich-profiles")
def admin_enrich_profiles(user=Depends(require_admin), db=Depends(get_db)):
    # trigger full pass synchronously (or fire background thread and return immediately)
    ...
```

### Step 6 — Update the player detail modal (frontend)
In `frontend/app.js`, in the function that opens the player detail modal, after setting the player name and avatar:

```javascript
fetch(`/players/${player.id}/profile`)
  .then(r => r.ok ? r.json() : null)
  .then(profile => {
    const bioSection = document.getElementById("playerBio");
    if (profile?.bio) {
      bioSection.textContent = profile.bio;
      bioSection.closest(".bio-wrapper").classList.remove("hidden");
    }
  });
```

Add a `<div class="bio-wrapper hidden"><p id="playerBio"></p></div>` block to the modal HTML in `frontend/index.html`.

---

## Verification
- After seeding and ingesting, call `POST /admin/enrich-profiles` and confirm `player_profile` rows are created.
- `GET /players/{id}/profile` returns non-empty `bio` for a player with an `opendota_id`.
- Open the player detail modal in the browser and confirm the bio section renders.
- Players without an `opendota_id` are skipped silently (no error row).
- Re-running enrichment within the cooldown window does not call the LLM again.
- If `ANTHROPIC_API_KEY` is unset, the crawler still stores `facts_json`; `bio_text` remains null and the frontend hides the section gracefully.
