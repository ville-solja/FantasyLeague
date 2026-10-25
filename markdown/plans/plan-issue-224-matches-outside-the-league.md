# Plan: Matches Outside the League

## Context
A Kanaliiga game was played in a lobby that wasn't started as a league match, so OpenDota doesn't list it under the league and ingest never sees it. The issue asks for an admin way to add such a match. The comment adds the harder case: the match isn't a regular match at all, so OpenDota has no usable data. The players have to provide the `.dem` replay, which is parsed locally and imported as the match's values.

**Why a league match matters:** ingest (`ingest.ingest_league`) only fetches match ids from `/leagues/{id}/matchIds`, and each stored `Match` carries that `league_id`. A match outside the league needs everything ingest would have given it:

| What depends on it | Where | What a manual match needs |
|---|---|---|
| Division | `accolades.league_division` reads the league name; `team_insights`, accolades and the Teams tab group by it | a `league_id` of one of the monitored leagues (Div 1 or Div 2), chosen by the admin |
| Series results on the Schedule | `schedule.resolve_series_result` matches games by `radiant_team_id`/`dire_team_id` and a ±4-day window | the right team ids (a non-league lobby often has none) and a correct `start_time` |
| Scoring week | `weeks.scoring_week_for`: `week_override_id`, else `start_time` | `start_time`; the existing week override (#189) still works |
| Fantasy points | `PlayerMatchStats` rows built by `_build_stat_row`, `fantasy_score`, then `card_points.refresh_card_points` | the same raw stats per player, scored with the same code |
| Players | `_ensure_players` creates `Player` rows by account id | each player's account id |
| Bench substitution, Weekly Report, MVP, leaderboard, player and team popups | all read `matches` and `player_match_stats` | nothing extra once the rows exist |
| **Parse retry** | `find_unparsed_match_ids` picks recent matches whose parse-only stats sum to 0; `refresh_match_stats` deletes and re-inserts rows from OpenDota | **must skip imported replay matches**, or it could replace them with OpenDota's empty or wrong data |
| Short matches | `ingest_match` skips games under 900 s | the same rule |

**Decisions** (change them in review if needed):
- **Two ways in, both in Admin › Matches › Add match:**
  1. **From OpenDota:** when OpenDota has the match but not under the league, the admin enters the match id and picks the league (division). The server fetches `/matches/{id}` and stores it through the existing `ingest_match` with that `league_id`. Parse retry treats it like any ingested match.
  2. **From a replay:** when OpenDota has no usable data, the operator parses the `.dem` **on their own machine** with a script, and the admin uploads the small JSON file it produces. The server validates it, shows a preview, and stores it on confirm.
- **No `.dem` parsing on the server.** Replays are 50–150 MB of untrusted binary. The parser runs locally (`backend/scripts/replay_to_match.py` driving OpenDota's open-source replay parser), and only a validated JSON summary reaches the server. This matches the issue's "locally parsed".
- **Replay parser:** OpenDota's parser (`odota/parser`, Java, run as a local Docker container) emits per-tick and combat-log events. The script turns them into one row per player with the stats `_build_stat_row` reads. Step 0 is a spike that confirms the parser's current interface and which stats come out reliably. Stats it can't produce (likely `teamfight_participation`, possibly `stuns`) are stored as 0 and the match is marked partial, using the existing partial-stat markers (`unparseable-match-handling.md`).
- **Teams:** the admin picks the Radiant and Dire teams from the season's teams, prefilled when OpenDota or the replay names them. Both are required, so Schedule results and team views work.
- **Source on the match:** a new `matches.source` column: `league` (default for existing and ingested rows), `opendota_manual` (path 1) and `replay` (path 2). Parse retry, stuck-match flagging and Retry parse skip `replay` matches. Admin › Matches shows a "Manual" or "Replay" chip.
- **Safety:**
  - Add match needs an admin with a recent re-auth (`require_recent_reauth`), like other scoring-changing actions, and writes an audit entry (`admin_match_added`, with source, match id and league).
  - It never overwrites a league-ingested match. Re-importing a `replay` or `opendota_manual` match replaces its rows (audited), so a corrected replay file can fix a mistake.
  - Excluding a manual match from scoring uses the existing exclusion toggle; there is no separate delete.
- **After storing:** the same follow-ups as ingest run: Twitch MVP re-apply, card points refresh, panel cache bust, bench substitutions re-run for the affected week (as the week override does), and the schedule cache is cleared so the series result appears.
- **If the league later lists the match:** `ingest_league` skips ids already stored, so the manual row stays. That is acceptable; the admin can re-add it from OpenDota to refresh it.

Resolves GitHub issue #224.

## User Stories

### Add a Match OpenDota Has Outside the League
**User story**
As an admin, I want to add a match by its id when the lobby wasn't started as a league match, so that its players get their fantasy points and the series result shows.

**Acceptance criteria**
- **Form:** Admin › Matches has **Add match** with a match id, a league picker (the monitored leagues, shown with their division), and Radiant and Dire team pickers.
- **Preview:** **Fetch** loads `/matches/{id}` from OpenDota and shows the start time, duration, winner, the ten players (name, hero, K/D/A) and the team names OpenDota gives; the team pickers are prefilled when the names match a team.
- **Refusals with a message:**
  - the match is already stored as a league match;
  - OpenDota has no player data for it ("Use a replay import instead");
  - it is shorter than 15 minutes;
  - a team isn't chosen.
- **Store:** **Add** needs a recent re-auth, stores the match through the normal ingest code with the chosen league, writes `source = opendota_manual`, and audits `admin_match_added`.
- **Everything follows:** the match counts in its week, the Schedule series result, leaderboards, Weekly Report and team views like any league match, and parse retry treats it normally.

### Import a Match From a Replay
**User story**
As an admin, I want to import a match from a replay file parsed on my own machine, so that a game OpenDota can't read still counts.

**Acceptance criteria**
- **Local script:** `python scripts/replay_to_match.py replay.dem` runs the parser locally and writes `match-<id>.json`, with the match id, start time, duration, winner, picks and bans, team names when present, and per player: account id, side, hero and every stat `_build_stat_row` reads. Stats the parser can't produce are listed under `missing_stats`.
- **Upload:** **Add match › From replay** accepts that JSON (at most 56 KB). The server validates it against a strict schema: exactly ten players, five per side, known hero ids, no unknown keys, numbers in sane ranges. It rejects anything else with the field that failed.
- **Preview:** the same preview as the OpenDota path, plus a "Partial stats: …" note when `missing_stats` is not empty, and a warning for players not in the season's pool (they're stored, as ingest stores them).
- **Store:** needs a recent re-auth; writes `source = replay`; marks the match partial when stats are missing (existing partial-stat markers); audits `admin_match_added` with `source=replay`.
- **Parse retry leaves it alone:** `find_unparsed_match_ids`, `mark_stuck_matches_unparseable` and **Retry parse** skip `replay` matches.
- **Corrections:** importing the same match id again replaces a `replay` or `opendota_manual` match's rows after a confirmation, audited. A league-ingested match is never replaced.

### Manual Matches Are Visible as Such
**User story**
As an admin, I want manual and replay matches marked in Admin › Matches, so that I know which results didn't come from the league.

**Acceptance criteria**
- **Chip:** Admin › Matches shows "Manual" (from OpenDota) or "Replay" next to the match, with a tooltip saying who added it and when (from the audit).
- **Filter:** a "Manual only" filter lists them.
- **Public views:** players see no difference, except the existing partial-stats marker where stats are missing.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py`, `backend/migrate.py` | `Match.source` (`String`, default `"league"`, not null); numbered migration with a `PRAGMA table_info` guard, backfilling `league` |
| `backend/ingest.py` | `ingest_match` takes `source` and team-id overrides; `store_manual_match(db, payload, league_id, radiant_team_id, dire_team_id, source)` shared by both paths (stat rows through `_build_stat_row`, bans, MVP re-apply, card points, panel cache); parse retry and stuck flagging skip `source == "replay"` |
| `backend/manual_match.py` (new) | Replay JSON schema validation, preview building, the replace rule |
| `backend/routers/admin_matches.py` | `POST /admin/matches/manual/preview` (OpenDota id or JSON), `POST /admin/matches/manual` (store; `require_recent_reauth`); `source` in `GET /admin/matches`; Retry parse refuses `replay` |
| `backend/weeks.py`, `backend/schedule.py` | Re-run substitutions for the match's week; clear the schedule cache after storing |
| `backend/scripts/replay_to_match.py` (new) | Local only: send the `.dem` to a local parser container, aggregate events into the JSON format; standard library only |
| `frontend/app-admin.js`, `frontend/index.html`, `frontend/style.css` | Add match dialog (two tabs, preview, team pickers), source chips and filter; tokens only, CSS before GUIDED TOUR |
| `markdown/features/reference/matches-outside-the-league.md`, `markdown/features/reference/ingest.md`, `markdown/features/reference/unparseable-match-handling.md`, `markdown/ui_description/admin.md` | Docs, including the operator run book for the replay path |
| `backend/tests/test_issue_224_matches_outside_the_league.py` | Tests |

New column `matches.source` (migration). No new env var.

### Step 0 — Parser spike (before Step 4)
Run OpenDota's parser locally on one real Kanaliiga replay and record:
- how it is started and called today;
- which of the stored stats it yields directly, which need aggregation, and which it can't give.

Write the findings into the feature doc. If the parser can't be run reasonably, the replay path falls back to the same JSON filled in by hand from the in-client scoreboard, and the plan is updated before Step 4.

### Step 1 — Source column and the shared store
Add `Match.source` with its migration. Refactor `ingest_match` so the OpenDota path and the replay path store through one function: same short-match rule, same stat rows, same follow-ups. Parse retry and stuck flagging skip `replay`.

### Step 2 — From OpenDota
Preview endpoint: fetch the match, refuse league duplicates, matches with no player data and short matches, and suggest teams by name. The store endpoint uses `store_manual_match` with `source = opendota_manual`, and audits.

### Step 3 — Admin UI
The Add match dialog (OpenDota tab first), preview, team pickers, the re-auth flow through `adminFetch`, source chips and the Manual-only filter.

### Step 4 — From a replay
The JSON schema and validation in `manual_match.py`, the preview and store with `source = replay`, partial-stat markers for `missing_stats`, the replace-on-confirm rule, and the local `replay_to_match.py` script with its run book.

### Step 5 — Follow-ups, docs and tests
Re-run substitutions for the week, clear the schedule cache, write the docs.

**Tests:**
- the migration adds `source` and backfills `league`;
- the OpenDota path stores with the chosen league and teams; refuses league duplicates, no-player-data and short matches;
- the stored match appears in its week, the Schedule series result, the leaderboard and the team view;
- replay JSON: strict validation (player count, sides, unknown keys, ranges, size), the preview, and partial markers for missing stats;
- parse retry, stuck flagging and Retry parse skip `replay` matches;
- a re-import replaces a manual match and never a league match;
- re-auth is required and the audit entries are written;
- `replay_to_match.py` aggregation against a small recorded parser output fixture;
- frontend harness: the dialog, the preview, the chips and the filter.

## Verification
- **From OpenDota:** on the test copy, add a known non-league lobby match with Div 1 and its two teams. The series result appears on the Schedule, the players' points appear in that week's leaderboard and Weekly Report, and the audit shows the entry.
- **From a replay:** parse a real replay locally, upload the JSON, and check the preview against the in-client scoreboard; store it and check the same views. Run Retry unparsed and confirm the match is untouched.
- **Duplicates:** adding a match the league already has is refused; re-importing a corrected replay replaces the rows.
- **Deploy:** run `bash scripts/backup-db.sh` before deploying, because of the migration.
