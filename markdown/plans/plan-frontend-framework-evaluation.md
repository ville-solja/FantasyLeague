# Plan: Frontend Framework Evaluation

## Context
The issue asks whether adopting a more elaborate frontend framework would provide tangible
benefits as the app's UI demands grow — it explicitly asks for an **evaluation**, not a
migration decision made unilaterally. The current frontend is vanilla JS split across 18+
`frontend/app-*.js` tab/role-scoped modules with no build step, sharing state via global
variables (`activeUserId`, `activeIsAdmin`, etc.) and served directly by FastAPI's
`StaticFiles`. This plan produces a decision document, not code changes: a structured
comparison grounded in this codebase's actual, observed pain points rather than generic
framework pros/cons, ending in a recommendation the user can act on (or reject) with full
information. A concrete data point already exists to inform it: a recent single-elimination
bracket-tree visualization (connector lines between rounds, dynamic winner/TBD states) was
scrapped as "way too complex" to build well in the current vanilla-JS/CSS approach — direct
evidence of where the ceiling is, not a hypothetical.

If the evaluation recommends adoption, this plan also scopes (but does not commit to) a
minimal spike as the very next step, rather than a big-bang rewrite — consistent with this
session's own lesson that large, speculative frontend builds in this codebase carry real risk
of being scrapped after the fact.

*Resolves GitHub issue #95.*

## User Stories

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

### Validate the Recommendation with a Minimal Spike *(not yet implemented)*
**User story**
As a developer, I want a small, isolated, fully-reversible prototype of one real existing
component rebuilt in the recommended framework (only if the evaluation recommends adoption),
so that integration cost against this app's actual FastAPI-served, no-build-step setup is
validated with working code before any full migration is committed to.

**Acceptance criteria**
- Only proceeds if `frontend-framework-evaluation.md`'s recommendation is not "stay vanilla
  JS," and only after the user explicitly approves starting the spike
- Rebuilds exactly one existing, bounded UI surface (not a new feature) — the plan defers
  picking which one until the framework choice is known, but favors something with contained
  blast radius (e.g. a single admin panel or the Players tab table, not the auth flow or
  anything touching payments/tokens)
- Runs alongside the existing vanilla-JS app without replacing or breaking any current page —
  reversible by deleting the spike's files and one script-tag/mount-point change
  in `index.html`
- Documents, in a follow-up note to the evaluation doc, the actual build-tooling and
  FastAPI-serving integration cost observed (not estimated) from doing the spike
- This story is intentionally deferred and separately gated — it is not implemented as part
  of this plan's initial pass

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `markdown/features/reference/frontend-framework-evaluation.md` | The evaluation document — this plan's actual deliverable |
| `markdown/features/README.md` | Add a row linking to the evaluation doc |
| `markdown/stories/tooling.md` | Append the two user stories above under a new `## Frontend Architecture` heading |

No `backend/` or `frontend/*.js` files change as part of this plan's first story. The second
story is deferred and, if it proceeds, will need its own follow-up plan once a framework is
chosen (new critical files depend entirely on that choice).

### Step 1 — Inventory the current frontend

Before comparing options, write down what actually exists today (do not estimate — read the
files):
- `frontend/app-*.js` file count, rough total line count, and the split convention (one file
  per tab/admin-concern, established this session when `app-admin.js` was split into 9 files
  along backend router boundaries)
- Global state variables and where they're declared (`frontend/app-globals.js`)
- Confirm there is no build step: `frontend/index.html` loads every JS file via a plain
  `<script src="...">` tag, no bundler config exists in the repo
- Confirm serving: `backend/main.py` mounts `frontend/` via `StaticFiles(..., html=True)`

### Step 2 — Draft the comparison

Produce the comparison table and narrative described in the first story's acceptance
criteria. Keep the framework choice for option (b)/(c) concrete (name an actual framework,
e.g. one already familiar to the maintainer or with the lowest build-tooling ceremony) rather
than leaving it abstract — a vague "a framework" comparison is not a usable decision input.

### Step 3 — Write the recommendation

State one recommendation plainly, with the reasoning that drove it (not a balanced "it
depends" non-answer — the issue asks for an evaluation specifically so a decision can be
made). If the recommendation is to adopt or hybrid-adopt, explicitly gate any further work
behind user approval per the second story's acceptance criteria.

### Step 4 — Update the doc indexes

Add the new file to `markdown/features/README.md` (Reference tier) and append the two user
stories to `markdown/stories/tooling.md` under a new `## Frontend Architecture` heading,
updating `markdown/stories/_index.md`'s row for `tooling.md` if its summary needs to mention
frontend architecture evaluation.

---

## Verification
- `markdown/features/reference/frontend-framework-evaluation.md` exists and contains all
  acceptance-criteria elements from the first story (inventory, 3-option comparison scored
  against actual constraints, bracket-tree example, single clear recommendation)
- `git diff --stat` shows no changes to any `backend/` or `frontend/*.js`/`index.html` file
  after this plan is implemented — confirms the documentation-only scope was respected
- `markdown/features/README.md` and `markdown/stories/tooling.md` / `_index.md` are updated
- The second story remains unimplemented (no new frontend framework files exist) unless the
  user has explicitly approved proceeding past the evaluation
