# Roster After a Draw

Keeps My Team showing the editable roster after a card draw, and keeps the week picker and week points honest when no week is scheduled. Issue #249. Plan: `markdown/plans/plan-issue-249-roster-after-draw.md`.

---

## The problem

During the Final week of season 16, production had no week after the Final, so no week was open for editing. The week picker then selected nothing, and the browser showed its first option (`Week 1 ✓`). Players who picked the live week and then drew saw the roster reload that locked snapshot: the new cards weren't shown, and the bench section was hidden. With no week chosen, "This week" added up card points from the start of time.

## Behaviour

- **After a draw:** a successful web draw (**Draw a card**, a team draw, or the reveal's **Draw another card**, which repeats one of the two) switches My Team back to the editable roster when a locked week was shown, then reloads, so the card shows in its slot or on the bench. A failed draw (no tokens, empty deck) keeps the week shown. So does the modifier reroll, which adds no card.
- **Week picker:** with no upcoming week, the first option is **Next week (not scheduled)**, selected when no week is chosen (when there are no weeks at all, the picker stays empty). It shows the editable roster: the live cards, which the next week will use.
- **Week points:** with no upcoming week, `GET /roster/{user_id}` without `week_id` returns `week: null`, zero card points and `combined_value` 0; the status line reads "No upcoming week".
- **Draw flight:** the lift frame of the deck-to-reveal flight no longer has `NaN` values.

## Endpoints

### `GET /roster/{user_id}` *(changed)*
With no `week_id` and no upcoming week (no week whose `start_time` is after now): `week` is null, every card's `total_points` and `match_count` are 0 and `combined_value` is 0.0. The card list, `season_points`, `tokens` and `version` are as before. With an upcoming week or an explicit `week_id`, nothing changed.

Before, this case summed each card's stored points over every scored match up to now.

## Implementation

| Where | What |
|---|---|
| `frontend/app-cards.js` `_showEditableRosterForDraw()` | Called in `drawCard` and `_drawBoosterForTeam` after the draw flight, right before the roster reload. Does nothing when no week is chosen (`_rosterWeekId === null`) or the chosen week is unlocked; otherwise sets `_rosterWeekId = null` and re-renders the picker. `confirmReroll` (the modifier reroll) doesn't call it. |
| `frontend/app-roster.js` `_renderWeekSelector()` | Adds `<option value="">Next week (not scheduled)</option>` first when no week in `_weeks` starts in the future. With no week chosen it also sets the select's value (the upcoming week, or the empty option), since unchanged markup isn't rewritten. |
| `frontend/app-roster.js` `onRosterWeekChange()` | An empty or non-numeric value becomes `null` (the editable roster), never `NaN`. |
| `frontend/app-roster.js` `loadRoster()` | `#rosterWeekStatus` reads "No upcoming week" when the response's `week` is null. |
| `backend/routers/cards.py` `_build_roster_response()` | With no week, the scoring window is empty (`ws = 1`, `we = 0`) instead of `0..now`. |
| `frontend/app-cards.js` `_playDrawFlight()` | The lifted rect is built from the `DOMRect`'s fields; `{ ...from }` copied none of them, because they are prototype getters. |

## Other callers

- **Twitch panel** (`twitch._me_state`): while a locked week is in progress and none is upcoming, it asks for that week by id, so nothing changed. With no upcoming week and no week in progress (between seasons), its roster rows now show 0.0 points instead of the all-time sum, the same as the website.
- **`PUT /roster`** returns the same response as `GET /roster` without `week_id`, so a save made with no upcoming week also answers with zero week points.
- **Weekly Report** always passes a week id: unchanged.

## Tests

`backend/tests/test_issue_249_roster_after_draw.py`.
