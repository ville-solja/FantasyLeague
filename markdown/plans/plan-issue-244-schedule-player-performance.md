# Plan: Schedule Player Performance

## Context
Issue #244: "Schedule to contain extended results with player 'raw' performance as metric." The issue has no body, so this plan reads it as follows.

Today an unfolded series in the Schedule tab lists its games with the heroes, team kills, MVP, duration and an OpenDota link (`schedule._build_games`, rendered in `frontend/app-players.js`). Nothing shows how each player performed. This plan adds a per-game player table whose metric is the player's **raw points**: the game's fantasy score from the player's own stats before card rarity, card modifiers and the MVP bonus. That is the number the Weekly Report shows on its RAW chip (`card_utils.card_points_breakdown`), computed by `scoring.fantasy_score(stat_dict_from_row(row), weights)`. It is not `player_match_stats.fantasy_points`, which already includes the MVP bonus.

**Decisions** (change them in review if needed):
- **Where:** each game row in an unfolded series gets a **Players** toggle that opens that game's table. The table is not shown for every game at once, because ten rows a game would make a best-of-three series thirty rows long.
- **Loaded on demand:** a new public endpoint returns one game's players when the table is opened. The schedule payload stays the size it is, and a hidden result never loads player data, so hide mode keeps its rule that a hidden row outputs nothing.
- **Columns:** player (opens the player popup), hero, kills / deaths / assists, raw points. Grouped by team, each team sorted by raw points. The game's highest raw score is marked, and the MVP keeps its star.
- **Weights:** the current scoring weights, as everywhere else that shows points.
- **Not scored and partial games:** a game excluded from scoring still shows its players and raw points, with the existing "Not scored" badge; it is a performance figure, not points that count. A game whose replay was not parsed shows the existing "Partial stats" badge, because wards, stuns, teamfight, runes and camps count as 0.
- **No series or season totals** in this issue. A "top raw performer of the series" line can follow if wanted.

Resolves GitHub issue #244.

## User Stories

### See How Each Player Performed in a Game
**User story**
As a fantasy player, I want to see every player's raw points in a game on the Schedule, so that I can judge who performed well regardless of whose cards I hold.

**Acceptance criteria**
- **Toggle:** each game row of an unfolded series has a **Players** button (`aria-expanded`). Pressing it opens that game's player table below the row; pressing it again closes it.
- **Table:** one row per player of the game, grouped under the two team names, each team sorted by raw points (highest first). Columns: player name, hero icon, kills / deaths / assists, raw points to one decimal (`display_points`).
- **Raw points:** `fantasy_score` of the player's stats in that game with the current weights: no rarity, no card modifiers, no MVP bonus. A short note under the table says so: "Raw points: from the player's own stats, before card rarity, modifiers and the MVP bonus."
- **Emphasis:** the player with the game's highest raw score is marked as the top performer (ties all marked). The MVP keeps the star.
- **Links:** a player's name opens the player popup.
- **Phone:** the table fits the screen width without sideways scrolling; the hero column may be dropped on narrow screens.

### Player Tables Keep Results Hidden
**User story**
As a player who hasn't watched the games yet, I want the player tables to stay out of hidden results, so that turning on hide mode still keeps me spoiler-free.

**Acceptance criteria**
- A hidden series row (hide mode on, not revealed) has no Players button and loads no player data; the page source of a hidden row holds no player names, stats or points.
- Revealing a series makes its games' Players buttons available; **Hide week again** closes any open player tables in that week.
- The Latest result card is unchanged: its **Games** button opens the week, where the tables work as above.

### Partial and Unscored Games Are Labelled
**User story**
As a fantasy player, I want to know when a game's figures are incomplete or don't count, so that I don't misread a low or ignored score.

**Acceptance criteria**
- A game whose replay is unparsed or unparseable shows the existing "Partial stats" badge on its player table, with the existing tooltip.
- A game excluded from scoring shows its players and raw points, and the table repeats the existing "Not scored" badge.
- A game with no stored player stats yet (a series still resolving) shows "No player stats for this game yet." instead of a table.

### Public Endpoint for One Game's Players
**User story**
As the frontend, I want one game's player lines from the API, so that the Schedule loads them only when asked.

**Acceptance criteria**
- `GET /matches/{match_id}/players` is public (no login), like `GET /schedule`, and returns `match_id`, `parse_status`, `excluded_from_scoring` and `teams`: two entries with `team_id`, `team_name` and `players`, each player with `player_id`, `player_name`, `hero_id`, `hero_icon`, `kills`, `deaths`, `assists`, `raw_points`, `is_mvp` and `top`.
- An unknown match answers 404; a match id outside the database id range answers 422.
- It returns no user, card or ownership data, only league data already public in the player popup.
- Responses are cached in memory per match and cleared with the schedule cache (`schedule.bust_cache`), so a new MVP or a re-ingested match shows at once.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/schedule.py` | `game_players(db, match_id)`: player lines with raw points; a per-match cache cleared by `bust_cache` |
| `backend/routers/players.py` | `GET /matches/{match_id}/players` (public, bounded id) |
| `frontend/app-players.js` | Players toggle on each game row, the table, and closing tables on Hide week again |
| `frontend/style.css` | Table styles inside `.series-games`, phone layout |
| `backend/tests/test_issue_244_schedule_player_performance.py` | Tests |
| `markdown/ui_description/schedule.md`, `markdown/features/reference/schedule-player-performance.md` | Docs |

No migration and no new setting.

### Step 1 — Player lines with raw points
In `schedule.py`, add `game_players(db, match_id)`. Read the match (`matches.parse_status`, `excluded_from_scoring`, radiant and dire team ids) and its `player_match_stats` rows joined to `players` and `teams`. For each row compute `raw = fantasy_score(stat_dict_from_row(row), weights)` with the weights loaded once (`{w.key: w.value for w in db.query(Weight)}`), and return `display_points(raw)`. Mark `top` on the highest raw score (all ties). Hero icons come from `cached_hero_maps()` so the request never waits on OpenDota. Group by `team_id` in radiant, dire order; sort each team by raw points descending.

Check first how `fantasy_score` treats the stats an unparsed replay lacks (they are stored as 0) so the Partial stats badge matches what the player popup says.

### Step 2 — Endpoint and cache
In `routers/players.py`, add `GET /matches/{match_id}/players` with `match_id: int = Path(ge=1, le=2**63 - 1)`, calling `game_players`; 404 when the match does not exist. Keep a small per-match dict cache in `schedule.py` next to `_cache`, cleared in `bust_cache()`, which ingest and the MVP routes already call. Grep `backend/tests` for `bust_cache` and for `/matches/` route lookups before adding the route.

### Step 3 — Frontend
In `gameRowsHtml` (`frontend/app-players.js`), add a **Players** button to each game row's meta cell with `aria-expanded` and `aria-controls`. On press, fetch `GET /matches/{id}/players` once per match (keep the response in a module map), render the table into a container after the row with `_escHtml` on every name, and toggle it. `hiddenRow` stays unchanged, so hidden rows get no button. In the Hide week again handler, close and empty the open tables of that week. Grep `backend/tests` for harnesses that load `app-players.js` (`gameRowsHtml`, `game-row`) and extend their stubs.

### Step 4 — Styles
A compact table inside `.series-games`: team name as a small heading, tabular numbers right-aligned, the top performer in the data-emphasis style from the design system's "States and emphasis" rules (`.claude/skills/README.md`). Put the CSS before the `GUIDED TOUR (issue #144)` block. Below 480 px hide the hero column.

### Step 5 — Tests
- `game_players`: raw points equal `fantasy_score` of the row's stats and leave out the MVP bonus (an MVP row's `fantasy_points` is higher than its raw points); teams grouped and sorted; ties both `top`; current weights used after a weight change.
- Endpoint: public 200; unknown match 404; oversized id 422; the response holds no user or card fields; the cache clears on `bust_cache`.
- Partial and excluded games carry `parse_status` and `excluded_from_scoring`; a match with no stats still returns its two teams (radiant, then dire), each with an empty `players` list, and the frontend shows "No player stats for this game yet."
- Frontend (source and Node harness as existing schedule tests do): the button is in shown game rows only, the hidden row has none, names are escaped, Hide week again closes tables.

## Verification
- Unfold a played series, open Players for each game: ten players, raw points to one decimal, the MVP starred and the top performer marked. Compare one player's raw points with the RAW chip in the Weekly Report for a card of that player in that game.
- Hide mode: a hidden series has no Players button and the network tab shows no `/matches/…/players` call; after Reveal, the button works; Hide week again closes open tables.
- An excluded game and an unparsed game show their badges.
- Phone width: no sideways scroll.
