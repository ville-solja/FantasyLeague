# FantasyLeague

## What is this?

FantasyLeague is a fantasy sports web app built around [Kanaliiga](https://kanaliiga.fi), a Finnish amateur Dota 2 league.

### What is a fantasy league?

A fantasy league is a game where participants act as virtual team managers. Instead of rooting for a real team, you draft real players onto your own fantasy roster and score points based on how those players actually perform in real matches. The better your picked players do in real life, the higher you climb on the fantasy leaderboard.

In a traditional fantasy sport (e.g. football), you pick players before a season and accumulate points week by week. This app follows the same idea — but for Dota 2 esports.

### How does it work here?

1. **Cards are generated from real league data.** When an admin ingests a Kanaliiga season, every player who has competed gets a set of cards (common → legendary) whose value is based on that player's actual in-game stats across all matches.
2. **You build a roster by drawing cards.** New users receive 7 draw attempts. Each draw gives you a random card from the shared deck — rarer cards belong to higher-performing players.
3. **Your roster earns fantasy points week by week.** The season is divided into weekly periods ending each Sunday. Whatever 5 cards are active when Sunday ends get locked in, and points are scored from matches played during that week only. Swap your cards freely before each Sunday lock to react to the upcoming match schedule.
4. **Compete on the leaderboard.** Weekly leaderboards show who made the best calls each week. An all-time leaderboard tracks cumulative performance across the whole season.

The season schedule, match results, and stream/VOD links are displayed in a unified timeline so you can follow the action that feeds your fantasy points.

---

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
| `AUTO_INGEST_LEAGUES` | Comma-separated OpenDota league IDs to ingest on startup. Defaults to `19368,19369`. Set empty to disable. |
| `SEASON_LOCK_START` | ISO date of the first Sunday lock (e.g. `2026-03-08`). All weekly boundaries are derived from this. |

### Ingest league data
League data is ingested automatically on startup in a background thread. The leagues to ingest are controlled by `AUTO_INGEST_LEAGUES` in `.env` (comma-separated OpenDota league IDs, defaults to `19368,19369`). Matches already in the database are skipped, so restarts are fast.

To disable auto-ingest, set `AUTO_INGEST_LEAGUES=` (empty).

To trigger a manual re-ingest (e.g. after a new match week), log in as admin and use the **Admin → Ingest League** panel, or via curl:
```
curl -X POST http://localhost:8000/ingest/league/19368 \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1}'
```
Ingestion fetches all matches from OpenDota, calculates fantasy points, seeds player cards into the deck, and enriches player profiles with names and avatars. It can take several minutes depending on match count and OpenDota rate limits.

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

## Weekly roster locks

The season is divided into **weekly periods**, each ending on Sunday at midnight UTC. At that moment the server automatically snapshots every user's active roster and locks it for that week.

### How points work

Fantasy points are **scoped to the week they were earned**. A card's weekly score is the sum of fantasy points from matches played during that specific week — not from all time. This means:

- A card that plays two matches in Week 3 only earns points in Week 3's leaderboard, regardless of what other weeks it has played in
- The all-time leaderboard still shows cumulative totals across the whole season
- The weekly leaderboard shows who made the best roster decisions for each individual week

### How locking works

1. **Before Sunday midnight** — freely swap cards in and out of your active roster. Whatever 5 cards are active when Sunday ends is your locked lineup for that week.
2. **Sunday midnight** — the server snapshots all active rosters. The snapshot is immutable and used for scoring.
3. **After Sunday** — the locked roster is shown as a read-only record. You can immediately start adjusting your roster for the following week's lock.

Locks happen automatically — no admin action is required. Past weeks are viewable as historical snapshots alongside the current editable roster.

### Viewing past weeks

The My Team tab includes a week selector. Selecting a past week shows that week's locked roster and the points it earned during that period. The current editable roster is always available and represents what will be snapshotted at the next Sunday lock.

### Season configuration

The first lock date and all subsequent Sunday boundaries are controlled by `SEASON_LOCK_START` in `.env` (default `2026-03-08`). For a new season, update this value and reset the database.

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

**Roster** — The active cards a user has selected (max 5). The editable roster is snapshotted each Sunday midnight into a weekly locked roster. Weekly value is the sum of fantasy points earned by those locked cards during that week's matches only.

**Weight** — A multiplier applied to a stat when calculating fantasy points. Stored in the database and adjustable via the admin panel.

**Fantasy Points** — Points earned by a player in a single match, calculated as the weighted sum of their performance stats.

## Stack
- **Backend** — FastAPI, SQLAlchemy, SQLite
- **Frontend** — Vanilla HTML/CSS/JavaScript (`index.html`, `style.css`, `app.js`), served by FastAPI
- **Data sources** — OpenDota API, Google Sheets CSV export
- **Container** — Docker, published to GitHub Container Registry via GitHub Actions
