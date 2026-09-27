# Team Draw Explanation

Renames the "booster" draw to **team draw** everywhere players see it, and explains it on the How to Play tab and in the Draw panel. Used by players deciding whether to spend extra tokens, and by admins tuning its cost.

---

## What players see

- **Draw panel:** a "Draw from a team (N Tokens)" button (`#boosterBtn`, text set by `_updateBoosterBtn()` in `frontend/app-cards.js`) with a one-line hint under it (`#boosterHint`): "One card from a team you pick, favouring players you don't own yet."
- **Team picker:** a "Draw 1 card from this team" confirm button (`#boosterDrawBtn`) and a "Costs N Tokens for 1 card" line (`#boosterCostLabel`, set by `loadBoosterTeams()`).
- **How to Play, Users subtab:** a Cards & Drawing bullet saying a team draw gives one card from a chosen team, uses the normal rarity odds, prefers players you don't own until you own them all, and that fully collected teams are greyed out in the picker. The cost is in `#htpTeamDrawCost`.

N is the live `team_booster_cost` from `GET /config`, so the copy follows admin changes. `loadConfig()` in `frontend/app-globals.js` sets `_teamBoosterCost` and writes it into `#htpTeamDrawCost`; the static HTML fallback is 3.

## Unchanged internal names

The mechanics are documented in [Team Booster Draws](team-booster-draws.md). The API paths `GET /deck/booster` and `POST /draw/booster/{team_id}`, the weight key `team_booster_cost` and the audit action `token_booster_draw` keep their names.

## Admin label

The Scoring Weights panel shows `team_booster_cost` as "Team draw cost (Tokens)". `seed_weights()` in `backend/seed.py` refreshes every existing weight row's label to its `DEFAULT_WEIGHTS` label on startup, so the new label reaches existing databases. It never changes a weight's value. No schema change or migration.

## Tests

`backend/tests/test_issue_103_team_draw_explanation.py` — static copy checks on `frontend/index.html`, `frontend/app-cards.js` and `frontend/app-globals.js` (including a checker that no user-visible text says "Booster"), and `seed_weights()` label-refresh tests.
