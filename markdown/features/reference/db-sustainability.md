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

This is separate from the automatic in-app backup `backup_sqlite_db()` (also in
`backend/database.py`, same online-backup mechanism) takes immediately before
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
| `DB_BACKUP_RETENTION_DAYS` | `14` | Age (by file mtime) at which an automatic backup is deleted |

Backups land next to the live DB as `data/fantasy.db.backup-YYYYMMDD-HHmmss`, same naming
convention as the manual script, so both are pruned/restorable the same way. Retention only
touches files matching that pattern — it never deletes the live database.

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
