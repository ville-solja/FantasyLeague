# Player Popup Visualizations

The player popup turns a player's season into a form chart, a points-by-source breakdown (which also shows which card modifiers pay most), league percentiles, heroes played and expandable match details. Everything is computed live from `player_match_stats`; the admin-run profile facts only add career heroes. Plan: `markdown/plans/plan-issue-208-player-popup-visualizations.md`; mockups on the design canvas https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr.

---

## Layout

Top to bottom:
1. **Header:** avatar, name and team, with #50's accolade pips (`#playerModalPips`) and seasons played, plus a Core or Support chip.
2. **Summary tiles:** Matches (W–L), Avg pts with league rank, Total, Best match, MVPs, and a Rank tile for ranked players (#230; three per row when present, see [Accolades and Rank in the Player Popup](player-popup-accolades-and-rank.md)).
3. **Form chart:** one bar per match by week. MVP stars, W/L squares, ghost bars for excluded matches, hatching for partial stats, and player and league average lines.
4. **Points by source:** a stacked bar and rows per source with the league average, and the top three modifier values (highlighting the viewer's own card).
5. **Compared with the league:** percentile strips for eight stats, against players with 3+ scored matches.
6. **Heroes:** this season's heroes with games, W–L and average points, plus career heroes from profile facts when present.
7. **Accolades** (#50).
8. **Match history:** Hero and Result columns, a Details panel with every stat and the match's points breakdown, and stacked rows at phone width.
9. **Bio:** the existing LLM bio, unchanged.

## Endpoints

### `GET /players/{player_id}`
- **Per match:** adds `hero_id`, `hero_name`, `hero_icon_url`, `won`, `duration`, `week_label`, `sen_placed` and `points_breakdown`.
- **Top level:** adds `summary`, `league_avg_points`, `points_sources`, `modifier_values`, `league_comparison` (null below 3 scored matches) and `heroes`.

The response shape is in `markdown/features/core/players.md`. Public, no viewer data, no new request per section.

### `GET /players/{player_id}/profile`
Unchanged. Its career heroes feed the secondary hero list; its `kanaliiga_seasons` is superseded by #50's `seasons_played`.

## Implementation

### Backend (`backend/player_insights.py`, `backend/routers/players.py`)
- **Sources** (`SOURCE_GROUPS`): Kills, Assists, Farm (last hits, denies), GPM, Vision (observer wards), Objectives (towers, Roshan), Teamfight, Stuns, Jungle and runes (camps, runes), First blood, Survival (the death pool) and MVP bonus. `points_by_source(stats, weights, is_mvp)` splits one match with the scoring code (`weight × value` per stat, `_death_contribution` for deaths, `mvp_bonus_pct` of `fantasy_score` for the MVP), so the parts add up to the match's points. Missing stats count as 0.
- **League** (`league_aggregates(db, weights)`): one query over every scored stat row. It gives the league average points and per-source averages per scored match (all players), and per-player averages for players with at least `MIN_COMPARISON_MATCHES` (3) scored matches, the comparison population. `cached_league_aggregates` keeps the result in process, keyed on the weights fingerprint and a cheap data version (stat row count, ids and sums, recalculated points, MVP flags, excluded matches), and recomputes after 60 s (`LEAGUE_CACHE_TTL`) regardless.
- **Percentiles** (`percentile`): mid-rank (ties count half); `lower_is_better` inverts it for Deaths. `avg_rank` ranks average points in the population.
- **Modifier values** (`modifier_values`): per stat, `modifier_bonus_pct` % of that stat's average points per scored match, highest first, with the stat's average points as `base`.
- **Heroes** (`hero_rows`): games, wins, losses and average points per hero, most played first; excluded matches and matches without a `hero_id` count in no row. Icons and names come from the cached OpenDota hero constants via `schedule.cached_hero_maps()`, which never fetches: the cache is warmed by a startup thread (`schedule.warm_hero_maps`), and a cold cache starts one background warm-up and answers with empty maps, so icons and names are null until it lands. Icon paths are accepted only when they start with a single `/`, so the CDN host can't change.
- **Weeks**: `weeks.scoring_week_for` with the week list loaded once per request, so `week_override_id` wins over the start time.
- Weights come from `card_points._current_weights(db)`. No formula change, no migration, no env var.

### Frontend (`frontend/app-player-popup.js`)
- The popup moved out of `app-players.js`; `openPlayerModal(id)` keeps its name and callers. `renderPlayerPopup(p)` fills every section from one response; the profile fetch then adds career heroes (`renderPlayerCareerHeroes`) and the bio (`renderPlayerProfile`).
- The form chart is HTML and CSS: bars are `<button>`s with a `data-tip` tooltip and `activatePlayerFormBar(id)`, which highlights (`.is-highlighted`) and scrolls to `#playerMatchRow-<id>`. Reference lines are positioned from the same scale as the bars.
- The tooltip is #50's shared one in `app-globals.js` (`_accoladeTipTarget`, `showAccoladeTip`), generalised from `data-accolade-tip` to `data-tip`; accolade pips use it too.
- "Your card": `_popupOwnCardModifiers(playerId)` reads the loaded My Team cards (`_rosterCards`) when signed in. No request.
- Stacked-bar colours are the `--series-1` … `--series-5` and `--series-other` tokens in `colors_and_type.css`; single-series bars and strips use neutral and accent tokens, and text never takes a series colour.
- CSS: the "PLAYER POPUP VISUALIZATIONS (issue 208)" block in `style.css`, before GUIDED TOUR; the phone layout is under `@media (max-width: 640px)`.

Tests: `backend/tests/test_issue_208_player_popup_visualizations.py` (backend and Node harness).
