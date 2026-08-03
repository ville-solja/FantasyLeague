# Plan: Schedule Tab Game Breakdown

## Context

The Schedule tab's past-results view currently collapses every resolved series into a single
aggregate score (e.g. "2–1") plus a flat row of bare "G1 ↗", "G2 ↗" links to OpenDota — one per
game, with no information about what actually happened in each game. Issue #87 asks for the
series to act as a parent with each game shown as an informative child: starting with game
duration, kills, and hero icons grouped by team.

Investigation findings that shape this plan:
- `resolve_series_result()` in `backend/schedule.py` already resolves a series to its underlying
  `match_ids` (a plain list of ints) by matching team names against the DB within a ±4-day
  window of the scheduled date. This is the exact set of games the new per-game breakdown needs
  — no new series-to-game matching logic is required, only enriching what's already resolved.
- `backend/models.py`'s `Match` table has **no `duration` column** today. OpenDota's match JSON
  already includes `duration` and `ingest.py:ingest_match` already reads
  `data.get("duration", 0)` (to skip too-short matches) but never stores it. This plan adds the
  column and stores the value already being read.
- Per-player `kills` and `hero_id` already exist on `PlayerMatchStats` (used for individual
  scoring) — team-level kills for a game is `SUM(kills)` grouped by `team_id`, and each team's
  hero picks are simply the distinct `hero_id` values for that `team_id`/`match_id`. No new
  per-player storage is needed.
- No hero icon URL mapping exists anywhere in the codebase yet. `backend/enrich.py`'s
  `_fetch_hero_name_map()` calls OpenDota's `GET /constants/heroes` and keeps only
  `localized_name`; the same response also carries an `icon` path. **Verified live** (not
  assumed): `GET https://api.opendota.com/api/constants/heroes` returns 127 heroes, each with
  an `id` (int, matches `PlayerMatchStats.hero_id`'s type) and a non-null `icon` path for all
  127; `https://cdn.cloudflare.steamstatic.com` + that `icon` path returns `200 image/png`
  (~4.7KB — the small icon variant, not the larger `img` full-portrait path, which is the right
  size for a compact draft strip). Hero constants are effectively static within a patch, so
  this plan caches the icon map for the process lifetime rather than on the schedule's existing
  1-hour `CACHE_TTL` — no need to re-fetch it every time the schedule cache refreshes. The fetch
  goes through `opendota_client.get_json()`, the same shared throttled client (rolling 60s
  window capped by `OPENDOTA_MAX_RPM`) used by every other OpenDota call in `ingest.py`/
  `enrich.py` — no separate rate-limit handling needed, and since it's cached for the process
  lifetime this is one extra call total, not a per-request cost.
- `backend/routers/admin_ingest.py` owns `GET /schedule` post the issue-85 router split; no
  route path changes as part of this plan.

Assumptions (flagged for review):
- "Kills" is read as each **team's total kills** for that game (a single number per side, e.g.
  "32–28"), not a per-player breakdown — matching the issue's "basic information about the
  match" framing and mirroring how the series-level score is already a single aggregate.
- Each game's heroes are split into two fixed groups of 5 by team (`team1_heroes`,
  `team2_heroes`), representing that side's draft. Confirmed with the user: the order *within*
  a team's 5 doesn't matter — no draft-order or lane/slot field is stored anywhere today, so
  this plan queries in `hero_id` ascending order purely for a stable, deterministic result
  (not because it reflects pick order).
- Games with missing `hero_id` data (e.g. very old matches ingested before hero tracking) show
  a placeholder icon rather than omitting the slot, so team rows always show 5 positions.
- The existing per-game OpenDota link ("G1 ↗") is preserved, just moved into the new expanded
  game row instead of sitting in a flat list next to the score.

Resolves GitHub issue #87.

---

## User Stories

### Expand Series into Individual Game Rows
**User story**
As a user, I want each past series in the Schedule tab to expand into its individual games so
that I can see game-level detail instead of a flat list of bare match links.

**Acceptance criteria**
- Each past series with one or more resolved games renders each game as a child row nested
  under the series' team-vs-team header row
- Each game row shows: duration (formatted mm:ss), each team's total kills for that game, and
  each team's hero icons grouped by side (team1's heroes on the left, team2's on the right)
- The existing external link to the match (OpenDota) is preserved on each game row
- Upcoming (unresolved) series are unaffected — still show planned date/time/stream as today
- Series with no resolved games still show "vs" with no expandable content, as today

### Store Match Duration at Ingest Time
**User story**
As a developer relying on ingested match data, I want match duration stored on the `Match`
record at ingest time so that the schedule game breakdown (and any future feature) can display
it without extra OpenDota API calls.

**Acceptance criteria**
- `Match.duration` (seconds, nullable `Integer`) is populated from OpenDota's match JSON
  (`data.get("duration")`) during `ingest_match()`
- Matches ingested before this change have `duration = NULL` until re-ingested; the schedule
  UI shows a game row without a duration in that case rather than erroring
- A numbered migration (`022_matches_duration`) adds the column to existing databases, guarded
  by a `PRAGMA table_info` check, per this repo's schema migration rule

### Show Hero Icons for Each Game
**User story**
As a user, I want to see which heroes each team played in a given game so that I can recognize
the draft at a glance without looking the match up on OpenDota.

**Acceptance criteria**
- Hero icon URLs are resolved from OpenDota's hero constants (the same source already used for
  hero names in player profile enrichment) and included in the schedule response for the games
  shown
- Icons are grouped by team (mapped to the series' `team1_id`/`team2_id`, not raw
  radiant/dire), so team1's heroes always render on the same side as team1's name and score
- A hero with no resolved icon (unknown `hero_id`, or the constants fetch failed) shows a
  placeholder rather than a broken image

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `Match.duration = Column(Integer, nullable=True)` |
| `backend/migrate.py` | Add `022_matches_duration` — `ALTER TABLE matches ADD COLUMN duration INTEGER`, guarded by `PRAGMA table_info` |
| `backend/ingest.py` | `ingest_match()` — pass `duration=data.get("duration")` into the `Match(...)` constructor |
| `backend/schedule.py` | Add hero-icon-map fetch/cache; extend `resolve_series_result()` (or a new helper it calls) to attach a `games` array per series with duration/team kills/team hero icons |
| `frontend/app-players.js` | `loadSchedule()`/`renderRow()` — render each past series' `games` array as child rows instead of the flat `match_ids` link list |
| `frontend/style.css` | New classes for the game child rows and hero icon strip |

### Step 1 — `Match.duration` column + migration

```python
# backend/models.py, on Match
duration = Column(Integer, nullable=True)  # seconds, from OpenDota match JSON
```

```python
# backend/migrate.py
def _m022_matches_duration(conn):
    match_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(matches)")).fetchall()]
    if "duration" not in match_cols:
        conn.execute(text("ALTER TABLE matches ADD COLUMN duration INTEGER"))
        conn.commit()

MIGRATIONS = [
    ...
    ("022_matches_duration", _m022_matches_duration),
]
```

### Step 2 — Store duration at ingest time

In `ingest_match()`, add `duration=data.get("duration")` to the existing `Match(...)`
constructor call (the value is already read earlier in the function for the too-short-match
skip check — no new OpenDota call needed).

### Step 3 — Hero icon map (`backend/schedule.py`)

```python
_hero_icon_cache: dict | None = None

def _fetch_hero_icon_map() -> dict:
    """{hero_id: full icon URL}, fetched once per process lifetime — hero constants
    are effectively static within a patch."""
    global _hero_icon_cache
    if _hero_icon_cache is not None:
        return _hero_icon_cache
    from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json
    data = opendota_get_json(f"{OPEN_DOTA_URL}/constants/heroes", label="constants/heroes") or {}
    _hero_icon_cache = {
        h["id"]: f"https://cdn.cloudflare.steamstatic.com{h['icon']}"
        for h in data.values() if h.get("id") and h.get("icon")
    }
    return _hero_icon_cache
```

### Step 4 — Attach per-game detail to each series

Extend `resolve_series_result()` (still in `backend/schedule.py`, following its existing raw-SQL
`text()` style) to also query, for the resolved `match_ids`:

```sql
SELECT m.match_id, m.duration, s.team_id, SUM(s.kills) as kills
FROM matches m
LEFT JOIN player_match_stats s ON s.match_id = m.match_id
WHERE m.match_id IN (:ids)
GROUP BY m.match_id, s.team_id
```

and

```sql
SELECT match_id, team_id, hero_id
FROM player_match_stats
WHERE match_id IN (:ids) AND hero_id IS NOT NULL
ORDER BY hero_id ASC
```

Assemble a `games` list (one entry per `match_id`, in the same order as the existing
`match_ids`), each entry shaped like:

```python
{
    "match_id": 8813824412,
    "duration": 2143,  # seconds, or None
    "team1_kills": 32, "team2_kills": 28,
    "team1_heroes": [<icon_url>, ...],  # up to 5
    "team2_heroes": [<icon_url>, ...],
}
```

using the series' already-resolved `team1_id`/`team2_id` (available in `get_schedule()`, so this
attachment happens there or is passed in) to decide which raw `team_id` maps to `team1`/`team2`.
Missing hero slots (fewer than 5 resolved) are padded with `None` so the frontend can render a
placeholder icon.

### Step 5 — Frontend: expand game rows (`frontend/app-players.js`)

In `renderRow(s)`, when `isPast && r && r.games?.length`, render one child `<div class="game-row">`
per game beneath the existing series header row, each showing:
- formatted duration (`mm:ss`, or "—" if `null`)
- `team1_kills`–`team2_kills`
- a hero icon strip per side (`<img>` per `team1_heroes`/`team2_heroes` entry, placeholder image
  for `null` slots)
- the existing OpenDota link for that specific `match_id`

Keep the existing stream-link rendering for the series header row unchanged.

### Step 6 — Styling (`frontend/style.css`)

Add `.game-row`, `.game-row-heroes`, `.hero-icon` classes using existing design tokens
(`--bg-card-hi`, `--border-soft`, `--r-xs`, `--fs-xs`) consistent with the rest of the schedule
section's existing styling.

---

## Verification

- `cd backend && python -m pytest tests/ -v` — full suite still passes
- New/updated tests should cover: `Match.duration` migration applies cleanly to a pre-existing
  DB; `ingest_match()` stores duration; `resolve_series_result()`/`get_schedule()` returns a
  `games` array shaped as above for a series with resolved matches; hero icon map falls back
  gracefully (empty dict, not an exception) if the OpenDota constants call fails
- Manual: view the Schedule tab's Results section for a series with 2+ games and confirm each
  game shows duration, kills, and 5 hero icons per side, with team1 always on the same side as
  the team1 name/score
- Confirm upcoming (unresolved) series are visually unchanged
