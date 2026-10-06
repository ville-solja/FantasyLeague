# Schedule Visuals

The Schedule tab opens on what matters now: a live match, the next match and the latest result. It shows the season one fantasy week at a time, in time order, and lets players hide results until they choose to reveal them. The tab is used by everyone, logged in or not. Issue #156; UI details in `markdown/ui_description/schedule.md`.

---

## Layout

- **Right now strip** (`#scheduleNow`): up to three cards. Each card is left out when it has nothing to show, and the strip is hidden when all three are empty.
  - **Live now:** a series whose team pair has a game in `live_matches` (see Live detection).
  - **Next up:** the next three upcoming series with a real time after now ("Time TBD" fixtures never qualify), as compact rows, with a countdown to the first. Each watch button has the streamer name before it (`_schedStreamerName` derives it from the URL when the feed gives no label); without a stream link it reads "Caster TBD" and the Watch button is greyed out. Fewer than three timed series: one summary row per coming week of untimed matches ("Next week · 7 matches, times to be announced", via `_schedWeeksAway`), with View week.
- **Times** are league wall-clock time: `schedule.py` converts the feed's `starts_at` to `LEAGUE_TZ` (Europe/Helsinki) and judges upcoming/past against league time (`_league_now()`), since the container runs on UTC. The countdown is computed at render time, with no timer.
  - **Latest result:** the played series with the latest time. Follows hide mode; its **Games** button opens that series' week with its games unfolded.
- **Week strip** (`#scheduleWeeks`): one chip per fantasy week (`Week` rows, from `fantasy_weeks`). With no `Week` rows it falls back to Monday-start calendar weeks built from the series' own dates.
  - The tab opens on the current week: the week containing now, else the next to start, else the last.
  - The selected week lives in a module variable (`_schedWeekKey`), so a quiet refresh (#159) keeps the player's place.
  - Chips with unrevealed results carry a marker.
- **Week panel** (`#scheduleContent`): the selected week's series grouped by day, earliest first, with All / Div 1 / Div 2 filter chips.
  - In the current week, a "Now" line separates started series from upcoming ones.
  - "Time TBD" fixtures close the week in their own group.
  - Per-game rows are folded behind an "N games" button.

## Week assignment

- A series' time (`seriesTime`) is `series_result.start_time` once played, else its planned `datetime_iso`.
- `assignWeek` places it in the week where `start_time <= t < end_time`. Outside every week it goes to the last week starting before it, else the first week, so no series disappears. This covers feed fixtures, DB-derived `extra_results` and "Time TBD" fixtures (whose `datetime_iso` is the Monday of their week).

## Hide and reveal

- **Hide results** is a toggle, on by default, so results start hidden. The player's choice is stored in the browser (`kc_schedule_hide`: `"0"` off, `"1"` on; absent or unreadable counts as on). It is not cleared on logout.
- **What hide mode hides:** for a played series, the score, winner styling, game count, game rows, kills, heroes, MVP and the "Not scored" badge. None of this is rendered at all while hidden. Row markup carries a short hash of the series key rather than the key itself, because the key (the match ids) would give away the game count.
- **Revealing:** one series at a time with **Reveal**, or a whole week with **Reveal week**. **Hide week again** (`hideScheduleWeekAgain`) undoes reveals made on the tab for that week. Reveals are stored in the browser (`kc_schedule_revealed`, a JSON array of series keys, newest 500 kept).
- **Series key** (`seriesKey`): the series' match ids sorted and joined with commas, or `team1|team2|datetime_iso` for a series with no games.
- **Row state** (`rowState`), in order: `live`, `upcoming` (`match_status !== "past"` or no `series_result`), `hidden` (hide mode on, key not revealed, week not revealed in the Weekly Report), `shown`. Live and upcoming rows look the same in both modes; a live series' partial score follows hide mode.
- **Weekly Report link-up:** for logged-in users, the Schedule fetches `GET /weekly-summary` once per load and treats fantasy weeks with `revealed: true` as revealed. A failure, or a logged-out viewer, falls back to the browser's reveals. Reveals never flow the other way: the Schedule makes no write to the Weekly Report.
- Every storage read and write is in try/catch. With storage blocked, hide mode and reveals work for the session but don't persist.

## Live detection

A series is live when a `live` entry has the same two team ids (sorted, so either side matches) and started within 12 hours of the series' time. When the series time or the live game's start is unknown, the team pair alone counts. A series whose team names never resolved to team ids cannot show as live. The window keeps an earlier or later meeting of the same two teams from showing as live.

## Endpoints

### `GET /schedule`
Public. The existing cached response, plus two fields computed for each request and never stored in the cache (`schedule.get_schedule_for_request` decorates a shallow copy of `get_schedule(db)`):
- `live`: `[{team_ids: [a, b], started_at}]` from `schedule.get_live_pairs(db, now)`. Built from `live_matches` rows with `ended_at` empty, `last_seen_at` within `LIVE_FRESH_SECONDS` (15 minutes) and both team ids set. `team_ids` is sorted; `started_at` is `first_seen_at`. No player data or names.
- `fantasy_weeks`: `[{week_id, label, start_time, end_time}]` from `schedule.get_fantasy_weeks(db)`, ordered by `start_time`.

### `POST /schedule/refresh`
Admin only. Busts the cache and returns the same shape as `GET /schedule`.

No new tables, columns or env vars.

## Code

- Backend: `backend/schedule.py` (`LIVE_FRESH_SECONDS`, `get_live_pairs`, `get_fantasy_weeks`, `get_schedule_for_request`), `backend/routers/admin_ingest.py`.
- Frontend: `frontend/app-players.js` (`loadSchedule` renders through `renderIfChanged`; pure helpers `seriesTime`, `seriesKey`, `assignWeek`, `calendarWeeks`, `currentWeekIndex`, `rowState` (states `live`, `upcoming`, `noresult`, `hidden`, `shown`); handlers `toggleScheduleHide`, `revealScheduleSeries`, `revealScheduleWeek`, `hideScheduleWeekAgain`, `selectScheduleWeek`, `scheduleThisWeek`, `setScheduleDivision`, `toggleScheduleGames`, `showScheduleLatestGames`), `frontend/index.html`, `frontend/style.css`.
- Tests: `backend/tests/test_issue_156_schedule_visuals.py` (runs `loadSchedule` under Node against a fake DOM when Node is installed).

---

*Mockup: https://claude.ai/artifact/EG87wyL8nRE1fW64pCS228*
