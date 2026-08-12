# Schedule Series Game Breakdown

Expands each resolved series in the Schedule tab's Results section from a single aggregate
score into a parent row with an expandable child row per individual game, showing duration,
each team's kills, and each team's hero picks. Visible to everyone (same audience as the
Schedule tab itself). Results also include series derived directly from ingested match data
when the schedule sheet has no corresponding row — see "Schedule-independent results" below.

---

## Concept

A series (one row in the season schedule sheet) is resolved against the database to a list of
individual `match_id`s via `resolve_series_result()` in `backend/schedule.py`. Previously this
only surfaced as a flat row of bare "G1 ↗" / "G2 ↗" links next to the aggregate score. This
feature attaches per-game detail — duration, team kills, hero icons — to each resolved game, so
the series acts as a parent for its games rather than a single opaque result.

Team sides in each game are mapped to the series' own `team1`/`team2` (not raw Dota
radiant/dire), so hero icons and kills always render on the same side as the team name already
shown in the series header.

### Implementation

- `backend/models.py` — `Match.duration = Column(Integer, nullable=True)` (seconds, from
  OpenDota's match JSON).
- `backend/migrate.py` — `_m022_matches_duration()`, registered as `022_matches_duration` in
  `MIGRATIONS`, adds `matches.duration` on legacy databases (`PRAGMA table_info` guarded, safe
  to run twice).
- `backend/ingest.py` — `ingest_match()` reads `duration = data.get("duration")` once (reused
  for both the existing too-short-match skip check and the `Match(...)` constructor's
  `duration=` argument). A payload missing `duration` entirely stores `None` rather than being
  treated as a 0-second match.
- `backend/schedule.py`:
  - `_fetch_hero_icon_map()` — `{hero_id: full_icon_url}`, built from
    `opendota_client.get_json(f"{OPEN_DOTA_URL}/constants/heroes")`, prefixing each hero's
    `icon` path with `https://cdn.cloudflare.steamstatic.com`. Cached in the module-level
    `_hero_icon_cache` for the process lifetime (hero constants are static within a patch) —
    fetched at most once per process. Degrades to `{}` (never raises) if the OpenDota call
    fails or raises.
  - `_build_games(db, match_ids, team1_id, team2_id)` — for the given `match_ids`, queries
    `matches.duration`, `SUM(player_match_stats.kills)` grouped by `(match_id, team_id)`, and
    `player_match_stats.hero_id` ordered ascending grouped by `(match_id, team_id)` (all via
    `sqlalchemy.text()` with `bindparam(expanding=True)` for the `match_id IN (...)` clause,
    matching this file's existing raw-SQL style). Assembles one dict per `match_id`, in the
    same order as `match_ids`, mapping raw `team_id`s to `team1`/`team2` via the already-known
    ids. Hero-icon lists are padded/truncated to exactly 5 slots with `_pad5()`, `None` for
    unresolved or missing slots.
  - `resolve_series_result()` calls `_build_games(...)` and attaches the result as `games`
    alongside the existing `team1_wins`, `team2_wins`, `game_count`, `start_time`, `match_ids`
    keys. Returns `None` as before (no `games` key at all) when the series doesn't resolve to
    any DB match.

## Schedule-independent results

`resolve_series_result()` requires a schedule-sheet row (team names + planned date) to anchor
its DB lookup — so a completed match with no corresponding sheet row (a playoff/bracket stage
the sheet never listed row-by-row, or a league that doesn't maintain a comparable spreadsheet at
all) was previously invisible in the Schedule tab, even though it was fully ingested. `GET
/schedule` gains a second, sheet-independent path that derives series directly from the
database:

- `_tally_wins(rows, team1_id)` — shared win/loss tally, extracted out of
  `resolve_series_result()`'s existing inline loop so both paths compute it identically.
- `_build_unscheduled_results(db, claimed_match_ids, div1_team_ids, div2_team_ids)` — queries
  every completed match (`radiant_team_id`/`dire_team_id` both set) not already claimed by a
  sheet-resolved series, clusters consecutive matches between the same two teams into one series
  when the gap between them is under 6 hours (a Bo3/Bo5 session heuristic — there's no
  series-id field to group by instead), and reuses `_build_games(...)` for the per-game
  breakdown. Division badge is inferred from whichever side (`div1`/`div2`) either team was seen
  on anywhere in the sheet across the season; `None` if neither team ever appeared in the sheet.
- `get_schedule()` accumulates `claimed_match_ids` from every sheet-resolved series' `match_ids`
  while looping over `weeks`, then calls `_build_unscheduled_results(...)` and attaches the
  result as a new top-level `extra_results` key. This also runs (and still returns real Results)
  when `SCHEDULE_SHEET_URL` is unset or unreachable with no cache — only `weeks` (Upcoming) is
  empty in that case, not the whole response.
- A side benefit: a sheet row whose team names fail fuzzy matching (`find_team_id()` returns
  `None`) previously showed as bare "vs" with no result at all, since its matches were never
  "claimed." Those matches now surface correctly via this same unclaimed-match path.

Frontend: `loadSchedule()` merges `data.extra_results` into the same `past` array built from the
sheet, before the upcoming/past split — so derived series sort into the existing Results list
chronologically alongside sheet-resolved ones, not a separate section. The division badge
renders nothing when `division` is `null` instead of assuming `div1`/`div2`.

## Endpoints

### `GET /schedule`
Existing endpoint (`backend/routers/admin_ingest.py::schedule_endpoint`, public — no auth
guard). Response shape gains a `games` array per resolved series inside `series_result`:
```json
{
  "match_id": 8813824412,
  "duration": 2143,
  "team1_kills": 32, "team2_kills": 28,
  "team1_heroes": ["https://cdn.cloudflare.steamstatic.com/...png", null, null, null, null],
  "team2_heroes": ["https://cdn.cloudflare.steamstatic.com/...png", null, null, null, null],
  "mvp_player_id": 123456789, "mvp_player_name": "SomePlayer"
}
```
`duration` is `null` for matches ingested before the `Match.duration` column existed, until
re-ingested. Hero slots are padded to 5 with `null` when fewer than 5 heroes resolved. Upcoming
(unresolved) series are untouched — `series_result` stays `None`, with no `games` key.
`mvp_player_id`/`mvp_player_name` are both `null` when the match has no `player_match_stats` row
with `is_mvp = true` — the same flag `POST /twitch/mvp` sets (see `core/twitch-extension.md`).

Response also gains a top-level `extra_results` array — see "Schedule-independent results" above
— of series shaped like a resolved sheet series (`team1`/`team2`/`team1_id`/`team2_id`/
`division`/`datetime_iso`/`match_status: "past"`/`series_result`) but with no `stream_url`,
`stream_label`, or `time` (not applicable — these only exist for sheet rows).

## Frontend rendering

`frontend/app-players.js`'s `renderRow(s)` (used by `loadSchedule()`'s Results section) renders
one `.game-row` `<div>` per entry in `series_result.games`, appended as a sibling immediately
after the series' `.series-row` header:
- `_formatGameDuration(seconds)` — `mm:ss`, or `"—"` when `null`.
- `_gameHeroIconsHtml(heroUrls)` — one `<img class="hero-icon">` per resolved URL (with
  `onerror="this.style.display='none'"`, the same broken-image guard used for player avatars in
  `renderPlayers()`), or a `<span class="hero-icon hero-icon-placeholder">` for a `null` slot.
- Each row also shows `team1_kills`–`team2_kills` and preserves the per-match OpenDota link
  (`https://www.opendota.com/matches/{match_id}`), now scoped to that one game instead of a flat
  "G1 ↗" list next to the score.
- When `mvp_player_id` is present, a ★ star (the same marker used in the player detail modal's
  match history MVP column) precedes the MVP's name, rendered as a `playerLink()` (opens the
  player detail modal), immediately before `.game-row-duration`; games with no MVP set show
  nothing in that position (see `markdown/stories/leaderboard.md`'s "MVP Visibility" section).

The series header's own `.series-links` cell now only carries the series' stream link for past
rows (unchanged for upcoming rows, which still show time + watch link). The old flat
`match_ids`-based link list was removed: `resolve_series_result()` always attaches `games` in the
same order as `match_ids` whenever it returns a non-`None` result (confirmed in
`backend/schedule.py` — `_build_games()` is called unconditionally right after `match_ids` is
computed, from the same non-empty `rows`), so there is no code path where `match_ids` is
populated but `games` is not.

Styling (`frontend/style.css`): `.game-row` mirrors `.series-row`'s 5-column grid
(`40px 1fr 64px 1fr minmax(0, 170px)`) with a `bg-card-hi` background and left padding so it
reads as a nested child under the series row above it. `.hero-icon` is a 20px rounded image;
`.hero-icon-placeholder` uses a dashed `border-soft` border over a darker `k-ink-900` fill (same
visual language as the existing `.card-slot-empty` empty-state convention) so a missing hero slot
is visibly distinct rather than blank.

---

*Covered by `backend/tests/test_issue_87_schedule_game_breakdown.py` (game breakdown) and
`backend/tests/test_schedule_independent_results.py` (schedule-independent results).*
