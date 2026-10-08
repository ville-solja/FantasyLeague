# Schedule Tournament Visualization

Admins define the season's tournament stages in the admin portal, and each shown stage becomes a subtab under Schedule. The first build draws a round-robin group stage (standings table or results grid) and a single-elimination bracket. The data model also covers double elimination, GSL groups and Swiss for later phases (issue #94). Plan: `markdown/plans/plan-issue-94-schedule-tournament-visualization.md`. Design canvas: https://claude.ai/artifact/HDsKnJv3MP7H4nrkQUVUGs.

---

## Stages, groups and series *(planned)*

- **Stage** (`tournament_stages`): a subtab with a name, format (`round_robin`, `single_elim`, `double_elim`, `gsl`, `swiss`), date window, Shown flag and settings (best-of, advance count, points, bracket size, third place).
- **Group** (`stage_groups`, `stage_group_teams`): a division or group within a stage and its teams, in the admin's order.
- **Series** (`stage_series`): bracket formats only. Each series has its round, slot, teams or sources (`seed:…`, `winner:…`, `loser:…`), scheduled time and an optional admin-set score. Round-robin pairings are derived from the group's teams.

Results come from ingested matches between the two teams inside the stage window, through `schedule.resolve_series_result`. An admin-set score is used only when no matches are found. Stage views follow the Schedule's Hide results switch and reveals.

## Endpoints

### `GET /schedule/stages` *(planned)*
Public. Shown stages with their computed standings, grid or bracket columns. It shares the Schedule's cache.

### `GET|POST /admin/stages`, `PUT|DELETE /admin/stages/{id}` *(planned)*
Admin only, audited. Stage list and editing.

### `PUT /admin/stages/{id}/groups`, `PUT /admin/stages/{id}/bracket`, `PUT /admin/stages/{id}/series/{series_id}` *(planned)*
Admin only, audited. Groups and teams; bracket size and seeds; a series' time and manual score.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
