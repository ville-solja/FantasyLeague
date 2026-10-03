# Plan: Tour Includes the Weekly Report

## Context
The guided tour of My Team (#144, `frontend/app-tour.js`) covers drawing, chances, the roster, the weekly lock, points and the leaderboards. It doesn't mention the Weekly Report. Since #151 and #152, the report is where players see what each card scored, game by game, with the reveal animation. Issue #153 asks for the report to be part of the tour.

The outcome is one new tour step on the header's **Weekly Report** button (`#weeklyReportBtn`), placed after "Points" and before "Leaderboards". It explains what the report shows and that a popup announces each new week's recap.

There is one interaction to fix. The "recap is ready" popup (#151) deliberately stays hidden while a tour runs, and is then only checked again on the next page load. After this change, the popup appears as soon as the tour closes, if a recap is waiting.

**Assumptions:**
- The step highlights the button; it doesn't open the report. Opening a popup inside the tour would put a modal under the tour's spotlight layer and needs revealed data. A new player usually has no finished week yet.
- The copy works whether or not a report exists yet ("After each week ends…").
- `#weeklyReportBtn` is shown for every logged-in user (`app-auth.js`), and the tour only runs logged in, so the step normally shows. `startTour` already drops steps whose element is missing or hidden, which also covers a header that hides the button at some width.
- Frontend only: no backend, API, env var or migration changes. The existing feature doc `reference/guided-tour.md` is extended rather than creating a new stub, as #151 did with the Weekly Report doc.

Resolves GitHub issue #153.

## User Stories

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

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-tour.js` | New step in `myTeamTourSteps()`; `endTour()` checks for a waiting recap after cleanup |
| `markdown/features/reference/guided-tour.md` | Step list (7 steps), the recap check after the tour |
| `markdown/ui_description/weekly-report.md` | The header button is a tour step; the popup can follow the tour |
| `markdown/stories/ux-and-polish.md` | Stories (added at planning) |
| `backend/tests/test_issue_153_tour_weekly_report.py` | Static frontend checks |
| `backend/tests/test_issue_85_split_admin_router.py` | Suite-size tripwire bump |

### Step 1 — Tour step
In `myTeamTourSteps()`, insert between the "Points" and "Leaderboards" entries:

```js
{
  target: "#weeklyReportBtn",
  title: "Weekly Report",
  body: "After each week ends, your recap is here: what each card scored, game by game, and every match result. A popup tells you when a new one is ready.",
},
```

### Step 2 — Recap popup after the tour
At the end of `endTour()`, after the focus is restored:

```js
if (activeUserId && typeof checkWeeklySummaryHighlight === "function") {
  checkWeeklySummaryHighlight();
}
```

`_tour` is already `null` at that point, so `maybeShowWeeklyRecapPrompt`'s tour guard lets it through. Its other guards (another popup open, password change required) still apply. `app-weekly-summary.js` loads before `app-tour.js` (`index.html` lines 1216–1217). The `typeof` guard is kept anyway, since the call runs at tour end, not at load.

### Step 3 — Tests and docs
`backend/tests/test_issue_153_tour_weekly_report.py`, as static checks in the style of `test_issue_144_guided_tour.py`:
- The step list has a `#weeklyReportBtn` step titled "Weekly Report" with the exact body copy, between the `#rosterTotals` and `#tab-btn-leaderboard` steps, and the list has 7 steps.
- `#weeklyReportBtn` exists in `index.html`.
- `endTour()` calls `checkWeeklySummaryHighlight()` behind an `activeUserId` check and a `typeof` guard, after `_tour = null` and `_markTourSeen()`.
- Failure path: `startTour` still filters steps with `_tourTargetVisible`, so a hidden button drops the step.
- `maybeShowWeeklyRecapPrompt` still checks `_tour`, so it doesn't open during a tour.

Update the #144 tests that pin the step list: `STEP_TARGETS` and `STEP_TITLES` in `test_issue_144_guided_tour.py` (`test_tour_steps_six_targets_in_order` and the titles test) gain the new step, and the "six" wording becomes seven. Bump the suite-size tripwire. Update `reference/guided-tour.md` (the step list becomes 7 steps; describe the recap check after the tour) and `ui_description/weekly-report.md`.

## Verification
- From How to Play › Show the tour (logged in): the tour has 7 steps, and step 6 highlights the Weekly Report button in the header with the box below it, inside the screen, at desktop and at 375 px width.
- With a recap waiting (a new report week not yet announced), finish or skip the tour: the "recap is ready" popup appears right away, with focus on "Open recap".
- With no recap waiting: the tour ends with no popup.
- Logged out, How to Play › Show the tour still opens the login popup as before.
- `cd backend && python3 -m pytest tests/ -q` passes.
