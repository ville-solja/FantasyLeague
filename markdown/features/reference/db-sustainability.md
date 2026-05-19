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

---

## CI enforcement

`backend/tests/test_migrate.py::TestSchemaCoverage::test_all_model_columns_present_after_migration`
runs on every PR. It applies `run_migrations()` against a legacy in-memory schema, then calls
`Base.metadata.create_all()`, and asserts every model column is present. Any model edit that adds
a column to an existing table without a corresponding migration will fail CI.

**Rule (also in CLAUDE.md):** when adding a column to an existing table in `backend/models.py`,
always add a `PRAGMA table_info`-guarded `ALTER TABLE … ADD COLUMN` block to `run_migrations()`
in the same commit.
