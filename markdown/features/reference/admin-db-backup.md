# Admin DB Backup

Lets admins create, list and download SQLite database backups from the admin Settings tab. Admins use it before deploying a new version mid-season, without needing shell access to the server.

---

## How it fits the existing backups

Every backup is written next to the live database as `fantasy.db.backup-YYYYMMDD-HHmmss`. Scheduled, pre-reset and admin-panel backups use `backup_sqlite_db()` in `backend/database.py`, which uses the sqlite3 online backup API. `scripts/backup-db.sh` makes a plain file copy with the same name pattern. A backup can come from:

- scheduled, from the background backup loop
- taken before a season reset
- created manually through `scripts/backup-db.sh`
- created from this admin panel

Because they share the naming pattern:

- all of them appear in the admin list
- `.gitignore`'s `data/*.backup-*` entry covers them
- all of them are deleted once older than `DB_BACKUP_RETENTION_DAYS`. Pruning runs after each successful scheduled backup, so a file can outlive the limit by up to `DB_BACKUP_INTERVAL_HOURS`

Backups live on the same disk as the database. Download a copy to keep one off the server.

## Endpoints

### `POST /admin/backups`
Admin only. Creates a backup now and returns `{filename, size_bytes, created_at}`. Returns 429 if the newest backup is less than 60 seconds old, and 409 if the database is not a local SQLite file. The audit log records it as `admin_db_backup`.

### `GET /admin/backups`
Admin only. Returns `{retention_days, backups: [{filename, size_bytes, created_at}]}`, newest first.

### `GET /admin/backups/{filename}`
Admin only. Downloads one backup as an attachment. The filename must exactly match an entry in the listing, otherwise the response is 404. The audit log records it as `admin_db_backup_download`. The file contains every user's email and password hash, so treat downloaded copies as sensitive.

## Implementation

- `backend/routers/admin_backups.py` — the three endpoints, all `Depends(require_admin)`. The 60-second cooldown is `BACKUP_COOLDOWN_SECONDS`.
- `backend/database.py`:
  - `list_sqlite_backups()` returns backup paths next to the live DB, newest first by mtime, or `[]` for a non-SQLite `DATABASE_URL`. `cleanup_old_backups()` uses the same helper, so listing and pruning share one definition of what counts as a backup.
  - `backup_retention_days()` reads `DB_BACKUP_RETENTION_DAYS` (default `DEFAULT_BACKUP_RETENTION_DAYS = 14`). `main.py`'s backup loop and `GET /admin/backups` both call it.
- Download safety: the requested filename is compared against the basenames returned by `list_sqlite_backups()`; the matched `Path` from the listing is served. The user-supplied value is never joined onto a directory, so `../fantasy.db`, the live DB name, and its `-wal`/`-shm` files all 404. Responses carry `Cache-Control: no-store`.
- `created_at` is the file's mtime as a Unix timestamp (seconds).
- Frontend: `frontend/app-admin-backups.js` (`loadBackups()`, `createBackup()`), panel markup in the Settings admin sub-tab of `frontend/index.html`. Filenames are escaped with `_escHtml()`. See `markdown/ui_description/admin.md`.

## Configuration

No new variables. The panel shows the existing retention setting.

| Variable | Default | Description |
|---|---|---|
| `DB_BACKUP_RETENTION_DAYS` | `14` | Age after which any backup, manual or automatic, is deleted |

## Restore

Restore is a manual operator step, not an endpoint. Stop the app, copy the backup over `data/fantasy.db`, delete any `fantasy.db-wal` and `fantasy.db-shm` files, and start the app again. Step-by-step commands are in `reference/db-sustainability.md`.

---

*Covered by `backend/tests/test_issue_132_admin_db_backup.py`.*
