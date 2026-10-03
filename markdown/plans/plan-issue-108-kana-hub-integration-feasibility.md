# Plan: Kana Hub Integration Feasibility

## Context
Kana Hub (https://hub.kanaliiga.fi/, source at https://gitlab.com/kanaliiga_public/kanahub/eggosystem) is Kanaliiga's central site for its game leagues. Issue #108 asks whether Kana Cards' key features could be built into the hub, and above all what the **architectural blockers** are.

The deliverable is a **feasibility and decision document**, not code. It follows the model of `reference/frontend-framework-evaluation.md`.

**Preliminary findings (2026-10-02, from the public repository, default branch `development`):**

| Area | Kana Hub (Eggosystem) | Kana Cards | Gap |
|---|---|---|---|
| Stack | TypeScript monorepo (pnpm + Turborepo): Express 5 + Knex backend, Next.js 16 / React 19 frontend, Tailwind + shadcn | Python FastAPI + SQLAlchemy, vanilla JS + Alpine | A port is a full rewrite, no shared code |
| Database | MariaDB; business rules in triggers and SQL functions; Knex migrations | SQLite with WAL; Python migration registry | Schema and rule placement differ |
| Identity | Steam OpenID → RSA-signed JWT access and refresh cookies; Steam ID as the primary player key; Discord linking | Username/password with server-side sessions (#117); optional OpenDota player ID; Twitch link | A bridge exists: OpenDota account id (Steam32) + 76561197960265728 = Steam64 |
| Games | CS2 (demo parser, KanaRating) and PUBG (Krafton ingestion). `Games` has a Dota 2 row (id 4, app 570), but no Dota match ingestion was found | Dota 2 only, via OpenDota league polling | Dota match data would have to be added to the hub |
| League model | Organizer-run seasons, leagues (divisions), team registration and the Sortter, matches and match games | Monitored OpenDota leagues; teams and players from match data; admin-defined weeks | Kanaliiga Dota teams and matches may not exist in the hub |
| Existing fantasy | A separate CS2 fantasy league exists (a different product, not competing; see Clarifications): `FantasyTeams` (budget of 1 000 000), `FantasyTeamPlayers` with CS2 roles (main_awp, entry_fragger…), `FantasyPlayerValues` with tiers, a points log, forfeit points, a leaderboard snapshot, and private leagues with invite codes | Card collection: token draws, rarities, modifiers, weekly rosters with a bench, MVP bonus, stored per-match points | No overlap to resolve: Kana Cards would be the Dota fantasy, next to the CS2 one |
| Background work | BullMQ (Redis), RabbitMQ consumers | In-process threads (ingest, week lock, enrichment, backups) | Jobs would be rewritten as queues |
| Twitch | No Twitch extension found | Twitch extension with an EBS at kana-cards.com; MVP drops; chat | The extension would need a new EBS host and a new Twitch review |
| Licence | GPL-3.0 | No licence file | Not a concern: both are hobby projects (see Clarifications) |
| Embedding | `(embed)` route group (calendar) and API-key service auth | Standalone site | A lighter integration path may exist |

**Clarifications from the product owner (2026-10-02):**
- **The CS2 fantasy league is a separate implementation, not a competing product.** Kana Cards would be the Dota fantasy game. The question is integration, not which fantasy design wins.
- **Kanaliiga runs Dota seasons, but nothing Dota is in the hub yet.** The Dota schedule is likely to move to the hub eventually, which gives real value to a single site for the tournament: schedule, teams, results and fantasy in one place.
- **Licensing is not a concern;** both are hobby projects.
- **Implementation would happen between seasons,** so live rosters, tokens and weekly locks aren't disrupted.
- **Kana Cards' visuals would be aligned with the hub's standards,** so the Dota fantasy feels like part of the same site.

**Further input from the product owner (2026-10-02):**
- **The linked-account count does not matter.** The architectural issues are the same however many users have linked IDs, so the count is not a deliverable.
- **Explain the hub's per-game structure and align Dota with it.** The hub is multi-organizer and multi-game (frontend game registry, per-game backend domains such as `games/cs/` and `games/pubg/`, fantasy namespaced per game in `games/fantasy/cs/`). The document should say where Dota fits and which Kana Cards part maps to which hub layer.
- **Steam login simplifies Kana Cards.** Moving into the hub forces Steam login, which removes the need for SMTP and much of Kana Cards' login handling. Option B could go Steam-only for most of the same simplification without moving; the document lists what becomes removable.

**Follow-up request from the product owner (2026-10-02):**
- **Evaluate Option A (full port) in much more depth,** grounded in both codebases, keeping every decision above. Re-evaluate whether the deeper analysis changes the recommendation; if not, say why; if a staged path toward A makes sense (C now, A later), give the trigger conditions.

**Initial conclusion, to be confirmed in the investigation:** a full fold-in means rewriting Kana Cards in the hub's stack, and first adding Dota seasons and match data to the hub. That is a large project. The most likely first step is different: once the Dota schedule lives in the hub, Kana Cards can read it from there. It already supports a JSON fixtures feed (`SCHEDULE_FIXTURES_URL`), so this could be a small change. Intermediate options with much less work exist: shared login, a link or embed from the hub, or data exchange over APIs. The document compares these and recommends one.

**Assumptions:**
- The investigation uses only the public repository and documentation. Questions only the hub team can answer (roadmap, whether Dota seasons are run in the hub, hosting) are collected and sent to them, not guessed.
- No code changes in either repository.

Resolves GitHub issue #108.

## User Stories

### Feasibility Document
**User story**
As the product owner, I want a written assessment of folding Kana Cards into Kana Hub so that I can decide the direction before investing development time.

**Acceptance criteria**
- `markdown/features/reference/kana-hub-integration-feasibility.md` compares the two systems area by area: stack, data model, identity, game data, fantasy design, background jobs, Twitch, hosting and licence. Each area cites concrete files or docs from both repositories, with the hub's branch and date
- It lists the **architectural blockers**, each with severity (blocker / major / minor) and what would remove it
- It confirms or corrects the preliminary findings in this plan, including whether the hub ingests any Dota data and how its fantasy league scores
- It explains how the hub is organised per game (game registry, per-game backend domains, per-game fantasy namespace, season routes), where Dota would fit, and which Kana Cards part maps to which hub layer
- It is understandable without reading either codebase

### Integration Options and Recommendation
**User story**
As the product owner, I want the realistic integration options compared side by side so that I can choose one with known cost and risk.

**Acceptance criteria**
- At least four options are compared:
  - (A) full port into the eggosystem,
  - (B) Kana Cards stays separate but uses hub (Steam) login and identity,
  - (C) the hub links to or embeds Kana Cards views, and the two exchange data through APIs. This includes Kana Cards reading the Dota schedule, teams and results from the hub once they move there,
  - (D) no integration; Kana Cards keeps its own branding
- Each option lists what users see, the work involved in t-shirt sizes (S/M/L/XL) per area, the risks, what happens to existing data (accounts, cards, history), and the effect on the Twitch extension
- What moving to Steam login removes from Kana Cards (files, endpoints, env vars), under Option A and under a Steam-only Option B, with the trade-off for players
- A clear recommendation with reasons, and the first concrete step if chosen
- An **Option A in depth** section evaluates the full port against both codebases: the target architecture in the hub (where each Kana Cards module lands in `games/dota/`, `games/fantasy/dota/` or hub core; how the hub's CS2 fantasy is structured and schedules scoring; `/api/v2/internal` vs public routes; frontend pages), the data model mapping (SQLite tables to hub tables or new Knex migrations, following hub conventions), background work, frontend, Twitch extension, testing and quality gates, an effort table per area with t-shirt size and person-week range plus a total and the critical path, a phased migration plan tied to season breaks, risks and gains, and decision criteria. It states whether the deeper analysis changes the recommendation and why, and every hub claim in it cites a hub file path at the checked commit
- How Kana Cards would sit next to the hub's CS2 fantasy league as the Dota game, for example in navigation, account and leaderboard presentation. Both stay separate products
- What "single site for the tournament" needs in order: Dota season, teams and schedule in the hub first, then fantasy linked or embedded

### Questions for the Hub Team
**User story**
As the product owner, I want the open questions collected so that a single conversation with the hub maintainers can settle them.

**Acceptance criteria**
- A short list of questions only the hub team can answer, for example:
  - When and how are Dota seasons, teams and the schedule planned to arrive in the hub?
  - Will the hub expose them through a public API (`/api/v2`) that Kana Cards could read?
  - Is Dota match data (OpenDota) wanted in the hub, or should Kana Cards keep ingesting it?
  - What hosting and login (SSO) options exist for external services, and can the hub link or embed one?
- Each question says which option or blocker it affects

### Account Bridging Check
**User story**
As a developer, I want to know how Kana Cards accounts would map to hub identities so that a later integration doesn't lose anyone's cards.

**Acceptance criteria**
- The document explains the Steam32 ↔ Steam64 relation (OpenDota account id + 76561197960265728)
- It states that the number of users with a linked player ID is not decisive: the architecture is the same whatever the count. No count is required, and no personal data appears in the document
- It describes what happens to users without a linked ID (for example, a one-time Steam link step) and to Twitch links

## Implementation

### Critical Files
| File | Change |
|---|---|
| `markdown/features/reference/kana-hub-integration-feasibility.md` | The decision document (from the stub) |
| `markdown/features/README.md` | Index row (added at planning) |
| `markdown/stories/tooling.md`, `markdown/stories/_index.md` | Stories (added at planning) |

No code changes.

### Step 1 — Read the hub
Using the public GitLab API or a shallow clone of `development`, read:
- `README*.md`
- `apps/backend/migrations/*fantasy*`, the fantasy services and controllers
- the auth middleware, and the `(embed)` routes
- docs on Discord and API-key service auth
- anything about Dota (`Games` id 4, match ingestion)

Record the commit SHA read.

### Step 2 — Map Kana Cards
Summarise Kana Cards' moving parts from its own docs:
- ingest and stored points (#141),
- sessions (#117),
- Twitch extension and EBS,
- weeks and substitutions (#129),
- tokens and draws.

List the login code a Steam-only login would make removable.

### Step 3 — Write the comparison, blockers and options
Fill in the document: the area table (confirmed), the blockers list, the four options with sizes and risks, the recommendation, the hub's per-game structure and where Dota fits, the questions for the hub team and account bridging.

### Step 4 — Option A in depth
Read the hub at the same commit (source archive, grepped in the scratchpad; nothing installed or run): the CS2 fantasy module (`apps/backend/src/games/fantasy/cs/`), how scoring is triggered, route mounting (`apps/backend/src/routes/index.ts`), the PUBG poller and BullMQ utilities, migrations and their conventions, CI (`.gitlab-ci.yml`), the frontend fantasy pages and registry. Map every Kana Cards module and table, estimate effort per area in person-weeks, and write the phased plan, risks, gains and decision criteria as section 11 of the document. Update the side-by-side table, Summary and Recommendation.

### Step 5 — Review
Run `/technical-writer` on the document. Developer-facing, so complete over short. Share it with the hub maintainers along with the questions.

## Verification
- Every claim about the hub cites a file path, and the document names the commit SHA it was checked against.
- The blockers list covers at least: stack rewrite, Dota seasons and data not yet in the hub, identity migration and Twitch EBS move. It also lists the dependency on the hub's Dota schedule work.
- The recommendation names a first step that can be done in one sprint.
- No personal data (usernames, emails, Steam IDs) appears in the document.
- The Option A deep dive has every required part, its effort total equals the sum of its rows, its phases are tied to season breaks, and its hub claims cite paths (`backend/tests/test_issue_108_kana_hub_integration_feasibility.py`, `TestOptionADeepDive`).
