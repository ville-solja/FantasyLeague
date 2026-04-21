# Plan: Player Profile Enrichment (Enhanced)

## Context
This plan supersedes the original player profile enrichment plan. The original was
underspecified on which statistics to collect and how to schedule enrichment safely. This
revision extends ingest to capture hero picks and ban data that the OpenDota match
endpoint already returns (but currently discards), enabling richer cross-referencing at
zero additional API cost — for example, identifying that a player's most-played pub hero
is being systematically banned in their tournament matches. Bio generation and
fact-gathering are non-critical background work, independent of ingest and fully
resumable across restarts.

---

## User Stories (updates section 15 in-place)

### 15.1 View Player Stats and Bio in Detail Modal
**User story**
As a user, I want to see key performance stats and an optional AI bio for each player in
the player browser so I can understand who they are beyond raw match scores.

**Acceptance criteria**
- Player detail modal shows: Kanaliiga match count, seasons, avg fantasy points, avg K/D/A,
  avg GPM, avg wards/match, best match score, role tendency
- Hero section shows: top pub/career heroes (up to full pool), tournament heroes played,
  and ban correlation — which of the player's common heroes were targeted in their matches
- AI bio (2–4 sentences) appears if generated; section hidden entirely if no profile exists
- Stats block visible even when `ANTHROPIC_API_KEY` is unset (bio omitted)
- Fetched lazily via `GET /players/{id}/profile` when the modal opens

### 15.2 Automatic Background Profile Enrichment
**User story**
As an operator, I want player profiles to be enriched automatically in the background so
hero stats, bans, and bios stay current without manual intervention or app performance impact.

**Acceptance criteria**
- A dedicated background loop (independent of ingest) runs every `ENRICHMENT_CHECK_INTERVAL`
  seconds (default 300)
- Each cycle processes up to `ENRICHMENT_BATCH_SIZE` players (default 3) whose
  `facts_fetched_at` is null or older than `PROFILE_ENRICHMENT_COOLDOWN_HOURS`
- Facts phase runs first (API calls + local queries); bio phase only if facts succeed and
  `ANTHROPIC_API_KEY` is set
- On restart, loop resumes from un-enriched players (fully resumable)
- Players with no ingested matches are skipped

### 15.3 Admin Manual Re-enrichment Trigger
**User story**
As an admin, I want to trigger a full profile enrichment pass from the admin tab so I
can refresh bios after changing the AI prompt or onboarding new players.

**Acceptance criteria**
- Admin tab "Re-enrich profiles" button calls `POST /admin/enrich-profiles`
- Response: `{"enriched": N, "skipped": M, "errors": K}`
- Logged to audit log as `admin_enrich_profiles`

---

## Statistics to Collect

### From local DB (zero API cost — expanded ingest fields)

Two new fields are added to ingest and stored at match time:
- `PlayerMatchStats.hero_id` — extracted from the `hero_id` field already present in
  each player object in the OpenDota `GET /api/matches/{match_id}` response
- `MatchBan.hero_id` — extracted from `picks_bans` entries where `is_pick == false` in
  the same match response; stored in a new `match_bans` table

All of this data is already returned by the match fetch during ingest — no additional
API calls are needed; only extraction and storage are added.

| Stat | `facts_json` key | Source |
|---|---|---|
| Total Kanaliiga matches | `kanaliiga_matches` | COUNT distinct match_id in PlayerMatchStats |
| Distinct seasons | `kanaliiga_seasons` | COUNT distinct league_id in PlayerMatchStats |
| Avg fantasy pts | `avg_fantasy_points` | AVG fantasy_points |
| Avg kills | `avg_kills` | AVG kills |
| Avg assists | `avg_assists` | AVG assists |
| Avg deaths | `avg_deaths` | AVG deaths |
| Avg GPM | `avg_gpm` | AVG gold_per_min |
| Avg wards | `avg_wards` | AVG (obs_placed + sen_placed) |
| Best match score | `best_match_points` | MAX fantasy_points |
| Role tendency | `role_tendency` | `"support"` if avg_wards ≥ 3 AND avg_gpm < 450, else `"core"` |
| Tournament heroes played | `tournament_heroes` | COUNT hero_id per player from PlayerMatchStats |
| Ban correlations | `ban_correlations` | Cross-reference: player's top pub heroes that also appear in MatchBan for their tournament matches |

### From OpenDota API (2 calls per player + 1 shared constants call per run)

| Stat | `facts_json` key | Endpoint |
|---|---|---|
| Full career hero pool (all heroes, sorted by games desc) | `top_heroes_alltime` | `GET /api/players/{id}/heroes` |
| Recent pub heroes — last 100 matches | `recent_pub_heroes` | `GET /api/players/{id}/matches?limit=100&project=hero_id` |

Hero IDs are resolved to names via `GET /api/constants/heroes` fetched **once per run**
and cached in memory. Per-player API cost: **2 calls**. Players with private profiles
store empty lists rather than failing enrichment.

### Facts JSON shape

```json
{
  "kanaliiga_matches": 47,
  "kanaliiga_seasons": 3,
  "avg_fantasy_points": 12.4,
  "avg_kills": 5.2,
  "avg_assists": 8.1,
  "avg_deaths": 3.4,
  "avg_gpm": 512.3,
  "avg_wards": 4.2,
  "best_match_points": 34.5,
  "role_tendency": "support",
  "top_heroes_alltime": [
    {"hero_name": "Crystal Maiden", "games": 512, "win_rate": 0.54},
    {"hero_name": "Rubick", "games": 380, "win_rate": 0.51}
  ],
  "tournament_heroes": [
    {"hero_name": "Crystal Maiden", "games": 14},
    {"hero_name": "Lion", "games": 9}
  ],
  "recent_pub_heroes": [
    {"hero_name": "Crystal Maiden", "games": 18},
    {"hero_name": "Oracle", "games": 12}
  ],
  "ban_correlations": [
    {
      "hero_name": "Crystal Maiden",
      "pub_games": 512,
      "tournament_match_count": 12,
      "banned_in": 8,
      "ban_rate": 0.67
    }
  ]
}
```

`ban_correlations` lists the player's most-played pub/career heroes that also appear as
bans in their tournament matches, sorted by `ban_rate` descending. An entry with
`ban_rate: 0.67` means that hero was banned in 67 % of the player's tournament games —
the key signal for the AI bio and for user-facing display.

The bio prompt receives: performance summary, top 5 all-time heroes, top 3 tournament
heroes, top 3 recent pub heroes, top 3 ban correlations. The AI can reason: *"Crystal
Maiden was banned in 67 % of their tournament matches this season, suggesting opponents
are specifically targeting their signature hero."*

---

## Rate Limit Budget

Assuming 40-player roster:

| Event | API calls |
|---|---|
| Initial enrichment | 40 × 2 (heroes + recent matches) + 1 (constants) = **81 calls** |
| Daily re-enrichment (24 h cooldown, batch 3, cycle 5 min) | max **80 calls/day** |
| Ingest hero_id + ban extraction | **0 extra** (data already in match response) |

OpenDota free-tier limit ~50,000 calls/day. This uses < 0.2 % of that budget at peak.
A 0.5 s inter-call sleep is added inside the batch loop as courtesy throttling.

---

## Anthropic API Cost Estimate

Model: `claude-haiku-4-5-20251001`
Pricing (2025): ~$0.80 / MTok input, ~$4.00 / MTok output

Per bio generation: ~500 input tokens, ~150 output tokens

| Scenario | Input | Output | Cost |
|---|---|---|---|
| Initial season (40 players) | 20 K tok | 6 K tok | **~$0.04** |
| Weekly re-enrichment × 52 weeks | 1.04 M tok | 0.31 M tok | **~$2.07/year** |

Effectively zero cost at this scale. Bio generation is skipped entirely when
`ANTHROPIC_API_KEY` is unset — feature runs cost-free by default.

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `hero_id` to `PlayerMatchStats`; add `MatchBan` model; add `PlayerProfile` model |
| `backend/ingest.py` | Extract and store `hero_id` per player and bans per match during ingestion |
| `backend/enrich.py` | Add `crawl_player_facts()`, `generate_player_bio()`, `run_profile_enrichment()` |
| `backend/main.py` | Add `GET /players/{id}/profile`, `POST /admin/enrich-profiles`, start background loop |
| `frontend/app.js` | Lazy-load profile in player modal; render stats, hero lists, ban correlations, bio |
| `frontend/index.html` | Add profile section HTML to player detail modal |
| `.env.example` | Add `ENRICHMENT_CHECK_INTERVAL`, `ENRICHMENT_BATCH_SIZE` |

`ANTHROPIC_API_KEY` and `PROFILE_ENRICHMENT_COOLDOWN_HOURS` already in `.env.example`.

### Step 1 — Model additions (`backend/models.py`)

Add `hero_id` to `PlayerMatchStats`:
```python
hero_id = Column(Integer, nullable=True)  # null for pre-migration rows
```

New `MatchBan` model:
```python
class MatchBan(Base):
    __tablename__ = "match_bans"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.match_id"))
    hero_id  = Column(Integer)
```

New `PlayerProfile` model:
```python
class PlayerProfile(Base):
    __tablename__ = "player_profiles"
    player_id        = Column(Integer, ForeignKey("players.id"), primary_key=True)
    facts_json       = Column(String, nullable=True)
    bio_text         = Column(String, nullable=True)
    facts_fetched_at = Column(Integer, nullable=True)  # Unix timestamp
    bio_generated_at = Column(Integer, nullable=True)  # Unix timestamp
```

SQLite `create_all()` on startup handles new tables and the new column for existing databases.

### Step 2 — Ingest changes (`backend/ingest.py`)

In the per-player extraction block, add:
```python
hero_id = p.get("hero_id")  # already present in match player objects
```

After storing all `PlayerMatchStats` for a match, extract bans and store them
(idempotent — skip if `match_bans` already has rows for this `match_id`):
```python
for pb in match_data.get("picks_bans", []):
    if not pb.get("is_pick"):
        db.merge(MatchBan(match_id=match_id, hero_id=pb["hero_id"]))
```

### Step 3 — `crawl_player_facts()` in `backend/enrich.py`

```python
def crawl_player_facts(player_id, hero_name_map, db):
    # 1. Local aggregates from PlayerMatchStats (no API call)
    # 2. Tournament heroes: GROUP BY hero_id from PlayerMatchStats for this player
    # 3. Ban correlations:
    #    a. Get match_ids for player (from PlayerMatchStats)
    #    b. Query MatchBan for those match_ids → count by hero_id
    #    c. Cross-reference with player's pub hero pool to compute ban_rate
    # 4. GET /api/players/{player_id}/heroes → full career hero pool
    # 5. GET /api/players/{player_id}/matches?limit=100&project=hero_id → recent pubs
    # 6. Resolve hero_ids to names via hero_name_map
    # 7. Return facts dict, or None on failure
```

### Step 4 — `generate_player_bio()` in `backend/enrich.py`

Uses `anthropic` Python SDK (claude-haiku-4-5-20251001). Prompt provides:
- Performance summary (matches, seasons, avg pts, K/D/A, GPM, wards, role)
- Top 5 career heroes with win rate
- Top 3 tournament heroes
- Top 3 recent pub heroes
- Top 3 ban correlations (hero, pub_games, ban_rate in tournament matches)

Returns a 2–4 sentence bio string, or `None` if key unset or API error.

### Step 5 — `run_profile_enrichment(batch_size)` in `backend/enrich.py`

```python
def run_profile_enrichment(batch_size=3):
    # 1. Fetch hero_name_map from GET /api/constants/heroes (1 shared call)
    # 2. Query players needing enrichment (null/stale facts_fetched_at, has ≥1 match)
    # 3. For each player (up to batch_size):
    #    a. crawl_player_facts() → upsert facts_json + facts_fetched_at
    #    b. generate_player_bio() → upsert bio_text + bio_generated_at (if key set)
    #    c. sleep(0.5) between players
    # Returns {"enriched": N, "skipped": M, "errors": K}
```

### Step 6 — Background loop in `backend/main.py`

Mirror the existing `_week_check_loop` daemon thread pattern. Loop sleeps
`ENRICHMENT_CHECK_INTERVAL` seconds (default 300) between cycles.

### Step 7 — API endpoints in `backend/main.py`

`GET /players/{player_id}/profile` — no auth:
- 404 if no `PlayerProfile` row
- Returns full facts dict + `bio_text` + timestamps

`POST /admin/enrich-profiles` — admin only:
- Calls `run_profile_enrichment()` synchronously
- Returns count dict + audit log entry (`admin_enrich_profiles`)

### Step 8 — Frontend

`frontend/index.html`: add `#playerProfile` section inside player detail modal (hidden by default).

`frontend/app.js`: on modal open, `GET /players/{id}/profile`. If found:
- Render performance stats grid
- Render hero lists (career top, tournament, recent pubs — collapsible)
- Render ban correlations as highlighted callouts (e.g. "Crystal Maiden — banned in 67 % of tournament matches")
- Render bio paragraph if present

---

## Verification

- After startup confirm enrichment loop thread starts in server log
- After first cycle confirm `player_profiles` rows have `facts_fetched_at` and all
  expected `facts_json` keys (including `tournament_heroes`, `ban_correlations`)
- Confirm `match_bans` table is populated after a fresh ingest
- Confirm `PlayerMatchStats.hero_id` is populated for newly ingested matches
- With `ANTHROPIC_API_KEY` unset: `bio_text` null, facts present
- With key set: `bio_text` populated after cycle
- `GET /players/{id}/profile` returns full facts and bio
- `POST /admin/enrich-profiles` returns count dict and audit log entry
- Player modal renders all sections correctly in browser
- Restart mid-enrichment confirms loop resumes un-enriched players
