# Kana Hub Integration Feasibility

Decision document for issue #108: can Kana Cards' key features move into Kana Hub (the Eggosystem), what blocks it, and which integration option to take. Written for the product owner, Kana Cards developers and the hub maintainers. It can be read without either codebase; file paths are there for checking.

**Recommendation: Option C, link plus API data exchange, with Kana Cards switching to Steam-only login (Option B1) in the same between-seasons release.** Kana Cards stays a separate app and becomes the Dota fantasy game next to the hub's separate CS2 fantasy. In the hub's per-game structure, Dota gets its own game entry and season pages, and the Dota season's Fantasy link opens Kana Cards. Once the Dota schedule moves into the hub, Kana Cards reads it from there instead of its own fixtures feed. Steam-only login gives both sites the same player identity and lets Kana Cards drop its password, email and reset handling. A full port (Option A) is a rewrite in another stack and needs Dota data in the hub first. Worked out in depth, it is about 45–70 person-weeks over at least five season breaks, so it is not recommended now; it stays a possible later target with explicit decision criteria. See [Recommendation](#6-recommendation), the [first step](#first-step-one-sprint) and [Option A in depth](#11-option-a-in-depth).

---

## Contents

- [Sources checked](#sources-checked)
- [Summary](#summary)
- [How the two systems compare](#1-how-the-two-systems-compare)
- [How the hub is organised per game, and where Dota fits](#2-how-the-hub-is-organised-per-game-and-where-dota-fits)
- [Preliminary findings: confirmed and corrected](#3-preliminary-findings-confirmed-and-corrected)
- [Architectural blockers](#4-architectural-blockers)
- [Integration options](#5-integration-options), including [what Steam login removes from Kana Cards](#what-steam-login-removes-from-kana-cards)
- [Recommendation](#6-recommendation)
- [Kana Cards next to the CS2 fantasy](#7-kana-cards-next-to-the-cs2-fantasy)
- [Toward a single tournament site](#8-toward-a-single-tournament-site)
- [Questions for the hub team](#9-questions-for-the-hub-team)
- [Account bridging](#10-account-bridging)
- [Option A in depth](#11-option-a-in-depth): target architecture, data model, background work, frontend, Twitch, testing, effort, phases, risks and decision criteria

---

## Sources checked

| Source | Version |
|---|---|
| Kana Hub (Eggosystem), public GitLab project `kanaliiga_public/kanahub/eggosystem` | Branch `development`, commit `9e49c668c1a698a55974b3d0dec7af05480a2287` (2026-10-02, "Merge branch 'cursor/playoff-match-object-created-8860' into 'development'"). Read on 2026-10-02 through the GitLab API and a source archive of that commit. Nothing from the hub was installed or run. |
| Kana Hub, live site `https://hub.kanaliiga.fi` | Two anonymous read requests on 2026-10-02 to the public calendar endpoint (see [section 3](#3-preliminary-findings-confirmed-and-corrected)). Only field names and status codes were recorded. |
| Kana Cards (this repository) | Branch `Documentation-overhaul`, commit `f47de6f2651c5c16dde3a2ee892a5159d0385583` (2026-10-01), plus uncommitted work in progress. |

Hub paths below are relative to the Eggosystem repository root (for example `apps/backend/src/routes/index.ts`). Kana Cards paths are relative to this repository (for example `backend/schedule.py`).

## Summary

- **The stacks share nothing.** The hub is a TypeScript monorepo (Express 5, Knex, MariaDB, Next.js 16, React 19). Kana Cards is Python (FastAPI, SQLAlchemy, SQLite) with a vanilla JS frontend. Moving Kana Cards into the hub means rewriting it.
- **The hub is built for more games, and Dota has a clear slot.** Each game has a frontend registry entry, its own backend domain (`games/cs/`, `games/pubg/`) and, for fantasy, its own namespace (`games/fantasy/cs/`). PUBG was added this way as the second game. Dota would follow the same pattern: a `dota` registry entry, a `games/dota/` domain for seasons and match data, and the fantasy either ported to `games/fantasy/dota/` or linked out to Kana Cards. See [section 2](#2-how-the-hub-is-organised-per-game-and-where-dota-fits).
- **Nothing Dota exists in the hub beyond a catalogue row.** `Games` has Dota 2 (id 4, Steam app 570), used only by the team-finder (Kanahautomo) sign-up form. There is no registry entry, no Dota season, no Dota match data and no OpenDota code. The live calendar answers "No active season found" for app 570.
- **The hub's fantasy is a CS2 game and a separate product.** It is a budget fantasy (1 000 000 budget, 5 players, CS2 roles) scored from parsed CS2 demos. Kana Cards is a card-collection fantasy for Dota. They do not compete, and nothing in one can be reused for the other without a rewrite.
- **Identities line up through Steam.** The hub keys players by Steam64 ID. A Kana Cards OpenDota player ID is a Steam32 ID, and Steam64 = Steam32 + `76561197960265728`. Dota needs no extra account link in the hub (unlike PUBG): the Steam login already gives the OpenDota ID.
- **Steam login simplifies Kana Cards.** Moving to the hub (A) means Steam login only, which removes Kana Cards' passwords, registration, password reset email (SMTP), login lockouts and its own session handling. Switching Kana Cards itself to Steam-only login (B1) removes most of the same code without moving. See [What Steam login removes](#what-steam-login-removes-from-kana-cards).
- **The cheapest real value is the schedule.** Kanaliiga plans to move the Dota schedule into the hub. Kana Cards already reads an external JSON fixtures feed (`SCHEDULE_FIXTURES_URL`), so reading the hub's schedule is a small adapter, once the hub has a Dota season and a stable endpoint for it.
- **A full port is years of hobby work.** Option A, worked out module by module, is about 45–70 person-weeks: roughly 1.7 to 3.3 years for two developers working evenings, live in phases over at least five season breaks, with no player benefit before the cutover. Option C with Steam-only login is about 5–8 person-weeks and is also the first step toward A. See [Option A in depth](#11-option-a-in-depth).
- **Licensing is not a concern.** The hub is GPL-3.0 and Kana Cards has no licence file, but both are hobby projects and the product owner has ruled it out.

---

## 1. How the two systems compare

| Area | Kana Hub (Eggosystem) | Kana Cards | Gap |
|---|---|---|---|
| **Stack** | pnpm + Turborepo monorepo. Backend: Node.js, Express 5, TypeScript, Knex, Passport (`README.architecture.md`, `apps/backend/src/app.ts`). Frontend: Next.js 16 App Router, React 19, Tailwind v4, shadcn (`apps/frontend/`). Shared types in `packages/types/`. | Python FastAPI app (`backend/main.py`, `backend/routers/`), SQLAlchemy models (`backend/models.py`). Frontend: vanilla JS split into `frontend/app-*.js`, with Alpine.js for some subtabs (`markdown/features/reference/frontend-framework-evaluation.md`). No build step. | No shared language, framework or code. A port is a rewrite. |
| **Data model (database)** | MariaDB 12. Knex migrations in `apps/backend/migrations/` (274 files). Business rules partly live in SQL triggers and functions (`README.architecture.md`, "Business Logic in Database Triggers"; `apps/backend/migrations/20250127080331_add_triggers.ts`). Hierarchy: organizer, season, league (division), team, match, match game. | One SQLite file in WAL mode (`backend/database.py`). Numbered Python migrations in `backend/migrate.py`. Tables for users, cards, weekly rosters, per-match player stats and stored card points (`backend/models.py`). | Different engine and different rule placement (triggers vs Python). Every Kana Cards table would need a Knex migration and new hub-side rules. |
| **Identity** | Steam OpenID login only, issuing RS256-signed JWT access and refresh cookies (`apps/backend/src/routes/v1/auth.routes.ts`, `apps/backend/src/services/auth.services.ts`, `apps/backend/src/middlewares/auth.middleware.ts`). Steam64 is the primary player key; `Accounts` plus `LinkedAccounts` (`apps/backend/migrations/20250415015337_add_accounts_tables.ts`), whose `provider` is one of `steam`, `discord` and `pubg` (`apps/backend/migrations/20260615120000_add_pubg_provider_to_linked_accounts.ts`). | Username, email and password with bcrypt (`backend/auth.py`, `backend/routers/auth.py`), password reset by email (`backend/email_utils.py`), and server-side sessions in `user_sessions` (`backend/sessions.py`, issue #117, `markdown/features/core/auth.md`). Optional self-reported OpenDota player ID (`users.player_id`, `markdown/features/reference/player-linking-and-tag-visibility.md`). Optional Twitch link (`users.twitch_user_id`). | Different login model. A bridge exists through the Steam ID (see [Account bridging](#10-account-bridging)). |
| **Game data** | CS2: demo parsing and KanaRating, fed through RabbitMQ consumers (`apps/backend/src/games/cs/services/parsed-queue-consumer.ts`). PUBG: Krafton API poller and ingestion (`apps/backend/src/games/pubg/services/pubg-poller.services.ts`, `apps/backend/src/games/pubg/services/pubg-ingestion.services.ts`). Dota 2: a `Games` row only (`apps/backend/migrations/20250623152817_add_more_steam_games.ts`). | Dota 2 only. Polls monitored OpenDota leagues, fetches each match and stores per-player stats (`backend/ingest.py`, `backend/opendota_client.py`, `markdown/features/reference/ingest.md`). Enriches player profiles in the background (`backend/enrich.py`). | The hub has no Dota match data. Kana Cards owns the only Dota ingest. |
| **League model** | Organizer-run seasons with leagues (divisions) built by the Sortter, team registration, and rosters in `SeasonTeamPlayers` (`README.architecture.md`, "Core Business Model"). Multi-organizer and multi-game, served at `/{organizer}/{game}` (see [section 2](#2-how-the-hub-is-organised-per-game-and-where-dota-fits)). | Teams and players come from OpenDota match data. Admin-defined fantasy weeks (`backend/weeks.py`, `markdown/features/core/weeks.md`). The Dota schedule comes from an external fixtures feed or a Google Sheet (`backend/schedule.py`). Series results are pushed to Toornament (`backend/toornament.py`). | Kanaliiga's Dota seasons, teams and schedule are not in the hub today. |
| **Fantasy design** | CS2 fantasy league, a separate product (see [section 7](#7-kana-cards-next-to-the-cs2-fantasy)). Code in `apps/backend/src/games/fantasy/cs/`; tables from `apps/backend/migrations/20251124000001_create_fantasy_league_tables.ts` and later fantasy migrations. Scoring described in [section 3](#how-the-hubs-fantasy-league-scores). | Card collection: token draws with rarities and modifiers (`backend/card_draw.py`, `markdown/features/core/cards.md`), weekly rosters with a bench and automatic substitution (`backend/match_scoring.py`, `markdown/features/reference/automatic-bench-substitution.md`), MVP bonus, per-match stored card points (`backend/card_points.py`, `markdown/features/reference/stored-card-points.md`). | Two different games. No merge is needed or planned. |
| **Background jobs** | RabbitMQ consumers started in `app.ts`; BullMQ queues on Redis for email, demo parsing and PUBG polling (`apps/backend/src/utils/bullmq.utils.ts`, `apps/backend/src/services/queue-consumer-manager.ts`, `README.architecture.md`, "Async Subsystems"). | In-process daemon threads in `backend/main.py`: ingest polling, week maintenance (lock and summaries), profile enrichment, database backups. | A port would turn every loop into a queue job or worker. |
| **Twitch** | No Twitch extension or EBS. Twitch appears only as stream links and caster reservations (`apps/frontend/src/components/calendar/StreamReservation.tsx`, `apps/frontend/src/lib/official-kanaliiga-stream.ts`). | Twitch panel extension (`twitch-extension/`) with the Kana Cards backend as its EBS (`backend/twitch.py`). The EBS URL `https://kana-cards.com` is set in the extension's global configuration and in its URL-fetching allowlist (`markdown/features/core/twitch-extension.md`). Account linking, MVP token drops and chat announcements. | Moving the EBS means a new host, new configuration and a new Twitch review. |
| **Hosting** | Docker Compose behind Traefik on a shared `web` network. Services: backend, Next.js frontend, MariaDB, MaxScale, Redis, RabbitMQ, bull-monitor, phpMyAdmin, a database backup job. Images from the GitLab registry; OpenTelemetry to Grafana Alloy (`docker-compose.prod.yml`). | One Docker image from GHCR with a SQLite volume (`Dockerfile`, `docker-compose.yml`), served at `kana-cards.com`. | Different hosts and operators. Co-hosting is possible but not required by any option except A. |
| **Embedding and APIs** | `(embed)` route group with an iframe calendar (`apps/frontend/src/app/(embed)/calendar/page.tsx`). Public API `/api/v2` is a narrow subset; the hub's own reads live under `/api/v2/internal`, which the frontend proxies; legacy `/api/v1` is fully public "until deprecated" (`apps/backend/src/routes/index.ts`, `README.api.md`). Service-to-service API keys via `x-api-key` (`apps/backend/src/middlewares/api-key-auth.middleware.ts`). | Standalone site. Content-Security-Policy `frame-ancestors 'self'` plus Twitch origins only (`backend/main.py`, `markdown/features/reference/security-headers.md`). Reads the schedule from `SCHEDULE_FIXTURES_URL` (`backend/schedule.py`, `markdown/features/reference/schedule-fixtures-api.md`). | Linking is easy. Reading hub data needs a stable endpoint. Embedding logged-in Kana Cards views is blocked (see blocker 8). |
| **Licence** | GPL-3.0 (`LICENSE`). | No licence file. | **Not a concern.** Both are hobby projects; the product owner has ruled licensing out. It is not listed as a blocker. |

### Kana Cards' moving parts

What any integration has to keep working:

| Part | Files | What it does |
|---|---|---|
| Ingest | `backend/ingest.py`, `backend/opendota_client.py` | Polls monitored OpenDota leagues, stores matches and per-player stats, skips matches under 15 minutes. |
| Stored card points (#141) | `backend/card_points.py` | One `card_match_points` row per (card, match). My Team, the weekly and season leaderboards and the End Season archive sum these rows; the Players tab's per-match view uses `player_match_stats.fantasy_points`. |
| Accounts and sessions (#117) | `backend/auth.py`, `backend/routers/auth.py`, `backend/email_utils.py`, `backend/sessions.py`, `backend/deps.py` | Password accounts, password reset by email, server-side sessions; the cookie carries only a session ID. |
| Twitch extension and EBS | `backend/twitch.py`, `twitch-extension/` | Viewer account linking, MVP selection, token drops, chat announcements. |
| Weeks and substitutions (#129) | `backend/weeks.py`, `backend/match_scoring.py` | Admin-defined weeks that lock automatically; bench cards replace starters with no counted match. |
| Tokens and draws | `backend/card_draw.py`, `backend/routers/cards.py` | Token balance, card draws by rarity, modifiers, rerolls, team booster draws. |
| Schedule | `backend/schedule.py` | Upcoming series from `SCHEDULE_FIXTURES_URL` (or the sheet CSV), cross-referenced with ingested results. |

---

## 2. How the hub is organised per game, and where Dota fits

The hub is not a CS2 site with extras. It is a multi-organizer, multi-game platform, and each game plugs into the same layers. PUBG was added as the second game by following this pattern (`PUBG-WORKFLOW.md`). Dota would be the third, and any integration option should put Kana Cards' parts into the same layers.

### The layers

| Layer | How it works | Hub source |
|---|---|---|
| **Organizers and seasons** | An `Organizers` table; each organizer enables games through `OrganizerGames`, with at most one `is_default` game. Each `Seasons` row has an `organizer_id` and a `game_id`. | `PUBG-WORKFLOW.md` ("Multi-organizer, multi-game"); `apps/backend/migrations/20250720170843_organizers.ts`; `apps/backend/migrations/20250811013830_add_season_organizer_fk.ts`; `apps/backend/migrations/20260611130000_add_organizer_games_is_default.ts` |
| **Public URLs** | `/{organizer}/{game}/…`, for example `/kanaliiga/pubg/seasons/12/schedule`. A proxy rewrites these to flat app routes and sets the `x-organizer-slug` and `x-game-slug` headers. `gameHubPath` builds `/{org}/{game}`; only games in the frontend registry get a hub, so an enabled game without a registry entry has no pages. | `PUBG-WORKFLOW.md`; `apps/frontend/src/proxy.ts`; `apps/frontend/src/lib/games/tenant-path.ts`; `apps/frontend/src/lib/games/game-hub-path.ts` |
| **Admin** | `/{organizer}/dashboard/…`. The navigation follows the game of the selected season (`resolveDashboardGameCapabilities`). | `PUBG-WORKFLOW.md`; `apps/frontend/src/lib/games/dashboard-nav-capabilities.ts` |
| **Frontend game registry** | `GAME_CONFIG` has one entry per game: `cs2` (gameId 1, appId 730, matchModel `h2h`, statsKind `round`, `fantasy: true`, plus map veto, demo parsing, Sortter, leaderboards and top teams, roster size 5) and `pubg` (gameId 2, appId 578080, `battle-royale`, `placement`, `fantasy: false`, `gameDay: true`, roster size 4). `GameCapabilities` switches features on or off per game. | `apps/frontend/src/lib/games/registry.ts` |
| **Season pages** | Season-scoped routes under `apps/frontend/src/app/(main)/(content-container)/seasons/[season]/`: calendar, captains, faceit-links, fantasy, leagues, live-placements, schedule, sessions, signup and standings. Which links a season shows depends on its game: a `h2h` game gets the head-to-head pages, and the "Fantasy League" link (to `/seasons/{id}/fantasy`) appears only when the game's `caps.fantasy` is true. | `apps/frontend/src/lib/season-utils.ts` (`getSeasonPageLinks`) |
| **Backend game domains** | One folder per game with controllers, models, routes, services and utils: `apps/backend/src/games/cs/` and `apps/backend/src/games/pubg/`. A test forbids imports and table names crossing between the CS and PUBG domains. | `apps/backend/src/games/domain-boundaries.test.ts` |
| **Fantasy per game** | Fantasy code is namespaced by game: `apps/backend/src/games/fantasy/cs/` is the CS2 fantasy. | `apps/backend/src/games/fantasy/cs/` |
| **Accounts and login (core)** | Not per game. Steam OpenID and JWT cookies for everyone; extra game accounts are `LinkedAccounts` rows. | `apps/backend/src/routes/v1/auth.routes.ts`; `apps/backend/migrations/20260615120000_add_pubg_provider_to_linked_accounts.ts` |

**How PUBG was added** (`PUBG-WORKFLOW.md`): a `pubg` registry entry, the `games/pubg/` domain, and a pipeline of account link (a Krafton nickname stored in `LinkedAccounts` with provider `pubg`), signup, admin approval, the Sortter, game days, ingestion from the Krafton API (`apps/backend/src/games/pubg/services/pubg-ingestion.services.ts`) and standings.

**Where Dota stands today:** `Games` has Dota 2 (id 4, app 570), but there is no registry entry and no `games/dota` domain, so the hub has no Dota pages (`/kanaliiga/dota2` is a tested 404 in `apps/frontend/src/proxy.test.ts`).

### Dota in the same pattern

| Hub layer | Dota piece | Notes |
|---|---|---|
| Frontend registry | A `dota` entry: gameId 4, appId 570, matchModel `h2h`, `caps.fantasy: true`. | `h2h` gives Dota the same season pages as CS2 (standings, calendar, schedule). The slug is the hub team's choice; this document uses `dota`. |
| Season pages | The Dota schedule at `/{organizer}/dota/seasons/{id}/schedule`, for example `/kanaliiga/dota/seasons/{id}/schedule`. | Reuses the existing season routes. |
| Backend game domain | `apps/backend/src/games/dota/` for Dota seasons, teams and the schedule, and, if the hub takes it over, OpenDota match ingestion by league polling as Kana Cards does today. | Mirrors `games/pubg/` with its Krafton ingestion. |
| Fantasy | Option A: the card fantasy ported to `apps/backend/src/games/fantasy/dota/`. Option C: no fantasy code in the hub; the Dota season's Fantasy link opens Kana Cards. | Today the Fantasy link always points to the internal `/seasons/{id}/fantasy` route (`apps/frontend/src/lib/season-utils.ts`), so an external link for Dota is a small hub change. |
| Identity | Nothing extra. | Simpler than PUBG: PUBG needs a linked Krafton account, but the OpenDota account ID is the Steam32 form of the Steam ID the user already logs in with (see [Account bridging](#10-account-bridging)). |

### Which Kana Cards part belongs to which hub layer

| Kana Cards part | Files | Hub layer |
|---|---|---|
| Match ingest, teams, players, profile enrichment | `backend/ingest.py`, `backend/opendota_client.py`, `backend/enrich.py` | `games/dota/` |
| Schedule and Toornament results | `backend/schedule.py`, `backend/toornament.py` | `games/dota/` (the schedule is the hub's own Dota season data) |
| Cards, tokens and draws | `backend/card_draw.py`, `backend/routers/cards.py` | `games/fantasy/dota/` |
| Weeks, rosters, substitutions, scoring, stored card points, weekly summaries | `backend/weeks.py`, `backend/match_scoring.py`, `backend/scoring.py`, `backend/card_points.py`, `backend/routers/weekly_summary.py` | `games/fantasy/dota/` |
| Twitch extension EBS | `backend/twitch.py`, `twitch-extension/` | `games/fantasy/dota/` (the MVP drops and token grants are fantasy features) |
| Accounts, login, sessions, password reset | `backend/auth.py`, `backend/routers/auth.py`, `backend/sessions.py`, `backend/email_utils.py` | Hub core: replaced by Steam OpenID and JWT, not ported |

Under Option C the same split decides who owns what: the hub owns the `games/dota/` layer (seasons, teams, schedule; ingestion stays in Kana Cards unless the hub wants it, question 3), and Kana Cards remains the `games/fantasy/dota/` layer as a separate site.

---

## 3. Preliminary findings: confirmed and corrected

The plan (`markdown/plans/plan-issue-108-kana-hub-integration-feasibility.md`) listed preliminary findings. Checked against commit `9e49c668c1a698a55974b3d0dec7af05480a2287`:

| Finding | Result |
|---|---|
| The hub is a TypeScript monorepo (Express 5, Knex, MariaDB, Next.js 16, React 19). | Confirmed (`README.architecture.md`, `README.md`). |
| Business rules in triggers and SQL functions. | Confirmed (`README.architecture.md`). |
| Steam OpenID login, RS256 JWT cookies, Steam ID as primary key, Discord linking. | Confirmed. Added detail: the access and refresh cookies are `SameSite=Strict` and set by the hub's own host, and the login return URL must be on an allow-list (the hub plus white-label custom domains in `packages/types/src/organizers/custom-domain-hostnames.ts`, checked in `apps/backend/src/utils/auth-url-utils.ts`). An outside site such as Kana Cards cannot reuse the hub login without a hub change. |
| `Games` has a Dota 2 row (id 4, app 570) but no Dota match ingestion. | Confirmed, and narrower than stated. The row and a "Team clash" game type exist only for the team-finder (Kanahautomo) sign-up (`apps/backend/src/games/cs/models/kanahautomo.models.ts`). The frontend game registry has only `cs2` and `pubg` (`apps/frontend/src/lib/games/registry.ts`); `/kanaliiga/dota2` is a tested 404 (`apps/frontend/src/proxy.test.ts`). `packages/types/src/games/game-ids.ts` defines only CS2 and PUBG. There is no OpenDota code anywhere in the repository. Live check: `GET https://hub.kanaliiga.fi/api/v1/calendar/organizers/1/apps/570/matches` returns 404 "No active season found for organizer 1 and app 570". So the hub ingests no Dota data and has no Dota season. |
| The hub has a CS2 fantasy league. | Confirmed. It is a separate product, see below and [section 7](#7-kana-cards-next-to-the-cs2-fantasy). |
| Background work on BullMQ and RabbitMQ. | Confirmed. |
| No Twitch extension in the hub. | Confirmed. |
| `(embed)` route group and API-key service auth. | Confirmed. The embed group has one page, the calendar, configured by query string (`organizer_id`, `app_id`, `league_id`, `view`, `theme`). |
| Licence GPL-3.0. | Confirmed (`LICENSE`); not a concern. |

**Corrections and additions:**

- **The hub's schedule data is not on its stable public API.** The calendar endpoint `GET /calendar/organizers/{organizer_id}/apps/{app_id}/matches` (`apps/backend/src/routes/v1/calendar.routes.ts`) is mounted under `/api/v2/internal` (the frontend's own API) and under the legacy `/api/v1`, which `README.api.md` calls "fully public until deprecated". The public `/api/v2` surface has only a few routes (player and organizer subsets, casters, ELO, launch, Discord bot, Faceit; see `mountExternalOnlyRoutes` in `apps/backend/src/routes/index.ts`). Kana Cards could read `/api/v1` today, but that path is set to be deprecated. A supported public endpoint is a question for the hub team.
- **The calendar response is not in Kana Cards' fixtures format.** A live CS2 response (`app_id` 730) is a JSON list of matches with fields such as `match_id`, `match_start`, `match_end`, `match_status` (`SCHEDULED`, `FINISHED`, `FORFEIT`), `match_team1`, `match_team2`, `teams`, `league_name`, `league_tier`, `season_id`, `match_number` and `stream_urls`. Kana Cards' fixtures feed expects `{"fixtures": [...]}` with `week`, `division` (`upper`/`lower`), `team1`, `team2`, an optional `starts_at` (falling back to `date`/`time`, then `week_start`) and `stream`; `parse_fixtures_json` in `backend/schedule.py` turns that input into the internal `weeks[]` structure the Schedule tab uses. Pointing `SCHEDULE_FIXTURES_URL` at the hub therefore needs either a small adapter in Kana Cards that produces `weeks[]` directly from the hub calendar (the recommended route, see the first step), or a fixtures-shaped endpoint in the hub.
- **The hub is multi-game by design.** Games plug in through a registry entry and a backend domain; see [section 2](#2-how-the-hub-is-organised-per-game-and-where-dota-fits).
- **Kana Cards' player ID is self-reported.** Users type their OpenDota ID on the Profile tab; nothing verifies it. A Steam login verifies the Steam ID, which matters for bridging.
- **Embedding logged-in Kana Cards views in the hub does not work as is.** Kana Cards only allows framing by itself and Twitch (`frame-ancestors`), and its session cookie is `SameSite=Lax` (`backend/main.py`), which browsers do not send inside a cross-site iframe. Public, read-only views could be embedded after a header change; logged-in views should be links.

### How the hub's fantasy league scores

From `apps/backend/src/games/fantasy/cs/utils/fantasy-scoring.utils.ts` and `apps/backend/src/games/fantasy/cs/services/fantasy-points.service.ts`:

- **Trigger:** when a parsed CS2 demo arrives, the RabbitMQ consumer `apps/backend/src/games/cs/services/parsed-queue-consumer.ts` calls `calculateFantasyPointsForGame` for that match game. Forfeits get a flat team-result score (`calculateFantasyPointsForForfeitMatch`, `FantasyForfeitPointsLog`).
- **Per player, per match game:** a base from KanaRating against a 0.7 baseline (×30), a K/D modifier (−5 to +8), impact plays (opening kills and deaths, 3K/4K/5K, clutches, MVPs, assists at 0.3 each), and bonuses for ADR, KAST and headshot percentage. Individual points are kept between −30 and +30. The team result adds +5 for a win or −5 for a loss.
- **Roles:** each picked player has one of 18 CS2 roles (`main_awp`, `entry_fragger`, `leader`, `clutch_player` and others in `FantasyTeamPlayers.role`). A role adds a percentage bonus when its condition is met, for example +30% of opening-kill points for an entry fragger.
- **Team building:** one team per Steam ID per season and division, exactly 5 players, a budget of 1 000 000 (`apps/backend/src/games/fantasy/cs/models/fantasy-teams.models.ts`). Player prices come from `FantasyPlayerValues` with bronze, silver and gold tiers and are updated from performance (`apps/backend/src/games/fantasy/cs/services/fantasy-value.service.ts`). Substitutions cost or return budget.
- **Results:** `FantasyPointsLog` per player and match game, a `FantasyLeaderboard` snapshot, and private leagues with invite codes (`FantasyPrivateLeagues`, `FantasyPrivateLeagueMembers`).

Everything above depends on CS2 demo statistics and CS2 roles. None of it applies to Dota, and Kana Cards' scoring (`backend/scoring.py`) has nothing to gain from it. That is consistent with the product owner's clarification: the two fantasies are separate products.

---

## 4. Architectural blockers

Severity: **blocker** means the option cannot start until it is removed; **major** means real work or a decision by another team; **minor** means a small, known change.

| # | Blocker | Severity | Affects | What removes it |
|---|---|---|---|---|
| 1 | **Stack rewrite.** Kana Cards (Python, FastAPI, SQLite, vanilla JS) shares no code with the hub (TypeScript, Express, Knex, MariaDB, Next.js). | blocker | A | Rewrite every backend module, migration and frontend tab in the hub's stack, or choose an option that keeps Kana Cards separate (B, C, D). |
| 2 | **Dota seasons, teams and schedule are not in the hub.** No Dota season exists, the frontend registry has no Dota entry and there is no `games/dota` domain, and the live calendar returns 404 for app 570. | blocker | A, C (schedule reading), single tournament site | The hub team adds a `dota` registry entry and Dota seasons, leagues, teams and the match schedule (see [section 2](#2-how-the-hub-is-organised-per-game-and-where-dota-fits)). This is the **dependency on the hub's Dota schedule work**: until it is done, nothing Dota can be read from or shown in the hub. |
| 3 | **Dota match data is not in the hub.** No OpenDota ingest, no Dota stats tables. | blocker for A; none for B, C, D | A | Either the hub ingests Dota matches in `games/dota/` (a new subsystem, like PUBG's Krafton ingestion), or Kana Cards keeps its own OpenDota ingest, which options B, C and D do. |
| 4 | **Identity (account) migration.** Kana Cards accounts are username and password; the hub has Steam accounts only. Player IDs are self-reported and unverified. | major | A, B | A one-time "Link Steam" step for each user via Steam OpenID, mapping the Kana Cards user to a Steam64 ID, done between seasons. Because the season reset deletes cards and resets tokens, a user who does not link loses only history, not a live collection. See [Account bridging](#10-account-bridging). |
| 5 | **Twitch EBS move.** The extension's EBS is `https://kana-cards.com`, stored in the extension's global configuration and URL-fetching allowlist. | major | A | Port the `/twitch/*` routes to the hub, change the configured EBS URL and allowlist, and submit a new extension version for Twitch review. Options B, C and D leave the EBS where it is. |
| 6 | **No stable public API for the hub's schedule.** The calendar endpoint is on `/api/v2/internal` and the legacy `/api/v1`, not on the public `/api/v2`. | major | C | The hub team exposes a public read endpoint for a season's matches (or confirms `/api/v1` stays), optionally behind an `x-api-key`. |
| 7 | **The hub login is not open to other sites.** Return URLs are allow-listed and the JWT cookies are `SameSite=Strict` on the hub's host. | major | B (shared login through the hub) | Either Kana Cards runs its own Steam OpenID login (no hub change, same Steam64 identity), or the hub adds an SSO flow for trusted external services. |
| 8 | **Embedding Kana Cards views.** Kana Cards' `frame-ancestors` allows only itself and Twitch; its `SameSite=Lax` session cookie is not sent in a cross-site iframe. | minor | C (embed variant) | Link to Kana Cards for logged-in pages. For public read-only views (a leaderboard), add the hub origin to `frame-ancestors`. |
| 9 | **Fixtures format differs.** The hub calendar returns a match list; Kana Cards' feed input is `{"fixtures": [...]}` with `week` and `division`, parsed into an internal `weeks[]` structure. | minor | C | A Kana Cards adapter that produces `weeks[]` directly, mapping `match_start` to a fantasy week and `league_name`/`league_tier` to a division; or a fixtures-shaped endpoint in the hub. |
| 10 | **Team identity across systems.** Kana Cards teams come from OpenDota team IDs; hub teams have their own IDs. Kana Cards already matches schedule team names to its teams by normalised name (`find_team_id` in `backend/schedule.py`). | minor | C | Keep name matching at first; later store the hub team ID next to the OpenDota team ID (an admin mapping), if name matching proves unreliable. |
| 11 | **Background job model.** Kana Cards' daemon threads have no counterpart in the hub's queue model. | major | A | Rewrite ingest, week maintenance and enrichment as `node-cron` schedules feeding BullMQ queues, as the hub's PUBG poller does; backups are covered by the hub's backup container (see [Background work](#114-background-work)). |

---

## 5. Integration options

Effort uses t-shirt sizes: **S** is a few days, **M** about one sprint, **L** several sprints, **XL** a project of a season or more. Sizes are for one part-time developer who knows the codebase in question.

### What Steam login removes from Kana Cards

Both Option A and Option B can make Steam the only way to log in. Every Kana Cards player then needs a Steam account, which Dota players already have, and existing accounts need a one-time Steam link or claim between seasons (see [Account bridging](#10-account-bridging)). In return, Kana Cards no longer handles passwords or sends email. Checked against this repository:

| Kind | Removable with Steam-only login (Option B1) |
|---|---|
| Files | `backend/email_utils.py` (SMTP sending); the password functions in `backend/auth.py` (`hash_password`, `verify_password`, `check_password_bytes`, and `check_email` once email is no longer collected). |
| Endpoints | `POST /register`, `POST /forgot-password`, `POST /reset-password` and `PUT /profile/password`. `POST /login` is replaced by a Steam OpenID login route and its callback. `PUT /profile/player-id` is no longer needed: `player_id` comes from the verified Steam ID. |
| In-process state | The per-username login lockout and the per-account forgot-password cooldown in `backend/routers/auth.py`. |
| Data | The `password_reset_tokens` table (`PasswordResetToken`), and the `users` columns `email`, `password_hash`, `must_change_password` and `temp_password_expires_at` (dropped, or left unused). |
| Env vars | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS`, `SMTP_SSL`; `PASSWORD_RESET_TOKEN_TTL_HOURS`; the legacy `TEMP_PASSWORD_TTL_HOURS`; `RATE_LIMIT_REGISTER`, `RATE_LIMIT_FORGOT_PASSWORD`, `RATE_LIMIT_RESET_PASSWORD`; `LOGIN_LOCKOUT_THRESHOLD`, `LOGIN_LOCKOUT_WINDOW_SECONDS`; `FORGOT_PASSWORD_COOLDOWN_SECONDS`. `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD` (and their numbered forms) are replaced by a Steam ID-based admin seed. |
| Dependency | `bcrypt` in `backend/requirements.txt`, and with it the 72-byte password limit. |
| Frontend | The register, forgot-password and reset-password modals (`frontend/index.html`, `frontend/app-auth.js`) and the change-password and player-ID forms on the Profile tab (`frontend/app-profile.js`). |
| Tests and docs | `backend/tests/test_auth.py`, `test_gmail_smtp_integration.py`, `test_issue_77_temp_password_expiry.py`, `test_issue_122_forgot_password_cooldown.py`, `test_issue_123_password_reset_token_flow.py`, and the login and reset parts of `test_issue_121_rate_limiting.py`; `markdown/features/reference/smtp-password-recovery.md`, `markdown/features/reference/password-reset-token-flow.md`, `markdown/features/reference/forgot-password-cooldown.md`, `markdown/features/reference/temp-password-expiry.md`, and the password parts of `markdown/features/core/auth.md` and `markdown/features/reference/rate-limiting.md`. |

**What stays under Option B1:** Kana Cards still issues its own login session after the Steam callback, so `backend/sessions.py`, the `user_sessions` table, the `SESSION_*` and `ADMIN_SESSION_*` limits, `/logout`, `/logout-everywhere` and the session list stay. `POST /reauth` (admin password re-entry, issue #117) becomes a fresh Steam login round trip. `APP_BASE_URL` stays and also gives the OpenID return URL. Kana Cards still keeps the username as a display name and the Twitch link. The verified Steam64 ID needs a new unique `users` column, which needs a numbered migration in `backend/migrate.py`.

**Under Option A** nothing in this table is ported, and neither is the session layer: the hub's Steam OpenID and JWT cookies (`apps/backend/src/routes/v1/auth.routes.ts`, `apps/backend/src/services/auth.services.ts`) replace `backend/sessions.py`, the `SESSION_*` and `ADMIN_SESSION_*` env vars, `/reauth`, `/logout-everywhere` and the session endpoints as well.

### Option A — Full port into the Eggosystem

Kana Cards is rebuilt inside the hub as the Dota game, following the per-game pattern in [section 2](#2-how-the-hub-is-organised-per-game-and-where-dota-fits): a `dota` registry entry, a `games/dota/` domain for seasons, teams and OpenDota ingestion, and the card fantasy in `games/fantasy/dota/`, next to the CS2 fantasy in `games/fantasy/cs/`.

**What users see:** one site and one Steam login. A Dota section at `/{organizer}/dota/…` with schedule, teams, results and the card fantasy under the season's Fantasy page. The Twitch extension talks to the hub. `kana-cards.com` redirects to the hub.

**Effort:**

| Area | Size | Work |
|---|---|---|
| Dota season, teams and schedule in the hub | L | Hub-side: the `dota` registry entry and the `games/dota/` season data; also a prerequisite for C (blocker 2). |
| Dota match ingest in the hub | L | Port `backend/ingest.py` and `backend/opendota_client.py` to a worker in `games/dota/`, as PUBG has Krafton ingestion in `games/pubg/`; stats tables (blocker 3). |
| Card fantasy backend | XL | Port draws, rarities, modifiers, rosters, bench, MVP, stored card points, weekly summaries and admin tools to `games/fantasy/dota/`; Knex migrations (blocker 1). |
| Card fantasy frontend | XL | Rebuild every tab in Next.js and React under the Dota season's fantasy route. |
| Background jobs | M | Queue jobs for ingest, week lock, enrichment (blocker 11). |
| Accounts and login | S | Nothing to port: the hub's Steam login replaces Kana Cards' accounts, password reset, SMTP email, lockouts and sessions (see [What Steam login removes](#what-steam-login-removes-from-kana-cards)). |
| Identity and data migration | M | Steam linking for all users, then a one-time import of users, season archives, tags and Twitch links into MariaDB (blocker 4). Done at the season break, after the reset has deleted cards and rosters, so no live collections are moved. |
| Twitch EBS | M | Port `/twitch/*` into `games/fantasy/dota/`, new EBS URL, new Twitch review (blocker 5). |

**In depth:** [section 11](#11-option-a-in-depth) breaks this down per area: about 45–70 person-weeks (sizes above are for one part-time developer; section 11 uses full-time person-weeks), a phased plan over at least five season breaks, the target layout in the hub, the data model mapping and the decision criteria.

**Risks:** the largest option by far, with no user-visible gain until it is finished. It depends on two hub prerequisites (blockers 2 and 3). Scoring parity: a rewritten scoring path must reproduce Kana Cards' scoring exactly, or results differ between seasons. Ownership: Kana Cards' developers would work in a codebase and process they do not own. Every player needs a Steam account, which is fine for Dota players.

**Existing data (accounts, cards, history):** accounts and history must be exported and imported. Cards and rosters do not move if the port happens between seasons, because the season reset deletes them anyway. Users without a Steam link cannot be matched to a hub account and lose their season history unless an admin matches them by hand. Season archives must be copied, not recalculated.

**Twitch extension:** the EBS moves to the hub; new extension version, new URL allowlist entry and a new Twitch review. Viewer Twitch links must be migrated to hub accounts, which first needs a `twitch` provider in `LinkedAccounts` (today `steam`, `discord` and `pubg`).

### Option B — Kana Cards stays separate, with Steam login and identity

Kana Cards keeps its codebase and host, and adds "Sign in with Steam" so a Kana Cards account carries the same Steam64 identity as the hub.

Two variants:
- **B1 — Kana Cards' own Steam OpenID login.** Kana Cards talks to Steam directly. No hub change. Recommended as **Steam-only**: Steam replaces password login instead of sitting beside it, which removes the code listed in [What Steam login removes](#what-steam-login-removes-from-kana-cards). Keeping password login beside Steam is possible, but keeps all of that code and adds a second login path.
- **B2 — Login through the hub (SSO).** Kana Cards sends users to the hub to log in. Needs a new hub flow for external services (blocker 7).

**What users see:** a "Sign in with Steam" button on Kana Cards and no password, registration or "forgot password" forms. Their Dota player card and Profile link are filled in from Steam automatically. Same site and branding as today; no change in the hub.

**Effort:**

| Area | Size | Work |
|---|---|---|
| Steam OpenID login (B1) | M | Login route, callback, account creation, Steam64 column and migration, tests. |
| Claim existing accounts | S | Between seasons: a "Link Steam" step for logged-in password users, then password login switched off before the next season's first week. |
| Remove password login | S | Delete the endpoints, files, env vars, tests and docs listed in [What Steam login removes](#what-steam-login-removes-from-kana-cards). |
| Hub SSO (B2) | L | Hub-side flow and token exchange, plus Kana Cards client side. Depends on the hub team. |
| Data migration | S | None beyond the claim step; accounts stay in Kana Cards. |
| Twitch EBS | S | No change. |

**Risks:** every player needs a Steam account (fine for Dota players). Players who miss the claim window lose their username, past-season history, tags and Twitch link unless an admin merges the accounts; cards are not at risk, because the season reset deletes them anyway. A Steam OpenID outage blocks all logins. Account merging when a Steam ID is already claimed by another Kana Cards user's self-reported `player_id`. Steam OpenID cannot force a password prompt, so the admin re-entry for destructive actions proves a fresh Steam login rather than a typed password. B2 depends on hub work and on a security review on both sides.

**Existing data (accounts, cards, history):** kept for every claimed account, which gains a verified Steam ID. Unclaimed accounts can no longer log in.

**Twitch extension:** no change. Twitch links stay on the Kana Cards user.

### Option C — Link or embed from the hub, and exchange data through APIs

Kana Cards stays separate. The hub links to it as the Dota fantasy; Kana Cards reads the Dota schedule, teams and results from the hub once they move there.

In the hub's structure ([section 2](#2-how-the-hub-is-organised-per-game-and-where-dota-fits)), the hub owns the Dota game layer (a `dota` registry entry with `caps.fantasy: true`, and Dota seasons, teams and the schedule in `games/dota/`), and Kana Cards stays the Dota fantasy layer as an external site. There is no `games/fantasy/dota/` in the hub; the Dota season's Fantasy link opens Kana Cards.

**What users see:** in the hub's Dota season pages (`/{organizer}/dota/seasons/{id}/…`), a "Fantasy" entry that opens Kana Cards. In Kana Cards, the Schedule tab shows the same fixtures as the hub, with a link back to the hub's match pages. Optionally, a public Kana Cards leaderboard embedded in the hub.

**Effort:**

| Area | Size | Work |
|---|---|---|
| Hub link to Kana Cards | S | Hub-side: the Dota season's Fantasy link points to Kana Cards instead of the internal `/seasons/{id}/fantasy` route (`apps/frontend/src/lib/season-utils.ts`). The hub team decides placement. |
| Read the hub's Dota schedule | S | Adapter from the hub calendar JSON to Kana Cards' `weeks[]` structure, selected by configuration next to `SCHEDULE_FIXTURES_URL` (blocker 9). |
| Read hub teams and results | M | Map hub teams to OpenDota teams (blocker 10); show hub results where they exist. |
| Public hub endpoint | S | Hub-side, if the hub team agrees (blocker 6). |
| Embedded public views | S | Allow the hub origin in `frame-ancestors`; an embed-friendly leaderboard page (blocker 8). |
| Data migration | S | None. |
| Twitch EBS | S | No change. |
| Visual alignment with the hub | M | Restyle Kana Cards to the hub's visual standards (colours, typography, spacing, component look) so the Dota fantasy reads as part of the same site. Kana Cards keeps its own HTML/CSS; it adopts the hub's design tokens rather than porting Tailwind or shadcn. |

**Risks:** depends on the hub's Dota schedule work (blocker 2) for its main benefit; until then only the link is possible. An unannounced change to the hub's response shape breaks the Schedule tab, so the adapter must fall back to the last good data, as `get_schedule` already does for the fixtures feed. On its own, C keeps two logins (Steam on the hub, password on Kana Cards); pairing it with B1 removes that.

**Existing data (accounts, cards, history):** unchanged.

**Twitch extension:** no change.

### Option D — No integration

Kana Cards keeps its own site, branding, login and schedule source.

**What users see:** nothing changes. Kanaliiga's Dota players use the hub for the tournament once it moves there, and Kana Cards separately for the fantasy, with no link between them.

**Effort:**

| Area | Size | Work |
|---|---|---|
| All areas | S | None, beyond keeping the current fixtures feed or sheet up to date. |

**Risks:** the Dota schedule is kept in two places once it moves to the hub, and they drift. Kana Cards misses the hub's audience. When the external fixtures feed or sheet is retired, the Schedule tab loses its source. Kana Cards keeps maintaining password login, reset email and SMTP.

**Existing data (accounts, cards, history):** unchanged.

**Twitch extension:** no change.

### Side by side

| | A — Full port | B — Steam login | C — Link + API | D — None |
|---|---|---|---|---|
| Users see | One site, one login | Steam-only login on Kana Cards | Hub links to Kana Cards; one schedule | No change |
| Place in the hub | `games/dota/` and `games/fantasy/dota/` | None | `dota` registry entry and `games/dota/` (hub); fantasy link out | None |
| Login code Kana Cards maintains | None (hub Steam login and JWT) | Steam callback and its own sessions; no passwords, reset email or SMTP (B1 Steam-only) | Unchanged, unless combined with B1 | Passwords, reset email, SMTP, lockouts and sessions |
| Total effort | XL: about 45–70 person-weeks ([section 11](#118-effort-and-phased-migration)) | M (B1 Steam-only), L (B2) | M (incl. visual alignment); about 5–8 person-weeks together with B1 | S |
| Season breaks to go live | At least five (realistically five to eight) | One | One (schedule from the hub once it has a Dota season) | None |
| Needs hub work | Yes, large | B2 only | Small (registry entry, link, endpoint) after the Dota schedule | No |
| Existing data | Accounts and history imported; cards reset between seasons | Kept for claimed accounts | Unchanged | Unchanged |
| Twitch extension | Moves, new review | No change | No change | No change |
| Main risk | Size, parity, ownership | Unclaimed accounts; Steam required | Hub API stability | Schedule drift |

---

## 6. Recommendation

**Choose Option C, switch Kana Cards to Steam-only login (Option B1) in the same between-seasons release, and do not start Option A.**

Reasons:
1. **It delivers the real value at the lowest cost.** The product owner's goal is one tournament site: schedule, teams, results and fantasy in one place. With C the hub owns the Dota game layer and links to the Dota fantasy, and Kana Cards shows the same schedule. That is most of the "single site" for a small part of A's cost.
2. **It fits the hub's own structure.** Dota becomes a registry game like CS2 and PUBG, with its season pages in the hub, and the fantasy is the one layer that stays external. A later port (A) would add `games/fantasy/dota/` without changing what users already know.
3. **It reuses what exists.** Kana Cards already reads an external schedule (`SCHEDULE_FIXTURES_URL` in `backend/schedule.py`) and falls back to stale data on failure. The hub already serves a per-season calendar and has an embed pattern.
4. **Steam-only login gives most of A's login simplification without moving.** It removes Kana Cards' passwords, registration, reset tokens, SMTP email, lockouts and cooldowns, needs no hub work, and turns self-reported player IDs into verified Steam64 IDs, the same identity the hub uses. Doing it between seasons is cheap, because the season reset already deletes cards and resets tokens: a player who misses the claim step loses only history.
5. **It keeps what users have.** Claimed accounts, season history and the Twitch extension stay as they are.
6. **Option A is blocked twice over, and large.** It needs the Dota schedule and Dota match data in the hub first (blockers 2 and 3), then a full rewrite (blocker 1). The [deep dive](#11-option-a-in-depth) puts it at about 45–70 person-weeks over at least five season breaks.

### Option A after the deep dive

The deeper evaluation of Option A does not change the recommendation; [section 11.11](#1111-does-the-deep-dive-change-the-recommendation) gives the reasons. C and B1 are also the first steps toward A: the Dota season in the hub is phase 0 of a port, and B1's verified Steam64 IDs remove the account claim from a later cutover. So the path is **C and B1 now, A as a possible later target**: re-check the [decision criteria](#1110-decision-criteria) at each season break, and start a port only when the hub runs Dota, the hub team wants Dota data and a `games/fantasy/dota/` module with a named owner, and the developer capacity for about 45–70 person-weeks exists.

### First step (one sprint)

**Build the hub schedule adapter in Kana Cards, tested against the hub's CS2 calendar, and send the questions in [section 9](#9-questions-for-the-hub-team) to the hub team.**

1. Send the questions to the hub maintainers, together with this document.
2. Add a parser that turns the hub calendar response (`match_start`, `match_team1`, `match_team2`, `league_name`/`league_tier`, `match_status`, `stream_urls`) into Kana Cards' `weeks[]` structure. Map `match_start` to the admin-defined fantasy week and the league to `div1`/`div2`.
3. Select it by configuration next to `SCHEDULE_FIXTURES_URL`, so the current fixtures feed stays the default until the hub has a Dota season.
4. Test it against a recorded CS2 response from `GET /api/v1/calendar/organizers/1/apps/730/matches` (same match structure), including the stale-data fallback.
5. Switch production to the hub source once the hub has a Dota season and the endpoint question (blocker 6) is answered.

This is size S to M, has no dependency to start, and is useful as soon as the hub's Dota schedule work lands. The Steam-only login can be built in the next sprint, behind configuration, and switched on at the season break.

### Timing: between seasons

The integration work is planned for the break **between seasons** (product-owner decision, 2026-10-02). During a season, players have live rosters, tokens and weekly locks, so changes to login, schedule source or the site's look would disrupt play.

- **Can happen any time:** building and testing the hub schedule adapter and the Steam login (behind configuration, default off), and sending the questions to the hub team.
- **Between seasons only:** switching the schedule source to the hub, the Steam claim step and switching off password login, the visual alignment with the hub, and the hub's Dota fantasy link going live. Do them together after End Season and before the next season's first week locks, so players start the new season on the integrated site.

---

## 7. Kana Cards next to the CS2 fantasy

The hub's CS2 fantasy league and Kana Cards are **separate products**. Kana Cards is the Dota fantasy game; the CS2 fantasy stays the CS2 game. Neither replaces the other, and their rules stay different (budget picks with roles in CS2, card collection in Dota).

How they sit side by side under Option C:

| Aspect | Proposal |
|---|---|
| **Navigation** | The hub already gates fantasy per game (`caps.fantasy` in `apps/frontend/src/lib/games/registry.ts`; the CS2 fantasy lives at `apps/frontend/src/app/(main)/(content-container)/seasons/[season]/fantasy/`). The Dota registry entry would set `caps.fantasy: true`, so "Fantasy" shows in the same place in the Dota season navigation, opening Kana Cards in a new tab and marked as an external site. |
| **Naming** | "CS2 Fantasy" and "Dota Fantasy (Kana Cards)", so players can tell the two games apart. |
| **Account** | Both use the same Steam identity once Kana Cards is Steam-only (B1), so a player is recognisably the same person in both, though the logins stay separate. |
| **Leaderboards** | Each game keeps its own leaderboard. The hub can link to (or, after blocker 8, embed) Kana Cards' public season leaderboard on the Dota season page. No combined cross-game leaderboard. |
| **Visuals** | Kana Cards is aligned with the hub's visual standards (product-owner decision, 2026-10-02), so moving between the hub and the Dota fantasy feels like one site. The card art and card-specific elements stay, restyled to fit. The `/ui-design` agent's brand context must then point at the hub's standards instead of the current Kana Cards palette. |

---

## 8. Toward a single tournament site

What one site for the Dota tournament needs, in order:

1. **Dota season, teams and schedule in the hub** (hub team): a `dota` registry entry and the `games/dota/` season data, so the schedule lives at `/{organizer}/dota/seasons/{id}/schedule`. This is the prerequisite; nothing below gives a single site without it.
2. **A readable endpoint for that schedule** (hub team, blocker 6).
3. **Kana Cards reads the schedule from the hub** (Kana Cards, the first step above). One schedule, kept in one place.
4. **The hub links the Dota fantasy** from the Dota season's Fantasy entry (hub team), and optionally embeds the public Kana Cards leaderboard.
5. **Steam-only login in Kana Cards** (Option B1), so both sites know the same player and Kana Cards drops its password and email handling.

Steps 3 to 5 and the visual alignment go live together between seasons (see [Timing](#timing-between-seasons)).

6. **Results and teams from the hub** where they exist (Option C, M size), with the hub team ID stored next to the OpenDota team ID.
7. **Only then, if wanted, revisit a deeper merge** (B2, or A as `games/fantasy/dota/` with Dota ingest in `games/dota/`), with real usage data from steps 1 to 6 and against the [decision criteria](#1110-decision-criteria) for Option A.

---

## 9. Questions for the hub team

| # | Question | Affects |
|---|---|---|
| 1 | When and how are Dota seasons, teams and the schedule planned to arrive in the hub? Will they follow the PUBG pattern: a `dota` registry entry (gameId 4, appId 570, `h2h`) and a `games/dota/` domain, using the existing season, league and match model? Which slug (`dota` or `dota2`)? | Blocker 2; Options A and C; the single tournament site |
| 2 | Will the hub expose a Dota season's matches through the public API (`/api/v2`) that Kana Cards could read? If not, will the legacy `/api/v1/calendar/...` route stay available, and for how long? Is an `x-api-key` preferred? | Blocker 6; Option C |
| 3 | Is Dota match data (OpenDota stats) wanted in the hub's `games/dota/` domain, or should Kana Cards keep ingesting it and stay the only Dota stats source? | Blocker 3; Option A |
| 4 | What hosting and login (SSO) options exist for external services? Could the hub add an SSO flow for a trusted external site, or should Kana Cards run its own Steam login? | Blocker 7; Options B (B2) and A |
| 5 | Can the hub link to, or embed, an external service from a season's navigation, in the place the CS2 fantasy uses (a Dota season's Fantasy link pointing outside the hub)? Is an iframe of a public Kana Cards page acceptable? | Blocker 8; Option C |
| 6 | Will Dota fixtures carry a week or round number, and which field identifies the division (league)? | Blocker 9; Option C |
| 7 | Would the hub store an OpenDota team ID (or Steam team ID) on Dota teams, so results can be matched without team names? | Blocker 10; Option C |
| 8 | Is there interest in a full port later (Option A), and who would own a `games/fantasy/dota/` module in the Eggosystem? | Blockers 1, 5 and 11; Option A |
| 9 | For a port: would the hub accept a Twitch EBS router on the public `/api/v2`, Twitch and Anthropic secrets in the backend, and `node-cron` plus BullMQ jobs for Dota ingestion in the shared backend process? Is there a hotfix path for a fantasy bug during a season? | Blocker 5; Option A |

---

## 10. Account bridging

### Steam32 and Steam64

A Kana Cards `users.player_id` is an OpenDota account ID, which is the 32-bit Steam account ID (Steam32). The hub keys players by the 64-bit Steam ID (Steam64). They convert exactly:

```
Steam64 = Steam32 + 76561197960265728
Steam32 = Steam64 - 76561197960265728
```

So a Kana Cards user with a player ID maps to exactly one hub Steam identity, and a Steam login (Option B1) gives Kana Cards the player ID directly, without the user typing it. This is also why Dota needs no extra linked account in the hub, unlike PUBG.

### The linked-ID count is not decisive

How many Kana Cards users have a linked player ID today does not change any decision in this document: the architecture, blockers and options are the same whatever the count. Every account is claimed the same way (a one-time Steam login), and a self-reported `player_id` is replaced by the verified one in any case.

### Users without a linked ID

- **Options C and D:** nothing changes; they keep playing as today.
- **Option B1 (Steam-only):** a one-time "Link Steam" step between seasons, while password login still works. After the Steam login, Kana Cards stores the verified Steam ID and sets `player_id` from it. If another account already claims the same self-reported `player_id`, the verified Steam login wins and an admin resolves the old claim. Once password login is switched off, an unclaimed account can no longer log in; its owner starts fresh with a Steam login, losing only username, season history, tags and Twitch link, since the season reset has already cleared cards and tokens. An admin can merge the old account on request.
- **Option A:** every user must link Steam before the import, or an admin matches the account by hand. Users who do neither cannot be mapped to a hub account, and their season history would be left behind.

### Twitch links

Twitch links (`users.twitch_user_id` and, since #160, `users.twitch_account_id` from Twitch sign-in in `backend/twitch_oauth.py`; link codes were retired) belong to the Kana Cards user, not to a Steam ID. Under Options B, C and D they stay as they are. Under Option A they must move to the hub, which first needs a `twitch` provider in `LinkedAccounts` (today `steam`, `discord` and `pubg`, `apps/backend/migrations/20260615120000_add_pubg_provider_to_linked_accounts.ts`), and the extension's EBS must move with them (blocker 5).

---

## 11. Option A in depth

This section works out what a full port into the Eggosystem would take, module by module, so the decision against it rests on numbers rather than on "it is a rewrite". All hub paths are at commit `9e49c668c1a698a55974b3d0dec7af05480a2287` (branch `development`).

**Result:** about **45–70 person-weeks**, spread over **at least five season breaks** (realistically five to eight). That does not change the [recommendation](#6-recommendation): Option C with Steam-only login now, and Option A only as a later target once the [decision criteria](#1110-decision-criteria) are met. See [Does the deep dive change the recommendation?](#1111-does-the-deep-dive-change-the-recommendation)

### 11.1 What would move

| | Kana Cards (this repository) | Hub reference point |
|---|---|---|
| Backend code | About 10 400 lines of Python in `backend/*.py` and `backend/routers/*.py` (tests excluded); 37 tables in `backend/models.py`; about 120 route handlers. | The CS2 fantasy backend, `apps/backend/src/games/fantasy/cs/`, is about 7 200 lines of TypeScript without tests. The PUBG domain, `apps/backend/src/games/pubg/`, is about 27 900 lines without tests, added through 33 migrations dated from `20260615120000_add_pubg_provider_to_linked_accounts.ts` to `20260928120000_add_admin_account_id_to_pubg_sessions.ts`. |
| Frontend code | 21 vanilla JS files (`frontend/app-*.js`, about 4 900 lines), `frontend/index.html` (about 1 200 lines) and `frontend/style.css` (about 1 300 lines). | The CS2 fantasy pages and components (`apps/frontend/src/components/fantasy/`, `apps/frontend/src/components/dashboard/fantasy-admin/`, `apps/frontend/src/app/(main)/(content-container)/seasons/[season]/fantasy/`) are about 7 500 lines of TSX without tests. |
| Tests | About 1 500 collected pytest tests in 84 files under `backend/tests/` (about 30 000 lines). | Jest suites next to the code, Playwright E2E in `apps/frontend/src/e2e/`. |
| Twitch | `backend/twitch.py` (EBS) and `twitch-extension/`. | None. |

### 11.2 Target architecture in the hub

**Backend layout.** Each game domain in the hub has `controllers/`, `models/`, `routes/`, `services/` and `utils/` (see `apps/backend/src/games/cs/`, `apps/backend/src/games/pubg/`, `apps/backend/src/games/fantasy/cs/`). Requests flow route, controller, service, model (`README.architecture.md`, "Layering"). Two hub facts shape the port:

- **Models are raw SQL, not Knex queries.** Knex runs the migrations, but runtime code queries MariaDB through `mysql2` with `runQuery` (`apps/backend/src/db/mysqlRunQuery.ts`, `apps/backend/src/db/mysqlConnection.ts`), even though the layering diagram in `README.architecture.md` says `db/ (Knex)`. Every SQLAlchemy query in Kana Cards becomes a hand-written SQL string in a `*.models.ts` file.
- **Steam IDs come back as strings.** The pool sets `bigNumberStrings: true` (`apps/backend/src/db/mysqlConnection.ts`), so every `BIGINT` `steam_id` is a string in TypeScript.

| Kana Cards module | Target in the hub | Notes |
|---|---|---|
| `backend/opendota_client.py` | `apps/backend/src/games/dota/services/` (OpenDota client) | Through the shared `thirdPartyFetch` wrapper with a Redis circuit breaker for 429s, as `docs/third-party-fetch-resilience.md` requires for new vendors (`apps/backend/src/utils/third-party-fetch.ts`). |
| `backend/ingest.py` (league polling, live matches, parse retry, 15-minute rule) | `games/dota/services/` (poller and ingestion), `games/dota/models/` | Mirrors `apps/backend/src/games/pubg/services/pubg-poller.services.ts` and `pubg-ingestion.services.ts`; see [11.4](#114-background-work). |
| `backend/enrich.py` (hero stats, Anthropic bios) | `games/dota/services/` | Needs an Anthropic SDK and key in the hub; `apps/backend/package.json` has neither today. |
| `backend/schedule.py`, `backend/toornament.py` | Not ported | The hub's own Dota season, `Matches` and calendar replace the fixtures feed (phase 0). Toornament sync is dropped if the hub owns results. |
| `backend/dotabuff_league_logos.py` | `games/dota/utils/` | Or replaced by hub-managed league and team logos. |
| `backend/scoring.py` | `apps/backend/src/games/fantasy/dota/utils/` | A pure scoring module, like `apps/backend/src/games/fantasy/cs/utils/fantasy-scoring.utils.ts`. |
| `backend/card_points.py`, `backend/match_scoring.py` | `games/fantasy/dota/services/` | Stored per-match card points, like `apps/backend/src/games/fantasy/cs/services/fantasy-points.service.ts` writing `FantasyPointsLog`. |
| `backend/card_draw.py`, `backend/card_utils.py`, `backend/routers/cards.py` | `games/fantasy/dota/` (services, models, controllers) | Tokens, draws, rarities, modifiers, rerolls, team boosters, promo codes, token grant events. |
| `backend/weeks.py` | `games/fantasy/dota/services/` | Week locks, bench substitutions (#129), weekly report generation. |
| `backend/routers/leaderboard.py`, `backend/routers/weekly_summary.py`, `backend/routers/players.py` | `games/fantasy/dota/` (fantasy reads) and `games/dota/` (player and match reads) | Split by layer, as in [section 2](#which-kana-cards-part-belongs-to-which-hub-layer). |
| `backend/twitch.py` | `games/fantasy/dota/` with its own router on the public `/api/v2` surface | See [11.6](#116-twitch-extension). |
| `backend/routers/admin_ingest.py`, `admin_leagues.py`, `admin_matches.py`, `admin_players.py` | `games/dota/routes/dashboard/` | Dashboard routes, like `apps/backend/src/games/pubg/routes/dashboard/`. |
| `backend/routers/admin_weeks.py`, `admin_season.py`, `admin_notifications.py`, `admin_tags.py` | `games/fantasy/dota/routes/dashboard/` | Like `apps/backend/src/games/fantasy/cs/routes/dashboard/fantasy.routes.ts`. End Season becomes "start a new hub season" (see [11.3](#113-data-model-mapping)). |
| `backend/auth.py`, `backend/routers/auth.py`, `backend/sessions.py`, `backend/email_utils.py`, `backend/deps.py`, `backend/routers/profile.py` (account parts) | Hub core, not ported | Steam OpenID and JWT cookies (`apps/backend/src/routes/v1/auth.routes.ts`), `authenticateJWT` and `checkPermissions` (`apps/backend/src/middlewares/auth.middleware.ts`). |
| `backend/routers/admin_users.py` | Hub core | Staff grants scoped per organizer and game (`docs/auth/staff-permission-matrix.md`, `apps/backend/migrations/20260630120000_staff_scoped_authorization.ts`): a Dota admin is a grant with `game_id` 4. |
| `backend/routers/admin_backups.py`, `backend/database.py` backups | Hub ops, not ported | The hub's `eggo-db-backup` service (`docker-compose.prod.yml`, `conf/mariadb/backup.sh`). |
| `backend/routers/admin_demo.py`, `demo_clock` | Not ported | The hub has seeds and on-demand review environments (`docker-compose.ondemand.yml`, `deploy-ondemand` in `.gitlab-ci.yml`). |
| `backend/rate_limit.py` (slowapi) | Hub utilities | The hub has no general rate-limit package in `apps/backend/package.json`; per-route limits are custom (`apps/backend/src/utils/rate-limit-utils.ts`). Each Kana Cards limit needs an equivalent. |

**How the hub's CS2 fantasy is structured.** It is the template for `games/fantasy/dota/`:

| Part | Hub file | What it does |
|---|---|---|
| Player routes | `apps/backend/src/routes/v1/season.routes.ts` | `/:season_id/fantasy/...` routes (team create, my team, substitutions, roles, leaderboards, price history, private leagues), with `authenticateJWT` on writes. Mounted under `/seasons`, which is an internal route. |
| Admin routes | `apps/backend/src/games/fantasy/cs/routes/dashboard/fantasy.routes.ts`, mounted at `/dashboard/fantasy` in `apps/backend/src/routes/v1/dashboard/index.ts` | Seed player values, point history, scoring breakdowns, and recalculation per match game or forfeit; `checkPermissions` with fallback role `admin`, plus `enforceRequestScope()`. |
| Controllers | `apps/backend/src/games/fantasy/cs/controllers/fantasy.controllers.ts`, `fantasy-private-leagues.controllers.ts`, `controllers/dashboard/fantasy-admin.controllers.ts` | Request handling and validation. |
| Models | `apps/backend/src/games/fantasy/cs/models/fantasy-teams.models.ts`, `fantasy-players.models.ts`, `fantasy-leaderboard.models.ts`, `fantasy-private-leagues.models.ts`, `fantasy-season-status.models.ts` | Raw SQL through `runQuery`. |
| Services | `apps/backend/src/games/fantasy/cs/services/fantasy-points.service.ts`, `fantasy-value.service.ts` | Scoring per match game, forfeit scoring, reversal, player values. |
| Utils | `apps/backend/src/games/fantasy/cs/utils/fantasy-scoring.utils.ts` | Pure point formulas. |

**How it schedules scoring and recomputes.** There is no fantasy scheduler. Scoring is event-driven:

1. When a parsed demo arrives, the RabbitMQ consumer `apps/backend/src/games/cs/services/parsed-queue-consumer.ts` calls `calculateFantasyPointsForGame(match_game_id)`; a fantasy error is logged and does not fail the demo import.
2. Forfeits are scored from the FACEIT webhook handler `apps/backend/src/games/cs/services/faceit-webhook/handlers/match-status-finished-championship.handler.ts` (`awardForfeitFantasyPoints`).
3. `calculateFantasyPointsForGame` runs in one transaction, locks the match row (`FOR UPDATE`), scores only regular-season (stage 1) matches whose status is `FINISHED`, writes one `FantasyPointsLog` row per team player and match game, and refreshes the leaderboard (`apps/backend/src/games/fantasy/cs/services/fantasy-points.service.ts`).
4. `refreshFantasyLeaderboard` deletes and rebuilds the `FantasyLeaderboard` snapshot for one season and league after any points change, under a `SeasonLeagues` row lock (`apps/backend/src/games/fantasy/cs/models/fantasy-leaderboard.models.ts`).
5. Admins recompute one match game or forfeit by hand through the dashboard routes above.

This is the same shape as Kana Cards' stored card points (#141): points written per match at scoring time and summed by readers. A Dota port would trigger scoring from the Dota ingestion job instead of a demo consumer, and keep Kana Cards' week-based rules (locks, bench substitutions) on top.

**Routes.** The hub has three API surfaces (`apps/backend/src/routes/index.ts`):

| Surface | Reached by | Dota fantasy routes |
|---|---|---|
| `/api/v2/internal` | Only the Next.js frontend (BFF). Traefik sends `/api/v1` and `/api/v2` to the backend but excludes `/api/v2/internal` (`docker-compose.prod.yml`). | All player and admin fantasy routes: `/seasons/:season_id/dota-fantasy/...` or game-neutral `/seasons/:season_id/fantasy/...` branched by game, and `/dashboard/dota/...`. |
| `/api/v2` (public) | Browsers, bots and services directly: health, `/auth`, Discord bot, FACEIT webhook and a few read subsets (`mountExternalOnlyRoutes`). | Only the Twitch EBS, because the extension runs on Twitch's CDN and calls the backend directly. |
| `/api/v1` (legacy) | Both surfaces, "fully public until deprecated" (`README.api.md`). | None; new routes should not depend on it. |

**Frontend pages.**

| Page | Hub location | Notes |
|---|---|---|
| Player-facing fantasy | `apps/frontend/src/app/(main)/(content-container)/seasons/[season]/fantasy/` | `getSeasonPageLinks` shows the Fantasy and Fantasy leaderboard links when the game's `caps.fantasy` is true (`apps/frontend/src/lib/season-utils.ts`). But `fantasy/page.tsx` renders the CS2 `FantasyLeague` component for every game, so Dota needs either a branch on the season's game (as the backend calendar does in `apps/backend/src/models/calendar.models.ts`) or a separate `seasons/[season]/dota-fantasy/` route with its own link. |
| Registry entry | `apps/frontend/src/lib/games/registry.ts` | `dota`: `gameId` 4, `appId` 570, `matchModel` `h2h`, `caps.fantasy: true`. `GameCapabilities` has no field that says which fantasy a game uses, and `statsKind` allows only `round` or `placement`, so the registry types need a new value or capability (for example a fantasy kind of budget or cards). |
| Admin | `apps/frontend/src/app/(admin)/[organizer]/dashboard/dota/...` | Like `dashboard/cs2/fantasy/page.tsx` and the `dashboard/pubg/` pages (`ingestions`, `gamedays`, `scoring-rules`). |

### 11.3 Data model mapping

**Hub conventions** for every new table (`apps/backend/migrations/README.md`, `apps/backend/.cursor/rules/migrations.mdc`, `README.database.md`):

- Knex migrations with `up` and `down`, self-contained (no imports from `apps/backend/src` or `@eggosystem/*`; constants inlined).
- PascalCase plural table names (`FantasyTeams`, `PubgMatches`), snake_case columns, a table comment (`ALTER TABLE ... COMMENT = '...'`) on every new table.
- Players keyed by `steam_id` `BIGINT` (Steam64), as in `FantasyTeams` and `FantasyTeamPlayers` (`apps/backend/migrations/20251124000001_create_fantasy_league_tables.ts`).
- Integrity in the database: foreign keys (mostly `ON DELETE CASCADE`), named `CHECK` constraints such as `chk_pubgsessionmap_rotation` (`apps/backend/migrations/20260629130000_create_pubg_gameday_tables.ts`), and triggers for cross-row rules (`README.database.md`, "Business Rules (Enforced by Triggers)").
- Timestamps as `timestamp` columns, not Unix integers (`Matches.start_timestamp`, `apps/backend/migrations/20260120214311_convert_match_times_to_timestamps.ts`).
- After a schema change: update `README.database.md`, the types in `@eggosystem/types` with `createMockX` factories (`README.architecture.md`, "Shared Packages").
- Table names are domain-owned: `domain-boundaries.test.ts` forbids `Pubg*` names in `games/cs/` and `MatchGames`, `CSSeasonSettings` and `PlayerStats` in `games/pubg/` (`apps/backend/src/games/domain-boundaries.test.ts`). Dota tables should get a `Dota` prefix and Dota fantasy tables a `FantasyDota` prefix, because the unprefixed `Fantasy*` tables belong to the CS2 fantasy.

**How the hub models matches, and whether Dota fits.** `Matches` is the scheduled series (season, league, stage, `best_of`, status, `start_timestamp`, `round`), with teams in `MatchTeams`; `MatchGames` holds the individual games (`apps/backend/migrations/20250127080330_database_schema.ts`). Dota series fit `Matches` and `MatchTeams` as they are, so the hub schedule and calendar work for Dota. Dota games do not fit `MatchGames`: it requires a CS2 map (`map_id` `NOT NULL`, foreign key to `Maps`) and a unique demo file name (`demofile` `NOT NULL`, unique since `apps/backend/migrations/20250804152819_add_uniqueness_in_match_games.ts`), and the boundary test reserves the name for CS. PUBG solved the same problem with its own tables (`PubgMatches`, `PubgMatchPlayerStats` in `apps/backend/migrations/20260629120100_create_pubg_match_domain_tables.ts`). Dota should do the same: a `DotaMatchGames` table keyed by the OpenDota match ID, with a nullable reference to the `Matches` series it belongs to.

| Kana Cards table (`backend/models.py`) | Hub target | Kind |
|---|---|---|
| `users` | `Accounts` plus `LinkedAccounts` with provider `steam` (`apps/backend/migrations/20250415015337_add_accounts_tables.ts`); `is_admin` becomes a staff grant; `tokens` moves to a per-season `FantasyDotaTokenBalances` | Existing hub tables, plus one new |
| `users.twitch_user_id` | `LinkedAccounts` with a new `twitch` provider; the enum is `steam`, `discord`, `pubg` today (`apps/backend/migrations/20260615120000_add_pubg_provider_to_linked_accounts.ts`) | Existing table, enum migration |
| `players` (OpenDota account ID, name, avatar) | `SteamPlayers` (`steam_id` = Steam32 + offset, `nickname`; `apps/backend/migrations/20250127080330_database_schema.ts`); fantasy pool flag (`is_active`) in a new `FantasyDotaPlayerPool` | Existing, plus one new |
| `teams` (OpenDota team ID, name, logo) | `TeamIdentities` and `TeamGameParticipations` (name and logo per organizer and game; `apps/backend/migrations/20260723180100_rename_teams_to_team_identities.ts`, `apps/backend/migrations/20260721120000_team_game_participations.ts`); the OpenDota team ID in a new `DotaTeamExternalIds`, since neither table has an external ID column | Existing, plus one new |
| `leagues` (monitored OpenDota leagues) | `SeasonLeagueExternalIds` rows (`season_id`, `league_id`, `stage_id`, `external_id`, free-text `type`, for example `opendota`; `apps/backend/migrations/20250704141851_season_league_external_id_table.ts`) | Existing hub table |
| `matches` (one OpenDota game) | New `DotaMatchGames`, referencing `Matches` for the series | New |
| `player_match_stats` | New `DotaPlayerMatchStats` | New |
| `match_bans`, `live_matches`, `player_profiles` | New `DotaMatchBans`, `DotaLiveMatches` (or Redis keys), `DotaPlayerProfiles` | New |
| `toornament_sync_log` | Dropped | — |
| `cards`, `card_modifiers` | New `FantasyDotaCards`, `FantasyDotaCardModifiers` (owner `steam_id`, `season_id`) | New |
| `weeks`, `weekly_roster_entries` | New `FantasyDotaWeeks` (per `season_id`), `FantasyDotaRosterEntries` | New |
| `card_match_points`, `scoring_state`, `weights` | New `FantasyDotaCardMatchPoints`, `FantasyDotaScoringWeights`; optionally a `FantasyDotaLeaderboard` snapshot like `FantasyLeaderboard` | New |
| `weekly_summaries`, `weekly_summary_reveals`, `weekly_summary_seen` | New `FantasyDotaWeeklySummaries` and two companion tables | New |
| `season_archive` | Mostly unnecessary: hub data is per `Seasons` row, so past seasons stay queryable; imported archives go to a `FantasyDotaSeasonArchive` | New (import only) |
| `promo_codes`, `code_redemptions`, `token_grant_events`, `token_grant_claims` | New `FantasyDota*` tables | New |
| `twitch_link_codes`, `twitch_presence`, `twitch_mvp`, `twitch_token_drops` | New `FantasyDotaTwitch*` tables | New |
| `notifications`, `notification_dismissals`, `tag_definitions`, `user_tags` | New `FantasyDota*` tables, unless the hub team prefers hub-wide equivalents (hub roles already include `caster`) | New |
| `audit_logs` | `AuditLog` (`apps/backend/migrations/20250512035018_audit_logging.ts`) with `audit-log.middleware.ts` | Existing hub table |
| `user_sessions`, `password_reset_tokens`, `demo_clock` | Not ported | — |

So about 25 new tables, against 37 in Kana Cards. Rules Kana Cards keeps in Python become database rules where the hub would expect them: for example `CHECK` constraints on modifier ranges and bench order, unique keys on (week, card), and row locks (`SELECT ... FOR UPDATE`, `apps/backend/src/db/row-lock-transaction.ts`) for the roster-limit race that Kana Cards fixed in #125. Points should be stored as `DOUBLE`, not as the integers `FantasyPointsLog` uses, so that per-match card points match Kana Cards' Python floats before display rounding (`display_points` in `backend/scoring.py`).

### 11.4 Background work

Kana Cards runs four daemon threads (five since #161, when `STEAM_API_KEY` is set), started in `_start_background_threads` in `backend/main.py`. The hub's periodic work runs inside the one `eggo-backend` process (`docker-compose.prod.yml`): `node-cron` schedules plus BullMQ queues on Redis, started from `apps/backend/server.ts`. RabbitMQ consumers are for pushed events (parsed demos), not polling.

| Kana Cards thread | What it does | Hub equivalent |
|---|---|---|
| `_live_poll_loop` | Since #161: every `LIVE_POLL_INTERVAL` (60 s) asks Steam's `GetLiveLeagueGames` for live games of the monitored leagues and stores them in `live_matches` (needs `STEAM_API_KEY`). | The same `node-cron` + BullMQ pattern, as a separate light queue so ingestion never delays it. |
| `_ingest_poll_loop` | Polls monitored OpenDota leagues, reads live state from `live_matches`, ingests finished games under `INGEST_LOCK`, then syncs Toornament. The interval adapts: `INGEST_LIVE_MATCH_POLL_INTERVAL` (30 s) while a match is live or just ended, `INGEST_LIVE_POLL_INTERVAL` (120 s) during an active week, otherwise `INGEST_POLL_INTERVAL` (900 s). | The PUBG pattern in `apps/backend/src/games/pubg/services/pubg-poller.services.ts`: a `node-cron` discovery task (`*/2 * * * *`) enqueues jobs on a BullMQ queue whose worker has concurrency 1 and a rate limiter, with attempts and exponential backoff. The FACEIT match sync uses `node-cron` the same way (`apps/backend/src/games/cs/services/faceit-match-sync.services.ts`). Live-aware intervals need a design choice: a cron tick every 30 s that skips until a Redis "next due" key expires, or a self-rescheduling BullMQ job with a computed delay. Concurrency 1 replaces `INGEST_LOCK`. Fantasy scoring is triggered at the end of each ingestion job, as `parsed-queue-consumer.ts` does for CS2. |
| `_week_maintenance_loop` | Every 300 s: `auto_lock_weeks`, `due_substitutions`, `generate_weekly_summaries` (`backend/weeks.py`), and once a day expired session cleanup. | A `node-cron` task (or a BullMQ repeatable job) in `games/fantasy/dota/`. Session cleanup is not needed: the hub's JWT cookies carry no server-side session rows. |
| `_profile_enrichment_loop` | Every 300 s, with a 300 s timeout: `run_profile_enrichment` (`backend/enrich.py`): hero stats from OpenDota and bios from the Anthropic API (`ANTHROPIC_API_KEY`). | A low-priority BullMQ queue with its own limiter, the Anthropic SDK and key added to the hub, and an Anthropic mock in `packages/shared-msw/` (third-party stubs live there, not in services; hub `CLAUDE.md`). |
| `_backup_loop` | Every `DB_BACKUP_INTERVAL_HOURS` (24): SQLite snapshot and pruning (`backup_sqlite_db` in `backend/database.py`). | Not ported. The `eggo-db-backup` container runs `conf/mariadb/backup.sh`: a `mariadb-dump --all-databases` at 04:00 UTC, gzipped, deleting dumps older than 7 days (`docker-compose.prod.yml`). |

**Ops the hub provides.** OpenTelemetry export to Grafana Alloy (`OTEL_*` variables on `eggo-backend` in `docker-compose.prod.yml`), bull-monitor for queues, health endpoints for the database and RabbitMQ (`mountHealthRoutes` in `apps/backend/src/routes/index.ts`), and staging and on-demand environments (`.gitlab-ci.yml`). Async subsystems are skipped in `test` and `e2e` mode and their failures are non-fatal (`README.architecture.md`, "Async Subsystems"), which matches Kana Cards' `BACKGROUND_TASKS_ENABLED` guard. One caution: workers share the web process, so a misbehaving Dota job competes with every hub request.

### 11.5 Frontend

The hub frontend is Next.js App Router with React, Tailwind v4 and shadcn/Radix components; data through SWR and server components; forms with `react-hook-form` and Zod (`README.architecture.md`, "Frontend Architecture"). Every Kana Cards view is rebuilt; none of the vanilla JS carries over.

| Kana Cards surface | Kana Cards source | In the hub | Size |
|---|---|---|---|
| My Team: active and bench slots with HTML5 drag-and-drop, keyboard alternative, week locks | `frontend/app-roster.js`, `markdown/ui_description/my-team.md` | `apps/frontend/package.json` has no drag-and-drop library, so either one is added or native drag events are wrapped in React; the keyboard path must be rebuilt for accessibility. | L |
| Cards: token draws with the reveal animation (`DRAW_REVEAL_MIN_MS`, burst classes) | `frontend/app-cards.js` | `framer-motion` is already a dependency (`apps/frontend/package.json`), and a CS2 flip-card component exists (`apps/frontend/src/components/fantasy/FantasyPlayerFlipCard.tsx`). | M |
| Card images | Rendered as PNGs on the server with Pillow (`generate_card_image` in `backend/image.py`: art, team logo, stickers, modifier lines, fonts), served by `backend/routers/cards.py` | The hub has no server image library (no `sharp` or `canvas` in `apps/backend/package.json` or `apps/frontend/package.json`). It does generate PNGs with `ImageResponse` from `next/og` for Open Graph images (`apps/frontend/src/app/(main)/(content-container)/matches/[match_id]/opengraph-image.utils.tsx`). Two routes: render cards as React components in the page (simplest, no PNG), and use an `ImageResponse` route only where a PNG is needed (sharing). `ImageResponse` supports a subset of CSS (flexbox layout), so the card layout must be redrawn, not translated. | M |
| Players, Leaderboards, Weekly Report, Profile, How to Play | `frontend/app-players.js`, `app-leaderboard.js`, `app-weekly-summary.js`, `app-profile.js`, `frontend/index.html` | React pages under the Dota season; the Profile shrinks to fantasy settings, because the account lives in the hub. | L |
| Guided tour (#144) | `frontend/app-tour.js` | No tour library in `apps/frontend/package.json`; rebuilt as a component or dropped. | S |
| Schedule and Teams | `backend/schedule.py`, `markdown/ui_description/schedule.md`, `markdown/ui_description/teams.md` | Replaced by the hub's own season pages (schedule, calendar, standings) from phase 0. | S |
| Admin panels (ingest, leagues, matches, players, weeks, season, notifications, tags, users, backups, demo) | `frontend/app-admin*.js` | Dashboard pages under `apps/frontend/src/app/(admin)/[organizer]/dashboard/dota/`; users, backups and demo are covered by hub tools. | L |

The visual alignment planned under Option C ([section 7](#7-kana-cards-next-to-the-cs2-fantasy)) would make the design carry over, though not the code.

### 11.6 Twitch extension

| Item | Today (`backend/twitch.py`, `twitch-extension/`, `markdown/features/core/twitch-extension.md`) | Under Option A |
|---|---|---|
| EBS routes | On `kana-cards.com`: the panel game routes (#157) `/twitch/join`, `/twitch/me`, `/twitch/panel`, `/twitch/teams`, `/twitch/draw`, `/twitch/draw/booster/{team_id}`, `/twitch/roster/*`, `/twitch/leave`, plus `/twitch/heartbeat`, `/twitch/matches/current`, `/twitch/mvp`; and the website's Twitch connection routes (#160, session cookie) `/auth/twitch/start`, `/auth/twitch/callback`, `/twitch/connection`, `/twitch/merge/confirm`, `/twitch/disconnect`. The link-code routes and `/twitch/status` were retired in #160. | A Twitch router in `games/fantasy/dota/`, mounted on the public `/api/v2` surface, because the extension calls the backend directly from Twitch's CDN and `/api/v2/internal` is reachable only through the frontend (`apps/backend/src/routes/index.ts`, `docker-compose.prod.yml`). The global `cors({ origin: true })` in `apps/backend/src/app.ts` admits the extension origin; the stricter `corsMiddleware` (`apps/backend/src/middlewares/cors.middleware.ts`) would reject it, so the Twitch router must not use it. |
| JWT verification | Twitch extension JWTs verified with the base64 secret `TWITCH_EXTENSION_SECRET`, client ID `TWITCH_EXTENSION_CLIENT_ID`. | `jsonwebtoken` is already a hub dependency (`apps/backend/package.json`); the secrets become hub CI/CD variables passed to `eggo-backend` in `docker-compose.prod.yml`. |
| Chat and PubSub | EBS-signed calls to `https://api.twitch.tv/helix/extensions/chat` and `https://api.twitch.tv/helix/extensions/pubsub` (`TWITCH_EXTENSION_VERSION` for chat). | Ported through `thirdPartyFetch`; Twitch mocks added to `packages/shared-msw/`. |
| Viewer links | `users.twitch_user_id` (opaque id) for soft accounts and recognised website accounts, and `users.twitch_account_id` (real Twitch id) from the identity share or Twitch sign-in on Profile (#160; link codes retired). | `LinkedAccounts` with a new `twitch` provider ([11.3](#113-data-model-mapping)); links migrated at cutover. |
| EBS URL | Set in the extension's global configuration by `twitch-extension/set-ebs-url.sh`; the script states that a URL change needs no rebuild or re-upload. | Can point anywhere on an allow-listed domain without review. |
| URL fetching allowlist | `https://kana-cards.com` (per extension version, Capabilities). | Moving to the hub's domain needs a new extension version and a Twitch review. **Mitigation:** keep `kana-cards.com` as a reverse proxy to the hub's EBS routes at cutover, so the allowlist entry stays valid and the extension keeps working while the new version is in review; drop the proxy once the new version is live. |

### 11.7 Testing and quality gates

**Kana Cards' tests do not carry over as code.** About 1 500 collected pytest tests in `backend/tests/` (84 files) fall into four groups:

| Group | Examples | What to do |
|---|---|---|
| Scoring, card points, substitutions, draws, week locks | `test_scoring_pipeline_parity.py`, `test_mvp_card_scoring_parity.py`, `test_issue_141_stored_card_points.py`, `test_issue_129_automatic_bench_substitution.py` | Port as Jest unit tests next to the pure modules (like `apps/backend/src/games/fantasy/cs/utils/fantasy-scoring.utils.test.ts`), plus a **golden parity suite**: export one full Kana Cards season (stats in, stored card points out) as fixtures and assert the hub computes the same per-match points. Highest value. |
| Endpoints, permissions, rate limits, security reviews | `test_issue_135_security_review_fixes.py`, `test_issue_121_rate_limiting.py` | Rewrite against hub conventions: mocked `runQuery` unit tests or `*.integration.test.ts` on real MariaDB (`apps/backend/.cursor/rules/testing.mdc`). |
| Login, sessions, passwords, SMTP | `test_auth.py`, `test_issue_117_longer_sessions.py`, `test_issue_123_password_reset_token_flow.py` | Drop; hub core covers login. |
| Document and plan checks | `test_issue_108_kana_hub_integration_feasibility.py` and similar | Drop; the hub does not test its docs this way. |

User flows (My Team, a draw, the leaderboard, the Twitch panel) get Playwright specs in `apps/frontend/src/e2e/`.

**Hub quality gates** (`.gitlab-ci.yml`), all required on merge requests:

| Gate | What it runs |
|---|---|
| `typecheck`, `lint-all`, `format:check` | `turbo typecheck`; `biome check .` in the backend (`apps/backend/package.json`) and ESLint in the frontend (`apps/frontend/package.json`); Biome and Prettier formatting (`biome.json`, root `package.json`). |
| `knip` | Unused files, exports and dependencies (`knip.json`); dead code from a partial port fails the build. |
| `audit`, `secrets_scan` | `pnpm audit`, secrets scanning. |
| `test:backend` | Jest in 4 shards against a fresh MariaDB, after seeding and migrating; coverage thresholds of 65 % branches, 50 % functions, 60 % lines and statements (`apps/backend/jest.config.mjs`, `test:backend:coverage-merge`). |
| `test:frontend` | Frontend Jest suites. |
| `test-e2e:frontend` | Playwright, only on the `development` to `main` release merge request (`.dev-to-main-mr`). |
| Domain boundaries | `apps/backend/src/games/domain-boundaries.test.ts` checks only `cs` and `pubg` today; a `dota` domain must be added to it, with its own table-name pattern. |

### 11.8 Effort and phased migration

**Assumptions.** One or two hobby developers working evenings, about 8–10 hours a week each, who know Kana Cards but are new to the hub's stack. A **person-week** is 40 hours of focused work, so one developer needs about four to five calendar weeks per person-week. Estimates are for conventional development; both projects use AI agent pipelines (this repository's `/develop`, the hub's `.cursor/agents/dag-orchestration.md`), which can shorten coding but not review, parity checking or the season-break windows. Even at half the estimate, Option A stays the largest option and keeps the same phases. Each area includes its unit tests. Sizes: **S** up to 1 person-week, **M** 1–3, **L** 3–6, **XL** more than 6.

| Area | Size | Person-weeks | Work |
|---|---|---|---|
| Dota season, teams and schedule in the hub (phase 0) | M | 2–4 | `dota` registry entry and capability types, Dota seasons and leagues, team participations, calendar branch. Hub team work, and the same prerequisite as Option C. |
| Dota ingestion in `games/dota/` | L | 4–6 | OpenDota client, poller and BullMQ queue with live-aware timing, `DotaMatchGames`, stats, bans and live tables, parse retry, admin ingest and match tools, OpenDota mocks. |
| Profile enrichment | M | 1–2 | Hero stats and Anthropic bios as a queue job. |
| Fantasy schema | M | 2–3 | About 25 `FantasyDota*` and `Dota*` migrations with comments, constraints, types and mock factories, `README.database.md`. |
| Cards, tokens and draws | L | 3–4 | Draws, rarities, modifiers, rerolls, team boosters, promo codes, token grant events. |
| Weeks, rosters, scoring and leaderboards | XL | 5–7 | Week locks, bench substitutions, scoring, stored per-match card points, MVP, weekly and season leaderboards, End Season as a new hub season. The parity-critical core. |
| Weekly Report | M | 2–3 | Summaries, reveals, seen state, substitutions-pending note. |
| Background jobs | M | 1–2 | Week maintenance and enrichment schedules, graceful shutdown hooks in `apps/backend/server.ts`. |
| Admin dashboard (backend and pages) | L | 4–6 | Weeks, season, matches, players, leagues, notifications, tags, token grants under `dashboard/dota/`. |
| Player-facing frontend | XL | 8–12 | My Team with drag-and-drop and bench, Cards with the draw reveal, Players, Leaderboards, Weekly Report, Profile, How to Play, guided tour. |
| Card rendering | M | 2–3 | Card component and an `ImageResponse` PNG route to replace `backend/image.py`. |
| Twitch EBS | M | 2–3 | Router on `/api/v2`, JWT verification, chat and PubSub, `twitch` provider, extension version and review. |
| Login and permissions wiring | S | 0.5–1 | `authenticateJWT`, staff grants for Dota admins. |
| Data migration and cutover | M | 2–3 | Export from SQLite, import of accounts, season history, tags and Twitch links into MariaDB, rehearsal on staging. |
| Parity suite and E2E | L | 3–5 | Golden season fixtures, Playwright specs. |
| Hub onboarding and review | M | 2–4 | Learning the stack and conventions, review cycles, docs. |
| **Total** | **XL** | **43.5–68** (about 45–70) | Two developers together give 0.4–0.5 of a full-time person: about **90–170 calendar weeks** (roughly 1.7 to 3.3 years). One developer alone: about twice that. |

For comparison, the recommended Option C with Steam-only login (B1) is about 5–8 person-weeks on the same scale.

**Critical path.** Phase 0 Dota season in the hub (hub team, timing outside Kana Cards' control), then Dota ingestion in the hub, then scoring and stored card points with proven parity, then the My Team and draw frontend (the largest single item), then a rehearsed data import, then the cutover at a season break. The Twitch review is off the critical path if `kana-cards.com` proxies the EBS during review ([11.6](#116-twitch-extension)).

**Phased migration plan.** Each phase goes live at a break between seasons, as decided for all integration work ([Timing](#timing-between-seasons)). Assumption to confirm with the product owner: two Dota seasons a year, so two season breaks a year.

| Phase | What goes live | Kana Cards during the phase | Season break |
|---|---|---|---|
| 0 — Dota season in the hub | Dota registry entry, seasons, teams and schedule in the hub; Kana Cards reads the schedule from it (Option C). | Unchanged; switches to Steam-only login (B1). | Break 1 (shared with Option C) |
| 1 — `games/dota/` ingestion | The hub ingests OpenDota for the Dota season in shadow mode; match and stat counts are compared with Kana Cards'. Player and match stats pages in the hub. | Still the source of truth for fantasy. | Break 2 (shadow ingestion has no player impact, so it can also start mid-season) |
| 2 — Fantasy core, read-only | Scoring and stored card points computed in the hub from hub data and checked against Kana Cards every week (parity suite on live data); read-only fantasy views. | Source of truth; its card points are the reference. | Break 3 |
| 3 — Full fantasy and Twitch | Cards, draws, rosters, weeks, Weekly Report, admin and the Twitch EBS in the hub. At the break: accounts, history, tags and Twitch links imported; the season starts in the hub. | Read-only, then redirected; `kana-cards.com` proxies the EBS. | Break 4 at the earliest; with the estimated effort, break 4 to 7 |
| 4 — Retire Kana Cards | After one season on the hub: new extension version live, proxy removed, SQLite archived, domain redirected. | Retired. | One break after phase 3: break 5 to 8 |

So Option A takes **at least five season breaks**, and with the effort above realistically **five to eight** (about 2.5 to 4 years at two breaks a year). Players see no benefit until phase 3.

### 11.9 Risks and gains

**Risks and mitigations specific to Option A:**

| Risk | Why it matters | Mitigation |
|---|---|---|
| Feature parity | Kana Cards keeps changing while the port runs for years; every new feature is built twice or the port falls behind. | Freeze Kana Cards features for the season before cutover; a parity checklist from `markdown/stories/` signed off feature by feature. |
| Scoring parity | A rewritten scoring path that differs by a fraction of a point changes rankings. | The golden parity suite (11.7) and phase 2's weekly comparison on live data; store points as `DOUBLE` (11.3). |
| Ownership and review in someone else's repository | Kana Cards developers would need hub maintainers' review for every change, under hub conventions (`.cursor/rules/`, Biome, knip, coverage thresholds). | A named owner of `games/fantasy/dota/` agreed with the hub team before phase 1 (question 8 in [section 9](#9-questions-for-the-hub-team)). |
| Coupling to the hub's release cadence | Production deploys are manual, from `main`, after staging (`deploy-prod` in `.gitlab-ci.yml`), and E2E runs only on the release merge request. A mid-season fantasy hotfix waits for a hub release. | Agree a hotfix path; ship risky changes behind configuration. |
| Scoring performance in MariaDB | Low. The hub already writes per-match points and keeps a leaderboard snapshot (`refreshFantasyLeaderboard`), and Kana Cards' stored card points have the same shape. | Indexes on (card, match) and (season, week); a leaderboard snapshot table if reads grow. |
| Shared process | Dota jobs run inside `eggo-backend`, so a runaway job slows the whole hub. | BullMQ limiter and concurrency 1, `thirdPartyFetch` timeouts and circuit breaker. |
| Data migration and account claim at the season break | Users without a Steam link cannot be mapped to hub accounts. | Do B1 first (the recommendation): every Kana Cards account then already has a verified Steam64 ID, and the import needs no claim step. Rehearse the import on a staging copy; cards and rosters are reset by the season break anyway. |
| Twitch review downtime | A new extension version can wait in review. | `kana-cards.com` as an EBS proxy until the new version is live (11.6). |
| Hub prerequisites | Phases 0 and 1 need the hub team to want Dota seasons and Dota match data (questions 1 and 3). | Nothing starts before both answers are yes. |
| Running two systems | During phases 1 to 3 both systems run, so both are maintained. | Keep the phases short; no new Kana Cards features after phase 2 starts. |

**What Option A gains:**

- **One codebase, one site, one login.** The fantasy sits on the Dota season's pages next to the schedule and standings, and reads the hub's teams, rosters (`SeasonTeamPlayers`) and matches directly: no fixtures adapter, no team-name matching.
- **Hub operations.** Daily MariaDB dumps with 7-day retention (`conf/mariadb/backup.sh`), OpenTelemetry to Grafana Alloy, bull-monitor, health endpoints, staging and on-demand environments, dependency audit and secrets scanning in CI (`.gitlab-ci.yml`).
- **No login code.** No passwords, SMTP, sessions, lockouts or reauth in Kana Cards (see [What Steam login removes](#what-steam-login-removes-from-kana-cards)); email, if ever needed, goes through the hub's BullMQ email queue (`apps/backend/src/utils/bullmq.utils.ts`).
- **Shared admin and permissions.** Staff grants scoped per organizer and game (`docs/auth/staff-permission-matrix.md`) and the hub's `AuditLog`.
- **Discord integrations.** The hub's Discord bot and per-organizer, per-game Discord configuration (`OrganizerDiscordConfigs`, `README.database.md`; `apps/backend/src/routes/v1/discord-bot.routes.ts`) could post the Weekly Report or MVP drops.
- **Seasons as data.** Every hub table is keyed by season, so End Season becomes "start the next hub season" and past seasons stay queryable instead of being archived and deleted.

### 11.10 Decision criteria

Option A becomes the right choice only when all of these hold:

1. **The hub runs Dota.** The Dota season, teams and schedule have been in the hub for at least one full season (phase 0 done).
2. **The hub team wants it.** The hub team wants Dota match data in `games/dota/` and agrees to host and review `games/fantasy/dota/`, with a named owner (questions 3 and 8 in [section 9](#9-questions-for-the-hub-team)).
3. **There is capacity for years, not sprints.** About 45–70 person-weeks are committed: two developers for roughly two to three years of evenings, or hub developers sharing the work.
4. **Kana Cards' rules are stable.** No major game-rule changes are planned for the seasons the port spans, so parity is a fixed target.
5. **Two sites cost more than the port.** For example: hosting or operating `kana-cards.com` becomes a burden, players report friction between the two sites despite the shared Steam identity, or a wanted feature needs hub data that Option C's API exchange cannot provide (fantasy on match pages, Discord announcements, shared rosters).

If any of 1 to 3 is missing, Option A cannot start; if 4 or 5 is missing, it does not pay off.

### 11.11 Does the deep dive change the recommendation?

**No.** The recommendation stays: Option C with Steam-only login (B1) in the same between-seasons release. The deeper analysis makes the case against starting Option A now stronger:

1. **Cost.** About 45–70 person-weeks against about 5–8 for C plus B1: roughly eight times the work at the midpoints, for a similar "single site" result.
2. **Time to value.** Players see nothing until phase 3, at least four season breaks away; C and B1 go live at the next break.
3. **Dependency.** Phases 0 and 1 depend on the hub team's plans and capacity, which Kana Cards does not control.
4. **Risk.** Scoring parity, review in another team's repository and the hub's release cadence are new risks that C does not carry.

**C now, A as a possible later target.** C and B1 are not a detour from A; they are its first steps. Phase 0 (the Dota season in the hub) is C's prerequisite too. B1 gives every account a verified Steam64 ID, which removes the claim step from an A cutover. The visual alignment carries the design over. So the path is: do C and B1 at the next season break, then re-check the [decision criteria](#1110-decision-criteria) at each later season break. Start phase 1 only when criteria 1 to 3 are met.
