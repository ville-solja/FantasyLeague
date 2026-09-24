# DB Sustainability

Versioned schema migration system that records each applied migration in a
`schema_migrations` table, ensuring schema changes run exactly once and production
data (users, rosters, cards) is never lost during a deploy.

---

## Overview

Each migration is a Python function paired with a unique string ID. On startup,
`run_migrations()` checks `schema_migrations` — if the ID is present the function is
skipped; if absent it runs and is recorded atomically. This replaces the ad-hoc
`PRAGMA table_info` column-existence checks with a clean, auditable history.

New SQLAlchemy models (new tables) continue to be created by `Base.metadata.create_all()`
on startup. New columns on existing tables must be added as a numbered migration.

---

## Migration table

`schema_migrations` — one row per applied migration:

| Column | Type | Description |
|---|---|---|
| `id` | TEXT PK | Human-readable migration ID, e.g. `"008_card_modifiers_constraint"` |
| `applied_at` | INTEGER | Unix timestamp of when the migration ran |

---

## Adding a migration

1. Write a function `_mNNN_description(conn)` in `backend/migrate.py`
2. Append `("NNN_description", _mNNN_description)` to the `MIGRATIONS` list
3. On next startup the migration runs once and is recorded

---

## Backup script

`scripts/backup-db.sh` creates a timestamped copy of the database file:

```bash
bash scripts/backup-db.sh          # → data/fantasy.db.backup-YYYYMMDD-HHmmss
bash scripts/backup-db.sh /path/to/other.db   # custom path
```

Run before every deploy.

**Custom-path caveat:** `.gitignore`'s `data/*.backup-*` entry (see
`reference/db-backup-leak-fix.md`) only covers backups written at the default path,
under `data/`. Running
`scripts/backup-db.sh /custom/path` writes the timestamped copy next to
`/custom/path` instead — outside the gitignored `data/` directory — so a backup taken
this way is **not** protected by that pattern and could be committed by an unrelated
`git add -A` if the custom path happens to live inside the repo. Prefer the default
(no-argument) invocation unless there's a specific reason to write elsewhere.

This is separate from the automatic in-app backup that `backup_sqlite_db()` (in
`backend/database.py`, using the sqlite3 online backup API rather than this script's plain `cp`) takes immediately before
`POST /admin/season/reset` deletes any data — see `reference/season-lifecycle.md`. That backup
runs unconditionally on every reset; `scripts/backup-db.sh` is the manual pre-deploy step.

## Automatic scheduled backups

A background thread (`_backup_loop` in `backend/main.py`, started unconditionally at startup
alongside week maintenance) calls `backup_sqlite_db()` on a timer and prunes old backup files with
`cleanup_old_backups()` (both in `backend/database.py`). This is the only unattended safety net for
the bind-mounted `data/fantasy.db` — `scripts/backup-db.sh` and the season-reset backup are both
one-off/manual.

| Variable | Default | Description |
|---|---|---|
| `DB_BACKUP_INTERVAL_HOURS` | `24` | Hours between automatic backups |
| `DB_BACKUP_RETENTION_DAYS` | `14` | Age (by file mtime) at which any backup file, automatic or manual, is deleted |

Backups land next to the live DB as `data/fantasy.db.backup-YYYYMMDD-HHmmss`, same naming
convention as the manual script, so both are pruned/restorable the same way. Retention only
touches files matching that pattern — it never deletes the live database.

## Admin panel

The admin Settings tab's **Database Backups** panel is the no-shell alternative to
`scripts/backup-db.sh` — use it before a mid-season deploy when you don't have a shell on the host.
It calls the same `backup_sqlite_db()` and writes the same `data/fantasy.db.backup-YYYYMMDD-HHmmss`
files, so manual panel backups are listed alongside scheduled and pre-reset ones.

- **60-second cooldown:** `POST /admin/backups` returns 429 if the newest backup file is under
  60 seconds old. This also prevents two backups in the same second from overwriting each other.
- **Retention applies to manual backups too:** anything matching the backup pattern is pruned after
  `DB_BACKUP_RETENTION_DAYS` (default 14, defined once in `database.backup_retention_days()` and
  read by both the backup loop and the panel). Download a copy to keep it longer, or off the host.

Endpoints and security details are in `reference/admin-db-backup.md`.

## Restoring a backup

Restore is a manual operator procedure, not an endpoint:

1. Stop the container: `docker compose stop backend`
2. Copy the chosen backup over the live file: `cp data/fantasy.db.backup-YYYYMMDD-HHmmss data/fantasy.db`
3. Delete any stale WAL files: `rm -f data/fantasy.db-wal data/fantasy.db-shm`
4. Start again: `docker compose start backend`

Leaving the old `-wal`/`-shm` files in place would let SQLite replay the pre-restore WAL on top of
the restored database.

## Container restart policy

`docker-compose.yml`'s `backend` service sets `restart: unless-stopped`, so the container
restarts automatically after a crash, an OOM kill, or a host/Docker-daemon reboot, rather than
staying down until someone notices and runs `docker compose up` by hand.

---

## CI enforcement

`backend/tests/test_migrate.py::TestSchemaCoverage::test_all_model_columns_present_after_migration`
runs on every PR. It applies `run_migrations()` against a legacy in-memory schema, then calls
`Base.metadata.create_all()`, and asserts every model column is present. Any model edit that adds
a column to an existing table without a corresponding migration will fail CI.

**Rule (also in CLAUDE.md):** when adding a column to an existing table in `backend/models.py`,
always add a `PRAGMA table_info`-guarded `ALTER TABLE … ADD COLUMN` block to `run_migrations()`
in the same commit.
