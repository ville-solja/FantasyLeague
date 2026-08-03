# Plan: Split `backend/routers/admin.py` into Focused Sub-Routers

## Context

`backend/routers/admin.py` has grown to 1,236 lines covering ten largely unrelated admin
concerns (users/tokens/codes, ingest/schedule, week management, notifications, tags, player
pool, league management, season lifecycle, matches/MVP, demo mode). This was flagged as a
Medium-severity finding by a systems-architect review earlier in this project's life and
deliberately deferred at the time as "a large refactor with broad blast radius; out of scope
unless requested." Issue #85 is that explicit request. Splitting the file makes each concern
independently reviewable and reduces the chance that an unrelated change (e.g. touching Week
Management) requires scrolling past nine other features to find the right code.

This is a pure internal reorganization — no endpoint path, request/response shape, auth guard,
or audit-log behavior should change. The existing test suite (which calls these handler
functions directly rather than through the ASGI stack) is the primary correctness check, not
new acceptance-criteria tests.

Investigation findings that shape this plan:
- The file already has clear internal section boundaries marked by comment banners (e.g.
  `# Player Pool Management`, `# League Management`, `# Season lifecycle...`, `# Demo Mode...`)
  for everything from the Week Management section onward. Only the first ~600 lines (ingest
  trigger, users/tokens/codes, schedule, week-match sync) are undivided and need a judgment
  call on where to split.
- `backend/main.py:24-34` mounts each router via `from routers import X as X_router` +
  `app.include_router(X_router.router)` — a simple, repeatable pattern with no shared state
  between routers, so adding more of them is mechanical.
- **Two test files import handler functions directly from `routers.admin` by name** —
  `backend/tests/test_issue_81_season_lifecycle.py` (`end_season`, `reset_season`,
  `create_week`, `edit_week`, `delete_week`, plus `import routers.admin as admin_module` for
  the `_stub_backup` monkeypatch fixture) and `backend/tests/test_issue_83_demo_mode.py`
  (`get_demo_clock`, `set_demo_clock`, `clear_demo_clock`, `seed_demo_accounts`). These ~30
  import lines must be updated to the new module paths, and the `_stub_backup` fixture's
  monkeypatch target (`routers.admin.backup_sqlite_db` → `routers.admin_season.backup_sqlite_db`)
  must move with `reset_season`. Missing this is the most likely way this refactor silently
  breaks CI.
- No production code outside `main.py` imports from `routers.admin` (confirmed by grep), so the
  blast radius is exactly: `main.py`, the two test files above, and two `.claude/commands/*.md`
  agent definitions (`security-reviewer.md`, `systems-architect.md`) that cite
  `backend/routers/admin.py` by path — the issue itself asks for `/agent-steward` to be run
  after implementation to catch and fix these.
- `POST /redeem` (in the users/codes group) uses `Depends(get_current_user)`, not
  `Depends(require_admin)` — it's a player-facing endpoint that happens to live in this file
  because it's tightly coupled to admin-created promo codes. It moves with the rest of the
  codes CRUD rather than being extracted separately, to keep "everything about promo codes" in
  one place; noted here so it isn't mistaken for a miscategorized admin route during review.

Resolves GitHub issue #85.

---

## User Stories

### Split Admin Endpoints into Focused Router Modules
**User story**
As a developer working on this codebase, I want admin endpoints grouped into small,
concern-specific router files instead of one 1,200+ line file so that I can find and change
the code for one admin feature without scanning past nine unrelated ones.

**Acceptance criteria**
- `backend/routers/admin.py` is replaced by focused modules, each a self-contained
  `APIRouter()` covering one concern (see Critical Files table below for the exact split)
- Every existing endpoint keeps its exact path, method, request/response shape, and
  `Depends()` auth guard — this is a file reorganization, not a behavior change
- `backend/main.py` imports and `include_router()`s each new module in place of the single
  `admin_router`
- No file in the new split exceeds roughly 350 lines

### Preserve Existing Test Coverage Through the Split
**User story**
As a developer relying on CI, I want the full existing test suite to keep passing unmodified
in behavior (only import paths change) so that the refactor is verifiably behavior-preserving.

**Acceptance criteria**
- `backend/tests/test_issue_81_season_lifecycle.py` and
  `backend/tests/test_issue_83_demo_mode.py` have their `from routers.admin import ...` lines
  updated to import from the correct new module for each function
- The `_stub_backup` monkeypatch fixture in `TestSeasonReset` patches
  `routers.admin_season.backup_sqlite_db` (or wherever `reset_season` lands), not the old path
- `cd backend && python -m pytest tests/ -v` passes with the same pass/skip counts as before
  the split (448 passed, 10 skipped as of this writing)
- `python -c "import main"` succeeds with no import errors

### Keep Developer Agent Definitions Accurate After the Split
**User story**
As a maintainer relying on the project's slash-command agents, I want agent definitions that
cite `backend/routers/admin.py` updated to reference the correct new file(s) so that agent
prompts don't silently point at a file that no longer contains what they describe.

**Acceptance criteria**
- `/agent-steward` is run after the split lands
- `.claude/commands/security-reviewer.md` and `.claude/commands/systems-architect.md` (the two
  files that currently cite `backend/routers/admin.py`) are corrected to reference the new
  module(s), with each corrected file's version header incremented per the agent-steward
  self-update process
- `/agent-steward`'s final status table shows 0 stale/broken agents

---

## Implementation

### Critical Files

| New file | Extracted from `admin.py` section | Approx. lines |
|---|---|---|
| `backend/routers/admin_users.py` | Users list/toggle-tester, grant-tokens, promo codes CRUD + `/redeem`, token-grant-events CRUD | ~1–110, 289–419 |
| `backend/routers/admin_ingest.py` | `/ingest/league/{id}`, `/recalculate`, `/schedule*`, `/matches/{id}/week`, `/admin/sync-match-weeks`, `/admin/sync-toornament`, `/admin/enrich-profiles` | ~47–56, 111–288 |
| `backend/routers/admin_weeks.py` | `WeekCreateBody`/`WeekEditBody`, `_derive_week_times`, `GET/POST/PATCH/DELETE /admin/weeks*` | ~420–549 |
| `backend/routers/admin_notifications.py` | Notifications CRUD | ~550–600 |
| `backend/routers/admin_tags.py` | Tag definitions CRUD + user tag grant/revoke | ~601–677 |
| `backend/routers/admin_players.py` | Player Pool Management (list/add/bulk/remove) | ~678–818 |
| `backend/routers/admin_leagues.py` | League Management (list/monitor/unmonitor/purge) | ~819–909 |
| `backend/routers/admin_season.py` | Season lifecycle (`end_season`, `reset_season`, `backup_sqlite_db` usage) + `GET /audit-logs` | ~910–1040 |
| `backend/routers/admin_matches.py` | Match table + Admin MVP selection | ~1041–1132 |
| `backend/routers/admin_demo.py` | Demo Mode (`_require_demo_mode`, clock, seed-accounts) | ~1133–end |
| `backend/main.py` | Replace the single `admin_router` import/mount with one import + `include_router()` per new module |
| `backend/tests/test_issue_81_season_lifecycle.py` | Update `from routers.admin import ...` lines and the `_stub_backup` monkeypatch target |
| `backend/tests/test_issue_83_demo_mode.py` | Update `from routers.admin import ...` lines |
| `.claude/commands/security-reviewer.md`, `.claude/commands/systems-architect.md` | Updated by `/agent-steward` after implementation, not by this plan directly |

Line ranges are as of this writing and will drift — use the section comment banners already
in the file (e.g. `# Player Pool Management`) as the authoritative split points, not the line
numbers.

### Step 1 — Extract each module

For each row in the table above: create the new file, copy its `APIRouter()` instance and the
relevant endpoint functions/Pydantic models/helpers verbatim, and add only the imports that
section actually uses (each new file's import block will be a subset of `admin.py`'s current
one — e.g. `admin_demo.py` needs `clock` and `weeks.auto_lock_weeks` but not `opendota_client`).
Each file follows the existing pattern: `router = APIRouter()` at module level, endpoints
decorated with `@router.get/post/patch/delete(...)`.

Delete `backend/routers/admin.py` once every section has a new home and nothing still imports
from it.

### Step 2 — Rewire `backend/main.py`

Replace:
```python
from routers import admin as admin_router
...
app.include_router(admin_router.router)
```
with one import + `include_router()` call per new module (ten pairs), grouped together where
the single admin import currently sits.

### Step 3 — Update the two test files

Change each `from routers.admin import X, Y` to import from whichever new module now owns
`X`/`Y` (a single test occasionally imports names that now live in different modules — split
into multiple import lines as needed). Update
`test_issue_81_season_lifecycle.py`'s `_stub_backup` fixture:
```python
# Before
import routers.admin as admin_module
monkeypatch.setattr(admin_module, "backup_sqlite_db", lambda: "/tmp/fake-backup.db")

# After
import routers.admin_season as admin_season_module
monkeypatch.setattr(admin_season_module, "backup_sqlite_db", lambda: "/tmp/fake-backup.db")
```

### Step 4 — Verify, then run `/agent-steward`

Run the full test suite and the import check (see Verification). Once both pass, run
`/agent-steward` per the issue's explicit instruction, and accept its proposed corrections to
`security-reviewer.md` and `systems-architect.md`.

---

## Verification

- `cd backend && python -m pytest tests/ -v` — same 448 passed / 10 skipped as before the split
- `cd backend && python -c "import main"` — no import errors
- `grep -rn "from routers.admin import\|routers\.admin\b" backend/` — no remaining references
  to the old module outside of expected leftovers (there should be none once Step 3 is done)
- Manual smoke test: hit one endpoint from each new module (e.g. `GET /admin/weeks`,
  `GET /admin/players`, `POST /admin/season/end` guard check) against the running dev
  container to confirm routes still resolve after the `main.py` rewire
- `/agent-steward` run after implementation reports `0 stale/broken` for
  `security-reviewer` and `systems-architect`
