# Season Placements Backfill

Works out the top three teams of every past Kanaliiga season (S4–S15) and their players from OpenDota, so an operator can review them in a table and then record them in Kana Cards as champion, runner-up and third-place accolades. Plan: `markdown/plans/plan-issue-233-season-placements-backfill.md` (issue #233).

---

## Flow

1. **Build:** `python scripts/season_placements.py build` (from `backend/`) reads `scripts/kanaliiga_leagues.json`, fetches each league's matches from OpenDota (cached, with a call budget), groups them into series, derives places 1–3 and their rosters, and writes `scripts/season_placements.csv`. It reads the database (player names, the live season, recorded champions) but never writes to it.
2. **Review:** the operator checks each row against its `evidence` and `confidence`, fixes it (most often 3rd place in double-elimination seasons, or the `review` rows), sets `reviewed=yes`, and commits the CSV, like `kanaliiga_leagues.json`.
3. **Apply:** `bash scripts/backup-db.sh`, then `python scripts/season_placements.py apply --dry-run`, then `apply`. Only rows with `reviewed=yes` are written.

## Run book

From `backend/` on a machine with OpenDota access (build) and on the server (apply):

1. `python scripts/season_placements.py build --season 15 --dry-run`: prints the S15 table without writing it. It should match the spike: Div 1 OP Platinum, Visma Tormentor, Elisa Oyj (all `high`); Div 2 PV-1, Gofore/Loihde, with 3rd flagged `low`.
2. `python scripts/season_placements.py build`. After a budget stop (exit 2, "Budget used: resume to continue from Season N"), run it again until it exits 0; the cache (`season_placements_cache.json` in the working directory, git-ignored) makes each rerun skip what it already read. About 1,180 calls cold, so two runs at the default budget.
3. Read the summary: one line per season and division (`Season 15 div1: 8 matches; 1 OP Platinum (high), 2 Visma Tormentor (high), 3 Elisa Oyj (high)`), the divisions to review, and any line `derived champion X differs from the recorded champion Y` (check those against the seasons recorded by hand).
4. Review `scripts/season_placements.csv`: fill or correct `team_name`, `team_id`, `players` (`account_id:name;…`) where needed, set `reviewed=yes` on every row to write, and commit the file.
5. On the server: `bash scripts/backup-db.sh` (from the repo root), then `python scripts/season_placements.py apply --dry-run`. Check the "Would write …", "skipped …" and "Rejected …" lines.
6. `python scripts/season_placements.py apply` (add `--replace` only to overwrite places recorded differently by hand). A second run should print "already recorded" for every place and add nothing.
7. Spot-check: a past champion's popup shows "S12 Div 1 Champion · with …", a runner-up's shows "S12 Div 1 Runner-up · with …", and the champion's Legendary cards can roll Holo in the current season.

## Placement rules

Per league; matches are grouped into series by `series_id` (old matches without one by unordered team pair and UTC day), and series are ordered by their last game.

- **Teams:** identified by OpenDota team id; a side without an id counts as the team whose name matches, else as a team of its own name.
- **1st and 2nd:** the winner and loser of the last series, with evidence `final OP Platinum 2–1 Visma Tormentor`, confidence `high`.
- **3rd, `high`:** each finalist's last series before the final is its semifinal (both won by the finalists); a later series between the two semifinal losers gives 3rd to its winner. Evidence lists both semifinals, the 3rd-place match and the final.
- **3rd, `low`:** otherwise, the loser of the final loser's last series before the final, when the final loser won it (a double-elimination lower-bracket final). Evidence names that series.
- **`review`, no guess:** a last series of a single game (or `series_type` 0), a tied final, missing team names in the final, no won series before the final for its loser (3rd only), a league with no matches (listed under `empty_leagues`, like S10 and S13 Div 2, or returning none), or a league with unreadable matches (run build again).
- **Divisions:** the first league of a season is `div1`; the second, under `leagues` or `empty_leagues`, is `div2` (the "Lower" league from S10 on). S4–S9 have one league each.
- **Rosters:** every account with at least one match on the team's side in that league, with its match count, most matches first, so substitutes show (`matches_per_player`, `account_id:count;…`). Names come from the player pool, else the match's personaname, else "Player <id>"; anonymous slots are left out.

## Table

`backend/scripts/season_placements.csv`, one row per season, division and place:

| Column | Content |
|---|---|
| `season` | Season number |
| `division` | `div1` or `div2` |
| `place` | 1, 2 or 3 |
| `team_name`, `team_id` | Blank on `review` rows |
| `players` | `account_id:name;…` (`;` in a name is written as `,`) |
| `matches_per_player` | `account_id:count;…` |
| `evidence` | The series scores used, or why the row needs review |
| `confidence` | `high`, `low` or `review` |
| `reviewed` | Blank from build; `yes` to apply |

`build` refuses to overwrite a table that already has reviewed rows unless `--overwrite` is given.

## Apply

- **Place 1:** `champion` rows through `accolades.set_champions` (label "Season N", division, team, players). Backfilled champions make their Legendary cards drawable as Holo in later seasons, as #53 intends.
- **Places 2 and 3:** `runner_up` and `third_place` rows through `accolades.set_placement`, which works like `set_champions` for those kinds. They never unlock Holo.
- **Existing rows:** a place whose recorded rows differ from the table (champions entered by hand, say) is skipped with a message unless `--replace` is given; a place recorded exactly as in the table prints "already recorded".
- **Rejected rows:** a reviewed row with an invalid season, division or place, an empty team name, or a `players` field that isn't `id:name;…` is reported and not written (exit 1; the valid rows are still written).
- **Audit:** one `admin_placements_backfilled` entry per season that changed, actor "script": `season_label=Season 15 places=div1:1,2,3;div2:1,2,3 players=div1:1=5;… added=N removed=N source=backfill`. A rerun that changes nothing writes no entry. The accolade rows themselves are stored with `source = "admin"` (as `backfill_played.py` does), so Player management's Source column shows "admin" for them; the audit entry tells backfilled rows apart.
- **Dry run:** `--dry-run` prints "Would write Season 15 Div 1 Runner-up Visma Tormentor (5 players)" lines and writes nothing.

## Script options

- `build [--season N …] [--dry-run] [--overwrite] [--table PATH] [--cache PATH] [--pause S] [--max-calls N]`. `--max-calls` (default 900, at least 1) caps OpenDota calls per run (match-id lists and matches; cache hits and the client's retries don't count). Exit 0 done, 1 invalid league file or a reviewed table in the way, 2 budget stop.
- `apply [--table PATH] [--dry-run] [--replace]`. Exit 0 done, 1 unreadable table or rejected rows.
- Reuses `backfill_played.py`'s league-file validation, call budget, pauses and cache writing. Like that script, it holds no league ids.

## Accolade kinds

`runner_up` and `third_place` are accolade kinds like `champion`: one per division (`div1_runner_up`, `div2_runner_up`, `div1_third`, `div2_third` in `ACCOLADE_KINDS`), named "Div 1 Runner-up" and "Div 1 Third place", Lucide `medal` and `award` on an outlined plate, colour tokens `--accolade-runner-up` (silver) and `--accolade-third` (bronze). See [season-winners-and-holo-cards.md](season-winners-and-holo-cards.md) for where they show.

There is no migration (`season_accolades.kind` is free text and the unique key already covers kind and division) and no env var. Tests: `backend/tests/test_issue_233_season_placements_backfill.py`.

## Safety notes

- **Spreadsheets:** cells starting with `=`, `+`, `-` or `@` are written with a leading `'`, so a team or player name can't run as a formula when the table is opened in a spreadsheet. `apply` drops the `'` again.
- **Size:** a row may name at most 50 players (the same cap as `PUT /admin/season-champions`); larger rows are rejected.
- **Terminal:** names from OpenDota, the player pool, recorded champions and the table are printed only after control characters are stripped.
