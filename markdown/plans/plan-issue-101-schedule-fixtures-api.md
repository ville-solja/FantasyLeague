# Plan: Schedule Fixtures API Source

## Context
The Schedule tab's fixture list is currently sourced from a published Google Sheet CSV
(`SCHEDULE_SHEET_URL`), parsed by a fragile row/column state machine in `backend/schedule.py`
(`fetch_csv_text` → `parse_schedule`). Kanaliiga now exposes the same fixture data as a
structured JSON feed — `https://kanaliiga-schedule.fly.dev/api/fixtures.json` — which is a
cleaner, less brittle source for the same information. This plan adds a second, preferred
schedule source: when `SCHEDULE_FIXTURES_URL` is set, the app fetches that JSON and converts it
into the exact same `weeks[]` structure `parse_schedule` produces, so everything downstream of
parsing (DB result cross-referencing, `extra_results` derivation, caching, the `/schedule`
response shape, the frontend) is unchanged. The CSV path stays as the fallback when only
`SCHEDULE_SHEET_URL` is configured, so existing deployments keep working untouched.

The issue also asks to flag any way the JSON feed *cannot* fulfil the sheet's purpose. One real
gap exists and is handled explicitly in this plan: in the current feed every fixture has
`scheduled: false`, `starts_at: null`, and empty `date`/`time` — only `week_start` (the Monday
of the fixture's week) is known. The sheet, by contrast, often carries a provisional date/time
before a match is officially scheduled. To avoid unscheduled fixtures vanishing from the
Upcoming list (the frontend only renders series that have a `datetime_iso`), the parser falls
back to `week_start` at 00:00 as an approximate date and marks the series `scheduled: false` so
the UI can show "time TBD" instead of a precise slot. Other minor differences (the feed's
`result` string is ignored — results still come from ingested matches; no playoff/bracket rows;
`starts_at` is UTC while `date`/`time` are Europe/Helsinki) are documented in the feature doc
rather than blocking anything.

*Resolves GitHub issue #101.*

## User Stories

### Configure a JSON Schedule Source
**User story**
As an operator, I want to point the app at a JSON fixtures endpoint via an environment
variable instead of a Google Sheet CSV, so the Schedule tab is populated from a structured,
less fragile source.

**Acceptance criteria**
- `SCHEDULE_FIXTURES_URL` environment variable configures a JSON fixtures endpoint
- When `SCHEDULE_FIXTURES_URL` is set, `GET /schedule` sources its `weeks[]` from that JSON
  and does not fetch the CSV sheet
- When `SCHEDULE_FIXTURES_URL` is unset, behaviour is exactly as today — the CSV sheet
  (`SCHEDULE_SHEET_URL`) is used, or the tab is empty if neither is set
- The `/schedule` JSON response keeps the same shape (`weeks[]` with `label`, `div1`, `div2`;
  each series with `team1`, `team2`, `datetime_iso`, `stream_url`, `series_result`, …), so no
  frontend or downstream change is required for sheet-parity fields
- `.env.example` and `markdown/features/reference/commands.md` document the new variable and
  its precedence over `SCHEDULE_SHEET_URL`

### Fixtures Map to the Same Week/Division Structure
**User story**
As a user, I want fixtures from the JSON feed grouped into the same weeks and divisions as the
sheet-sourced schedule, so the Schedule tab looks and behaves identically regardless of source.

**Acceptance criteria**
- Each feed fixture's `division` (`upper`/`lower`) maps to `div1`/`div2` respectively
- Fixtures are grouped by their `week` integer into weeks labelled `"Week {n}"`, ordered
  ascending
- `team1`/`team2`, and `stream` (as `stream_url` when it is an `http(s)` URL, else
  `stream_label`) carry across
- A fixture with a missing/unrecognised `week` or `division` is skipped, not allowed to crash
  the parse
- Team-name → `team_id` resolution, `series_result` cross-referencing, and independently-derived
  `extra_results` all work identically to the sheet path (they operate on the post-parse
  structure, which is unchanged)

### Unscheduled Fixtures Still Appear
**User story**
As a user, I want fixtures that don't yet have a confirmed date/time to still show up under the
right week in the Schedule tab, so I can see the full season plan before matches are scheduled.

**Acceptance criteria**
- A fixture with `starts_at: null` and empty `date`/`time` is given an approximate
  `datetime_iso` of its `week_start` date at 00:00, so it is not filtered out of the Upcoming
  list
- Such a series is marked `scheduled: false` in the `/schedule` response
- The Schedule tab shows "Time TBD" (or equivalent) instead of a specific time for a
  `scheduled: false` series, and still shows team names, division badge, and week grouping
- A fixture with a real `starts_at` (ISO datetime) uses that as its `datetime_iso`, converted
  to local time, and is marked `scheduled: true`
- When both `starts_at` and `date`/`time` are present, `starts_at` wins

### Diagnose the Active Schedule Source
**User story**
As an operator, I want the schedule debug endpoint to tell me which source is active and
whether the JSON feed parsed cleanly, so I can troubleshoot a misconfigured or malformed feed.

**Acceptance criteria**
- `GET /schedule/debug` reports which source is in use (`fixtures_json` vs `sheet_csv`) and the
  configured URL (prefix only)
- For the JSON source it reports HTTP status, the feed's `season` and `count`, the number of
  weeks parsed, and the number of fixtures dropped for a missing/unknown `week` or `division`
- A fetch failure or non-JSON / schema-mismatched response is reported as a clear error string,
  not an unhandled exception

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/schedule.py` | Add `SCHEDULE_FIXTURES_URL`, `fetch_fixtures_json()`, `parse_fixtures_json()` (+ `_fixture_to_series`, `_parse_iso_date` helpers); in `get_schedule()` choose the JSON source when `SCHEDULE_FIXTURES_URL` is set, else the existing CSV path; add a `source` field to the returned dict |
| `backend/routers/admin_ingest.py` | Extend `schedule_debug` to branch on the active source and validate/summarise the JSON feed; import `SCHEDULE_FIXTURES_URL` |
| `frontend/app-players.js` | In `renderRow`, when a series has `scheduled === false`, show "Time TBD" instead of `s.time`; no other change (the parser guarantees `datetime_iso` is set) |
| `.env.example` | Document `SCHEDULE_FIXTURES_URL` above `SCHEDULE_SHEET_URL`, noting precedence |
| `markdown/features/reference/commands.md` | Add a row for `SCHEDULE_FIXTURES_URL`; note the sheet URL is now the fallback |

No `backend/models.py` change and no migration — this is a parsing/source change only.

### Step 1 — Fetch and parse the JSON feed
In `backend/schedule.py`, alongside the existing `SCHEDULE_SHEET_URL`:

```python
SCHEDULE_FIXTURES_URL = os.getenv("SCHEDULE_FIXTURES_URL", "")

_DIVISION_MAP = {"upper": "div1", "lower": "div2"}


def fetch_fixtures_json():
    """Fetch the Kanaliiga fixtures JSON feed. Returns the parsed payload dict,
    or None on any failure (mirrors fetch_csv_text's contract)."""
    if not SCHEDULE_FIXTURES_URL:
        print("[SCHEDULE] SCHEDULE_FIXTURES_URL is not set")
        return None
    try:
        res = requests.get(SCHEDULE_FIXTURES_URL, timeout=15, allow_redirects=True)
        print(f"[SCHEDULE] Fixtures fetch status={res.status_code}")
        if res.status_code != 200:
            return None
        return res.json()
    except Exception as e:
        print(f"[SCHEDULE] Fixtures fetch error: {e}")
        return None


def _parse_iso_date(iso_date, time_str=""):
    """'2026-09-14' (+ optional 'HH:MM') -> naive ISO datetime string, or None.
    Distinct from parse_date_time(), which expects Finnish d.m.y order."""
    if not iso_date:
        return None
    try:
        y, m, d = (int(p) for p in str(iso_date).strip().split("-")[:3])
    except (ValueError, TypeError):
        return None
    tc = (time_str or "").strip().replace(".", ":")
    h, mi = 0, 0
    if ":" in tc:
        try:
            h, mi = int(tc.split(":")[0]), int(tc.split(":")[1])
        except (ValueError, IndexError):
            h, mi = 0, 0
    try:
        return datetime(y, m, d, h, mi).isoformat()
    except ValueError:
        return None


def _fixture_to_series(f):
    """One feed fixture -> the same series dict parse_match_row() emits."""
    starts_at = f.get("starts_at")
    date_str = (f.get("date") or "").strip()
    time_str = (f.get("time") or "").strip()

    dt_iso, scheduled = None, bool(f.get("scheduled"))
    if starts_at:
        try:
            dt_iso = (datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                      .astimezone().replace(tzinfo=None).isoformat())
            scheduled = True
        except ValueError:
            dt_iso = None
    if dt_iso is None and date_str:
        dt_iso = parse_date_time(date_str, time_str)
        if dt_iso:
            scheduled = True
    # Unscheduled: fall back to the Monday of the fixture's week so the series
    # still lands in Upcoming instead of being filtered out by the frontend.
    if dt_iso is None:
        dt_iso = _parse_iso_date(f.get("week_start"))
        scheduled = False

    stream = (f.get("stream") or "").strip()
    stream_url = stream if stream.startswith(("http://", "https://")) else None
    stream_label = None if stream_url else (stream or None)

    status = "unknown"
    if dt_iso:
        try:
            status = "past" if datetime.fromisoformat(dt_iso) < datetime.now() else "upcoming"
        except ValueError:
            pass

    return {
        "team1": f.get("team1") or None,
        "team2": f.get("team2") or None,
        "date": date_str or f.get("week_start") or None,
        "time": time_str or None,
        "stream_label": stream_label,
        "stream_url": stream_url,
        "datetime_iso": dt_iso,
        "match_status": status,
        "scheduled": scheduled,
    }


def parse_fixtures_json(payload):
    """Convert a fixtures.json payload into the weeks[] structure parse_schedule()
    produces: [{label, div1: [...], div2: [...]}, ...] ordered by week number.
    Returns (weeks, dropped_count)."""
    fixtures = (payload or {}).get("fixtures") or []
    by_week, dropped = {}, 0
    for f in fixtures:
        wk = f.get("week")
        bucket = _DIVISION_MAP.get((f.get("division") or "").strip().lower())
        if wk is None or bucket is None:
            dropped += 1
            continue
        node = by_week.setdefault(wk, {"label": f"Week {wk}", "div1": [], "div2": []})
        node[bucket].append(_fixture_to_series(f))
    return [by_week[k] for k in sorted(by_week)], dropped
```

### Step 2 — Source selection in `get_schedule()`
Replace the `csv_text = fetch_csv_text()` block at the top of `get_schedule()` with a source
switch. Everything below `team_lookup = build_team_lookup(db)` stays exactly as-is — it only
consumes the parsed `weeks` list.

```python
    if SCHEDULE_FIXTURES_URL:
        source = "fixtures_json"
        payload = fetch_fixtures_json()
        weeks = None if payload is None else parse_fixtures_json(payload)[0]
    else:
        source = "sheet_csv"
        csv_text = fetch_csv_text()
        weeks = None if csv_text is None else parse_schedule(csv_text)

    if weeks is None:
        # unchanged: serve stale cache if present, else fall through with
        # weeks=[] so Results still derive from the DB; only Upcoming is empty
        if _cache["data"] is not None:
            stale = dict(_cache["data"])
            stale["stale"] = True
            return stale
        weeks = []
        error = "Schedule unavailable"
    else:
        error = None
```

Add `"source": source` to the `data` dict that is cached and returned.

### Step 3 — Frontend "Time TBD"
In `frontend/app-players.js`, `renderRow`, the `!isPast` branch currently does:
```js
const time = s.time ? `<span class="series-time">${s.time}</span>` : "";
```
Change to show a placeholder when the series is known to be unscheduled:
```js
const time = s.time
  ? `<span class="series-time">${s.time}</span>`
  : (s.scheduled === false ? `<span class="series-time tbd">Time TBD</span>` : "");
```
No other frontend change — `loadSchedule` already groups by date and the parser guarantees an
approximate `datetime_iso`. (Optional: a `.series-time.tbd { color: #555; }` rule in
`frontend/style.css`.)

### Step 4 — Debug endpoint
In `backend/routers/admin_ingest.py`, import `SCHEDULE_FIXTURES_URL` and rewrite
`schedule_debug` to branch:

```python
@router.get("/schedule/debug")
def schedule_debug(_: dict = Depends(require_admin)):
    from schedule import (SCHEDULE_FIXTURES_URL, SCHEDULE_SHEET_URL,
                          fetch_fixtures_json, parse_fixtures_json)
    if SCHEDULE_FIXTURES_URL:
        url = SCHEDULE_FIXTURES_URL
        result = {"source": "fixtures_json", "url_prefix": url[:60]}
        payload = fetch_fixtures_json()
        if payload is None:
            result["error"] = "fetch failed or non-200 (see server logs)"
            return result
        if not isinstance(payload, dict) or "fixtures" not in payload:
            result["error"] = "response is not a fixtures.json payload"
            return result
        weeks, dropped = parse_fixtures_json(payload)
        result.update(season=payload.get("season"), count=payload.get("count"),
                      weeks_parsed=len(weeks), fixtures_dropped=dropped)
        return result
    # ... existing sheet_csv debug body, with "source": "sheet_csv" added ...
```

### Step 5 — Docs / env
- `.env.example`: add, above the `SCHEDULE_SHEET_URL` block —
  ```
  # Structured JSON fixtures feed for the season schedule. Preferred over
  # SCHEDULE_SHEET_URL when both are set; unset falls back to the CSV sheet.
  # SCHEDULE_FIXTURES_URL=https://kanaliiga-schedule.fly.dev/api/fixtures.json
  ```
- `markdown/features/reference/commands.md`: new row for `SCHEDULE_FIXTURES_URL`; amend the
  `SCHEDULE_SHEET_URL` row to note it is the fallback.

## Verification
- With `SCHEDULE_FIXTURES_URL` set to the Kanaliiga feed and `SCHEDULE_SHEET_URL` unset:
  `GET /schedule` returns `source: "fixtures_json"`, `weeks[]` with `"Week 1".."Week 7"`,
  `div1` populated for `upper` fixtures and `div2` for `lower`, team names matching the feed
- Every current feed fixture (`scheduled: false`) appears in the Upcoming list grouped under
  the Monday of its week, marked `scheduled: false`, rendered with "Time TBD"
- A fixture given a real `starts_at` resolves to that local datetime and `scheduled: true`
- Results still cross-reference: a `div1`/`div2` series whose teams have ingested matches gets
  a `series_result` and per-game breakdown exactly as with the sheet source
- `extra_results` still derives DB-only series not claimed by any feed fixture (playoff games)
- With `SCHEDULE_FIXTURES_URL` unset but `SCHEDULE_SHEET_URL` set: behaviour and
  `source: "sheet_csv"` unchanged from today
- With neither set: `GET /schedule` returns empty Upcoming, Results still derived from the DB,
  "Schedule unavailable" scoped to Upcoming — unchanged
- `GET /schedule/debug` with the feed configured reports status, `season`, `count`,
  `weeks_parsed`, and `fixtures_dropped`
- Feed unreachable → `/schedule` serves stale cache if present, else empty Upcoming; the
  background/`/schedule/refresh` path does not raise
- `POST /admin/sync-match-weeks` still matches feed weeks to DB `Week` records by the
  `"Week {n}"` label (confirm DB week labels use that form for this season)
- `cd backend && python -m pytest tests/ -v` — full suite passes; add
  `tests/test_schedule_fixtures_api.py` covering `parse_fixtures_json` grouping, the
  `starts_at` / `date`+`time` / `week_start` fallback precedence, and division mapping
