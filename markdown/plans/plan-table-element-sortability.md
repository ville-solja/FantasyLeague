# Plan: Table Element Sortability

## Context
The Players tab displays a table of all players with stat columns (name, team, avg fantasy
points, avg K/D/A, GPM, etc.) but the rows are currently in a fixed, unordered sequence.
Users who want to find the highest-scoring player or the one with the best GPM must scan
the entire table manually. Clickable sortable column headers fix this with a standard UX
pattern: click once to sort ascending, click again to flip to descending, with a visual
arrow indicator on the active column. The feature is implemented entirely client-side — no
new API endpoints are needed. *Resolves GitHub issue #39.*

## User Stories

### Sort Players Table by Column Header
**User story**
As a user, I want to click a column header in the Players tab to sort the table by that
column so that I can quickly find top-performers or compare players on a stat I care about.

**Acceptance criteria**
- Clicking any column header sorts all visible rows by that column
- Numeric columns (fantasy points, K/D/A, GPM) default to descending on first click so
  the highest values appear at the top
- Text columns (player name, team) default to ascending on first click (A → Z)
- The active sort column is visually indicated with an arrow icon (↑ or ↓) next to the
  header label
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

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app.js` (or `frontend/app-players.js`) | Add `sortTable()` helper + click handlers on `<th>` elements |
| `frontend/style.css` | Add `.sort-asc` / `.sort-desc` styles for the active-column arrow indicator |
| `frontend/index.html` | Add sort classes or `data-col` attributes to Players table headers |

### Step 1 — Identify the players table in the frontend
Locate the `<table>` element that renders the players list in the Players tab. Note the
exact `<th>` element IDs or classes and the column order. Identify how rows are currently
rendered (e.g. via `renderPlayers()` in `app.js`).

### Step 2 — Add sort state and comparator logic
Add a module-level sort state object:
```js
let playerSort = { col: null, dir: "desc" };
```

Write a `sortPlayers(rows, col, dir)` function that returns a sorted copy of the rows
array. For numeric columns use numeric comparison; for string columns use
`localeCompare`. Determine column type from a config map:
```js
const PLAYER_COL_TYPES = {
  name: "string", team: "string",
  avg_pts: "number", avg_kills: "number", avg_deaths: "number",
  avg_assists: "number", avg_gpm: "number",
};
```

### Step 3 — Wire click handlers to headers
After the table is rendered, attach a `click` listener to each `<th>`. On click:
1. If the column is already active, flip `playerSort.dir`; otherwise set `playerSort.col`
   and reset to the column's default direction.
2. Re-render the table with the sorted rows.
3. Update the active-column visual: remove `.sort-asc` / `.sort-desc` from all headers,
   add the appropriate class to the clicked header.

Use `addEventListener` + `textContent` — never `innerHTML` with untrusted data (player
names come from the API).

### Step 4 — Add CSS indicators
```css
th.sort-asc::after  { content: " ↑"; }
th.sort-desc::after { content: " ↓"; }
th[data-sortable]   { cursor: pointer; user-select: none; }
```

### Step 5 — Reset sort on tab switch
When the Players tab is closed or the page reloads, reset `playerSort` to its initial
state so the next visit starts unsorted.

---

## Verification
- Open Players tab — table renders in default (unsorted) order, no arrows visible
- Click a numeric column header — rows sort descending, arrow ↓ appears
- Click the same header again — rows sort ascending, arrow flips to ↑
- Click a different header — sort moves to the new column, previous arrow cleared
- Click player name header — sorts A → Z on first click
- Search or filter (if applicable) — sorted order is maintained within the filtered set
- Mobile: touch targets on headers large enough to tap comfortably
