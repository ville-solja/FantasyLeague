# Team Booster Draws

Users can spend a configurable number of Tokens (default 3) to draw a card guaranteed to
come from a specific team's player roster. The feature is accessed via a "Draw from a team
(N Tokens)" button in the Draw panel of the My Team tab, which opens a team picker modal.

**Naming:** players see this feature as the **team draw** (it gives one card, not a pack).
The internal names keep "booster": the endpoints `GET /deck/booster` and
`POST /draw/booster/{team_id}`, the weight key `team_booster_cost`, the audit action
`token_booster_draw`, and element IDs such as `boosterBtn` / `boosterModal`. See
[Team Draw Explanation](team-draw-explanation.md).

---

## Flow

The team draw lives in the **Draw panel** alongside the standard draw. Clicking "Draw
from a team" opens a modal listing all teams with player data. Each team shows how
many players on the team the current user does not yet own any card of. Teams where the
user already owns at least one card of every player are greyed out.

The user selects a team and confirms. The backend rolls a rarity using the standard
`draw_rate_*` weights, then picks a player from the selected team. Duplicate prevention
is player-level: the user will not receive a player they already own a card of (at any
rarity) until they own every player on the team, at which point any player becomes
eligible again. The result is revealed in the same reveal modal as a standard draw.

## Endpoints

### `GET /deck/booster`
Returns a list of teams, sorted into two buckets — teams with at least one undrawn player
first, fully-collected teams last — alphabetically by name within each bucket (not a numeric
sort on `remaining`). Each entry contains per-team counts of players the authenticated user
does not yet own any card of. Unauthenticated callers see the total player count per team.
Teams with no players in the DB are omitted. Each entry contains `team_id`, `team_name`,
`logo_url`, and `remaining`.

### `POST /draw/booster/{team_id}`
Auth required. Spends `team_booster_cost` Tokens, rolls a rarity using the standard
`draw_rate_*` weights, and picks a player from the specified team. Duplicate prevention
is player-level: players the user already owns any card of are excluded; only when every
player on the team has been collected does the fallback allow any player. Returns the
same card payload shape as `POST /draw`, including the user's new balance as `tokens`
(not `tokens_remaining`). Returns 404 if `team_id` doesn't exist or user not found; 409 if
insufficient tokens or no players available for the team. The draw is recorded in the audit
log as `token_booster_draw`.

## Configuration

| Weight Key | Default | Description |
|---|---|---|
| `team_booster_cost` | `3` | Token cost per team draw. Shown read-only in the admin Scoring Weights panel (label "Team draw cost (Tokens)"); change it with `WEIGHTS_JSON` |

The cost is also exposed via `GET /config` as `team_booster_cost` so the frontend can
display it without hard-coding.

---
