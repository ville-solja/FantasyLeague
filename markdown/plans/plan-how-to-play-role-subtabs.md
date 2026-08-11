# Plan: How to Play — Role-Based Subtabs

## Context
GitHub issue #82 asks for short instruction pages aimed at different audiences: Users, Players
(Kanaliiga players who may also be app users), Streamers (extension application + usage), and
Developers (design decisions). A follow-up comment clarifies the delivery mechanism: rather than
separate top-level pages, the existing **How to Play** tab should gain **role-based subtabs**,
and while restructuring, the current content should be audited and corrected for accuracy.

The How to Play tab already exists (`markdown/features/reference/how-to-play-tab.md`,
`frontend/index.html` `#tab-howtoplay`, `frontend/app-init.js` `loadHowToPlay()`) with three
flat panels: Getting Started, Twitch & MVP, Scoring & Modifiers. This plan reorganises that
content under a **Users** subtab (Getting Started + Scoring & Modifiers, since both apply to
every registered user) and adds three new subtabs: **Players**, **Streamers**, and
**Developers**. The existing Twitch & MVP content splits across Users (viewer linking, since
any user can be a viewer) and Streamers (broadcaster setup + Quick Actions flow). Sub-navigation
follows the same pattern as the Admin panel's `.admin-tab-btn` buttons
(`frontend/index.html:630-635`, driven by `initAdminTabs()` in `frontend/app-admin.js`) — a row
of buttons toggling which content panel is visible, all client-side, no new backend endpoints.

Because the feature doc `reference/how-to-play-tab.md` already fully describes this tab, this
plan **updates that file in place** rather than creating a duplicate stub, per the project's
"do not duplicate content" documentation rule. `markdown/features/README.md`'s existing row for
this file is updated in place rather than a new row added.

Resolves GitHub issue #82.

## User Stories

### Role-Based How to Play Subtabs
**User story**
As any visitor to the app, I want the How to Play tab organised into subtabs by role (Users,
Players, Streamers, Developers) so that I can jump straight to the instructions relevant to me
instead of reading unrelated content.

**Acceptance criteria**
- The How to Play tab shows a row of four subtab buttons: Users, Players, Streamers, Developers
- Exactly one subtab panel is visible at a time; clicking a button shows its panel and hides the others
- The Users subtab is shown by default when the How to Play tab is first opened
- Subtab switching is client-side only — no additional network request is made when switching
- All four subtabs are visible regardless of login state (the tab remains public, matching current behaviour)
- Existing content (Getting Started, Twitch & MVP viewer/broadcaster split, Scoring & Modifiers with live `GET /weights` values) is preserved and reviewed for accuracy against the current codebase, with any outdated statements corrected

### Users Subtab
**User story**
As a new user, I want a "Users" subtab that explains how the fantasy app works and how scoring is calculated so that I can get started without reading external documentation.

**Acceptance criteria**
- Contains the existing Getting Started content: drawing cards, roster/weekly lock, earning tokens
- Contains the existing Scoring & Modifiers content: live stat weight table, rarity bonus table, modifier table, and MVP bonus value, all loaded from `GET /weights`
- Contains the viewer half of the existing Twitch & MVP content: linking a Fantasy account via Profile → Generate Twitch Code, and that watching linked streams makes a viewer eligible for token drops
- Renders correctly with no active session, since `GET /weights` is a public endpoint

### Players Subtab
**User story**
As a Kanaliiga player, I want a "Players" subtab that explains how to link my Dota 2 profile to my Fantasy account so that tags and stickers granted to me appear correctly on my cards and the leaderboard.

**Acceptance criteria**
- Explains that a Kanaliiga player who also wants a Fantasy account can link the two via Profile tab → enter Dota 2 (OpenDota) player ID
- Explains what linking unlocks: admin-granted tags appear as card stickers and leaderboard chips (per `reference/player-linking-and-tag-visibility.md`)
- Explains that linking is optional and can be changed later from the Profile tab
- Clarifies that a player does not need a Fantasy account for their real match performance to count toward other users' rosters — only linking affects their own tags/stickers

### Streamers Subtab
**User story**
As a Kanaliiga broadcaster, I want a "Streamers" subtab that explains both how to apply for the Twitch extension and how to use it, so that I can get set up and run MVP selection without contacting a developer for every step.

**Acceptance criteria**
- Explains how to apply: while the extension is in Twitch's "Local Test" status, a broadcaster needs a developer-provided test install link to whitelist their channel; once publicly released this step is not needed
- Explains how to install: add the extension from the Twitch Extension Manager (or via the test install link), no URL configuration required on the broadcaster's side
- Explains how to use it: Quick Actions (Live Config view in Twitch Stream Manager) → Select match MVP → series → match → player → confirm
- Explains the effects of confirming an MVP: automatic one-time token drop to eligible linked viewers, and a configurable fantasy score bonus applied to that player for that match
- Content matches the current implementation described in `markdown/features/core/twitch-extension.md` (no stale steps, e.g. no mention of manually setting an EBS URL, which is a one-time operator task, not a broadcaster task)

### Developers Subtab
**User story**
As a prospective contributor, I want a "Developers" subtab that summarises the app's key design decisions so that I can understand the reasoning behind the architecture before reading the full documentation.

**Acceptance criteria**
- Summarises 4-6 notable, currently-accurate design decisions (e.g. dynamic per-draw card generation instead of a shared static pool, SQLite with an online-backup safety net instead of a heavier DB engine, admin-driven season lifecycle instead of env-var season boundaries, demo mode for reproducing the season lifecycle on demand)
- Links out to `README.md`, `markdown/features/README.md`, and `markdown/process-diagrams.md` for full depth rather than duplicating their content
- Does not restate implementation details already covered by other subtabs (Users/Players/Streamers) — stays scoped to high-level rationale

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/index.html` | Restructure `#tab-howtoplay` (currently three stacked `.panel` divs, `frontend/index.html:533-618`) into a subtab nav row (`.howtoplay-tab-btn` buttons, mirroring `.admin-tab-btn` at `frontend/index.html:630-635`) plus four panel containers (`#howtoplay-panel-users`, `-players`, `-streamers`, `-developers`) |
| `frontend/app-init.js` | `loadHowToPlay()` (currently lines 1-60+) keeps fetching `GET /weights` for the Users panel; add `switchHowToPlayTab(role)` toggling panel visibility and active button state, called on tab init (default `users`) and on button click |
| `frontend/style.css` | Reuse or extend `.admin-tab-btn` styling for `.howtoplay-tab-btn`; add panel show/hide class if not already generic |
| `markdown/features/reference/how-to-play-tab.md` | Rewritten to document the four subtabs, their content ownership, and the client-side switching mechanism |
| `markdown/features/README.md` | Update the existing How to Play Tab row description to mention role-based subtabs |
| `markdown/stories/ux-and-polish.md` | Append the five stories above under the existing `## How to Play` heading |

### Step 1 — Content audit
Before restructuring, re-read `frontend/index.html:533-618` and `markdown/features/core/twitch-extension.md`
side by side. Confirm every factual claim in the current How to Play content still matches the
implementation (token drop cap, MVP bonus wording, roster size of 5, lock timing). Correct any
drift found (this addresses the "check the contents and update them" instruction from the issue
comment).

### Step 2 — Subtab shell
Add the `.howtoplay-tab-btn` row and four panel `<div>`s to `#tab-howtoplay`. Move the existing
Getting Started and Scoring & Modifiers panels into `#howtoplay-panel-users`; move the viewer
bullet list from the current Twitch & MVP panel into the Users panel; move the broadcaster
bullet list and MVP Fantasy Bonus explanation into `#howtoplay-panel-streamers`.

### Step 3 — New panel content
Write the Players and Developers panel content as static HTML (no new endpoints), following the
existing panel style (`<h2>`/`<h3>`/`<ul>` with the established inline styles used elsewhere in
this tab).

### Step 4 — Subtab switching JS
Add `switchHowToPlayTab(role)` to `frontend/app-init.js`, toggling a `hidden`/`active` class per
panel and per button. Call it with `'users'` whenever `switchTab('howtoplay')` runs, so the tab
always opens on the Users subtab.

### Step 5 — Documentation
Rewrite `markdown/features/reference/how-to-play-tab.md` to describe the new subtab structure.
Update the `markdown/features/README.md` row. Append the new stories to
`markdown/stories/ux-and-polish.md`.

## Verification
- Open the How to Play tab while logged out — Users subtab shows by default, `GET /weights` values populate
- Click through all four subtab buttons — exactly one panel visible at a time, no network request fires on click
- Confirm Players subtab content matches `reference/player-linking-and-tag-visibility.md`
- Confirm Streamers subtab content matches `markdown/features/core/twitch-extension.md` (no stale EBS URL / developer-only steps presented as broadcaster steps)
- Confirm Developers subtab links resolve to real files (`README.md`, `markdown/features/README.md`, `markdown/process-diagrams.md`)
- No backend changes — no migration or pytest run needed beyond a quick manual browser check of the restructured tab
