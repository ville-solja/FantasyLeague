# Plan: Season Scenarios

## Context
Testing a mid-season feature by hand on a dev or test server means building the state first: locked weeks, rosters with a bench, scored matches with MVPs, a substitution, an unparsed match. That takes hours. This issue adds one admin action under Demo Mode that replaces the game data with a named, deterministic season (`pre-season`, `mid-season`, `season-end`) and sets the demo clock to match. It also adds a startup rule that makes Demo Mode impossible in production.

It is split from the umbrella plan `plan-issue-114-testing-tooling.md`, with these updates for the code as it is now:

- **The wipe reuses `season_reset` (#133).** `season_reset.clear()` already empties every season table, and `TABLE_GROUPS` covers every model table. Scenarios add their own list of what they keep, and a test checks it the same way.
- **The season generator becomes pure data.** `backend/season_generator.py` returns plain dicts (teams, players, weeks, matches, stats, users, cards) from a seed, with no database. That lets the mock OpenDota (#146) build the same league in its own container. The scenario loader and `scripts/bench_leaderboards.py` write that data to the database.
- **Weeks lock through the real code path.** The loader advances the demo clock week by week and runs `auto_lock_weeks`, `due_substitutions` and `generate_weekly_summaries`, the same sequence as `POST /admin/demo/clock`. Roster snapshots, substitutions and Weekly Reports therefore come from production code, not from hand-written rows.

**Assumptions:**
- **Loading needs a recent password re-entry** (`require_recent_reauth`), like the other admin actions that destroy data. The issue doesn't ask for it, but the load replaces every account except the caller's.
- **What is kept:** the caller's own user row and sessions, `weights`, `scoring_state`, `tag_definitions`, `audit_logs`, and the `demo_clock` row (which gets set). Everything else is cleared, including season history, other users and their linked rows. Scenario history therefore never mixes with real data.
- **Fixed dates.** Week 1 starts on Monday 2026-01-05 00:00 UTC. Scenario data never depends on the real time.
- **Scenario accounts:** `scenario-admin` (admin) and `scenario1` to `scenario5`, all `is_demo=True`, with the password from `DEMO_ACCOUNT_PASSWORD` and emails `@demo.local`. The caller stays logged in as themselves.
- **Synthetic names only:** teams "Scenario Team A" to "Scenario Team H" and generated player names. No real league data is used. The league id is a fixed constant shared with the mock (`SCENARIO_LEAGUE_ID = 990001`).

Resolves GitHub issue #145.

## User Stories

### Load a Season Scenario
**User story**
As a developer testing on a dev or test server, I want to reset the app to a named, realistic season state in one action so that I can test mid-season features without building the state by hand.

**Acceptance criteria**
- `POST /admin/demo/scenario` with `{"name": "pre-season" | "mid-season" | "season-end"}` replaces all game data with the named scenario and sets the demo clock to match. It is admin only, needs a recent password re-entry, and gives 404 when `DEMO_MODE` is off
- **mid-season:** 10 weeks, 5 locked and scored, and week 6 open for edits. 8 teams of 5 synthetic players. 1 admin and 5 player accounts with 10–15 cards each. Rosters with benches, at least one bench substitution, and MVPs on most matches. One unparsed match and one match excluded from scoring
- **pre-season:** 10 weeks, none locked, and accounts with starter tokens and a few cards. **season-end:** all 10 weeks locked and scored, with no archive yet, so End Season can run
- The same scenario name always produces the same data, with the same seed and the same totals
- The loader refuses to run without `DEMO_ACCOUNT_PASSWORD` (409 with a clear message), and writes a `demo_scenario_loaded` audit entry
- Stored card points (#141) are rebuilt and substitutions (#129) run for finished weeks, so every page shows the same numbers right after loading
- The admin Demo panel has a scenario picker with an in-page confirmation step. It never uses `confirm()`

### Demo Mode Can Never Reach Production
**User story**
As an operator, I want the test tools impossible to switch on in production so that a misconfiguration can't wipe real data.

**Acceptance criteria**
- With `ENV=production`, startup fails when `DEMO_MODE=true`, with a clear `[SECURITY]` message
- Every demo endpoint returns 404 when `DEMO_MODE` is off, before any admin check
- The docs list the test setup for `test.kana-cards.com`: `DEMO_MODE=true`, `DEMO_ACCOUNT_PASSWORD` set, `ENV` unset

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/season_generator.py` *(new)* | Pure, seeded generator: teams, players, weeks, matches with per-player stats, users and cards as dicts. No database, no app imports beyond `scoring.SCORING_STATS` and `card_utils._SCORED_STAT_COLS` |
| `backend/scenarios.py` *(new)* | `SCENARIOS`, `KEPT_TABLES`, `load(db, name, caller_id)`: wipe, write the generated data, step the clock through the weeks, rebuild card points |
| `backend/routers/admin_demo.py` | `POST /admin/demo/scenario` |
| `backend/main.py` | Add `DEMO_MODE` to the `ENV=production` dev-flag refusal |
| `scripts/bench_leaderboards.py` | `seed()` writes `season_generator` output; same counts for the same arguments |
| `frontend/app-admin-demo.js` | Scenario picker, in-page confirmation, re-auth through `adminFetch` |
| `.env.example` | `DEMO_ACCOUNT_PASSWORD` with a comment |
| `markdown/features/reference/testing-tooling.md`, `demo-mode.md` | Docs, including the test-server setup |
| `backend/tests/test_issue_145_season_scenarios.py` | Tests |

### Step 1 — Pure season generator
Move the data generation out of `scripts/bench_leaderboards.py::seed()` into `season_generator.generate(seed, *, weeks, teams, players_per_team, games_per_team_week, users, cards_per_user, roster_size, start)`. It returns dicts with fixed ids. Keep the `random.Random` call order, so the bench produces the same counts (`matches`, `stat_rows`, `cards`, `roster_entries`) for its default arguments. Add the fields the scenarios and the mock need: `hero_id` per stat row, `radiant_name` and `dire_name`, `parse_status`, `start_time` inside each week, and a series grouping (games of one pair within `schedule.SERIES_GAP_SECONDS`).

`scripts/bench_leaderboards.py` writes that output to its temp database exactly as it does now.

### Step 2 — Scenario definitions
```python
SCENARIOS = {
    "pre-season": dict(seed=145_001, locked_weeks=0, ...),
    "mid-season": dict(seed=145_002, locked_weeks=5, unparsed=1, excluded=1, ...),
    "season-end": dict(seed=145_003, locked_weeks=10, ...),
}
```
Matches exist only for weeks the scenario has finished. Mid-season's weeks 6–10 have no matches; the mock (#146) releases them.

### Step 3 — Wipe
In one transaction, run `season_reset.clear(db)`, then delete every non-kept table that `clear` leaves, except the caller's `users` and `user_sessions` rows. `scenarios.KEPT_TABLES` names what stays. A test fails when a model table is in neither `season_reset.CLEARED_TABLES` nor `scenarios.KEPT_TABLES` nor the scenario's own extra-delete list, mirroring the #133 test.

### Step 4 — Build
1. Insert the league (monitored), teams, players, weeks (all unlocked), accounts and cards. Use `bench`-style writes for cards and modifiers. Only the active roster cards get a `slot_index`.
2. Insert the matches for week 1.
3. Step the clock: for each week to lock, `clock.set_override(db, lock_time)`, then `auto_lock_weeks`, `due_substitutions` and `generate_weekly_summaries`. Before locking the next week, change one account's active roster deterministically and insert that week's matches. One rostered player sits out one locked week, which gives the bench substitution.
4. MVPs: set `is_mvp` on the stat rows as the generator decides (most matches, not all), the same flag `upsert_mvp` writes.
5. Mid-season only: one match with `parse_status="unparsed"` and partial stats, and one with `excluded_from_scoring=True`.
6. `card_points.rebuild_all(db)`, then set the final clock (mid-season: the middle of week 6, before its lock), commit, and run `season_reset.bust_caches()`.
7. Audit `demo_scenario_loaded` with `name=… users=… matches=…`.

### Step 5 — Endpoint
```python
class ScenarioBody(BaseModel):
    name: Literal["pre-season", "mid-season", "season-end"]

@router.post("/admin/demo/scenario",
             dependencies=[Depends(_require_demo_mode), Depends(require_recent_reauth)])
```
Call `_require_demo_mode()` imperatively too (the tests call endpoints directly). Return 409 without `DEMO_ACCOUNT_PASSWORD`. Answer with the scenario name, the effective clock, the account usernames (never the password) and the counts.

### Step 6 — Production guard
Add `"DEMO_MODE"` to `_active_dev_flags` in `main.py`. The message names it like the others.

### Step 7 — Admin UI and docs
In the Demo panel: a select with the three names, a short description of each, a Load button, an in-page confirmation ("Replaces every account except yours and all game data"), then `adminFetch`, which handles re-auth. After loading, show the counts and reload the clock display. Document the test-server setup in `demo-mode.md`.

## Verification
- `cd backend && python -m pytest tests/test_issue_145_season_scenarios.py tests/test_issue_83_demo_mode.py tests/test_issue_133_season_reset_clean_slate.py -q`, then the full suite.
- Loading mid-season twice gives identical results: season leaderboard, weekly leaderboard for weeks 1–5, each account's My Team week points and the Weekly Report totals.
- Mid-season: at least one `WeeklyRosterEntry` substitution in weeks 1–5, week 6 editable, one unparsed and one excluded match, and stored card points equal to `card_points.check_week` for every locked week.
- 404 with `DEMO_MODE` off, even for an admin. 403 `reauth_required` without a recent re-auth. 409 without `DEMO_ACCOUNT_PASSWORD`.
- `ENV=production` with `DEMO_MODE=true` fails at import with `[SECURITY]`.
- `python3 scripts/bench_leaderboards.py` reports the same seed counts as before the move.
- Manual on the test server: load mid-season, log in as `scenario1`, and check My Team shows a substitution and the leaderboards are populated.
