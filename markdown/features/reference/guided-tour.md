# Guided Tour

A short spotlight tour of My Team, started from the How to Play tab. An automatic first-visit start exists but is off by default (`GUIDED_TOUR_AUTOSTART`). It explains how to draw cards, set the roster and see the scoring, one highlighted element at a time. Resolves issue #144.

---

## How it works

- **Engine:** `frontend/app-tour.js`, in plain JavaScript with no library, loaded locally before `app-init.js`. A fixed layer (`.tour-root`, above the popups) holds a transparent backdrop, a cut-out (`.tour-spotlight`) whose large `box-shadow` darkens everything except the current element, and a text box (`.tour-box`, `role="dialog"`, `aria-modal="true"`, labelled by its title) with the title, one or two sentences, a step counter ("2 / 6"), and **Skip** / **Next** (**Done** on the last step). All text is set with `textContent`.
- **Steps** (`myTeamTourSteps()`), built when the tour starts:
  1. **Draw a card** (`#drawBtn`) — "A draw costs 1 of your {token name}, or {cost} for a card from a team you pick", with the configured `token_name` (`_tokenName`) and the live `team_booster_cost` (`_teamBoosterCost`) from `GET /config`; unowned players first
  2. **Chances** (`.rarity-grid`) — chance of each rarity per draw; rarer cards score a higher bonus
  3. **Your roster** (`#rosterActiveGrid`) — up to N cards, where N is the number of slots rendered in the grid (`ROSTER_SLOTS` in `app-roster.js`, not a server value); only active cards score. If the grid is empty, the copy reads "up to the roster limit" instead
  4. **Weekly lock** (`#rosterWeekSelect`) — the roster locks automatically when the week starts
  5. **Points** (`#rosterTotals`, the This week / Season line) — active cards score from every league match that week
  6. **Leaderboards** (`#tab-btn-leaderboard`) — weekly and season ranks; full rules are in How to Play

  `startTour(steps, {force})` drops steps whose element is missing or hidden (no client rects or `visibility: hidden`) and counts only the rest. A step whose element vanishes mid-tour is dropped too.
- **Positioning:** before each step the element is scrolled to the middle of the screen (`scrollIntoView({block: "center"})`). The box goes below the element, or above it when there's no room, and is clamped inside the viewport with a 16 px margin (box width `min(340px, 100vw - 32px)`). Resize and scroll events recompute the position in a `requestAnimationFrame`; the listeners are removed when the tour closes.
- **Controls:** Esc or a backdrop click skips; Enter or → goes to the next step; ← goes back. Tab cycles between the box's buttons. Focus moves into the box when the tour opens and returns to the previously focused element when it closes.
- **Seen flag:** Skip, Done, Esc and backdrop all write `localStorage["fantasy.tourSeen.v1"] = "1"`, even while autostart is off, so turning it on later doesn't re-show the tour. Reads and writes are wrapped in `try/catch`; with blocked storage the page still works and the tour just counts as unseen.
- **Reduced motion:** with `prefers-reduced-motion: reduce` the cut-out moves without a transition and scrolling is instant.

### Starting from How to Play

**Show the tour** (`#htpTourBtn`) sits under the Getting Started intro on the How to Play Users subtab and calls `startTourFromHowToPlay()`. Logged out, it opens the login popup (`showLogin()`). Logged in, it calls `switchTab('team')`, waits up to 5 seconds for the roster grid to render, then calls `startTour(myTeamTourSteps(), {force: true})`, which ignores the seen flag.

### Automatic start (off by default)

`loadConfig()` in `frontend/app-globals.js` stores `GET /config`'s `tour_autostart` in `_tourAutostart`. `switchTab('team')` calls `maybeStartMyTeamTour()` after `loadRoster()` finishes. That function returns at once unless `_tourAutostart` is true, the user is logged in, no tour is running and the seen flag is absent. It then waits until no `.modal-overlay` without `.hidden` is visible (Notification and Weekly Report popups), checking every 250 ms and giving up after 10 seconds for that visit, re-checks that My Team is still the active tab, and starts the tour.

## Endpoints

### `GET /config`
Adds `tour_autostart` (boolean). It is `true` only when `GUIDED_TOUR_AUTOSTART` is `true` (any case, surrounding spaces ignored); `1`, `yes`, an empty value or an unset variable all give `false`. The variable is read on each request, not frozen at import, so tests can toggle it with `monkeypatch.setenv`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GUIDED_TOUR_AUTOSTART` | `false` | Start the tour automatically on a player's first visit to My Team (per browser) |

## Files

| File | Role |
|---|---|
| `frontend/app-tour.js` | Engine, step list, `maybeStartMyTeamTour()`, `startTourFromHowToPlay()` |
| `frontend/app-globals.js` | `_tourAutostart` from `GET /config`; autostart hook in `switchTab('team')` |
| `frontend/index.html` | `#htpTourBtn`, `#rosterTotals`, `<script src="/app-tour.js">` before `app-init.js` |
| `frontend/style.css` | `.tour-*` styles with the design tokens, reduced-motion rule |
| `backend/main.py` | `tour_autostart` in `GET /config` |
| `backend/tests/test_issue_144_guided_tour.py` | Static frontend checks and `get_config` tests |

Not covered by tests (needs a browser): placement at phone width, scrolling, following resize, focus movement, waiting for popups, blocked storage.
