# FantasyLeague

## Description
A fantasy league web app for [Kanaliiga](https://kanaliiga.fi), a Finnish amateur Dota 2 league. Users build a roster from a deck of player cards and compete on leaderboards based on real match performance data fetched from the OpenDota API.

## Deployment

### Requirements
- Docker and Docker Compose
- A `.env` file based on `.env.example`

### Quick start
```
cp .env.example .env
# Edit .env and set GITHUB_REPOSITORY to your repo (e.g. myusername/dota-kanaliiga-fantasy)
docker compose up -d
```

The app is available at `http://localhost:8000`. The SQLite database is stored in `./data/fantasy.db` and persists across restarts.

### Ingest league data
After the app is running, trigger ingestion for the Kanaliiga league:
```
curl -X POST http://localhost:8000/ingest/league/19369
```
This fetches all matches from OpenDota, calculates fantasy points, and seeds player cards into the deck. Ingestion can take several minutes depending on match count and OpenDota rate limits.

### Local development
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```
Source directories are mounted for hot reload.

## Features
- Register and log in — leaderboards are visible without an account
- Draw a random player card from the deck (common / rare / epic / legendary)
- Manage your roster — up to 5 active cards at a time, rest on bench
- Leaderboards for roster value and individual player performance
- Admin panel for league ingestion, weight adjustment, and points recalculation

## Scoring

Fantasy points per match are calculated from weighted player stats:

| Stat | Default weight |
|---|---|
| Kills | 3.0 |
| Assists | 2.0 |
| Deaths | -1.0 |
| Gold per minute | 0.02 |
| Observer wards placed | 1.0 |
| Sentry wards placed | 1.5 |
| Tower damage | 0.002 |

Weights are configurable at runtime via the Admin tab without re-ingesting data.

## Terminology

**League** — A tournament in OpenDota. The single ID that ties together all players, teams, and matches. Cards are currently seeded for Kanaliiga S15 Lower division (league ID 19369) — ingesting a different league won't have matching players in the deck.

**Match** — A single played map. Contains two teams, 10 players, and per-player performance stats from the OpenDota API.

**Player** — A participant in a match tied to the current league. Names are resolved from OpenDota player profiles after ingestion.

**Team** — A team taking part in the league. Team names are extracted from match data since amateur teams are not in the OpenDota pro teams database.

**Card** — A player instance that can be owned by a user. Each player has 15 cards in the deck: 1 legendary, 2 epic, 4 rare, 8 common.

**Deck** — The pool of unowned cards available to draw from.

**Roster** — The active cards a user has selected (max 5). Roster value is the sum of fantasy points across all active cards.

**Weight** — A multiplier applied to a stat when calculating fantasy points. Stored in the database and adjustable via the admin panel.

**Fantasy Points** — Points earned by a player in a single match, calculated as the weighted sum of their performance stats.

## Stack
- **Backend** — FastAPI, SQLAlchemy, SQLite
- **Frontend** — Vanilla HTML/CSS/JavaScript, served by FastAPI
- **Data source** — OpenDota API
- **Container** — Docker, published to GitHub Container Registry via GitHub Actions
