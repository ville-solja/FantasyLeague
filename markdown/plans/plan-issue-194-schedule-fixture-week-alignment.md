# Plan: Schedule Fixture Week Alignment

## Context
Issue #194: on the Schedule tab, the Week 4 view (5.10.–12.10.) showed four week-5 fixtures as "Time TBD" with "No result", although week 5 hadn't been played yet. One played Week 4 series was also listed twice. Checked against the live feed (`SCHEDULE_FIXTURES_URL`, `https://kanaliiga-schedule.fly.dev/api/fixtures.json`, season 16, 43 fixtures) and the code, there are three causes and one difference that is by design.

**1. Unscheduled fixtures fall into the previous week.**
- **The feed:** a fixture without a time has `starts_at: null`, an empty `date`, `scheduled: false`, and its league week (`week`, `week_start`). In week 5, these were Elisa Oyj–OP Platinum, Gofore/Frends–Visma, Elisa Appelsiini–HOLISA and PV-1–Supercell.
- **The fallback:** `schedule._fixture_to_series` gives such a fixture `datetime_iso = week_start` at 00:00 league time (Mon 12.10. 00:00 Helsinki).
- **The fantasy week boundary:** fantasy weeks start Monday 03:00 UTC (06:00 Helsinki, #111).
- **The result:** `assignWeek` (`frontend/app-players.js`) puts the fixture in the week containing Mon 00:00, which is Week 4.

**2. Unplayed TBD fixtures read "No result".** `match_status` becomes `past` as soon as that Monday-midnight anchor has passed, and `rowState` turns a past series with no result into "No result". That happens even while the fixture's own week is still running.

**3. A team name resolves to the wrong team.**
- **The names:** the feed says "Innofactor/NordCloud"; the `teams` table has "InnofactorNordcloud" (current) and "Innofactor" (an older team).
- **The match:** `norm_team_name` keeps the `/`, so there is no exact match. `find_team_id`'s substring fallback then returns the first key contained in the name, which is the old "Innofactor".
- **The effect:** the Reaktor–Innofactor/NordCloud fixture found no games ("No result"). The games it should have claimed appeared as a separate unscheduled result row ("Reaktor 2–0 InnofactorNordcloud").

**4. League week vs. fantasy week (by design, but not explained).** The Schedule groups series by fantasy week, using each series' time. A league week-4 fixture played on Mon 12.10. 21:00, Hoxhunt Fortum–Elisa Oyj, belongs to fantasy week 5, because its points count there. So it isn't in the Week 4 view even though the feed labels it week 4. Played series also show their actual start (Visma–Futurice 21:02) rather than the planned time (20:30).

This plan fixes the first three and explains the fourth on the page and in the docs. Assumptions:
- **Anchor for unscheduled fixtures:** Thursday 12:00 league time of their league week. That is well inside any Monday-based fantasy week, whatever hour the boundary uses.
- **Grouping stays by fantasy week**, because points follow fantasy weeks. A row whose league week differs from the fantasy week it is shown in gets a small "League week N" tag.

Resolves GitHub issue #194.

## User Stories

### Unscheduled Fixtures Stay in Their Own Week
**User story**
As a player looking at the Schedule, I want a fixture without a time to appear in the week it belongs to, so that past weeks don't fill up with matches that haven't been played.

**Acceptance criteria**
- A feed fixture with no `starts_at` and no `date` keeps `scheduled: false` and gets `datetime_iso` = its `week_start` + 3 days at 12:00, league time (the Thursday of its league week)
- On the Schedule, it appears in the fantasy week that contains that Thursday, under "Time TBD"; for the season-16 feed, the four TBD week-5 fixtures appear in Week 5, not Week 4
- A fixture with a `starts_at`, or a `date` and `time`, keeps today's behaviour
- A fixture with neither a date nor a `week_start` is dropped and counted in `dropped` (before this change it was kept with no time and skipped by the frontend)

### TBD Fixtures Don't Say "No Result" Before Their Week Ends
**User story**
As a player, I want an unscheduled match that hasn't been played to read "Time TBD", not "No result", so that I don't think it was cancelled.

**Acceptance criteria**
- An unscheduled fixture's `match_status` is `upcoming` until its league week ends (`week_start` + 7 days, league time), then `past`
- While it is `upcoming`, the Schedule row shows "Time TBD" and "vs"
- After its week, with no games found, it shows "No result" as other past series do
- A TBD fixture whose games are found (a series result) shows its score and moves out of the "Time TBD" group to its played day, as today

### Team Names Match Despite Punctuation and Old Teams
**User story**
As a player, I want each scheduled series to show its result, so that a played match is never listed both as "No result" and as a separate result row.

**Acceptance criteria**
- `norm_team_name` compares names case-insensitively, ignores parentheticals as today, and ignores every character that isn't a letter or digit: "Innofactor/NordCloud", "InnofactorNordcloud" and "innofactor nordcloud" are the same name
- `find_team_id` returns the exact normalised match when there is one
- The substring fallback is used only when exactly one team matches. When several match (for example "Innofactor" and "InnofactorNordcloud"), it returns the longest matching name if that one is unambiguous; otherwise it returns no team and logs a warning that names the fixture's team text
- With the season-16 data, Reaktor–Innofactor/NordCloud (Wed 7.10.) resolves to the current team, shows Reaktor 2–0, and the separate "InnofactorNordcloud" result row is gone

### League Week Shown When It Differs
**User story**
As a player comparing the Schedule with the league's own schedule, I want to see when a match belongs to a different league week than the fantasy week it is listed under, so that the two schedules don't look contradictory.

**Acceptance criteria**
- Each series from the fixtures feed carries its league week (`league_week`, the feed's `week`)
- When a row's league week differs from the number in the fantasy week label it is shown under, the row shows a small "League week N" tag after the division badge. Example: Hoxhunt Fortum–Elisa Oyj, league week 4, played Mon 12.10. 21:00, shown in Week 5
- No tag when they match, when the fantasy week has no number in its label, or when the source is the Google Sheet (no league week)
- The tag text is set with `textContent` or `_escHtml`

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/schedule.py` | `_fixture_to_series`: Thursday-noon anchor, `match_status` by week end, `league_week`; `norm_team_name` letters and digits only; `find_team_id` unique or longest match only, warning when ambiguous |
| `frontend/app-players.js` | "League week N" tag in `seriesRow`'s meta when it differs from the shown fantasy week |
| `frontend/style.css` | Tag style (small, muted, like the division badge) |
| `markdown/features/reference/schedule-fixtures-api.md` | New section "Weeks, times and team names": the feed's fields, the anchor, league week vs. fantasy week, actual vs. planned time, name matching |
| `markdown/ui_description/schedule.md` | The tag and the TBD rule |
| `backend/tests/test_issue_101_schedule_fixtures_api.py` | `test_fixture_to_series_falls_back_to_week_start_midnight_when_unscheduled` now expects the Thursday-noon anchor |
| `backend/tests/test_issue_194_schedule_fixture_week_alignment.py` | Tests |

No schema change and no new env var.

### Step 1 — Unscheduled anchor and status
In `_fixture_to_series`, when there is no `starts_at` and no usable `date`:
```python
anchor = _parse_iso_date(f.get("week_start"))            # Monday 00:00, league time
if anchor:
    start = datetime.fromisoformat(anchor)
    dt_iso = (start + timedelta(days=3, hours=12)).isoformat()   # Thursday 12:00
    week_end = start + timedelta(days=7)
    status = "past" if week_end <= _league_now() else "upcoming"
```
Keep `scheduled = False`, and add `"league_week": f.get("week")` to every series from the feed.

### Step 2 — Team name matching
- **Normalisation:** `norm_team_name` lowercases, strips parentheticals, then removes every character outside `[0-9a-z]` (Unicode-aware: `str.isalnum`, so "Ä" stays).
- **`find_team_id`:**
  1. exact match;
  2. otherwise the candidates whose key contains the name or the other way round;
  3. one candidate → it; several → the longest key, if no other key is as long; otherwise `None`, with `logger.warning("schedule: ambiguous team name %r matches %d teams", name, n)`.
- **Callers:** `build_team_lookup` and `resolve_series_result` need no change. Check `_build_unscheduled_results` and the Twitch MVP pairs, which also use `find_team_id`.

### Step 3 — League week tag
Pass `league_week` through `get_schedule` (it already copies the series dicts). In `seriesRow`, compare it with the shown week's number, parsed from its label (`/\d+/`); on a mismatch add `<span class="league-week-tag">League week N</span>` to the meta.

### Step 4 — Docs
Add the "Weeks, times and team names" section to `schedule-fixtures-api.md`, covering:
- **feed fields:** `week`, `week_start`, `date`, `time`, `starts_at`, `scheduled`, `division`, `stream`;
- **conversions:** how each becomes a series, and the anchor and status rules;
- **week rules:** fantasy-week grouping, and when the tag shows;
- **times and names:** actual vs. planned times, and the name-matching rules with the ambiguity warning.

### Step 5 — Tests
`backend/tests/test_issue_194_schedule_fixture_week_alignment.py`:
- **Anchor:** an unscheduled fixture gets Thursday 12:00; it is `upcoming` before `week_start + 7d` and `past` after (monkeypatch `_league_now`).
- **Feed regression:** a fixture with neither date nor `week_start` is dropped. A minimal copy of the season-16 week 4–5 fixtures puts the four TBD fixtures' anchors inside a fantasy week starting Mon 12.10. 03:00 UTC.
- **Names:**
  - "Innofactor/NordCloud" resolves to "InnofactorNordcloud" when "Innofactor" also exists;
  - an ambiguous name returns `None` and logs once;
  - "Meta(no)core" still resolves to "Metacore".
- **Series result:** `resolve_series_result` finds the Reaktor–InnofactorNordcloud games, and `get_schedule` no longer lists them as unscheduled results.
- **Frontend, static check:**
  - `seriesRow` builds the tag only on a mismatch, through `_escHtml`/`textContent`;
  - `rowState` returns `upcoming` for a TBD series whose `match_status` is `upcoming` (Node harness, as in the #156 tests).

Update the #101 midnight-fallback test.

## Verification
- **Local check against the live feed:**
  1. With `SCHEDULE_FIXTURES_URL` set to the live feed, open the Schedule, then `POST /schedule/refresh` (admin).
  2. Week 4 shows only its seven played series. Reaktor–Innofactor/NordCloud shows 2–0, and there is no separate InnofactorNordcloud row.
  3. Week 5 lists the four TBD fixtures under "Time TBD" with "vs", not "No result". Hoxhunt Fortum–Elisa Oyj is in Week 5 with "League week 4".
- **Logs:** `GET /schedule/debug` and the logs show no ambiguous-name warning for season 16. If one appears, the warning names the team text to fix in the feed or the `teams` table.
- **Tests:** `cd backend && python -m pytest tests/test_issue_194_schedule_fixture_week_alignment.py tests/test_issue_101_schedule_fixtures_api.py -q`, then `python -m pytest tests/ -n auto -q`.
