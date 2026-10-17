# Leaderboard and Browse

## Leaderboard

### Season Leaderboard
**Acceptance criteria**
- Users ranked by cumulative fantasy points across all locked weeks
- Points only counted for cards in the user's active roster snapshot for each week, after bench substitution (subbed-in bench cards count, subbed-out cards don't)
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

## Player Popup Visualizations

*(Not yet implemented)* Plan: `markdown/plans/plan-issue-208-player-popup-visualizations.md`.

### Season Form at a Glance
**User story**
As a fantasy manager, I want to see a player's season as a chart of match scores, so that I can tell whether they're in form before drafting or keeping their card.

**Acceptance criteria**
- **Form chart** under the header: one bar per match, oldest left. Bar height is fantasy points, grouped under scoring-week labels ("W3").
- **Markers:**
  - MVP is a star above the bar;
  - a win is a filled square under the bar, a loss a hollow one, so the result never relies on colour;
  - an excluded match is a dashed ghost bar labelled "Not scored";
  - a partial-stats match is hatched.
- **Reference lines:** the player's average (solid) and the league average per match (dashed), each labelled.
- **Bars are buttons:**
  - hover, focus or tap shows a tooltip with date, opponent, hero, result, points and K/D/A, using the same tooltip component as #50's pips;
  - activating a bar scrolls to and highlights that match's row in the history.
- **Summary tiles** above the chart: Matches with W–L, Avg pts with the league rank ("#7 of 84"), Total pts, Best match (with its opponent), and MVPs.
- **Accessibility:** the chart has an `aria-label` summary ("12 matches, average 14.2, last 3 above average"). The history table is its data equivalent.
- **Motion:** the bars grow once on open; nothing moves under reduced motion.
- **Empty state:** with no matches, the chart, tiles and the sections below are replaced by "No matches yet this season."

### Where a Player's Points Come From
**User story**
As a fantasy manager, I want to see which stats earn a player their points, so that I understand their playstyle and know which card modifiers are worth the most on their card.

**Acceptance criteria**
- **Points by source:** one 100 % stacked bar plus a row per source, giving average points per scored match, share of the total, and a marker for the league's average for that source.
- **Sources,** from `SCORING_STATS` and the death pool: Kills, Assists, Farm (last hits and denies), GPM, Vision (observer wards), Objectives (towers and Roshan), Teamfight, Stuns, Jungle and runes (camps and runes), First blood, Survival (death pool), and MVP bonus.
- **Modifier value:** a line "A +10 % modifier is worth most on: Kills (+0.42 / match), GPM (+0.38)". It uses `modifier_bonus_pct` and each stat's average points, per stat rather than per group, and the top three.
- **Your card:** when the viewer owns a card of this player, its modifiers are highlighted in that list with their value per match. When they don't, the list is shown unhighlighted.
- **One formula:** values come from the server, using the same scoring code as match points. The parts of a match add up to its fantasy points.

### Compared with the League
**User story**
As a fantasy manager, I want to see how a player's averages rank against the league, so that a number like "6.2 assists" means something.

**Acceptance criteria**
- **Percentile strips** for Kills, Deaths, Assists, GPM, Last hits, Wards, Stuns and Teamfight %. Each row shows the label, the player's average, a 0–100 track with the league median tick and the player's dot, and "Top 15 %" or "Bottom 30 %".
- **Deaths** are ranked lower-is-better and say so ("fewer deaths than 80 % of players").
- **Population:** players with at least 3 scored matches this season, with the size shown ("vs 84 players"). Below 3 matches, the section shows "Not enough matches to compare yet".
- **Role:** a Core or Support chip in the header, computed live from this season's averages (same rule as today's `role_tendency`: support when wards ≥ 3 and GPM < 450).

### Heroes Played
**User story**
As a visitor, I want to see which heroes a player has played in the league and how those games went, so that their style and comfort picks are visible.

**Acceptance criteria**
- **This season:** hero icons from the match history, each with games, W–L and average points, sorted by games. The top six show, then "Show all".
- **Career heroes:** when profile facts exist, a smaller list "Career (OpenDota, updated <date>)" with games and win rate. It is hidden when there are no facts.
- **Unknown heroes:** a match without `hero_id` counts in no hero row.

### Match Details on Demand
**User story**
As a fantasy manager, I want the full stats of any match a click away, so that the table stays readable but nothing is hidden.

**Acceptance criteria**
- **New history columns:** Hero (icon) and Result (W or L, as text) after Date. The existing columns stay.
- **Details:** each row has a **Details** toggle (`aria-expanded`) that opens a panel with every stat, including the never-shown ones (last hits, denies, towers, Roshan, teamfight, camps, runes, first blood, stuns, sentry wards, duration). The panel also shows that match's points breakdown by source, with the MVP bonus.
- **Badges stay:** Partial stats and Not scored badges and tooltips are unchanged.
- **Phone width:** the table becomes one stacked row per match (date, opponent, result, hero, points), with the same Details toggle. Nothing scrolls sideways.
