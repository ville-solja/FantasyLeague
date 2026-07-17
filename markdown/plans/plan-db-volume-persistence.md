# Plan: DB Volume Persistence

## Context
Both `docker-compose.yml` and `docker-compose.dev.yml` already mount `./data:/app/data`
as a bind mount, so the database persists across container rebuilds in principle. However,
the `data/` directory is not tracked in git — a fresh `git clone` on a new server leaves
it absent. Docker silently creates the directory when the container starts, but does so
owned by root, which can cause write-permission issues when the container user is
non-root and creates a confusing first-deploy experience. The fix is small: add
`data/.gitkeep` so the directory is always present after `git clone`, and document the
persistence strategy explicitly so operators know what to protect and how to reset.
*Resolves GitHub issue #75.*

## User Stories

### Database Survives Container Rebuilds
**User story**
As an operator, I want the database to survive container rebuilds and host restarts so
that player data and league progress are never accidentally lost when deploying a new
version.

**Acceptance criteria**
- The SQLite database file persists at `./data/fantasy.db` on the host across
  `docker compose down && docker compose up --build`
- The `data/` directory exists in the repository (tracked via `.gitkeep`) so a fresh
  `git clone` followed by `docker compose up` works without any manual `mkdir` steps
- The bind-mount strategy and its rationale are documented in
  `markdown/features/reference/db-volume-persistence.md`
- The existing versioned migration system (`schema_migrations` table in `migrate.py`)
  ensures schema changes apply once and are skipped on subsequent starts, whether the
  database is new or has years of existing data

### Consistent Dev and Production Persistence
**User story**
As a developer, I want the local development environment to use the same persistence
strategy as production so that I develop against a real database without losing data
between sessions.

**Acceptance criteria**
- `docker-compose.dev.yml` mounts `./data:/app/data` (already in place — no code change)
- `docker compose ... down --volumes` does NOT delete `./data/` on the host (bind mounts
  are never removed by `--volumes`; this should be documented to prevent confusion)
- The database reset procedure in `commands.md` explicitly removes only the db files
  (`rm -f data/fantasy.db*`), not the `data/` directory itself

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `data/.gitkeep` | New empty file — ensures the directory is tracked in git |
| `markdown/features/reference/db-volume-persistence.md` | Feature doc stub (created by product-planner) |

No changes to `docker-compose.yml`, `docker-compose.dev.yml`, or any backend code — the
bind mount is already configured correctly in both files.

### Step 1 — Add `data/.gitkeep`

Create an empty file at `data/.gitkeep`. Verify `.gitignore` already has entries for
`data/fantasy.db`, `data/fantasy.db-shm`, and `data/fantasy.db-wal` (it does) but does
NOT ignore `data/.gitkeep` (it does not — the gitignore entries are file-specific, not a
directory wildcard). Commit the `.gitkeep` file.

### Step 2 — Fill in the feature doc

Update `markdown/features/reference/db-volume-persistence.md` with the completed
description, covering:
- The bind-mount approach and why it is preferred over a named Docker volume for this
  project (easier host-side backup, direct SQLite access for debugging)
- How the versioned migration system ensures schema safety when the database already
  exists
- How to reset the database during development (rm the files, not the directory)
- Why `--volumes` in `docker compose down` is safe and will not delete data

---

## Verification
- `git clone` the repository to a temporary directory; verify `data/` exists and is
  empty (contains only `.gitkeep`)
- Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`; ingest
  some data; run `docker compose ... down`; restart — verify data is still present
- Run `docker compose ... down --volumes` — verify `data/fantasy.db` still exists
- Run `rm -f data/fantasy.db data/fantasy.db-shm data/fantasy.db-wal` then restart —
  verify a fresh database is created and all migrations run from scratch
