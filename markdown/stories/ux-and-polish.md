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
- Tab contains three clearly separated sections: Getting Started, Twitch & MVP, and Scoring & Modifiers
- Getting Started section explains: draw a card using a token, activate up to 5 cards into the roster, roster locks weekly, points accumulate from locked rosters
- Getting Started section explains how to obtain more tokens: week lock bonus, Twitch extension drops, promo codes
- Twitch & MVP section explains the broadcaster MVP selection flow and that the selected MVP receives a point bonus for that match
- Scoring & Modifiers section lists the scoring stats and reads live weight values from the server to show current multipliers
- Scoring section explains card rarity bonuses and card modifier bonuses using live weight values
- Tab renders correctly with no active session (weights endpoint is public)

---

### Streamer MVP Instructions
**User story**
As a Kanaliiga streamer, I want the How to Play tab to explain the Twitch extension MVP flow so that I can set it up and use it without reading separate documentation.

**Acceptance criteria**
- The Twitch & MVP section explains: install the extension, use Quick Actions to select a series → match → player
- Explains that token drops fire automatically on MVP confirmation (once per match)
- Explains that the MVP selection also grants a fantasy score bonus to that player's match
- The section is visible to all users (not restricted to admins or streamers)

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
