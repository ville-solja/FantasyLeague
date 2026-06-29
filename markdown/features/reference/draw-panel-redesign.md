# Draw Panel Redesign

Renames the "Deck" panel on the My Team tab to "Draw" and replaces the per-rarity card count numbers with normalised drop percentages sourced from the live `draw_rate_*` scoring weights.

---

## Concept

Card counts were meaningful when cards came from a shared pre-seeded pool. With dynamic card generation, the pool is effectively unlimited and the count is misleading. Drop percentages — the actual probability of drawing each rarity — are what players need to make informed decisions about spending tokens.

## Backend change

### `GET /config`
Extended to include a `draw_rates` object:

```json
{
  "token_name": "...",
  "initial_tokens": 5,
  "app_version": "...",
  "app_release": "...",
  "team_booster_cost": 3,
  "draw_rates": {
    "common": 60.0,
    "rare": 25.0,
    "epic": 10.0,
    "legendary": 5.0
  }
}
```

Values are normalised from `draw_rate_common / draw_rate_rare / draw_rate_epic / draw_rate_legendary` weights (sum → 100%). Falls back to hardcoded defaults (60/25/10/5) if the weight rows are absent.

## Frontend change

- Panel heading: "Deck" → "Draw"
- Each rarity box: count replaced with `{pct}%`
- `loadDeck()` fetches both `GET /deck` (for the status line draw count) and `GET /config` (for percentages) in parallel

---

## Endpoints

### `GET /config`

Returns the full config object including `draw_rates`. No authentication required.

```
GET /config
```

Response (example with default weights):
```json
{
  "token_name": "token",
  "initial_tokens": 5,
  "app_version": "1.0.0",
  "app_release": "2026-01-01",
  "team_booster_cost": 3,
  "draw_rates": {
    "common": 60.0,
    "rare": 25.0,
    "epic": 10.0,
    "legendary": 5.0
  }
}
```

## Implementation notes

- Draw rates are read from `Weight` rows with keys `draw_rate_common`, `draw_rate_rare`, `draw_rate_epic`, `draw_rate_legendary`.
- Values are normalised so they always sum to 100% regardless of the raw weight magnitudes.
- Each value is rounded to 1 decimal place.
- If all four rows are absent, defaults (60/25/10/5) are used and normalised.
- `loadDeck()` in `app-cards.js` fetches `/deck` and `/config` in parallel. The `/deck` response drives the "X draws available" status line; `draw_rates` from `/config` drives the per-rarity percentage display.
- The `id="deck-{rarity}"` element IDs in `index.html` are unchanged so no other JS references required updating.
