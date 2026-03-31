# Cards

Cards are the core collectible unit of the fantasy league. Each card represents a real Dota 2 league player and is drawn from a shared seasonal deck.

## Card Rarities

Each player has four cards in the deck with different rarities:

| Rarity | Count per player | Display colour |
|--------|-----------------|----------------|
| Common (white) | 8 | White |
| Rare (blue) | 4 | Blue |
| Epic (purple) | 2 | Purple |
| Legendary (golden) | 1 | Gold |

Rarity is purely cosmetic in the current implementation — all cards of the same player score equally. Rarity may influence modifier scoring in a future update.

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

Each card has modifiers stored at generation time. Modifiers map to match events and apply bonus multipliers on top of base scoring. Modifier weights are managed globally by the admin — individual cards cannot be modified after generation.
