# FantasyLeague

A fantasy sports web app built around [Kanaliiga](https://kanaliiga.fi), a Finnish amateur Dota 2 league.

## What is a fantasy league?

Participants act as virtual team managers — you draft real players onto your fantasy roster and score points based on how those players actually perform in real matches. The better your picks play in real life, the higher you climb on the leaderboard.

In this app:
- Player cards are generated from real Kanaliiga match data (common → legendary rarity)
- You build a roster by drawing cards using tokens
- Your active roster earns fantasy points from matches played each week
- Rosters lock every Sunday — make your picks before then

## Quick start

**Requirements:** Docker, Docker Compose, and a `.env` file based on `.env.example`.

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY, SCHEDULE_SHEET_URL, and optionally AUTO_INGEST_LEAGUES
docker compose up -d
```

The app runs at `http://localhost:8000`. Data persists in `./data/fantasy.db`.

### Local development

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Source directories are mounted for live reload.

### Reset the database

```bash
rm data/fantasy.db && docker compose restart
```

## Documentation

- [Feature documentation](markdown/features/README.md) — Core features and reference details, split into two tiers
- [User stories](markdown/stories/_index.md) — Full system requirements by section
- [Developer agents](.claude/commands/README.md) — Slash commands, development pipeline, and agent reference

## Stack

- **Backend** — FastAPI, SQLAlchemy, SQLite
- **Frontend** — Vanilla HTML/CSS/JavaScript, served by FastAPI
- **Data sources** — OpenDota API, Google Sheets CSV export
- **Container** — Docker, published to GitHub Container Registry via GitHub Actions
