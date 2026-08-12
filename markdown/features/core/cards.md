# Cards

Cards are the core collectible unit of the fantasy league. Each card represents a real Dota 2 league player and is generated on demand at draw time.

## Card Rarities

Each draw creates one card with a rarity rolled from configurable percentage weights. In API responses the rarity is returned as the `card_type` field with values `"common"`, `"rare"`, `"epic"`, or `"legendary"`.

| Rarity | Default draw rate | Default rarity bonus | Default modifiers granted |
|--------|------------------|---------------------|--------------------------|
| Common | 60% | +0% | 0 |
| Rare | 25% | +1% | 1 |
| Epic | 10% | +2% | 2 |
| Legendary | 5% | +3% | 3 |

**Draw rates** are relative weights (`draw_rate_common`, `draw_rate_rare`, `draw_rate_epic`, `draw_rate_legendary`) configurable in the admin panel under Scoring Weights. They do not need to sum to 100 — proportions are used. Defaults approximate 8:4:2:1 ratios from the old pool model.

**Rarity bonus** is a percentage multiplier applied to the card's total fantasy score after all other calculations. It is configurable via `rarity_common`, `rarity_rare`, `rarity_epic`, `rarity_legendary`.

## Drawing Cards

- Costs **1 token** per draw.
- Rarity is rolled from the configured draw-rate weights at draw time.
- A player is chosen with a proportionality bias: players the user does not yet own any card of (at any rarity) are preferred. Among those, players with fewer total cards in the user's collection are weighted higher.
- If the user already owns at least one card of every active player, the uniqueness constraint is relaxed and any player may be selected.
- If no players exist in the database at all, the draw returns 409.
- Each draw **creates a new Card row** — there is no shared pre-generated pool to exhaust.
- If the user has fewer than 5 active roster slots filled, the card is placed into the **active roster** automatically. Otherwise it goes to the **bench**.

## Deck Structure

Cards are generated dynamically at draw time rather than from a pre-seeded shared pool. `GET /deck` returns the number of distinct `(player, rarity)` combinations the requesting user has not yet drawn. This count decreases by one each time the user draws a new unique combination.

Each Card row carries `generation=1` by default. The `league_id` field is nullable for dynamically created cards. Existing pre-seeded cards (from before the migration) are unaffected.

## Card States

| State | Meaning |
|-------|---------|
| Benched | Owned by a user, not in any active roster slot |
| Active | In the user's active 5-card roster for the upcoming week |
| Locked | Active roster was snapshot at week lock — card scores for that week |

## Scoring

Fantasy points for a card are derived from the real-life player's match stats during the locked week:

```
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

## Card Modifiers

Card modifiers are per-stat bonuses assigned to a card at draw time. They boost the contribution of a specific stat to that card's fantasy score.

### How modifiers work

Each modifier targets one of the scoring stats and carries a `bonus_pct` percentage value.

Valid modifier targets: `kills`, `deaths`, `gold_per_min`, `obs_placed`, `last_hits`, `denies`, `towers_killed`, `roshan_kills`, `teamfight_participation`, `camps_stacked`, `rune_pickups`, `firstblood_claimed`, `stuns`

The modifier always benefits the card owner:
- For **standard stats** (all except deaths):  
  `contribution = stat_value × weight × (1 + bonus_pct / 100)`
- For **deaths**:  
  `contribution = max(0, death_pool − deaths × death_deduction) × (1 + bonus_pct / 100)` — the survival bonus is amplified. This modifier is most valuable on players who rarely die; it has no effect when the death contribution is already 0.

### Full scoring formula with modifiers

```
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
  card_points = stat_total × (1 + rarity_bonus_pct / 100)
```

### Modifier assignment at draw time

When a card is drawn from the deck, modifiers are randomly assigned:

1. **How many**: determined by `modifier_count_<rarity>` weight (e.g. `modifier_count_rare = 1` → 1 modifier on a rare card).
2. **Which stats**: randomly sampled without replacement from the 13 valid stat keys (12 scoring stats + `deaths`).
3. **Bonus %**: all modifiers on a card share the same `modifier_bonus_pct` value.

All three settings are configurable in the admin panel under Scoring Weights.

### Modifier visibility

Modifiers are rendered directly onto the card's PNG image (see `reference/card-image-generation.md`) — that is the only place they're shown. There is deliberately no separate text/pill rendering anywhere in the UI (My Team roster rows, the reveal modal, or the card detail popup); the values are already readable on the card image itself, so a second text rendering would be duplicate information.

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

Returns the new modifier list and the user's remaining token balance. Returns 409 if the user has no tokens. Returns 400 `"Common cards cannot be rerolled"` if the card's rarity is `common` (no modifier stats to reroll) — no token is deducted in that case. The Reroll button is also hidden client-side for common cards. See `reference/prevent-common-card-reroll.md`.

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

Requires authentication. Returns 403 `"Cannot view another user's roster"` if `user_id` doesn't
match the caller's own ID, unless the caller is an admin (admins can view any user's roster).

---

### `POST /roster/{card_id}/activate`

Moves a benched card into the active roster. Requires authentication; the card must be owned by the caller.

- Returns 409 `"Roster full ({ROSTER_LIMIT} cards max)"` if the user already has `ROSTER_LIMIT` active cards (default: 5).
- Returns 409 `"A card for this player is already active"` if another card for the same player is already active.
- Returns `{ "status": "ok", "card_id": N }` on success.

---

### `POST /roster/{card_id}/deactivate`

Moves an active card to the bench. Requires authentication; the card must be owned by the caller.

Returns `{ "status": "ok", "card_id": N }`.

---

### `POST /roster/reorder`

Sets `slot_index` (drag-and-drop display position) for a list of the caller's own cards within
their current zone (active or bench). Accepts `{"card_ids": [...]}` for sequential positions
(index in the array = new `slot_index`), or `{"card_ids": [...], "slot_indexes": [...]}` to
assign explicit positions instead. Requires authentication. See
`reference/my-team-drag-and-drop.md`.

---

### `POST /roster/swap`

Atomically activates a bench card into a given slot while deactivating an active card, applying
the same duplicate-player guard as `activate`. Requires authentication. Returns 404 if either
card isn't found in the expected zone; 409 on a duplicate-player conflict. See
`reference/my-team-drag-and-drop.md`.

---

## Card Endpoints

### `GET /deck`

Returns the number of distinct `(player, rarity)` combinations the requesting user has not yet drawn, grouped by rarity.

- **Authenticated:** returns the per-rarity count of combinations the user can still draw uniquely.
- **Unauthenticated:** returns the total combinations across all players (4 rarities × number of players).

```json
{ "common": 12, "rare": 12, "epic": 12, "legendary": 12 }
```

The frontend displays this as "X draws available". The count decreases by 1 each time the user draws a new unique `(player, rarity)` combination. No authentication required.

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

Draws one card. A new Card row is created on demand — no pre-generated pool is required. Requires authentication.

**Cost:** 1 token, deducted on success. Returns 409 if the user has no tokens, and 409 if no Player records exist.

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

---

### `GET /deck/booster` and `POST /draw/booster/{team_id}`

A variant of the standard deck/draw pair, restricted to one team's player roster at a
configurable Token cost (`team_booster_cost`, default 3) instead of the usual 1. Duplicate
prevention and response shape otherwise match `GET /deck` and `POST /draw`. See
`reference/team-booster-draws.md` for the full endpoint contract and configuration.
