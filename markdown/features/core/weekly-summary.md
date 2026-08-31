# Weekly Summary Report

A post-week recap popup, similar in spirit to the Battle Report popup in the Dota 2 client:
once a week's scoring window closes, users can open a "Weekly report" button to see that
week's matches, then choose to reveal the full player-level breakdown (MVPs, points earned)
at their own pace.

*(see `markdown/plans/plan-issue-51-weekly-summary.md`, resolves GitHub issue #51)*

---

## Availability, Not Generation

There is no scheduled-content generation step and no calendar cadence (the originating issue
proposed "every Monday at 06:00"; that was overridden — see the plan's Context section).
Instead, a week simply becomes **available** in the report once its own `end_time` has passed
— the same boundary `auto_lock_weeks()` already uses, including its post-midnight grace period
(see `reference/admin-week-management.md`). This is checked from the existing background
week-maintenance loop, so irregular weeks (e.g. a compressed finals week) are handled the same
way as regular ones, with no separate schedule to keep in sync.

Report content itself (matches, teams, players, points, MVP) is computed live from `Match`,
`PlayerMatchStats`, and `Team` at request time — the same way the weekly leaderboard and card
scoring already work — rather than being pre-generated and stored as a snapshot.

## Two-Stage Visibility

Each week's tab in the popup has two states, gated per user:

1. **Before reveal** — matches for the week, grouped by series (same two teams clustered
   together), team names and logos (winner highlighted), and a VOD link where one has been
   set. No player names, points, or MVP information.
2. **After reveal** — clicking "Reveal results" permanently unlocks, for that user and that
   week only: every player per match grouped under their team, the match's MVP player with a
   highlighted portrait, and a points-earned number per player (neutral color if the player
   wasn't on the viewing user's roster that week, accent color if they were).

Reveal state does not affect other users or other weeks.

## Report Highlight

The "Weekly report" button carries a highlight/badge whenever a newer week's summary has
become available than the last one the current user opened the popup for. Opening the popup
(not revealing any particular week) clears it.

## Series Grouping

Matches within a week are clustered into series with the same pair/gap rule
`backend/schedule.py` uses for the season-wide schedule view (`_group_into_series()` in
`backend/routers/weekly_summary.py`): consecutive matches between the same unordered team pair
belong to the same series as long as the gap to the previous match in that pair is ≤ 6 hours.

## Endpoints

### `GET /weekly-summary`
Auth required (`Depends(get_current_user)`). Lists weeks with a generated `WeeklySummary` row,
ordered most-recent-first:
```json
{
  "weeks": [{"week_id": 3, "label": "Week 3", "revealed": false}],
  "has_unseen": true
}
```
`has_unseen` compares the latest available week against the caller's `WeeklySummarySeen.last_seen_week_id`.

### `GET /weekly-summary/{week_id}`
Auth required. 404 if no `WeeklySummary` row exists for the week yet. Returns matches (grouped
into `series`) with team names/logos/winner/VOD link always included; each match additionally
carries a `players` list (`player_id`, `name`, `avatar_url`, `team_id`, `points`, `is_mvp`,
`on_roster`) only if the caller has revealed that week.

### `POST /weekly-summary/{week_id}/reveal`
Auth required. Idempotently inserts a `WeeklySummaryReveal` row for `(week_id, current user)`,
then returns the same content `GET /weekly-summary/{week_id}` would return afterward.

### `POST /weekly-summary/seen`
Auth required. Upserts `WeeklySummarySeen.last_seen_week_id` to the current latest available
week, clearing the highlight badge on the caller's next `GET /weekly-summary`.

### `PATCH /admin/matches/{match_id}/vod`
Admin required (`Depends(require_admin)`). Body `{"vod_url": "https://..." | null}`; rejects
non-`http(s)` values with 422, 404 if the match doesn't exist. Also surfaced as a `vod_url`
field on `GET /admin/matches`.

## Generation

`weeks.generate_weekly_summaries(db)` runs from the same background loop as `auto_lock_weeks`
(`_week_maintenance_loop` in `backend/main.py`, interval `WEEK_CHECK_INTERVAL`). It inserts a
`WeeklySummary(week_id, generated_at)` row for every `Week` whose `end_time` has passed and has
no row yet — idempotent, and with no dependency on calendar day/time.

## Models

`Match.vod_url` (nullable string), `WeeklySummary` (`week_id` PK, `generated_at` — availability
marker only, no denormalised content), `WeeklySummaryReveal` (`week_id`, `user_id`,
`revealed_at`; unique per week/user), `WeeklySummarySeen` (`user_id` PK, `last_seen_week_id`).

---

*Implemented via `markdown/plans/plan-issue-51-weekly-summary.md`.*
