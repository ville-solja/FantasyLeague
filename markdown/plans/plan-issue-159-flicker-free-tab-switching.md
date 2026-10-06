# Plan: Flicker-Free Tab Switching

## Context
Player feedback in issue #159, translated from Finnish: switching tabs makes windows flicker. Updates should be partial or state-driven, depending on whether the player clicks the tab they're on or a different one. The Weekly Report should also keep its whole window in place when you switch weeks, and redraw only what's inside.

**What causes it today:**
- **Main tabs.** `switchTab(name)` in `frontend/app-globals.js` re-runs every loader for the tab on each click, even when that tab is already open. Most loaders rewrite their whole block with `innerHTML`, even when the data hasn't changed:
  - `loadRoster`, `loadDeck`, the leaderboard tables, the players and teams tables, the week selects.
  
  Re-creating the same markup reloads card images, resets dropdowns and rebuilds tables, which shows as a flash. Two loaders also replace content with a "Loading…" placeholder on every visit:
  - `loadSchedule` sets `#scheduleContent` to "Loading...",
  - `loadBoosterTeams` sets `#boosterTeamGrid` to "Loading…".
- **Weekly Report.**
  - `.weekly-summary-modal` has only `max-height: 85vh`, so the popup's height follows its content.
  - `selectWeeklySummaryTab()` replaces both columns with "Loading…" before fetching. The popup shrinks to two lines, then grows back when the data arrives.
  - `renderWeeklySummaryTabs()` rebuilds the week tab bar on every open.

**The approach (plain JS, no framework):**
- **Render only when changed.** A small helper skips a DOM write when the new markup equals what that element last got, so a refresh with unchanged data changes nothing on screen.
- **No placeholders over existing content.** Loading text shows only on a block's very first load. Later refreshes keep the old content until the new data is in.
- **Same tab vs a different tab.** Clicking the open tab keeps its scroll position and does a quiet refresh. Opening a different tab shows its last content at once, then refreshes quietly.
- **Fixed Weekly Report frame.** The popup has a fixed height. Switching weeks keeps the previous week visible, slightly dimmed, until the new one is ready, and then swaps both columns at once. Weeks already loaded during this opening come from memory.

**Assumptions:**
- `switchTab` is also called from code to load data: after login and logout (`app-auth.js`), when a password change is forced, and by the tour (`app-tour.js`). So clicking the open tab still refreshes its data rather than doing nothing. The refresh is just invisible when nothing changed.
- No new dependency or framework; the `innerHTML` rendering style stays.
- Popup content inside tabs (player and team popups) is out of scope. Those popups open fresh by design.
- Frontend only: no backend, API, env var or migration changes.

Resolves GitHub issue #159.

## User Stories

### No Flicker When Switching Tabs
**User story**
As a player, I want switching between tabs to be smooth so that the page doesn't flash or reload content that hasn't changed.

**Acceptance criteria**
- **New helper `renderIfChanged(el, html)`** in `frontend/app-globals.js`:
  - sets `el.innerHTML` only when `html` differs from the markup it last set on that element (kept in a `WeakMap`),
  - returns whether it wrote,
  - always writes the first time it sees an element.
- **Loaders that use it** for their main blocks:
  - `loadRoster` (`#rosterActiveGrid`, `#benchGrid`, the totals),
  - `loadDeck`, `loadBoosterTeams`,
  - `loadSeasonLeaderboard`, `loadWeeklyLeaderboard`, `loadPastSeasons`,
  - `loadPlayers`, `loadLeaderboard`, `loadTop`, `loadTeams`, `loadSchedule`,
  - the week selects in `loadWeeks` and `_populateLbWeekSelect`.
  
  A refresh with unchanged data leaves those elements' DOM nodes untouched: same node identity, no image reload, the selected dropdown option and the scroll position kept.
- **Placeholders:** `loadSchedule` and `loadBoosterTeams` show their "Loading…" text only while their container is still empty. Otherwise the old content stays until the new data replaces it.
- **Select boxes** rebuilt with changed options keep the previously selected value when it still exists.
- **Failure path:** when a refresh fails (network error, non-OK response), the content already on screen stays. The error appears in the tab's existing status line, as today, instead of replacing the content. A block that had never loaded shows the error as before.

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
  - above 1100 px wide, `.weekly-summary-modal` has a fixed `height: 85vh` (not just `max-height`), so the frame, title bar, week tabs and column headers don't move when content changes,
  - at 600 px and below the height is `92vh`,
  - in the stacked layout (1100 px and below) the popup scrolls as one page, as today.
- **Switching weeks:**
  - `selectWeeklySummaryTab()` no longer writes "Loading…" over existing content. The previous week's columns stay visible, dimmed by a `.is-loading` class (opacity about 0.6, a 150 ms fade, no animation with reduced motion), with `aria-busy="true"` on both column bodies.
  - When the new week's data arrives, both columns and their headers are replaced in one update, and both bodies scroll to the top.
  - A slow or out-of-order response for a week the player has already left is ignored, using a request counter, so it can't overwrite the week now shown.
- **Week cache:** weeks fetched while the popup is open are kept in memory (`_weeklySummaryCache`, keyed by week id). Switching back to one renders it at once, then refreshes quietly in the background with `renderIfChanged`. The cache is cleared when the popup closes, and for the revealed weeks on "Reveal results" (`revealAllWeeklySummaries`, the only reveal path), so revealed data is never stale.
- **Tab bar:** `renderWeeklySummaryTabs()` updates the week tab bar in place. It rebuilds the buttons only when the list of weeks (ids, labels, reveal state) changed, and otherwise only moves the `active` class.
- **First open:** the popup shows its full frame immediately, with "Loading…" in the empty columns only on that first load.
- **Failure path:** when loading a week fails, the error replaces that week's columns (there is nothing correct to keep). The frame stays the same size, and the dimming is removed.
- **Recap animation (#152):** it still plays only on a week's first revealed view and is stopped on a week switch, as today. Re-rendering from the cache doesn't replay it.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-globals.js` | `renderIfChanged(el, html)` helper; `switchTab` handles same vs different tab and per-tab scroll memory |
| `frontend/app-roster.js` | `loadRoster`, `loadWeeks` use `renderIfChanged`; week select keeps its value |
| `frontend/app-cards.js` | `loadDeck`, `loadBoosterTeams` use `renderIfChanged`; placeholder only when empty |
| `frontend/app-leaderboard.js` | Season, weekly and past-season tables, `loadLeaderboard`, `loadTop`, `_populateLbWeekSelect` use `renderIfChanged` |
| `frontend/app-players.js` | `loadPlayers`, `loadTeams`, `loadSchedule` use `renderIfChanged`; schedule placeholder only when empty; errors keep content |
| `frontend/app-weekly-summary.js` | Keep-and-dim week switch, request counter, `_weeklySummaryCache`, in-place tab bar, one-step column swap |
| `frontend/style.css` | `.weekly-summary-modal` fixed height; `.weekly-summary-col-body.is-loading` dimming with reduced-motion rule |
| `markdown/features/reference/flicker-free-tab-switching.md` | Feature doc (stub at planning) |
| `markdown/ui_description/weekly-report.md` | Fixed frame and loading state |
| `backend/tests/test_issue_159_flicker_free_tab_switching.py` | Static checks |
| `backend/tests/test_issue_85_split_admin_router.py` | Suite-size tripwire bump |

### Step 1 — `renderIfChanged`
```js
const _lastHtml = new WeakMap();
/** Set el.innerHTML only when html differs from what this function last set there. */
function renderIfChanged(el, html) {
  if (!el) return false;
  if (_lastHtml.get(el) === html && el.innerHTML !== "") return false;
  el.innerHTML = html;
  _lastHtml.set(el, html);
  return true;
}
```

The empty check covers code that clears an element directly. Comparing against the stored string, not `el.innerHTML`, avoids false differences from how the browser re-serialises markup.

### Step 2 — Loaders
- **Writes:** replace each loader's main `x.innerHTML = …` with `renderIfChanged(x, …)`.
- **Event handlers:** check whether a loader attaches listeners after rendering (for example, drag-and-drop on the roster in `app-roster.js`). Those must still run when the DOM wasn't rewritten, or move to delegated listeners on a stable parent.
- **Placeholders:** in `loadSchedule` and `loadBoosterTeams`, write the placeholder only when the container is empty.
- **Errors:** set the status line and leave existing content.
- **Selects:** remember `sel.value`, call `renderIfChanged`, then restore the value if that option still exists.

### Step 3 — `switchTab`
- **Same tab:** if `name` is already the active tab, skip the class toggling and scrolling, and run the loaders.
- **Different tab:** save `window.scrollY` for the outgoing tab in `_tabScroll[name]`, switch the classes, restore the saved scroll (or 0) in a `requestAnimationFrame`, then run the loaders.
- Keep the forced-password-change redirect first, as now.

### Step 4 — Weekly Report
- **CSS:** set `.weekly-summary-modal { height: 85vh; }` and `92vh` in the 600 px rule. Leave `max-height` in place for very short screens. Add `.weekly-summary-col-body.is-loading { opacity: .6; transition: opacity 150ms; }` and turn the transition off under reduced motion.
- **`selectWeeklySummaryTab(weekId)`:**
  1. Bump `_weeklySummaryReq` and stop the recap animation.
  2. If the week is in `_weeklySummaryCache`, render it at once.
  3. Otherwise add `.is-loading` and `aria-busy`, or show "Loading…" if the columns are empty.
  4. Fetch the week. Ignore the response if `_weeklySummaryReq` has moved on.
  5. Store it in the cache and render, using `renderIfChanged` for both columns and headers.
  6. Remove `.is-loading`. Scroll to the top only when the week changed.
- **Clearing the cache:** on `closeWeeklySummary()` (whole cache), and in `revealAllWeeklySummaries()` (the listed weeks; there is no single-week reveal path).
- **`renderWeeklySummaryTabs()`:** compare a signature of the week list (`week_id:label:revealed`) with the last one. Rebuild only when it differs; otherwise just call `_markActiveWeeklySummaryTab`.

### Step 5 — Tests and docs
`backend/tests/test_issue_159_flicker_free_tab_switching.py`, as static checks:
- **The helper:** `renderIfChanged` exists in `app-globals.js` with a `WeakMap`.
- **The loaders:** each listed loader calls it. `loadSchedule` and `loadBoosterTeams` write "Loading" only behind an empty-content check.
- **`switchTab`:** has a same-tab branch and a `_tabScroll` map, and still redirects to Profile on a forced password change.
- **Weekly Report CSS:** `.weekly-summary-modal` has `height: 85vh` (and `92vh` at 600 px), and the `.is-loading` rule is in the reduced-motion block.
- **`selectWeeklySummaryTab`:** has no unconditional "Loading…" write, has the request counter and the cache, and the cache is cleared in `closeWeeklySummary` and the reveal functions.
- **`renderWeeklySummaryTabs`:** has the signature check.

Update the #151 and #152 tests if they pin `max-height: 85vh` or the old Loading write. Bump the suite-size tripwire. Fill in the feature doc and `ui_description/weekly-report.md`, and note the behaviour in the tab UI descriptions where they mention loading.

## Verification
- **Switching tabs:** in a browser, go back and forth between My Team, Leaderboards, Players and Schedule. Content doesn't flash. Card images on My Team don't reload when nothing changed (check the DevTools Network tab). The roster week select keeps its value.
- **Clicking the open tab:** nothing visibly changes. A new match or draw that changed the data does update the page.
- **Scroll memory:** scroll down on Players, switch to Leaderboards and back. Players is at the same position.
- **Weekly Report, switching weeks:** the frame, tabs and headers don't move. The old week dims briefly, then both columns change together. Switch quickly between three weeks: the last one clicked is the one shown. Switch back to a viewed week: it appears instantly.
- **Weekly Report, reveal:** reveal a week. Its revealed content shows (not a cached pre-reveal copy), and the recap animation plays once.
- **Errors:** with the network offline, switching tabs keeps the content and shows the error line; switching to an unloaded report week shows the error in a frame of the same size.
- **Narrow screens:** at 375 px, the Weekly Report frame keeps its size and the stacked layout scrolls.
- `cd backend && python3 -m pytest tests/ -q` passes.
