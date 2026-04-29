# MVP Fantasy Bonus

When a broadcaster selects the MVP of a match via the Twitch extension, the designated player receives a configurable percentage bonus on their `fantasy_points` for that specific match. The bonus is retroactive and persists through weight recalculation.

---

## How it works

1. Broadcaster confirms MVP via `POST /twitch/mvp`.
2. Backend sets `player_match_stats.is_mvp = true` for the selected `(player_id, match_id)` row and multiplies `fantasy_points` by `(1 + mvp_bonus_pct / 100)`.
3. If the broadcaster changes the MVP for the same match, the previous player's flag is cleared and their `fantasy_points` reverts to the base score; the new player receives the bonus.
4. `POST /recalculate` re-applies the current `mvp_bonus_pct` weight to all `is_mvp = true` rows, so changing the bonus weight takes effect on the next recalculate run.
5. When a match is ingested and a `TwitchMVP` record already exists for it, the bonus is applied immediately to the new `PlayerMatchStats` row.

The bonus affects `player_match_stats.fantasy_points` directly, so it propagates automatically into all existing aggregation queries — roster totals, weekly leaderboard, season leaderboard, and match history — without any additional changes.

---

## Data model

### `player_match_stats.is_mvp`

| Field | Type | Description |
|---|---|---|
| `is_mvp` | BOOLEAN (default 0) | True when this player was named MVP for this match by the broadcaster |

`twitch_mvp` (existing table) continues to be the canonical record of *which* player is the MVP. `is_mvp` on `player_match_stats` is a derived flag that drives the bonus calculation.

---

## Endpoints

### `POST /twitch/mvp` *(updated)*

Existing endpoint. In addition to saving the MVP and dropping tokens, it now:
- Clears `is_mvp` and removes the bonus from the previous MVP's `PlayerMatchStats` row (if the MVP is being changed)
- Sets `is_mvp = true` and applies the bonus to the new MVP's `PlayerMatchStats` row

### `POST /recalculate` *(updated)*

Existing endpoint. After recalculating base scores for all rows, applies `fantasy_points *= (1 + mvp_bonus_pct / 100)` to every row where `is_mvp = true`.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `mvp_bonus_pct` *(weight key)* | `10.0` | Percentage bonus applied to the MVP player's fantasy score for that match. Managed via the admin weights panel alongside rarity bonuses and stat weights. |

The weight has no dedicated env var override — it is set at startup via `WEIGHTS_JSON` if needed, or edited in the admin panel.

---

## Frontend

The `GET /players/{player_id}` match history response includes `is_mvp: true` on the relevant match row. The player detail modal renders a small "MVP" label next to the score for that match.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
