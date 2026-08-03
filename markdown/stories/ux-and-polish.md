# UX and Polish

## Schedule and Transparency

### Scoring Explanation
**Acceptance criteria**
- Stats and their point mapping are shown to the user in the My Team tab
- Collapsible "How is scoring calculated?" section lists all weighted stats

---

### Schedule Tab
**User story**
As a user, I want to see the full season fixture list including past results and upcoming matches.

**Acceptance criteria**
- All series shown in a single chronological list spanning all divisions
- Upcoming series show planned date, team names, and stream link where available
- Past series show actual match start time, series result (e.g. 2–0)
- Team names link to the team detail modal
- Stale cache notice shown if schedule data is outdated

---

### Expand Series into Individual Game Rows
**User story**
As a user, I want each past series in the Schedule tab to expand into its individual games so
that I can see game-level detail instead of a flat list of bare match links.

**Acceptance criteria**
- Each past series with one or more resolved games renders each game as a child row nested
  under the series' team-vs-team header row
- Each game row shows: duration (formatted mm:ss), each team's total kills for that game, and
  each team's hero icons grouped by side (team1's heroes on the left, team2's on the right)
- The existing external link to the match (OpenDota) is preserved on each game row
- Upcoming (unresolved) series are unaffected — still show planned date/time/stream as today
- Series with no resolved games still show "vs" with no expandable content, as today

### Store Match Duration at Ingest Time
**User story**
As a developer relying on ingested match data, I want match duration stored on the `Match`
record at ingest time so that the schedule game breakdown (and any future feature) can display
it without extra OpenDota API calls.

**Acceptance criteria**
- `Match.duration` (seconds, nullable `Integer`) is populated from OpenDota's match JSON during
  `ingest_match()`
- Matches ingested before this change have `duration = NULL` until re-ingested; the schedule UI
  shows a game row without a duration in that case rather than erroring
- A numbered migration (`022_matches_duration`) adds the column to existing databases, guarded
  by a `PRAGMA table_info` check, per this repo's schema migration rule

### Show Hero Icons for Each Game
**User story**
As a user, I want to see which heroes each team played in a given game so that I can recognize
the draft at a glance without looking the match up on OpenDota.

**Acceptance criteria**
- Hero icon URLs are resolved from OpenDota's hero constants (the same source already used for
  hero names in player profile enrichment) and included in the schedule response for the games
  shown
- Icons are grouped by team (mapped to the series' `team1_id`/`team2_id`, not raw
  radiant/dire), so team1's heroes always render on the same side as team1's name and score
- A hero with no resolved icon (unknown `hero_id`, or the constants fetch failed) shows a
  placeholder rather than a broken image

### Show Past Results Without Requiring a Schedule-Sheet Row
**User story**
As a user, I want completed matches to appear in the Schedule tab's results even when the
schedule spreadsheet has no corresponding fixture row (playoffs, bracket stages, or matches the
sheet simply never listed) so that the results I see always reflect what's actually been played.

**Acceptance criteria**
- `GET /schedule` additionally derives series from completed matches not already resolved by any
  sheet row, grouping consecutive matches between the same two teams (played within a short time
  window of each other) into one series
- These derived series appear in the same Results list as sheet-resolved series, sorted
  chronologically together — not a separate or hidden section
- Each derived series shows the same detail as a sheet-resolved one: aggregate score and the
  per-game breakdown (duration, kills, hero icons)
- A completed match is never shown twice — matches already claimed by a resolved sheet series
  are excluded from the independently-derived results

### Results Remain Available Without a Configured Schedule Sheet
**User story**
As an operator running this app for a league that doesn't maintain a Google Sheets schedule, I
want the Schedule tab's Results to still populate directly from ingested match data so that the
app is useful without requiring a spreadsheet at all.

**Acceptance criteria**
- When `SCHEDULE_SHEET_URL` is unset (or the sheet is unreachable with no prior cache),
  `GET /schedule` returns an empty Upcoming set but still returns fully-populated Results derived
  from the database
- The existing "Schedule unavailable" messaging is scoped to Upcoming only — it is not shown
  (or is clearly secondary) when Results have data to display

### Upcoming Fixtures Remain Sheet-Sourced
**User story**
As a user, I want upcoming/future fixtures to keep coming from the schedule spreadsheet so that
planned dates and stream links — information that doesn't exist anywhere else before a match is
played — are still shown.

**Acceptance criteria**
- No change to how Upcoming series are resolved or displayed — still sourced entirely from the
  schedule sheet
- Existing sheet-resolved Results (series the sheet does describe) are unaffected in shape or
  content by this plan

---

## Layout

### Roster-first My Team Layout
**User story**
As a user, I want the My Team tab to show my roster as the primary content area so that I can see my active lineup and bench immediately without scrolling past deck controls.

**Acceptance criteria**
- My Roster (active cards + bench) occupies the majority of the tab's horizontal space
- Deck panel appears to the right of the roster as a sidebar, not above it
- On narrow screens (< 768 px) the sidebar stacks below the roster so the mobile experience is unaffected

---

### Deck Sidebar
**User story**
As a user, I want deck counts, the draw button, token balance, and the promo code field in a compact sidebar so these controls remain accessible without dominating the view.

**Acceptance criteria**
- Sidebar contains (top to bottom): deck rarity counts, draw button + token balance, promo code field, scoring info toggle
- Sidebar width is fixed at approximately 300 px on desktop

---

## Automated Testing

### Backend Unit Tests in CI
**User story**
As a developer, I want the backend pytest suite to run automatically on every push so that failures are caught before they reach production.

**Acceptance criteria**
- GitHub Actions workflow runs `pytest backend/tests/` on every push and pull request to `main`
- Workflow installs dependencies from `backend/requirements.txt` before running
- Failing tests block the PR check

---

### UI Regression Suite *(not yet implemented)*
**User story**
As a developer, I want automated browser tests for critical user flows so that UI regressions are caught without manual testing.

**Acceptance criteria**
- Playwright test suite covers: registration (field validation, duplicate errors), login/logout, card draw modal, roster activate/deactivate, and admin tab access guard
- Tests run against a locally started instance of the app
- Each test is independent — it seeds its own data and does not rely on leftover state from prior tests
- Suite produces a pass/fail exit code usable by CI and runs automatically on pull requests to `main`

---

## How to Play

### How to Play Tab
**User story**
As a new user, I want a tab that explains how the fantasy app works so that I can get started without reading external documentation.

**Acceptance criteria**
- A "How to Play" tab is visible to all users (logged in and logged out) in the main navigation
- The tab's Users subtab contains three clearly separated sections: Getting Started, Watching on Twitch, and Scoring & Modifiers *(superseded by the Role-Based How to Play Subtabs story below — content now lives in the Users subtab rather than three flat top-level sections)*
- Getting Started section explains: draw a card using a token, activate up to 5 cards into the roster, roster locks weekly, points accumulate from locked rosters
- Getting Started section explains how to obtain more tokens: week lock bonus, Twitch extension drops, promo codes
- Watching on Twitch section explains the viewer half of the MVP flow — linking a Fantasy account and receiving token drops
- Scoring & Modifiers section lists the scoring stats and reads live weight values from the server to show current multipliers
- Scoring section explains card rarity bonuses and card modifier bonuses using live weight values
- Tab renders correctly with no active session (weights endpoint is public)

---

### Streamer MVP Instructions
**User story**
As a Kanaliiga streamer, I want the How to Play tab to explain the Twitch extension MVP flow so that I can set it up and use it without reading separate documentation.

**Acceptance criteria**
- The tab's Streamers subtab explains: apply/install the extension, use Quick Actions to select a series → match → player *(superseded by the Streamers Subtab story below — this content now lives in its own subtab alongside extension application/installation instructions, rather than a flat "Twitch & MVP" section)*
- Explains that token drops fire automatically on MVP confirmation (once per match)
- Explains that the MVP selection also grants a fantasy score bonus to that player's match
- The subtab is visible to all users (not restricted to admins or streamers)

---

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

---

### Users Subtab
**User story**
As a new user, I want a "Users" subtab that explains how the fantasy app works and how scoring is calculated so that I can get started without reading external documentation.

**Acceptance criteria**
- Contains the existing Getting Started content: drawing cards, roster/weekly lock, earning tokens
- Contains the existing Scoring & Modifiers content: live stat weight table, rarity bonus table, modifier table, and MVP bonus value, all loaded from `GET /weights`
- Contains the viewer half of the existing Twitch & MVP content: linking a Fantasy account via Profile → Generate Twitch Code, and that watching linked streams makes a viewer eligible for token drops
- Renders correctly with no active session, since `GET /weights` is a public endpoint

---

### Players Subtab
**User story**
As a Kanaliiga player, I want a "Players" subtab that explains how to link my Dota 2 profile to my Fantasy account so that tags and stickers granted to me appear correctly on my cards and the leaderboard.

**Acceptance criteria**
- Explains that a Kanaliiga player who also wants a Fantasy account can link the two via Profile tab → enter Dota 2 (OpenDota) player ID
- Explains what linking unlocks: admin-granted tags appear as card stickers and leaderboard chips (per `reference/player-linking-and-tag-visibility.md`)
- Explains that linking is optional and can be changed later from the Profile tab
- Clarifies that a player does not need a Fantasy account for their real match performance to count toward other users' rosters — only linking affects their own tags/stickers

---

### Streamers Subtab
**User story**
As a Kanaliiga broadcaster, I want a "Streamers" subtab that explains both how to apply for the Twitch extension and how to use it, so that I can get set up and run MVP selection without contacting a developer for every step.

**Acceptance criteria**
- Explains how to apply: while the extension is in Twitch's "Local Test" status, a broadcaster needs a developer-provided test install link to whitelist their channel; once publicly released this step is not needed
- Explains how to install: add the extension from the Twitch Extension Manager (or via the test install link), no URL configuration required on the broadcaster's side
- Explains how to use it: Quick Actions (Live Config view in Twitch Stream Manager) → Select match MVP → series → match → player → confirm
- Explains the effects of confirming an MVP: automatic one-time token drop to eligible linked viewers, and a configurable fantasy score bonus applied to that player for that match
- Content matches the current implementation described in `markdown/features/core/twitch-extension.md` (no stale steps, e.g. no mention of manually setting an EBS URL, which is a one-time operator task, not a broadcaster task)

---

### Developers Subtab
**User story**
As a prospective contributor, I want a "Developers" subtab that summarises the app's key design decisions so that I can understand the reasoning behind the architecture before reading the full documentation.

**Acceptance criteria**
- Summarises 4-6 notable, currently-accurate design decisions (e.g. dynamic per-draw card generation instead of a shared static pool, SQLite with an online-backup safety net instead of a heavier DB engine, admin-driven season lifecycle instead of env-var season boundaries, demo mode for reproducing the season lifecycle on demand)
- Links out to `README.md`, `markdown/features/README.md`, and `markdown/process-diagrams.md` for full depth rather than duplicating their content
- Does not restate implementation details already covered by other subtabs (Users/Players/Streamers) — stays scoped to high-level rationale

---

## My Team Interactions

### Active Roster Drag-and-Drop
**User story**
As a player, I want to drag cards within my active roster to change their display order so
that I can arrange my lineup in a way that is meaningful to me.

**Acceptance criteria**
- Cards in the active roster grid are draggable
- Dragging a card and dropping it onto another card swaps or inserts it at the target position
- The new order is persisted to the backend so it survives a page refresh
- When the week is locked, drag handles are hidden and the order cannot be changed
- A visual drag-over indicator (highlight or gap) shows the drop target while dragging

---

### Bench Drag-and-Drop Reorder
**User story**
As a player, I want to drag cards within my bench to change their order so that I can
organise my reserve cards the same way I can my active roster.

**Acceptance criteria**
- Bench cards are draggable (when the week is unlocked)
- Dragging a bench card onto another bench card repositions it at that target position
- The new bench order is persisted to the backend so it survives a page refresh
- A visual drag-over indicator shows the drop target while dragging

---

### Card Viewer Backdrop Dismiss
**User story**
As a player, I want clicking outside an open card to close it so that I can dismiss the
card viewer without hunting for the close button.

**Acceptance criteria**
- Clicking the dark overlay area around the card viewer closes the modal
- Clicking inside the card content area does not close the modal
- The close button (X) continues to work as before
- The behaviour applies when a card is opened from the roster, bench, or any other context

---

## Table Sortability

### Sort Players Table by Column Header
**User story**
As a user, I want to click a column header in the Players tab to sort the table by that
column so that I can quickly find top-performers or compare players on a stat I care about.

**Acceptance criteria**
- Clicking any column header sorts all visible rows by that column
- Numeric columns (fantasy points, K/D/A, GPM) default to descending on first click so the highest values appear at the top
- Text columns (player name, team) default to ascending on first click (A → Z)
- The active sort column is visually indicated with an arrow icon (↑ or ↓) next to the header label
- All rows in the current filtered/search result set are sorted — not just the visible page

### Toggle Sort Direction
**User story**
As a user, I want to click the already-active sort column again to reverse the sort order
so that I can view the bottom of the ranking without scrolling.

**Acceptance criteria**
- Clicking the active sort header reverses the current direction (ascending ↔ descending)
- The arrow icon flips to reflect the new direction
- Sort state is reset to default when the tab is first loaded or reloaded
