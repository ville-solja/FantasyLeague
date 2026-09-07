# Plan: Weekly Report Fixes

## Context
The Weekly Summary Report popup (`plan-issue-51-weekly-summary.md`) shipped with four rough
edges reported in GitHub issue #100: the "Reveal results" button is rendered inline at the
bottom of each week's scrollable match list, so it disappears from view once there are enough
matches to require scrolling; reveal state is scoped per week tab, forcing repeated clicks
across every listed week to see everything; the winning team is highlighted unconditionally in
both the API response and the frontend markup even before a week is revealed, defeating the
"no spoilers" purpose of the reveal gate (MVP and points are correctly gated already); and each
match's played date, though already present in the API payload (`start_time`), is never
rendered. This plan fixes all four without changing the underlying availability/generation
model — `markdown/features/core/weekly-summary.md`'s "Availability, Not Generation" section
(weeks becoming available via `end_time`, content computed live) is unaffected.
*Resolves GitHub issue #100.*

## User Stories

### Reveal Button Stays Visible While Scrolling
**User story**
As a user, I want the "Reveal results" control to stay visible at the bottom of the Weekly
Report popup regardless of how many matches are listed, so I don't have to scroll to find it.

**Acceptance criteria**
- The reveal control is docked to the bottom of the popup (not inside the scrollable match
  list) and remains visible while scrolling through a week's matches
- It is shown whenever at least one currently-listed week is not yet revealed, and hidden once
  everything currently listed has been revealed
- Scrolling the match list does not move, hide, or duplicate the docked control

---

### Reveal All Currently Available Results at Once
**User story**
As a user, I want a single "Reveal results" action to reveal every week currently shown in the
report, so I don't have to click reveal separately for each week tab.

**Acceptance criteria**
- Clicking the reveal control reveals every week currently listed in the popup that the user
  has not yet revealed, not just the currently active tab
- Weeks already revealed before the click are unaffected (idempotent — clicking again changes
  nothing for them)
- After the click, the active tab's content updates immediately to show the revealed state;
  switching to any other previously-unrevealed tab also shows it already revealed
- A week that becomes available (gets listed) after a previous "reveal all" click starts
  unrevealed, requiring the reveal control to be used again to reveal it

---

### Hide Match Outcome Until Revealed
**User story**
As a user, I want the winning team, MVP, and points breakdown all hidden until I reveal a
week's results, so glancing at the report can't spoil the outcome before I'm ready to see it.

**Acceptance criteria**
- Before a week is revealed, no team is visually marked as the winner and no "Winner" label is
  shown for either team in that week's matches
- MVP highlighting and per-player points remain hidden before reveal (existing behaviour,
  confirmed unaffected by this fix)
- After reveal, the winning team is visually highlighted exactly as before, alongside the
  existing MVP and points breakdown

---

### Match Date Displayed
**User story**
As a user, I want to see the date each match was played, so I can place the result in time
without cross-referencing the schedule tab.

**Acceptance criteria**
- Each match in the Weekly Report shows the date it was played
- The date is shown for every match regardless of reveal state, consistent with the other
  always-visible match fields (teams, VOD link)

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/weekly_summary.py` | Gate `winner_team_id` behind `revealed` in `_build_week_summary`; add `POST /weekly-summary/reveal-all` to reveal every currently-available week for the current user in one call |
| `frontend/app-weekly-summary.js` | Replace the per-tab inline reveal button with a single docked control calling the new reveal-all endpoint; render each match's date; drop `revealWeeklySummary(weekId)` in favor of the global action |
| `frontend/index.html` | Add a docked/sticky reveal footer inside `#weeklySummaryModal`, outside the scrollable `#weeklySummaryContent` area |
| `frontend/style.css` | Sticky/docked positioning for the new reveal footer; match-date text styling |
| `markdown/stories/team-tokens-scoring.md` | Correct the pre-reveal winner-highlight claim in "View the Weekly Report"; note the winner highlight now belongs to "Reveal Full Match Results" |

### Step 1 — Hide the winner until revealed
In `backend/routers/weekly_summary.py::_build_week_summary`, the `matches` loop currently sets
`match["winner_team_id"] = winner_team_id` unconditionally. Gate it the same way
`match["players"]` already is:
```python
match = {
    "match_id": r.match_id,
    "radiant_team_id": r.radiant_team_id,
    "dire_team_id": r.dire_team_id,
    "radiant_team": _team_dict(teams_by_id.get(r.radiant_team_id)),
    "dire_team": _team_dict(teams_by_id.get(r.dire_team_id)),
    "winner_team_id": winner_team_id if revealed else None,
    "vod_url": r.vod_url,
    "start_time": r.start_time,
}
```
No frontend change is needed for the highlight itself — `_weeklySummaryMatchHtml` in
`frontend/app-weekly-summary.js` already derives `winnerRadiant`/`winnerDire` from
`m.winner_team_id`, so a `null` value naturally suppresses the "Winner" label and highlight
class pre-reveal.

### Step 2 — Reveal-all endpoint
Add to `backend/routers/weekly_summary.py`:
```python
@router.post("/weekly-summary/reveal-all")
def reveal_all_weekly_summaries(db=Depends(get_db),
                                current_user: dict = Depends(get_current_user)):
    week_ids = [w.week_id for w in db.query(WeeklySummary.week_id).all()]
    already = {
        r[0] for r in
        db.query(WeeklySummaryReveal.week_id)
          .filter(WeeklySummaryReveal.user_id == current_user["user_id"],
                  WeeklySummaryReveal.week_id.in_(week_ids)).all()
    }
    now = int(time.time())
    for week_id in week_ids:
        if week_id not in already:
            db.add(WeeklySummaryReveal(week_id=week_id, user_id=current_user["user_id"],
                                       revealed_at=now))
    db.commit()
    return {"revealed_week_ids": week_ids}
```
Idempotent by construction (skips weeks already revealed for this user). A week that gets a
`WeeklySummary` row later, via the existing `generate_weekly_summaries` background pass, is
untouched by past calls and stays unrevealed until the control is used again — satisfying the
"new games default to unrevealed" requirement with no extra state to track.

### Step 3 — Docked reveal control
In `frontend/index.html`, add a footer element inside `#weeklySummaryModal`, sibling to (not
nested inside) the scrollable `#weeklySummaryContent`:
```html
<div id="weeklySummaryRevealFooter" class="weekly-summary-reveal-footer hidden">
  <button onclick="revealAllWeeklySummaries()">Reveal results</button>
</div>
```
In `frontend/style.css`, dock it to the bottom of the modal (`position: sticky; bottom: 0;`, or
`position: absolute` within a `position: relative` modal body — match whichever pattern the
existing modal CSS already uses for a similar footer/action bar).

### Step 4 — Frontend: reveal-all wiring
In `frontend/app-weekly-summary.js`:
- Remove the inline `<button onclick="revealWeeklySummary(...)">` from `renderWeeklySummaryContent`
- Add `_updateWeeklySummaryRevealFooter()` — shows the footer if any entry in
  `_weeklySummaryWeeks` has `revealed === false`, hides it otherwise; call it from
  `renderWeeklySummaryTabs()` and after a reveal-all completes
- Replace `revealWeeklySummary(weekId)` with `revealAllWeeklySummaries()`:
```js
async function revealAllWeeklySummaries() {
  try {
    const res = await fetch(`${API}/weekly-summary/reveal-all`, { method: 'POST' });
    if (!res.ok) return;
    _weeklySummaryWeeks.forEach(w => { w.revealed = true; });
    _updateWeeklySummaryRevealFooter();
    if (_weeklySummaryActiveWeekId != null) {
      await selectWeeklySummaryTab(_weeklySummaryActiveWeekId);
    }
  } catch (_) {}
}
```

### Step 5 — Match date
In `_weeklySummaryMatchHtml`, format `m.start_time` (unix seconds) and render it — e.g. next to
the VOD link in `.weekly-summary-match-vs-cell`. Check `frontend/app.js` / the existing schedule
rendering for whatever date-formatting convention is already established there rather than
introducing a new one.

## Verification
- Load the Weekly Report with a week containing enough matches to require scrolling — the
  reveal control stays visible at the bottom without scrolling to it
- With two or more available weeks unrevealed, click reveal once — both weeks show as revealed
  when switching tabs, from a single click
- Before revealing, confirm no team is marked "Winner" in the match display, and no MVP/points
  are shown; after revealing, the winner highlight, MVP, and points all appear together
- Confirm each match displays its played date both before and after reveal
- Generate a new week's summary (or wait for one) after a prior reveal-all — the new week
  starts unrevealed and requires the control to be used again
- Run `cd backend && python -m pytest tests/ -v` — full suite passes
