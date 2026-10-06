# Plan: Schedule Visuals

## Context
Issue #156 asks for a rethink of the Schedule tab, with a canvas mockup. It names two needs:
- **Hide and reveal results** (winner and loser, kills, MVP), so that a player who hasn't watched yet doesn't get spoiled.
- **Recent results and the next matches first.** Players mostly care about these. Today the tab is one long list: Upcoming, sorted farthest future first, then Results, newest first. The next match sits at the bottom of the Upcoming block, and older results scroll on forever below it.

**Mockup:** https://claude.ai/artifact/EG87wyL8nRE1fW64pCS228 (private canvas). It has three frames: the interactive desktop page, the same page at phone width, and one series row in each state.

**The approach:**
- **A "Right now" strip at the top** with up to three cards:
  - **Live now**, from the `live_matches` table that the Twitch MVP feature already fills,
  - **Next up**, with planned time, a relative countdown ("in 1 h 20 min") and the stream link,
  - **Latest result**, which respects hide mode.
- **A week strip** of chips (W1 … W10) over a single-week view. The tab opens on the current week, and each chip jumps to its week. Within a week, series read in time order, oldest first, grouped by day. In the current week an orange **"Now" line** sits between the last started series and the next one. The page reads as a timeline with you on it, and nothing scrolls forever.
- **Hide results.** A "Hide results" toggle in the header switches spoiler-free mode on and off, and each browser remembers the choice. While it is on, a played series shows both teams at the same weight with "Played" and a **Reveal** button. The score, winner styling, game count, per-game rows and MVP stay hidden. A week header offers **Reveal week**.
- **Weekly Report link-up.** When a logged-in player has revealed a fantasy week in their Weekly Report, that week's series count as revealed on the Schedule too. They have already seen those results, so hiding them again would be noise.

**What exists today:**
- `GET /schedule` (`backend/routers/admin_ingest.py`, `backend/schedule.py::get_schedule`) returns `weeks[]`, the feed weeks with `div1`/`div2` series, plus `extra_results[]`, the DB-derived series without a feed row. The whole response is cached for `CACHE_TTL`.
  - Each series has `datetime_iso`, `match_status` (`"past"` or not), `team1_id`/`team2_id`, `stream_url`/`stream_label`, and `series_result` with `team1_wins`, `team2_wins`, `start_time`, `match_ids` and `games[]`.
  - Each game in `games[]` has kills, heroes, MVP, duration and `excluded_from_scoring`.
- `frontend/app-players.js::loadSchedule` renders the list with `renderIfChanged` (issue #159), and per-game rows are always expanded.
- `LiveMatch` (`backend/models.py`, the `live_matches` table) holds monitored-league games seen in OpenDota `/live`: `radiant_team_id`, `dire_team_id`, `first_seen_at`, `last_seen_at`, and `ended_at`, which is set when a poll no longer sees the game.
- `Week` rows (`label`, `start_time`, `end_time`) are the admin-defined fantasy weeks. `GET /weekly-summary` returns each week's `revealed` flag for the current user.

**Assumptions** (flagged for review):
- **Results start hidden.** A first visit shows every played series hidden, and the player reveals what they want. Turning hide mode off is remembered, and so are the per-series reveals, both in `localStorage`. The tab is public, so logged-out viewers get the same feature, and nothing goes to the server.
- **Reveals only flow from the Weekly Report to the Schedule.** Revealing a series on the Schedule does not reveal the fantasy week in the Weekly Report, which also hides fantasy points the Schedule never shows.
- **The week strip uses the fantasy weeks** (`Week` rows), so the chips match the Weekly Report and the reveal link-up works. With no `Week` rows, it falls back to calendar weeks starting on Monday, labelled by date. A series outside every fantasy week goes to the nearest week before it, or the first week if none is earlier, so no series disappears.
- **A series is placed by its actual start time** (`series_result.start_time`) once played, and by its planned `datetime_iso` before that.
- **Live detection is per team pair:** a `LiveMatch` with `ended_at IS NULL`, `last_seen_at` within the last 15 minutes and the same two team ids (either side) marks that series live, provided the game started within 12 hours of the series' time (added at implementation, so a rematch of the same pair elsewhere in the season is not marked live). Live state never shows a score of its own. If game 1 of a live series is already ingested, the series still shows "LIVE", and its partial score follows hide mode like any other result.
- **The live flags are computed for each request,** outside the one-hour schedule cache. The query is one small indexed read of `live_matches`.
- **Hero icons are real data,** shown only once a series is revealed and opened. Kills, MVP, duration and the "Not scored" badge also stay inside the folded game rows.
- **Out of scope:** results shown elsewhere (the team popup, player match history, leaderboards) are not affected by hide mode.

Resolves GitHub issue #156.

## User Stories

### See What's Happening Now at the Top of the Schedule
**User story**
As a player, I want the Schedule tab to open on what is live, what is next and what just finished, so that I don't scroll through the whole season to find tonight's matches.

**Acceptance criteria**
- A "Right now" strip at the top of the Schedule tab shows up to three cards:
  - **Live now:** a series with a matching live game. It shows both teams, its division, when it started and a "Watch live" link when a stream URL is known.
  - **Next up:** the next series with a planned time in the future. It shows the planned time, a relative countdown ("in 1 h 20 min", "in 2 days") and the stream link.
  - **Latest result:** the most recently played series.
- A card is left out when it has nothing to show. When all three are empty, the strip is not shown.
- The Latest result card follows hide mode: while the series is hidden it shows "Result hidden" with a Reveal button, and it never shows a score or MVP.
- Live state comes from `live_matches` rows with `ended_at` empty, seen in the last 15 minutes, with the same two team ids as the series in either order. The live game must have started within 12 hours of the series' time, so an earlier or later meeting of the same two teams is not marked live.
- Live state is never served from the one-hour schedule cache; it reflects the database at request time.

### Browse the Season Week by Week in Time Order
**User story**
As a player, I want to move through the season one week at a time, with matches in the order they are played, so that the schedule reads like a timeline and I can see where we are in it.

**Acceptance criteria**
- A week strip shows one chip per fantasy week (W1 … Wn), with its start date. The current week's chip is marked "This week" in orange and has `aria-current="date"`. Played weeks and upcoming weeks look different from each other.
- The tab opens on the current week. Between weeks it opens on the next upcoming week, and after the season on the last week.
- Clicking a chip, or the previous and next arrows, shows that week; a "This week" button returns to the current week.
- Within a week, series are grouped by day and sorted by time, earliest first, across both divisions. "Time TBD" fixtures have no real time, so they close the week in their own "Time TBD" group.
- In the current week, a "Now" line appears between the last started series and the next one, labelled with the current day and time.
- Division filter chips (All, Div 1, Div 2) narrow the week's list. A division with no series that week shows "No fixtures for this division this week."
- Every series appears in exactly one week, including feed fixtures, DB-derived results without a feed row, and "Time TBD" fixtures. A series outside every fantasy week goes to the nearest earlier week, or to the first week if none is earlier.
- With no fantasy weeks defined, the strip uses calendar weeks starting on Monday.
- At phone width the week strip scrolls sideways, the arrows are hidden, the Right now cards stack, and each series row becomes two lines: the time, division and action on top, the teams and score below.
- The stale notice, the "Loading..." shown only on the first load, and partial re-rendering (`renderIfChanged`) keep working as today.

### Hide Results Until I Choose to See Them
**User story**
As a player who watches matches later, I want to hide results on the Schedule tab and reveal them one series at a time, so that the schedule doesn't spoil a match I haven't watched yet.

**Acceptance criteria**
- A "Hide results" toggle in the Schedule header turns hide mode on and off. It has `aria-pressed`, and its label reads "Results hidden" while hide mode is on.
- Hide mode is on by default: on a first visit, or with nothing stored, results start hidden.
- The player's choice is remembered in the browser across visits and logins. Once they turn hide mode off, it stays off until they turn it back on.
- While hide mode is on, a played series that hasn't been revealed shows:
  - both team names at equal weight, with no winner styling,
  - the word "Played" in place of the score,
  - a "Reveal" button.
  
  It does not show the score, the number of games, per-game rows, kills, hero picks, the MVP or the "Not scored" badge.
- Clicking Reveal shows that series' score and winner styling. The game rows stay folded behind a "N games" button.
- A revealed series stays revealed across visits in the same browser.
- A week with hidden results shows a "Reveal week" button in its header, which reveals every played series in that week. Its chip in the week strip carries a small marker.
- Turning hide mode off shows every result. Turning it back on hides again only the series that were never revealed.
- Upcoming and live series look the same in both modes.

### Results Already Seen in the Weekly Report Stay Revealed
**User story**
As a logged-in player, I want weeks I already revealed in my Weekly Report to show their results on the Schedule tab, so that hide mode doesn't hide what I've already seen.

**Acceptance criteria**
- For a logged-in user, the Schedule tab reads the `revealed` flags from `GET /weekly-summary`. In hide mode, every series placed in a revealed fantasy week shows its result without a click.
- That week's header shows "Revealed in your Weekly Report" and no "Reveal week" button.
- Revealing a series or a week on the Schedule tab does not change anything in the Weekly Report.
- For a logged-out viewer, or if `GET /weekly-summary` fails, the Schedule tab still works and falls back to the reveals stored in the browser.

### Played Results Read at a Glance
**User story**
As a player, I want each played series to show who won at a glance and keep game details one click away, so that a week's results fit on one screen.

**Acceptance criteria**
- A revealed series shows its series score in display type, the winner's name bright and bold, and the loser's name in muted text.
- Per-game rows are folded by default behind a "N games" button with `aria-expanded`. When unfolded, each game row shows:
  - game number,
  - each side's hero icons,
  - the kills score,
  - the MVP with a star,
  - the duration,
  - the OpenDota link,
  - the "Not scored" badge where it applies.
- The Latest result card's "Games" button jumps to that series' week (normally the current week) and unfolds its games.
- A series with no result yet shows "vs" and no games button, as today. A played series with a result but no resolved games shows its score and no games button.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/schedule.py` | New `get_live_pairs(db, now)` helper. New `get_fantasy_weeks(db)`. `get_schedule` stays cached; a new wrapper adds `live` and `fantasy_weeks` to a shallow copy for each request. |
| `backend/routers/admin_ingest.py` | `GET /schedule` returns the decorated copy (`live`, `fantasy_weeks`), so the cache entry itself is never changed. |
| `frontend/app-players.js` | Rewrite `loadSchedule` rendering. New helpers: week assignment, the Right now strip, the week strip, day groups with the Now line, row states, hide mode and reveal storage, and the Weekly Report reveal lookup. |
| `frontend/index.html` | Schedule tab markup: header with the Hide results toggle and Refresh; containers for the Right now strip, the week strip and the week panel (`#scheduleNow`, `#scheduleWeeks`, `#scheduleContent`). |
| `frontend/style.css` | Styles for the now cards, week chips, row states, the Now line, folded game rows and the phone layout. Design-system tokens only: orange for current and "now", `--err` for live, no pills, no left-border cards, nothing under 11 px. |
| `markdown/ui_description/schedule.md` | Describe the new layout and states. |
| `markdown/features/reference/schedule-visuals.md` | Fill in the stub. |
| `backend/tests/test_issue_156_schedule_visuals.py` | New tests. |

No new tables or columns, so no migration. No new env vars.

### Step 1 — Live pairs and fantasy weeks in `GET /schedule`
In `backend/schedule.py`:

```python
LIVE_FRESH_SECONDS = 15 * 60

def get_live_pairs(db, now: int) -> list[dict]:
    """Team pairs with a game in progress: live_matches rows not ended and seen recently."""
    rows = db.query(LiveMatch).filter(
        LiveMatch.ended_at.is_(None),
        LiveMatch.last_seen_at >= now - LIVE_FRESH_SECONDS,
        LiveMatch.radiant_team_id.isnot(None),
        LiveMatch.dire_team_id.isnot(None),
    ).all()
    return [{"team_ids": sorted([r.radiant_team_id, r.dire_team_id]),
             "started_at": r.first_seen_at} for r in rows]

def get_fantasy_weeks(db) -> list[dict]:
    return [{"week_id": w.id, "label": w.label, "start_time": w.start_time, "end_time": w.end_time}
            for w in db.query(Week).order_by(Week.start_time).all()]
```

In the router, decorate a shallow copy so the cached dict is never changed:

```python
@router.get("/schedule")
def schedule_endpoint(db=Depends(get_db)):
    data = dict(get_schedule(db))
    data["live"] = get_live_pairs(db, int(time.time()))
    data["fantasy_weeks"] = get_fantasy_weeks(db)
    return data
```

`POST /schedule/refresh` returns the same shape. The response holds only team ids and timestamps: no player data, no Twitch ids.

### Step 2 — Week assignment and ordering (frontend)
- Flatten `weeks[].div1/div2` and `extra_results` into one series list, as today.
- `seriesTime(s)` is `series_result.start_time` when played, else `Date.parse(datetime_iso)/1000`.
- `assignWeek(series, fantasyWeeks)` places a series in the week whose `start_time <= t < end_time`. Outside every week, it goes to the last week that starts before it, else the first week. With no fantasy weeks, `calendarWeeks(series)` builds Monday-start weeks from the series' own dates.
- The current week is the one containing now; between weeks, the next one to start; after the last week, the last one. The selected week is kept in a module variable, so a quiet refresh (#159) keeps the player's place.
- Within the selected week, apply the division filter, sort by `seriesTime` ascending, and group by day with `toLocaleDateString("fi-FI", …)` as today. In the current week, insert the Now marker before the first series whose time is after now.

### Step 3 — Row states and hide mode
- `seriesKey(s)` is `series_result.match_ids` sorted and joined, or `team1|team2|datetime_iso` for a series with no games. It is stable across refreshes.
- Storage keys, each read and written inside try/catch so a blocked storage still renders:
  - `kc_schedule_hide`: `"0"` once the player turns hide mode off, `"1"` when they turn it on. Absent or unreadable counts as on.
  - `kc_schedule_revealed`: a JSON array of series keys, capped at the 500 most recent.
- Revealed weeks: when `activeUsername` is set, fetch `GET /weekly-summary` once per Schedule load. Ignore any failure, and keep a set of revealed `week_id`s.
- `rowState(s)`, in this order:
  - `live` when its sorted team ids match a `live` entry,
  - otherwise `upcoming` when `match_status !== "past"` or there is no `series_result`,
  - otherwise `hidden` when hide mode is on, its key isn't revealed and its week isn't revealed in the Weekly Report,
  - otherwise `shown`.
- Render each state as in the canvas's States frame. Hidden rows output no score, game count or game markup at all, rather than hiding it with CSS, so nothing leaks to view-source or screen readers.
- Clicking "N games" toggles an in-memory set of open series keys and re-renders through `renderIfChanged`.

### Step 4 — Right now strip and week strip
- **Live now:** the first series in `live` state. **Next up:** the earliest `upcoming` series with a real time (not "Time TBD") after now. **Latest result:** the latest played series by `seriesTime`.
- The countdown is computed at render time, with no timer. A tab switch or refresh updates it.
- Week chips are `<button>` elements with label, date and `aria-current`, plus the hidden-results marker. The previous and next arrows are `<button aria-label>` elements.

### Step 5 — Styles and phone layout
- Follow the mock's CSS, mapped onto `style.css` tokens. Below 700 px:
  - the now cards stack,
  - the week strip scrolls sideways and the arrows are hidden,
  - series rows use a two-line grid,
  - hero icons are hidden in game rows.
- Touch targets are at least 44 px for the toggle, chips and week buttons.

### Step 6 — Documentation
Update `markdown/ui_description/schedule.md` and the feature doc. Check that `markdown/stories/ux-and-polish.md` matches what was built.

## Verification
- **Backend tests:**
  - `GET /schedule` includes `live` and `fantasy_weeks`.
  - A `LiveMatch` that has ended, or was last seen more than 15 minutes ago, is not listed.
  - Team ids come back sorted.
  - The cached dict has no `live` key after a request, so the cache isn't changed.
  - `fantasy_weeks` is ordered by `start_time`.
  - The endpoint is still public.
- **Frontend checks** (the repo's static JS tests):
  - `loadSchedule` uses `kc_schedule_hide` and `kc_schedule_revealed` inside try/catch.
  - The hidden-row markup has no score or `game-row`.
  - Week chips use `aria-current`, and the toggle uses `aria-pressed`.
  - `renderIfChanged` is still used.
- **Manual, with demo data:**
  1. Open Schedule: it lands on the current week, the Now line sits between played and upcoming series, and Next up's countdown is right.
  2. Insert a `live_matches` row for tonight's pair: Live now and the row's LIVE tag appear without waiting for the cache to expire.
  3. On a first visit (clear site storage first), results start hidden:
     - played rows show "Played" and Reveal; Latest result shows "Result hidden";
     - reveal one series and reload, and it stays revealed;
     - Reveal week reveals the rest.
  4. As a logged-in user who revealed week N in the Weekly Report, week N shows its results in hide mode, with the "Revealed in your Weekly Report" note.
  5. Delete all `Week` rows (on a scratch DB): the strip falls back to calendar weeks and no series is lost.
  6. Check the layout at 390 px wide.
  7. Block site storage in the browser: the tab renders, and hide mode simply doesn't persist.
- Run the full pytest suite and bump the suite-size tripwire in `tests/test_issue_85_split_admin_router.py`.
