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
