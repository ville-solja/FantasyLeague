# Plan: Test Background Task Isolation

## Context
`backend/tests/test_issue_124_roster_mutation_rate_limiting.py` now fails on most full-suite runs. It used to fail about once in five. The typical failure is a roster call returning 404 or 409 for a card the test has just seeded. The same file passes every time on its own. The developer on issue #136 measured 2–3 failures in 15 when it runs straight after any test that reloads `main`.

The cause is recorded in `markdown/lessons-learned.md` and in the architecture review. Entering `TestClient(main.app)` as a context manager runs the app's lifespan, which starts four background threads: week maintenance, ingest polling, profile enrichment and database backups. They start inside tests and keep running after the test that started them. They share the test's in-memory SQLite connection, or reach the real `data/fantasy.db`. A rollback or query from one of them can undo or hide rows a later test just wrote. The backup loop also logs `PermissionError` against the real `data/` directory on every run.

CI runs the same suite on every push through `.github/workflows/unit-tests.yml`, so the flake now fails builds at random. The fix is to not start background threads under tests. Tests that exercise a loop's work call its function directly, as they already do.

**Assumption:** no test depends on a background thread actually running. Any that does is changed to turn tasks back on for itself, or to call the loop body directly.

## User Stories

### Tests Never Start Background Threads
**User story**
As a developer, I want the test suite to run without the app's background threads so that tests cannot interfere with each other through a shared database.

**Acceptance criteria**
- A `BACKGROUND_TASKS_ENABLED` env var, default `true`, controls whether the lifespan starts the week-maintenance, ingest-poll, profile-enrichment and backup threads
- `backend/tests/conftest.py` sets `BACKGROUND_TASKS_ENABLED=false` before any app module is imported, so no test starts those threads by default
- The lifespan still runs its synchronous startup work, such as table creation, migrations and seeding, and logs one line saying background tasks are disabled
- A test that opens `TestClient(main.app)` as a context manager starts no new threads. The number of live threads is the same before and after
- No test writes a backup file into the real `data/` directory, and the "Automatic DB backup failed" log line no longer appears during the suite

### Stable Full-Suite Runs
**User story**
As a developer, I want the full suite to pass repeatedly so that a red CI build means a real regression.

**Acceptance criteria**
- `test_issue_124_roster_mutation_rate_limiting.py` passes in 10 consecutive full-suite runs
- The suite-size tripwire in `test_issue_85_split_admin_router.py` passes in the same runs
- Production behaviour is unchanged: with the variable unset, all four threads start as before

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/main.py` | Lifespan skips starting the four background threads when `BACKGROUND_TASKS_ENABLED` is `false` |
| `backend/tests/conftest.py` | Set `BACKGROUND_TASKS_ENABLED=false` at import time, before `main` or any router is imported |
| `backend/tests/test_test_background_task_isolation.py` | Tests for the acceptance criteria |
| `markdown/features/reference/automated-testing.md` | Explain the variable and why tests disable background tasks |
| `markdown/lessons-learned.md` | Point the existing flake entries at the fix |

### Step 1 — Lifespan switch
In `lifespan()`, wrap the `threading.Thread(...).start()` calls and their log lines in a single `if os.getenv("BACKGROUND_TASKS_ENABLED", "true").lower() != "false":` block. Log `"Background tasks disabled (BACKGROUND_TASKS_ENABLED=false)"` otherwise. Leave `DEMO_MODE`'s existing ingest skip as it is.

### Step 2 — conftest
At the top of `backend/tests/conftest.py`, before the other imports, add `os.environ.setdefault("BACKGROUND_TASKS_ENABLED", "false")`. Grep the tests for anything that relies on a running loop, for example asserting the backup thread started, and have those tests set the variable to `true` for themselves.

### Step 3 — Verify
Run the full suite ten times in a row and record the results.

## Verification
- `cd backend && python3 -m pytest tests/test_test_background_task_isolation.py -v`.
- Ten consecutive full-suite runs pass with no failures in `test_issue_124` or the `test_issue_85` tripwire. Bump the tripwire by the number of new tests.
- The suite output has no "Automatic DB backup failed" line.
- Starting the app normally, with the variable unset, logs all four "thread started" lines.
