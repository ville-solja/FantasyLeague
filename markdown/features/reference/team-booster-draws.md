# Team Booster Draws

Users can spend a configurable number of Tokens (default 3) to draw a card guaranteed to
come from a specific team's player roster. The feature is accessed via a "Draw Booster
from Team" button in the Deck tab, which opens a team selector modal.

---

## Flow

The booster draw lives in the **Deck tab** alongside the standard draw. Clicking "Draw
Booster from Team" opens a modal listing all teams with player data. Each team shows how
many distinct (player, rarity) combinations the current user can still draw from that
team. Teams where the user has collected every combination are greyed out.

The user selects a team and confirms. The backend rolls a rarity using the standard
`draw_rate_*` weights, then picks a player from the selected team. The duplicate
prevention logic mirrors the standard draw: the selected (player, rarity) must not already
be owned, falling back to any unowned rarity for that team, then any player on the team if
all combinations are collected. The result is revealed in the same reveal modal as a
standard draw.

## Endpoints

### `GET /deck/booster`
Returns a list of teams (sorted by remaining drawable count descending, then name) with
per-team remaining drawable (player, rarity) counts for the authenticated user.
Unauthenticated callers see total possible counts. Teams with no players in the DB are
omitted. Each entry contains `team_id`, `team_name`, `logo_url`, and `remaining`.

### `POST /draw/booster/{team_id}`
Auth required. Spends `team_booster_cost` Tokens, rolls a rarity using the standard
`draw_rate_*` weights, and picks a player from the specified team using duplicate
prevention (prefers unowned (player, rarity) combos, falls back to any player on the
team). Returns the same card payload shape as `POST /draw` plus `tokens_remaining`.
Returns 404 if `team_id` doesn't exist or user not found; 409 if insufficient tokens or
no players available for the team. The draw is recorded in the audit log as
`token_booster_draw`.

## Configuration

| Weight Key | Default | Description |
|---|---|---|
| `team_booster_cost` | `3` | Token cost per team booster draw; editable in admin Scoring Weights panel |

The cost is also exposed via `GET /config` as `team_booster_cost` so the frontend can
display it without hard-coding.

---
