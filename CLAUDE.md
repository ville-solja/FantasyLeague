# CLAUDE.md — Developer rules for this repo

## Schema migrations

**Rule:** When adding a column to an existing table in `backend/models.py`, always add a
corresponding numbered migration to `backend/migrate.py` in the same edit session.

New tables created with `Base.metadata.create_all()` do not require a migration entry —
only new columns on **existing** tables do.

The CI test `tests/test_migrate.py::TestSchemaCoverage::test_all_model_columns_present_after_migration`
enforces this. It will fail if a model column has no migration path from the legacy schema.

**How to add a migration:**

1. Add a conditional `ALTER TABLE … ADD COLUMN` block inside `run_migrations()` in
   `backend/migrate.py`, guarded by a `PRAGMA table_info` check (see existing examples).
2. Run `cd backend && python -m pytest tests/test_migrate.py -v` to confirm the test passes.

## Pre-deploy backup

Run `bash scripts/backup-db.sh` before every deploy. See `markdown/features/reference/db-sustainability.md`.
