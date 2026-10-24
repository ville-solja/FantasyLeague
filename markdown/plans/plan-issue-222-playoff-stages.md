# Plan: Playoff Stages in Scoring

## Context
Scoring runs in fantasy weeks. A week locks a snapshot of each roster at its `start_time`, and it scores the matches assigned to it: by `week_override_id`, or else by `start_time` inside its window. The tournament organiser has added semifinals and grand finals. They don't follow the weekly rhythm, and the two divisions play them at different paces: the upper division has more matches, so its playoffs take longer. Issue #222 asks how scoring could support them without breaking the week structure, and to compare practical alternatives.

### Options

| # | Option | How it works | Code | Pros | Cons |
|---|---|---|---|---|---|
| 1 | **One long Playoffs week** | The admin creates one week from the first semifinal to the last grand final. | None | Works today. | One lock for 2–3 weeks: no roster changes between the semifinals and the finals. One token and one Weekly Report. Lower-division players finish early and sit idle. |
| 2 | **Override playoff series into ordinary weeks** (the issue's first idea) | Keep weekly windows and use Admin › Matches "Move to week" to put each series in a chosen week. | None | Works today with existing tools. | Weeks become arbitrary buckets, and some contain only one division's matches. The lock time is still a calendar date, unrelated to when each round starts. |
| 3 | **Stage weeks** (recommended) | A new kind of week, a *stage*. It locks at the stage's start like any week, but scores only the series assigned to it. It may overlap other weeks and stages. | Small | Each stage (for example "Lower semifinals", "Upper semifinals", "Grand finals") locks its own roster snapshot when it starts. Players set their roster before each stage, which gives the "separate events" feel without a second roster system. Leaderboards, the Weekly Report, bench substitution and tokens work unchanged. | Rosters are still one live roster: a stage's snapshot is the roster as it stood at that stage's lock. You can't edit the roster of a stage that has already locked. |
| 4 | **Separate events with parallel rosters** (the issue's second idea) | Each event has its own roster, so a user keeps several rosters at once and a card may be in more than one. | Large | The most flexible. | It changes the roster model, My Team, roster limits, locking, scoring, leaderboards, the Weekly Report and the Twitch panel. That's a drastic change for a few series a season. |
| 5 | Per-match scoring with no windows | Score every match for the roster held at its start. | Large | No windows to manage. | It replaces the core of the game, and roster snapshots per match are expensive. |

**Recommendation at planning time: option 3, stage weeks** (revised for season 16 under Feasibility below). It keeps the week structure, which is the whole engine, and fixes the real problem: the lock moment and the set of scored matches follow the bracket, not the calendar. For the current season, if there isn't time to build it, option 1 (one long week) or option 2 (overrides) works today with no code. The plan below builds option 3.

Assumptions:
- **Few series:** playoff series are few (semifinals and finals for two divisions, about six series), so assigning them by hand in Admin › Matches is enough. If the fixtures feed marks playoff series (a stage or round field), Step 1 records it as a later shortcut. I couldn't reach the feed or the schedule site from the planning environment.
- **Admin-set times:** a stage's `start_time` is its lock time, normally just before its first series. Its `end_time` is when the Weekly Report and bench substitution become due, normally after its last series. The admin sets and can edit both.
- **Tokens:** every lock grants +1 token as today, so a stage lock does too. The admin plans how many stages to create with that in mind.
- **More games, more points:** the upper division plays more games, so its players can score more. That's normal fantasy behaviour (deeper runs are worth more), and the plan doesn't normalise it.

Feasibility timeline: https://claude.ai/artifact/WofLAWSmtKkTrF4p79R2bt (private until shared). Paste the fixtures feed's JSON into it and it draws both divisions' playoff series against the fantasy weeks. It proposes stages, one per division and round, that can be edited, and it lists problems: a series that starts before its stage locks, a stage that locks before the previous round of the same division is over, a stage that ends too soon after its last series, unscheduled series, and token and report counts. It opens with example data, because the feed couldn't be reached from the planning environment.

### Season 16 fixtures (feed of 24 Oct 2026)
- **Lower division:** 6 teams, league weeks 1–5; regular season finished Sun 18 Oct.
- **Upper division:** 8 teams, league weeks 1–7; 7 series still to play, 5 of them without a date; its week 7 is 26 Oct – 1 Nov.
- **What this means:** the lower playoffs can start while the upper regular season is still running. That's the "different pace" in the issue.
- **No playoff fixtures in the feed yet.** Until the organiser adds them, the app's schedule, series results and out-of-week check can't see playoff series. Admins must assign them by hand whatever option is chosen.
- **Off-week series:** three regular-season series were already played outside their league week. Week overrides (#193) handle them.

### Feasibility (timeline artifact)
Organiser input (24 Oct): the first lower semifinal is Sun 25 Oct and the other about two weeks later, so even one round has a large calendar gap. With that:
- **Per-round stages don't fit.** A "Lower semifinals" stage would lock on 25 Oct and keep that roster until about 9 Nov (15 days), much like option 1.
- **Too late for this season:** option 3 also can't be live before the 25 Oct lock.
- **Ordinary weeks fit this schedule:** each series scores in the fantasy week it's played, with that week's roster. The lower semifinals fall in the weeks of 19 Oct and 2 Nov; the week of 26 Oct has no lower playoff series.
- **Operational needs this season:**
  - fantasy weeks must exist until the last final;
  - a series played outside its week needs an override (#193);
  - the playoff matches must be ingested: if the organiser runs them under a different OpenDota league, that league must be added to Monitored leagues.

The upper final is a LAN event on Sat 14 Nov. It falls in the week of 9 Nov, so ordinary weeks score it as any other series; the week design already allows for LAN finals (`admin-week-management.md`). It adds one check: the LAN games must be played as league lobbies, so OpenDota records them under the monitored league. LAN replays may also parse late; unparsed games show as partial (unparseable match handling).

The upper semifinal dates are still guesses. Replace them in the artifact when known.

**Revised recommendation (24 Oct): option 2 for season 16, no code.** Keep weekly fantasy weeks running through the playoffs, and check the three operational points above. Option 3 stays a plan for a later season. Building it is only worth it if a future bracket packs rounds into a few days, so that separate locks per round matter. If it is built, one stage per series (not per round) avoids long locks when a round is spread out.

### Decision for season 16 (24 Oct 2026)
The product owner chose ordinary weeks with no code change:
- **Weekly to week 7:** the weekly schedule continues through week 7.
- **Lower playoffs:** the lower semifinals and final have no league week. Each scores in the fantasy week it is played.
- **LAN week:** the LAN (upper semifinals and grand final on 14 Nov) gets its own fantasy week.
- **Idle cards:** bench substitution swaps out active cards whose players didn't play in a given week.

Weeks created in Week Management:

| Week | Dates |
|---|---|
| Week 7 | 26 Oct – 1 Nov |
| Week 8 | 2–8 Nov |
| Lan finals weekend | 9–15 Nov |

They run back to back, so every date up to 15 Nov is covered. Stage weeks (option 3) are not built; the plan stays on file for a later season.

Resolves GitHub issue #222.

## User Stories

### Create a Playoff Stage
**User story**
As an admin, I want to create a playoff stage with its own lock time so that rosters lock when that round of the bracket starts, not on a calendar boundary.

**Acceptance criteria**
- Week Management can create a week as a **stage** (`weeks.kind = "stage"`; ordinary weeks are `"week"`), with a label, start date and time, and end date and time
- A stage may overlap any other week or stage; two ordinary weeks still cannot overlap (409 as today)
- A stage locks at its `start_time` like any week: roster snapshot, +1 token, irreversible
- A stage appears in every week list (Weekly leaderboard, Week History, Weekly Report) under its label, marked as a stage
- Creating, editing and deleting a stage is audit-logged as weeks are

### Assign Playoff Series to a Stage
**User story**
As an admin, I want to put each playoff series into its stage so that it scores there and nowhere else.

**Acceptance criteria**
- Admin › Matches "Move to week" lists stages as well as weeks; choosing a stage sets `week_override_id` for the whole series, as today
- A stage scores only the matches assigned to it; a match inside a stage's dates that isn't assigned to it doesn't count there
- A match is never counted in two weeks: an assigned match counts only for its stage, even when an ordinary week's window also contains it
- Matches not assigned to any stage keep today's rule (override, else the ordinary week whose window contains them); stages are never chosen by time
- Moving a series into or out of a stage re-runs bench substitutions for the affected weeks that already ran them, as today
- The out-of-week check (`schedule.out_of_week_series`) doesn't flag series assigned to a stage

### Play the Playoffs Stage by Stage
**User story**
As a player, I want each playoff stage to lock my roster when it starts so that I can adjust my team between rounds.

**Acceptance criteria**
- My Team edits the roster for the next unlocked week or stage, the one that starts first, and shows its label and lock time
- After a stage locks, roster changes apply to the next stage, even while the locked stage is still being played
- A stage's points are the sum of its assigned matches for the cards in its snapshot (bench substitution included); the season leaderboard adds stages like weeks
- How to Play explains stages in one short paragraph

### See Stages Clearly *(not yet implemented)*
**User story**
As a player, I want the schedule and the bracket to show which stage each playoff series belongs to so that I know which roster it scores for.

**Acceptance criteria**
- The Schedule tab and the tournament bracket (#94) label playoff series with their stage
- Needs the bracket view from #94

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `Week.kind` (String, default `"week"`, not null) |
| `backend/migrate.py` | Numbered migration: `ALTER TABLE weeks ADD COLUMN kind TEXT NOT NULL DEFAULT 'week'` with the `PRAGMA table_info` guard |
| `backend/match_scoring.py` | `match_in_week_sql(match_alias, week_alias)`: the one condition for "this match counts for this week", replacing the copies |
| `backend/weeks.py` | `week_containing` ignores stages; the substitution and report queries use the shared condition |
| `backend/routers/leaderboard.py`, `backend/routers/cards.py`, `backend/routers/weekly_summary.py` | Use `match_in_week_sql` instead of their own copies of the window condition |
| `backend/routers/admin_weeks.py` | `kind` on create and edit, with times as well as dates for stages; the overlap check only compares ordinary weeks |
| `backend/schedule.py` | `out_of_week_series` skips series assigned to a stage |
| `frontend/app-admin-weeks.js`, `frontend/app-admin-matches.js` (or wherever "Move to week" lives) | Stage option in the week form; stages in the move list |
| Week lists in the frontend | A "Stage" marker next to stage labels |
| How to Play (`frontend/index.html` or its partial) | One paragraph on stages |
| `markdown/features/core/weeks.md`, `markdown/features/reference/playoff-stages.md` | Docs |
| `backend/tests/test_issue_222_playoff_stages.py` | Tests |

### Step 1 — Check the data
- Look at the fixtures feed (`SCHEDULE_FIXTURES_URL`) on the test server: do playoff fixtures carry a `week`, a `stage` or a round name? Record the answer in this plan. A stage field could later drive an "assign by stage" shortcut. It isn't needed for this plan.
- List every place that repeats the window condition: `week_override_id = … OR (week_override_id IS NULL AND start_time BETWEEN …)`. It is currently in `leaderboard.py`, `cards.py`, `weekly_summary.py` and `weeks.py`.

### Step 2 — Model and the shared condition
- Add `Week.kind` and its migration.
- `match_scoring.match_in_week_sql`:

```python
def match_in_week_sql(m="m", wk="wk") -> str:
    """A match counts for a week (issue #222): assigned to it, or, for an ordinary
    week only, unassigned and inside its window."""
    return (f"({m}.week_override_id = {wk}.id OR ({wk}.kind = 'week' "
            f"AND {m}.week_override_id IS NULL "
            f"AND {m}.start_time BETWEEN {wk}.start_time AND {wk}.end_time))")
```

- Queries that pass the week as parameters (`:week_id`, `:ws`, `:we`) gain a `:wkind` parameter, or join `weeks`. Use one form everywhere.
- `weeks.week_containing` filters `Week.kind == "week"`, so time never picks a stage, and `scoring_week_for` stays correct.

### Step 3 — Admin
- `POST/PUT /admin/weeks` accept `kind`. A stage takes a start and an end date and time (league time). The existing formula still makes ordinary weeks from dates.
- `_check_week_overlap` runs only when both weeks are ordinary.
- Editing a locked stage's `end_time` is allowed (a delayed final), as for weeks.
- The "Move to week" list in Admin › Matches includes stages, labelled "Stage: …".
- `out_of_week_series` treats a series assigned to a stage as an explicit decision.

### Step 4 — Player-facing
- `get_next_editable_week` already picks the earliest unlocked week by `start_time`; confirm it with overlapping stages.
- Show a small "Stage" marker in week dropdowns and headers; the label carries the name.
- Add the How to Play paragraph:
  > "In the playoffs, each stage locks your roster when it starts. Changes after that apply to the next stage."

### Step 5 — Docs and tests
- Docs:
  - `weeks.md`: add stages to Week Structure, the Week Override order, and Roster Scoring;
  - `admin-week-management.md`;
  - the feature doc.
- Tests:
  - migration;
  - a stage overlapping an ordinary week can be created, and two overlapping ordinary weeks still return 409;
  - a match inside both windows: unassigned, it counts only for the ordinary week; assigned to the stage, it counts only for the stage;
  - `week_containing` ignores stages;
  - two overlapping stages lock separately and each snapshot holds the roster at its own lock;
  - roster changes after the first lock show in the second snapshot;
  - weekly and season leaderboards, `GET /roster` points and the Weekly Report agree for a stage;
  - substitutions re-run after moving a series into a stage;
  - `out_of_week_series` ignores stage series;
  - every scoring reader uses `match_in_week_sql` (a static check that the old condition is gone).

## Verification
- `cd backend && python -m pytest tests/test_issue_222_playoff_stages.py tests/test_migrate.py`, then the full suite.
- On the test server, rehearse the playoffs:
  - create "Lower semifinals", "Upper semifinals" and "Grand finals" with overlapping dates;
  - assign their series;
  - check that each locks at its start and that roster changes in between land in the next stage;
  - after the ends, compare the weekly leaderboard per stage, the season total and the Weekly Report.
- Migration adds one column with a default; no env vars.
