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
| [Card Player Popup Navigation](reference/card-player-popup.md) | Clickable player name on viewed card; modal stacking fix |
| [Tester Account Exclusion](reference/tester-account-exclusion.md) | `is_tester` flag; admin toggle; leaderboard filtering |
| [Profile Header Link](reference/profile-header-link.md) | Clickable username button in header; one-click access to Profile tab |
| [MVP Fantasy Bonus](reference/mvp-fantasy-bonus.md) | Per-match score bonus for the Twitch-appointed MVP; configurable weight |
| [How to Play Tab](reference/how-to-play-tab.md) | In-app rules tab: getting started, Twitch MVP flow, live scoring formula display |
| [Twitch MVP Series Window](reference/twitch-mvp-series-window.md) | Cross-week series list for MVP panel; live ingest polling interval |
| [Token Grant Event](reference/token-grant-event.md) | Admin-configured time-bounded token distribution; auto-claimed on next login |
| [Notification System](reference/notification-system.md) | Admin-configured time-bounded broadcast messages; one-time popup per player |
| [Admin Week Management](reference/admin-week-management.md) | Admin CRUD for week records: custom lock times, create/edit/delete unlocked weeks |
| [DB Sustainability](reference/db-sustainability.md) | Versioned schema migration registry; pre-deploy backup script |
| [Table Element Sortability](reference/table-element-sortability.md) | Client-side sortable column headers for the Players tab table |
| [Card Draw Modal UX](reference/card-draw-modal-ux.md) | Enter-key support, dynamic button label, and backdrop-click dismiss for the draw modal |
| [Prevent Common Card Reroll](reference/prevent-common-card-reroll.md) | Backend 400 guard and hidden Reroll button for common-rarity cards |
| [Env-Based Admin Seeding](reference/env-based-admin-seeding.md) | Replace hardcoded seed credentials with `SEED_ADMIN_*` env vars; empty `users.json` stub in repo |
| [Agent Lessons Log](reference/agent-lessons-log.md) | Append-only lessons file read by agents at run start to avoid recurring pitfalls |
| [User Tag System](reference/user-tag-system.md) | Generic admin-granted tags shown as card stickers and leaderboard chips; new tags need only a DB row + image asset |
