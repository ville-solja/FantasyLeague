# DB Volume Persistence

The app stores its SQLite database on the **host filesystem** via a Docker bind mount.
The database is never inside the container image, never in the git repository, and never
shared between environments — each host (dev machine, production server) has its own
completely independent database.

---

## What is and is not in git

| Path | In git? | Why |
|---|---|---|
| `data/.gitkeep` | ✓ Yes | Empty placeholder so the directory exists after `git clone` |
| `data/fantasy.db` | ✗ No | Live data — gitignored, environment-specific |
| `data/fantasy.db-shm` | ✗ No | SQLite WAL shared memory — gitignored |
| `data/fantasy.db-wal` | ✗ No | SQLite WAL journal — gitignored |

The git repository contains **no data**. Cloning the repo gives you code and an empty
`data/` directory. The database is created fresh on first startup and accumulates data
only on the host it runs on.

---

## How persistence works when updating the image

This is the key architectural point: **the database lives on the host, not in the image.**

```
Host filesystem                    Container
─────────────────────────────      ──────────────────────────────
./data/fantasy.db  ←──────── bind mount ──────→  /app/data/fantasy.db
                                   │
                              (SQLite reads/writes here,
                               which are actually writes
                               to the host file)
```

When you run `docker compose up --build` or pull a new image:

1. Docker creates a **new container** from the new image — the container's internal
   filesystem is completely fresh.
2. The `./data:/app/data` bind mount is re-attached — the host-side `./data/` directory
   (and the database inside it) is the same file it was before.
3. The app starts, `migrate.py` runs, finds the existing `schema_migrations` table, skips
   already-applied migrations, and applies any new ones.
4. The app continues with all existing data intact.

**Updating the image never touches the database.** The database persists through any
number of image rebuilds, container recreations, `docker compose down`, host reboots, or
`docker system prune` runs (prune removes images and containers, not bind-mounted files).

---

## Environment separation

Because the bind mount uses a relative path (`./data`), the database location is
determined by **where `docker compose` is run from** — which is naturally different per
environment:

| Environment | Host | Database location |
|---|---|---|
| Development | Developer's laptop | `~/projects/kanaliiga-fantasy/data/fantasy.db` |
| Production | Server | `/home/deploy/kanaliiga-fantasy/data/fantasy.db` |
| Tests | CI / pytest | `sqlite:///:memory:` (in-memory, never touches disk) |

Dev and prod databases are completely separate files on completely separate machines.
There is no configuration needed to achieve this separation — it is structural.

---

## Is this good architectural form?

**Yes, for SQLite.** The bind mount pattern is the standard approach for containerised
SQLite applications and has three key properties that suit this project:

**1. Transparency** — the database is a plain file on the host. You can open it directly
with `sqlite3 data/fantasy.db`, copy it with `cp`, or inspect it with any SQLite browser.
Named Docker volumes hide the file behind Docker's volume management layer and require
`docker cp` or volume inspection to access it.

**2. Simple backup** — `bash scripts/backup-db.sh` creates a timestamped copy with a
single `cp`. With a named volume, backup requires a one-off container or `docker run`.

**3. Easy migration to a new host** — copy the `data/` directory, redeploy. No volume
export/import steps needed.

The main trade-off of bind mounts over named volumes is that the path must exist on the
host before the container starts (solved by `data/.gitkeep`), and permissions can be
surprising if the container runs as a non-root user (Docker creates the directory as root
on first mount if it is absent). The `.gitkeep` solves the first; running the container
as root (the default) solves the second.

For PostgreSQL or MySQL, a named volume would be the right choice because those engines
are not single-file and do not benefit from direct host access. For SQLite the bind mount
wins on simplicity every time.

---

## `docker compose down --volumes` is safe

The `--volumes` flag removes **named volumes** declared in the `volumes:` section of
`docker-compose.yml`. The `./data:/app/data` mount is a **bind mount** (host path →
container path), not a named volume. It is never touched by `--volumes`. Your database
will survive `docker compose down --volumes`.

---

## Schema migrations on existing databases

The versioned migration system (`schema_migrations` table, `backend/migrate.py`)
records each applied migration by a unique ID. On every startup:

- **New database**: all migrations run in sequence and are recorded.
- **Existing database**: only migrations whose ID is not yet in `schema_migrations` run.
  Everything else is skipped.

Deploying a new image version that adds a migration will apply it exactly once on first
startup, then skip it forever.

---

## Resetting the database (development)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
rm -f data/fantasy.db data/fantasy.db-shm data/fantasy.db-wal
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

This removes the database files only — not the `data/` directory. The next startup
creates a fresh database and runs all migrations from scratch.

---

## Backup before deploy (production)

```bash
bash scripts/backup-db.sh   # creates data/fantasy.db.backup-YYYYMMDD-HHmmss
docker compose up -d
```

See [DB Sustainability](db-sustainability.md) for the migration registry and backup
script details.
