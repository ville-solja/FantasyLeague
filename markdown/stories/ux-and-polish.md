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
- All series shown in a single chronological list spanning all divisions *(superseded by issue #156: the tab now shows one fantasy week at a time; see "Schedule Visuals" below)*
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

### Configure a JSON Schedule Source
**User story**
As an operator, I want to point the app at a JSON fixtures endpoint via an environment
variable instead of a Google Sheet CSV, so the Schedule tab is populated from a structured,
less fragile source.

**Acceptance criteria**
- `SCHEDULE_FIXTURES_URL` environment variable configures a JSON fixtures endpoint
- When `SCHEDULE_FIXTURES_URL` is set, `GET /schedule` sources its `weeks[]` from that JSON
  and does not fetch the CSV sheet
- When `SCHEDULE_FIXTURES_URL` is unset, behaviour is exactly as today — the CSV sheet
  (`SCHEDULE_SHEET_URL`) is used, or the tab is empty if neither is set
- The `/schedule` JSON response keeps the same shape (`weeks[]` with `label`, `div1`, `div2`;
  each series with `team1`, `team2`, `datetime_iso`, `stream_url`, `series_result`, …), so no
  frontend or downstream change is required for sheet-parity fields
- `.env.example` and `markdown/features/reference/commands.md` document the new variable and
  its precedence over `SCHEDULE_SHEET_URL`

### Fixtures Map to the Same Week/Division Structure
**User story**
As a user, I want fixtures from the JSON feed grouped into the same weeks and divisions as the
sheet-sourced schedule, so the Schedule tab looks and behaves identically regardless of source.

**Acceptance criteria**
- Each feed fixture's `division` (`upper`/`lower`) maps to `div1`/`div2` respectively
- Fixtures are grouped by their `week` integer into weeks labelled `"Week {n}"`, ordered
  ascending
- `team1`/`team2`, and `stream` (as `stream_url` when it is an `http(s)` URL, else
  `stream_label`) carry across
- A fixture with a missing/unrecognised `week` or `division` is skipped, not allowed to crash
  the parse
- Team-name → `team_id` resolution, `series_result` cross-referencing, and independently-derived
  `extra_results` all work identically to the sheet path

### Unscheduled Fixtures Still Appear
**User story**
As a user, I want fixtures that don't yet have a confirmed date/time to still show up under the
right week in the Schedule tab, so I can see the full season plan before matches are scheduled.

**Acceptance criteria**
- A fixture with `starts_at: null` and empty `date`/`time` is given an approximate
  `datetime_iso` of its `week_start` date at 00:00, so it is not filtered out of the Upcoming
  list
- Such a series is marked `scheduled: false` in the `/schedule` response
- The Schedule tab shows "Time TBD" instead of a specific time for a `scheduled: false`
  series, and still shows team names, division badge, and week grouping
- A fixture with a real `starts_at` (ISO datetime) uses that as its `datetime_iso`, converted
  to local time, and is marked `scheduled: true`
- When both `starts_at` and `date`/`time` are present, `starts_at` wins

### Diagnose the Active Schedule Source
**User story**
As an operator, I want the schedule debug endpoint to tell me which source is active and
whether the JSON feed parsed cleanly, so I can troubleshoot a misconfigured or malformed feed.

**Acceptance criteria**
- `GET /schedule/debug` reports which source is in use (`fixtures_json` vs `sheet_csv`) and the
  configured URL (prefix only)
- For the JSON source it reports HTTP status, the feed's `season` and `count`, the number of
  weeks parsed, and the number of fixtures dropped for a missing/unknown `week` or `division`
- A fetch failure or non-JSON / schema-mismatched response is reported as a clear error string,
  not an unhandled exception

---

### MVP Selection Immediately Reflects on the Schedule Tab
**User story**
As a user, I want a match's MVP to show up on the Schedule tab right after the broadcaster or
an admin sets it, so I don't have to wait up to an hour for the cached schedule to catch up.

**Acceptance criteria**
- `POST /admin/matches/{match_id}/mvp` busts the schedule cache after successfully setting the
  MVP, so the next `GET /schedule` call recomputes fresh data instead of serving a stale cached
  response
- `POST /twitch/mvp` (the streamer-facing MVP flow) does the same
- A `GET /schedule` call made immediately after either endpoint succeeds shows the new MVP on
  the corresponding game row, with no waiting period
- Setting/changing the MVP for a match that isn't part of any currently-cached schedule response
  doesn't error — busting an already-clear cache is a no-op, matching `bust_cache()`'s existing
  behaviour used elsewhere (`POST /schedule/refresh`)
- No change to how the MVP itself is selected, stored, or scored — this only fixes how promptly
  the Schedule tab's read-side cache reflects it

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
- Contains the viewer half of the existing Twitch & MVP content: joining in the Kana Cards panel with **Join Kana Cards** (Twitch login, no sign-up), and that watching with the panel open makes a joined viewer eligible for token drops *(updated for #157: the earlier "Profile → Generate Twitch Code" linking step is gone)*
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
- Explains the effects of confirming an MVP: automatic one-time token drop to eligible joined viewers (soft accounts and website accounts (code-linked before #160, or connected with Twitch sign-in), #157), and a configurable fantasy score bonus applied to that player for that match
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

### Decluttered Card Slot Controls
**User story**
As a player, I want the My Team card slots to show only the card itself (no move or
bench/activate buttons) so that the roster view stays visually clean and drag-and-drop is the
obvious, primary way to manage my lineup.

**Acceptance criteria**
- The ◀/▶ move-left/move-right buttons are removed from every card slot (active and bench)
- The Bench/Activate text buttons are removed from every card slot
- Card slots show only the card image, its points value, and modifier pills (if any);
  drag-and-drop remains the way to reorder within a zone or move a card between zones by mouse
- Locked-week card slots are unaffected (they never showed these buttons)

---

### Keyboard Fallback for Bench/Active Toggle
**User story**
As a keyboard-only user, I want to move a card between my bench and active roster without a
mouse, so that removing the visible Bench/Activate buttons doesn't lock me out of that action
entirely.

**Acceptance criteria**
- Focusing a card slot's image and pressing Enter or Space toggles the card between active and
  bench: an active card is benched, a benched card is activated
- Activation failure cases reuse the existing `activateCard()` error handling (e.g. roster full,
  a card for this player is already active) — no new error copy is introduced
- The toggle does nothing when the current week is locked, matching drag-and-drop's existing
  lock gating (`_rosterLocked`)
- Mouse click on the card image continues to open the card detail modal, unchanged; this is a
  distinct interaction from the new keyboard toggle, not a replacement for it

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

---

## First-Time Guided Tour

### Start the Tour from How to Play
**User story**
As a player, I want to start a short guided tour from the How to Play tab so that I can learn how to draw cards, set my roster, see my points and find the Weekly Report when I choose to.

**Acceptance criteria**
- The How to Play Users subtab has a "Show the tour" button near the top. For a logged-in user it switches to My Team and starts the tour from step 1. For a logged-out visitor it opens the login popup instead
- The tour is **not** started automatically for anyone while `GUIDED_TOUR_AUTOSTART` is `false`, the default
- The tour has these steps, in order, each highlighting one element with a title and one or two sentences:
  1. **Draw a card** (`#drawBtn`): a draw costs 1 of your tokens (shown with the configured token name), or the team draw cost for a card from a team you pick; you get players you don't own yet first
  2. **Chances** (`.rarity-grid`): your chance of each rarity per draw; rarer cards score a higher bonus
  3. **Your roster** (`#rosterActiveGrid`): put up to {roster limit} cards on your active roster; only active cards score. The roster limit is the number of slots rendered on My Team (`ROSTER_SLOTS` in `app-roster.js`), not a server value; if the grid is empty it reads "up to the roster limit" instead
  4. **Weekly lock** (`#rosterWeekSelect`): your roster locks automatically when the week starts, so make changes before then
  5. **Points** (`#rosterTotals`, the This week / Season totals): your active cards score from every league match that week; totals update as matches come in
  6. **Weekly Report** (`#weeklyReportBtn`): added by #153, see "Tour Includes the Weekly Report" below
  7. **Leaderboards** (`#tab-btn-leaderboard`): see how you rank each week and over the season; full rules are in How to Play
- The text comes from live values (configured token name, team draw cost, rendered roster slot count), so it never shows a stale number or name
- A step whose element is missing or hidden is skipped, and the step count adjusts

### Control the Tour
**User story**
As a player, I want to skip or step through the tour easily so that it never gets in my way.

**Acceptance criteria**
- Buttons: **Skip** and **Next**, with **Done** on the last step, plus a step counter ("2 / 7")
- Clicking the dark backdrop or pressing Esc skips; Enter or → goes to the next step; ← goes back
- Focus moves into the tour box when it opens and returns to the page when it closes; the box has `role="dialog"`, `aria-modal="true"` and a label
- Skip, Done, Esc and a backdrop click all set `fantasy.tourSeen.v1`, so the tour doesn't start again after a reload. A blocked or failing `localStorage` doesn't break the page; the tour then simply shows again next time
- With `prefers-reduced-motion`, the highlight moves without animation

### Automatic Start for New Players (switched off at first)
**User story**
As an operator, I want to switch on an automatic first-visit tour later so that new players see it without looking for it, once the tour has proven itself.

**Acceptance criteria**
- `GUIDED_TOUR_AUTOSTART` (default `false`) is exposed to the frontend as `tour_autostart` in `GET /config`
- When it is `true`, the tour starts automatically the first time a logged-in user opens My Team in a browser with no `fantasy.tourSeen.v1` key, once no other popup is open. If a popup stays open for 10 seconds, it gives up for that visit
- When it is `false`, nothing starts automatically, and `fantasy.tourSeen.v1` is still written when the tour closes (Skip, Done, Esc or backdrop), so turning it on later doesn't re-show the tour to people who already took it
- The How to Play button always starts the tour, seen or not
- Pinned How to Play phrases in existing tests stay unchanged

### Works on Every Screen
**User story**
As a player on a phone, I want the tour to fit my screen so that I can read every step.

**Acceptance criteria**
- At 400 px wide the text box stays fully on screen, placed below or above the highlighted element, whichever has room
- The highlighted element is scrolled into view before its step shows
- The highlight follows the element if the window is resized or rotated during the tour

## Tour Includes the Weekly Report

### Weekly Report Step in the Tour
**User story**
As a new player taking the guided tour, I want the tour to show me the Weekly Report so that I know where to see what my cards scored each week.

**Acceptance criteria**
- `myTeamTourSteps()` in `frontend/app-tour.js` includes a step on `#weeklyReportBtn`, after the "Points" step (`#rosterTotals`) and before the "Leaderboards" step (`#tab-btn-leaderboard`). The full tour therefore has 7 steps.
- The step's title is "Weekly Report". Its body reads: "After each week ends, your recap is here: what each card scored, game by game, and every match result. A popup tells you when a new one is ready."
- The step highlights the button; it doesn't open the report.
- The step counter shows "6 / 7" on this step when every step is visible.
- When `#weeklyReportBtn` is missing or hidden, the step is dropped and the counter counts only the remaining steps, using the existing `startTour` filtering. This is the failure path.
- The box is positioned below the header button and kept inside the viewport (16 px margin) at desktop and phone widths, with the existing positioning logic.

### Recap Popup After the Tour
**User story**
As a player who just finished or skipped the tour, I want the "recap is ready" popup to appear then, if a recap is waiting, so that the tour doesn't make me miss it until my next visit.

**Acceptance criteria**
- When the tour closes (Done, Skip, Esc or a backdrop click), `endTour()` calls `checkWeeklySummaryHighlight()` if it exists and a user is logged in. That function fetches `GET /weekly-summary` and calls `maybeShowWeeklyRecapPrompt(data)`.
- The popup appears only under the existing rules: `show_prompt` is true, no other popup is open, and no password change is required. The tour no longer counts as open, because `_tour` is cleared before the check.
- When no recap is waiting (`show_prompt` false) or the user is logged out, nothing appears and no request is made logged out. This is the failure path.
- Ending the tour still marks it seen (`fantasy.tourSeen.v1`) and returns focus as before. If the popup appears, focus moves to its "Open recap" button.

## Flicker-Free Tab Switching

### No Flicker When Switching Tabs
**User story**
As a player, I want switching between tabs to be smooth so that the page doesn't flash or reload content that hasn't changed.

**Acceptance criteria**
- **New helper `renderIfChanged(el, html)`** in `frontend/app-globals.js`:
  - sets `el.innerHTML` only when `html` differs from the markup it last set on that element (kept in a `WeakMap`),
  - returns whether it wrote,
  - always writes the first time it sees an element.
- **Loaders that use it** for their main blocks:
  - `loadRoster` (`#rosterActiveGrid`, `#benchGrid`, `#rosterCombined`; `#rosterSeasonPoints` is set with `textContent`),
  - `loadDeck`, `loadBoosterTeams`,
  - `loadSeasonLeaderboard`, `loadWeeklyLeaderboard`, `loadPastSeasons`,
  - `loadPlayers`, `loadLeaderboard`, `loadTop`, `loadTeams`, `loadSchedule`,
  - the week selects in `loadWeeks` and `_populateLbWeekSelect`.
  
  A refresh with unchanged data leaves those elements' DOM nodes untouched: same node identity, no image reload, the selected dropdown option and the scroll position kept.
- **Placeholders:** `loadSchedule` and `loadBoosterTeams` show their "Loading…" text only while their container is still empty. Otherwise the old content stays until the new data replaces it.
- **Select boxes** rebuilt with changed options keep the previously selected value when it still exists. The My Team week select keeps the player's own pick; with none, the upcoming week stays the default.
- **View state:** the Players table sort and the "Show all" toggle of Top players by avg stay across a refresh, and a kept team-draw tile loses its selection like a rebuilt one.
- **Failure path:** when a refresh fails (network error, non-OK response), the content already on screen stays (except Past seasons, which hides its panel on error). The error appears in the tab's existing status line, as today, instead of replacing the content. A block that had never loaded shows the error as before.

### Same Tab or a Different Tab
**User story**
As a player, I want clicking the tab I'm on to just refresh quietly, and opening another tab to show it immediately, so that navigation feels instant.

**Acceptance criteria**
- **Same tab:** clicking it (or a code call to `switchTab(name)` for the active tab) leaves the tab classes and scroll position as they are. It runs the tab's loaders as a quiet refresh: unchanged data changes nothing on screen.
- **Different tab:** switching shows that tab's last content immediately, because hidden tab panels keep their DOM. It then runs the loaders as a quiet refresh. It restores the window scroll position the player last had on that tab during this page visit, or scrolls to the top on a first visit.
- **Existing callers keep working:** login, logout, a forced password change and the tour still land on their tab with fresh data.
- **Failure path:** a forced password change still overrides any requested tab with Profile, as `switchTab` does today.

### Weekly Report Keeps Its Frame
**User story**
As a player reading the Weekly Report, I want the popup window to stay the same size and in place when I switch weeks so that only its contents change.

**Acceptance criteria**
- **Fixed size:**
  - above 600 px wide, `.weekly-summary-modal` has a fixed `height: 85vh` (not just `max-height`), so the frame, title bar, week tabs and column headers don't move when content changes,
  - this includes the stacked layout (1100 px and below), where the popup scrolls as one page inside the fixed frame,
  - at 600 px and below the height is `92vh`.
- **Switching weeks:**
  - `selectWeeklySummaryTab()` no longer writes "Loading…" over existing content. The previous week's columns stay visible, dimmed by a `.is-loading` class (opacity about 0.6, a 150 ms fade, no animation with reduced motion), with `aria-busy="true"` on both column bodies.
  - When the new week's data arrives, both columns and their headers are replaced in one update, and both bodies scroll to the top.
  - A slow or out-of-order response for a week the player has already left is ignored, using a request counter, so it can't overwrite the week now shown.
- **Week cache:** weeks fetched while the popup is open are kept in memory (`_weeklySummaryCache`, keyed by week id). Switching back to one renders it at once, then refreshes quietly in the background with `renderIfChanged`. The cache is cleared when the popup closes, and for the revealed weeks on "Reveal results" (`revealAllWeeklySummaries`, the only reveal path), so revealed data is never stale.
- **Tab bar:** `renderWeeklySummaryTabs()` updates the week tab bar in place. It rebuilds the buttons only when the list of weeks (ids, labels, reveal state) changed, and otherwise only moves the `active` class.
- **First open:** the popup shows its full frame immediately, with "Loading…" in the empty columns only on that first load.
- **Failure path:** when loading a week fails, the error replaces that week's columns (there is nothing correct to keep). The frame stays the same size, and the dimming is removed. A cached week whose quiet refresh fails keeps its content.
- **Recap animation (#152):** it still plays only on a week's first revealed view and is stopped on a week switch, as today. Re-rendering a week during the same opening (from the cache or its quiet refresh) doesn't replay it; a recap interrupted by a week switch plays again on a later opening.

---

## Schedule Visuals (issue #156)

### See What's Happening Now at the Top of the Schedule
**User story**
As a player, I want the Schedule tab to open on what is live, what is next and what just finished, so that I don't scroll through the whole season to find tonight's matches.

**Acceptance criteria**
- A "Right now" strip at the top of the Schedule tab shows up to three cards:
  - **Live now:** a series with a matching live game. It shows both teams, its division, when it started and a "Watch live" link when a stream URL is known.
  - **Next up:** up to three next series with a planned time in the future, as compact rows with time, division, teams, streamer and a Watch button. The header shows a relative countdown to the first ("in 1 h 20 min", "in 2 days").
- Each watch button has the streamer name before it: the feed's stream label, or the channel from the stream URL. An upcoming fixture without a stream link shows "Caster TBD" and a greyed-out Watch button.
- With fewer than three timed series, Next up adds a row per coming week whose matches have no time yet, saying how far away it is ("Next week", "In 2 weeks") and how many matches it has ("7 matches, times to be announced"), with a View week button.
  - **Latest result:** the most recently played series.
- A card is left out when it has nothing to show. When all three are empty, the strip is not shown.
- The Latest result card follows hide mode: while the series is hidden it shows "Result hidden" with a Reveal button, and it never shows a score or MVP.
- Live state comes from `live_matches` rows with `ended_at` empty, seen in the last 15 minutes, with the same two team ids as the series in either order. The live game must have started within 12 hours of the series' time, so an earlier or later meeting of the same two teams is not marked live.
- Live state is never served from the one-hour schedule cache; it reflects the database at request time.

### Browse the Season Week by Week in Time Order
**User story**
As a player, I want to move through the season one week at a time, with matches in the order they are played, so that the schedule reads like a timeline and I can see where we are in it.

**Acceptance criteria**
- A week strip shows one chip per fantasy week (W1 … Wn), with its start date. The current week's chip is marked "This week" in orange and has `aria-current="date"`. Played weeks and upcoming weeks look different from each other.
- The tab opens on the current week. Between weeks it opens on the next upcoming week, and after the season on the last week.
- Clicking a chip, or the previous and next arrows, shows that week; a "This week" button returns to the current week.
- Within a week, series are grouped by day and sorted by time, earliest first, across both divisions. "Time TBD" fixtures have no real time, so they close the week in their own "Time TBD" group.
- In the current week, a "Now" line appears between the last started series and the next one, labelled with the current day and time.
- Division filter chips (All, Div 1, Div 2) narrow the week's list. A division with no series that week shows "No matches for this division this week."
- Every series appears in exactly one week, including feed fixtures, DB-derived results without a feed row, and "Time TBD" fixtures. A series outside every fantasy week goes to the nearest earlier week, or to the first week if none is earlier.
- With no fantasy weeks defined, the strip uses calendar weeks starting on Monday.
- At phone width the week strip scrolls sideways, the arrows are hidden, the Right now cards stack, and each series row becomes two lines: the time, division and action on top, the teams and score below.
- The stale notice, the "Loading..." shown only on the first load, and partial re-rendering (`renderIfChanged`) keep working as today.

### Hide Results Until I Choose to See Them
**User story**
As a player who watches matches later, I want to hide results on the Schedule tab and reveal them one series at a time, so that the schedule doesn't spoil a match I haven't watched yet.

**Acceptance criteria**
- A "Hide results" toggle in the Schedule header turns hide mode on and off. It has `aria-pressed`; its label stays "Hide results" and the pressed styling shows the state.
- Hide mode is on by default: on a first visit, or with nothing stored, results start hidden.
- The player's choice is remembered in the browser across visits and logins. Once they turn hide mode off, it stays off until they turn it back on.
- While hide mode is on, a played series that hasn't been revealed shows:
  - both team names at equal weight, with no winner styling,
  - the word "Played" in place of the score,
  - a "Reveal" button.
  
  It does not show the score, the number of games, per-game rows, kills, hero picks, the MVP or the "Not scored" badge.
- Clicking Reveal shows that series' score and winner styling. The game rows stay folded behind a "N games" button.
- A revealed series stays revealed across visits in the same browser.
- A week with hidden results shows a "Reveal week" button in its header, which reveals every played series in that week. Its chip in the week strip carries a small marker.
- After revealing on the Schedule tab, the week header offers "Hide week again", which hides that week's series revealed on the tab again.
- In a hidden row, team names are plain text rather than links to the team popup, which lists results.
- Turning hide mode off shows every result. Turning it back on hides again only the series that were never revealed.
- Upcoming and live series look the same in both modes.

### Results Already Seen in the Weekly Report Stay Revealed
**User story**
As a logged-in player, I want weeks I already revealed in my Weekly Report to show their results on the Schedule tab, so that hide mode doesn't hide what I've already seen.

**Acceptance criteria**
- For a logged-in user, the Schedule tab reads the `revealed` flags from `GET /weekly-summary`. In hide mode, every series placed in a revealed fantasy week shows its result without a click.
- That week's header shows "Revealed in your Weekly Report" and no "Reveal week" button.
- Revealing a series or a week on the Schedule tab does not change anything in the Weekly Report.
- For a logged-out viewer, or if `GET /weekly-summary` fails, the Schedule tab still works and falls back to the reveals stored in the browser.

### Played Results Read at a Glance
**User story**
As a player, I want each played series to show who won at a glance and keep game details one click away, so that a week's results fit on one screen.

**Acceptance criteria**
- A revealed series shows its series score in display type, the winner's name bright and bold, and the loser's name in muted text.
- Per-game rows are folded by default behind a "N games" button with `aria-expanded`. When unfolded, each game row shows:
  - game number,
  - each side's hero icons,
  - the kills score,
  - the MVP with a star,
  - the duration,
  - the OpenDota link,
  - the "Not scored" badge where it applies.
- The Latest result card's "Games" button jumps to that series' week (normally the current week) and unfolds its games.
- An upcoming series shows "vs" and no games button, as today. A fixture past its date with no resolved games shows "No result". A played series with a result but no resolved games shows its score and no games button.
