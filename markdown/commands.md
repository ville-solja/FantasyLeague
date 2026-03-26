# Commands

## Docker
docker compose down -v
docker compose up --build

## Ingestion
curl -X POST http://localhost:8000/ingest/league/19369

## Access DB
docker exec -it dota-kanaliiga-fantasy-db-1 psql -U dota -d fantasy

### DB queries
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