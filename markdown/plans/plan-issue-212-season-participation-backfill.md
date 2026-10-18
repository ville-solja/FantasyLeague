# Plan: Season Participation Backfill

## Context
#50 added a seasons-played count, and with it `backend/scripts/backfill_played.py`, which records one `played` accolade per player per past season from that season's OpenDota leagues. This issue asks to find Kanaliiga's earlier league ids, measure how many players that covers, and backfill participation if the number is reasonable. Ingesting the old seasons' matches is out of scope: only participation is recorded. Other accolades from old seasons are not attempted.

**Findings (2026-10-18)** from OpenDota's `/leagues` list, plus `/leagues/{id}/matchIds` and `/matches/{id}` for every listed match.

The SQL explorer doesn't index these leagues: they are tier "excluded", so the explorer has none of their matches.

| Season | League id(s) and OpenDota name | Matches | Players |
|---|---|---|---|
| 4 | 12481 "Kanaliiga" (no number; played Nov–Dec 2020, between S3 and S5) | 26 | 43 |
| 5 | 12837 "Kanaliiga Season 5" | 46 | 38 |
| 6 | 13501 | 114 | 62 |
| 7 | 13943 | 85 | 55 |
| 8 | 14537 | 60 | 45 |
| 9 | 15007 | 119 | 83 |
| 10 | 15715; 15753 "… Lower Division" has **0 matches** | 136 | 90 |
| 11 | 16268 + 16270 "… Lower" | 73 + 37 | 92 |
| 12 | 17028 + 17029 "… Lower" | 71 + 35 | 100 |
| 13 | 17812; 17813 "… Lower" has **0 matches** | 107 | 84 |
| 14 | 18649 + 18650 "… Lower" | 67 + 26 | 86 |
| 15 | 19368 + 19369 "… Lower" | 67 + 50 | 88 |
| 16 (live) | 20162 + 20163 "… Lower" | 36 + 28 | 80 |

Not used:
- 17814, "Kanaliiga Season 3 Middle": 0 matches.
- Seasons 1–3: no OpenDota league exists.

**Totals:**
- Seasons 4–15: **305 distinct players**, **866 `played` rows**, about **1,180 OpenDota calls** in one cold run.
- **Seasons per player:** 1 → 121 players, 2 → 61, 3 → 39, 4 → 26, 5 → 15, 6 → 14, 7 → 12, 8 → 7, 9 → 1, 10 → 6, 11 → 2, 12 → 1.
- **Season 16:** 61 of its 80 players took part earlier, so most current players gain a meaningful count.
- **Data quality:** every league match carried every player's account id; there were no anonymous slots. 14 match fetches failed transiently and will be retried.

**Gaps that can't be recovered from OpenDota:**
- **Seasons 1–3:** no leagues exist.
- **Season 10 and Season 13 Div 2:** their Lower leagues have no matches.
- **Seasons 5–9:** one league each, so whether a lower division existed or played elsewhere is unknown.

Counts are therefore "seasons played since Season 4" for every player, and an undercount for players who only played Div 2 in S10 or S13. The bulk Played paste (#50) can add known rosters for those.

**Decisions** (change them in review if needed):
- **Checked-in league list:** the table above becomes a data file, `backend/scripts/kanaliiga_leagues.json` (season → league ids, with notes). This includes the S4 mapping of the unnumbered league 12481. The script stops relying on name discovery for past seasons.
- **One command for everything:** `backfill_played.py --all` runs every season in the file except the live one (S4–S15), in order, through the existing per-season logic. Steps 2–4 cover the call budget, the report and the label.
  - **Same safeguards:** cache, pauses, `ON CONFLICT DO NOTHING`, audit per season, dry run.
- **Call budget:** `--max-calls N` (default 900) stops cleanly when the budget is used and prints how far it got. The cache makes the next run continue, so the backfill can be spread over two days if OpenDota's daily quota is shared with live ingest.
- **Report:** the run ends with per-season and total figures (players, new rows, skipped as already recorded, matches unreadable), and the seasons-per-player distribution. The operator can compare it with the table above.
- **"Since Season 4" label:** the Players tab Seasons legend and the count's hover text say counts start at Season 4. The live season counts as before.
- **The Players list stays the current season:** the tab still lists the current pool. History lives only in `season_accolades`, so players from old seasons who aren't in the pool appear in History and the Hall of fame, not in the Players list. This matches the issue's comment.
- **No match ingest, no new tables, no migration:** rows go into the existing `season_accolades` with `kind = 'played'` and `source = 'admin'`.

Resolves GitHub issue #212.

## User Stories

### Past Seasons' Participation Is Backfilled in One Run
**User story**
As the operator, I want one command that records who played in every past Kanaliiga season found on OpenDota, so that seasons-played counts are right without ingesting old matches.

**Acceptance criteria**
- **League file:** `backend/scripts/kanaliiga_leagues.json` lists seasons 4–16 with their league ids and a note per season (empty Lower leagues, the unnumbered S4 league). A test checks it is valid: unique ids, seasons ascending, each league an int.
- **`--all`:** runs every listed season except the live one (`accolades.current_season_label`), oldest first, using the same per-season code as `--season`. Each season writes its own `admin_accolade_added` audit entry (`played=N source=backfill`).
  - `--dry-run --all` writes nothing.
  - A second run adds nothing.
- **`--max-calls N` (default 900):** caps OpenDota calls per run. When it's reached, the run stops after the current match, keeps the cache, records what it finished, and exits 2 with "Budget used: resume to continue from Season N". A resumed run spends no calls on cached matches.
- **Unreadable matches:** a match that can't be fetched after the client's retries is counted in the report and retried on the next run. The season's rows are still written for the matches that were read.
- **Report:** the run prints a per-season line (players, new rows, already recorded, unreadable matches), the totals, and the seasons-per-player distribution.
- **Existing modes unchanged:** `--season` and `--league` work as before. S4 resolves through the file even though its OpenDota name has no number.

### Counts Say Where They Start
**User story**
As a visitor, I want the seasons count to say it starts at Season 4, so that a long-time player's number isn't mistaken for their whole history.

**Acceptance criteria**
- **Players tab:** the Seasons legend reads "Seasons played since Season 4 (earlier seasons have no OpenDota record)".
- **Hover text:** the count's hover text lists the seasons and ends with "Counted from Season 4".
- **One constant:** the first counted season is a single constant used by the backend (`/players` response field `seasons_counted_from`) and the frontend. The text isn't hard-coded in two places.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/scripts/kanaliiga_leagues.json` (new) | Season → league ids, with notes |
| `backend/scripts/backfill_played.py` | `--all`, `--max-calls`, the final report, and reading the league file for season resolution |
| `backend/accolades.py` | `FIRST_COUNTED_SEASON = 4` |
| `backend/routers/players.py` | `seasons_counted_from` on `GET /players` |
| `frontend/app-players.js`, `frontend/index.html` | Seasons legend and hover text |
| `markdown/features/reference/season-participation-backfill.md` (new), `markdown/features/reference/season-winners-and-holo-cards.md`, `markdown/ui_description/players.md` | Docs, including the league table and the run book |
| `backend/tests/test_issue_212_season_participation_backfill.py` | Tests |

No migration, no new env var.

### Step 1 — League file
Write the JSON from the table: S4–S16, the ids, and notes for 15753, 17813 and 17814. Leagues with 0 matches are kept listed so the gaps are explicit; their notes say "no matches".

### Step 2 — Script
Add `--all` (it iterates the file and skips the live season), `--max-calls` (a counter around the OpenDota calls, then a clean stop with exit 2), the report, and season resolution through the file before name parsing. Reuse the existing cache, validation, pauses and audit.

### Step 3 — Label
Add `FIRST_COUNTED_SEASON`, the `seasons_counted_from` field, and the legend and hover text.

### Step 4 — Run (after deploy, by the operator)
1. `bash scripts/backup-db.sh`.
2. `python scripts/backfill_played.py --all --dry-run`. Compare it with the table: about 305 players and 866 rows.
3. `python scripts/backfill_played.py --all`. Rerun until it reports no budget stop; the counts should match the dry run.

### Step 5 — Docs and tests
**Docs:** the feature doc with the league table, the gaps and the run book. The season-winners doc and the Players UI description.

**Tests**, all with OpenDota mocked:
- the league file is valid;
- `--all` skips the live season and runs seasons in order;
- dry run writes nothing; rerun adds nothing;
- the budget stop: exit 2, a resume continues, no calls spent on cached matches;
- unreadable matches are counted and retried;
- the report figures and distribution;
- S4 resolves through the file;
- `seasons_counted_from` is in `/players`;
- the legend and hover text.

## Verification
- **Dry run:** `--all --dry-run` on a copy of production lists S4–S15 with figures close to the table: about 305 players and 866 rows.
- **Real run:** the Players tab shows counts for current players (61 of S16's 80 have earlier seasons), and the hover text says "Counted from Season 4".
- **Rerun:** writes nothing, and the audit log has one entry per season.
- **Budget stop:** with `--max-calls 50`, the run stops cleanly and a rerun continues from the cache.
