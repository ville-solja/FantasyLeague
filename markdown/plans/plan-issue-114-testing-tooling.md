# Plan: Testing Tooling: Season Scenarios and Mock OpenDota

## Context
Testing a feature by hand on a dev or test server is slow, because most features only show up in a mid-season state: locked weeks, rosters with a bench, ingested matches with MVPs, unparsed matches, substitutions, a populated leaderboard. Building that state by hand takes hours. Real league data only arrives as the actual season plays out, and it can't be replayed.

The issue asks for a mock of the match-data API, to mimic the real process more closely. "OpenAI" in the issue is read as **OpenDota**, the app's only match-data source. It also asks for a way to restore the environment to a known state in debug mode.

What exists already:
- **Demo Mode** (`DEMO_MODE=true`, `backend/routers/admin_demo.py`): an admin-set clock override and disposable demo accounts. It turns off ingest polling.
- **A deterministic season generator** in `scripts/bench_leaderboards.py` (#141): users, cards, weeks, matches and stats from a seed.
- **Local fallbacks for every other outside service:** `TWITCH_LOCAL_DEV` logs Twitch calls, unset SMTP logs emails, and unset Anthropic and Toornament settings skip those features.
- **OpenDota's address is hard-coded** (`opendota_client.OPEN_DOTA_URL`).

This plan adds three tools, all gated behind `DEMO_MODE`:
1. **Named season scenarios.** An admin action resets the database to a realistic, deterministic state such as "mid-season", and sets the demo clock to match.
2. **A mock OpenDota server.** A small local service the app can point at. It serves a scripted league and lets a tester "finish" the next match, make a game live, or turn an unparsed match into a parsed one, so the real ingest path runs end to end.
3. **Snapshots.** Save the current test database under a name and restore it later, to repeat a manual test from the same starting point.

**Assumptions:**
- **The gate is `DEMO_MODE`, not `DEBUG`.** `DEMO_MODE` is the existing gate for state-changing test tools and already hides its endpoints with 404 when off. `DEBUG` only controls logging and the startup checks. Production refuses neither today, so the startup guard gets a new rule: `ENV=production` refuses `DEMO_MODE=true`.
- **Scenario data is synthetic:** generated players, teams and users with clearly fake names. It never copies real league data.
- **Scenario accounts:** one admin and five players, with a shared password from `DEMO_ACCOUNT_PASSWORD`. Without that setting, the scenario loader refuses to run.
- **Snapshots** use SQLite's online backup API in both directions, so the app keeps running while one is restored. They live in `data/demo-snapshots/`, separate from the real backups.
- **The mock OpenDota server is a dev tool** in `tools/mock_opendota/`, run as an optional Docker Compose service in `docker-compose.dev.yml`. It is never part of the production image.

Resolves GitHub issue #114, which is split into three issues that can be built separately:
- **#145 Season scenarios:** stories "Load a Season Scenario" and "Demo Mode Can Never Reach Production"
- **#146 Mock OpenDota:** story "Drive Ingest with a Mock OpenDota"
- **#147 Snapshots:** story "Save and Restore a Test Snapshot"

## User Stories

### Load a Season Scenario
**User story**
As a developer testing on a dev or test server, I want to reset the app to a named, realistic season state in one action so that I can test mid-season features without building the state by hand.

**Acceptance criteria**
- `POST /admin/demo/scenario` with `{"name": "pre-season" | "mid-season" | "season-end"}` (admin, `DEMO_MODE` only, otherwise 404) replaces all game data with the named scenario and sets the demo clock to match
- **mid-season:** 10 weeks, 5 locked and scored, week 6 open for edits. 8 teams of 5 synthetic players, 1 admin and 5 player accounts with 10–15 cards each, rosters with benches, at least one bench substitution, MVPs set on most matches, one unparsed match and one excluded match
- **pre-season:** weeks created, none locked, accounts with starter tokens and a few cards. **season-end:** all weeks locked and scored, ready for End Season
- The same scenario name always produces the same data: same seed, same totals
- The loader refuses to run without `DEMO_ACCOUNT_PASSWORD`, and writes a `demo_scenario_loaded` audit entry
- Stored card points (#141) are rebuilt, and substitutions (#129) are run for finished weeks, so every page shows consistent numbers right after loading
- The admin Demo panel shows a scenario picker with a confirmation step in the page; it never uses `confirm()`

### Drive Ingest with a Mock OpenDota
**User story**
As a developer, I want the app to ingest matches from a local mock OpenDota so that I can test ingest, live polling, parse retry and early MVP selection exactly as they run in production.

**Acceptance criteria**
- `OPENDOTA_BASE_URL` (default `https://api.opendota.com/api`) replaces the hard-coded address; every OpenDota call uses it
- `tools/mock_opendota/` serves the endpoints the app calls: `/leagues/{id}`, `/leagues/{id}/matchIds`, `/matches/{id}`, `/live`, `POST /request/{id}` and `/constants/heroes`. Responses follow the field shapes the app reads, including `/live` with a string `match_id` and players without names
- The mock's control endpoints let a tester:
  - `POST /_control/next-match`: release the next scripted match
  - `POST /_control/live`: make a scripted game live for N minutes
  - `POST /_control/parse/{id}`: turn an unparsed match into a parsed one
  - `POST /_control/reset`: reset the script
- The script matches the mid-season scenario's teams and players, so mock matches score against scenario rosters
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile mock up` starts the app with the mock and `OPENDOTA_BASE_URL` pointing at it. Ingest polling runs normally in that profile
- With `ENV=production`, startup refuses an `OPENDOTA_BASE_URL` that isn't https

### Save and Restore a Test Snapshot
**User story**
As a tester, I want to save the test database and restore it later so that I can repeat a manual test from the same starting point.

**Acceptance criteria**
- `POST /admin/demo/snapshots` with `{"name"}` (letters, digits, hyphen; 1–40 characters) saves a copy of the live database to `data/demo-snapshots/{name}.db`
- `GET /admin/demo/snapshots` lists the saved snapshots with name, size and time
- `POST /admin/demo/snapshots/{name}/restore` restores one into the live database while the app keeps running, then rebuilds stored card points
- All three are admin and `DEMO_MODE` only (404 otherwise), and need the admin password re-entry from #117, since restore overwrites everything
- Snapshot names never become paths outside `data/demo-snapshots/`; anything else gets 422
- Restoring keeps the restoring admin logged in: their user row is in the snapshot, and the session table is preserved across the restore. Every other session ends

### Demo Mode Can Never Reach Production
**User story**
As an operator, I want the test tools impossible to switch on in production so that a misconfiguration can't wipe real data.

**Acceptance criteria**
- With `ENV=production`, startup fails when `DEMO_MODE=true`, with a clear `[SECURITY]` message
- Every scenario and snapshot endpoint returns 404 when `DEMO_MODE` is off, before any admin check, as the existing demo endpoints do
- The docs list the test setup for `test.kana-cards.com`: `DEMO_MODE=true`, `DEMO_ACCOUNT_PASSWORD` set, `ENV` unset

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/opendota_client.py` | `OPEN_DOTA_URL` from `OPENDOTA_BASE_URL` |
| `backend/scenarios.py` *(new)* | Deterministic scenario builders, sharing the season generator with `scripts/bench_leaderboards.py` (moved into a shared module) |
| `backend/routers/admin_demo.py` | `POST /admin/demo/scenario`; snapshot list, save and restore |
| `backend/demo_snapshots.py` *(new)* | SQLite online backup and restore helpers, name validation, session-table preservation |
| `backend/main.py` | Startup guards: `ENV=production` refuses `DEMO_MODE=true` and a non-https `OPENDOTA_BASE_URL` |
| `tools/mock_opendota/` *(new)* | Small FastAPI app with scripted league data and control endpoints; Dockerfile |
| `docker-compose.dev.yml` | `mock` profile: the mock service, plus `OPENDOTA_BASE_URL` for the app |
| `scripts/bench_leaderboards.py` | Uses the shared generator; results unchanged against the saved baseline |
| `frontend/app-admin-demo.js`, `frontend/index.html` | Scenario picker and snapshot list in the Demo panel, with in-page confirmation |
| `.env.example`, `markdown/features/reference/demo-mode.md`, `markdown/features/reference/testing-tooling.md`, `README.md` (dev section link) | Docs |
| `backend/tests/test_issue_114_testing_tooling.py` | Tests |

### Step 1 — Configurable OpenDota address
Read `OPENDOTA_BASE_URL` in `opendota_client.py`. `schedule.py` and `ingest.py` already import the constant. Add the production https guard.

### Step 2 — Shared season generator and scenarios
Move the seeding logic from `scripts/bench_leaderboards.py` into `backend/scenarios.py`, keeping it deterministic from a seed. Add builders for the three scenarios, using the real code paths where possible:
- `_snapshot_week` and `auto_lock_weeks` for locking,
- `upsert_mvp` for MVPs,
- `card_points.rebuild_all` for stored points,
- `run_substitutions` for finished weeks.

The loader wipes game tables in one transaction, the same tables as the season-reset path plus users other than the caller, builds the scenario and sets the demo clock. Check the benchmark still matches its baseline.

### Step 3 — Mock OpenDota
`tools/mock_opendota/app.py` holds an in-memory script built from the same generator and seed: league info, a match id list, match JSON in OpenDota's shape, a live list and parse state. It has the four control endpoints listed in the story. Add a Compose profile and a short README in the folder.

### Step 4 — Snapshots
`demo_snapshots.save(name)` runs `sqlite3.Connection.backup()` from the live database to the file. `restore(name)` runs a backup from the file into the live connection, keeping the `user_sessions` rows of the restoring admin. Validate names with `^[A-Za-z0-9-]{1,40}$` and resolve paths under the snapshot folder.

### Step 5 — Guards, UI, docs
Add the startup guards, the Demo panel UI (an in-page confirmation for scenario load and restore, with the re-auth prompt via `adminFetch`), and the docs. The README's development section gets one link to `testing-tooling.md`.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_114_testing_tooling.py tests/test_issue_83_demo_mode.py -v`, then the full suite.
- Loading "mid-season" twice gives identical leaderboard totals. Every page agrees: My Team, both leaderboards and the Weekly Report.
- With `DEMO_MODE` off, every new endpoint gives 404 even for an admin. With `ENV=production` and `DEMO_MODE=true`, startup fails.
- Mock profile: release the next match, and the app ingests it on the next poll. Make a game live, and it appears as provisional in the Twitch panel (#139). Parse an unparsed match, and parse retry replaces its stats.
- Snapshot save and restore round-trips the leaderboard. Snapshot names like `../x` and `a/b` get 422. Restore needs re-auth.
- `python3 scripts/bench_leaderboards.py --compare scripts/bench-leaderboards-baseline.json` shows the same totals as before the generator move.
- Manual on test.kana-cards.com: load "mid-season", log in as a scenario player, check My Team shows substitutions and the leaderboard is populated.
