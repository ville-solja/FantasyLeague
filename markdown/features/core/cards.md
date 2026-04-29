# Cards

Cards are the core collectible unit of the fantasy league. Each card represents a real Dota 2 league player and is drawn from a shared seasonal deck.

## Card Rarities

Each player has four cards in the deck with different rarities. In API responses the rarity is returned as the `card_type` field with values `"common"`, `"rare"`, `"epic"`, or `"legendary"`.

| Rarity | Count per player | Default rarity bonus | Default modifiers granted |
|--------|-----------------|---------------------|--------------------------|
| Common | 8 | +0% | 0 |
| Rare | 4 | +1% | 1 |
| Epic | 2 | +2% | 2 |
| Legendary | 1 | +3% | 3 |

**Rarity bonus** is a percentage multiplier applied to the card's total fantasy score after all other calculations (e.g. +1% means the total is multiplied by 1.01). It is configurable in the admin panel under Scoring Weights (`rarity_common`, `rarity_rare`, `rarity_epic`, `rarity_legendary`).

## Drawing Cards

- Costs **1 token** per draw.
- A card is chosen randomly from the shared unowned pool.
- The system prefers players the user does not yet own a card for. If the user owns a card for every player in the pool, duplicates are allowed.
- The drawn card is immediately assigned to the user.
- If the user has fewer than 5 active roster slots filled, the card is placed into the **active roster** automatically. Otherwise it goes to the **bench**.

## Deck Structure

The deck is shared across all users. Each card can only be owned by one user at a time. Cards are generated per season by an admin ingestion action, seeded from a given OpenDota league ID.

Each seeding batch is assigned a `generation` integer (starting at 1). Mid-season top-ups add a second batch at generation 2, a third at generation 3, and so on. Generation tracking is what makes seeding idempotent — a player is skipped only if a card for that player already exists in the current generation, not across all generations. See `POST /admin/top-up-cards` in `core/admin.md`.

## Card States

| State | Meaning |
|-------|---------|
| Unowned | In the shared pool, available to draw |
| Benched | Owned by a user, not in any active roster slot |
| Active | In the user's active 5-card roster for the upcoming week |
| Locked | Active roster was snapshot at week lock — card scores for that week |

## Scoring

Fantasy points for a card are derived from the real-life player's match stats during the locked week:

```
<<<<<<< HEAD
points = kills × kill_weight
       + assists × assist_weight
       - deaths × death_weight
       + gpm × gpm_weight
       + obs_wards × obs_weight
       + sen_wards × sen_weight
       + tower_damage × tower_dmg_weight
```

Weights are configured by the admin under **Scoring Weights** in the admin panel. Changes apply to future recalculations only.
=======
points = kills                   × kill_weight
       + last_hits               × last_hits_weight
       + denies                  × denies_weight
       + gold_per_min            × gpm_weight
       + obs_placed              × obs_weight
       + towers_killed           × tower_weight
       + roshan_kills            × roshan_weight
       + teamfight_participation × participation_weight
       + camps_stacked           × stack_weight
       + rune_pickups            × rune_weight
       + firstblood_claimed      × firstblood_weight
       + stuns                   × stun_weight
       + max(0, death_pool − deaths × death_deduction)
```

The death contribution awards `death_pool` points (default 3.0) for surviving with 0 deaths, deducting `death_deduction` (default 0.3) per death, floored at 0. A player with 10 or more deaths scores 0 from this component.

All weights are configured by the admin under **Scoring Weights** in the admin panel. Changes apply to future recalculations only.
>>>>>>> 25cc59e (Initial commit)

## Card Modifiers

Card modifiers are per-stat bonuses assigned to a card at draw time. They boost the contribution of a specific stat to that card's fantasy score.

### How modifiers work

<<<<<<< HEAD
Each modifier targets one of the scoring stats (kills, assists, deaths, GPM, observer wards, sentry wards, tower damage) and carries a `bonus_pct` percentage value.

The modifier always benefits the card owner:
- For **positive-weight stats** (kills, assists, GPM, wards, tower damage):  
  `contribution = stat_value × weight × (1 + bonus_pct / 100)`
- For **negative-weight stats** (deaths):  
  `contribution = stat_value × weight × (1 - bonus_pct / 100)` — the penalty is reduced
=======
Each modifier targets one of the scoring stats and carries a `bonus_pct` percentage value.

Valid modifier targets: `kills`, `deaths`, `gold_per_min`, `obs_placed`, `last_hits`, `denies`, `towers_killed`, `roshan_kills`, `teamfight_participation`, `camps_stacked`, `rune_pickups`, `firstblood_claimed`, `stuns`

The modifier always benefits the card owner:
- For **standard stats** (all except deaths):  
  `contribution = stat_value × weight × (1 + bonus_pct / 100)`
- For **deaths**:  
  `contribution = max(0, death_pool − deaths × death_deduction) × (1 + bonus_pct / 100)` — the survival bonus is amplified. This modifier is most valuable on players who rarely die; it has no effect when the death contribution is already 0.
>>>>>>> 25cc59e (Initial commit)

### Full scoring formula with modifiers

```
<<<<<<< HEAD
For each stat:
  base = stat_value × stat_weight
  if modifier present and weight > 0:  points += base × (1 + modifier_bonus_pct / 100)
  if modifier present and weight < 0:  points += base × (1 - modifier_bonus_pct / 100)
  if no modifier:                       points += base

After summing all stats:
=======
For each standard stat (kills, last_hits, denies, gpm, obs, towers, roshan,
                        participation, stacks, runes, firstblood, stuns):
  base = stat_value × stat_weight
  points += base × (1 + modifier_bonus_pct / 100)   if modifier present
  points += base                                      if no modifier

For deaths:
  base = max(0, death_pool − deaths × death_deduction)
  points += base × (1 + modifier_bonus_pct / 100)   if modifier present
  points += base                                      if no modifier

After summing all contributions:
>>>>>>> 25cc59e (Initial commit)
  card_points = stat_total × (1 + rarity_bonus_pct / 100)
```

### Modifier assignment at draw time

When a card is drawn from the deck, modifiers are randomly assigned:

1. **How many**: determined by `modifier_count_<rarity>` weight (e.g. `modifier_count_rare = 1` → 1 modifier on a rare card).
<<<<<<< HEAD
2. **Which stats**: randomly sampled without replacement from the 7 scoring stats.
=======
2. **Which stats**: randomly sampled without replacement from the 13 valid stat keys (12 scoring stats + `deaths`).
>>>>>>> 25cc59e (Initial commit)
3. **Bonus %**: all modifiers on a card share the same `modifier_bonus_pct` value.

All three settings are configurable in the admin panel under Scoring Weights.

### Modifier visibility

- Displayed as green pills on the card row in the My Team roster (active and bench).
- Shown in the card reveal modal immediately after drawing.
- Shown in the card detail popup when clicking a player name in the roster.

### Modifier configuration (admin)

| Weight key | Description | Default |
|---|---|---|
| `modifier_count_common` | Number of modifiers on a Common card | 0 |
| `modifier_count_rare` | Number of modifiers on a Rare card | 1 |
| `modifier_count_epic` | Number of modifiers on an Epic card | 2 |
| `modifier_count_legendary` | Number of modifiers on a Legendary card | 3 |
| `modifier_bonus_pct` | % bonus each modifier grants | 10 |

Modifier counts apply to **newly drawn cards only** — existing cards in users' rosters are not retroactively updated when the count weights change.

### Modifier Reroll

A user can spend **1 token** to discard a card's current modifiers and generate a new random set in their place. The card's rarity, player, and league are unchanged — only the `card_modifiers` rows are replaced.

#### `POST /roster/{card_id}/reroll`

Requires authentication. The card must be owned by the calling user.

**Cost:** 1 token, deducted on success.

**Behaviour:**
1. All existing `CardModifier` rows for the card are deleted.
2. New modifiers are assigned using the same random logic as draw time: count determined by `modifier_count_<rarity>`, stats randomly sampled without replacement, bonus set by `modifier_bonus_pct`.
3. The action is recorded in the audit log (`reroll_modifiers`).

**Response:**
```json
{
  "modifiers": [{"stat": "kills", "bonus_pct": 10.0}],
  "tokens": 4
}
```

Returns the new modifier list and the user's remaining token balance. Returns 409 if the user has no tokens.

The reroll applies the **current** `modifier_count_<rarity>` and `modifier_bonus_pct` weight values, so a reroll may produce a different number of modifiers than the card originally had if an admin has changed the weights since the card was drawn.

### Extending the modifier system

The current system uses a single uniform `bonus_pct` for all modifiers. Future extensions could include:
- Per-stat modifier pools with different bonus ranges (e.g. kill modifiers stronger than GPM modifiers)
- Negative modifiers (penalties) drawn alongside bonuses
- Rarity-specific bonus ranges (e.g. Legendary cards get higher `bonus_pct` than Rare)
- Special named modifiers with flavour text
- Card-specific modifiers that affect only one player's known strengths

To add a new modifier type, add a new row to the `card_modifiers` table with the appropriate `stat_key` and `bonus_pct`. Any `stat_key` present in `SCORING_STATS` (defined in `backend/scoring.py`) will be applied automatically.

---

## Roster Endpoints

### `GET /roster/{user_id}`

Returns the calling user's cards split into `active` and `bench` lists, with per-card fantasy points scoped to the requested week.

**Query parameter:** `week_id` (optional integer). Omit to use the current editable week.

- For a **locked** week: returns the immutable `WeeklyRosterEntry` snapshot for that week with points from matches played during the week's window.
- For the **current editable** week: returns all owned cards from the `cards` table, split by `is_active`, with running points accumulated so far.

```json
{
  "active": [{ "id": 42, "card_type": "rare", "player_name": "SomePlayer", "total_points": 34.5, "modifiers": [...], ... }],
  "bench":  [...],
  "combined_value": 130.2,
  "season_points": 420.0,
  "tokens": 4
}
```

Requires authentication. Returns 401 if not logged in.

---

### `POST /roster/{card_id}/activate`

Moves a benched card into the active roster. Requires authentication; the card must be owned by the caller.

- Returns 409 `"Roster full"` if the user already has `ROSTER_LIMIT` active cards (default: 5).
- Returns 409 `"A card for this player is already active"` if another card for the same player is already active.
- Returns `{ "status": "ok", "card_id": N }` on success.

---

### `POST /roster/{card_id}/deactivate`

Moves an active card to the bench. Requires authentication; the card must be owned by the caller.

Returns `{ "status": "ok", "card_id": N }`.

---

## Card Endpoints

### `GET /deck`

Returns a count of unowned cards remaining in the shared pool, grouped by rarity.

```json
{ "common": 34, "rare": 12, "epic": 4, "legendary": 1 }
```

No authentication required. Used by the frontend to show pool depth before drawing.

---

### `GET /cards/{card_id}`

Returns full detail for a single card owned by the authenticated user. Returns 404 if the card does not exist or is not owned by the caller.

```json
{
  "id": 42,
  "card_type": "rare",
  "player_name": "SomePlayer",
  "avatar_url": "https://...",
  "team_name": "SomeTeam",
  "team_logo_url": "https://...",
  "modifiers": [{ "stat": "kills", "bonus_pct": 10.0 }]
}
```

`team_name` and `team_logo_url` are resolved from the player's most recent ingested match.

---

### `POST /draw`

Draws one card from the shared pool. Requires authentication.

**Cost:** 1 token, deducted on success. Returns 409 if the user has no tokens, and 409 if the pool is empty.

**Response:**
```json
{
  "id": 42,
  "card_type": "rare",
  "player_id": 123456789,
  "player_name": "SomePlayer",
  "avatar_url": "https://...",
  "team_name": "SomeTeam",
  "team_logo_url": "https://...",
  "is_active": true,
  "modifiers": [{ "stat": "kills", "bonus_pct": 10.0 }],
  "tokens": 4
}
```

`is_active` is `true` if the card was placed directly into the active roster, `false` if it went to the bench.

The card is automatically placed in the active roster if fewer than `ROSTER_LIMIT` slots are filled; otherwise it goes to the bench. The action is recorded in the audit log (`token_draw`).

---

### `GET /cards/{card_id}/image`

Generates and returns a PNG card image for any card (owner not required). Returns `Content-Type: image/png` with `no-cache` headers.

Returns 404 if the card does not exist. Returns 503 if the Pillow image library is not available in the runtime environment.

The image includes the player avatar, team logo, card rarity border, player name, and any stat modifier labels. Used by the frontend draw reveal modal.
