# Cards

> **Note:** The original card system used a shared pre-generated pool ("Generate Deck",
> fixed rarity per card) with an admin "Mid-Season Card Top-Up" action. Both were replaced
> by the **Dynamic Card Creation** system below — cards are generated per draw with a
> weighted rarity roll, so there is no shared pool, no seed-time rarity, and no top-up
> action to run. See the "Dynamic Card Creation" and "Deprecate Pool Management" sections
> further down this file for the current, authoritative stories.

### Draw Card
**User story**
As a user, I want to be able to draw cards using tokens.

**Acceptance criteria**
- User can draw a card if they have at least 1 token
- Card is shown to the user in a reveal modal
- Card is added to the user's active roster if empty slots exist, otherwise to their bench
- Rarity and duplicate-avoidance rules are covered by the "Dynamic Card Creation" stories below

---

### Stat Modifiers
**User story**
As a user, I want each card to have a defined number of stat modifiers.

**Acceptance criteria**
- Modifiers are assigned at draw time based on rarity and configured weights
- Visible whenever the card is accessed

---

### Modifier Management
**User story**
As an admin, I want to be able to adjust the weights of modifiers in order to tune balance.

**Acceptance criteria**
- Modifier tuning is controlled by normal `weights` rows (`modifier_count_*`, `modifier_bonus_pct`) — same mechanism as scoring weights (DB defaults from `backend/seed.py`, optional `WEIGHTS_JSON` overrides on startup)
- Individual cards are not modified — entire modifier weights are adjusted at once
- Modifier changes are not applied retroactively without an explicit recalculate action

---

### View Collection
**User story**
As a user, I want to browse my roster and bench.

**Acceptance criteria**
- All benched cards are shown in the My Team tab
- Cards are either in the currently active roster for the upcoming week, or in the bench
- Shows player, rarity, and points accumulated during the current week
- Bench is hidden for locked past weeks (read-only snapshot view)

---

### Card Visual Identity
**User story**
As a user, I want each card to display the player's name, team name, photo, and team emblem so I can identify the player and team at a glance.

**Acceptance criteria**
- Player name is printed on the card image in the name plate area (uppercased, truncated if too long)
- Team name is printed below the player name on the card image
- Player avatar (from OpenDota) is composited as a circular portrait on the card image
- Team logo (from local Dotabuff cache, HTTP fallback) is composited as a smaller circular badge on the card image
- If avatar or logo is unavailable, the card still renders correctly with the slot left empty
- During the draw reveal animation, player and team names are sourced from the card PNG only — they are not duplicated in the HTML below the image

---

### Rarity-Distinct Card Design
**User story**
As a user, I want each rarity tier to have a visually distinct card frame so I can identify rarity from the card art alone.

**Acceptance criteria**
- Each rarity (Common, Rare, Epic, Legendary) uses a separate template PNG with its own border and colour scheme
- Rarity frame is always visible regardless of player or team

---

### Modifier Labels on Card Image
**User story**
As a user, I want my card's stat modifiers printed directly on the card image so the bonus is always visible without opening a detail view.

**Acceptance criteria**
- Each active modifier is shown in the lower band of the card as `STAT +X%`
- After a reroll, the card image updates immediately to reflect the new modifiers
- Cards with no modifiers (e.g. Common) show no modifier text in that area

---

### Replaceable Card Template Artwork
**User story**
As an operator, I want to update card template artwork for each rarity by replacing files so the visual design can be refreshed between seasons without code changes.

**Acceptance criteria**
- Templates are loaded from a configurable assets directory at startup
- Replacing any of the four template PNGs takes effect on the next card image request
- Missing templates fail with a clear error rather than silently using a wrong rarity

---

### Player Link from Card
**User story**
As a user, I want to click the player name displayed on a viewed card so that I can read the player's stats and bio without navigating away from the card.

**Acceptance criteria**
- The player name shown in the card reveal modal is rendered as a clickable link when a valid player exists
- Clicking it opens the player detail modal with the correct player loaded
- The reveal modal remains open and visible behind the player modal
- Cards without a linked player show the name as non-clickable plain text
- Closing the player modal leaves the reveal modal open and unchanged
- Pressing Escape closes only the top-most open modal (player popup first, then card reveal if pressed again)

---

> **Superseded:** "Mid-Season Card Top-Up" (an admin action to add a fresh batch of cards to
> the shared pool) no longer applies — cards are generated per draw, so there is no pool to
> top up. See "Deprecate Pool Management" below, which removed `POST /admin/top-up-cards`.

---

## Card Draw Modal UX

### Enter Key Draws or Closes the Card Modal
**User story**
As a user, I want to press Enter after drawing a card so that I can immediately draw
another card (or close the modal if I have no tokens left) without reaching for the mouse.

**Acceptance criteria**
- Pressing Enter while the card draw result modal is open triggers the same action as clicking the primary button
- If the user has tokens remaining, Enter draws another card
- If the user has zero tokens, Enter closes/dismisses the modal
- Enter key handling is removed when the modal is closed (no ghost listener)

### Dynamic Button Label Reflects Available Action
**User story**
As a user, I want the primary button in the draw modal to tell me what will happen next so
that I understand whether clicking it costs a token or just dismisses the screen.

**Acceptance criteria**
- When the user has 1 or more tokens after drawing, the primary button reads "Draw another card"
- When the user has 0 tokens after drawing, the primary button reads "Continue"
- The button label updates immediately after each draw without a page reload

### Dismiss Modal by Clicking Outside
**User story**
As a user, I want to close the card draw modal by clicking outside it (on the dark overlay)
so that I can dismiss it using the standard web pattern instead of hunting for the X button.

**Acceptance criteria**
- Clicking the modal backdrop (outside the modal content box) closes the modal
- Clicking inside the modal content does not close it (click propagation stops at the content box)
- The modal can still be closed with the existing X button as well

---

## Common Card Reroll Prevention

### Reroll Button Hidden for Common Cards
**User story**
As a user, I want the Reroll Modifiers button to be absent when I am viewing a common card
so that I am not tempted to spend a token on an action that does nothing.

**Acceptance criteria**
- The Reroll Modifiers button is not visible when the card draw modal shows a common card
- The Reroll Modifiers button is visible for rare, epic, and legendary cards (unchanged)
- No change to any other modal behaviour

### Backend Rejects Common Card Reroll
**User story**
As a developer, I want the reroll endpoint to reject requests for common cards so that the
rule is enforced server-side regardless of how the request is made.

**Acceptance criteria**
- `POST /roster/{card_id}/reroll` returns HTTP 400 with a clear error message when the target card is of type `"common"`
- The endpoint continues to succeed for rare, epic, and legendary cards
- The error message is distinct enough to aid debugging (e.g. `"Common cards cannot be rerolled"`)

## Card Stickers (User Tags)

Card sticker stories are in [user-tags.md](user-tags.md) — the tag system is generic
and covers cards, leaderboard display, and admin management together.

---

## Dynamic Card Creation

### Draw a Card with Weighted Rarity
**User story**
As a user, I want the rarity of each drawn card to be determined by configured drop rates so
that I have a realistic chance of high-rarity cards on every draw.

**Acceptance criteria**
- Each draw rolls a rarity from configurable percentage weights (`draw_rate_common`,
  `draw_rate_rare`, `draw_rate_epic`, `draw_rate_legendary`; defaults approximate the old
  pool ratios)
- The rolled rarity is reflected in the card shown in the reveal modal
- A card is always created — draws never fail due to pool exhaustion

### Player Proportionality on Draw
**User story**
As a user, I want the draw system to prefer players I have fewer cards of so that my collection
stays diverse and mid-season additions are accessible.

**Acceptance criteria**
- Players for whom the user already holds the rolled rarity are excluded from selection
- Among remaining eligible players, those with fewer total cards in the user's collection
  are assigned a higher selection weight
- If every active player already owns the drawn rarity, the draw proceeds with full player
  selection (no hard failure)

### No Duplicate Rarity–Player Combinations
**User story**
As a user, I want the system to prevent me from drawing an identical card (same player and
rarity) twice so that each draw adds something new to my collection.

**Acceptance criteria**
- `POST /draw` never returns a card whose `(owner_id, player_id, card_type)` combination
  already exists in the `cards` table
- If a user owns the drawn rarity for every eligible player, the uniqueness constraint is
  relaxed for that draw (fallback to allow any player, then any rarity)
- The constraint is per user — other users owning the same player/rarity does not affect
  availability

### Configurable Drop Rates
**User story**
As an admin, I want to configure the rarity drop rates via the scoring weights so that I
can tune the economy without a code deploy.

**Acceptance criteria**
- Four new weight keys exist: `draw_rate_common`, `draw_rate_rare`, `draw_rate_epic`,
  `draw_rate_legendary`
- These are seeded with sensible defaults and editable in the Scoring Weights admin panel
- The draw logic reads these values at draw time (not cached between requests)
- Weights do not need to sum to exactly 100; relative proportions are used

### Deprecate Pool Management
**User story**
As an admin, I want pre-generation and pool top-up actions to be removed so that the
system is simpler to operate.

**Acceptance criteria**
- `POST /admin/top-up-cards` is removed (returns 410 Gone or is deleted)
- Card generation is removed from the ingest pipeline — ingest creates only player records
- `GET /deck` returns a count of how many distinct (player, rarity) combinations the
  requesting user can still draw (i.e. combinations they do not yet own), replacing the
  old unowned pool count
- Existing owned cards in users' collections are unaffected by the migration

## Team Booster Draws

### Team Booster Draw
**User story**
As a user, I want to open a team selector in the Draw tab and draw a card from a chosen
team for 3 Tokens so that I can target the players I care about rather than relying on
random selection from the full pool.

**Acceptance criteria**
- A "Draw Booster from Team" button is visible in the Draw tab
- Clicking the button opens a team selection modal listing all teams with at least one
  player with match data, each showing how many drawable (player, rarity) combinations
  remain for the current user
- Teams where the user has collected every combination are shown greyed out and unselectable
- Selecting a team and confirming spends `team_booster_cost` Tokens and draws a card whose
  player is from that team; rarity is still determined by the standard `draw_rate_*` weights
- The drawn card is revealed in the same reveal modal as a standard draw
- The "Draw Booster" button is disabled with "Not enough Tokens" if the user's balance is
  below the configured cost
- After a successful draw, the team selector modal updates its remaining counts and the
  token balance refreshes

### Booster Duplicate Prevention
**User story**
As a user, I want the booster draw to avoid giving me a card I already own so that each
booster adds something new, with a fallback when I have collected the whole team.

**Acceptance criteria**
- The booster draw excludes (player, rarity) combinations the user already owns within
  the selected team
- If all combinations at the rolled rarity are owned, the draw picks any unowned rarity
  for that team's players
- If the user owns every (player, rarity) combination for the team, the draw proceeds from
  the full team player list (no hard failure on collection completion)
- `POST /draw/booster/{team_id}` returns 409 only when the team has no players in the DB

### Configurable Booster Cost (Admin)
**User story**
As an admin, I want to control the token cost of a team booster draw via the scoring
weights panel so that I can adjust the economy without a code change.

**Acceptance criteria**
- A weight key `team_booster_cost` exists with a default value of `3`
- The weight is editable in the admin Scoring Weights panel alongside other economy weights
- The booster draw endpoint reads this weight at request time (not cached)
- Setting the weight to `1` makes booster draws cost the same as standard draws

---

## Draw Panel Redesign

### View Drop Percentages in the Draw Panel
**User story**
As a player, I want to see the drop chance for each rarity in the Draw panel so that I know what I am likely to get when I spend a token.

**Acceptance criteria**
- The panel heading reads "Draw" instead of "Deck"
- Each rarity card template displays its drop percentage (e.g. "60%") instead of a card count
- Percentages are normalised from the live `draw_rate_*` weights so they always sum to 100%
- Percentages update if an admin changes the draw rate weights (on next page load)
- The "X draws available" status line and the draw/booster buttons are unchanged *(superseded — the status line's data source was corrected by "Fix Available Draws Count Display" below, issue #89; the buttons themselves remain unchanged)*

### Expose Draw Rates via the Config Endpoint
**User story**
As a frontend client, I want the `/config` endpoint to include the current draw rate percentages so that I do not have to parse the full weights list client-side.

**Acceptance criteria**
- `GET /config` returns a `draw_rates` object with keys `common`, `rare`, `epic`, `legendary`
- Each value is a float representing the normalised percentage (rounds to 1 decimal place)
- If all four `draw_rate_*` weights are missing from the database the endpoint falls back to the seeded defaults (60/25/10/5)

## Fix Available Draws Count Display

### Accurate Available Draws Count
**User story**
As a user, I want the "draws available" number on the Draw panel to reflect my actual remaining
draws (my token balance) so that I am not misled into thinking I can draw far more cards than I
actually can.

**Acceptance criteria**
- The Draw panel's `#deckStatus` line shows a number derived from the user's current token
  balance, not from `GET /deck`'s summed per-rarity undrawn-combination counts
- Immediately after a successful standard or team-booster draw, the number decreases by 1 to
  match the new token balance returned by the draw response, with no page refresh needed
- When the user has 0 tokens, the line shows "No draws available", matching the account's actual
  draw eligibility (`POST /draw` returns 409 at this point)
- Logged-out users are not shown a specific draws-available number derived from data that
  doesn't apply to them, mirroring the existing logged-out behavior of `#drawCounter`

---

### Consistent Draw-Count Messaging
**User story**
As a user, I want the two draw-count indicators near the Draw button (the counter beside the
button and the status line below it) to always agree with each other so that I am not shown two
different numbers for the same thing.

**Acceptance criteria**
- `#drawCounter` and `#deckStatus`'s "draws available" text derive from the same source of truth
  (the user's token balance, `_tokenBalance`)
- After a successful draw (standard or team-booster), both indicators update together in the
  same call, so they can never show conflicting numbers even momentarily
- `GET /deck`'s response shape, and its use by the team-booster panel (`GET /deck/booster`,
  `loadBoosterTeams()`), are unaffected — this fix only changes how `loadDeck()`'s status line
  interprets data, not the `/deck` endpoint's contract or any other caller of it
