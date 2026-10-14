# Plan: Match Scoring Week Override

## Context
Issue #193: Hoxhunt Fortum played their league week-4 series against Elisa Oyj on Mon 12.10. at 21:00. Fantasy Week 4 ended Mon 12.10. at 03:00 UTC. So the games counted for Week 5, and Week 4's bench substitution replaced Hoxhunt Fortum players who had in fact played their week-4 match.

**What exists today, and why it didn't help:**
- **A per-match override.** `matches.week_override_id`, set through `PUT /matches/{match_id}/week` (`routers/admin_ingest.py`). Every scoring query honours it: leaderboards, My Team, the Weekly Report, `weeks._players_who_played`. But there is no admin UI for it.
- **The supposed correction mechanism, `POST /admin/sync-match-weeks`.** It sets overrides from the schedule, but:
  - it has no UI and never runs on its own;
  - it pairs the schedule's week label with a fantasy week's label by exact text, which breaks as soon as the labels differ (week labels are admin-chosen);
  - it decides which games belong to a series with a ±3-day window of its own.
- **Bench substitutions don't follow later changes.** `weeks.run_substitutions` already resets and recomputes from scratch and honours overrides. It runs automatically once, `SUBSTITUTION_DELAY_HOURS` (24 h) after the week ends. An override set after that run changes the points, but not the substitutions, unless an admin also presses "Re-run substitutions" in Week Management.

**Why the scoring window can't fix this alone.** On the same Monday evening, Hoxhunt Fortum–Elisa Oyj (league week 4) and Reaktor–Futurice and Metacore–OP Gold (league week 5) were all played. No week boundary separates them. The only reliable signal for which week a series counts in is the league week in the fixtures feed (`league_week` on each series since #194).

**The proposal: keep the window simple and make the exception one admin action.**
1. **Show the scoring week in Admin › Matches.** Each match shows its scoring week, and a week picker sets it for the whole series.
2. **Fix substitutions in the same action.** Changing a series' week re-runs bench substitutions for every finished week it affects. One action fixes points and bench together, whenever it happens.
3. **Flag out-of-week series automatically.** A series whose league week maps to a different fantasy week than the one it is counted in is flagged in Admin › Matches with a one-click fix. The existing sync endpoint is rebuilt on the same detection, replacing the label matching.

Fully automatic reassignment from the feed was considered and left out. It depends on the feed and on team-name matching being right, and admins already manage the fantasy weeks. The flag makes the problem visible, and the admin confirms the fix.

Resolves GitHub issue #193.

## User Stories

### Admin Sets a Series' Scoring Week
**User story**
As an admin, I want to see and change which fantasy week a series counts for in Admin › Matches, so that a series played outside its week scores in the right week.

**Acceptance criteria**
- `GET /admin/matches` adds, per match:
  - `scoring_week_id` and `scoring_week_label`: the override if set, else the fantasy week whose window contains `start_time`, else null;
  - `scoring_week_source`: `override` or `time`.
- The Matches table shows a "Week" column, for example "Week 4" or "Week 4 (set)"; "—" when no week contains the match
- Each row has a week picker:
  - **"By time (Week N)"** clears the override;
  - **every fantasy week label** sets it;
  - **apply to series:** choosing a week applies to every game of the same series. A series means the same two teams, with start times within 6 hours of each other. The confirmation names the number of games ("Count 2 games for Week 4?")
- `PUT /matches/{match_id}/week` keeps its body (`week_id`, null clears) and adds `apply_to_series: bool = true`. It returns the changed match ids, and refuses an unknown week with 404 as today
- One `admin_set_match_week` audit entry per changed match, as today

### Changing a Week Fixes Scoring and Bench Together
**User story**
As an admin, I want a week change to also fix the bench substitutions, so that a player who played isn't left replaced in the week their match now counts for.

**Acceptance criteria**
- After a week change, every affected week (each changed match's old and new scoring week) whose substitutions have already run (`substitutions_at` set) gets `weeks.run_substitutions` again in the same request
- The response lists those weeks with their new substitution counts, and the page shows them, for example "Week 4: substitutions re-run (3)"
- A week whose substitutions haven't run yet is left alone; its scheduled run uses the new assignment
- Leaderboards, My Team and the Weekly Report show the moved points and the corrected substitutions on their next load: any response cache the change affects is busted
- Each re-run writes an `admin_substitutions_rerun` audit entry with `reason=week_override`
- The Hoxhunt Fortum case: moving its 12.10. games to Week 4 removes the Week 4 substitutions of its players, so their week-4 points count, and removes those points from Week 5

### Out-of-Week Series Are Flagged
**User story**
As an admin, I want series played outside their scheduled week to be pointed out, so that I don't have to spot them myself before substitutions run.

**Acceptance criteria**
- For each scheduled series from the fixtures feed that has a result (`series_result.match_ids`) and a `league_week`:
  - its **scheduled fantasy week** is the fantasy week containing its league week's anchor (`week_start` + 3 days, 12:00 league time, the #194 rule);
  - it is **out of week** when any of its matches counts for a different week (by override or time), unless every match of the series has an explicit override (an admin decision, such as "Keep in Week M");
  - a series whose league week has no fantasy week containing its anchor is not flagged.
- Admin › Matches shows "N series played outside their scheduled week" above the table, one line each: teams, played date, scheduled week, counted week, and two buttons:
  - **"Count for Week N"** applies the scheduled week to the series, with the substitution re-run;
  - **"Keep in Week M"** sets an explicit override to the current week, which clears the flag.
- `POST /admin/sync-match-weeks` is rebuilt on the same detection and no longer pairs weeks by label:
  - `dry_run=true` returns the flagged series;
  - without it, it applies all of them and re-runs substitutions as above.
- With the season-16 feed, Hoxhunt Fortum–Elisa Oyj (league week 4, played Mon 12.10.) is flagged as scheduled Week 4, counted Week 5, until it is fixed

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/admin_ingest.py` | `PUT /matches/{match_id}/week`: `apply_to_series`, series grouping, substitution re-run, cache bust; `POST /admin/sync-match-weeks` on the new detection with `dry_run` |
| `backend/weeks.py` | `scoring_week_for(db, match)`, `rerun_substitutions_for(db, week_ids, reason)` (re-runs only weeks with `substitutions_at` set) |
| `backend/schedule.py` | `out_of_week_series(db)`: feed series → scheduled fantasy week (anchor rule) vs counted week per match |
| `backend/routers/admin_matches.py` | `GET /admin/matches`: `scoring_week_id`, `scoring_week_label`, `scoring_week_source`; `GET /admin/matches/out-of-week` (or a field on the list response) |
| `frontend/app-admin-matches.js` | Week column and picker, series confirmation, out-of-week banner with its two buttons, re-run summary |
| `markdown/features/reference/automatic-bench-substitution.md`, `markdown/features/core/admin.md`, `markdown/features/core/weeks.md`, `markdown/ui_description/admin.md` | Existing docs: override, re-run on change, flagging; the sync endpoint's new behaviour |
| `backend/tests/test_issue_193_match_scoring_week_override.py` | Tests |

No schema change: `matches.week_override_id` exists. No new env var.

### Step 1 — Scoring week helpers
- **`scoring_week_for(db, match)`:** returns `(week, "override")` when `week_override_id` is set; otherwise the week whose window contains `start_time`, as `(week, "time")`; otherwise `(None, None)`. Use the same `BETWEEN` rule as the scoring queries.
- **`rerun_substitutions_for(db, week_ids, reason)`:** for each week with `substitutions_at` set, call `run_substitutions` and audit. Return `[(week, count)]`. The caller commits.

### Step 2 — Series-aware override endpoint
In `set_match_week`:
1. Find the series' matches: same team pair, `start_time` within 6 h of the chosen match.
2. Record each match's current scoring week, then set `week_override_id`.
3. Re-run substitutions for the union of old and new weeks, bust the caches, audit, and commit once.

The route keeps `require_admin`. Check whether it needs `require_recent_reauth`: other scoring-changing routes, such as `PATCH /admin/matches/{id}/scoring`, show the precedent.

### Step 3 — Detection and sync
`schedule.out_of_week_series(db)` uses `get_schedule(db)` (series with `league_week`, team ids and `series_result.match_ids`) and the fantasy weeks. For each series it compares the anchor's week with each match's scoring week. Rebuild `sync_match_weeks` on it, with `dry_run`.

### Step 4 — Admin › Matches UI
- **Week column and picker:** a `<select>` per row. On change, confirm with the game count, then send `PUT`.
- **Results:** show the re-run summary and reload the table.
- **Banner:** built from the out-of-week list, with the two buttons. All text goes through `textContent` or `_escHtml`.

### Step 5 — Docs
Update the existing docs only:
- **`automatic-bench-substitution.md`:** re-runs on a week change.
- **`core/admin.md`:** Matches week column, banner, endpoints.
- **`core/weeks.md`:** override precedence and why the league week decides out-of-week series.
- **`ui_description/admin.md`:** the Matches tab.

### Step 6 — Tests
- **Scoring week:** `scoring_week_for` by time, by override, and outside every week.
- **Override endpoint:**
  - `apply_to_series` changes both games of a series, and not a rematch of the same teams days later;
  - an unknown week gives 404;
  - clearing the override returns the match to time-based.
- **Substitution re-run:**
  - moving a series into a week whose substitutions ran re-runs them, and the moved players' entries are no longer `subbed_out`;
  - the old week is re-run too;
  - a week not yet due is not re-run.
- **Points:** a week leaderboard includes the moved points in the new week and not the old.
- **Detection and sync:**
  - with a season-16-like feed, the 12.10. Hoxhunt Fortum–Elisa Oyj series is flagged as scheduled Week 4, counted Week 5;
  - after the fix it is not flagged;
  - "Keep" clears the flag;
  - sync `dry_run` changes nothing, and sync applies and re-runs.
- **Frontend (static):**
  - the picker and banner are built without raw `innerHTML` interpolation of team names;
  - the confirmation names the game count.

## Verification
- **Fix the Hoxhunt Fortum case in production.** Run `bash scripts/backup-db.sh` before the deploy, then:
  1. Admin › Matches shows the banner with Hoxhunt Fortum–Elisa Oyj.
  2. "Count for Week 4" reports "Week 4: substitutions re-run (…)".
  3. My Team and the Week 4 leaderboard count the Hoxhunt Fortum players' points again, and their bench replacements are gone.
  4. Week 5 no longer includes those games.
- **Keep:** another flagged series stays where it is after "Keep in Week M", and the flag is gone.
- **Sync:** `POST /admin/sync-match-weeks?dry_run=true` lists the same series as the banner.
- **Tests:** `cd backend && python -m pytest tests/test_issue_193_match_scoring_week_override.py -q`, then `python -m pytest tests/ -n auto -q`.
