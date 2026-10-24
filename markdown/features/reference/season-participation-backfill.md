# Season Participation Backfill

Records who played in each past Kanaliiga season (S4–S15) as `played` accolades, from the seasons' OpenDota leagues, so seasons-played counts are right. Old matches are not ingested. Plan: `markdown/plans/plan-issue-212-season-participation-backfill.md`.

---

## Leagues (as found 2026-10-18)

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

- **Not used:** 17814 "Kanaliiga Season 3 Middle" has no matches, and Seasons 1–3 have no OpenDota league.
- **S4–S15 totals:** 305 players, 866 `played` rows, about 1,180 OpenDota calls cold.

## Gaps

- **Seasons 1–3:** no league on OpenDota.
- **S10 and S13 Div 2:** their Lower leagues have no matches.
- **S5–S9:** a single league each.

Counts read "since Season 4". Known rosters for the gaps can be added with the bulk Played paste.

## Run book

After deploy, from `backend/` on the server:

1. `bash scripts/backup-db.sh` (from the repo root).
2. `python scripts/backfill_played.py --all --dry-run`. Compare the report with the table above: about 305 players and 866 rows over 12 seasons.
3. `python scripts/backfill_played.py --all`. After a budget stop (exit 2), run the same command again until it exits 0; the cache makes each rerun skip the matches already read. The counts should match the dry run.
4. If the report lists unreadable matches, run it once more: those matches weren't cached and are fetched again.

A full rerun writes nothing new, and the audit log has one `admin_accolade_added` entry per season (`played=N source=backfill`, actor "script").

## Script

`backend/scripts/backfill_played.py`, extended from #50 (see [season-winners-and-holo-cards.md](season-winners-and-holo-cards.md#backfill-of-played)).

- **League file:** `backend/scripts/kanaliiga_leagues.json` maps each season to its league ids, with a note per season. `empty_leagues` (15753, 17813) and `unused_leagues` (17814) are listed so the gaps are explicit, but never fetched. `load_league_file` rejects the file (exit 1, nothing written) when a league id is repeated or isn't a positive integer, seasons aren't strictly ascending, or a season lists no league. The script itself holds no league ids.
- **`--all`:** runs every season in the file except the live one (`accolades.current_season_label`), oldest first, through the same per-season code as `--season`. It can't be combined with `--season` or `--league`. For a season from the file, the label is "Season N" and the league names aren't fetched.
- **`--season "Season N"`:** without `--league`, the season's leagues come from the file (so Season 4 resolves although its league is named just "Kanaliiga"); a season not in the file falls back to discovery by name. `--league` ids take precedence over the file.
- **`--max-calls N`** (default 900, at least 1): caps the OpenDota calls one run makes: league names, match-id lists and matches. Cache hits don't count, and neither do the OpenDota client's own retries of a call (up to 5 per call), so a run sends at most about five times the budget in HTTP requests. When the budget is used, the run stops before the next call, records the seasons it finished, prints the report for them and "Budget used: resume to continue from Season N", and exits 2. The unfinished season is recorded by the next run.
- **Unreadable matches:** a match OpenDota doesn't return (after the client's retries) is counted, isn't cached, and is fetched again on the next run. The season's rows are written for the matches that were read.
- **Report:** one line per season (`Season 5: 46 matches, 38 players, 38 new rows, 0 anonymous slots skipped, 0 already recorded, 0 unreadable matches`), then a total line (seasons, distinct players, played rows, new rows, already recorded, unreadable matches) and the seasons-per-player distribution (`  1 season: 121 players`).
- **Exit codes:** 0 done; 1 when the league file is invalid, a season can't be resolved, or a listed league returns no matches; 2 on a budget stop.

## Counts say where they start

- `accolades.FIRST_COUNTED_SEASON = 4` is the one constant. `GET /players` puts it on every row as `seasons_counted_from` (the response stays a list).
- The Players tab shows "Seasons played since Season 4 (earlier seasons have no OpenDota record)" under the table, and the Seasons count's hover text ends with "Counted from Season 4". Both are built from `seasons_counted_from`; the frontend has no literal season number.
- The Players list still shows the current pool only. Players from old seasons who aren't in the pool appear in History and the Hall of fame.

No migration, no new table, no environment variable. Tests: `backend/tests/test_issue_212_season_participation_backfill.py`.
