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

Match data is ingested automatically in a background polling loop every 15 minutes (configurable via `INGEST_POLL_INTERVAL`). Manual ingest is available for admins when an immediate refresh is needed:

```
curl -X POST http://localhost:8000/ingest/league/19369
```

Each ingest also:
- Runs player profile enrichment (names, avatars from OpenDota)
- Seeds new player cards into the unowned pool
- Refreshes **Dotabuff league team logos** (new PNGs downloaded only when missing under `assets/.../dotabuff_league_logos/`)

Configure which leagues are auto-ingested via `AUTO_INGEST_LEAGUES` (comma-separated OpenDota league IDs, default: `19368,19369`).

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

## Toornament sync

Push current series results to toornament.com manually (also runs automatically after each poll cycle):
```
curl -X POST http://localhost:8000/admin/sync-toornament \
  -H "Cookie: session=<admin-session>"
```

Returns `{"pushed": N, "skipped": M, "errors": [...]}`.

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

-- Check toornament sync log
SELECT * FROM toornament_sync_log ORDER BY pushed_at DESC;

-- Check week lock status
SELECT label, is_locked, datetime(start_time, 'unixepoch') as start,
       datetime(end_time, 'unixepoch') as end FROM weeks;
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_REPOSITORY` | *(required for prod compose)* | `owner/repo` used by `docker-compose.yml` to resolve the GHCR image (`ghcr.io/${GITHUB_REPOSITORY}:...`) |
| `AUTO_INGEST_LEAGUES` | `19368,19369` | Comma-separated OpenDota league IDs to poll |
| `INGEST_POLL_INTERVAL` | `900` | Seconds between ingest + toornament sync cycles (off-season) |
| `INGEST_LIVE_POLL_INTERVAL` | `120` | Seconds between ingest cycles when an active week is running |
| `WEEK_CHECK_INTERVAL` | `300` | Seconds between week lock maintenance checks |
| `SEASON_LOCK_START` | `2026-03-08` | First Sunday lock date (ISO format) |
| `SCHEDULE_SHEET_URL` | *(Kanaliiga sheet)* | Google Sheets CSV export URL for the match schedule |
| `OPENDOTA_API_KEY` | *(empty)* | Optional API key to raise OpenDota rate limits |
| `OPENDOTA_MAX_RPM` | `55` | Max OpenDota requests per rolling 60 s (free tier ~60/min; default leaves headroom) |
| `TOORNAMENT_CLIENT_ID` | *(empty)* | OAuth2 client ID for toornament.com |
| `TOORNAMENT_CLIENT_SECRET` | *(empty)* | OAuth2 client secret for toornament.com |
| `TOORNAMENT_API_KEY` | *(empty)* | `X-Api-Key` header for toornament.com |
| `TOORNAMENT_TOURNAMENT_ID` | *(empty)* | Toornament tournament UUID |
| `DOTABUFF_LEAGUE_LOGO_PAGES` | *(Kanaliiga URLs)* | Dotabuff league overview URLs to scrape team logos from |
| `WEIGHTS_JSON` | *(empty)* | JSON overrides for scoring weights applied at startup |
| `TOKEN_NAME` | `Tokens` | Display name for the token currency |
| `INITIAL_TOKENS` | `5` | Tokens granted to newly registered users |
| `SECRET_KEY` | *(insecure dev default)* | Session signing key — **must be set in production** |
| `DEBUG` | *(unset)* | Set to `true` to bypass `SECRET_KEY` requirement for local dev — **never set in production** |
| `HTTPS_ONLY` | `false` | Set to `true` when behind an HTTPS reverse proxy; enables `Secure` flag on session cookies |
| `SMTP_HOST` | *(empty)* | SMTP host for email (forgot-password). Disabled if unset. |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(empty)* | SMTP username |
| `SMTP_PASSWORD` | *(empty)* | SMTP password |
| `SMTP_FROM` | Falls back to `SMTP_USER`, then `noreply@fantasy` | Sender address in outgoing emails |
| `SMTP_TLS` | `true` | Use STARTTLS; set to `false` for plain SMTP |
| `APP_NAME` | `Kanaliiga Fantasy` | Prefix used in email subject lines |
| `TWITCH_EXTENSION_CLIENT_ID` | *(empty)* | Extension client ID from Twitch dev console |
| `TWITCH_EXTENSION_SECRET` | *(empty)* | Base64-encoded extension secret from Twitch dev console |
| `TWITCH_DROP_MAX` | `20` | Server-side cap on viewers per token drop |
| `TWITCH_LOCAL_DEV` | *(unset)* | Set to `true` to bypass Twitch JWT validation locally — **never set in production** |
| `ROSTER_LIMIT` | `5` | Maximum active cards per user roster |
