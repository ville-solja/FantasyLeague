# Fantasy League System Requirements

## Table of Contents

1. [User Accounts and Access](#1-user-accounts-and-access)
   - 1.1 User Registration
   - 1.2 User Login
   - 1.3 User Receive Temporary Password
   - 1.4 User Password Reset
   - 1.5 User Logout
   - 1.6 Admin-only Access
2. [Initial Onboarding and Starter Tokens](#2-initial-onboarding-and-starter-tokens)
   - 2.1 Grant Starter Tokens on Registration
   - 2.2 Token Visibility
   - 2.3 View Cards
   - 2.4 View Weekly Rosters
   - 2.5 View Current and Season Points
   - 2.6 View Collection *(post-MVP)*
   - 2.7 Configurable Token Name
3. [Card Collection and Deck Rules](#3-card-collection-and-deck-rules)
   - 3.1 Generate Cards
   - 3.2 Card Drawing
   - 3.3 Remove Cards from Pool *(post-MVP)*
   - 3.4 Assign Randomized Card Rarity
   - 3.5 Assign Randomized Modifiers
   - 3.6 Modifier Management
   - 3.7 View Seasonal Reserve Cards
   - 3.8 View Permanent Collection *(post-MVP, duplicate of 2.6)*
4. [Active Lineup and Reserve Management](#4-active-lineup-and-reserve-management)
   - 4.1 Place Cards into Active Slots
   - 4.2 Lock Active Cards
   - 4.3 Admin Move Series Time Manually
   - 4.4 Preserve Points
5. [Token System](#5-token-system)
   - 5.1 Free Weekly Token
   - 5.2 Token Log *(admin)*
   - 5.3 Spend Token to Draw Card
   - 5.4 Redeem Code
   - 5.5 Generate Codes *(admin, duplicate of 9.1)*
   - 5.6 View Token Balance *(duplicate of 2.2)*
   - 5.7 Re-roll Modifiers
6. [Scoring and Points](#6-scoring-and-points)
   - 6.1 Score Active Cards
   - 6.2 Configure Event Weights *(admin, duplicate of 9.3)*
   - 6.3 Card Modifier Scoring
   - 6.4 Track Season Points
   - 6.5 Track Points per Card
   - 6.6 Prevent Duplicate Scoring
7. [Dota Data Integration](#7-dota-data-integration)
   - 7.1 Fetch Player Data
   - 7.2 Import Match Data
   - 7.3 Handle API Failures
8. [Leaderboard](#8-leaderboard)
   - 8.1 Season Leaderboard
   - 8.2 Scrollable Leaderboard
   - 8.3 Show User Rank
   - 8.4 Weekly Leaderboard
9. [Admin Management](#9-admin-management)
   - 9.1 Generate Codes *(duplicate of 5.5)*
   - 9.2 Grant Tokens
   - 9.3 Configure Scoring *(duplicate of 6.2)*
   - 9.4 Manage Season Lifecycle
   - 9.5 View System Status
   - 9.6 Start New Season
10. [UX and Transparency](#10-ux-and-transparency)
    - 10.1 Explain Scoring
11. [Security and Integrity](#11-security-and-integrity)
    - 11.1 Server-side Validation
    - 11.2 Audit Logs
12. [Implemented — Not Yet in Stories](#12-implemented--not-yet-in-stories)
    - 12.1 Player Browser
    - 12.2 Team Browser
    - 12.3 Schedule Tab
    - 12.4 User Profile Tab
    - 12.5 Week History Selector
    - 12.6 Auto-ingest on Startup
    - 12.7 Admin: Recalculate Points
    - 12.8 Admin: Manual League Ingestion
    - 12.9 Admin: Schedule Refresh
    - 12.10 Admin: Grant Draws to User

---

## 1. User Accounts and Access

### 1.1 User Registration
**User story**
As a new user, I want to register an account by providing a unique email and username so that I can participate in the fantasy league.

**Acceptance criteria**
- User can register with required credentials
- Registration fails if the username or email is already in use
- After successful registration, the user account is created
- After successful registration, the user receives their initial tokens automatically
- The system records the date and time of registration

---

### 1.2 User Login
**User story**
As a registered user, I want to log in securely so that I can access my cards, team, and leaderboard.

**Acceptance criteria**
- User can log in with valid credentials (username AND password)
- Invalid credentials show an error: "Login failed – Invalid credentials."
- Logged-in users are redirected to their main dashboard
- Session persists according to configured authentication rules
- Logged-out users cannot access authenticated pages

---

### 1.3 User Receive Temporary Password
**User story**
As a user, I want to have the ability to receive a new password in case I've forgotten the current one.

**Acceptance criteria**
- User that does not remember their password has the option to send a temporary password to the email listed on their profile
- If the user does not have an email, an error is given informing them of the inability to reset

---

### 1.4 User Password Reset
**User story**
As a user, once logged in, I want to be able to reset my password.

**Acceptance criteria**
- Profile page has a flow for setting a new password

---

### 1.5 User Logout
**User story**
As a logged-in user, I want to log out so that my account stays secure on shared devices.

**Acceptance criteria**
- User can log out from any page
- Session is invalidated on logout
- User is redirected to the leaderboard screen (the only tab visible without login)

---

### 1.6 Admin-only Access
**User story**
As an admin, I want a protected admin area so that only authorized users can manage league configuration and season operations.

**Acceptance criteria**
- Only admin users can access the admin tab
- Non-admin cannot see the admin tab
- Admin authentication is tied to specific login credentials

---

## 2. Initial Onboarding and Starter Tokens

### 2.1 Grant Starter Tokens on Registration
**User story**
As a newly registered user, I want to receive N tokens when I sign up so that I can start building my active lineup immediately.

**Acceptance criteria**
- N tokens are granted at registration

---

### 2.2 Token Visibility
**User story**
As a user, I want to know how many tokens I currently have.

**Acceptance criteria**
- Token amount is visible across all tabs in shared UI elements

> ⚠️ *Duplicate of 5.6 — consolidate into one story.*

---

### 2.3 View Cards
**User story**
As a new user, I want to see the cards I have drawn in my bench and my roster.

**Acceptance criteria**
- Each drawn card displays player identity, quality, and modifiers
- Cards are clearly shown as benched until placed into the weekly roster
- Cards drawn should be visible in the "My Team" tab

---

### 2.4 View Weekly Rosters
**User story**
As a new user, I want to see the upcoming week's roster.

**Acceptance criteria**
- Upcoming week's active roster should be the default view
- All active slots should be initially carried over from the previous week unless the user makes changes
  - This limits the effect of missing roster updates for a particular week
- It should be clearly visible in the UI when the roster is getting locked (every Sunday at end of day)

---

### 2.5 View Current and Season Points
**User story**
As a new user, I want to see my earned points for this week and the whole season.

**Acceptance criteria**
- Should be 0 for a new user with no participation
- Clearly visible in the UI
- Two separate point pools: weekly and season
- Points and past rosters visible per week via weekly roster selection

---

### 2.6 View Collection
**User story**
As a long-time user, I want to have a collection of player cards from multiple seasons.

**Phase:** Not included in the MVP scope.

**Acceptance criteria**
- Cards should show up in my Collection
- Collection should be a separate tab

> ⚠️ *Duplicate of 3.8 — consolidate into one story.*

---

### 2.7 Configurable Token Name
**User story**
As a league administrator, I want the in-game currency name to match the league's branding so that the game feels thematic for participants.

**Acceptance criteria**
- Token name is configurable via an environment variable (`TOKEN_NAME`)
- All UI elements use the configured name consistently
- Default is "Tokens" when the variable is not set
- The initial token grant amount is also configurable via `INITIAL_TOKENS`

---

## 3. Card Collection and Deck Rules

### 3.1 Generate Cards
**User story**
As a system administrator, I want the seasonal card deck to reflect real Dota 2 league players participating in the season.

**Acceptance criteria**
- Admin can import league players into the card deck based on a given player ID list
  - This is particularly useful pre-season when there is no league data to ingest
- Admin can provide a league ID for ingestion, which generates cards based on the obtained player list
- Permanent pool avoids duplicates
- Shared deck among all users
- Deck contains per player:
  - 1 golden
  - 2 purple
  - 4 blue
  - 8 white cards

---

### 3.2 Card Drawing
**User story**
As a user, I want to be able to draw cards from the deck.

**Acceptance criteria**
- User can draw a card, given they have the necessary token
- Card is shown to the user
- Card is added to the user's active roster if empty slots exist, otherwise to their bench

---

### 3.3 Remove Cards from Pool
**User story**
As a system administrator, I want to remove players from card pools.

**Phase:** Not in MVP. A clear justification is needed, e.g. a player known to be unable to participate for the whole season.

**Acceptance criteria**
- Admin selects and deletes a player from the restricted admin tab
- Users receive 1 token per removed card
- All card types for that player are removed from the season

---

### 3.4 Assign Randomized Card Rarity
**User story**
As a user, I want each drawn card to have a rarity.

**Acceptance criteria**
- Cards that are generated have a rarity

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
- Modifiers manageable from the admin tab
- Individual cards are not modified — entire modifier weights are adjusted at once
- Modifier changes are not applied retroactively to already-generated fantasy points

---

### 3.7 View Seasonal Reserve Cards
**User story**
As a user, I want to browse my roster and bench.

**Acceptance criteria**
- All benched cards are shown in the My Team tab
- Cards are either in the currently active roster for the upcoming week, or in the bench
- Show player, quality, and points accumulated over the season
- Supports filtering/sorting

---

### 3.8 View Permanent Collection
**User story**
As a user, I want to track cards across seasons.

**Phase:** Not in MVP.

**Acceptance criteria**
- Shows all owned cards
- Higher quality replaces lower
- No duplicates
- No gameplay effect
- Supports filtering
- Past season cards are stored separately so they are not included in current season logic

> ⚠️ *Duplicate of 2.6 — consolidate into one story.*

---

## 4. Active Lineup and Reserve Management

### 4.1 Place Cards into Active Slots
**User story**
As a user, I want to assign cards to the upcoming week's roster.

**Acceptance criteria**
- Upcoming week's roster has 5 slots
- One card per slot
- Cards lock Sunday EoD
- User can set a card from bench to the upcoming week's roster
- User can bench a card from the upcoming week's roster
- Only one card may be active from a single player

---

### 4.2 Lock Active Cards
**User story**
As a user, I want cards to lock before the week begins.

**Acceptance criteria**
- Auto-lock Sunday EoD
- UI indicates that the week is locked
- User is informed of the upcoming lock on the My Team tab

---

### 4.3 Admin Move Series Time Manually
**User story**
As an admin, I want to correct series timing when teams play out of the regular week cycle.

**Acceptance criteria**
- Ability to see series in the Admin tab
- Ability to select a series and input a corrected match date
- Corrected start date is persisted so that future ingestions do not override it
  - Particularly the schedule sheet sync

---

### 4.4 Preserve Points
**User story**
As a user, I want my points to persist across weeks.

**Acceptance criteria**
- Once a week has passed and is scored, the points for that week are stored in the DB
- Total points are derivable from past week records

---

## 5. Token System

### 5.1 Free Weekly Token
**User story**
As a user, I want a free weekly token.

**Acceptance criteria**
- When the week is locked all users are granted 1 additional token

---

### 5.2 Token Log
**User story**
As an admin, I want visibility into events that have granted tokens.

**Acceptance criteria**
- Weekly free token grants are shown with the total number of users affected
- Admin token grants are listed with time, granting admin, target user, and amount
- Other methods of obtaining tokens are logged as well

---

### 5.3 Spend Token to Draw Card
**User story**
As a user, I want to draw a card using a token.

**Acceptance criteria**
- 1 token deducted
- Card marked as owned by the user
- User cannot receive a card for a player they already have, unless they have cards from all players
  - Exception: higher-rarity duplicates are allowed
- Card shown to user immediately

---

### 5.4 Redeem Code
**User story**
As a user, I want to redeem a code.

**Acceptance criteria**
- Valid code grants tokens
- Invalid code shows an error
- One use per user
- Logged

---

### 5.5 Generate Codes *(Admin)*
**Acceptance criteria**
- Admin creates reusable codes
- Token amount configurable
- Server-side validation

> ⚠️ *Duplicate of 9.1 — consolidate into one story.*

---

### 5.6 View Token Balance
**Acceptance criteria**
- Token balance visible in UI

> ⚠️ *Duplicate of 2.2 — consolidate into one story.*

---

### 5.7 Re-roll Modifiers
**User story**
As a user, I want to re-roll a card's modifiers and quality.

**Acceptance criteria**
- Costs 1 token
- Confirmation popup
- Modifiers and quality replaced
- Logged

---

## 6. Scoring and Points

### 6.1 Score Active Cards
**Acceptance criteria**
- Uses Dota 2 match data
- Only active (locked) cards score
- No double counting

---

### 6.2 Configure Event Weights *(Admin)*
**Acceptance criteria**
- Adjustable weights
- Only affects future scoring
- Logged

> ⚠️ *Duplicate of 9.3 — consolidate into one story.*

---

### 6.3 Card Modifier Scoring
**Acceptance criteria**
- Modifiers map to match events
- Bonus points applied accordingly

---

### 6.4 Track Season Points
**Acceptance criteria**
- Persistent total score per user
- Visible to user

---

### 6.5 Track Points per Card
**Acceptance criteria**
- Per-week card contribution visible
- Historical tracking

---

### 6.6 Prevent Duplicate Scoring
**Acceptance criteria**
- Match events uniquely tracked
- Safe to retry ingestion

---

## 7. Dota Data Integration

### 7.1 Fetch Player Data
### 7.2 Import Match Data
### 7.3 Handle API Failures

*(All include validation, logging, retry handling, and admin visibility.)*

---

## 8. Leaderboard

### 8.1 Season Leaderboard
- Ranked by total season points

### 8.2 Scrollable Leaderboard
- Visible in a separate tab

### 8.3 Show User Rank
- Always visible to logged-in user

### 8.4 Weekly Leaderboard
- Weekly ranking support

---

## 9. Admin Management

### 9.1 Generate Codes
> ⚠️ *Duplicate of 5.5 — consolidate into one story.*

### 9.2 Grant Tokens
### 9.3 Configure Scoring
> ⚠️ *Duplicate of 6.2 — consolidate into one story.*

### 9.4 Manage Season Lifecycle
### 9.5 View System Status
### 9.6 Start New Season

---

## 10. UX and Transparency

### 10.1 Explain Scoring
- Show stats and their point mapping
- UI explanation available

---

## 11. Security and Integrity

### 11.1 Server-side Validation
- All actions validated server-side

### 11.2 Audit Logs
- Tracks:
  - Registration rewards
  - Token usage
  - Draws
  - Re-rolls
  - Admin actions
  - Season resets
- Includes timestamp and actor

---

## 12. Implemented — Not Yet in Stories

These features exist in the current implementation but have no corresponding user story. Each should be evaluated: write a story to formalise it, or remove it if no longer needed.

### 12.1 Player Browser
Players tab with searchable list of all league players, showing match count, average and total fantasy points. Clicking a player opens a detail modal with full match history and per-match stats.

### 12.2 Team Browser
Teams tab listing all teams with match count and player count. Clicking a team opens a detail modal showing its current roster.

### 12.3 Schedule Tab
Shows the full season schedule, including upcoming series and past results. Team names are clickable and link to 12.2.

### 12.4 User Profile Tab
Allows the logged-in user to edit their display name and link their OpenDota player ID to their account.

### 12.5 Week History Selector
Dropdown on the My Team tab lets users view any past locked week's snapshot roster and the points it earned during that week.

### 12.6 Auto-ingest on Startup
The server automatically ingests configured league IDs when it starts, controlled by the `AUTO_INGEST_LEAGUES` environment variable. Skips data already present in the database.

### 12.7 Admin: Recalculate Points
Admin action that recalculates all stored fantasy points using the current modifier weights. Useful after a weight adjustment.

### 12.8 Admin: Manual League Ingestion
Admin can trigger ingestion of a specific league by ID from the admin tab, outside of the auto-ingest flow.

### 12.9 Admin: Schedule Refresh
Admin can force a re-fetch of the season schedule from the configured Google Sheets source.

### 12.10 Admin: Grant Draws to User
Admin can grant additional card draws to a specific user, overriding their default draw limit.
