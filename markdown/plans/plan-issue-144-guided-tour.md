# Plan: First-Time Guided Tour (MVP)

## Context
New players get no guidance. The rules live on the How to Play tab, which most people never open, and the first screen they reach (My Team) shows a draw panel, a roster grid, a week selector and point totals with no explanation. Issue #144 asks for the simplest tour that still covers the basics: **how to draw cards, set the roster, and see the scoring**.

The design follows the pattern noted in the competitor review: a dark overlay with a highlighted cut-out around one element at a time, one or two sentences per step, shown once and replayable. It is built in plain JavaScript with no library, to fit the existing frontend.

**Decision (2026-10-01):** at first the tour is **only started from the How to Play tab**. It is not shown automatically to anyone. Starting it automatically on a player's first visit is built but switched off with `GUIDED_TOUR_AUTOSTART` (default `false`), so it can be turned on later without a code change.

**Assumptions:**
- **One tour, on My Team, for logged-in users only.** Logged-out visitors can't draw or set a roster.
- **"Seen" is remembered per browser** in `localStorage` under a versioned key, `fantasy.tourSeen.v1`. Bumping the version shows a changed tour again. Server-side "seen" per account is out of scope.
- **The tour waits for popups.** Notification and Weekly Report popups can open on page load, so the tour waits until no modal (`.modal-overlay` without `.hidden`) is open, checking briefly and giving up after 10 seconds for that visit.
- **Copy uses live values:** the token name and team draw cost come from `/config` (`_tokenName`, `_teamBoosterCost`), and the roster limit is the number of slots rendered on My Team (`ROSTER_SLOTS` in `app-roster.js`, not a server value), never fixed text.
- **The brand rules apply** (from `/ui-design`): Big Shoulders Text for titles, the flame palette, no pill buttons, no emoji.

Resolves GitHub issue #144.

## User Stories

### Start the Tour from How to Play
**User story**
As a player, I want to start a short guided tour from the How to Play tab so that I can learn how to draw cards, set my roster and see my points when I choose to.

**Acceptance criteria**
- The How to Play Users subtab has a "Show the tour" button near the top. For a logged-in user it switches to My Team and starts the tour from step 1. For a logged-out visitor it opens the login popup instead
- The tour is **not** started automatically for anyone while `GUIDED_TOUR_AUTOSTART` is `false`, the default
- The tour has these steps, in order, each highlighting one element with a title and one or two sentences:
  1. **Draw a card** (`#drawBtn`): a draw costs 1 of your tokens (shown with the configured token name), or the team draw cost for a card from a team you pick; you get players you don't own yet first
  2. **Chances** (`.rarity-grid`): your chance of each rarity per draw; rarer cards score a higher bonus
  3. **Your roster** (`#rosterActiveGrid`): put up to {roster limit} cards on your active roster; only active cards score. The roster limit is the number of slots rendered on My Team (`ROSTER_SLOTS` in `app-roster.js`), not a server value; if the grid is empty it reads "up to the roster limit" instead
  4. **Weekly lock** (`#rosterWeekSelect`): your roster locks automatically when the week starts, so make changes before then
  5. **Points** (the This week / Season totals): your active cards score from every league match that week; totals update as matches come in
  6. **Leaderboards** (`#tab-btn-leaderboard`): see how you rank each week and over the season; full rules are in How to Play
- The text comes from live values (configured token name, team draw cost, rendered roster slot count), so it never shows a stale number or name
- A step whose element is missing or hidden is skipped, and the step count adjusts

### Control the Tour
**User story**
As a player, I want to skip or step through the tour easily so that it never gets in my way.

**Acceptance criteria**
- Buttons: **Skip** and **Next**, with **Done** on the last step, plus a step counter ("2 / 6")
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

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-tour.js` *(new)* | Tour engine (overlay, cut-out, positioning, keyboard, focus, storage) and the My Team step list |
| `frontend/index.html` | Load `app-tour.js` before `app-init.js`; "Show the tour" button in How to Play Users |
| `frontend/style.css` | Overlay, cut-out and tour box styles using the existing tokens |
| `frontend/app-globals.js` | Read `tour_autostart` from `/config`; when true, start the tour from `switchTab('team')` once the roster has loaded, if not seen |
| `backend/main.py` | `GET /config` returns `tour_autostart` from `GUIDED_TOUR_AUTOSTART` |
| `.env.example` | `GUIDED_TOUR_AUTOSTART=false` |
| `markdown/ui_description/my-team.md`, `markdown/features/reference/how-to-play-tab.md`, `markdown/features/reference/guided-tour.md` | Docs |
| `backend/tests/test_issue_144_guided_tour.py` | Static checks of the frontend (steps, targets, storage key, no `confirm`/`prompt`, escaping, replay button) |

### Step 1 — Engine
`app-tour.js` exposes `startTour(steps, {force})` and `maybeStartMyTeamTour()`.

- **Overlay:** a fixed full-screen layer holding:
  - a cut-out box placed over the target's bounding rectangle, with a large `box-shadow` that darkens everything else,
  - a text box (`role="dialog"`) with the title, body, counter and buttons.
- **Text:** set with `textContent` only; there is no HTML from data.
- **Positioning:**
  - recompute on resize and scroll with `requestAnimationFrame`,
  - call `scrollIntoView({block: "center"})` before each step,
  - place the box below the target, or above it when there's no room, and clamp it inside the viewport with a 16 px margin.
- **Storage:** read and write `localStorage` inside `try/catch`.

### Step 2 — My Team steps and trigger
Build the step list with live values: `_tokenName`, `_teamBoosterCost`, and the roster limit as the number of slots rendered in `#rosterActiveGrid` (falling back to "up to the roster limit" when the grid is empty). After `loadRoster` finishes on the team tab, call `maybeStartMyTeamTour()`. It returns immediately unless `tour_autostart` is true; then it checks the logged-in state and the storage key, waits for open modals to close, and starts.

### Step 3 — How to Play button and styles
Add the How to Play button (the tour's main entry point at first) and wire it to `switchTab('team')` then `startTour(steps, {force: true})`. Add CSS with the existing tokens: square corners, flame accent outline on the cut-out, Big Shoulders title.

### Step 4 — Docs and tests
Add static tests for:
- the six step targets existing in `index.html`,
- the storage key,
- `textContent` use,
- no `confirm(` or `prompt(`,
- the replay button,
- the pinned How to Play phrases being kept.

Update the docs listed above. Bump the suite-size tripwire.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_144_guided_tour.py tests/test_how_to_play_role_subtabs.py -v`, then the full suite; `node --check frontend/app-tour.js`.
- Manual on test.kana-cards.com:
  - **Default settings:** a new account sees no tour automatically. "Show the tour" on How to Play starts it, and all six steps highlight the right element.
  - **With `GUIDED_TOUR_AUTOSTART=true`:** the tour starts on My Team after any popup closes; after Done and a reload, it doesn't return.
  - **Controls:** Skip, Esc and backdrop each end it and write the seen flag; ←/→ step back and forth.
  - **Phone width:** every step's box stays on screen.
  - **Logged out:** "Show the tour" opens the login popup.
  - **Storage blocked:** private window with storage blocked, and the page still works.
