# Feature Documentation

Feature docs are split into two tiers: **Core** features that are user-facing and frequently referenced, and **Reference** features covering implementation details, integrations, and tooling.

---

## Core Features

These describe the primary user-visible surfaces of the app.

| Feature | Description |
|---|---|
| [Authentication & Accounts](core/auth.md) | Registration, login, sessions, profile management, forgot-password |
| [Cards & Rarities](core/cards.md) | Card generation, rarity distribution, modifiers, scoring formula, reroll |
| [Weeks & Leaderboards](core/weeks.md) | Weekly roster locks, scoring windows, and leaderboard types |
| [Players & Teams](core/players.md) | Player and team browse endpoints with match history |
| [Admin Features](core/admin.md) | Promo codes, token grants, weights, ingest, schedule, audit log |
| [Twitch Extension](core/twitch-extension.md) | Broadcaster token drops, MVP selection, viewer account linking |

---

## Reference Features

Implementation details, integrations, and operator tooling.

| Feature | Description |
|---|---|
| [Terminology](reference/terminology.md) | Definitions for all domain concepts (League, Card, Deck, Roster, Week, etc.) |
| [Data Ingest](reference/ingest.md) | How match data flows from OpenDota into the app |
| [Card Image Generation](reference/card-image-generation.md) | Pillow-based PNG card rendering pipeline |
| [Toornament Integration](reference/toornament.md) | Automatic result sync to toornament.com |
| [Player Profile Enrichment](reference/player-profile-enrichment.md) | AI-generated player bios from OpenDota stats |
| [Point Simulator](reference/point-simulator.md) | The `/simulate` endpoint for testing scoring weights |
| [Automated Testing](reference/automated-testing.md) | Playwright UI suite and GitHub Actions CI setup |
| [Version Visibility](reference/version-visibility.md) | Faint build version badge on every page |
| [Configuration & Commands](reference/commands.md) | Environment variables and useful admin commands |
| [My Team Tab Layout](reference/my-team-tab-layout.md) | Two-column desktop layout for the My Team tab |
