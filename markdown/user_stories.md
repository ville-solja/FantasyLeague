# Fantasy League System Requirements

## Table of Contents

1. [User Accounts and Access](#1-user-accounts-and-access)
   - 1.1 User Registration
   - 1.2 User Login
   - 1.3 User Receive Temporary Password
   - 1.4 User Password Reset
   - 1.5 User Logout
   - 1.6 Admin-only Access
   - 1.7 User Profile Tab
2. [Initial Onboarding and Starter Tokens](#2-initial-onboarding-and-starter-tokens)
   - 2.1 Grant Starter Tokens on Registration
   - 2.2 Token Visibility
   - 2.3 View Cards
   - 2.4 View Weekly Rosters
   - 2.5 View Current and Season Points
3. [Card Collection and Deck Rules](#3-card-collection-and-deck-rules)
   - 3.1 Generate Cards
   - 3.2 Card Drawing
   - 3.3 Remove Cards from Pool *(post-MVP)*
   - 3.4 Assign Randomized Card Rarity
   - 3.5 Assign Randomized Modifiers
   - 3.6 Modifier Management
   - 3.7 View Seasonal Reserve Cards
   - 3.8 View Permanent Collection *(post-MVP)*
4. [Active Lineup and Reserve Management](#4-active-lineup-and-reserve-management)
   - 4.1 Place Cards into Active Slots
   - 4.2 Lock Active Cards
   - 4.3 Admin Move Series Time Manually
   - 4.4 Preserve Points
   - 4.5 View Past Week Snapshots
5. [Token System](#5-token-system)
   - 5.1 Free Weekly Token
   - 5.2 Token Log *(admin)*
   - 5.3 Spend Token to Draw Card
   - 5.4 Redeem Code
   - 5.5 Re-roll Modifiers
6. [Scoring and Points](#6-scoring-and-points)
   - 6.1 Score Active Cards
   - 6.2 Card Modifier Scoring
   - 6.3 Track Season Points
   - 6.4 Track Points per Card
   - 6.5 Prevent Duplicate Scoring
7. [Dota Data Integration](#7-dota-data-integration)
   - 7.1 Fetch Player Data
   - 7.2 Import Match Data
   - 7.3 Handle API Failures
   - 7.4 Auto-ingest on Startup
8. [Leaderboard and Browse](#8-leaderboard-and-browse)
   - 8.1 Season Leaderboard
   - 8.2 Scrollable Leaderboard
   - 8.3 Show User Rank
   - 8.4 Weekly Leaderboard
   - 8.5 Player Performance Browser
   - 8.6 Team Browser
9. [Admin Management](#9-admin-management)
   - 9.1 Generate Promo Codes
   - 9.2 Grant Tokens
   - 9.3 Configure Scoring Weights
   - 9.4 Manage Season Lifecycle
   - 9.5 View System Status
   - 9.6 Start New Season
   - 9.7 Admin Set Series Date
   - 9.8 Recalculate Fantasy Points
   - 9.9 Manual League Ingestion
   - 9.10 Schedule Refresh
10. [UX and Transparency](#10-ux-and-transparency)
    - 10.1 Explain Scoring
    - 10.2 Schedule Tab
11. [Security and Integrity](#11-security-and-integrity)
    - 11.1 Server-side Validation
    - 11.2 Audit Logs
14. [Automated Testing](#14-automated-testing)
    - 14.1 Automated UI Regression Suite
    - 14.2 Continuous Unit Test Automation
    - 14.3 UI Tests in CI
15. [Player Profile Enrichment](#15-player-profile-enrichment)
    - 15.1 View Player Bio in Detail Modal
    - 15.2 Automatic Profile Enrichment After Ingestion
    - 15.3 Admin Manual Re-enrichment Trigger
16. [Version Visibility](#16-version-visibility)
    - 16.1 View Build Version on Every Page
    - 16.2 Environment-Aware Version Display

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
- Invalid credentials show an error
- Session persists according to configured authentication rules
- Logged-out users cannot access pages that require authentication

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
- Current password is required before a new one is accepted

---

### 1.5 User Logout
**User story**
As a logged-in user, I want to log out so that my account stays secure on shared devices.

**Acceptance criteria**
- User can log out from any page
- Session is invalidated on logout

---

### 1.6 Admin-only Access
**User story**
As an admin, I want a protected admin area so that only authorized users can manage league configuration and season operations.

**Acceptance criteria**
- Only admin users can access the admin tab
- Non-admin cannot see the admin tab
- Admin status is verified server-side on every admin request — client-side state alone is not sufficient

---

### 1.7 User Profile Tab
**User story**
As a logged-in user, I want a profile page where I can update my account details.

**Acceptance criteria**
- User can change their display username; must remain unique
- User can change their password via a current password + new password form
- User can optionally link their account to an OpenDota player ID
- When a valid player ID is saved and the player exists in league data, the player's name and avatar are shown as a preview

---

## 2. Initial Onboarding and Starter Tokens

### 2.1 Grant Starter Tokens on Registration
**User story**
As a newly registered user, I want to receive N tokens when I sign up so that I can start building my active lineup immediately.

**Acceptance criteria**
- N tokens are granted at registration (configurable via `INITIAL_TOKENS`)

---

### 2.2 Token Visibility
**User story**
As a user, I want to know how many tokens I currently have.

**Acceptance criteria**
- Token balance is visible in the header across all tabs
- Balance updates immediately after any token-changing event (draw, redeem, weekly grant)
- Token counter on the My Team tab stays in sync with the header balance

---

### 2.3 View Cards
**User story**
As a new user, I want to see the cards I have drawn in my bench and my roster.

**Acceptance criteria**
- Each drawn card displays player identity, rarity, and current week's points
- Cards are clearly shown as benched until placed into the weekly roster
- Cards drawn should be visible in the My Team tab

---

### 2.4 View Weekly Rosters
**User story**
As a new user, I want to see the upcoming week's roster.

**Acceptance criteria**
- Upcoming week's active roster is the default view
- It is clearly visible when the roster will be locked
- Empty active slots are shown explicitly so the user knows how many cards they can still add

---

### 2.5 View Current and Season Points
**User story**
As a user, I want to see my earned points for this week and the whole season.

**Acceptance criteria**
- Should be 0 for a new user with no participation
- Clearly visible in the My Team tab
- Two separate point pools: weekly and season
- Points and past rosters visible per week via the week history selector

---

## 3. Card Collection and Deck Rules

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

## 4. Active Lineup and Reserve Management

### 4.1 Place Cards into Active Slots
**User story**
As a user, I want to assign cards to the upcoming week's roster.

**Acceptance criteria**
- Upcoming week's roster has 5 slots
- User can move a card from bench to active roster (Activate)
- User can move a card from active roster to bench (Bench)
- Only one card may be active from a single player
- Roster changes are only allowed on the editable (upcoming) week, not on locked past weeks

---

### 4.2 Lock Active Cards
**User story**
As a user, I want cards to lock before the week begins.

**Acceptance criteria**
- Auto-lock every Sunday at end of day (UTC)
- UI indicates that the week is locked and shows a locked banner
- User is informed of the upcoming lock date on the My Team tab
- Locked roster is immutable and shown as a read-only snapshot

---

### 4.3 Admin Move Series Time Manually
**User story**
As an admin, I want to correct series timing when teams play out of the regular week cycle.

**Acceptance criteria**
- Ability to see series in the Admin tab
- Ability to select a series and input a corrected match date
- Corrected start date is persisted so that future ingestions do not override it

---

### 4.4 Preserve Points
**User story**
As a user, I want my points to persist across weeks.

**Acceptance criteria**
- Once a week has passed and is scored, the points for that week are stored in the DB
- Total points are derivable from past week records

---

### 4.5 View Past Week Snapshots
**User story**
As a user, I want to review my roster and points from any past week.

**Acceptance criteria**
- Week selector dropdown on the My Team tab lists all season weeks
- Selecting a past locked week shows the immutable roster snapshot for that week
- Weekly points shown reflect only matches played during that specific week
- Current editable roster is always accessible via the selector

---

## 5. Token System

### 5.1 Free Weekly Token
**User story**
As a user, I want a free weekly token.

**Acceptance criteria**
- When the week is locked all users are granted 1 additional token

---

### 5.2 Token Log *(admin)*
**User story**
As an admin, I want visibility into events that have granted tokens.

**Acceptance criteria**
- Weekly free token grants are shown with the total number of users affected
- Admin token grants are listed with time, granting admin, target user, and amount
- Other methods of obtaining tokens (draws, code redemptions) are logged as well

---

### 5.3 Spend Token to Draw Card
**User story**
As a user, I want to draw a card using a token.

**Acceptance criteria**
- 1 token deducted
- Card marked as owned by the user
- User cannot receive a card for a player they already have, unless they have cards from all players
- Card shown to user immediately in a reveal modal

---

### 5.4 Redeem Code
**User story**
As a user, I want to redeem a code.

**Acceptance criteria**
- Valid code grants tokens
- Invalid code shows an error
- One use per user
- Logged in the audit log

---

### 5.5 Re-roll Modifiers
**User story**
As a user, I want to spend a token to re-roll a card's stat modifiers so that I can try for a more useful modifier combination.

**Acceptance criteria**
- Costs 1 token per reroll; returns 409 if the user has no tokens
- All existing modifiers on the card are replaced with a freshly randomised set (same count and bonus rules as draw time)
- Card rarity, player, and league are unchanged — only modifiers are replaced
- Action is recorded in the audit log
- Frontend shows a confirmation prompt before spending the token
- Updated modifier list and remaining token balance are returned in the response

---

## 6. Scoring and Points

### 6.1 Score Active Cards
**Acceptance criteria**
- Uses Dota 2 match data
- Only active (locked) cards score
- No double counting

---

### 6.2 Card Modifier Scoring
**Acceptance criteria**
- Rarity bonus applied on top of raw fantasy points (common +0%, rare +1%, epic +2%, legendary +3% by default)
- Rarity modifiers are configurable environment variables

---

### 6.3 Track Season Points
**Acceptance criteria**
- Persistent total score per user across all locked weeks
- Visible to user on the My Team tab and leaderboard

---

### 6.4 Track Points per Card
**Acceptance criteria**
- Per-week card point contribution visible in the week snapshot view
- Historical tracking via the week selector

---

### 6.5 Prevent Duplicate Scoring
**Acceptance criteria**
- Match events uniquely tracked
- Safe to retry ingestion — already-stored records are not duplicated

---

## 7. Dota Data Integration

### 7.1 Fetch Player Data
**Acceptance criteria**
- Player names and avatar images fetched from OpenDota after ingestion
- Missing or unknown players are handled gracefully

---

### 7.2 Import Match Data
**Acceptance criteria**
- Match data (kills, assists, deaths, GPM, wards, tower damage) fetched per player per match
- Fantasy points calculated and stored per player-match record

---

### 7.3 Handle API Failures
**Acceptance criteria**
- API failures are logged
- Partial ingestion does not corrupt existing data
- Admin can re-trigger ingestion to recover

---

### 7.4 Auto-ingest on Startup
**User story**
As an operator, I want the server to automatically fetch fresh match data when it starts so that the app stays up to date without manual intervention.

**Acceptance criteria**
- League IDs to ingest are configured via `AUTO_INGEST_LEAGUES` environment variable
- Ingestion runs in a background thread on startup; already-stored matches are skipped
- Setting `AUTO_INGEST_LEAGUES=` (empty) disables auto-ingest

---

## 8. Leaderboard and Browse

### 8.1 Season Leaderboard
**Acceptance criteria**
- Users ranked by cumulative fantasy points across all locked weeks
- Points only counted for cards in the user's active roster snapshot for each week
- Rarity modifiers applied

---

### 8.2 Scrollable Leaderboard
**Acceptance criteria**
- Leaderboard visible in its own tab without requiring a login

---

### 8.3 Show User Rank
**Acceptance criteria**
- Logged-in user's rank visible on the leaderboard

---

### 8.4 Weekly Leaderboard
**Acceptance criteria**
- Weekly leaderboard mode available alongside season view
- Week selector to view any past locked week

---

### 8.5 Player Performance Browser
**User story**
As a user, I want to browse all league players and their performance stats.

**Acceptance criteria**
- Players tab lists all players with match count, average points, and total points
- Filterable by player name or team name
- Clicking a player opens a detail modal with full match history and per-match stats (K/A/D, GPM, wards, tower damage, fantasy points)

---

### 8.6 Team Browser
**User story**
As a user, I want to browse all teams in the league.

**Acceptance criteria**
- Teams tab lists all teams with match count and player count
- Clicking a team opens a detail modal showing its player roster with stats

---

## 9. Admin Management

### 9.1 Generate Promo Codes
**User story**
As an admin, I want to create promo codes that grant tokens to users who redeem them.

**Acceptance criteria**
- Admin creates codes with a configurable token amount
- Codes are reusable (multiple users can redeem the same code)
- Each user can only redeem a given code once
- Admin can delete codes

---

### 9.2 Grant Tokens
**User story**
As an admin, I want to manually grant additional tokens to a specific user.

**Acceptance criteria**
- Admin can select any user and grant a specified number of tokens
- Token balance updates immediately
- Logged in the audit log with admin actor, target user, and amount

---

### 9.3 Configure Scoring Weights
**User story**
As an admin, I want to configure the scoring weights for match stats.

**Acceptance criteria**
- Each stat weight (kills, assists, deaths, GPM, wards, tower damage) is editable from environment variables
- Rarity modifier percentages (common, rare, epic, legendary) are also configurable in the environment variables
- Weight changes take effect for future calculations; use Recalculate to apply retroactively

---

### 9.4 Manage Season Lifecycle
**Acceptance criteria**
- Admin can initiate and close a season
- Season configuration (lock dates, league IDs) managed via environment variables

---

### 9.5 View System Status
**Acceptance criteria**
- Admin can see current system state (ingest status, schedule cache status)

---

### 9.6 Start New Season
**Acceptance criteria**
- Admin can reset the database and begin a new season with a fresh configuration

---

### 9.7 Admin Set Series Date
**User Story**
As admin there can be matches that take place outside of their intended week schedule. I need to have the ability to identify the series from a list and set the week when it should have happened instead. This value should not be automatically overwritten by schedule refreshes or other events that touch on the match data.

**Acceptance Criteria**
- Admin view allows selecting a series that took place on the wrong week
- Admin can select the appropriate week
- New datetime is displayed on the schedule instead of the actual match date
- This is done to keep scoring and match history aligned and avoid confusion

---

### 9.8 Recalculate Fantasy Points
**User story**
As an admin, I want to recalculate all historical fantasy points using the current scoring weights.

**Acceptance criteria**
- Recalculate button applies the current weights to all stored player-match stats
- Does not require re-fetching data from OpenDota
- Result shows the number of records updated
- Logged in the audit log

---

### 9.9 Manual League Ingestion
**User story**
As an admin, I want to trigger data ingestion for a specific league at any time.

**Acceptance criteria**
- Admin can enter a league ID and trigger ingestion from the admin tab
- Ingestion fetches new matches, calculates fantasy points, seeds player cards, and enriches player profiles
- Already-stored matches are skipped (idempotent)
- Logged in the audit log

---

### 9.10 Schedule Refresh
**User story**
As an admin, I want to force a refresh of the season schedule from the Google Sheet source.

**Acceptance criteria**
- Refresh button busts the in-memory schedule cache
- Fresh data is fetched immediately from the configured Google Sheets CSV URL
- Logged in the audit log

---

## 10. UX and Transparency

### 10.1 Explain Scoring
**Acceptance criteria**
- Stats and their point mapping are shown to the user in the My Team tab
- Collapsible "How is scoring calculated?" section lists all weighted stats

---

### 10.2 Schedule Tab
**User story**
As a user, I want to see the full season fixture list including past results and upcoming matches.

**Acceptance criteria**
- All series shown in a single chronological list spanning all divisions
- Upcoming series show planned date, team names, and stream link where available
- Past series show actual match start time, series result (e.g. 2–0)
- Team names link to the team detail modal
- Stale cache notice shown if schedule data is outdated

---

## 11. Security and Integrity

### 11.1 Server-side Validation
**Acceptance criteria**
- All state-changing actions (draw, activate, admin ops) are validated server-side
- Client-side `is_admin` flag alone is not sufficient — every admin endpoint re-verifies from the session

---

### 11.2 Audit Logs
**User Story**
As admin I want to have visibility into actions that have taken place on the app.

**Acceptance Criteria**
- Tracks: user registrations, user logins, token draws, code redemptions, admin token grants, league ingestion, weight changes, recalculations, schedule refreshes, code creation and deletion
- Each entry includes timestamp, actor username, action type, and a detail string
- Visible in the Admin tab with most recent entries first
- Admin-only access
- Roster changes and other minor "regular" events are not needed to be tracked

---

### 12.1 Weight calculation
**User Story** 
As admin I want to provide a weight for statistics experts to simulate the values and set the values for the season

**Acceptance criteria**
- Separate endpoint is created outside of the league navigation
- Endpoint is given the matchID
- Endpoint can receive the each scoring stat and value that differs from the default
- Returning value is a simple table containing the players and their fantasypoint values from the given match, with the provided scoring modifiers

### 12.2 Weight statistics
**User Story**
As statistician, I want to have documentation about the weight simulation endpoint, so I can build my own tooling to systematically gather data

**Acceptance criteria**
- Documentation about the endpoint functionality is available to users

---

### 13.1 Twitch integration - MVP selection and token drop
**User story**
As a streamer I want to select the MVP of a match, which also rewards viewers watching the stream.

**Acceptance criteria**
- After a match has ended the streamer presses the quick action button on Twitch to open MVP selection
- The most recent matches (ongoing and ended) in the system are listed with start time and teams. Streamer makes the selection out of these matches.
- Streamer is shown the list of 10 players who participated in the match
- Streamer selects one of the players who participated in the match and confirms
- Confirming the MVP saves the selection and automatically drops tokens to viewers in the presence pool (once per match — re-confirming a different MVP does not re-drop)
- The number of viewers rewarded is capped server-side by `TWITCH_DROP_MAX`
- The broadcaster sees a confirmation showing the MVP name and which viewers received tokens

---

### 13.2 Twitch integration - Viewer token eligibility
**User story**
As a viewer I want to be eligible for token drops while watching the Kanaliiga stream.

**Acceptance criteria**
- Viewers who have linked their Fantasy account and have the Twitch extension panel open are in the drop pool
- Presence in the pool is maintained automatically while the panel is open (heartbeat every ~55 seconds)
- Viewers not in the pool at the time of the MVP confirmation do not receive a token for that match

---

### 13.3 Twitch integraton - Account linking
**User story**
As a user of fantasy league I want to link my twitch profile in fantasy league so I am eligible for drops while watching stream

**Acceptance criteria**
- User can navigate to their profile and start process for linking their Twitch account
- Account linking is done in Twitch recommended fashion that is safe and does not create attack surface against twitch accounts from the fantasy league
- - Safety of linking accounts is documented

---

### 13.4 Twitch integration - Extension
**User story**
As a streamer I want to take FantasyLeague twitch extension into use so I can use extension features that interact with app. I additionally want the buttons and flow to be on quick actions, so they are not conflicting with any other elements.

**Acceptance criteria**
- Streamer is able to take the extension into use with instructions documented in fantasy league app
- Extension buttons are visible in the quick actions

---

## 14. Automated Testing

### 14.1 Automated UI Regression Suite
**User story**
As a developer, I want automated browser tests for critical user flows so that UI regressions are caught without manual testing or agent invocation.

**Acceptance criteria**
- Playwright test suite covers: registration (field validation, duplicate errors), login/logout, card draw modal, roster activate/deactivate, and admin tab access guard
- Tests run against a locally started instance of the app (docker-compose or direct uvicorn)
- Each test is independent — it seeds its own data and does not rely on leftover state from prior tests
- Suite produces a pass/fail exit code usable by CI

---

### 14.2 Continuous Unit Test Automation
**User story**
As a developer, I want the backend pytest suite to run automatically on every push so that failures are caught before they reach production without relying on agent invocation.

**Acceptance criteria**
- GitHub Actions workflow runs `pytest backend/tests/` on every push and pull request to `main`
- Workflow installs dependencies from `backend/requirements.txt` before running
- Failing tests block the PR check
- Test results are visible in the GitHub Actions tab without requiring local setup

---

### 14.3 UI Tests in CI
**User story**
As a developer, I want the Playwright UI suite to run in CI so that browser-level regressions are caught on every pull request.

**Acceptance criteria**
- GitHub Actions workflow starts the app and runs the Playwright suite against it
- App is seeded with test data before the suite runs
- Workflow reports pass/fail per test file
- CI does not require any secrets beyond those already available in the repo

---

## 15. Player Profile Enrichment

### 15.1 View Player Bio in Detail Modal
**User story**
As a user, I want to see a short bio for each player in the player browser so that I can understand who they are beyond raw statistics.

**Acceptance criteria**
- Player detail modal shows a "Player Bio" section with a 2–4 sentence AI-generated excerpt
- Bio highlights at least two notable facts (e.g. signature hero, consecutive seasons, match count)
- Bio is displayed even if only partially enriched; section is hidden if the player has not been enriched yet
- Bio text is fetched lazily when the modal opens, not bulk-loaded with the player list

---

### 15.2 Automatic Profile Enrichment After Ingestion
**User story**
As an operator, I want player profiles to be enriched automatically after match ingestion so that bios stay current without manual intervention.

**Acceptance criteria**
- Enrichment pass runs after every successful ingestion batch
- For each player with an `opendota_id`: fetches top heroes from OpenDota, counts local matches and distinct Kanaliiga seasons
- Facts and generated bio are stored in a `player_profile` table keyed by player ID
- LLM call is skipped for players whose facts have not changed since the last enrichment (24-hour cooldown)

---

### 15.3 Admin Manual Re-enrichment Trigger
**User story**
As an admin, I want to trigger a full profile enrichment pass from the admin tab so that I can refresh bios after changing the AI prompt or onboarding new players.

**Acceptance criteria**
- Admin tab has a "Re-enrich profiles" button that calls `POST /admin/enrich-profiles`
- Response reports number of players enriched and number of errors
- Action is logged in the audit log

---

## 16. Version Visibility

### 16.1 View Build Version on Every Page
**User story**
As a user reporting a bug, I want to see a faint version identifier on every page so that I can include the exact build in my report without needing to know anything about the server.

**Acceptance criteria**
- A version string is visible on every page in a small, low-contrast style that does not compete with the UI
- The string is present regardless of login state
- If `APP_VERSION` is not set the badge shows the literal text `APP_VERSION` as a fallback so that the element is always visible and it is immediately clear which variable to configure

---

### 16.2 Environment-Aware Version Display
**User story**
As an operator, I want the version display to show the image SHA in test and both the image SHA and release tag in production, so that the right level of detail is available in each environment.

**Acceptance criteria**
- Setting only `APP_VERSION` (image SHA) displays that value alone
- Setting both `APP_VERSION` and `APP_RELEASE` displays both values (e.g. `v1.2.0 · b06e0c4`)
- Values are served from the existing `/config` endpoint so no additional HTTP request is needed
- `.env.example` documents both variables
- The value of `APP_VERSION` is injected by CI as a Docker build argument (`--build-arg APP_VERSION=<git-sha>`) and passed through to the container via `ENV APP_VERSION` in the Dockerfile, so no manual step is required after a build

---