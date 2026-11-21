# Plan: Test Database Snapshots

## Context
A manual test often has to be repeated from the same starting point, for example to retry a lock or a substitution after a fix. This issue lets an admin on a Demo Mode server save the database under a name and restore it later, while the app keeps running.

It is split from the umbrella plan `plan-issue-114-testing-tooling.md`, with these details settled against the current code:

- **Restore uses SQLite's backup API into the live file.** Then `engine.dispose()` drops pooled connections, `migrate.run_migrations(engine)` brings an older snapshot up to the current schema, `card_points.rebuild_all` rebuilds stored card points, and `season_reset.bust_caches()` (#133) empties the in-memory caches.
- **Staying logged in.** Before restoring, the restoring admin's `user_sessions` rows are read. After restoring, every `user_sessions` row is deleted and those rows are written back, so every other session ends. Restore refuses with 409 when the snapshot has no admin user with the caller's id, since the caller would otherwise be locked out.
- **Paths.** A name with `/` in the URL wouldn't reach the route at all (404), but the issue wants 422. The restore route therefore takes `{name:path}` and validates it with `^[A-Za-z0-9-]{1,40}$`. The file path is built from the validated name and checked to resolve inside the snapshot folder.

**Assumptions:**
- The snapshot folder is `data/demo-snapshots/` next to the live database. It is created owner-only (`0o700`) and each file is `0o600`, since snapshots hold password hashes and emails. `.dockerignore` already ignores `data/`, but `.gitignore` lists only specific `data/` files, so add `data/demo-snapshots/`.
- Saving over an existing name gives 409. Deleting snapshots is out of scope (remove the files by hand).
- Only restore needs a recent password re-entry; save and list need admin only.
- The restore audit entry is written after the restore, since the snapshot replaces `audit_logs`.
- Restores run one at a time under a module lock. Background threads may hit a busy database briefly; SQLite's `timeout=10` covers that.

Resolves GitHub issue #147.

## User Stories

### Save and Restore a Test Snapshot
**User story**
As a tester, I want to save the test database and restore it later so that I can repeat a manual test from the same starting point.

**Acceptance criteria**
- `POST /admin/demo/snapshots` with `{"name"}` (letters, digits, hyphen; 1–40 characters) saves a copy of the live database to `data/demo-snapshots/{name}.db` with SQLite's online backup. An existing name gives 409
- `GET /admin/demo/snapshots` lists the saved snapshots with name, size and time, newest first
- `POST /admin/demo/snapshots/{name}/restore` restores one into the live database while the app keeps running, then rebuilds stored card points and empties the caches
- All three are admin and `DEMO_MODE` only, and give 404 otherwise. Restore needs the admin password re-entry from #117 (403 `reauth_required` without it), and the typed phrase `RESTORE SNAPSHOT` (400 `confirmation_required` without it, the #150 rule as for `LOAD SCENARIO`)
- Names never become paths outside `data/demo-snapshots/`. `../x`, `a/b` and any other invalid name get 422
- The restoring admin stays logged in and every other session ends. A snapshot without that admin account gives 409 and restores nothing
- The admin Demo panel lists the snapshots with Save and Restore, and restore has an in-page confirmation. It never uses `confirm()`

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/demo_snapshots.py` *(new)* | `NAME_RE`, `folder()`, `path_for(name)`, `save(name)`, `list_all()`, `restore(name, keep_user_id)` |
| `backend/routers/admin_demo.py` | The three endpoints |
| `backend/database.py` | Reuse `_sqlite_db_path()`; no change expected |
| `.gitignore` | `data/demo-snapshots/` |
| `frontend/app-admin-demo.js` | Snapshots section: list, name input with Save, Restore buttons with in-page confirmation, re-auth through `adminFetch` |
| `markdown/features/reference/testing-tooling.md`, `demo-mode.md` | Docs |
| `backend/tests/test_issue_147_demo_snapshots.py` | Tests on a temporary file database (the in-memory test database can't be backed up to a file and restored) |

### Step 1 — Helpers
```python
NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,40}$")

def path_for(name: str) -> Path:
    if not NAME_RE.fullmatch(name):
        raise ValueError("invalid snapshot name")
    p = (folder() / f"{name}.db").resolve()
    if p.parent != folder().resolve():
        raise ValueError("invalid snapshot name")
    return p
```
`save` writes with `sqlite3.Connection.backup`, creating the file `0o600` first, as `database.backup_sqlite_db` does. `list_all` returns `{name, size_bytes, saved_at}`.

### Step 2 — Restore
1. Under a lock, read the caller's `user_sessions` rows (all columns).
2. Open the snapshot read-only and check `users` has the caller's id with `is_admin=1`; otherwise 409.
3. `snapshot_conn.backup(live_conn)` with a fresh `sqlite3` connection to the live file.
4. `engine.dispose()`, `run_migrations(engine)`, then in a new session: delete all `user_sessions`, re-insert the saved rows, `card_points.rebuild_all`, audit `demo_snapshot_restored name=…`, commit.
5. `season_reset.bust_caches()`.

### Step 3 — Endpoints
```python
class SnapshotBody(BaseModel):
    name: str = Field(..., pattern=r"^[A-Za-z0-9-]{1,40}$")

@router.get("/admin/demo/snapshots")
@router.post("/admin/demo/snapshots")
@router.post("/admin/demo/snapshots/{name:path}/restore",
             dependencies=[Depends(_require_demo_mode), Depends(require_recent_reauth)])
```
Each has `_require_demo_mode` as its first dependency and calls it imperatively too. An invalid name on restore gives 422, and a missing file gives 404. Save writes a `demo_snapshot_saved` audit entry.

### Step 4 — UI and docs
Under the Demo panel's clock section, add a Snapshots list (name, size, time, Restore), a name input with Save, and an in-page confirmation for Restore ("Replaces all data with snapshot <name>; everyone else is logged out"). After a restore, reload the page data. Document it in `testing-tooling.md`.

## Verification
- `cd backend && python -m pytest tests/test_issue_147_demo_snapshots.py tests/test_issue_83_demo_mode.py -q`, then the full suite.
- Save, change data (draw a card, edit a roster), restore, and the season leaderboard, the user's cards and tokens equal the values before the change.
- `../x`, `a/b`, `..%2Fx`, a 41-character name and an empty name get 422, and no file outside the folder is touched.
- Restore without a recent re-auth gives 403 `reauth_required`. With `DEMO_MODE` off, all three give 404 for an admin.
- After a restore, the caller's session still works and another user's session gets 401.
- A snapshot whose users lack the caller as admin gives 409 and leaves the live data unchanged.
- The snapshot files and folder have modes `0600` and `0700`.
