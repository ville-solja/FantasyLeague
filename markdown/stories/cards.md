# Cards

### Generate Deck
**User story**
As a system administrator, I want the seasonal card deck to reflect real Dota 2 league players participating in the season.

**Acceptance criteria**
- Admin can provide a league ID for ingestion, which generates cards based on the player list obtained from match data
- Deck avoids duplicate seeding (idempotent)
- Shared deck among all users
- Deck contains per player: 1 legendary, 2 epic, 4 rare, 8 common

---

### Draw Card
**User story**
As a user, I want to be able to draw cards from the deck.

**Acceptance criteria**
- User can draw a card if they have at least 1 token
- Card is shown to the user in a reveal modal
- Card is added to the user's active roster if empty slots exist, otherwise to their bench
- System prefers players the user does not yet own; only allows duplicates when the user owns all available players

---

### Card Rarity
**User story**
As a user, I want each drawn card to have a rarity.

**Acceptance criteria**
- Cards are generated with a fixed rarity (common / rare / epic / legendary) set at deck creation time, not at draw time
- Rarity is shown on the card in the reveal modal and roster views

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

### Mid-Season Card Top-Up
**User story**
As an admin, I want to add a new batch of cards to the deck mid-season so that new users joining late have cards to draw.

**Acceptance criteria**
- Admin can trigger a top-up that adds one additional set (1L/2E/4R/8C per player) to the unowned pool
- Top-up is idempotent per generation — running it twice does not double the pool
- Existing owned cards are unaffected
- Audit log records the top-up event
