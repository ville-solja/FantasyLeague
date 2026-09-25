# Plan: Unparseable Match Handling

## Context
A support player (radres, account 56845125) shows 0.9 fantasy points for match 9000632714 and 9.4 for match 9000543547. Both were played against Hoxhunt Fortum on 15 September. Investigation on 2026-09-24 found the scoring code correct and the data incomplete:

- **The calculation is correct.** Recomputing both matches with the production weights gives exactly the stored values: 9.431 and 0.945.
- **9000632714 has never been parsed.** OpenDota returns `version: null` and `od_data.has_parsed: false`. Every parse-only stat is therefore 0: observer wards, stuns, teamfight participation, runes and camps. In the parsed match, those stats earned radres roughly 7.5 of the 9.4 points.
- **The replay looks unavailable.** Valve's replay URL for 9000632714 returns HTTP 502, while the parsed match's replay returns 200. OpenDota cannot parse without the replay, so the match may never parse. A single 502 can be temporary, but the match is nine days old.
- **The app has stopped retrying.** The parse-retry pass only looks back `INGEST_PARSE_RETRY_HOURS` (48 hours), so it stopped re-checking this match on 17 September. Nothing tells an admin or a player that the score is partial.
- **The 0 assists is real.** OpenDota itself records 0 assists for radres in 9000632714. That is not an app bug.
- **Assists are in the current build but not in production.** Production runs commit 9c147f2, whose `SCORING_STATS` has no `assists`. The assists fix (issue #130) ships with the pending release, and stored points need `POST /recalculate` once after deploy. No separate issue is needed.

Every player in an unparsed match is underscored the same way, so one lost replay depresses ten players' weekly points and every roster holding them. This plan makes partial matches visible, lets an admin retry or give up on a parse, and lets an admin exclude a permanently unparseable match from scoring.

**Assumptions:**
- Estimating missing stats, for example from a player's average, is out of scope. Scores stay factual or are excluded.
- A match counts as "unparsed" using the existing `find_unparsed_match_ids()` signature: zero teamfight participation, stuns and observer wards across all its stat rows.
- Keeping the partial score stays the default. Exclusion is an explicit admin decision.

## User Stories

### See When a Match Score Is Partial
**User story**
As a fantasy player, I want matches with incomplete stats to be marked so that I don't mistake a missing replay for a bad performance.

**Acceptance criteria**
- A player's match history, in the player popup, shows a "Partial stats" marker on every match the app considers unparsed
- The marker's tooltip says the replay has not been parsed, so wards, stuns, teamfight, runes and camps count as 0
- A match marked excluded from scoring shows "Not scored" instead, and its points display as a dash
- Parsed matches show no marker

### Track Parse Status in the Admin Match Table
**User story**
As an admin, I want to see each match's parse status and retry a parse on demand so that I can fix partial scores without waiting for the background pass.

**Acceptance criteria**
- The admin Matches table has a Parse column showing Parsed, Unparsed, or Unparseable
- Each unparsed match has a "Retry parse" button that calls `POST /admin/matches/{match_id}/retry-parse`
- Retry re-fetches the match from OpenDota. If it is now parsed, its stat rows and fantasy points are replaced, as the background pass does. If not, a parse is requested from OpenDota, subject to the existing re-request cooldown
- The response says what happened: `refreshed` (now parsed, stats replaced), `requested` (parse requested), `cooldown` (a request was sent too recently, none sent) or `request_failed` (OpenDota rejected the request). The table refreshes
- Each retry is written to the audit log as `admin_match_retry_parse`
- The endpoint is admin-only and returns 404 for an unknown match

### Mark a Match Unparseable and Choose How It Scores
**User story**
As an admin, I want to mark a match as unparseable and decide whether it still counts, so that one lost replay does not unfairly sink ten players' fantasy points.

**Acceptance criteria**
- `PATCH /admin/matches/{match_id}/scoring` accepts `{"unparseable": bool, "excluded_from_scoring": bool}` and is admin-only
- A match marked unparseable is skipped by the background parse-retry pass, which never requests a parse for it again. An admin can still request one with Retry parse
- A match excluded from scoring contributes nothing to weekly and season leaderboards, the roster leaderboard, card points in rosters, or the weekly summary's points
- An excluded match still appears in schedules, match lists and player match history, labelled "Not scored"
- Clearing either flag restores normal behaviour, and the parse retry picks the match up again if it is still unparsed. A match older than the retry window that is still unparsed is flagged unparseable again on the next pass
- Every change is written to the audit log as `admin_match_scoring` with the old and new values

### Flag Stuck Matches Automatically
**User story**
As an admin, I want matches that stay unparsed after repeated parse requests to be flagged for me, so that I notice lost replays without checking each match by hand.

**Acceptance criteria**
- When the parse-retry pass finds a match still unparsed and older than `INGEST_PARSE_RETRY_HOURS`, it marks the match unparseable instead of dropping it silently
- Auto-marking never sets `excluded_from_scoring`. That stays an admin decision
- The auto-mark is written to the audit log as `match_marked_unparseable` with the match ID
- The admin Matches table can filter to unparseable matches

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `Match.parse_status` (`String`, nullable: `parsed` / `unparsed` / `unparseable`) and `Match.excluded_from_scoring` (`Boolean`, default false) |
| `backend/migrate.py` | Migration `027_match_parse_status`: add both columns, then backfill `parse_status` from the existing unparsed signature |
| `backend/ingest.py` | Set `parse_status` on ingest and refresh; skip `unparseable` matches in `find_unparsed_match_ids()`; auto-mark matches past the retry window |
| `backend/routers/admin_matches.py` | `parse_status` and `excluded_from_scoring` in `GET /admin/matches`; new `POST /admin/matches/{id}/retry-parse` and `PATCH /admin/matches/{id}/scoring` |
| `backend/routers/cards.py`, `backend/routers/leaderboard.py`, `backend/routers/weekly_summary.py` | Exclude `excluded_from_scoring` matches from every points aggregation |
| `backend/routers/players.py` | `parse_status` and `excluded_from_scoring` per match in player match history |
| `frontend/app-admin-matches.js` | Parse column, Retry parse button, scoring toggles, unparseable filter |
| `frontend/app-players.js` | "Partial stats" and "Not scored" markers in the player popup's match history |
| `backend/tests/test_unparseable_match_handling.py` | Tests for every acceptance criterion |

### Step 1 — Model and migration
Add both columns to `Match`, and add migration `027_match_parse_status` with the usual `PRAGMA table_info` guard. The backfill sets `parse_status = 'unparsed'` for matches matching the signature in `find_unparsed_match_ids()`, and `'parsed'` for the rest. `excluded_from_scoring` defaults to false.

### Step 2 — Ingest keeps the status current
- `ingest_match()` and `refresh_match_stats()` set `parse_status` from `_is_unparsed(data)`.
- `find_unparsed_match_ids()` skips matches whose `parse_status` is `'unparseable'`.
- A new step at the end of `retry_unparsed_matches()` marks `unparsed` matches older than the retry window as `unparseable`, and writes the audit entry.

### Step 3 — Admin endpoints
Both new endpoints go in `admin_matches.py` with `require_admin` and `_audit`. `retry-parse` reuses `refresh_match_stats()` and `request_parse()` from `ingest.py`, and must take `INGEST_LOCK` (return 409 when it is held), like `POST /ingest/retry-unparsed`. The `PATCH` body uses a Pydantic model with two optional booleans.

### Step 4 — Exclude from scoring everywhere
Add shared SQL helpers for "match counts for scoring" in `backend/match_scoring.py` (`scored_match_sql()`, `scored_stat_sql()`), and apply them at every points aggregation. Before writing code, list the current sites with:

```bash
grep -rn "player_match_stats\|PlayerMatchStats" backend --include=*.py | grep -v tests | grep -v migrate
```

Card points are recomputed from raw stat sums with modifiers, not from `fantasy_points`. So the filter must go into the stat aggregation in `_build_roster_response`, not only into leaderboard sums. `card_draw.py` needs no filter: it weights picks by how many cards the user owns, not by points.

### Step 5 — Frontend
- Admin Matches: add a Parse column and a Retry parse button; put the two scoring flags in two inline checkboxes on each row; add an "Unparseable only" filter.
- Player popup: add the markers and tooltip. Escape everything rendered with `_escHtml`.

### Step 6 — Resolve the reported match
After deploying, mark 9000632714 unparseable. Then decide with the league whether to exclude it from scoring.

## Verification
- `cd backend && python3 -m pytest tests/test_unparseable_match_handling.py -v`, then the full suite. Bump the suite-size tripwire in `test_issue_85_split_admin_router.py`.
- The CLAUDE.md schema test (`tests/test_migrate.py::TestSchemaCoverage`) passes with the two new columns.
- Use a fixture with one parsed and one unparsed match for the same players. Excluding the unparsed match removes exactly its points from the weekly leaderboard, season leaderboard, roster leaderboard and roster card points, and nothing else.
- Retry parse on an unparsed match whose OpenDota data is now parsed replaces its stats. On one still unparsed, it records a parse request and a second call inside the cooldown does not.
- A match older than the retry window that is still unparsed becomes `unparseable` after one retry pass and is never requested again.
- The player popup shows the markers for 9000632714 on a copy of production data.
- Deploy note: run `POST /recalculate` once after the pending release, so stored points include assists (issue #130). This is independent of this plan.
