# Player Profile Enrichment

Player profile enrichment gives each league player a short AI-generated bio that highlights memorable facts — signature heroes, seasons played, match volume — so users have meaningful context when browsing the player list and making card choices.

---

## How it works

Enrichment runs as a two-phase pipeline triggered automatically after each ingestion batch, and optionally via an admin action:

1. **Fact-finder crawler** — queries OpenDota for the player's most-played heroes and combines that with local DB data (total ingested matches, distinct Kanaliiga seasons).
2. **Bio generator** — sends the structured facts to a Claude model (Haiku) which produces a 2–4 sentence narrative excerpt.

Facts and bio are stored in the `player_profile` table and cached for a configurable cooldown period to avoid redundant LLM calls.

---

## Data model

| Field | Type | Description |
|---|---|---|
| `player_id` | FK → Player | One profile per player |
| `facts_json` | TEXT | Raw structured facts (top heroes, match count, seasons) |
| `bio_text` | TEXT | AI-generated bio; null if not yet enriched or API unavailable |
| `enriched_at` | DateTime | Timestamp of last enrichment run |

---

## Endpoints

> **Not yet implemented** — the enrichment pipeline (`backend/enrich.py`) is present but not exposed via API. The endpoints below are planned; run `/developer plan-player-profile-enrichment` to implement them.

### `GET /players/{player_id}/profile` *(not yet implemented)*
Returns the player's enriched profile.

**Response:**
```json
{
  "bio": "Known for his 500+ games on Treant Protector...",
  "facts": {
    "top_heroes": [{"name": "Treant Protector", "games": 512}],
    "total_matches": 47,
    "kanaliiga_seasons": 6
  }
}
```

Returns `404` if the player has not been enriched yet.

### `POST /admin/enrich-profiles` *(not yet implemented)*
Triggers a full enrichment pass for all players with a linked `opendota_id`. Admin only.

**Response:**
```json
{"enriched": 14, "skipped": 3, "errors": 0}
```

---

## Frontend integration

The player detail modal fetches `/players/{id}/profile` when opened. If a bio is present, a "Player Bio" section appears above the match history table. The section is hidden if the profile is not yet enriched or if `ANTHROPIC_API_KEY` is not configured.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(empty)* | Required for bio generation; if unset, facts are stored but bio is skipped |
| `PROFILE_ENRICHMENT_COOLDOWN_HOURS` | `24` | Minimum hours between re-enrichment for a given player |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
