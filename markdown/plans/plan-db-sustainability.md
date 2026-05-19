# Plan: DB Sustainability

## Context
The current `migrate.py` uses ad-hoc column-existence checks (`PRAGMA table_info`) to
apply changes idempotently, but there is no formal record of which migrations have run.
This makes it fragile to add complex, multi-step migrations (e.g. data backfills, table
renames) without risking double-execution or data loss on the production database.
New tables added since the last deploy are handled silently by `Base.metadata.create_all()`
but there is no safety net if that call fails. The goal is a lightweight versioned
migration registry — a `schema_migrations` table that records each applied migration by
ID — so future schema changes can be implemented as discrete, never-repeated steps rather
than ad-hoc PRAGMA checks. *Resolves GitHub issue #31.*

## User Stories

### Apply Schema Changes Without Losing Data
**User story**
As a developer, I want each schema migration to be recorded in the database so that
deploying a new version never re-runs a migration that has already been applied.

**Acceptance criteria**
- A `schema_migrations` table exists after first startup, with columns `id` (string) and
  `applied_at` (Unix timestamp)
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
- If a migration raises an exception, the startup error is logged clearly and the
  `schema_migrations` row is not written (the migration will be retried next startup)

### Pre-Deploy Backup Reminder
**User story**
As an operator, I want a documented backup procedure so that I can recover data if a
migration goes wrong.

**Acceptance criteria**
- `scripts/backup-db.sh` creates a timestamped copy of `data/fantasy.db`
- The script is referenced in `README.md` under the deployment section
- The backup takes less than 1 second on a typical database size

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/migrate.py` | Add `schema_migrations` table + migration registry pattern |
| `scripts/backup-db.sh` | New: one-line backup script |
| `README.md` | Document backup step in deployment section |

### Step 1 — schema_migrations table and registry

Replace the monolithic `run_migrations()` body with a registry pattern. Add at the top
of `migrate.py`:

```python
def _ensure_migrations_table(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id         TEXT PRIMARY KEY,
            applied_at INTEGER NOT NULL
        )
    """))
    conn.commit()

def _applied(conn, migration_id: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM schema_migrations WHERE id = :id"),
        {"id": migration_id}
    ).first()
    return row is not None

def _record(conn, migration_id: str):
    conn.execute(
        text("INSERT INTO schema_migrations (id, applied_at) VALUES (:id, :ts)"),
        {"id": migration_id, "ts": int(__import__("time").time())}
    )
    conn.commit()
```

Then wrap each existing migration block in a guard:

```python
def _m001_players_avatar_url(conn):
    cols = [r[1] for r in conn.execute(text("PRAGMA table_info(players)")).fetchall()]
    if "avatar_url" not in cols:
        conn.execute(text("ALTER TABLE players ADD COLUMN avatar_url TEXT"))
        conn.commit()

MIGRATIONS = [
    ("001_players_avatar_url",       _m001_players_avatar_url),
    ("002_matches_columns",          _m002_matches_columns),
    # ... one entry per existing migration block
]

def run_migrations(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=30000"))
        conn.commit()
        _ensure_migrations_table(conn)
        for migration_id, fn in MIGRATIONS:
            if _applied(conn, migration_id):
                continue
            try:
                fn(conn)
                _record(conn, migration_id)
                logger.info("Migration applied: %s", migration_id)
            except Exception:
                logger.exception("Migration FAILED: %s — startup will continue but "
                                 "this migration will be retried next start", migration_id)
```

### Step 2 — Wrap all existing migrations as numbered functions

Convert each existing `if "column" not in cols:` block into a discrete named function:
- `001_players_avatar_url`
- `002_matches_columns`
- `003_users_columns`
- `004_pms_hero_id`
- `005_pms_expanded_stats`
- `006_cards_generation`
- `007_teams_logo_url`
- `008_card_modifiers_constraint`
- `009_indexes`
- `010_weeks_epoch0_reset`

Keep the PRAGMA checks inside each function so existing installs that already have the
columns skip the ALTER TABLE safely — the column check is now the inner guard, and the
`schema_migrations` row is the outer guard for new installs going forward.

### Step 3 — New tables via create_all + migrations

`Base.metadata.create_all(engine)` already handles tables that don't exist yet
(e.g. `notifications`, `token_grant_events`). No change needed — new models continue
to use this path. Document this pattern: new tables → add model + `create_all()`.
New columns on existing tables → add a numbered migration function.

### Step 4 — Backup script

Create `scripts/backup-db.sh`:

```bash
#!/bin/bash
set -e
DB="${1:-data/fantasy.db}"
DEST="${DB}.backup-$(date +%Y%m%d-%H%M%S)"
cp "$DB" "$DEST"
echo "Backup written to $DEST"
```

Add to `README.md` under a Deployment section:

```markdown
## Deployment

Before every deploy:
```bash
bash scripts/backup-db.sh          # creates data/fantasy.db.backup-YYYYMMDD-HHmmss
docker compose up --build -d
```

---

## Verification
- Fresh `sqlite:///:memory:` startup: `schema_migrations` table is created, all 10
  migrations run and are recorded
- Second startup with same DB: all migrations are skipped (no `ALTER TABLE` calls logged)
- Add a new `011_test` migration with a no-op body; verify it runs once, then is skipped
- Simulate a migration that raises: verify the `schema_migrations` row is absent and the
  migration is retried on next startup
- Run `bash scripts/backup-db.sh data/fantasy.db` — timestamped copy appears in same dir
- Run `python -m pytest tests/ -v` — existing migration tests still pass
