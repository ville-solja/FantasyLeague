# 3. Card Collection and Deck Rules

### 3.1 Generate Cards
**User story**
As a system administrator, I want the seasonal card deck to reflect real Dota 2 league players participating in the season.

**Acceptance criteria**
- Admin can provide a league ID for ingestion, which generates cards based on the player list obtained from match data
- Deck avoids duplicate seeding (idempotent)
- Shared deck among all users
- Deck contains per player: 1 legendary, 2 epic, 4 rare, 8 common

---

### 3.2 Card Drawing
**User story**
As a user, I want to be able to draw cards from the deck.

**Acceptance criteria**
- User can draw a card if they have at least 1 token
- Card is shown to the user in a reveal modal
- Card is added to the user's active roster if empty slots exist, otherwise to their bench
- System prefers players the user does not yet own; only allows duplicates when the user owns all available players

---

### 3.3 Remove Cards from Pool
**User story**
As a system administrator, I want to remove players from card pools.

**Phase:** Not in MVP. A clear justification is needed, e.g. a player known to be unable to participate for the whole season.

**Acceptance criteria**
- Admin selects and deletes a player from the admin tab
- Users receive 1 token per removed card
- All card types for that player are removed from the season

---

### 3.4 Card Rarity
**User story**
As a user, I want each drawn card to have a rarity.

**Acceptance criteria**
- Cards are generated with a fixed rarity (common / rare / epic / legendary) set at deck creation time, not at draw time
- Rarity is shown on the card in the reveal modal and roster views

---

### 3.5 Assign Randomized Modifiers
**User story**
As a user, I want each card to have a defined number of modifiers.

**Acceptance criteria**
- Modifiers are stored in the cards table
- Visible whenever the card is accessed

---

### 3.6 Modifier Management
**User story**
As an admin, I want to be able to adjust the weights of modifiers in order to tune balance.

**Acceptance criteria**
- Modifiers manageable from environment variables
- Individual cards are not modified — entire modifier weights are adjusted at once
- Modifier changes are not applied retroactively without an explicit recalculate action

---

### 3.7 View Seasonal Reserve Cards
**User story**
As a user, I want to browse my roster and bench.

**Acceptance criteria**
- All benched cards are shown in the My Team tab
- Cards are either in the currently active roster for the upcoming week, or in the bench
- Shows player, rarity, and points accumulated during the current week
- Bench is hidden for locked past weeks (read-only snapshot view)

---

### 3.8 View Permanent Collection
**User story**
As a user, I want to track cards across seasons.

**Phase:** Not in MVP.

**Acceptance criteria**
- Shows all owned cards across seasons
- Higher quality replaces lower; no duplicates
- No gameplay effect
- Supports filtering
- Past season cards are stored separately so they are not included in current season logic

---

### 3.9 Card Visual Identity
**User story**
As a user, I want each card to display the player's name, team name, photo, and team emblem so I can identify the player and team at a glance without reading separate UI text.

**Acceptance criteria**
- Player name is printed on the card image in the name plate area (uppercased, truncated if too long)
- Team name is printed below the player name on the card image
- Player avatar (from OpenDota) is composited as a circular portrait on the card image
- Team logo (from local Dotabuff cache, HTTP fallback) is composited as a smaller circular badge on the card image
- If avatar or logo is unavailable, the card still renders correctly with the slot left empty
- During the draw reveal animation, player and team names are sourced from the card PNG only — they are not duplicated in the HTML below the image

---

### 3.10 Rarity-Distinct Card Design
**User story**
As a user, I want each rarity tier to have a visually distinct card frame so I can identify rarity from the card art alone.

**Acceptance criteria**
- Each rarity (Common, Rare, Epic, Legendary) uses a separate template PNG with its own border and colour scheme
- Rarity frame is always visible regardless of player or team
- Card image is returned correctly for all four rarities

---

### 3.11 Modifier Labels on Card Image
**User story**
As a user, I want my card's stat modifiers printed directly on the card image so the bonus is always visible without opening a detail view.

**Acceptance criteria**
- Each active modifier is shown in the lower band of the card as `STAT +X%`
- After a reroll, the card image updates immediately to reflect the new modifiers
- Cards with no modifiers (e.g. Common) show no modifier text in that area

---

### 3.12 Replaceable Card Template Artwork
**User story**
As an operator, I want to update card template artwork for each rarity by replacing files so the visual design can be refreshed between seasons without code changes.

**Acceptance criteria**
- Templates are loaded from a configurable assets directory at startup
- Replacing any of the four template PNGs takes effect on the next card image request
- Missing templates fail with a clear error rather than silently using a wrong rarity
