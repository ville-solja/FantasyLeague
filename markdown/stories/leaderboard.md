# Leaderboard and Browse

## Leaderboard

### Season Leaderboard
**Acceptance criteria**
- Users ranked by cumulative fantasy points across all locked weeks
- Points only counted for cards in the user's active roster snapshot for each week
- Rarity and card modifiers applied
- Tester accounts excluded from all public views

---

### Weekly Leaderboard
**Acceptance criteria**
- Weekly leaderboard mode available alongside season view
- Week selector to view any past locked week
- Same modifier and snapshot rules as season view

---

### Leaderboard Access
**Acceptance criteria**
- Leaderboard visible in its own tab without requiring a login
- Logged-in user's rank highlighted

---

## Player and Team Browse

### Player Performance Browser
**User story**
As a user, I want to browse all league players and their performance stats.

**Acceptance criteria**
- Players tab lists all players with match count, average points, and total points
- Filterable by player name or team name
- Clicking a player opens a detail modal with full match history and per-match stats (fantasy points, K/A/D, GPM, plus the expanded scoring stat fields stored per match)

---

### Team Browser
**User story**
As a user, I want to browse all teams in the league.

**Acceptance criteria**
- Teams tab lists all teams with match count and player count
- Clicking a team opens a detail modal showing its player roster with stats

---

## Weight Simulation

### Simulate Fantasy Points
**User story**
As an admin or statistician, I want to provide custom scoring weights and a match ID to see how scores would change.

**Acceptance criteria**
- `POST /simulate/{match_id}` accepts per-stat weight overrides; unspecified stats fall back to current DB defaults
- Returns a ranked list of players with their fantasy points under the provided weights
- No authentication required so statisticians can call this without an account

---

### Simulation Endpoint Documentation
**User story**
As a statistician, I want documentation about the weight simulation endpoint so I can build my own tooling.

**Acceptance criteria**
- `GET /simulate` returns machine-readable documentation of the endpoint: parameters, response shape, examples
