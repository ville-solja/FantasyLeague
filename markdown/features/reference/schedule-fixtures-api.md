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
3. Else → empty Upcoming; Results still derived from ingested matches

### `backend/schedule.py` signatures

- `fetch_fixtures_json() -> dict | None` — GET `SCHEDULE_FIXTURES_URL` (15s timeout); returns
  the parsed payload, or `None` on non-200 / fetch error / non-JSON (mirrors `fetch_csv_text`).
- `_parse_iso_date(iso_date, time_str="") -> str | None` — `"2026-09-14"` (+ optional
  `"HH:MM"`) to a naive ISO datetime string. Distinct from `parse_date_time()` (Finnish d.m.y).
- `_fixture_to_series(f) -> dict` — one feed fixture to the series dict `parse_match_row()`
  emits, plus a `scheduled` bool. Precedence: `starts_at` (UTC ISO → local, `scheduled: true`)
  > `date`/`time` (`scheduled: true`) > `week_start` at 00:00 (`scheduled: false`).
- `parse_fixtures_json(payload) -> (weeks, dropped)` — groups fixtures by `week` into
  `[{label: "Week {n}", div1: [...], div2: [...]}]` ordered ascending; `division` `upper`→`div1`,
  `lower`→`div2` (`_DIVISION_MAP`); a fixture with a missing/unknown `week` or `division` is
  counted in `dropped` and skipped.

Both parsers emit the **same** `weeks[]` structure — `[{label, div1: [...], div2: [...]}]`,
each series dict carrying `team1`, `team2`, `date`, `time`, `stream_label`, `stream_url`,
`datetime_iso`, `match_status` — so DB result cross-referencing (`series_result`),
independently-derived `extra_results`, the 1-hour cache, the `/schedule` response shape, and
the frontend are all unchanged. The JSON path adds one field per series: `scheduled` (bool).

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
| `week` (int) | week grouping + `label` = `"Week {n}"` |
| `week_start` (ISO date) | approximate `datetime_iso` fallback for unscheduled fixtures |
| `team1` / `team2` | same |
| `starts_at` (ISO datetime, UTC) | `datetime_iso` (converted to local), `scheduled: true` |
| `date` / `time` (Europe/Helsinki) | `datetime_iso` when `starts_at` is null |
| `stream` | `stream_url` if `http(s)`, else `stream_label` |
| `result` | **ignored** — results come from ingested matches, not the feed |

## Known gaps vs. the Google Sheet

Flagged per the issue — none block adoption:

- **No provisional times.** Every fixture in the current feed is `scheduled: false` with
  `starts_at: null` and empty `date`/`time`. The parser falls back to `week_start` at 00:00 so
  the fixture still appears under its week in Upcoming; the UI shows "Time TBD". Precise slots
  appear once the feed populates `starts_at`.
- **Round-robin only.** No playoff/bracket rows in the feed. As with the sheet, `extra_results`
  still surfaces those from ingested match data.
- **Week-label coupling.** `POST /admin/sync-match-weeks` matches feed weeks to DB `Week`
  records by the `"Week {n}"` label — DB week labels must follow that form.
- **Timezone split.** `starts_at` is UTC; `date`/`time` are Europe/Helsinki. `starts_at` is
  preferred and converted to server-local time.

## Endpoints

### `GET /schedule`
Unchanged shape. Gains a top-level `source` field (`"fixtures_json"` | `"sheet_csv"`) and, on
the JSON path, a per-series `scheduled` boolean.

### `GET /schedule/debug`
Admin only (`Depends(require_admin)`). Reports the active `source` and the configured URL
prefix. For the JSON source it also returns `status_code`, `content_type`, feed `season` /
`count`, `weeks_parsed`, and `fixtures_dropped` (fixtures with a missing/unknown `week` or
`division`). A network/parse exception returns `error` = the exception class name; a non-200
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
