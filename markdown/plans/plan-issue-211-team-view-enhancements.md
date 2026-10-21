# Plan: Team View Enhancements

## Context
The player popup now tells a season's story (#208). The team popup still shows only a name, a match count and a four-column roster (`openTeamModal` in `frontend/app-players.js`, `GET /teams/{id}` in `backend/routers/players.py`). The Teams tab lists name, matches and players (`GET /teams`). This plan brings the team view up to the player popup's level with data the app already has.

**What exists to work with:**
- **Teams:** `teams.id` (OpenDota team id), `name`, `logo_url`.
- **Matches:** radiant and dire team ids, `radiant_win`, `start_time`, `duration`, `league_id`, `excluded_from_scoring`. The division comes from the league name (`accolades.league_division`, #50).
- **Per-player stats:** every stat with `team_id`, `hero_id`, `fantasy_points` and `is_mvp` (`player_match_stats`).
- **Schedule feed:** each series' teams, division, week, `series_result` (wins and `match_ids`), `stream_url`, and upcoming fixtures (`schedule.get_schedule`).
- **Reusable code:**
  - #208's `player_insights`: points by source, the cached league aggregates, hero rows, `won`, week labels;
  - its form chart and tooltip patterns;
  - #50's accolades: champion rows carry `team_name`, so a team's titles are found by name.
- **Not available:** hero bans are stored per match without the banning team, so per-team bans can't be shown.

**Decisions** (change them in review if needed):
- **Team popup layout,** top to bottom, mirroring #208:
  1. **Header:** logo, name, "Div 1 · Season 17", and champion title chips ("S16 Div 1 Champion").
  2. **Summary tiles:** Series W–L, Games W–L, Fantasy pts per game (the team's five players combined), average game length, MVPs.
  3. **Season results:** one row per series, week by week: opponent (logo, link), score ("2–1"), and a W or L shown in text and shape, never colour alone.
     - Upcoming series show the date and the stream link.
     - A small strip of result chips heads the list as the team's form.
  4. **Roster:** each player shows the accolade pips (#50) and the tag pips (#217), role chip, games played of the team's games, average points, total points, a bar for their share of the team's points, and "Owned by N %".
     - Players who played under 30 % of the team's games are listed under **Also played**.
  5. **Where the team's points come from:** a stacked bar by source for the team, against the average team, using `player_insights` sources summed over the roster.
  6. **Heroes:** the team's most picked heroes, with games and W–L.
- **Ownership is aggregate only:** "Owned by N %" is the share of managers (full, non-tester accounts with at least one active card) who hold an active card of the player. It shows a percentage only, never who, and only once at least 10 managers have cards (`OWNERSHIP_MIN_MANAGERS`); below that `owned_pct` is null and the popup shows "—", so a percentage can't reveal one manager's roster.
- **Teams tab:**
  - **Columns:** Team (logo, name), Division, Series W–L, Games W–L, Fantasy pts per game, Players, Titles (chips).
  - **Filters:** All, Div 1, Div 2. Sortable columns, using the existing sortable-table pattern.
- **Season scope:** this season's data. Titles come from all seasons' accolades.
- **Performance:** league-wide numbers (the average team's sources, ownership denominators) are cached with the same versioned in-process cache as #208. The schedule feed is already cached.
- **Mockups:** design canvas https://claude.ai/artifact/4H1nAuQQPxoSMMpMT441KN.

Resolves GitHub issue #211.

## User Stories

### A Team's Season at a Glance
**User story**
As a fantasy manager, I want a team's record, results and upcoming games in its popup, so that I can judge how strong a team is and when its players play next.

**Acceptance criteria**
- **Header:** logo, name, division and season ("Div 1 · Season 17"), and the champion title chips from all seasons' accolades, matched by team name.
- **Summary tiles:**
  - Series W–L;
  - Games W–L;
  - Fantasy pts per game: the team's players' combined scored points per game;
  - average game length (mm:ss);
  - MVPs earned by the team's players.
- **Season results:**
  - one row per series from the schedule feed, newest last: week, opponent (logo, link to its popup), score, and W or L as text;
  - a form strip of result chips above the list, with shape and text so it isn't colour alone;
  - upcoming series show the date and time, and a stream link when the feed has one.
- **Exclusions:** excluded matches count in no figure. Partial-stat matches count.
- **Empty state:** "No matches yet this season." The header and titles still show.

### The Roster Explained
**User story**
As a fantasy manager, I want to see who carries a team and how popular its players are, so that I can pick the right players from it.

**Acceptance criteria**
- **Rows:** one row per player who played for the team this season, with:
  - avatar, name (link to the player popup), role chip (Core or Support, same rule as #208);
  - accolade pips and tag pips;
  - games played as "12 / 13";
  - average and total points;
  - a share-of-team-points bar with the percentage;
  - "Owned by N %".
- **Order:** by total points by default; every column sorts.
- **Also played:** players with under 30 % of the team's games are listed under this heading.
- **Ownership:** N is the percentage of managers (full, non-tester accounts with at least one active card) holding an active card of the player. No user identities in the response.

### Where the Team's Points Come From
**User story**
As a fantasy manager, I want to see what kind of fantasy points a team produces, so that I know which card modifiers suit its players.

**Acceptance criteria**
- **Stacked bar:** sources (the same groups as #208) summed over the team's players per game, with a tick for the average team per source.
- **Modifier value:** "A +10 % modifier pays most on this team's players: Kills, GPM, Assists", from the team totals.
- **Heroes:** the top six heroes by games, with W–L and the players who played them.
- **One formula:** values come from the server, using `player_insights`. No scoring maths in the browser.

### Teams Tab Ranks Teams
**User story**
As a visitor, I want the Teams list to show divisions, records and titles, so that I can compare teams without opening each one.

**Acceptance criteria**
- **Columns:** Team (logo, name), Division, Series W–L, Games W–L, Fantasy pts per game, Players, Titles (chips; pips at phone width).
- **Filters and sorting:** filter chips All, Div 1 and Div 2, and every column sorts. The default sort is by division, then series wins.
- **Phone width:** the table becomes stacked rows with no sideways scroll.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/team_insights.py` (new) | Team record from matches; series list from `schedule.get_schedule`; team sources from `player_insights`; heroes; ownership percentages; titles from accolades by team name; cached league numbers |
| `backend/routers/players.py` | `GET /teams` adds `logo_url`, `division`, records, `points_per_game`, `titles`. `GET /teams/{id}` adds `logo_url`, `division`, `season`, `summary`, `series`, `players` (role, `games`, `team_games`, `share`, `owned_pct`, `also_played`), `points_sources`, `modifier_values`, `heroes`, `titles` |
| `frontend/app-team-popup.js` (new) | The team popup, moved out of `app-players.js` and redesigned |
| `frontend/app-players.js` | Teams tab columns, filters and sorting (`loadTeams`) |
| `frontend/index.html`, `frontend/style.css` | Team popup sections, Teams tab table; tokens only, CSS before GUIDED TOUR |
| `markdown/ui_description/teams.md`, `markdown/features/core/players.md`, `markdown/features/reference/team-view-enhancements.md` | Docs |
| `backend/tests/test_issue_211_team_view_enhancements.py` | Tests |

No migration, no new env var.

### Step 1 — Data
`team_insights.py`:
- the record (series wins from the feed, games from matches);
- the series list with upcoming fixtures;
- roster aggregates with games, share and also-played;
- team sources against the average team, through the #208 cache pattern;
- heroes;
- ownership counts (one grouped query over active cards, joined to full non-tester users);
- titles by team name, matched case- and whitespace-insensitively.

### Step 2 — Endpoints
Extend `GET /teams` and `GET /teams/{id}`. The schedule fetch must be failure-safe: with the feed down, the series and upcoming lists are empty, games still come from matches, and the endpoint answers 200.

### Step 3 — Team popup
Move the popup to `app-team-popup.js` and build the sections. Reuse the shared tooltip, pips and #208 chart styles. Phone layout stacks.

### Step 4 — Teams tab
Add the columns, filters, sorting and the phone layout.

### Step 5 — Docs and tests
**Tests:**
- record and series from a mocked feed;
- excluded matches left out;
- share sums to 100 %;
- the also-played threshold;
- ownership as a percentage with testers and soft accounts excluded, and no user ids;
- titles matched by name;
- feed-down safety;
- the cache reused across requests;
- frontend harness: sections, form chips not colour alone, sorting, filters, empty state.

## Verification
- **Div 1 team, test copy:** the record matches the Schedule tab, the results list matches the feed, upcoming games show their stream link, and the roster shares add to 100 %.
- **Last season's champions:** the "S16 Div 1 Champion" chip shows on that team.
- **Teams tab:** filtering Div 2 and sorting by series wins orders teams as in the standings.
- **Feed down:** the popup still shows the roster, sources and heroes.
