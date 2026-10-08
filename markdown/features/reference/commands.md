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

### Check container health status
`GET /health` checks DB connectivity, not just process liveness (see
`reference/container-health-check.md`). The check runs automatically via `backend/Dockerfile`'s
`HEALTHCHECK` instruction (works under any orchestrator) and is also declared explicitly in
`docker-compose.yml`.
```
docker compose ps
docker inspect --format='{{json .State.Health}}' <container-name-or-id>
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
- Creates player and match records (no card generation — cards are created dynamically at draw time)
- Refreshes **Dotabuff league team logos** (new PNGs downloaded only when missing under `assets/.../dotabuff_league_logos/`)

Leagues are ingested only if monitored — add or remove leagues at runtime via the League Management panel (Admin → Settings tab), no env var or restart required. See `reference/monitored-leagues-admin.md`.

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
| `INGEST_POLL_INTERVAL` | `900` | Seconds between ingest + toornament sync cycles (off-season) |
| `INGEST_LIVE_POLL_INTERVAL` | `120` | Seconds between ingest cycles when an active week is running |
| `INGEST_LIVE_MATCH_POLL_INTERVAL` | `30` | Seconds between ingest cycles when a monitored league has a match currently in progress (per `live_matches`, written by the live thread) — takes priority over `INGEST_LIVE_POLL_INTERVAL` |
| `STEAM_API_KEY` | *(empty)* | Steam Web API key for live-game detection (`GetLiveLeagueGames`). Unset: no live checks run and a warning is logged at start-up. See `reference/mvp-selection-delays.md` |
| `LIVE_POLL_INTERVAL` | `60` | Seconds between live-game checks (Steam), in their own thread apart from ingest |
| `WEEK_CHECK_INTERVAL` | `300` | Seconds between week auto-lock maintenance checks (weeks themselves are admin-created, see `reference/season-lifecycle.md`). The same loop deletes expired login sessions on its first pass after startup and then once a day |
| `SUBSTITUTION_DELAY_HOURS` | `24` | Hours after a locked week's `end_time` before its automatic bench substitutions run (see `reference/automatic-bench-substitution.md`) |
| `SCHEDULE_FIXTURES_URL` | *(empty)* | Structured JSON fixtures feed URL for the match schedule. Preferred over `SCHEDULE_SHEET_URL` when both are set; unset falls back to the CSV sheet. See `reference/schedule-fixtures-api.md` |
| `SCHEDULE_SHEET_URL` | *(empty)* | Google Sheets CSV export URL for the match schedule. Fallback when `SCHEDULE_FIXTURES_URL` is unset. No built-in default — leave both empty to disable the schedule tab (e.g. a fresh instance for another league); Kanaliiga deployments must set one explicitly |
| `OPENDOTA_API_KEY` | *(empty)* | Optional API key to raise OpenDota rate limits |
| `OPENDOTA_MAX_RPM` | `55` | Max OpenDota requests per rolling 60 s (free tier ~60/min; default leaves headroom) |
| `TOORNAMENT_CLIENT_ID` | *(empty)* | OAuth2 client ID for toornament.com |
| `TOORNAMENT_CLIENT_SECRET` | *(empty)* | OAuth2 client secret for toornament.com |
| `TOORNAMENT_API_KEY` | *(empty)* | `X-Api-Key` header for toornament.com |
| `TOORNAMENT_TOURNAMENT_ID` | *(empty)* | Toornament tournament UUID |
| `DOTABUFF_LEAGUE_LOGO_PAGES` | *(Kanaliiga URLs)* | Dotabuff league overview URLs to scrape team logos from |
| `LOGO_HOST_ALLOWLIST` | Steam CDN hosts | Comma-separated hosts a team `logo_url` may use (https, no port); others are not stored, returned or fetched (#171) |
| `WEIGHTS_JSON` | *(empty)* | JSON overrides for scoring weights applied at startup |
| `TOKEN_NAME` | `Tokens` | Display name for the token currency |
| `INITIAL_TOKENS` | `5` | Tokens granted to newly registered users |
| `SECRET_KEY` | *(insecure dev default)* | Session signing key — **must be set in production**; with `ENV=production` it must be at least 32 characters |
| `DEBUG` | *(unset)* | Set to `true` for local dev: bypasses the `SECRET_KEY` requirement and the `HTTPS_ONLY` startup check — **never set in production**; with `ENV=production` startup refuses it. `docker-compose.dev.yml` and the backend test conftest set it |
| `HTTPS_ONLY` | `false` | **Required in production.** Set to `true` behind an HTTPS reverse proxy; enables `Secure` flag on session cookies and HSTS. The app refuses to start without it unless `DEBUG=true` or `TWITCH_LOCAL_DEV=true` (the latter only with `SECRET_KEY` unset) |
| `SESSION_IDLE_SECONDS` | `1209600` (14 days) | Player session idle limit. See `reference/longer-sessions.md` |
| `SESSION_ABSOLUTE_SECONDS` | `2592000` (30 days) | Player session absolute limit (the cookie lifetime is the larger of this and `ADMIN_SESSION_ABSOLUTE_SECONDS`) |
| `SESSION_MAX_AGE_SECONDS` | *(unset)* | Deprecated alias for `SESSION_ABSOLUTE_SECONDS`, used only when that is unset (logs a warning) |
| `SESSION_TOUCH_SECONDS` | `300` (5 min) | Minimum interval between `last_seen_at` writes; must be smaller than `ADMIN_SESSION_IDLE_SECONDS` |
| `ADMIN_SESSION_IDLE_SECONDS` | `7200` (2 hours) | Admin session idle limit |
| `ADMIN_SESSION_ABSOLUTE_SECONDS` | `43200` (12 hours) | Admin session absolute limit |
| `ADMIN_REAUTH_SECONDS` | `600` (10 min) | How long a `POST /reauth` covers destructive admin actions |
| `SMTP_HOST` | *(empty)* | SMTP host for email (forgot-password). Disabled if unset. |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(empty)* | SMTP username |
| `SMTP_PASSWORD` | *(empty)* | SMTP password |
| `SMTP_FROM` | Falls back to `SMTP_USER`, then `noreply@fantasy` | Sender address in outgoing emails |
| `SMTP_TLS` | `true` | Use STARTTLS; set to `false` for plain SMTP |
| `SMTP_SSL` | `false` | Use direct SSL (`smtplib.SMTP_SSL`, typically port 465); takes priority over `SMTP_TLS` |
| `APP_NAME` | `Kana Cards` | Prefix used in email subject lines |
| `TWITCH_EXTENSION_CLIENT_ID` | *(empty)* | Extension client ID from Twitch dev console; also the only `ext-twitch.tv` origin CORS allows (none when unset, with a start-up warning) |
| `TWITCH_EXTENSION_SECRET` | *(empty)* | Base64-encoded extension secret from Twitch dev console |
| `TWITCH_EXTENSION_VERSION` | *(empty)* | Extension version installed on the channel (e.g. `1.2.0`); required for MVP chat announcements, which are skipped with one warning when empty |
| `TWITCH_DROP_MAX` | `20` | Server-side cap on viewers per token drop |
| `TWITCH_DROPS_ENABLED` | `true` | `false` turns MVP token drops off (MVP and bonus still set); see `twitch-extension-policy-compliance.md` |
| `TWITCH_SOFT_ACCOUNT_RETENTION_DAYS` | `365` | Idle days before a Twitch viewer soft account is purged by the daily job |
| `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` | `24` | Hours before a new soft account is in MVP drop pools; `0` turns it off; website accounts always eligible (#171) |
| `RATE_LIMIT_TWITCH_JOIN` / `RATE_LIMIT_TWITCH_JOIN_IP` / `RATE_LIMIT_TWITCH_ACTION` | `10/minute` / `60/minute` / `30/minute` | Twitch panel: Join per viewer; Join, draws, heartbeats and `/twitch/ping` per IP; draws, heartbeats, roster changes and Leave per viewer |
| `TWITCH_MVP_CHANNEL_IDS` | *(empty)* | Comma-separated channel IDs always allowed to set MVPs, in addition to channels approved in the admin portal (Admin › Users › Approved streamers, #175). Both empty: no channel with `ENV=production`, any channel otherwise (#165) |
| `RATE_LIMIT_TWITCH_OAUTH` | `10/minute` | Per-IP limit on each of `GET /auth/twitch/start` and `GET /auth/twitch/callback` (#160; replaced `RATE_LIMIT_TWITCH_LINK` with the retired `POST /twitch/link`) |
| `TWITCH_LOCAL_DEV` | *(unset)* | Set to `true` to bypass Twitch JWT validation locally. Also bypasses the `SECRET_KEY` / `HTTPS_ONLY` startup checks, but startup refuses it together with `SECRET_KEY` — **never set in production** |
| `BACKGROUND_TASKS_ENABLED` | `true` | `false` skips starting the four background threads (ingest poll, week maintenance, profile enrichment, DB backup). The backend test conftest sets it `false` — **do not set `false` in production** |
| `ENV` | *(unset)* | Set `production` in production. Startup then fails if `DEBUG=true` or `TWITCH_LOCAL_DEV=true`, or if `SECRET_KEY` is shorter than 32 characters; the Twitch JWT bypass also refuses to run (500) |
| `CSRF_ORIGIN_CHECK` | `true` | Refuses cross-origin POST/PUT/PATCH/DELETE (Origin, else Referer, must match the request `Host` or `APP_BASE_URL`); `/twitch/*` exempt except the session-cookie `/twitch/merge/confirm` and `/twitch/disconnect`. Set `false` if the proxy rewrites `Host` |
| `CORS_EXTRA_ORIGINS` | *(empty)* | Extra comma-separated CORS origins beyond `https://<TWITCH_EXTENSION_CLIENT_ID>.ext-twitch.tv`, e.g. `http://localhost:8080` for Twitch Local Test |
| `ROSTER_LIMIT` | `5` | Maximum active cards per user roster |
| `DEMO_MODE` | *(unset)* | Enables the demo clock override and account-seeding endpoints; disables the OpenDota ingest poll thread — **never set in production**. See `reference/demo-mode.md` |
| `SEED_ADMIN_USERNAME` / `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | *(unset)* | Bootstrap admin account credentials; if all three are set, an admin is created at startup unless an account with that username already exists (ignoring letter case; reserved words are allowed here). Skipped with a warning when `LOGIN_METHOD=steam_signup`. See `reference/env-based-admin-seeding.md` |
| `LOGIN_METHOD` | `password` | `password`, `both` or `steam_signup`: whether Steam sign-in is offered and whether password registration is open (#150). See `reference/steam-login.md` |
| `RESERVED_USERNAME_WORDS` | `admin,kana,liiga,support,official,staff,mod` | Words new usernames can't contain, after look-alike normalisation (#169). See `reference/impersonation-hardening.md` |
| `USERNAME_CHANGE_COOLDOWN_DAYS` | `7` | Days between username changes; `0` turns the limit off (#169) |
| `SEED_ADMIN_STEAM_IDS` | *(empty)* | Comma-separated Steam64 IDs that become admins on a verified Steam sign-in, sign-up or link; removing an ID does not demote (#150) |
| `RATE_LIMIT_STEAM_CALLBACK` | `10/minute` | Per-IP limit on each of the Steam start, callback and sign-up routes (#150) |
| `TEMP_PASSWORD_TTL_HOURS` | `24` | Legacy, no longer read: password reset now uses one-time links. See `reference/temp-password-expiry.md` |
| `ANTHROPIC_API_KEY` | *(empty)* | Enables AI-generated player bios during profile enrichment; facts are stored without a bio if unset. See `reference/player-profile-enrichment.md` |
| `PROFILE_ENRICHMENT_COOLDOWN_HOURS` | `24` | Minimum hours between re-enrichment for a given player |
| `ENRICHMENT_CHECK_INTERVAL` | `300` | Seconds between background profile-enrichment cycles |
| `ENRICHMENT_BATCH_SIZE` | `3` | Players enriched per cycle |
| `GUIDED_TOUR_AUTOSTART` | `false` | `true` starts the My Team guided tour automatically on a player's first visit (per browser); otherwise it only starts from How to Play. Served as `tour_autostart` in `GET /config`. See `reference/guided-tour.md` |
| `APP_VERSION` / `APP_RELEASE` | *(unset)* | Build version / release tag shown as a faint badge on every page. See `reference/version-visibility.md` |
