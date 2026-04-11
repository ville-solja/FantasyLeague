# Commands

## Docker

### Production (server) — uses image from GHCR, no source code needed
```
docker compose up -d
docker compose down
```

### Local development — builds image locally, mounts source for hot reload
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

## Reset database
Stops the container, deletes the database file, and restarts from scratch (re-runs migrations and seed on next startup):
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml down 
rm -f data/fantasy.db 
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## Ingestion
```
curl -X POST http://localhost:8000/ingest/league/19369
```

Each ingest also refreshes **Dotabuff league team logos** (default Kanaliiga overview URLs): new PNGs are downloaded only when missing under `assets/.../dotabuff_league_logos/` (or `Assets/...` in Docker). Configure or disable with `DOTABUFF_LEAGUE_LOGO_PAGES` in `.env`.

### Clear cached Dotabuff league logos
Force re-download on next ingest (e.g. after a team rename on Dotabuff):

**Repo root (paths match your card template folder — often `assets/` locally, `Assets/` in the Linux container):**
```
rm -f assets/dotabuff_league_logos/*.png
```

**Docker (production image uses `/app/Assets`):**
```
docker compose exec backend sh -c 'rm -f /app/Assets/dotabuff_league_logos/*.png'
```

## Access DB (SQLite)
```
docker compose exec backend sqlite3 /app/data/fantasy.db
```

### DB queries
```sql
SELECT COUNT(*) FROM matches;
SELECT * FROM matches LIMIT 5;

SELECT id, name FROM players LIMIT 10;

SELECT match_id, COUNT(*)
FROM player_match_stats
GROUP BY match_id
ORDER BY match_id
LIMIT 10;

SELECT pms.*
FROM player_match_stats pms
LEFT JOIN matches m ON pms.match_id = m.match_id
WHERE m.match_id IS NULL;

SELECT pms.*
FROM player_match_stats pms
LEFT JOIN players p ON pms.player_id = p.id
WHERE p.id IS NULL;
```
