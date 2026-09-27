# Plan: Team Draw Explanation and Naming

## Context
The Draw panel has a second button, "Draw Booster from Team", that spends 3 tokens by default for one card from a chosen team's roster. The How to Play tab never mentions it: its Cards & Drawing section only describes the 1-token draw. The word "booster" also misleads. In card games a booster is a pack of several cards, but this draw gives exactly one card, the same as the standard draw, just limited to one team.

This plan renames every user-visible "Booster" to "team draw", explains the team draw on the How to Play tab and next to the button, and relabels the admin cost weight.

**Assumptions:**
- Internal names stay unchanged: the endpoints `GET /deck/booster` and `POST /draw/booster/{team_id}`, the weight key `team_booster_cost`, the audit action `token_booster_draw`, and element IDs such as `boosterBtn`. Renaming them would break API clients, stored weights and audit history for no user benefit.
- The explanation shows the live cost from `GET /config` (`team_booster_cost`), not a hard-coded 3, because admins can change it.

Resolves GitHub issue #103.

## User Stories

### Team Draw Explained on How to Play
**User story**
As a player, I want the How to Play tab to explain the team draw so that I know what I get for the extra tokens before spending them.

**Acceptance criteria**
- The Users subtab's Cards & Drawing section has a bullet for the team draw, right after the standard draw bullet
- The bullet says the team draw gives **one card** from a team you choose, at the current team draw cost in tokens
- The cost shown is read from `GET /config` (`team_booster_cost`) at page load, with 3 as the fallback when it is unavailable
- The bullet says rarity uses the same odds as the standard draw, and that you get a player from that team you do not own yet, until you own every player on it
- The bullet says fully collected teams are greyed out in the team picker

### Clear Team Draw Naming in the Draw Panel
**User story**
As a player, I want the team draw's buttons and labels to say plainly what it does so that I don't expect a pack of several cards.

**Acceptance criteria**
- The Draw panel button reads "Draw from a team (N Tokens)", using the live cost and the configured token name
- A one-line hint under the button reads "One card from a team you pick, favouring players you don't own yet."
- The team picker's confirm button reads "Draw 1 card from this team", and its cost line reads "Costs N Tokens for 1 card"
- No user-visible text in `frontend/index.html` or `frontend/app-cards.js` contains the word "Booster"; internal identifiers are unchanged
- The reveal modal's "Draw another card" button still repeats a team draw from the same team after a team draw, as it does today

### Team Draw Cost Label for Admins
**User story**
As an admin, I want the cost setting to use the same name players see so that I know which draw it controls.

**Acceptance criteria**
- The Scoring Weights panel labels `team_booster_cost` as "Team draw cost (Tokens)"
- `seed_weights()` refreshes the label of every existing weight row to the label defined in `DEFAULT_WEIGHTS` on startup, so relabels reach deployed databases
- Refreshing labels never changes a weight's value

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/index.html` | How to Play team draw bullet with a cost span; button text, hint line and modal confirm text in the Draw panel |
| `frontend/app-cards.js` | Button text, cost line and confirm text use "team draw" wording; fill the How to Play cost span from `_teamBoosterCost` |
| `backend/seed.py` | `team_booster_cost` label → "Team draw cost (Tokens)"; `seed_weights()` refreshes labels on existing rows |
| `backend/tests/test_issue_103_team_draw_explanation.py` | Static checks on the HTML and JS copy; `seed_weights()` label refresh test |
| `markdown/ui_description/my-team.md` | Describe the team draw button, hint and picker in the Draw panel section |
| `markdown/features/reference/team-booster-draws.md` | Note the user-facing name "team draw" and the unchanged internal names |

No model change and no migration. `weights.label` already exists.

### Step 1 — How to Play copy
Add the bullet after the standard draw bullet in `#howtoplay-panel-users`, for example:

```html
<li>A <strong>team draw</strong> costs <strong><span id="htpTeamDrawCost">3</span> tokens</strong> and gives
<strong>one card</strong> from a team you pick. Rarity uses the same odds as a normal draw, and you get
a player from that team you don't own yet, until you own them all. Fully collected teams are greyed out.</li>
```

Fill `#htpTeamDrawCost` wherever `_teamBoosterCost` is set from `/config`.

### Step 2 — Draw panel and picker wording
- `_updateBoosterBtn()`: `Draw from a team (${cost} ${_tokenName})`. Change the static fallback text in `index.html` to match.
- Add the hint line under `#boosterBtn`, reusing the panel's muted text style.
- Modal: confirm button "Draw 1 card from this team"; `boosterCostLabel` → `Costs ${cost} ${_tokenName} for 1 card`.

### Step 3 — Admin label
Change the `team_booster_cost` label in `DEFAULT_WEIGHTS`. In `seed_weights()`, when a row exists and `existing.label != w["label"]`, set `existing.label = w["label"]`. Leave the value logic untouched.

### Step 4 — Docs
Update the Draw panel section of `ui_description/my-team.md` and the naming note in `team-booster-draws.md`. Fill in the feature stub.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_103_team_draw_explanation.py -v`, then the full suite. Bump the suite-size tripwire in `test_issue_85_split_admin_router.py`.
- Grep the two frontend files for user-visible "Booster": none remain outside identifiers, function names and API paths.
- With `WEIGHTS_JSON={"team_booster_cost": 4}` set and the app restarted (the Scoring Weights panel is read-only), reload. The Draw panel button, picker cost line and How to Play bullet all show 4.
- On an existing database, restart the app. The Scoring Weights panel shows "Team draw cost (Tokens)" and the value is unchanged.
- Do a team draw, then "Draw another card". It draws from the same team again.
