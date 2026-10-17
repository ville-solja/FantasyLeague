# Player Popup Visualizations

The player popup turns a player's season into a form chart, a points-by-source breakdown (which also shows which card modifiers pay most), league percentiles, heroes played and expandable match details. Everything is computed live from `player_match_stats`; the admin-run profile facts only add career heroes. Plan: `markdown/plans/plan-issue-208-player-popup-visualizations.md`; mockups on the design canvas https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr.

---

## Layout *(planned)*

Top to bottom:
1. **Header:** avatar, name and team, with #50's accolade pips (`#playerModalPips`) and seasons played, plus a Core or Support chip.
2. **Summary tiles:** Matches (W–L), Avg pts with league rank, Total, Best match, MVPs.
3. **Form chart:** one bar per match by week. MVP stars, W/L squares, ghost bars for excluded matches, hatching for partial stats, and player and league average lines.
4. **Points by source:** a stacked bar and rows per source with the league average, and the top three modifier values (highlighting the viewer's own card).
5. **Compared with the league:** percentile strips for eight stats, against players with 3+ scored matches.
6. **Heroes:** this season's heroes with games, W–L and average points, plus career heroes from profile facts when present.
7. **Accolades** (#50).
8. **Match history:** Hero and Result columns, a Details panel with every stat and the match's points breakdown, and stacked rows at phone width.
9. **Bio:** the existing LLM bio, unchanged.

## Endpoints

### `GET /players/{player_id}` *(planned extension)*
- **Per match:** adds `hero_id`, `hero_icon_url`, `won`, `duration`, `week_label`, `sen_placed` and `points_breakdown`.
- **Top level:** adds `summary`, `points_sources`, `modifier_values`, `league_comparison` (null below 3 scored matches) and `heroes`.

### `GET /players/{player_id}/profile`
Unchanged. Its career heroes feed the secondary hero list; its `kanaliiga_seasons` is superseded by #50's `seasons_played`.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
