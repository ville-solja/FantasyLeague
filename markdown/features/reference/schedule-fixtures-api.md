# Schedule Fixtures API Source

An alternative, preferred source for the Schedule tab's fixture list: a structured JSON feed
(`SCHEDULE_FIXTURES_URL`) that replaces the fragile Google Sheet CSV parse
(`SCHEDULE_SHEET_URL`). Used by operators; transparent to end users.

*(see `markdown/plans/plan-issue-101-schedule-fixtures-api.md`, resolves GitHub issue #101)*

---

## How it fits in

`backend/schedule.py::get_schedule(db)` picks a source before parsing:

1. If `SCHEDULE_FIXTURES_URL` is set → `fetch_fixtures_json()` fetches that JSON,
   `parse_fixtures_json(payload) -> (weeks, dropped)` converts it (`source: "fixtures_json"`)
2. Else if `SCHEDULE_SHEET_URL` is set → the existing CSV path (`fetch_csv_text` →
   `parse_schedule`), `source: "sheet_csv"`
3. Else → no feed fixtures; played series are still derived from ingested matches

### `backend/schedule.py` signatures

- `fetch_fixtures_json() -> dict | None` — GET `SCHEDULE_FIXTURES_URL` (15s timeout); returns
  the parsed payload, or `None` on non-200 / fetch error / non-JSON (mirrors `fetch_csv_text`).
- `_parse_iso_date(iso_date, time_str="") -> str | None` — `"2026-09-14"` (+ optional
  `"HH:MM"`) to a naive ISO datetime string. Distinct from `parse_date_time()` (Finnish d.m.y).
- `_fixture_to_series(f) -> dict` — one feed fixture to the series dict `parse_match_row()`
  emits, plus `scheduled` (bool) and `league_week` (the feed's `week`). Precedence: `starts_at`
  (UTC ISO → league time, `scheduled: true`) > `date`/`time` (`scheduled: true`) > Thursday
  12:00 of the `week_start` week (`scheduled: false`; see [Weeks, times and team names](#weeks-times-and-team-names)).
- `parse_fixtures_json(payload) -> (weeks, dropped)` — groups fixtures by `week` into
  `[{label: "Week {n}", div1: [...], div2: [...]}]` ordered ascending; `division` `upper`→`div1`,
  `lower`→`div2` (`_DIVISION_MAP`). A fixture with a missing/unknown `week` or `division`, or
  with no `starts_at`, no `date` and no `week_start` (nowhere to place it), is counted in
  `dropped` and skipped.

Both parsers emit the **same** `weeks[]` structure — `[{label, div1: [...], div2: [...]}]`,
each series dict carrying `team1`, `team2`, `date`, `time`, `stream_label`, `stream_url`,
`datetime_iso`, `match_status` — so DB result cross-referencing (`series_result`),
independently-derived `extra_results`, the 1-hour cache, the `/schedule` response shape, and
the frontend work the same for both sources. The JSON path adds two fields per series: `scheduled` (bool)
and `league_week` (int, the feed's `week`), which the frontend uses for "Time TBD" rows and the
"League week N" tag.

## Feed format

`https://kanaliiga-schedule.fly.dev/api/fixtures.json`:

```json
{
  "season": 16, "timezone": "Europe/Helsinki",
  "generated_at": "2026-09-07T12:21:15.132Z", "count": 43,
  "fixtures": [
    {"id": 1, "division": "upper", "week": 1, "week_start": "2026-09-14",
     "team1": "Hoxhunt Fortum", "team2": "Visma",
     "scheduled": false, "starts_at": null, "date": "", "time": "",
     "stream": "", "result": "", "updated_by": null}
  ]
}
```

| Feed field | Maps to |
|---|---|
| `division` (`upper`/`lower`) | `div1` / `div2` |
| `week` (int) | week grouping + `label` = `"Week {n}"`, and `league_week` on each series |
| `week_start` (ISO date) | approximate `datetime_iso` (its Thursday 12:00) and `match_status` for unscheduled fixtures |
| `team1` / `team2` | same |
| `starts_at` (ISO datetime, UTC) | `datetime_iso` (converted to local), `scheduled: true` |
| `date` / `time` (Europe/Helsinki) | `datetime_iso` when `starts_at` is null |
| `stream` | `stream_url` if `http(s)`, else `stream_label` |
| `result` | **ignored** — results come from ingested matches, not the feed |

## Known gaps vs. the Google Sheet

Flagged per the issue — none block adoption:

- **No provisional times.** Every fixture in the current feed is `scheduled: false` with
  `starts_at: null` and empty `date`/`time`. The parser anchors it at the Thursday 12:00 of its
  `week_start` week so the fixture still appears in its week, in a "Time TBD" group at the end;
  the UI shows "Time TBD". Precise slots appear once the feed populates `starts_at`.
- **Round-robin only.** No playoff/bracket rows in the feed. As with the sheet, `extra_results`
  still surfaces those from ingested match data.
- **Week-label coupling.** `POST /admin/sync-match-weeks` matches feed weeks to DB `Week`
  records by the `"Week {n}"` label — DB week labels must follow that form.
- **Timezone split.** `starts_at` is UTC; `date`/`time` are Europe/Helsinki. `starts_at` is
  preferred and converted to league time (`LEAGUE_TZ`, Europe/Helsinki), whatever the server's
  own timezone is.

## Weeks, times and team names

How feed fixtures become Schedule rows, and why the Schedule can differ from the league's own
listing (issue #194, `markdown/plans/plan-issue-194-schedule-fixture-week-alignment.md`).

### Feed fields

| Field | Meaning | Used for |
|---|---|---|
| `week` | League week number | Grouping in `weeks[]`, the `"Week {n}"` label, `league_week` on each series |
| `week_start` | Monday of the league week (ISO date, league time) | Anchor and status of an unscheduled fixture |
| `starts_at` | Planned start, UTC ISO datetime, or `null` | `datetime_iso` in league time, `scheduled: true` |
| `date`, `time` | Planned day and time (league time), or empty | `datetime_iso` when `starts_at` is `null`, `scheduled: true` |
| `scheduled` | The feed's own flag | Overridden: a series is `scheduled: true` whenever a time was found, else `false` |
| `division` | `upper` / `lower` | `div1` / `div2` |
| `stream` | URL or caster name | `stream_url` or `stream_label` |

### Unscheduled fixtures

A fixture with no `starts_at` and no usable `date` (`_fixture_to_series`):

- **Time:** `datetime_iso` = `week_start` + 3 days at 12:00 league time, the Thursday of its
  league week. Fantasy weeks start on Monday (06:00 Helsinki, #111), so Thursday noon always
  falls inside the fantasy week that covers the league week, whatever hour the boundary uses.
  The old Monday 00:00 anchor fell into the previous fantasy week.
- **Status:** `match_status` is `upcoming` until the league week ends (`week_start` + 7 days,
  league time), then `past`. The row reads "Time TBD" and "vs" until then, and "No result" only
  after the week, when no games were found for it.
- **Played:** once its games are found (`series_result`), the row shows the score and moves
  from the "Time TBD" group to the day it was played (`seriesTime` uses the first game's start).
- **No `week_start` either:** dropped and counted in `dropped`.

A fixture with `starts_at`, or with `date` and `time`, keeps its own time, and its status
turns `past` once that time has passed.

### League week vs. fantasy week

The Schedule groups series by **fantasy week** (the admin-defined `weeks` rows), using each
series' time, because points count by fantasy week. A league fixture played outside its league
week is therefore listed in another fantasy week: for example Hoxhunt Fortum–Elisa Oyj, league
week 4, played Mon 12.10. 21:00, is listed in Week 5.

Such a row shows a small **"League week N"** tag after the division badge. The frontend
(`leagueWeekTag` in `loadSchedule`) compares `league_week` with the first number in the fantasy
week's label. No tag when they match, when the label has no number, when the Schedule falls back
to calendar weeks (no fantasy weeks defined), or when the series has no `league_week` (the Google
Sheet source and DB-derived `extra_results`).

### Actual vs. planned time

A played series shows the actual start of its first game (`series_result.start_time`), not the
planned time from the feed, and is grouped under that day. Visma–Futurice planned for 20:30 and
started at 21:02 shows 21:02.

### Team name matching

Feed team names are matched to the `teams` table by `norm_team_name` and `find_team_id`
(`backend/schedule.py`); `resolve_series_result`, `get_schedule` and the Toornament sync all use
them.

- **Normalisation:** lowercase, parentheticals removed ("Meta(no)core" → "metacore"), then only
  letters and digits kept (`str.isalnum`, so "Ä" stays). "Innofactor/NordCloud",
  "InnofactorNordcloud" and "innofactor nordcloud" are the same name.
- **Exact match** on the normalised name wins.
- **Partial match:** otherwise, the teams whose normalised name contains the fixture's name, or
  is contained in it. One such team → it. Several → the one with the longest name, if no other
  is as long ("Innofactor Nordcloud Ltd" → InnofactorNordcloud, not the older Innofactor).
- **Ambiguous:** otherwise no team, and the `schedule` logger writes
  `schedule: ambiguous team name '<text>' matches N teams`. The series then has no result; fix
  the name in the feed or the `teams` table.

## Endpoints

### `GET /schedule`
Unchanged shape. Gains a top-level `source` field (`"fixtures_json"` | `"sheet_csv"`) and, on
the JSON path, a per-series `scheduled` boolean and `league_week` number.

### `GET /schedule/debug`
Admin only (`Depends(require_admin)`). Reports the active `source` and the configured URL
prefix. For the JSON source it also returns `status_code`, `content_type`, feed `season` /
`count`, `weeks_parsed`, and `fixtures_dropped` (fixtures with a missing/unknown `week` or
`division`, or with no date and no `week_start`). A network/parse exception returns `error` = the exception class name; a non-200
response or a 200 body that isn't a fixtures payload returns `error` =
`"response is not a fixtures.json payload"` (with `status_code` still present for diagnosis) —
never an unhandled exception.

### `POST /schedule/refresh`
Unchanged. Busts the cache and re-fetches from whichever source is active.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SCHEDULE_FIXTURES_URL` | *(empty)* | JSON fixtures feed URL. Preferred over `SCHEDULE_SHEET_URL` when both are set. |
| `SCHEDULE_SHEET_URL` | *(empty)* | Google Sheets CSV export URL. Fallback when `SCHEDULE_FIXTURES_URL` is unset. |
