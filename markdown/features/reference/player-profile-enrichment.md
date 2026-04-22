# Player Profile Enrichment

Player profile enrichment gives each league player structured performance facts and an optional AI-generated bio. Stats include hero pools, ban correlations, K/D/A, GPM, ward rate, and role tendency. The bio section appears in the player detail modal when available; the modal works normally when it is not.

---

## How it works

Enrichment runs as a two-phase pipeline in a dedicated background thread (independent of ingest), and can also be triggered manually from the admin tab.

1. **Fact crawler** — queries local DB for aggregate stats and tournament hero usage, queries `match_bans` for ban correlation analysis, then makes 2 OpenDota API calls per player (`/heroes` and `/matches?limit=100`). Hero IDs are resolved via a single shared `GET /constants/heroes` call per batch run.
2. **Bio generator** — sends structured facts to `claude-haiku-4-5-20251001`. Skipped entirely when `ANTHROPIC_API_KEY` is unset.

Facts and bio are stored in the `player_profiles` table. `facts_fetched_at` and `bio_generated_at` are tracked separately so facts can be refreshed without re-generating the bio.

---

## Data model

### `player_profiles`

| Field | Type | Description |
|---|---|---|
| `player_id` | FK → players.id (PK) | One profile per player |
| `facts_json` | TEXT | JSON blob — see schema below |
| `bio_text` | TEXT | AI-generated bio; null if not yet generated or API unavailable |
| `facts_fetched_at` | INTEGER | Unix timestamp of last facts crawl |
| `bio_generated_at` | INTEGER | Unix timestamp of last bio generation |

### `match_bans`

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `match_id` | FK → matches.match_id | The match this ban belongs to |
| `hero_id` | INTEGER | OpenDota hero ID of the banned hero |

### `player_match_stats.hero_id`

A `hero_id INTEGER` column was added to `player_match_stats` to record which hero each player picked in each ingested match. Pre-migration rows have `null`.

---

## `facts_json` schema

```json
{
  "kanaliiga_matches":   47,
  "kanaliiga_seasons":   3,
  "avg_fantasy_points":  12.4,
  "avg_kills":           5.2,
  "avg_assists":         8.1,
  "avg_deaths":          3.4,
  "avg_gpm":             512.3,
  "avg_wards":           4.2,
  "best_match_points":   34.5,
  "role_tendency":       "support",
  "top_heroes_alltime":  [{"hero_name": "Crystal Maiden", "games": 512, "win_rate": 0.54}],
  "tournament_heroes":   [{"hero_name": "Crystal Maiden", "games": 14}],
  "recent_pub_heroes":   [{"hero_name": "Crystal Maiden", "games": 18}],
  "ban_correlations": [
    {
      "hero_name":              "Crystal Maiden",
      "pub_games":              512,
      "tournament_match_count": 47,
      "banned_in":              31,
      "ban_rate":               0.66
    }
  ]
}
```

`role_tendency` is `"support"` when `avg_wards ≥ 3 AND avg_gpm < 450`, otherwise `"core"`.

`ban_correlations` lists heroes from the player's career pool that also appeared as bans in their tournament matches, sorted by `ban_rate` descending.

---

## Endpoints

### `GET /players/{player_id}/profile`

Returns the enriched profile for a player. No authentication required.

Returns `404` if the player has not been enriched yet.

**Response:**
```json
{
  "player_id":        40022324,
  "facts":            { ... },
  "bio_text":         "Known for her dominance on Crystal Maiden...",
  "facts_fetched_at": 1745000000,
  "bio_generated_at": 1745000005
}
```

`facts` is null if enrichment has not run. `bio_text` is null when `ANTHROPIC_API_KEY` is unset.

### `POST /admin/enrich-profiles`

Triggers a synchronous enrichment batch. Admin only. Logged to audit log as `admin_enrich_profiles`.

**Response:**
```json
{"enriched": 3, "skipped": 1, "errors": 0}
```

---

## Frontend integration

The player detail modal fetches `GET /players/{id}/profile` non-blocking when the modal opens. If a profile is found, an enriched section is rendered between the stats grid and the match history table, showing:

- Additional stat row (seasons, avg K/D/A, avg GPM, avg wards, role tendency)
- Career hero pool, tournament heroes, recent pub heroes
- Ban correlation callouts (highlighted in red, e.g. "Crystal Maiden — banned in 66% of tournament matches")
- AI bio paragraph (shown only if `bio_text` is present)

If the profile is unavailable (404 or network error), the modal shows normally with no profile section.

The admin tab has a "Re-enrich Player Profiles" button that calls `POST /admin/enrich-profiles`.

---

## Background loop

A daemon thread (`_profile_enrichment_loop`) runs independently of the ingest loop. Each cycle processes up to `ENRICHMENT_BATCH_SIZE` players whose `facts_fetched_at` is null or older than `PROFILE_ENRICHMENT_COOLDOWN_HOURS`. Players with no ingested matches are skipped. The loop is fully resumable across restarts.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(empty)* | Required for bio generation; if unset, facts are stored but bio is skipped |
| `PROFILE_ENRICHMENT_COOLDOWN_HOURS` | `24` | Minimum hours between re-enrichment for a given player |
| `ENRICHMENT_CHECK_INTERVAL` | `300` | Seconds between background enrichment cycles |
| `ENRICHMENT_BATCH_SIZE` | `3` | Players enriched per cycle |

---

## Rate limit budget

Assuming a 40-player roster:

| Event | API calls |
|---|---|
| Initial enrichment | 40 × 2 + 1 (constants) = **81 calls** |
| Daily re-enrichment (24 h cooldown, batch 3, cycle 5 min) | max **80 calls/day** |
| Ingest hero_id + ban extraction | **0 extra** (data already in match response) |

OpenDota free tier: ~50,000 calls/day. This uses < 0.2% at peak.
