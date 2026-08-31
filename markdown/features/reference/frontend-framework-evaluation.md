# Frontend Framework Evaluation

A decision document evaluating whether adopting a frontend framework would provide tangible
benefits over the current vanilla-JS approach. *Resolves GitHub issue #95.*

**Recommendation: incremental/hybrid adoption of a lightweight, build-step-free library
(Alpine.js) for new and rebuilt complex-state UI — not a full rewrite, and not "stay vanilla
forever."** See [Recommendation](#recommendation) for the reasoning and the explicit approval
gate before any code changes begin.

---

## Current State (Inventory)

Read directly from the repository, not estimated:

| Property | Value |
|---|---|
| Frontend JS files | 18 (`frontend/app-*.js`) |
| Total JS lines | 3,728 |
| Split pattern | One file per tab or admin sub-concern (`app-cards.js`, `app-roster.js`, `app-admin-weeks.js`, `app-admin-users.js`, …) — established/reinforced this session when the original single `app-admin.js` (1,425 lines) was split into 9 files along the backend's `routers/admin_*.py` boundaries |
| Largest files | `app-cards.js` (513 lines), `app-roster.js` (482), `app-players.js` (430) |
| Build tooling | **None.** No `package.json`, no bundler config, no `node_modules` anywhere under `frontend/`. (`tests/ui/package.json` exists but is Playwright test tooling, entirely separate from the shipped app.) |
| Loading mechanism | 19 plain `<script src="/app-*.js">` tags in `frontend/index.html`, loaded in dependency order (e.g. `app-globals.js` first, since later files reference its globals) |
| Serving | `backend/main.py` mounts `frontend/` directly: `app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")` — the files FastAPI serves are exactly the files in the repo, no compile/transpile step in between |
| State management | Global `let` variables in `app-globals.js` (`activeUserId`, `activeIsAdmin`, `activeMustChangePassword`, `_tokenBalance`, `_weeks`, …), read and written directly by every other file with no encapsulation |
| Rendering pattern | Hand-written `fetch()` → build an HTML string via template literals → `element.innerHTML = ...`, repeated independently in every file that renders a table or panel |

## Recurring Pain Point: Duplicated Tab-Switching Logic

Three near-identical tab-bar implementations exist in the codebase today, each independently
hand-written:

- `switchAdminTab()` / `initAdminTabs()` (admin panel subtabs)
- `switchHowToPlayTab()` / `initHowToPlayTabs()` (How to Play subtabs)
- The equivalent pattern was written a third time earlier this session for a Schedule subtab
  bar (since reverted along with the rest of that feature), and hit a real bug in the process:
  the button and panel elements collided on the same `data-schedule-tab` attribute, so
  switching tabs also hid the tab buttons themselves — a class of bug that a framework's
  declarative state-to-DOM binding (e.g. `x-show`, conditional rendering) would not permit,
  because visibility would be derived from state rather than imperatively toggled via
  string-matched `data-*` attributes on every element in the DOM.

This is not a one-off — it is the same ~20-line pattern manually re-derived three times, and
it is where the one concrete bug in this evaluation's other worked example (below) actually
came from.

## Worked Example: The Scrapped Bracket-Tree Visualization

Earlier this session, a single-elimination bracket-tree visualization (`plan-tournament-stages.md`)
was built and then explicitly scrapped by the maintainer as "way too complex." The relevant
detail for this evaluation is *what* made it complex:

- The backend (4 new models, 2 new routers, 13 endpoints) was implemented cleanly and all 28
  tests passed on the first real attempt — the complexity was not in the data model or API.
- The frontend bracket-tree renderer (`frontend/app-schedule-stages.js`, now deleted) required
  hand-rolling CSS flexbox layout plus pseudo-element connector lines between rounds, winner/
  loser/TBD visual states computed and re-derived on every render, and manual pairing logic to
  align series into the correct bracket positions — all via string-templated HTML and direct
  DOM queries, with no component model to encapsulate "one bracket series" as a reusable,
  independently-updatable unit.
- The actual functionality worked (verified live via Playwright screenshots: connector lines,
  winner highlighting, and TBD placeholders all rendered correctly) — the complexity was in
  the amount of hand-written, imperative plumbing required to get there and keep it correct,
  not in whether it was achievable at all.

This is the clearest concrete evidence available for this evaluation: vanilla JS in this
codebase can build genuinely complex, stateful, dynamically-updating UI — but the cost of
doing so is high enough that the maintainer's own judgment was to scrap the feature rather
than accept that cost. A framework's value proposition is precisely reducing that cost for
this *class* of UI (multiple visual states derived from data, elements that need to
re-render when underlying data changes) — not for the CRUD-table-and-form UI that makes up
most of the rest of the app, which vanilla JS already handles adequately.

---

## Option Comparison

### (a) Stay vanilla JS, with incremental structural improvements

**What this means:** No new dependency, no build step. Address the duplicated tab-switching
logic by extracting one shared `initTabBar(barSelector, panelAttr, onSwitch)` helper instead
of three copies. Continue hand-writing `fetch`/render logic for CRUD surfaces.

**Fit against this codebase's constraints:**
- Build step: N/A — zero cost, zero change.
- FastAPI static serving: no change needed — already fully compatible.
- 18-file split pattern: no change needed.
- Team size: zero new tooling to learn or maintain — lowest ongoing cost by a wide margin.

**Verdict:** Correct default for the ~80% of this app that is CRUD tables, forms, and simple
tab panels — that code is not the source of the pain point this evaluation exists to address.
Does not address the bracket-tree class of problem at all; the next attempt at similarly
stateful UI (a live-updating leaderboard, a drag-and-drop bracket editor, anything with
several visual states per element) would hit the same wall.

### (b) Full-rewrite migration to one concrete framework (e.g. React or Vue)

**What this means:** Replace all 18 `app-*.js` files and `index.html`'s server-rendered
structure with a single-page application, introducing `package.json`, a bundler (Vite is the
standard pairing for either), and a build step whose output FastAPI would serve instead of
the current hand-written HTML/JS.

**Fit against this codebase's constraints:**
- Build step: goes from zero to a real, ongoing tooling surface — `npm install`,
  `node_modules`, a `vite build` (or equivalent) step added to the Docker image build and to
  local dev workflow, dependency updates to track, a new class of "works on my machine" build
  failures that don't exist today.
- FastAPI static serving: still works, but now serves a *compiled* bundle rather than the
  literal repo files — anyone (human or agent) editing `frontend/` directly no longer sees
  their change reflected until a rebuild runs. This removes a property the codebase currently
  has for free: every file in `frontend/` is exactly what ships.
- 18-file split pattern: entirely discarded — would need a full rewrite of every tab, not an
  incremental migration, since a SPA framework restructures rendering, routing, and state
  management app-wide, not file-by-file.
- Team size: highest cost of all three options. A solo maintainer (plus AI coding agents)
  absorbs 100% of the migration risk and the ongoing framework-version-upgrade burden, for a
  rewrite of code that mostly already works correctly today.

**Verdict:** Cost is disproportionate to the actual pain point. The bracket-tree example shows
*specific* UI classes are expensive in vanilla JS — it does not show the *entire app* needs
replacing. A full rewrite would spend the largest possible effort fixing the smallest fraction
of the app that actually hurts.

### (c) Incremental / hybrid adoption

**What this means:** Keep the existing 18-file vanilla-JS app and FastAPI static serving
exactly as-is. For *new* complex-state UI (the next bracket-tree-style feature) and,
opportunistically, for the duplicated tab-switching logic, mount a lightweight library
alongside the existing code rather than replacing it.

The concrete choice this evaluation recommends within option (c): **Alpine.js**, not React/
Vue/Svelte, specifically because it requires no build step — it is a single `<script src=
"...">` tag, the exact same integration mechanism every one of the 18 existing files already
uses. It provides declarative state-to-DOM binding (`x-show`, `x-for`, `x-data`) that directly
solves the class of bug the tab-switching duplication produced (visibility as a function of
state, not imperative attribute-matching), without introducing `package.json`, `node_modules`,
or a compile step.

**Fit against this codebase's constraints:**
- Build step: stays at zero. Alpine.js is added the same way `lucide.min.js` already is
  (`<script src="https://unpkg.com/...">` in `index.html`) — no new tooling category.
- FastAPI static serving: unaffected — every file in `frontend/` is still exactly what ships,
  for both the existing vanilla-JS files and any new Alpine-based ones.
- 18-file split pattern: fully preserved. Existing files are not touched unless and until
  there's a specific reason to touch them (e.g. finally de-duplicating the three tab-switchers
  into one Alpine component).
- Team size: lowest incremental cost of the two non-status-quo options — Alpine's entire API
  surface is a handful of directives, learnable in under an hour, with no ecosystem tooling to
  maintain.

**Verdict:** Directly targets the one class of problem this evaluation has concrete evidence
for (the bracket tree, the tab-switcher duplication), at close to the tooling cost of option
(a) and a small fraction of the cost of option (b).

---

## Recommendation

**Adopt option (c): incremental/hybrid adoption of Alpine.js**, not a full framework rewrite,
and not indefinite vanilla-only status quo.

Reasoning: the only concrete evidence gathered for this evaluation — the scrapped bracket-tree
visualization and the three independently-hand-written tab-switcher implementations (one of
which shipped a real bug from the duplication) — points at a specific, bounded class of UI
complexity, not at the whole application being wrong. Option (b)'s cost is calibrated to "the
whole frontend is the problem," which the evidence doesn't support. Option (a) leaves the
actual observed pain point unaddressed. Option (c) is scoped to the evidence.

**No migration or new-dependency work begins as a result of this document alone.** This
evaluation is the deliverable the GitHub issue asked for; adopting Alpine.js for any specific
surface — including the spike story in `markdown/stories/tooling.md` — requires the user to
review this recommendation and explicitly approve proceeding before any `frontend/index.html`
or `frontend/app-*.js` file changes, and before any new script dependency is added.

---

## Spike Results (observed, not estimated)

The recommendation was approved and the deferred spike story was carried out: the How to Play
tab's subtab switching (previously `switchHowToPlayTab()`/`initHowToPlayTabs()` in
`frontend/app-init.js`, the exact duplicated pattern cited above) was rebuilt using Alpine's
`x-data`/`x-show`/`@click` directives, alongside the untouched vanilla-JS admin and main-nav
tab switching.

- **Build-tooling cost: zero, as predicted.** Alpine was added as
  `<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>`
  in `frontend/index.html`'s `<head>` — the same mechanism as the existing `lucide.min.js` tag.
  No `package.json`, no `node_modules`, no change to the Docker build or CI.
- **FastAPI serving: unaffected, as predicted.** `frontend/index.html` and `frontend/app-init.js`
  are still served exactly as written, with no compile step.
- **One real integration detail not fully anticipated:** `x-show` toggles inline
  `display:none` at runtime, but before Alpine finishes initializing on page load, an element
  with `x-show="false"` is briefly unstyled (all four subtab panels would flash visible at
  once). This needed one small addition beyond what the evaluation above described: an
  `x-cloak` attribute on each conditionally-shown panel plus a two-line global CSS rule
  (`[x-cloak] { display: none !important; }`). This is Alpine's own documented pattern for
  this exact issue, not a workaround specific to this codebase — but it's the kind of detail
  that only surfaces by actually doing the integration, which is precisely why this evaluation
  called for a spike instead of committing to a broader migration on paper alone.
- **Net diff:** 2 functions removed from `app-init.js` (replaced by declarative markup), ~10
  lines of `index.html` attribute changes, 1 new CSS rule, 1 new script tag. Verified live
  (Playwright): tab switching, active-state styling, and content all behave identically to the
  pre-spike vanilla version, with the admin panel's independent vanilla-JS tab bar confirmed
  unaffected — hybrid coexistence works as evaluated.

This is a positive result for the option (c) recommendation: the cost was as low as predicted,
and the exact bug class this evaluation named (`data-*`-attribute collisions between buttons
and panels, which is what broke the reverted Schedule-tab implementation) is structurally
impossible in the Alpine version, since visibility is derived from state rather than matched
by imperative attribute comparison.

---

*Evaluation produced per `markdown/plans/plan-frontend-framework-evaluation.md`. See
`markdown/stories/tooling.md`'s "Frontend Architecture" section — the spike story is now
implemented.*
