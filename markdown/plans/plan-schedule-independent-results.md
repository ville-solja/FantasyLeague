# Plan: Schedule-Independent Past Results

## Context

The Schedule tab's Results section currently only ever shows a series if a matching row exists
in the Google Sheet schedule (`resolve_series_result()` in `backend/schedule.py` requires a
sheet row's team names + planned date to anchor the DB lookup). This was discovered to silently
hide real, fully-ingested matches: DotaBuff series
[#2854050](https://sr.dotabuff.com/esports/series/2854050-op-vs-visma) (OP Platinum vs Visma
Tormentor, best-of-3, matches `8813628780`/`8813718513`/`8813824412`, played May 16) is fully
present in the `matches` table — `ingest_league()` pulls every match for a monitored league_id
directly from OpenDota, entirely independent of the schedule sheet — but never appeared in the
Schedule tab, because the live Google Sheet's Week 9 only contains a "Live-pleijarit" ("live
playoffs" in Finnish) placeholder instead of real per-series rows, and Week 10 has a header with
zero data rows underneath it. The sheet's maintainer never listed the playoff bracket as
structured fixtures — expected to recur every season, and for other leagues entirely that may
not maintain a comparable spreadsheet at all.

Confirmed direction: **Upcoming stays sheet-sourced** (there's no other source of information
about matches that haven't happened yet — planned date, stream link). **Results should show
every completed match regardless of whether the sheet has a row for it**, merged into the same
list the sheet-resolved results already appear in (not a separate, easy-to-miss section) — so
the app keeps working for leagues that don't maintain a schedule spreadsheet at all, and for the
part of any season (playoffs, bracket stages) the spreadsheet doesn't enumerate.

Investigation findings that shape this plan:
- `Match` rows carry `radiant_team_id`, `dire_team_id`, and `radiant_win` directly — a series'
  win/loss tally can be computed straight from the DB, without any sheet involvement, exactly
  the same way `resolve_series_result()` already does it from a resolved `rows` list.
- The per-game breakdown (`_build_games()`, from the schedule-series-game-breakdown feature)
  already takes `(db, match_ids, team1_id, team2_id)` and needs no sheet context at all — it is
  directly reusable for DB-derived series.
- A useful side effect: today, if a sheet row's team names fail fuzzy matching
  (`find_team_id()` returns `None` for a typo or unusual name), `resolve_series_result()` returns
  `None` and the series shows as bare "vs" with **no result at all**, even though the match
  genuinely happened and is in the DB. Since this plan's derivation works from unclaimed
  matches (not sheet rows), those matches will now surface correctly via the new path too —
  fixing that failure mode as a side effect, not just the playoffs case.
- `get_schedule()` currently short-circuits to `{"weeks": [], ..., "error": "Schedule
  unavailable"}` when `SCHEDULE_SHEET_URL` is unset and there's no prior cache, before any DB
  work happens. This must change so Results still populate in that case — Upcoming is the only
  part that has no fallback.

Assumptions (flagged for review):
- Matches are clustered into a "series" by unordered team pair, gapped by time: consecutive
  matches (sorted by `start_time`) between the same two teams belong to the same series as long
  as the gap to the previous match in that pair is under **6 hours** — generous headroom for a
  real Bo3/Bo5 session (which the OP-vs-Visma example fits comfortably: 17:58, 19:11, 20:40) while
  still separating genuinely distinct meetings (e.g. a regular-season match and a playoff
  rematch between the same two teams, months apart). No draft-order/series-id field exists to
  group by instead, so this is a heuristic, easy to retune later.
- Division (Div 1 / Div 2 badge) for a derived series is inferred, not authoritative: the sheet
  is scanned once for every team name that ever appeared in a `div1` or `div2` column across the
  whole season, resolved to team_ids, and a derived series is labeled by whichever side either
  of its teams was seen on. If a team never appears in the sheet at all (fully sheet-independent
  league, or a foreign playoff opponent), the series shows with no division badge rather than a
  guess.
- A completed match qualifies for this derivation if it has both `radiant_team_id` and
  `dire_team_id` set (already a de facto requirement — `ingest_match()` only stores matches with
  `duration >= 900`s, filtering out remakes/aborts).

---

## User Stories

### Show Past Results Without Requiring a Schedule-Sheet Row
**User story**
As a user, I want completed matches to appear in the Schedule tab's results even when the
schedule spreadsheet has no corresponding fixture row (playoffs, bracket stages, or matches the
sheet simply never listed) so that the results I see always reflect what's actually been played.

**Acceptance criteria**
- `GET /schedule` additionally derives series from completed matches not already resolved by any
  sheet row, grouping consecutive matches between the same two teams (played within a short time
  window of each other) into one series
- These derived series appear in the same Results list as sheet-resolved series, sorted
  chronologically together — not a separate or hidden section
- Each derived series shows the same detail as a sheet-resolved one: aggregate score and the
  per-game breakdown (duration, kills, hero icons)
- A completed match is never shown twice — matches already claimed by a resolved sheet series
  are excluded from the independently-derived results

### Results Remain Available Without a Configured Schedule Sheet
**User story**
As an operator running this app for a league that doesn't maintain a Google Sheets schedule, I
want the Schedule tab's Results to still populate directly from ingested match data so that the
app is useful without requiring a spreadsheet at all.

**Acceptance criteria**
- When `SCHEDULE_SHEET_URL` is unset (or the sheet is unreachable with no prior cache),
  `GET /schedule` returns an empty Upcoming set but still returns fully-populated Results derived
  from the database
- The existing "Schedule unavailable" messaging is scoped to Upcoming only — it is not shown
  (or is clearly secondary) when Results have data to display

### Upcoming Fixtures Remain Sheet-Sourced
**User story**
As a user, I want upcoming/future fixtures to keep coming from the schedule spreadsheet so that
planned dates and stream links — information that doesn't exist anywhere else before a match is
played — are still shown.

**Acceptance criteria**
- No change to how Upcoming series are resolved or displayed — still sourced entirely from the
  schedule sheet
- Existing sheet-resolved Results (series the sheet does describe) are unaffected in shape or
  content by this plan

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/schedule.py` | Add `_tally_wins()` (shared win/loss tally, extracted from `resolve_series_result()`), `_build_unscheduled_results()` (groups unclaimed completed matches into series), and rework `get_schedule()` to compute `extra_results` and to stop short-circuiting Results when the sheet is unavailable |
| `frontend/app-players.js` | `loadSchedule()` — merge `data.extra_results` into the `past` array alongside sheet-derived past series before grouping/rendering; adjust the "no schedule data" / stale-sheet messaging to only gate Upcoming |
| `markdown/features/reference/schedule-series-game-breakdown.md` | Extend to document `extra_results` and the sheet-independent derivation (this doc already covers `_build_games()`, which this plan reuses directly) |

### Step 1 — Extract a shared win/loss tally helper

`resolve_series_result()` already computes `team1_wins`/`team2_wins` from a list of
`(match_id, radiant_team_id, radiant_win, start_time)` rows. Extract that loop into:

```python
def _tally_wins(rows, team1_id):
    """rows: iterable of (radiant_team_id, radiant_win) for one series. Returns (team1_wins, team2_wins)."""
    team1_wins = team2_wins = 0
    for radiant_id, radiant_win in rows:
        if radiant_win is None:
            continue
        if radiant_id == team1_id:
            team1_wins += 1 if radiant_win else 0
            team2_wins += 0 if radiant_win else 1
        else:
            team2_wins += 1 if radiant_win else 0
            team1_wins += 0 if radiant_win else 1
    return team1_wins, team2_wins
```

`resolve_series_result()` calls this instead of inlining the loop — no behavior change there.

### Step 2 — Derive series from unclaimed completed matches

```python
def _build_unscheduled_results(db, claimed_match_ids, div1_team_ids, div2_team_ids):
    rows = db.execute(text("""
        SELECT match_id, radiant_team_id, dire_team_id, radiant_win, start_time
        FROM matches
        WHERE radiant_team_id IS NOT NULL AND dire_team_id IS NOT NULL
        ORDER BY start_time ASC
    """)).fetchall()

    leftover = [r for r in rows if r.match_id not in claimed_match_ids]

    GAP = 6 * 3600  # seconds — see Assumptions
    groups: dict[tuple, list] = {}
    last_seen: dict[tuple, int] = {}
    for r in leftover:
        pair = tuple(sorted((r.radiant_team_id, r.dire_team_id)))
        if pair in last_seen and (r.start_time - last_seen[pair]) > GAP:
            # gap exceeded — this row starts a fresh series for this pair;
            # key by start_time so it doesn't merge into the old group
            groups[(pair, r.start_time)] = [r]
        else:
            key = next((k for k in groups if k[0] == pair and (r.start_time - groups[k][-1].start_time) <= GAP), None)
            if key:
                groups[key].append(r)
            else:
                groups[(pair, r.start_time)] = [r]
        last_seen[pair] = r.start_time

    team_names = {t[0]: t[1] for t in db.execute(text("SELECT id, name FROM teams")).fetchall()}

    results = []
    for (pair, _), matches in groups.items():
        team1_id, team2_id = pair
        team1_wins, team2_wins = _tally_wins(
            [(m.radiant_team_id, m.radiant_win) for m in matches], team1_id
        )
        match_ids = [m.match_id for m in matches]
        division = (
            "div1" if team1_id in div1_team_ids or team2_id in div1_team_ids else
            "div2" if team1_id in div2_team_ids or team2_id in div2_team_ids else
            None
        )
        results.append({
            "team1": team_names.get(team1_id, str(team1_id)), "team1_id": team1_id,
            "team2": team_names.get(team2_id, str(team2_id)), "team2_id": team2_id,
            "division": division,
            "datetime_iso": datetime.fromtimestamp(matches[0].start_time).isoformat(),
            "match_status": "past",
            "series_result": {
                "team1_wins": team1_wins, "team2_wins": team2_wins,
                "game_count": len(matches), "start_time": matches[0].start_time,
                "match_ids": match_ids,
                "games": _build_games(db, match_ids, team1_id, team2_id),
            },
        })
    return results
```

(The grouping loop above is a sketch of the intended gap-based clustering — the developer stage
should verify it against a couple of known multi-series fixtures, e.g. a team that played two
unrelated series months apart, before trusting it verbatim.)

### Step 3 — Wire into `get_schedule()`

- Stop returning early when `csv_text is None` and there's no cache — instead set `weeks = []`
  and `error = "Schedule unavailable"`, but continue on to compute `extra_results` regardless.
- While resolving each sheet series (existing loop), accumulate `claimed_match_ids.update(r["match_ids"])`
  whenever `series["series_result"]` is not `None`, and accumulate every team name seen in each
  week's `div1`/`div2` arrays into two global `div1_names`/`div2_names` sets, resolving them to
  ids via the existing `team_lookup` once the loop finishes.
- Call `_build_unscheduled_results(db, claimed_match_ids, div1_ids, div2_ids)` and attach as
  `data["extra_results"]`.

### Step 4 — Frontend: merge into the existing Results list

In `loadSchedule()` (`frontend/app-players.js`), after building `allSeries` from `data.weeks`:

```javascript
for (const s of (data.extra_results || [])) allSeries.push(s);
```

before the `upcoming`/`past` split (derived series always have `match_status: "past"`, so they
naturally sort into `past`). Update the division badge in `renderRow()` to render nothing when
`s.division` is falsy, instead of always assuming `div1`/`div2`. Update the "no schedule data"
guard from `!data.weeks?.length` to `!data.weeks?.length && !data.extra_results?.length`, and
scope the `data.error` early-return the same way — only short-circuit when there's truly nothing
to show at all.

---

## Verification

- `cd backend && python -m pytest tests/ -v` — full suite passes
- New backend tests: a match between two teams with no sheet row at all appears in
  `extra_results`; a match already claimed by a resolved sheet series does not also appear in
  `extra_results`; two matches between the same team pair within the gap window merge into one
  derived series, while two matches outside the gap window (or a different day entirely) do not;
  `GET /schedule` still returns populated `extra_results` when `SCHEDULE_SHEET_URL` is unset
- Manual: confirm the OP Platinum vs Visma Tormentor playoff series
  (https://sr.dotabuff.com/esports/series/2854050-op-vs-visma) now appears in the live Schedule
  tab's Results with the correct 2-1 score and per-game breakdown
- Manual: temporarily unset `SCHEDULE_SHEET_URL` and confirm Results still populate (Upcoming
  empty, no blocking error)
