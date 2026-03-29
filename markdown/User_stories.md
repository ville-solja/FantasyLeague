# Fantasy League System Requirements

## 1. User Accounts and Access

### 1.1 User Registration
**User story**  
As a new user, I want to register an account by providing a unique email and username so that I can participate in the fantasy league.

**Acceptance criteria**
- User can register with required credentials  
- Registration fails if the username or email is already in use  
- After successful registration, the user account is created  
- After successful registration, the user receives their initial 5 Kana tokens automatically  
- The system records the date and time of registration  

---

### 1.2 User Login
**User story**  
As a registered user, I want to log in securely so that I can access my cards, team, and leaderboard.

**Acceptance criteria**
- User can log in with valid credentials (email and username)  
- Invalid credentials show an error: “Login failed – Invalid credentials.”  
- Logged-in users are redirected to their main dashboard  
- Session persists according to configured authentication rules  
- Logged-out users cannot access authenticated pages  

---

### 1.3 User Logout
**User story**  
As a logged-in user, I want to log out so that my account stays secure on shared devices.

**Acceptance criteria**
- User can log out from any authenticated page  
- Session is invalidated on logout  
- User is redirected to the login screen  

---

### 1.4 Admin-only Access
**User story**  
As an admin, I want a protected admin area so that only authorized users can manage league configuration and season operations.

**Acceptance criteria**
- Only admin users can access admin routes  
- Non-admin cannot see the admin page  
- Admin authentication is tied to specific login credentials  

---

## 2. Initial Onboarding and Starter Tokens

### 2.1 Grant Starter Tokens on Registration
**User story**  
As a newly registered user, I want to receive 8 Kana tokens when I sign up so that I can start building my active lineup immediately.

**Acceptance criteria**
- Exactly 8 Kana tokens are granted at registration  
- The Kana tokens are visible in the UI  

---

### 2.3 View Reserve and Collection
**User story**  
As a new user, I want to see the cards I have drawn in my Reserve and my Collection.

**Acceptance criteria**
- Each drawn card displays player identity, quality, and both stats  
- Cards are clearly shown as reserve cards until placed into active slots  
- Cards drawn should show up in my Reserve view  
- Cards should show up in my Collection  
- Collection should be a separate tab  
- Reserve and Active should be separate views  

---

### 2.4 View Weekly Rosters
**User story**  
As a new user, I want to see the next week’s active roster.

**Acceptance criteria**
- Upcoming week’s active roster should be the default view  
- All active slots should be empty by default  
- It should be clearly visible in the UI when the roster is getting locked (every Sunday 24:00)  

---

### 2.5 View Current and Season Points
**User story**  
As a new user, I want to see my earned points for this week and whole season.

**Acceptance criteria**
- Should be 0 for a new user with no participation  
- Clearly visible in the UI  
- Two separate point pools: weekly and season  
- Points and past rosters visible per week via dropdown  

---

## 3. Card Collection and Deck Rules

### 3.1 Generate Cards for League Players
**User story**  
As a system administrator, I want the seasonal card deck to reflect real Dota 2 league players.

**Acceptance criteria**
- Admin can import league players into card deck  
- Each player has one base card definition  
- Draws create user-owned instances  
- Admin can reload deck before season start  
- Permanent pool avoids duplicates  
- Shared deck among users  
- Deck contains:
  - 1 golden  
  - 2 purple  
  - 4 blue  
  - 8 white cards per player  

---

### 3.2 Remove Cards from Pool
**User story**  
As a system administrator, I want to remove players from card pools.

**Acceptance criteria**
- Admin selects and deletes player  
- Users receive 1 Kana token per removed card  
- All card types removed from season  

---

### 3.3 Assign Randomized Card Quality
**User story**  
As a user, I want each drawn card to have randomized quality.

**Acceptance criteria**
- Qualities: white, blue, purple, golden  
- Probability matches deck distribution  
- Stored and visible in UI  

---

### 3.4 Assign Two Randomized Stats
**User story**  
As a user, I want each card to have two stats.

**Acceptance criteria**
- Exactly 2 stats per card  
- Stats follow rules  
- Stored and visible  
- Different copies may differ  
- Stats generate points  
- Points multiplied by quality  

---

### 3.5 View Seasonal Reserve Cards
**User story**  
As a user, I want to browse my seasonal cards.

**Acceptance criteria**
- All cards visible  
- Status: active/reserve  
- Show player, quality, stats, points  
- Supports filtering/sorting  

---

### 3.6 View Permanent Collection
**User story**  
As a user, I want to track cards across seasons.

**Acceptance criteria**
- Shows all owned cards  
- Higher quality replaces lower  
- No duplicates  
- No gameplay effect  
- Supports filtering  

---

## 4. Active Lineup and Reserve Management

### 4.1 Place Cards into Active Slots
**User story**  
As a user, I want to assign cards to 5 active slots.

**Acceptance criteria**
- 5 slots available  
- One card per slot  
- Slots are equal  
- Cards lock Sunday 24:00  

---

### 4.2 Lock Active Cards
**User story**  
As a user, I want cards to lock before week begins.

**Acceptance criteria**
- Auto-lock Sunday  
- UI indicates lock state  

---

### 4.3 Resetting Cards
**User story**  
As a user, I want to reset active cards before lock.

**Acceptance criteria**
- Reset individual or all non-locked cards  
- Not available when locked  

---

### 4.5 Preserve Points
**User story**  
As a user, I want my points to persist across weeks.

**Acceptance criteria**
- Points carry over  
- Past weeks stop updating  
- Past data accessible  

---

## 5. Kana Token System

### 5.1 Free Weekly Token
**User story**  
As a user, I want a free weekly token.

**Acceptance criteria**
- 1 token every Sunday  
- History recorded  

---

### 5.3 Spend Token to Draw Card
**User story**  
As a user, I want to draw a card using a token.

**Acceptance criteria**
- Costs 1 token  
- Confirmation popup  
- Card added to reserve & collection  
- Duplicate rules apply  
- Deck updated  
- UI feedback shown  

---

### 5.4 Redeem Kana Code
**User story**  
As a user, I want to redeem a code.

**Acceptance criteria**
- Valid code grants tokens  
- Invalid shows error  
- One use per user  
- Logged  

---

### 5.5 Generate Kana Codes (Admin)
**Acceptance criteria**
- Admin creates reusable codes  
- Token amount configurable  
- Server-side validation  

---

### 5.6 View Token Balance
**Acceptance criteria**
- Visible in UI  
- Updates instantly  
- Min: 0, Max: 100  

---

### 5.7 Re-roll Stats
**User story**  
As a user, I want to re-roll stats and quality.

**Acceptance criteria**
- Costs 1 token  
- Confirmation popup  
- Stats + quality replaced  
- Logged  

---

## 6. Scoring and Points

### 6.1 Score Active Cards
**Acceptance criteria**
- Uses Dota 2 match data  
- Only active cards score  
- No double counting  

---

### 6.2 Configure Event Weights (Admin)
**Acceptance criteria**
- Adjustable weights  
- Only affects future scoring  
- Logged  

---

### 6.3 Card Stat Scoring
**Acceptance criteria**
- Stats map to events  
- Bonus points applied  

---

### 6.4 Track Season Points
**Acceptance criteria**
- Persistent total score  
- Visible to user  

---

### 6.5 Track Points per Card
**Acceptance criteria**
- Per-week card contribution visible  
- Historical tracking  

---

### 6.6 Prevent Duplicate Scoring
**Acceptance criteria**
- Events uniquely tracked  
- Safe retries  

---

## 7. Dota Data Integration

### 7.1 Fetch Player Data
### 7.2 Import Match Data
### 7.3 Handle API Failures

*(All include validation, logging, retry handling, and admin visibility.)*

---

## 8. Leaderboard

### 8.1 Season Leaderboard
- Ranked by total points  

### 8.2 Scrollable Leaderboard
- Separate tab  

### 8.3 Show User Rank
- Always visible  

### 8.4 Weekly Leaderboard
- Weekly ranking support  

---

## 9. Admin Management

### 9.1 Generate Codes  
### 9.2 Grant Tokens  
### 9.3 Configure Scoring  
### 9.4 Manage Season Lifecycle  
### 9.5 View System Status  
### 9.6 Start New Season  

---

## 10. UX and Transparency

### 10.1 Explain Scoring
- Show stats and mapping  
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