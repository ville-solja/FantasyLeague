# Fantasy League

A fantasy league for amateur Dota 2 tournaments. Players collect cards of real league players, build a weekly roster, and score points from those players' real match stats. It is not tied to any one league: the league, its schedule, the token name and the scoring weights are all configured per deployment.

## How the game works

- Each card is a real league player, with a rarity from Common to Legendary.
- You draw cards with tokens.
- Up to 5 cards form your active roster, which earns points from that week's league matches.
- Rosters lock when each admin-defined week begins, so make your picks before then.

## Quick start (local)

**Requirements:** Docker and Docker Compose.

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The app runs at `http://localhost:8000`. Log in with an admin account (see `SEED_ADMIN_*` in `.env.example`) and set up leagues and season weeks in the admin panel. To show a league schedule, set `SCHEDULE_FIXTURES_URL` or `SCHEDULE_SHEET_URL` in `.env`.

The dev compose file sets `DEBUG=true`, so the app starts over plain http without `SECRET_KEY` or `HTTPS_ONLY`, and mounts the source directories for live reload. Data persists in `./data/fantasy.db`.

To start again with an empty database (this deletes all data):

```bash
rm data/fantasy.db && docker compose restart
```

## Deployment

Production runs `docker compose up -d` behind a TLS-terminating reverse proxy (nginx, Caddy, etc.).

### Required settings

| Variable | Value | Why |
|---|---|---|
| `ENV` | `production` | Turns on the production guards: the app refuses to start if `DEBUG=true` or `TWITCH_LOCAL_DEV=true` is set |
| `HTTPS_ONLY` | `true` | Marks session cookies `Secure`; see below |
| `SECRET_KEY` | 32+ random characters | Signs session cookies; shorter keys are refused with `ENV=production` |
| `APP_BASE_URL` | e.g. `https://your-deployment.example.com` | Links in reset emails; also accepted by the cross-origin check |

### Production requires HTTPS

The app refuses to start without `HTTPS_ONLY=true` unless `DEBUG=true` or `TWITCH_LOCAL_DEV=true` is set for local dev (`TWITCH_LOCAL_DEV` only works with `SECRET_KEY` unset). Without it, session cookies lack the `Secure` flag and can be intercepted on unencrypted connections. Set it only once TLS is really in front of the app: browsers don't send `Secure` cookies over plain HTTP, so login breaks otherwise. See [HTTPS Enforcement](markdown/features/reference/https-enforcement.md).

### Each deploy

1. Back up the database:
   ```bash
   bash scripts/backup-db.sh          # creates data/fantasy.db.backup-YYYYMMDD-HHmmss
   docker compose up --build -d
   ```
2. Schema migrations run automatically on startup (`run_migrations()` in `backend/migrate.py`). See [DB Sustainability](markdown/features/reference/db-sustainability.md) for the migration rules.
3. On staging behind the real proxy, log in, draw a card and change the roster. A 403 "Cross-origin request refused" means the proxy rewrites `Host`: set `APP_BASE_URL`, or as a last resort `CSRF_ORIGIN_CHECK=false`. See [Security Headers](markdown/features/reference/security-headers.md).

Every other setting is documented in `.env.example`.

## Documentation

- [Feature documentation](markdown/features/README.md) — Core features and reference details, split into two tiers
- [Process diagrams](markdown/process-diagrams.md) — Visual flowcharts: season lifecycle, token/card economy, admin tools
- [User stories](markdown/stories/_index.md) — Full system requirements by section
- [Developer agents](.claude/commands/README.md) — Slash commands, development pipeline, and agent reference

## Stack

- **Backend** — FastAPI, SQLAlchemy, SQLite
- **Frontend** — Vanilla HTML/CSS/JavaScript with Alpine.js, served by FastAPI
- **Twitch** — Panel and broadcaster extension in `twitch-extension/`, backed by the same app
- **Data sources** — OpenDota API; schedule from a JSON fixtures feed or a Google Sheets CSV export
- **Container** — Docker, published to GitHub Container Registry via GitHub Actions
