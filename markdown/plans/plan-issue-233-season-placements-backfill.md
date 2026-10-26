# Plan: Season Placements Backfill

## Context
#212 backfilled who *played* in each past Kanaliiga season (S4–S15) from OpenDota. Past seasons still have no results: champions exist only for seasons an admin recorded by hand. Issue #233 asks for:
- the placements 1–3 of every past season;
- each placed team's players from that season;
- a table an admin can use to backfill those results into Kana Cards.

**What exists:**
- **Champions:** `season_accolades` rows of kind `champion`, with `division` (`div1`/`div2`) and `team_name`, one row per player. They are written by End Season, `PUT /admin/season-champions` and `POST /admin/season-accolades` (`accolades.set_champions`). A champion makes the player's Legendary cards drawable as Holo in later seasons (#53).
- **No 2nd or 3rd place:** no accolade kind exists for them.
- **League list:** `backend/scripts/kanaliiga_leagues.json` (#212) maps S4–S16 to their OpenDota league ids. Seasons 1–3 have no league. S10 and S13 Div 2 leagues have no matches.
- **`backend/scripts/backfill_played.py`:** the patterns to reuse are the league file, a JSON cache, a call budget, pauses, a dry run and an audit per season. Its cache keeps only account ids and names per match, so it can't be reused for teams or series.

**Spike (2026-10-26, Season 15, 28 OpenDota calls):**
- **Bulk endpoint unusable:** `/leagues/{id}/matches` and `/leagues/{id}/teams` return `[]` for these "excluded"-tier leagues.
- **Per-match data works:** `/leagues/{id}/matchIds`, then `/matches/{id}` for each match. Each match carries `series_id`, `series_type`, `radiant_name` / `dire_name`, the team ids, `radiant_win`, `start_time` and the players with their side.
- **S15 Div 1 (19368):** the final day had two semifinals, a single game between the semifinal losers, and the final:
  - OP Platinum beat Elisa Oyj 2–0;
  - Visma Tormentor beat Reaktor 2–0;
  - Elisa Oyj beat Reaktor;
  - OP Platinum beat Visma Tormentor 2–1.
  - **Result:** 1 OP Platinum, 2 Visma Tormentor, 3 Elisa Oyj.
- **S15 Div 2 (19369):**
  - final: PV-1 beat Gofore/Loihde 2–1, so 1 PV-1, 2 Gofore/Loihde;
  - 3rd is not obvious: Gofore/Loihde beat Visma Wisdom 2–0 in the series before the final, but PV-1 also beat OP Gold earlier. This is a double-elimination shape the rules can't settle with certainty.
- **Conclusion:** the final is reliable from the data, and 3rd place sometimes needs a person. So the table must carry its evidence and a confidence flag, and nothing is written until a person has reviewed it.

**Decisions** (change them in review if needed):
- **Two steps, a reviewed table in between:**
  1. `backend/scripts/season_placements.py build` fetches and derives, and writes the table `backend/scripts/season_placements.csv`.
  2. The operator or an admin checks and corrects the table, which is committed to the repo like `kanaliiga_leagues.json`.
  3. `season_placements.py apply` writes the reviewed table into the database.
- **Placement rules** (per league, matches grouped by `series_id`; old matches without one are grouped by team pair and day):
  - **1st and 2nd:** the winner and loser of the last series of the league.
  - **3rd, high confidence:** if a series between the two semifinal losers follows the semifinals, its winner.
  - **3rd, low confidence:** otherwise, the loser of the last series before the final that involved the final's loser, as in a double-elimination lower-bracket final.
  - **Needs review:** a final that isn't a best-of-two-or-more, a season with no clear final day, or missing team names.
- **Roster:** the players with at least one match for that team in that season's league, matched by the team id on their side (or the team name when the id is missing). Each player gets their number of matches for the team, so substitutes are visible. Names come from the current player pool, else the match's personaname.
- **Table columns:** `season`, `division`, `place`, `team_name`, `team_id`, `players` (`account_id:name;…`), `matches_per_player`, `evidence` (series scores, e.g. "final OP Platinum 2–1 Visma Tormentor"), `confidence` (`high`/`low`/`review`), `reviewed` (blank until a person sets `yes`). `apply` refuses rows not marked `reviewed=yes`.
- **Divisions:**
  - S4–S9 have one league each, recorded as `div1`.
  - S10 and S13 have no Div 2 data.
  - From S11 on, the "Lower" league is `div2`.
- **2nd and 3rd place become accolades** (confirmed by the product owner, 2026-10-26): two new kinds, `runner_up` and `third_place`, per division with the team name, like `champion`:
  - named "Div 1 Runner-up" and "Div 1 Third place";
  - Lucide `medal` and `award` icons, with their own colour tokens;
  - shown wherever accolades are listed (player popup timeline, chips, pips, Hall of fame);
  - **no Holo:** only champions unlock Holo (confirmed: Holo is for winners only).
- **Champions follow the existing rules** (confirmed): place 1 is written through `accolades.set_champions`. That makes the backfilled champions' Legendary cards drawable as Holo in later seasons, as #53 intends for past champions.
- **Existing rows win:** a place (season, division, kind) whose recorded rows differ from the table (champions entered by hand, say) is skipped unless `--replace` is given; a place recorded exactly as in the table counts as already applied. `build` reports where the derived champion differs from the recorded one.
- **Safety:**
  - `apply` needs a backup first (`scripts/backup-db.sh`) and supports `--dry-run`;
  - a rerun changes nothing (insert-ignore, as in #212);
  - each season writes an audit entry, `admin_placements_backfilled`, with the season, places and player counts.
- **Budget:** `build` reads every match of every league, about 1,180 OpenDota calls cold (the #212 figure). It uses a JSON cache, `--max-calls` (default 900) and exits with code 2 to resume, like `backfill_played.py`.

Resolves GitHub issue #233.

## User Stories

### Build the Placements Table From OpenDota
**User story**
As the operator, I want a script that works out each past season's top three teams and their players from OpenDota, so that the results can be checked before anything is written.

**Acceptance criteria**
- **Command:** `python scripts/season_placements.py build` reads `kanaliiga_leagues.json` (every season except the live one) and writes `scripts/season_placements.csv` with one row per season, division and place (1–3).
- **Placements:** 1st and 2nd are the winner and loser of the league's last series. 3rd follows the rules in this plan, and each row records its `evidence` (the series scores used) and its `confidence` (`high`, `low`, `review`).
- **Rosters:** each row lists the players who played at least one match for that team in that league, with their match counts. Names come from the player pool, else the match's personaname.
- **Gaps:** leagues with no matches (S10 and S13 Div 2) and seasons without a clear final are listed with `confidence=review` and no guessed placement.
- **Budget:** `--max-calls` (default 900) stops cleanly with exit code 2 and keeps the cache; a rerun spends no calls on cached matches.
- **Comparison:** `build` prints where a derived champion differs from champions already recorded for that season and division.
- **Read-only:** `build` writes nothing to the database.

### Apply the Reviewed Table
**User story**
As the operator, I want to write the reviewed placements into Kana Cards in one command, so that past champions, runners-up and third places show up as accolades.

**Acceptance criteria**
- **Command:** `python scripts/season_placements.py apply [--dry-run] [--replace]` reads the table and writes only rows with `reviewed=yes`; other rows are listed as skipped.
- **Place 1:** written as `champion` accolades through `accolades.set_champions` (season label "Season N", division, team name, players).
- **Places 2 and 3:** written as `runner_up` and `third_place` accolades with division and team name, one row per player.
- **Existing champions:** a season and division with champions already recorded is skipped, with a message, unless `--replace` is given.
- **Idempotent:** a second run adds nothing. Each season writes one `admin_placements_backfilled` audit entry.
- **Dry run:** `--dry-run` prints what would be written and writes nothing.

### Runner-up and Third Place Accolades
**User story**
As a visitor, I want to see when a player finished second or third in a season, so that a strong player's history isn't reduced to titles alone.

**Acceptance criteria**
- **Kinds:** `runner_up` and `third_place` exist in `accolades.KINDS`, in `ACCOLADE_KINDS` (backend and frontend, kept in step by the existing test) and in the admin `AccoladeIn` model. Like `champion`, they need a division and a team name.
- **Display:**
  - the player popup timeline lists "S15 Div 1 Runner-up · with Visma Tormentor" and "S15 Div 1 Third place · with Elisa Oyj";
  - chips, pips and the Hall of fame show them with their own symbol and colour token;
  - text always names the place, so meaning never depends on colour.
- **No Holo:** neither kind unlocks Holo (`holo_eligible` counts only `champion`).
- **Admin:** Player management can add, edit and delete them like other accolades.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/scripts/season_placements.py` (new) | `build`: fetch with cache and budget, derive series and placements, rosters, write the CSV and print comparisons. `apply`: read the reviewed rows and write accolades with an audit. Reuses the league file and the OpenDota client |
| `backend/scripts/season_placements.csv` (new, generated, then reviewed) | The table |
| `backend/accolades.py` | `runner_up` and `third_place` in `KINDS` and `ACCOLADE_KINDS`; a `set_placement(db, label, division, kind, team_name, players)` helper beside `set_champions`; `holo_eligible` unchanged (champion only) |
| `backend/routers/admin_accolades.py` | `AccoladeIn` accepts the new kinds, with a division and team name required as for `champion` |
| `frontend/app-globals.js` | `ACCOLADE_KINDS` gains the two kinds; detail-line and chip text "Div N Runner-up · with Team" |
| `frontend/colors_and_type.css`, `design/colors_and_type.css` | `--accolade-runner-up`, `--accolade-third` tokens (both files identical) |
| `frontend/style.css` | Pip and chip plate styles for the new kinds; tokens only, before GUIDED TOUR |
| `.claude/skills/README.md` | Accolade symbol table rows |
| `markdown/features/reference/season-placements-backfill.md` (new), `season-winners-and-holo-cards.md`, `season-participation-backfill.md` | Docs, including the run book and the placement rules |
| `backend/tests/test_issue_233_season_placements_backfill.py` | Tests |

No migration: `season_accolades.kind` is a free string, and the unique index already covers kind and division. No new env var.

### Step 1 — Fetch and derive (`build`)
Fetch `matchIds` per league, then each match, into a cache (`season_placements_cache.json`). Each match is slimmed to its series id and type, start time, team ids and names per side, the winner, and the players' account ids, names and sides. Group the matches into series and apply the placement rules. Build the rosters and write the CSV. Print a summary per season and the champion comparisons.

### Step 2 — Review
The operator reads the CSV against the evidence, fixes rows (most likely 3rd place in double-elimination seasons) and sets `reviewed=yes`, then commits the file.

### Step 3 — New accolade kinds
Add the kinds, the tokens, the symbols, the display text and the admin model.

### Step 4 — Apply
`apply` writes champions through `set_champions`, and places 2 and 3 through `set_placement`, with the `--replace` and dry-run rules and an audit per season.

### Step 5 — Docs and tests
**Tests**, all with OpenDota mocked:
- series grouping with and without `series_id`;
- the final and the 3rd-place rules, including a 3rd-place match, a double-elimination shape and an unclear season → `review`;
- rosters and match counts, team matching by id and by name;
- CSV columns;
- the budget stop and resume;
- `build` writes nothing to the database;
- `apply` writes only reviewed rows, skips existing champions without `--replace`, is idempotent, audits, and does nothing on a dry run;
- the new kinds in `ACCOLADE_KINDS` on both ends, admin validation, no Holo from the new kinds;
- display text and the tokens in both colour files.

## Verification
- **S15 check:** `build --dry-run` on S15 reproduces the spike: Div 1 OP Platinum, Visma Tormentor, Elisa Oyj (`high`), and Div 2 PV-1, Gofore/Loihde, with 3rd flagged `low`.
- **Full build:** S4–S15 complete within two budgeted runs. The summary lists the `review` rows, and the champion comparison is checked against seasons recorded by hand.
- **Apply on a copy of production:** after review, `apply --dry-run`, then `apply`. Afterwards a past champion shows "S12 Div 1 Champion · with …" and a runner-up shows "Runner-up" in the player popup. Their Legendary cards can roll Holo in the current season. A rerun adds nothing.
- **Deploy:** `bash scripts/backup-db.sh` before `apply` on production.
