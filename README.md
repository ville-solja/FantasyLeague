# Fantasy League
League agnostic tool that is meant to be easily set up for any Dota 2 amateur tournaments.

A prototype production running for [Kanaliiga](https://kanaliiga.fi), a Finnish amateur Dota 2 league. Not officially affiliated with Kanaliiga.

## What is a fantasy league?

Participants act as virtual team managers — you draft real players onto your fantasy roster and score points based on how those players actually perform in real matches. The better your picks play in real life, the higher you climb on the leaderboard.

In this app:
- Player cards are generated from real league match data (common → legendary rarity)
- You build a roster by drawing cards using tokens
- Your active roster earns fantasy points from matches played each week
- Rosters lock when each admin-defined week begins — make your picks before then

## Quick start

**Requirements:** Docker, Docker Compose, and a `.env` file based on `.env.example`.

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY and, if hosting the Kanaliiga schedule, SCHEDULE_SHEET_URL
# Leagues and season weeks are configured from the admin panel after first login
docker compose up -d
```

`docker compose up -d` is the production path: the app refuses to start unless `SECRET_KEY`
and `HTTPS_ONLY=true` (behind a TLS proxy, see [Deployment](#deployment)) are set. For local use,
run the dev compose command below (it sets `DEBUG=true`) or set `DEBUG=true` in `.env`.

The app runs at `http://localhost:8000`. Data persists in `./data/fantasy.db`.

### Local development

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Source directories are mounted for live reload. The dev file sets `DEBUG=true`, so the app starts
over plain http without `SECRET_KEY` or `HTTPS_ONLY`.

### Reset the database

```bash
rm data/fantasy.db && docker compose restart
```

## Deployment

Before every deploy, back up the database:

```bash
bash scripts/backup-db.sh          # creates data/fantasy.db.backup-YYYYMMDD-HHmmss
docker compose up --build -d
```

### Production requires HTTPS

Production deployments must run behind a TLS-terminating reverse proxy (nginx, Caddy, etc.)
and set `HTTPS_ONLY=true`. The app refuses to start without it (unless `DEBUG=true` or
`TWITCH_LOCAL_DEV=true` for local dev; `TWITCH_LOCAL_DEV` only works with `SECRET_KEY` unset), because without it session cookies are sent without
the `Secure` flag and can be intercepted on unencrypted connections. Only set it once TLS is
really in front of the app: browsers do not send `Secure` cookies over plain HTTP, so login
breaks otherwise. See [HTTPS Enforcement](markdown/features/reference/https-enforcement.md).

### Production environment

Production environment must set `ENV=production`, `HTTPS_ONLY=true` and a `SECRET_KEY` of at
least 32 characters. With `ENV=production` the app refuses to start if `DEBUG=true` or
`TWITCH_LOCAL_DEV=true` is set, so the HTTPS check cannot be bypassed there.
After deploying to staging behind the real proxy, log in, draw a card and change the roster: a 403
"Cross-origin request refused" means the proxy rewrites `Host` — set `APP_BASE_URL`, or as a last
resort `CSRF_ORIGIN_CHECK=false`. See [Security Headers](markdown/features/reference/security-headers.md).

Schema migrations run automatically on startup via `run_migrations()` in `backend/migrate.py`.
See [DB Sustainability](markdown/features/reference/db-sustainability.md) for the migration registry rules.

## Documentation

- [Feature documentation](markdown/features/README.md) — Core features and reference details, split into two tiers
- [Process diagrams](markdown/process-diagrams.md) — Visual flowcharts: season lifecycle, token/card economy, admin tools
- [User stories](markdown/stories/_index.md) — Full system requirements by section
- [Developer agents](.claude/commands/README.md) — Slash commands, development pipeline, and agent reference

## Stack

- **Backend** — FastAPI, SQLAlchemy, SQLite
- **Frontend** — Vanilla HTML/CSS/JavaScript, served by FastAPI
- **Data sources** — OpenDota API, Google Sheets CSV export
- **Container** — Docker, published to GitHub Container Registry via GitHub Actions
