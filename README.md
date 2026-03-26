# FantasyLeague

## Description
A fantasy league web app for [Kanaliiga](https://kanaliiga.fi), a Finnish amateur Dota 2 league. Users build a roster from a deck of player cards and compete on leaderboards based on real match performance data fetched from the OpenDota API. The season schedule is pulled from a public Google Sheet and displayed as a unified timeline with live series results.

## Deployment

### Requirements
- Docker and Docker Compose
- A `.env` file based on `.env.example`

### Quick start
```
cp .env.example .env
# Edit .env — set GITHUB_REPOSITORY and SCHEDULE_SHEET_URL
docker compose up -d
```

The app is available at `http://localhost:8000`. The SQLite database is stored in `./data/fantasy.db` and persists across restarts.

### Environment variables

| Variable | Description |
|---|---|
| `GITHUB_REPOSITORY` | Your repo in `owner/repo` format — used to pull the correct image from `ghcr.io` |
| `SCHEDULE_SHEET_URL` | Google Sheets CSV export URL for the season fixture list (sheet must be publicly viewable) |

### Ingest league data
After the app is running, log in as admin and use the **Admin → Ingest League** panel, or trigger via curl:
```
curl -X POST http://localhost:8000/ingest/league/19368 \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1}'
```
Repeat for each division. Ingestion fetches all matches from OpenDota, calculates fantasy points, seeds player cards into the deck, and enriches player profiles with names and avatars. It can take several minutes depending on match count and OpenDota rate limits.

### Reset the database
```
rm data/fantasy.db && docker compose restart
```

### Local development
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```
Source directories are mounted for live reload. SQLite is accessed with:
```
sqlite3 data/fantasy.db
```

## Features

### Public
- Season schedule tab — upcoming and past series from the Google Sheet, with results and stream/VOD links where available
- Leaderboards for roster standings and individual player performance (visible without an account)

### Registered users
- Draw a random player card from the deck (common / rare / epic / legendary) — 7 draws granted on registration
- Manage your roster — up to 5 active cards, remaining cards on bench
- View your draw counter and combined roster value

### Admin
- Ingest league data by ID (supports multiple divisions simultaneously)
- Grant additional card draws to specific users
- Adjust scoring weights at runtime and recalculate all historical fantasy points
- Refresh the schedule cache manually

## Schedule tab
The schedule pulls from a public Google Sheet CSV export. Both divisions are shown in a single chronological timeline:
- **Upcoming** series at the top (farthest future first), with stream links
- **Past** series below, with the actual series result (e.g. `2–0`) and VOD links where available
- Series timestamps use the real match start time from the database when results are available

Team names are matched between the sheet and the database using normalised fuzzy matching (case-insensitive, parenthetical content stripped, substring fallback).

## Card draw limits
Each user starts with a draw limit of 7. Admins can grant additional draws per user from the **Admin → Draw Limits** panel. The limit is stored on the user record and enforced server-side.

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

**League** — A tournament in OpenDota. The ID that ties together all players, teams, and matches. Multiple leagues (divisions) can be ingested simultaneously — cards are generated per-league.

**Series** — A best-of-N between two teams on a given fixture date. One row in the schedule sheet; one or more individual matches in the database.

**Match** — A single played map. Contains two teams, 10 players, and per-player performance stats from the OpenDota API.

**Player** — A participant tied to the current league. Names and avatar images are resolved from OpenDota player profiles after ingestion.

**Team** — A team taking part in the league. Names are extracted from match data.

**Card** — A player instance that can be owned by a user. Cards are generated dynamically per league on ingestion: 1 legendary, 2 epic, 4 rare, 8 common per player.

**Deck** — The pool of unowned cards available to draw from.

**Roster** — The active cards a user has selected (max 5). Roster value is the sum of fantasy points across all active cards.

**Weight** — A multiplier applied to a stat when calculating fantasy points. Stored in the database and adjustable via the admin panel.

**Fantasy Points** — Points earned by a player in a single match, calculated as the weighted sum of their performance stats.

## Stack
- **Backend** — FastAPI, SQLAlchemy, SQLite
- **Frontend** — Vanilla HTML/CSS/JavaScript (`index.html`, `style.css`, `app.js`), served by FastAPI
- **Data sources** — OpenDota API, Google Sheets CSV export
- **Container** — Docker, published to GitHub Container Registry via GitHub Actions
