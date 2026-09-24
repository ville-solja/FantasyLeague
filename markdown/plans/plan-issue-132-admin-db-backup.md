# Plan: Admin DB Backup

## Context
Admins want to back up the database from the admin panel before pushing a new version mid-season, without shell access to the host. The backup machinery already exists in `backend/database.py`:

- `backup_sqlite_db()` takes a transactionally consistent online backup with the sqlite3 backup API. It writes `data/fantasy.db.backup-YYYYMMDD-HHmmss` next to the live database.
- A background loop in `backend/main.py` calls it every `DB_BACKUP_INTERVAL_HOURS`. `cleanup_old_backups()` then deletes backups older than `DB_BACKUP_RETENTION_DAYS`.
- `POST /admin/season/reset` calls it before deleting anything.
- `scripts/backup-db.sh` is the manual pre-deploy step, but it needs a shell on the host.

What's missing is an admin-facing trigger, a view of which backups exist, and a way to copy one off the host. Taking a backup copy off the host matters because every backup sits on the same disk and bind mount as the live database. A deploy that damages `data/` would take the backups with it.

This plan adds three admin-only endpoints and a "Database Backups" panel in the admin Settings tab.

**Assumptions:**
- Manual backups use the same file naming as automatic ones. They are therefore covered by the existing `.gitignore` entry `data/*.backup-*`, and pruned by the same retention rule. An admin who needs a backup kept longer than `DB_BACKUP_RETENTION_DAYS` downloads it.
- **Restore is out of scope.** Restoring means stopping the app and replacing the database file. That stays a documented operator procedure, not an endpoint.
- **Downloads are sensitive.** A backup contains every user's email and password hash, so each download is admin-only and written to the audit log.

Resolves GitHub issue #132.

## User Stories

### Create a Backup On Demand
**User story**
As an admin, I want to create a database backup from the admin panel so that I can safely deploy a new version mid-season without shell access to the server.

**Acceptance criteria**
- The admin Settings tab has a "Database Backups" panel with a "Create backup now" button
- Clicking it calls `POST /admin/backups`, which uses `backup_sqlite_db()` and returns the new backup's filename, size in bytes, and creation time
- The new file follows the existing naming pattern `{db}.backup-YYYYMMDD-HHmmss` in the same directory as the live database
- The action is written to the audit log as `admin_db_backup` with the filename
- A request within 60 seconds of the newest existing backup file returns 429 and creates no file
- When the database is not a local SQLite file, the endpoint returns 409 with a clear message and creates no file
- Non-admin users get 403, and logged-out users get 401

### See Which Backups Exist
**User story**
As an admin, I want to see a list of existing backups so that I can confirm a recent backup exists before deploying.

**Acceptance criteria**
- `GET /admin/backups` returns every file matching `{db}.backup-*` in the database directory, newest first, with filename, size in bytes, and modification time
- The response never includes the live database file or its `-wal`/`-shm` files
- The panel shows the list as a table with filename, created time in local time, and a human-readable size, plus a Refresh button
- The panel shows the retention period from `DB_BACKUP_RETENTION_DAYS`, so admins know when backups are deleted automatically
- An empty list shows "No backups yet"

### Download a Backup
**User story**
As an admin, I want to download a backup file so that I can keep a copy off the server in case the server's disk is lost.

**Acceptance criteria**
- Each row in the backup table has a Download link that calls `GET /admin/backups/{filename}`
- The response is the file as an attachment, with `Content-Disposition` set to the backup's filename
- The filename must exactly match a file returned by the backup listing. Any other value, including path traversal attempts such as `../fantasy.db` or the live database's own name, returns 404
- Each download is written to the audit log as `admin_db_backup_download` with the filename
- Non-admin users get 403, and logged-out users get 401

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/database.py` | Add `list_sqlite_backups()` returning backup file paths newest first; reuse the path logic already in `cleanup_old_backups()` |
| `backend/routers/admin_backups.py` | New router: `POST /admin/backups`, `GET /admin/backups`, `GET /admin/backups/{filename}` |
| `backend/main.py` | Include the new router next to the other admin routers |
| `frontend/index.html` | "Database Backups" panel in the admin Settings tab, next to Season Lifecycle |
| `frontend/` admin JS | `loadBackups()`, `createBackup()`, rendering of the backup table with Download links |
| `backend/tests/test_issue_132_admin_db_backup.py` | Tests for every acceptance criterion, using a temporary SQLite file |
| `markdown/features/reference/db-sustainability.md` | Mention the admin panel as an alternative to `scripts/backup-db.sh` |
| `markdown/features/reference/admin-router-organization.md` | Add `admin_backups.py` to the module map |
| `markdown/ui_description/admin.md` | Describe the Database Backups panel |

No model changes and no migration. No new env vars; the panel reads the existing `DB_BACKUP_RETENTION_DAYS`.

### Step 1 — Backup listing helper
In `backend/database.py`, factor the directory-and-glob logic out of `cleanup_old_backups()` into a shared helper. Add a function that lists backups newest first:

```python
def list_sqlite_backups() -> list[Path]:
    """Backup files next to the live SQLite DB, newest first. Empty for non-SQLite URLs."""
    db_path = _sqlite_db_path()          # None for non-SQLite DATABASE_URL
    if db_path is None or not db_path.parent.is_dir():
        return []
    files = [f for f in db_path.parent.glob(f"{db_path.name}.backup-*") if f.is_file()]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
```

`cleanup_old_backups()` switches to the same helper so both share one definition of what counts as a backup.

### Step 2 — Admin router
Create `backend/routers/admin_backups.py` following the `admin_season.py` pattern, with `require_admin` and `_audit`:

- `POST /admin/backups`:
  - Return 409 if `backup_sqlite_db()` can't apply because the database isn't local SQLite.
  - Return 429 if the newest backup's modification time is under 60 seconds ago. This also prevents two backups in the same second from overwriting each other, since the filename only has one-second resolution.
  - Otherwise create the backup, write the audit entry, commit, and return `{filename, size_bytes, created_at}`.
- `GET /admin/backups` returns `{retention_days, backups: [{filename, size_bytes, created_at}]}`.
- `GET /admin/backups/{filename}`:
  - Look up the filename in `list_sqlite_backups()` by exact basename match. Never join the filename onto a path, which rules out path traversal.
  - Return 404 if it isn't there.
  - Otherwise write the audit entry, commit, and return a `FileResponse` with `filename=` set, so the browser saves it as an attachment.

Read `retention_days` from the same env var `main.py` uses. Don't duplicate the default in a way that could drift. Import the value, or move both reads into a single place.

### Step 3 — Admin panel
Add a "Database Backups" panel to the admin Settings tab, next to Season Lifecycle:

- A "Create backup now" button, disabled while its request is in flight. It shows the new filename, or the error from the response, in the panel's status line.
- A Refresh button and a table with Filename, Created and Size columns, and a Download link on each row.
- A line of explanatory text: "Backups are stored on the server and deleted automatically after N days. Download a copy before deploying if you need to keep it."

The Download link is a plain `<a href="/admin/backups/{filename}">`. The session cookie authenticates it, the same as every other admin call. Escape every filename rendered into the table with the existing HTML-escape helper. Load the list when the Settings tab opens.

### Step 4 — Documentation
- In `db-sustainability.md`, add an "Admin panel" subsection. It says the panel is the no-shell alternative to `scripts/backup-db.sh`, and covers the 60-second cooldown and that retention also applies to manual backups.
- Add a short restore procedure: stop the container, copy the backup over `data/fantasy.db`, delete any `-wal` and `-shm` files, and start again.
- Update the admin router module map and `ui_description/admin.md`.
- Fill in the feature doc stub.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_132_admin_db_backup.py -v` passes, using a temporary database path so no real backup files are written.
- Full suite passes. Bump the suite-size tripwire in `test_issue_85_split_admin_router.py` by the number of new tests.
- As admin, click "Create backup now". A new row appears. Clicking again straight away shows the 429 cooldown message.
- Download the backup and open it with `sqlite3 downloaded.db "PRAGMA integrity_check; SELECT COUNT(*) FROM users;"`. It reports `ok` and the expected user count.
- Request `/admin/backups/..%2Ffantasy.db` and `/admin/backups/fantasy.db`. Both return 404.
- As a non-admin, all three endpoints return 403. Logged out, they return 401.
- The audit log shows `admin_db_backup` and `admin_db_backup_download` entries with filenames.
- `git status` after creating a backup locally shows no new untracked file under `data/`.
- No migration or seed step is needed.
