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

---

## Security Headers

### Security Response Headers
**User story**
As an operator, I want the server to return standard security response headers so that
vulnerability scanners report no missing-header findings and browsers apply protective
policies.

**Acceptance criteria**
- Every response includes `X-Content-Type-Options: nosniff`
- Every response includes `Referrer-Policy: strict-origin-when-cross-origin`
- Every response includes a `Content-Security-Policy` header containing at least
  `frame-ancestors 'self' https://www.twitch.tv https://*.ext-twitch.tv`
- When `HTTPS_ONLY=true`, every response includes
  `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- When `HTTPS_ONLY=false` (default), `Strict-Transport-Security` is not sent
- The headers are added by a middleware layer and do not require changes to individual
  endpoint handlers

### CORS Wildcard Documentation
**User story**
As a security reviewer, I want the intentional `access-control-allow-origin: *`
configuration to be explained in the codebase and documentation so that it is not
misread as an oversight.

**Acceptance criteria**
- The existing inline comment in `main.py` explaining the wildcard is preserved and
  accurate
- `markdown/features/reference/security-headers.md` documents the CORS decision: why
  wildcard is used, why it is safe (`allow_credentials=False` + Twitch JWT auth), and what
  would need to change if the Twitch extension were removed
