# Plan: Player Popup Visualizations

## Context
The player popup opens from every player name and card. Mockups: the "Player popup visualizations (planned)" boards on the design canvas https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr. It already carries a full season of per-match data, but shows it as four number tiles and a nine-column table. This plan turns that data into views a fantasy manager can read at a glance: how the player's form has gone, where their points come from (and so which card modifiers pay), how they compare with the league, and which heroes they play.

**What the popup has today:**

| Source | Data | Shown today |
|---|---|---|
| `GET /players/{id}` (live, every open) | name, avatar, team (from the latest match); matches, avg, total and best match | Tiles: Matches, Avg pts, Total pts, Best match |
| `GET /players/{id}` › `match_history[]` | match id, start time, fantasy points, `is_mvp`, `parse_status`, `excluded_from_scoring`, kills, assists, deaths, GPM, observer wards, tower damage, opponent | Table: MVP, Date, Fantasy pts, K/A/D, GPM, Wards, Tower dmg, Opponent, OpenDota link |
| same, returned but **never shown** | last hits, denies, towers killed, Roshan kills, teamfight participation, camps stacked, rune pickups, first blood, stuns | none |
| `player_match_stats` and `matches`, **not returned** | `hero_id`, `sen_placed`, result (`radiant_win` with the player's side), `duration`, scoring week (`weeks.scoring_week_for`) | none |
| `GET /players/{id}/profile` (`player_profiles.facts_json`, filled only when an admin runs `POST /admin/enrich-profiles`; calls OpenDota) | `kanaliiga_seasons`, average K/D/A, GPM and wards, `role_tendency`, career heroes with win rate, tournament heroes, recent pub heroes, `ban_correlations` (never shown) | A second row of tiles and three hero text lines |

**Findings that shape the plan:**
- **Most of the value is already in the main endpoint.** Everything except career and pub heroes can be computed live from `player_match_stats`, so the new views don't depend on the admin-run crawl.
- **Profile facts are stale and partly wrong.** They exist only after a manual crawl. `kanaliiga_seasons` counts distinct leagues in the current database, which a Season Reset empties, so it is close to meaningless. #50 replaces it with `seasons_played`.
- **The scoring formula can explain every point.** `fantasy_score` is a weighted sum over `SCORING_STATS` plus the death pool, and `card_utils.card_points_breakdown` already splits a match into parts for the Weekly Report (#152). The same split gives "where the points come from".
- **Card modifiers are per stat**, at `modifier_bonus_pct` (10 %) of that stat's points. So a points-by-stat view also tells a manager which modifiers on this player's card are worth the most.
- **The LLM bio** (`bio_text`) is out of scope: it isn't in active use, and this plan leaves it as it is, below everything else.

**Decisions** (change them in review if needed):
- **Live data first:** the new views use only `GET /players/{id}`, extended. Career heroes from the profile facts show as a secondary list only when present, with their update date.
- **No chart library:** inline SVG and CSS on design tokens, like the rest of the site.
- **League comparison population:** players with at least 3 scored matches this season. A player below that gets "Not enough matches to compare yet".
- **Excluded matches** (`excluded_from_scoring`) stay in the history and the form chart as ghost bars, but count in no average, breakdown, comparison or hero figure. Partial-stat matches count, and are marked.
- **Season scope:** everything is this season (Season Reset clears earlier stats). Multi-season history comes from #50's accolades.
- **The #50 parts are built** (added in review, after #50 was implemented): the popup header has `#playerModalPips`, the `#playerModalAccolades` section is rendered by `renderPlayerAccolades(p)` in `frontend/app-players.js`, and `GET /players/{id}` returns `seasons_played`, `seasons`, `titles`, `accolades`, `current_season`, `current_season_matches` and `holo_unlocked`. This plan moves those into the new layout unchanged (header and section 7) rather than rebuilding them.
- **One tooltip:** #50's tooltip in `frontend/app-globals.js` (`_accoladeTipTarget`, shown on hover, focus and tap for any `[data-accolade-tip]`) is generalised to a neutral `data-tip` attribute that pips and chart bars both use; existing pips keep working.
- **Season name:** chart and section headings use `current_season` from the response ("Season 16"), which #50 reads from the monitored leagues' OpenDota names.

Resolves GitHub issue #208.

## User Stories

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

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/players.py` | `GET /players/{id}`: per-match `hero_id`, `hero_icon_url`, `won`, `duration`, `week_label`, `sen_placed`, `points_breakdown`; top-level `summary`, `points_sources`, `modifier_values`, `league_comparison`, `heroes` |
| `backend/player_insights.py` (new) | `points_by_source(stats, weights)`, `league_aggregates(db)`, `percentile(...)`, `hero_rows(history, icons)`, source groups and labels |
| `backend/scoring.py` | Reuse `fantasy_score`, `_death_contribution` and `STAT_LABELS`; no formula change |
| `backend/schedule.py` | Reuse `_fetch_hero_icon_map()` (maybe moved to a shared helper) |
| `backend/weeks.py` | Reuse `scoring_week_for(db, match, weeks)` with the week list loaded once |
| `frontend/app-player-popup.js` (new) | The popup, moved out of `app-players.js` (`openPlayerModal`, `renderPlayerProfile`, `renderPlayerAccolades`, `_matchPointsCellHtml`): tiles, form chart, points by source, comparison strips, heroes, history with details |
| `frontend/index.html` | Popup markup sections; script tag |
| `frontend/style.css` | Chart, strip and history styles in the design system (tokens, tabular numbers, before GUIDED TOUR) |
| `frontend/app-globals.js` | #50's pip tooltip generalised to `data-tip` (pips keep working) |
| `markdown/ui_description/players.md`, `markdown/features/core/players.md` | Docs |
| `backend/tests/test_player_popup_visualizations.py` | Tests |
| Node harness test for `app-player-popup.js` | Frontend tests |

No migration, no new env var.

### Step 1 — Data
Extend `GET /players/{id}` with:
- **Per match:**
  - `hero_id` and `hero_icon_url`;
  - `won`: `radiant_win` compared with whether `team_id == radiant_team_id`, null when unknown;
  - `duration`, `sen_placed`;
  - `week_label`: the scoring week, honouring `week_override_id`;
  - `points_breakdown`: by source, with `mvp_bonus`; it sums to `fantasy_points`.
- **`summary`:** wins, losses, MVPs, and `avg_rank` as `{rank, of}` among the comparison population.
- **`points_sources` and `modifier_values`:** averages over scored matches, plus the league average per source.
- **`league_comparison`:** per stat `{value, percentile, median, lower_is_better}` and `population`; null below 3 scored matches.
- **`heroes`:** this season's heroes from the history.

League aggregates come from one `GROUP BY player_id` over scored stats, computed per request (the data is about 100 players), with a short in-process cache if profiling asks for it. Weights come from `card_points._current_weights(db)`.

### Step 2 — Popup layout
Move the popup to `app-player-popup.js`. Sections, top to bottom:
1. header (the existing `#playerModalPips`, seasons played from `seasons_played`, and the role chip);
2. summary tiles;
3. form chart;
4. points by source;
5. league comparison;
6. heroes;
7. Accolades (the existing `renderPlayerAccolades` section, unchanged);
8. match history;
9. the existing bio, unchanged.

The modal stays `modal-wide`. Below 640 px the sections stack and the history uses stacked rows.

### Step 3 — Charts
- **Form chart:** inline SVG, bars as `<button>` overlays for focus and tap.
- **Strips and stacked bar:** HTML and CSS.
- **Tooltip:** shared with #50.
- **Reduced motion:** honoured.

### Step 4 — Your card
Read the viewer's cards from the already-loaded My Team data, when logged in, and highlight matching modifiers. There is no new endpoint.

### Step 5 — Docs and tests
**Docs:** the UI description and core players doc.

**Tests:**
- **Backend:**
  - `won` from side and `radiant_win`, including null;
  - breakdown parts sum to fantasy points, with and without MVP;
  - excluded matches are left out of every aggregate but stay in the history;
  - partial-stat matches count;
  - percentiles: Deaths inverted, the population threshold, null below 3;
  - hero rows, with no `hero_id` skipped;
  - week labels honour overrides;
  - no user data in the response.
- **Frontend harness:**
  - bar count and ghost bars;
  - tooltip text;
  - bar activation highlights the row;
  - Details toggle and `aria-expanded`;
  - empty state;
  - career heroes hidden without facts.

## Verification
- **A regular player:** on a test copy, open their popup. The bars match the history, the MVP stars and W/L squares are right, and the breakdown of one match adds up to its points.
- **A support player:** shows the Support chip and Vision high in points by source. "A +10 % modifier is worth most on" names plausible stats.
- **A player with 1–2 matches:** shows "Not enough matches to compare yet".
- **An excluded match:** shows as a ghost bar and changes no average.
- **Phone width:** the history is stacked rows with Details; nothing scrolls sideways.
- **No profile facts:** the career heroes list is absent and nothing else changes.
