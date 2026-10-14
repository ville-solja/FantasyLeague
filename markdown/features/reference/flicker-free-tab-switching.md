# Flicker-Free Tab Switching

Switching tabs, and switching weeks in the Weekly Report, updates only what changed, so the page doesn't flash or jump. For every player moving around the app. Resolves issue #159 (player feedback).

*(see `markdown/plans/plan-issue-159-flicker-free-tab-switching.md`)*

---

## Why it flickered

- **Main tabs:** `switchTab()` re-ran every loader on each click, and the loaders rewrote whole blocks with `innerHTML` even when the data hadn't changed. This reloaded card images, reset dropdowns and rebuilt tables. The schedule and the team-draw grid also showed "Loading…" over their content on every visit.
- **Weekly Report:** the popup had only a `max-height`. Switching weeks replaced both columns with "Loading…", so the window shrank and grew back.

## How it works

Frontend only: no endpoint, env var or database change.

### Render only when changed (`frontend/app-globals.js`)

- **`renderIfChanged(el, html)`** sets `el.innerHTML` only when `html` differs from the markup it last wrote into that element, kept in a module-level `WeakMap` (`_lastHtml`). It always writes on first sight of an element, and again when the element was emptied elsewhere (`el.innerHTML === ""`). It returns whether it wrote; `null` returns `false`. It compares against the stored string, not `el.innerHTML`, because the browser re-serialises markup differently.
- **`forgetRendered(el)`** drops the stored markup, so the next `renderIfChanged` writes.
- **`renderSelectIfChanged(sel, html)`** is `renderIfChanged` for a `<select>`: after a write it restores the previous value when that option still exists.

**The rule for a managed element:** every write to it goes through `renderIfChanged`, including placeholders and error messages. Code that rebuilds its children by hand calls `forgetRendered(el)` first. The #152 recap animation in `_playRecap` is the one place that does this. Cosmetic changes may stay on kept nodes: an expanded leaderboard row, the roster settle-animation class, a hidden broken logo. A kept booster tile's selection is cleared on each load. Changed data always changes the markup, so it always writes. A card reroll changes the image URL (`bumpCardImageCacheBust`), so the roster re-renders.

### Loaders

| Loader | Elements | Notes |
|---|---|---|
| `loadRoster` (`app-roster.js`) | `#rosterActiveGrid`, `#benchGrid`, `#rosterCombined` | Settle animation only on grids that were redrawn |
| `loadWeeks` → `_renderWeekSelector` | `#rosterWeekSelect` | Keeps the player's own pick; with none, the upcoming week is the default |
| `loadDeck` (`app-cards.js`) | `#deck-{rarity}` | |
| `loadBoosterTeams` | `#boosterTeamGrid` | "Loading…" only when empty; clears a kept tile's selection |
| `loadSeasonLeaderboard`, `loadWeeklyLeaderboard`, `loadPastSeasons` / `loadPastSeasonStandings` (`app-leaderboard.js`) | standings bodies, `#pastSeasonSelect` | Past-season choice kept and reloaded |
| `_populateLbWeekSelect` | `#lbWeekSelect` | Value kept |
| `loadLeaderboard` → `_renderLeaderboard`, `loadTop` | `#leaderboardBody`, `#topBody` | "Show all" state (`_lbShowAll`) kept across refreshes |
| `loadPlayers` → `renderPlayers`, `_renderMvpLeaderboard`, `loadTeams`, `loadSchedule` (`app-players.js`) | `#playersBody`, `#mvpLeaderboardBody`, `#teamsBody`, `#scheduleContent` | Players sort (`_playerSort`) kept across refreshes; schedule "Loading..." only when empty |

**Errors:** a failed refresh (network error or non-OK response) only sets the tab's status line (`setStatus(...)`, or `#rosterStatus`), so content already on screen stays. Most loaders throw on a non-OK response into their `catch`; the exceptions handle it themselves:

- `loadSchedule` sets `#scheduleStatus` inline. On a first load it also empties its "Loading..." placeholder.
- `loadBoosterTeams` reports through `showError`: in the grid on a first load, in `#boosterStatus` once the grid has content.
- `loadPastSeasonStandings` sets `#pastSeasonStatus` inline.
- `loadPastSeasons` hides `#pastSeasonsPanel` on error (and when there are no archived seasons), so its content does not stay.
- `loadWeeks` returns silently on a non-OK response or an error; the week select keeps its options.

### Roster drag-and-drop

The roster DOM outlives a render. Since #186 the grids are a keyed render (`renderRosterLayout()` in `app-roster.js`):

- Each card keeps its `.card-slot` node (`_rosterNodes`) and each empty slot its placeholder; a render only reorders nodes and rewrites a card's inner markup when it changed. Both grids are then marked with `forgetRendered`.
- The pointer, click and key listeners are delegated to `#rosterActiveGrid` and `#benchGrid`, bound once (`_bindRosterGrid`, guarded by `grid._rosterBound`; the grids are never replaced). The handlers read the current `_layout`, not one captured at bind time.
- A locked week is gated in the handlers (`_rosterLocked`), not in the markup. See [My Team Drag-and-Drop](my-team-drag-and-drop.md#drag).

### `switchTab(name)`

1. The forced-password-change redirect to Profile comes first, as before.
2. **Same tab:** the tab classes and scroll position are left as they are.
3. **Different tab:**
   - The outgoing tab's `window.scrollY` is saved in `_tabScroll`.
   - The classes switch.
   - The incoming tab's saved position, or 0 on a first visit, is restored in a `requestAnimationFrame`.
4. The tab's loaders always run, as a quiet refresh. Login, logout, a forced password change and the tour still get fresh data this way.

### Weekly Report (`frontend/app-weekly-summary.js`, `style.css`)

- **Fixed frame:** `.weekly-summary-modal { height: 85vh; max-height: 85vh }`, and `height: 92vh` at 600 px and below. In the stacked layout (1100 px and below) the popup still scrolls as one page.
- **Dimming:** `.weekly-summary-col-body.is-loading { opacity: .6; transition: opacity 150ms }`. The transition is off under `prefers-reduced-motion`. `_setWeeklySummaryLoading(on)` toggles the class and `aria-busy="true"` on both column bodies.
- **`selectWeeklySummaryTab(weekId)`:**
  1. Returns at once when the week is already the active one (issue #202: clicking the active tab does nothing; closing the popup and revealing reset the active week, so reopening still selects it). Before that, it drops the cache if it belongs to another signed-in user.
  2. Bumps `_weeklySummaryReq`, then calls `_stopRecap()`.
  3. Shows the week at once:
     - a week in `_weeklySummaryCache` (a `Map` keyed by week id, entries `{data, at}` since #202) renders at once, without the recap; when its copy is less than 60 s old, `selectWeeklySummaryTab` stops here, with no fetch,
     - otherwise, if both columns are empty, "Loading…" shows,
     - otherwise the shown week is dimmed.
  4. Fetches the week. A response whose request number is no longer current is ignored.
  5. Stores the data in the cache and calls `renderWeeklySummaryContent(data, {playRecap})`. That function renders both columns with `renderIfChanged` and the headers in the same synchronous call. `playRecap` is false for a week that was already cached.
  6. Scrolls both bodies to the top only when the week changed.
  7. If the fetch fails, the error replaces the columns of an uncached week. A cached week keeps its content.
- **Cache clearing:**
  - `closeWeeklySummary()` bumps the request counter, resets the active week and removes the dimming. Since issue #202 it keeps the cache for the page visit; see `markdown/features/core/weekly-summary.md` › "Client Cache" for its lifetime and clearing (reveal, logout, user switch, a changed week list).
  - `revealAllWeeklySummaries()` deletes every listed week from the cache before re-selecting the active one. It is the only reveal path; there is no single-week reveal.
- **Tab bar:** `renderWeeklySummaryTabs()` rebuilds the buttons only when the `week_id:label:revealed` signature (`_weeklySummaryTabsSig`) or the button count changed. Otherwise it only moves the active mark.
- **Recap (#152):** it plays on a week's first revealed view and stops on a week switch or close. Rendering a week again from the cache or its quiet refresh shows the finished state. Since issue #202 the cache lasts for the page visit, so a recap plays at most once per week per page visit: an interrupted recap does not play again on reopening (the week is cached); the **Replay** button plays it. On a later page visit it plays again only if it never finished, since the week is marked played only at the end.

## Tests

`backend/tests/test_issue_159_flicker_free_tab_switching.py` checks the code statically. With Node available, it also runs `renderIfChanged` against a fake element.
