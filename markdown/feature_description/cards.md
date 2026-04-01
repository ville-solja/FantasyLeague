# Cards

Cards are the core collectible unit of the fantasy league. Each card represents a real Dota 2 league player and is drawn from a shared seasonal deck.

## Card Rarities

Each player has four cards in the deck with different rarities:

| Rarity | Count per player | Default rarity bonus | Default modifiers granted |
|--------|-----------------|---------------------|--------------------------|
| Common | 8 | +0% | 0 |
| Rare | 4 | +1% | 1 |
| Epic | 2 | +2% | 2 |
| Legendary | 1 | +3% | 3 |

**Rarity bonus** is a flat multiplier applied to the card's total fantasy score after all other calculations. It is configurable in the admin panel under Scoring Weights (`rarity_common`, `rarity_rare`, `rarity_epic`, `rarity_legendary`).

## Drawing Cards

- Costs **1 token** per draw.
- A card is chosen randomly from the shared unowned pool.
- The system prefers players the user does not yet own a card for. If the user owns a card for every player in the pool, duplicates are allowed.
- The drawn card is immediately assigned to the user.
- If the user has fewer than 5 active roster slots filled, the card is placed into the **active roster** automatically. Otherwise it goes to the **bench**.

## Deck Structure

The deck is shared across all users. Each card can only be owned by one user at a time. Cards are generated per season by an admin ingestion action, seeded from a given OpenDota league ID.

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
points = kills × kill_weight
       + assists × assist_weight
       - deaths × death_weight
       + gpm × gpm_weight
       + obs_wards × obs_weight
       + sen_wards × sen_weight
       + tower_damage × tower_dmg_weight
```

Weights are configured by the admin under **Scoring Weights** in the admin panel. Changes apply to future recalculations only.

## Card Modifiers

Card modifiers are per-stat bonuses assigned to a card at draw time. They boost the contribution of a specific stat to that card's fantasy score.

### How modifiers work

Each modifier targets one of the scoring stats (kills, assists, deaths, GPM, observer wards, sentry wards, tower damage) and carries a `bonus_pct` percentage value.

The modifier always benefits the card owner:
- For **positive-weight stats** (kills, assists, GPM, wards, tower damage):  
  `contribution = stat_value × weight × (1 + bonus_pct / 100)`
- For **negative-weight stats** (deaths):  
  `contribution = stat_value × weight × (1 - bonus_pct / 100)` — the penalty is reduced

### Full scoring formula with modifiers

```
For each stat:
  base = stat_value × stat_weight
  if modifier present and weight > 0:  points += base × (1 + modifier_bonus_pct / 100)
  if modifier present and weight < 0:  points += base × (1 - modifier_bonus_pct / 100)
  if no modifier:                       points += base

After summing all stats:
  card_points = stat_total × (1 + rarity_bonus_pct / 100)
```

### Modifier assignment at draw time

When a card is drawn from the deck, modifiers are randomly assigned:

1. **How many**: determined by `modifier_count_<rarity>` weight (e.g. `modifier_count_rare = 1` → 1 modifier on a rare card).
2. **Which stats**: randomly sampled without replacement from the 7 scoring stats.
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

### Extending the modifier system

The current system uses a single uniform `bonus_pct` for all modifiers. Future extensions could include:
- Per-stat modifier pools with different bonus ranges (e.g. kill modifiers stronger than GPM modifiers)
- Negative modifiers (penalties) drawn alongside bonuses
- Rarity-specific bonus ranges (e.g. Legendary cards get higher `bonus_pct` than Rare)
- Special named modifiers with flavour text
- Card-specific modifiers that affect only one player's known strengths

To add a new modifier type, add a new row to the `card_modifiers` table with the appropriate `stat_key` and `bonus_pct`. Any `stat_key` present in `SCORING_STATS` (defined in `backend/scoring.py`) will be applied automatically.
