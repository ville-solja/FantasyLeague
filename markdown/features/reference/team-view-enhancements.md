# Team View Enhancements

The team popup and the Teams tab show a team's season: its record, its results and upcoming games, how its roster scores and how often managers own each player, what kind of fantasy points the team produces, its heroes, and its championship titles. Plan: `markdown/plans/plan-issue-211-team-view-enhancements.md`. Mockups: https://claude.ai/artifact/4H1nAuQQPxoSMMpMT441KN. UI spec: `markdown/ui_description/teams.md`.

---

## Where the code lives

| Part | File |
|---|---|
| Data: records, series, roster, ownership, sources, heroes, titles, cache | `backend/team_insights.py` |
| Endpoints `GET /teams`, `GET /teams/{team_id}` | `backend/routers/players.py` |
| Shared helpers reused from the player popup (#208) | `backend/player_insights.py`: `points_by_source`, `points_sources(..., per=)`, `modifier_values(..., per=)`, `hero_rows`, `won`, `week_short`, `role` |
| Team popup | `frontend/app-team-popup.js` (moved out of `app-players.js`; `openTeamModal` / `closeTeamModal` stay global, so `teamLink` keeps working) |
| Teams tab | `frontend/app-players.js`: `loadTeams`, `renderTeams`, `setTeamsFilter`, `_sortTeams` |
| Markup and styles | `frontend/index.html` (`#teamModal`, `#tab-teams`), `frontend/style.css` ("TEAM POPUP AND TEAMS TAB (issue 211)") |

## Team popup

1. **Header:** logo (or monogram), name, "Div 1 · Season 17", and champion title chips (`accoladeChipsHtml`) from all seasons' accolades, matched by team name ignoring case and extra whitespace.
2. **Summary tiles:** Series W–L (from the feed), Games W–L (from matches), pts per game (the team's players combined), average game length (mm:ss), MVPs.
3. **Season results:** a form strip and one row per played series, oldest first, with opponent link, score and a result chip; upcoming series with date, time and stream link (`_safeUrl`). Result chips show the letter and a shape (filled W, hollow L, dashed D) and carry the result as `aria-label`, so colour is never the only signal.
4. **Roster:** tag and accolade pips, role chip, games ("12 / 13"), average, total, share bar, "Owned by N %". Every column sorts (`sortTeamRoster`); players under 30 % of the team's games are grouped under **Also played**.
5. **Where the points come from:** the #208 stacked bar and source rows per team game, with an average-team tick, and the top three modifier stats.
6. **Heroes:** the top six by games, with W–L and the players who played them. Bans aren't stored per team, so they aren't shown.

All values come from the server; the popup does no scoring maths.

## Teams tab

- **Columns:** Team (logo, name), Division, Series W–L, Games W–L, Fantasy pts per game, Players, Titles (chips; pips at phone width through `.accolade-swap`).
- **Filters:** All, Div 1, Div 2 (`.players-filter-chip[data-teams-filter]`, the shared selected state).
- **Sorting:** every header sorts (click again to flip). Default: Div 1, Div 2, unknown; then series wins, game wins and name. Filter and sort persist across data refreshes (not a page reload); the table renders through `renderIfChanged`.
- **Phone width:** stacked blocks with labels (`data-label`), no sideways scroll.

## Rules

- **Exclusions:** matches with `excluded_from_scoring` count in no figure (games, points, game length, MVPs, roster, sources, heroes, league numbers). Partial-stat matches count. Series scores are the feed's own (`schedule.resolve_series_result`), so they match the Schedule tab.
- **Series:** a feed series involves the team through `team1_id` / `team2_id`, or `schedule.find_team_id` on the names. A series with a result is played; one without is upcoming unless its `match_status` is `past`.
- **Division:** the league of most of the team's matches (`accolades.league_division`).
- **Ownership:** managers are full, non-tester, non-demo accounts with at least one active card; `owned_pct` is the whole percentage of them holding an active card of the player. Only the percentage is returned, and only once at least `OWNERSHIP_MIN_MANAGERS` (10) managers have cards: below that every `owned_pct` is `null`, the response carries `ownership_hidden: true`, and the popup shows "—" (sorted last), so a percentage can't reveal a specific manager's active roster.
- **Logos:** every `logo_url` (team and opponents) passes through `logo_hosts.safe_logo_url`. Issue #171 had kept logos out of these endpoints; issue #211 adds them sanitised.
- **Feed down:** `team_insights.feed_weeks` catches any error from `schedule.get_schedule`; series and upcoming are empty, series records zero, everything else intact, status 200.

## Caching

`team_insights.cached_league_numbers(db, weights)` caches the average team's sources per team game and the ownership counts in-process, keyed on the weights fingerprint, `player_insights._data_version` (stats, MVP flags, exclusions) and an active-card fingerprint, for at most `LEAGUE_CACHE_TTL` (60 s). `team_insights.cached_team_list(db, weights)` caches the whole `GET /teams` list the same way, keyed on the weights fingerprint, `player_insights._data_version`, a match/team/league/champion fingerprint and the schedule feed's `cached_at`; games records come from one pass over the matches (`games_records`). `team_insights.clear_league_cache()` empties both. The schedule feed has its own cache (`schedule.get_schedule`).

## Endpoints

### `GET /teams`
Each row: `id`, `name`, `logo_url`, `division`, `series_wins`, `series_losses`, `series_draws`, `wins`, `losses`, `matches`, `points_per_game`, `player_count`, `titles`. Public.

### `GET /teams/{team_id}`
`id`, `name`, `logo_url`, `division`, `season`, `titles`, `matches`, `summary`, `series`, `upcoming`, `players` (with `role`, `games`, `team_games`, `avg_points`, `total_points`, `share`, `owned_pct`, `also_played`, `accolades`, `tags`), `points_sources`, `modifier_values`, `heroes`. 404 `"Team not found"` for an unknown team. Public.

Full field reference: `markdown/features/core/players.md`.

## Tests

`backend/tests/test_issue_211_team_view_enhancements.py`: backend figures against a mocked feed, exclusions, shares, the also-played threshold, ownership, titles, feed-down safety, the cache, logo allowlist, and Node harnesses for the popup sections, form chips, roster sorting, the Teams tab filters, sorting and phone layout.
