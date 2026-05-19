# Deployment & Operations

## DB Sustainability

### Apply Schema Changes Without Losing Data
**User story**
As a developer, I want each schema migration to be recorded in the database so that
deploying a new version never re-runs a migration that has already been applied.

**Acceptance criteria**
- A `schema_migrations` table exists after first startup, with columns `id` (string) and `applied_at` (Unix timestamp)
- Each migration has a unique string ID (e.g. `"001_add_is_mvp"`)
- Migrations already recorded in `schema_migrations` are skipped on subsequent startups
- A migration not yet in `schema_migrations` is applied and then recorded atomically
- The existing column-addition migrations in `migrate.py` are preserved as registered steps

### Add a New Migration Without Breaking Existing Installs
**User story**
As a developer, I want to add a new migration step to `migrate.py` and have it run
exactly once on the next deploy, so that I can safely evolve the schema without manual
intervention on the server.

**Acceptance criteria**
- Adding a new migration function with a new ID causes it to run on next startup
- The migration is skipped on all subsequent startups
- If a migration raises an exception, the startup error is logged clearly and the `schema_migrations` row is not written (the migration will be retried next startup)

### Pre-Deploy Backup
**User story**
As an operator, I want a documented backup procedure so that I can recover data if a
migration goes wrong.

**Acceptance criteria**
- `scripts/backup-db.sh` creates a timestamped copy of `data/fantasy.db`
- The script is referenced in `README.md` under the deployment section
- The backup takes less than 1 second on a typical database size
