# Plan: Roster After a Draw

## Context
Issue #249, "Card draw breaks the bench and roster is missing after the draw", has a title and no body. It was filed on Sat 15 Nov 21:06 UTC, during the Final week (id 10, 14–16 Nov). Production has no week after the Final, so no week was open for editing.

**Reproduced locally (2026-11-16)** on a copy of the database, with one locked week covering now and none after it, in a headless browser:
- **The bug:** with the live week chosen in My Team's week picker (`Final (live)`), each draw spends a token and shows the reveal. The roster then reloads that locked snapshot (`loadRoster(_rosterWeekId)`): the active slots stay empty, the bench section is hidden (a locked week with no saved bench), and the card's landing flight has no slot to reach. The cards exist; they are just not on screen.
- **Why the picker is on a locked week:** with no upcoming week, `_renderWeekSelector` selects nothing, so the browser shows the first option, `Week 1 ✓`, while the roster below shows the live cards. To see this week, a player picks `Final (live)`, then draws.
- **A related wrong number:** with no upcoming week and no week chosen, `GET /roster` adds up card points from time 0 to now (`ws = 0`), so "This week" shows season-long points (826.1 for brand-new cards in the test), and the week status line is blank.
- **Unrelated but in the same flow:** the deck-to-reveal flight's lift frame is `translate(NaNpx, …) scale(NaN, NaN)`, because `{ ...from }` spreads a `DOMRect`, whose fields are prototype getters (`app-cards.js`, `_rectTransform` call in the lift step). Browsers drop the invalid frame.
- **Not the cause:** with the default view (no week chosen), draws land correctly in the active slots and then the bench, on desktop and phone, with or without a live week.

**Decisions** (change them in review if needed):
- **A draw shows where the card went.** After any web draw (random or team), when the picker shows a locked week, My Team switches back to the editable roster before reloading, so the new card appears in its slot or on the bench and the landing flight has a target.
- **The picker names the editable roster.** With no upcoming week, the picker gets a first option, **Next week (not scheduled)**, selected when no week is chosen. It shows the live cards, which are what the next week will use.
- **No made-up week points.** With no upcoming week, `GET /roster` without `week_id` returns zero week points per card and `combined_value` 0, and the status line reads "No upcoming week". Season points are unchanged.
- **Twitch panel:** it has no week picker. While a week is in progress it asks for that week by id, so nothing changes; between seasons (no upcoming week and none in progress) its roster rows show 0.0 week points, like the website.
- **No backend scoring or schema change.**

Resolves GitHub issue #249.

## User Stories

### A Drawn Card Shows Up in My Roster
**User story**
As a player, I want a card I draw to appear in my roster or bench straight away, even if I was looking at a locked week, so that a draw never seems to lose my cards.

**Acceptance criteria**
- **Switch back:** after a successful draw or team draw on the web, if My Team showed a locked week, it switches to the editable roster (the picker shows the upcoming week, or **Next week (not scheduled)**), then reloads.
- **Visible:** the drawn card is in its active slot or on the bench, the bench section is visible, and the landing flight ends on the card's slot (desktop) or the "Added to …" notice shows (phone).
- **Unchanged otherwise:** with the editable roster already shown, a draw behaves as today. A failed draw (no tokens, empty deck) doesn't change the week shown.

### The Week Picker Says Which Roster Is Shown
**User story**
As a player, I want the week picker to match the roster on screen when no week is scheduled yet, so that I don't pick a locked week by mistake.

**Acceptance criteria**
- **No upcoming week:** the picker's first option is **Next week (not scheduled)**, selected when no week is chosen; the past and live weeks follow, as today.
- **Upcoming week exists:** no extra option; the upcoming week is selected, as today.
- **Choosing it:** selecting **Next week (not scheduled)** shows the editable roster (`_rosterWeekId = null`), never a `NaN` week id.

### No Week Points Without a Week
**User story**
As a player, I want My Team to show no week points when no week is scheduled, so that season-long totals don't look like this week's score.

**Acceptance criteria**
- **API:** `GET /roster/{user_id}` without `week_id`, when no week starts in the future, returns `week: null`, every card's `total_points` 0.0 and `combined_value` 0.0; `season_points` and the card list are unchanged.
- **UI:** the week status reads "No upcoming week"; "This week" shows 0.0.
- **With a week:** an upcoming week, or an explicit `week_id`, is scored as today.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-cards.js` | `_showEditableRosterForDraw()` before the roster reload in `drawCard` and `_drawBoosterForTeam` (the reveal's "Draw another card" goes through these two); the modifier reroll (`confirmReroll`) adds no card and keeps the week shown; fix the lift frame's rect copy |
| `frontend/app-roster.js` | `_renderWeekSelector`: **Next week (not scheduled)** option when no upcoming week; `onRosterWeekChange`: empty value → `null`; status "No upcoming week" when `week` is null |
| `backend/routers/cards.py` | `_build_roster_response`: with no week, an empty scoring window (no week points) |
| `markdown/features/reference/roster-after-draw.md`, `markdown/features/core/weeks.md` (My Team roster), `markdown/ui_description/` My Team spec | Docs |
| `backend/tests/test_issue_249_roster_after_draw.py` | Tests |

No migration, no env var.

### Step 1 — Back to the editable roster after a draw
In `app-cards.js`, add:

```js
/** Issue #249: a draw lands on the editable roster, so show it if a locked week is up. */
function _showEditableRosterForDraw() {
  if (_rosterWeekId === null) return;
  const shown = (_weeks || []).find(w => w.id === _rosterWeekId);
  if (shown && !shown.is_locked) return;
  _rosterWeekId = null;
  if (typeof _renderWeekSelector === "function") _renderWeekSelector();
}
```

Call it right before the `loadRoster(_rosterWeekId)` that follows a successful draw in `drawCard` and `_drawBoosterForTeam`. Failed draws return earlier and don't call it. The modifier reroll's reload doesn't call it.

### Step 2 — Week picker
In `_renderWeekSelector`, when `nextWeek` is undefined, prepend `<option value="">Next week (not scheduled)</option>`, selected when `_rosterWeekId === null`. In `onRosterWeekChange`, map `""` (and any `NaN`) to `null`. Keep the "keep the player's own pick" logic.

### Step 3 — No week points without a week
In `_build_roster_response`, when `week` is None (no `week_id`, no upcoming week), use an empty window (for example `ws = 1`, `we = 0`) so `match_count` and `total_points` are 0, instead of `0..now`. In `loadRoster`, when `week` is null, set `rosterWeekStatus` to "No upcoming week".

### Step 4 — Lift frame
Build the lifted rect from the `DOMRect`'s fields (`{ left: from.left, top: from.top - 24, width: from.width, height: from.height }`) instead of spreading it.

### Step 5 — Tests
- **Backend:** with only past weeks, `GET /roster/{id}` returns `week: null`, `combined_value` 0.0 and every `total_points` 0.0, with the same cards and `season_points` as before. With an upcoming week, the points are unchanged. With an explicit locked `week_id`, the snapshot is unchanged.
- **Frontend source checks:**
  - `_showEditableRosterForDraw` is defined and called before the roster reload in `drawCard` and `_drawBoosterForTeam`, the reveal's "Draw another card" calls one of those two, and `confirmReroll` doesn't call it;
  - the picker has the **Next week (not scheduled)** option, and `onRosterWeekChange` maps an empty value to `null`;
  - the status text "No upcoming week";
  - no `{ ...from` spread of a rect in `app-cards.js`.
- **UI test (Playwright, if the seed allows):** choose a locked week, draw, and the new card is in `#rosterActiveGrid` or `#benchGrid`.

## Verification
- On a database copy with a live locked week and no upcoming week: pick the live week, draw. The picker switches to **Next week (not scheduled)**, and the card shows in its slot (desktop) or with the notice (phone). Draw past five cards: the extras show on the bench.
- With no week chosen, the picker shows **Next week (not scheduled)**, "This week" is 0.0 and the status reads "No upcoming week".
- With an upcoming week (create one in Admin › Weeks), the picker and points behave as before.
- No NaN keyframe warning in the browser console during a draw.
- After deploy, comment on #249 with the cause.
