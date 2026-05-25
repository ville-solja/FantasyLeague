# Dynamic Card Creation

Cards are generated at draw time rather than pre-populated into a shared pool. Rarity is
rolled from configurable drop-rate weights; player selection uses a proportionality bias to
prefer players the user owns fewer cards of.

---

## How it works

When `POST /draw` is called:

1. **Rarity roll** — a weighted random choice across `draw_rate_common`, `draw_rate_rare`,
   `draw_rate_epic`, and `draw_rate_legendary` weight keys determines the card's rarity.
2. **Player selection** — all players are candidates. Players for whom the user already owns
   the rolled rarity are excluded. Among the remaining eligible players, those with fewer total
   cards in the user's collection are given a higher selection weight (proportionality bias).
   If all players already own the rarity, the exclusion is relaxed and any player is eligible.
3. **Card creation** — a new `Card` row is inserted with `owner_id`, `player_id`, and
   `card_type` set. Modifiers are assigned using the existing draw-time logic.
4. **Duplicate prevention** — the `(owner_id, player_id, card_type)` triple is unique per
   user in normal operation. The constraint is relaxed only when no other option exists.

There is no shared pool. Cards are never pre-generated. Pool exhaustion is not possible.

---

## Deprecated features

| Feature | Status |
|---|---|
| `POST /admin/top-up-cards` | Removed — mid-season players are accessible automatically |
| Ingest card generation | Removed — ingest creates player/match records only |
| Shared unowned card pool | Removed — cards are created on draw |

---

## Endpoints

### `POST /draw` *(updated)*
Unchanged surface behaviour: costs 1 token, returns card data, assigns modifiers. Internally,
no longer selects from a pool — generates a new card instead.

### `GET /deck` *(updated)*
Previously returned unowned pool counts. Now returns per-user available draw combinations:
the number of distinct `(player, rarity)` pairs the authenticated user does not yet own.
Requires authentication for per-user counts.

---

## Configuration

| Weight key | Default | Description |
|---|---|---|
| `draw_rate_common` | 60.0 | Relative weight for drawing a Common card |
| `draw_rate_rare` | 25.0 | Relative weight for drawing a Rare card |
| `draw_rate_epic` | 10.0 | Relative weight for drawing an Epic card |
| `draw_rate_legendary` | 5.0 | Relative weight for drawing a Legendary card |

Weights are relative, not percentages — they do not need to sum to 100. Configure via the
Scoring Weights panel in the admin tab.

