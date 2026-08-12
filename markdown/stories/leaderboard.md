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

### Roster Value Leaderboard
**User story**
As a user, I want to see a leaderboard ranked by the current value of everyone's active
roster so that I can compare collections independent of any single week's snapshot.

**Acceptance criteria**
- `GET /leaderboard/roster` ranks users by the total all-time fantasy points of their
  currently active cards (not a locked snapshot, not scoped to any week)
- Tester accounts are excluded
- No authentication required

---

### Top Single-Match Performances
**User story**
As a user, I want to see the standout individual performances across all matches so that I
can spot which players are having exceptional games.

**Acceptance criteria**
- `GET /top` returns the 10 highest single-match fantasy point scores across all ingested
  data, regardless of week or user roster
- Each entry shows the player, avatar, and the raw fantasy points for that match
- No authentication required

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

## MVP Visibility

### MVP Count on the Players Tab
**User story**
As a user browsing the Players tab, I want to see how many times each player has been named
match MVP so that I can spot standout performers at a glance.

**Acceptance criteria**
- `GET /players` includes an `mvp_count` field per player: the count of that player's
  `player_match_stats` rows where `is_mvp` is true
- The Players tab table shows a new "MVPs" column, sortable like the existing columns
- Players who have never been MVP show `0`, not a blank cell

---

### Match History Shows MVP, Opponent, and an OpenDota Link
**User story**
As a user viewing a player's match history in the detail modal, I want to immediately see which
matches they were MVP in, who they played against, and a way to jump to the match on OpenDota,
so that I don't have to cross-reference other tabs or an external site to get that context.

**Acceptance criteria**
- `GET /players/{player_id}`'s `match_history` rows each include `opponent_team_id` and
  `opponent_team_name`, resolved from whichever of the match's `radiant_team_id`/`dire_team_id`
  is not the player's own `team_id` for that match
- The match history table's first column is a dedicated MVP indicator (star), populated only
  for rows where `is_mvp` is true — not appended after another column as a small inline badge
  the way it is today
- An "Opponent" column shows the resolved opponent team name (linking to the team detail modal
  when `opponent_team_id` is available, matching how team names link elsewhere in the app)
- The last column is a link to the match on OpenDota (`https://www.opendota.com/matches/{match_id}`),
  opening in a new tab

---

### Schedule Tab Shows Match MVP
**User story**
As a user browsing the Schedule tab's expanded game rows, I want to see who was MVP for each
individual game so that I don't have to open the match on OpenDota or check Twitch to find out.

**Acceptance criteria**
- `GET /schedule`'s per-game entries (`_build_games()` in `backend/schedule.py`) include
  `mvp_player_id` and `mvp_player_name`, `null` when no MVP has been set for that match
  (matches without an `is_mvp=true` row in `player_match_stats`)
- Each game row shows the MVP player's name as a clickable link (the existing `playerLink()`
  pattern — opens the player detail modal), positioned immediately before the game's duration
- Games with no MVP set show no MVP link in that position — the row layout doesn't shift or
  leave a visibly broken gap

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
