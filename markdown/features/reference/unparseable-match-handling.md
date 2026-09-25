# Unparseable Match Handling

Tracks whether each match's replay has been parsed. Players see when a score is based on partial stats, and admins can retry a parse, mark a match as unparseable, and exclude it from fantasy scoring.

*(see `markdown/plans/plan-unparseable-match-handling.md`)*

---

## Why it exists

OpenDota records kills, deaths, assists, last hits and GPM for every match. Observer wards, stuns, teamfight participation, runes and camps only exist once OpenDota parses the replay. When Valve's replay file is missing or broken, the match never parses, and every player in it keeps those stats at 0.

Example: radres scored 9.4 in parsed match 9000543547 but 0.9 in match 9000632714, whose replay URL returned HTTP 502 on 2026-09-24. The scoring was correct for the data it had.

## Parse status

`matches.parse_status` (`String`, nullable) is one of:

| Value | Meaning |
|---|---|
| `parsed` | OpenDota has parsed the replay. All stats are real. |
| `unparsed` | Not parsed yet. The background retry pass re-checks it within `INGEST_PARSE_RETRY_HOURS`. |
| `unparseable` | Still unparsed past the retry window, or marked by an admin. The background pass sends no more parse requests. |

`matches.excluded_from_scoring` (`Boolean`, default false) removes the match from every points aggregation. Only an admin sets it.

### How the status is kept current (`backend/ingest.py`)

- `ingest_match()` stores `parsed` or `unparsed`, based on the payload's `version` (`_is_unparsed()`).
- `refresh_match_stats()` sets `parsed` when it replaces a match's rows with parsed stats.
- `find_unparsed_match_ids()` skips `unparseable` matches, so the retry pass neither fetches them nor requests a parse.
- `mark_stuck_matches_unparseable(db, max_age_hours)` runs at the end of every `retry_unparsed_matches()` pass. It marks each `unparsed` match whose `start_time` is older than the window as `unparseable`, and writes a `match_marked_unparseable` audit row for each one. It never sets `excluded_from_scoring`. The window it uses is `max(max_age_hours, INGEST_PARSE_RETRY_HOURS)`, so a manual pass with a narrow window cannot flag recent matches.

### Migration `027_match_parse_status`

Adds both columns. It then backfills `parse_status` for rows where it is NULL. Matches whose stat rows sum to 0 on `teamfight_participation`, `stuns` and `obs_placed` become `unparsed`. All other matches become `parsed`. The backfill never overwrites an existing status.

On the first poll cycle after deploy, every backfilled `unparsed` match older than the retry window is flagged `unparseable`. This only happens when `INGEST_PARSE_RETRY_HOURS > 0` and at least one league is monitored, since the poll loop skips the retry step otherwise. Each flagged match gets its own `match_marked_unparseable` audit row, so a database with many historical unparsed matches gets many rows in one cycle.

## Exclusion from scoring (`backend/match_scoring.py`)

The shared helpers are:

- `scored_match_sql(alias="m")` is a SQL condition on a joined `matches` row. It goes into the `JOIN … ON` clause, so an excluded match drops out of the `CASE WHEN m.match_id IS NOT NULL` sums.
- `scored_stat_sql(match_id_col="s.match_id")` is a `NOT IN (excluded match IDs)` condition. It is for queries that do not join `matches`.

These places apply the helpers:

| Site | What is filtered |
|---|---|
| `routers/leaderboard.py` | `GET /top`, `GET /leaderboard`, `GET /leaderboard/roster`, `compute_season_standings()` (season leaderboard + End Season archive), `GET /leaderboard/weekly`, including the MVP-bonus row queries |
| `routers/cards.py::_build_roster_response` | Week card stat sums and match counts (locked and unlocked week), week MVP rows, season points and season MVP rows |
| `routers/players.py` | `GET /players` and `GET /teams/{id}` avg/total points; `GET /players/{id}` total/avg/best (match count and history still list every match) |
| `enrich.py::crawl_player_facts` | `avg_fantasy_points` and `best_match_points` profile facts |
| `routers/weekly_summary.py` | An excluded match stays listed, carries `excluded_from_scoring: true`, and its players' `points` are `null` |

A Twitch MVP bonus on an excluded match is dropped along with the rest of the match. Ingest writes, purge/reset deletes, the schedule, match lists, the Twitch EBS series payload (per-match `fantasy_points`) and the simulate endpoint are not filtered. `card_draw.py` weights picks by how many cards the user owns, not by points, so exclusion does not affect it.

## Endpoints

### `GET /admin/matches`
Each row now also includes `parse_status` and `excluded_from_scoring`.

### `POST /admin/matches/{match_id}/retry-parse`
Admin only. Accepts any match, whatever its `parse_status` (only the UI limits the button to unparsed rows). Returns 404 for an unknown match, and 409 while `ingest.INGEST_LOCK` is held (a poll cycle, manual ingest or parse-retry run). The lock is always released. It re-fetches the match with `refresh_match_stats()`:

| `outcome` | Meaning |
|---|---|
| `refreshed` | OpenDota has now parsed the match. Stat rows and `fantasy_points` were replaced, and `parse_status` is `parsed` |
| `requested` | Still unparsed. A parse was requested with `request_parse()` |
| `cooldown` | Still unparsed. A parse was requested less than `INGEST_PARSE_REREQUEST_HOURS` ago, so none was sent |
| `request_failed` | Still unparsed. OpenDota rejected the parse request |

Response: `{"match_id", "outcome", "parse_status"}`. Busts the schedule cache only on `refreshed`. Audited as `admin_match_retry_parse` (`detail="match <id> fetch=<refresh result> outcome=<outcome>"`).

### `PATCH /admin/matches/{match_id}/scoring`
Admin only, 404 for an unknown match. Body: `{"unparseable": bool | null, "excluded_from_scoring": bool | null}`. An omitted field is left unchanged. `unparseable: true` sets `parse_status = 'unparseable'`. `unparseable: false` on an unparseable match restores `unparsed` or `parsed`, depending on the stat-row signature, and the retry pass picks the match up again while it is inside the window. A match older than the window that is still unparsed is flagged again on the next pass. To retry one in the UI, untick **Unparseable** and then click **Retry parse** on that row before the next poll cycle re-flags it. Busts the schedule cache. Response: `{"match_id", "parse_status", "excluded_from_scoring"}`. Audited as `admin_match_scoring`, with the old and new values of both fields in `detail`. The audit row is written even when the body changes nothing (for example `{}`).

### Public payload additions
- `GET /players/{id}`: each `match_history` row has `parse_status` and `excluded_from_scoring`.
- `GET /schedule`: each game in `series_result.games` has `excluded_from_scoring`.
- `GET /weekly-summary/{week_id}`: each match has `excluded_from_scoring`.

## UI

- **Player popup match history.** A match that is unparsed or unparseable shows a "Partial stats" badge next to its points. The tooltip says the replay has not been parsed, so wards, stuns, teamfight, runes and camps count as 0. An excluded match shows a dash and a "Not scored" badge.
- **Schedule game rows and the Weekly Report.** Excluded matches show a "Not scored" badge. In the Weekly Report, player points on those matches show as a dash.
- **Admin Matches tab.** A Parse column shows Parsed / Unparsed / Unparseable, with a Retry parse button on unparsed rows. A Scoring column has Unparseable and Not scored checkboxes. An "Unparseable only" filter sits in the header.

## Configuration

No new variables. Uses the existing parse-retry settings:

| Variable | Default | Description |
|---|---|---|
| `INGEST_PARSE_RETRY_HOURS` | `48` | Retry window. An unparsed match older than this is auto-marked `unparseable` |
| `INGEST_PARSE_REREQUEST_HOURS` | `6` | Minimum gap between parse requests for one match |

## Tests

`backend/tests/test_unparseable_match_handling.py` has 41 tests and makes no network calls.
