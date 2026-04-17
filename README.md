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

### Feature descriptions

| Topic | Description |
|---|---|
| [Terminology](markdown/feature_description/terminology.md) | Definitions for all domain concepts (League, Card, Deck, Roster, Week, etc.) |
| [Cards & Rarities](markdown/feature_description/cards.md) | Card generation, rarity distribution, and modifiers |
| [Weeks & Leaderboards](markdown/feature_description/weeks.md) | Weekly roster locks, scoring windows, and leaderboard types |
| [Data Ingest](markdown/feature_description/ingest.md) | How match data flows from OpenDota into the app |
| [Admin Features](markdown/feature_description/admin.md) | Admin endpoints: ingest, weights, tokens, promo codes, audit log |
| [Toornament Integration](markdown/feature_description/toornament.md) | Automatic result sync to toornament.com |
| [Point Simulator](markdown/feature_description/point_simulator.md) | The `/simulate` endpoint for testing scoring weights |
| [Profile & Account Management](markdown/feature_description/profile.md) | Username, password, Dota 2 player linking, and forgot-password flow |
| [Configuration & Commands](markdown/feature_description/commands.md) | Environment variables and useful admin commands |
| [Twitch Extension](markdown/feature_description/twitch-extension.md) | Broadcaster token drops, MVP selection, viewer account linking |

### User stories

Full system requirements and user stories: [markdown/user_stories.md](markdown/user_stories.md)

## Stack

- **Backend** — FastAPI, SQLAlchemy, SQLite
- **Frontend** — Vanilla HTML/CSS/JavaScript, served by FastAPI
- **Data sources** — OpenDota API, Google Sheets CSV export
- **Container** — Docker, published to GitHub Container Registry via GitHub Actions
