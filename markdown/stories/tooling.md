# Development Tooling

## Agent Lessons Log

### Read Lessons Before Working
**User story**
As a developer agent, I want to read the lessons log before starting implementation so
that I avoid mistakes that a previous agent already documented.

**Acceptance criteria**
- `markdown/lessons-learned.md` exists with a defined structure (date, agent, category,
  problem, solution)
- The developer, qa-engineer, security-reviewer, scoring-analyst, and test-planner agent
  definitions each list `markdown/lessons-learned.md` in their `## Files to read` section
- When a run produces no new lessons, the file is not modified

### Write a Lesson After Encountering a Novel Issue
**User story**
As any agent, I want to append a lesson entry when I encounter a novel problem so that
future agents benefit from the discovery.

**Acceptance criteria**
- Any agent can append a new entry to `markdown/lessons-learned.md` using the standard
  format when it encounters an issue not already covered
- Entries are appended, never rewritten — the log is append-only
- Each entry includes: date (ISO), agent name, category tag, one-line problem summary,
  and a solution or workaround
- Lessons are not appended for issues already documented; duplicates are avoided by
  reading the log first

### Browse and Maintain the Lessons Log (Operator)
**User story**
As an operator, I want a readable, navigable lessons log so that I can understand
recurring issues and remove stale entries.

**Acceptance criteria**
- The log is a single Markdown file with flat `### [date] — [category]` heading entries
- Entries are sorted newest-first
- Stale or superseded entries can be manually deleted without breaking agent reads

## Process Diagrams

### View the Season Lifecycle Diagram
**User story**
As a new contributor or operator, I want to see a visual diagram of the season lifecycle
so that I can understand the pre-season setup and the recurring weekly loop without reading
all the source files.

**Acceptance criteria**
- A Mermaid `flowchart LR` diagram exists in `markdown/process-diagrams.md`
- It shows a pre-season phase (player pool setup, league configuration, week creation)
- It shows the during-season weekly loop (ingest → score → lock → roster snapshot → repeat)
- It shows the Twitch MVP flow as a side-group connected to match scoring
- Admin tools are shown as a side group, not inline with the main flow

---

### View the Token and Card Economy Diagram
**User story**
As a developer working on scoring or draw logic, I want a visual map of all token sources
and sinks and the card lifecycle so that I can trace how tokens move through the system.

**Acceptance criteria**
- A second Mermaid diagram shows all token sources (initial allocation, promo code, token
  grant event, Twitch drop, player refund)
- It shows all token sinks (standard draw, booster draw, reroll)
- It shows the card lifecycle after a draw (activate vs bench, weekly scoring, swap window)
- All sources and sinks match the current implementation

---

### Discover Process Diagrams from the Documentation Index
**User story**
As any reader of the docs, I want the process diagrams to be discoverable from the main
documentation entry points so that I do not have to know they exist in order to find them.

**Acceptance criteria**
- `markdown/features/README.md` includes a link to `markdown/process-diagrams.md`
- The main `README.md` documentation section also links to `markdown/process-diagrams.md`
- The page title and file name are descriptive enough to be findable by search

## Admin Router Organization

### Split Admin Endpoints into Focused Router Modules
**User story**
As a developer working on this codebase, I want admin endpoints grouped into small,
concern-specific router files instead of one 1,200+ line file so that I can find and change
the code for one admin feature without scanning past nine unrelated ones.

**Acceptance criteria**
- `backend/routers/admin.py` is replaced by focused modules, each a self-contained
  `APIRouter()` covering one concern (users/tokens/codes, ingest/schedule, weeks,
  notifications, tags, player pool, leagues, season lifecycle, matches/MVP, demo mode)
- Every existing endpoint keeps its exact path, method, request/response shape, and
  `Depends()` auth guard — this is a file reorganization, not a behavior change
- `backend/main.py` imports and `include_router()`s each new module in place of the single
  `admin_router`
- No file in the new split exceeds roughly 350 lines

### Preserve Existing Test Coverage Through the Split
**User story**
As a developer relying on CI, I want the full existing test suite to keep passing unmodified
in behavior (only import paths change) so that the refactor is verifiably behavior-preserving.

**Acceptance criteria**
- Test files that import handler functions directly from `routers.admin` have those imports
  updated to the correct new module for each function
- Any monkeypatch fixture targeting a function that moved (e.g. `backup_sqlite_db` used by
  season reset) is updated to patch the function's new module path
- The full backend test suite passes with the same pass/skip counts as before the split
- `python -c "import main"` succeeds with no import errors

### Keep Developer Agent Definitions Accurate After the Split
**User story**
As a maintainer relying on the project's slash-command agents, I want agent definitions that
cite `backend/routers/admin.py` updated to reference the correct new file(s) so that agent
prompts don't silently point at a file that no longer contains what they describe.

**Acceptance criteria**
- `/agent-steward` is run after the split lands
- Every agent definition that previously cited `backend/routers/admin.py` is corrected to
  reference the new module(s), with its version header incremented
- `/agent-steward`'s final status table shows 0 stale/broken agents

## Frontend Architecture

### Produce a Framework Evaluation Document
**User story**
As the maintainer, I want a written comparison of staying vanilla-JS versus adopting a
frontend framework (evaluated both as a full rewrite and as incremental/hybrid adoption),
grounded in this codebase's actual architecture and recent pain points, so that I can decide
whether migrating is worth the cost without having to research it myself.

**Acceptance criteria**
- The document lives at `markdown/features/reference/frontend-framework-evaluation.md`
- It inventories the current frontend's actual shape: file count/split pattern, global state
  management, build tooling (none), and how it's served (FastAPI `StaticFiles`, no bundler)
- It evaluates at least: (a) staying vanilla JS with incremental structural improvements,
  (b) a full-rewrite migration to one concrete framework, (c) incremental/hybrid adoption
  (framework mounted alongside existing vanilla JS for new or rebuilt surfaces only)
- Each option is scored against this codebase's actual constraints: no build step today (so
  bundler/tooling cost is not zero for any framework option), FastAPI serving static files
  directly (compatibility with each option), the existing 18+-file split-by-tab pattern
  (compatibility or migration cost), and team size/velocity implications
  (single/small-team maintenance)
- It references the bracket-tree visualization complexity/scrap as a concrete worked example
  of the current approach's ceiling, not just an abstract claim
- It ends with a single clear recommendation (which option, and why) and, if the
  recommendation is anything other than "stay vanilla JS," an explicit statement that no
  migration work begins until the user reviews and approves this document
- Does not modify any `frontend/*.js`, `frontend/index.html`, or `backend/` file — this story
  is documentation-only

### Validate the Recommendation with a Minimal Spike
**User story**
As a developer, I want a small, isolated, fully-reversible prototype of one real existing
component rebuilt in the recommended framework (only if the evaluation recommends adoption),
so that integration cost against this app's actual FastAPI-served, no-build-step setup is
validated with working code before any full migration is committed to.

**Implemented**: rebuilt the How to Play tab's subtab switching (previously
`switchHowToPlayTab()`/`initHowToPlayTabs()` in `frontend/app-init.js`) using Alpine.js
`x-data`/`x-show`/`@click`, loaded via CDN script tag alongside the untouched vanilla-JS admin
and main-nav tab switching. See "Spike Results" in
`markdown/features/reference/frontend-framework-evaluation.md` for the observed integration
cost.

**Acceptance criteria**
- Only proceeds if `frontend-framework-evaluation.md`'s recommendation is not "stay vanilla
  JS," and only after the user explicitly approves starting the spike
- Rebuilds exactly one existing, bounded UI surface (not a new feature) — favors something
  with contained blast radius (e.g. a single admin panel or the Players tab table, not the
  auth flow or anything touching payments/tokens)
- Runs alongside the existing vanilla-JS app without replacing or breaking any current page —
  reversible by deleting the spike's files and one script-tag/mount-point change
  in `index.html`
- Documents the actual build-tooling and FastAPI-serving integration cost observed (not
  estimated) from doing the spike, as a follow-up note to the evaluation doc
- Intentionally deferred and separately gated — not implemented as part of the first story

---

## Test Background Task Isolation

### Tests Never Start Background Threads
**User story**
As a developer, I want the test suite to run without the app's background threads so that tests cannot interfere with each other through a shared database.

**Acceptance criteria**
- A `BACKGROUND_TASKS_ENABLED` env var, default `true`, controls whether the lifespan starts the week-maintenance, ingest-poll, profile-enrichment and backup threads
- `backend/tests/conftest.py` sets `BACKGROUND_TASKS_ENABLED=false` before any app module is imported, so no test starts those threads by default
- The lifespan still runs its synchronous startup work, such as table creation, migrations and seeding, and logs one line saying background tasks are disabled
- A test that opens `TestClient(main.app)` as a context manager starts no new threads. The number of live threads is the same before and after
- No test writes a backup file into the real `data/` directory, and the "Automatic DB backup failed" log line no longer appears during the suite

### Stable Full-Suite Runs
**User story**
As a developer, I want the full suite to pass repeatedly so that a red CI build means a real regression.

**Acceptance criteria**
- `test_issue_124_roster_mutation_rate_limiting.py` passes in 10 consecutive full-suite runs
- The suite-size tripwire in `test_issue_85_split_admin_router.py` passes in the same runs
- Production behaviour is unchanged: with the variable unset, all four threads start as before

---

## Technical Writer

### Rewrite a Document for Its Audience
**User story**
As a maintainer, I want to run `/technical-writer <target>` on a piece of documentation so that it states its core message clearly and concisely for the people who read it.

**Acceptance criteria**
- The command accepts a file path, a file path plus section heading (e.g. `README.md#Deployment`), or a short description of a documentation area (e.g. "hoster deploy notes")
- If no argument is given, the command stops and asks what documentation to consider
- If the target cannot be resolved to existing files, the command lists the closest matches and asks which one was meant
- Before proposing changes, the command prints the audience it identified, what that audience needs to know or do, and the one- or two-sentence core message of the document
- The rewrite keeps every fact that audience needs: env var names, defaults, endpoint paths, commands, file paths and version numbers stay exact
- Any fact the rewrite removes or moves elsewhere is listed in the report with the reason

### Identify the Audience and Ask When Unsure
**User story**
As a maintainer, I want the writer to tell me who it thinks the document is for, and ask me when it cannot tell, so that the rewrite targets the right readers.

**Acceptance criteria**
- The command infers the audience from the file's location and content using a documented mapping (e.g. `markdown/features/reference/` → developers and operators; `.env.example` and the README deployment section → the hoster; `markdown/stories/` → product owner and developers; `.claude/commands/` → the agents themselves)
- When the location and content point to different audiences, or the document serves more than one, the command asks the user to choose, offering 2–4 concrete options
- When a question is open that changes the rewrite (for example whether a section still applies), the command asks it instead of guessing
- The command never asks about choices that have a clear default in the project's conventions (CLAUDE.md, existing doc structure)

### Approve Changes Before They Are Written
**User story**
As a maintainer, I want to see the proposed rewrite and choose how to proceed so that no documentation changes without my agreement.

**Acceptance criteria**
- The command shows the proposed rewrite, or a before/after of each changed section for long files, with word counts before and after
- It then offers options: apply as proposed, apply with listed changes excluded, or discard
- Decisions that go beyond rewording, such as deleting a section, splitting a file, or moving content to another doc, are offered as separate options, not applied silently
- After approval, the command edits only the target files and any index it must keep in sync (`markdown/features/README.md`, `markdown/stories/_index.md`)
- It follows CLAUDE.md documentation rules: the README links to `markdown/features/` instead of duplicating it, and stories keep the standard **User story** / **Acceptance criteria** format

### Keep the Agent Roster Consistent
**User story**
As a maintainer, I want the new command registered like every other agent so that `/agent-steward` and the docs know about it.

**Acceptance criteria**
- `.claude/commands/technical-writer.md` starts with `<!-- version: 1 -->` and `<!-- mode: read-write -->` and follows the shared contract: Role, Scope, When to run, Precondition check, output format
- The command is listed in `CLAUDE.md` under Developer Agents and in `.claude/commands/README.md` under Maintenance agents
- The command reads `markdown/lessons-learned.md` at the start of a run and appends an entry when it finds a novel documentation pitfall
- `/agent-steward` reports no missing headers or broken file references for the new command

---

## Testing Tooling: Season Scenarios and Mock OpenDota

### Load a Season Scenario
**User story**
As a developer testing on a dev or test server, I want to reset the app to a named, realistic season state in one action so that I can test mid-season features without building the state by hand.

**Acceptance criteria**
- `POST /admin/demo/scenario` with `{"name": "pre-season" | "mid-season" | "season-end"}` (admin, `DEMO_MODE` only, otherwise 404) replaces all game data with the named scenario and sets the demo clock to match
- **mid-season:** 10 weeks, 5 locked and scored, week 6 open for edits. 8 teams of 5 synthetic players, 1 admin and 5 player accounts with 10–15 cards each, rosters with benches, at least one bench substitution, MVPs set on most matches, one unparsed match and one excluded match
- **pre-season:** weeks created, none locked, accounts with starter tokens and a few cards. **season-end:** all weeks locked and scored, ready for End Season
- The same scenario name always produces the same data: same seed, same totals
- The loader refuses to run without `DEMO_ACCOUNT_PASSWORD`, and writes a `demo_scenario_loaded` audit entry
- Stored card points (#141) are rebuilt, and substitutions (#129) are run for finished weeks, so every page shows consistent numbers right after loading
- The admin Demo panel shows a scenario picker with a confirmation step in the page; it never uses `confirm()`

### Drive Ingest with a Mock OpenDota
**User story**
As a developer, I want the app to ingest matches from a local mock OpenDota so that I can test ingest, live polling, parse retry and early MVP selection exactly as they run in production.

**Acceptance criteria**
- `OPENDOTA_BASE_URL` (default `https://api.opendota.com/api`) replaces the hard-coded address; every OpenDota call uses it
- `tools/mock_opendota/` serves the endpoints the app calls: `/leagues/{id}`, `/leagues/{id}/matchIds`, `/matches/{id}`, `/live`, `POST /request/{id}` and `/constants/heroes`. Responses follow the field shapes the app reads, including `/live` with a string `match_id` and players without names
- The mock's control endpoints let a tester:
  - `POST /_control/next-match`: release the next scripted match
  - `POST /_control/live`: make a scripted game live for N minutes
  - `POST /_control/parse/{id}`: turn an unparsed match into a parsed one
  - `POST /_control/reset`: reset the script
- The script matches the mid-season scenario's teams and players, so mock matches score against scenario rosters
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile mock up` starts the app with the mock and `OPENDOTA_BASE_URL` pointing at it. Ingest polling runs normally in that profile
- With `ENV=production`, startup refuses an `OPENDOTA_BASE_URL` that isn't https

### Save and Restore a Test Snapshot
**User story**
As a tester, I want to save the test database and restore it later so that I can repeat a manual test from the same starting point.

**Acceptance criteria**
- `POST /admin/demo/snapshots` with `{"name"}` (letters, digits, hyphen; 1–40 characters) saves a copy of the live database to `data/demo-snapshots/{name}.db`
- `GET /admin/demo/snapshots` lists the saved snapshots with name, size and time
- `POST /admin/demo/snapshots/{name}/restore` restores one into the live database while the app keeps running, then rebuilds stored card points
- All three are admin and `DEMO_MODE` only (404 otherwise), and need the admin password re-entry from #117, since restore overwrites everything
- Snapshot names never become paths outside `data/demo-snapshots/`; anything else gets 422
- Restoring keeps the restoring admin logged in: their user row is in the snapshot, and the session table is preserved across the restore. Every other session ends

### Demo Mode Can Never Reach Production
**User story**
As an operator, I want the test tools impossible to switch on in production so that a misconfiguration can't wipe real data.

**Acceptance criteria**
- With `ENV=production`, startup fails when `DEMO_MODE=true`, with a clear `[SECURITY]` message
- Every scenario and snapshot endpoint returns 404 when `DEMO_MODE` is off, before any admin check, as the existing demo endpoints do
- The docs list the test setup for `test.kana-cards.com`: `DEMO_MODE=true`, `DEMO_ACCOUNT_PASSWORD` set, `ENV` unset

---

## Kana Hub Integration Feasibility

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
