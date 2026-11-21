# Plan: A Clean Slate Between Seasons That Keeps the History

## Context
Issue #133: "Season archiving does not clean the slate." After archiving season 15 in test, the weeks, user tokens, players' active cards and matches were all still there. The owner's comment (2026-11-17): "Plan and consider how to effectively clean the slate for next season, while still retaining data that is valuable to have over seasons, like history."

**What happens today** (`backend/routers/admin_season.py`, [Season Lifecycle](../features/reference/season-lifecycle.md)):
- Ending a season takes two separate admin actions. **End Season** (`POST /admin/season/end`) archives the standings and records accolades; it deletes nothing. **Reset Season** (`POST /admin/season/reset`) is the clean slate: it takes a backup, then deletes matches, stats, stored card points, bans, weeks, rosters, Twitch MVPs and drops, players, teams, cards, modifiers and own-card grants, resets tokens and unmonitors leagues. It has existed since August 2026, so the four items in the issue are what End Season alone leaves behind; nothing in the admin panel says a second step is needed.
- Reset predates several later features and misses their season data. The Weekly Report's per-week rows (`weekly_summaries`, `weekly_summary_reveals`, `weekly_summary_seen`) stay, and new weeks reuse the old week ids (SQLite reuses ids once the table is empty), so next season's Week 1 can show as already revealed or summarised. `live_matches` and `match_timings` keep rows for deleted matches. The in-memory caches (schedule, Twitch panel, per-game player tables, accolades) can serve last season's data for up to an hour. A demo clock left on carries over.
- What survives today: users, tags, the audit log, `season_archive` (each user's final points and rank) and `season_accolades` (champions, awards, Played). What is lost for good: every match, every player's per-game stats, and the team results. The pre-reset backup holds them, but it sits with the daily backups and is deleted after 14 days (`cleanup_old_backups`).

**Decisions** (change them in review if needed):
- **Keep the clean slate, keep a summary.** Past matches are not kept in the live tables: every page treats the database as the current season (there is no season column), and scoping every query by season would be a large refactor for data that is rarely looked at. Instead, End Season stores a **season summary** of what is worth keeping, and the raw data is kept in a **permanent season backup** file.
- **The summary, per season:** one row per player (name, team, games, wins, raw-point total and average, best game with its points and match id, kills, deaths and assists, MVPs) and one row per team (name, division, series won and lost, games won and lost). It is written in the same transaction as the archive and accolades, so a season is either fully archived or not at all.
- **Showing it is a follow-up.** This issue stores the summary so season 16 isn't lost; History and the player and team popups can read it later. A follow-up issue is listed under Verification.
- **End Season's parts are optional** (added after review, 2026-11-17). Season 16's champions and awards were granted by hand, and End Season would record them again: the unique key stops exact copies, but a hand-entered row that differs slightly (a label spelled "S16" against "Season 16", a tie entered once, a champion squad with other players) is not caught, so near-duplicates appear. End Season therefore lets the admin choose each part (awards, champions, Played, summary); the archive of the standings is always recorded. Season 16's existing duplicates are removed by hand in Admin › Player management; no clean-up tool is part of this issue.
- **One guided flow.** End Season's result offers **Continue to Reset Season**, and Reset shows a preview of exactly what it deletes and keeps (counts) before the typed confirmation, so an admin can't believe the slate is clean after step one.
- **Reset clears every season table**, including the ones added since August, and clears the caches. Twitch vote polls and pending vote tokens are kept: a pending token is a viewer's claim that runs for 60 days across the season boundary. Player profiles (`player_profiles`, keyed by OpenDota account id) are kept, because players return next season.

Resolves GitHub issue #133.

## User Stories

### Reset Leaves Nothing of the Old Season Behind
**User story**
As the league admin, I want Reset Season to clear everything that belongs to the season, so that next season starts clean without leftovers that confuse players.

**Acceptance criteria**
- **Already cleared, unchanged:** matches, per-game stats, stored card points, bans, weeks, weekly rosters, Twitch MVPs and token drops, players, teams, cards, card modifiers, own-card grants; tokens reset to `INITIAL_TOKENS`; leagues unmonitored.
- **Also cleared:** `weekly_summaries`, `weekly_summary_reveals`, `weekly_summary_seen`, `live_matches`, `match_timings`, and the demo clock override.
- **Week ids:** after a reset, a new Week 1 shows no Weekly Report as revealed or seen, even when it gets the id an old week had (a test creates a week after reset with the old id and checks).
- **Caches:** the reset clears the schedule cache, the Twitch panel cache, the per-game player cache and any other in-memory season cache, so the first request after it shows the empty season.
- **Kept, unchanged:** users, tags and user tags, audit logs, `season_archive`, `season_accolades`, finals tables, team signups, promo codes, token grant events, notifications, weights, player profiles, Twitch vote polls and pending vote tokens.
- The response's `counts` lists every cleared table, and `kept` lists the kept ones with their row counts.

### Season Stats Survive the Reset
**User story**
As a player, I want each season's player and team results kept after the reset, so that the league's history isn't wiped every season.

**Acceptance criteria**
- **End Season** stores, for the season label, one `season_player_stats` row per player with a scored match (player id, name, team name, games, wins, raw-point total and average, best game's raw points and match id, kills, deaths, assists, MVPs) and one `season_team_results` row per team (team id, name, division, series won and lost, games won and lost), in the same transaction as the archive and accolades; a failure stores nothing.
- Raw points follow the stored stats and the weights in force at End Season (`scoring.fantasy_score`, issue #244's definition); a game excluded from scoring is left out.
- Ending a season twice with the same label is refused as today (409), and a re-run never duplicates summary rows.
- **A season ended before this change:** an admin can store the summary for an already-archived label once, before Reset, from the same live data (`POST /admin/season/summary` with the label; 409 if that label already has a summary; refused once the season's matches are gone).
- Reset never deletes `season_player_stats` or `season_team_results`.

### Choose What End Season Records
**User story**
As the league admin, I want to choose which parts End Season applies, so that it doesn't record champions or awards again when I've already granted them by hand.

**Acceptance criteria**
- **Parts:** the End Season dialog lists each part with a checkbox: **Archive standings** (always on: the season's archive is what Reset checks for), **Record awards** (Most Points, Best Average, Best Single Match, Most MVPs, Fantasy Winner and its tag), **Record champions**, **Record Played** and **Store season summary**.
- **Already recorded:** for the typed label, each accolade part shows how many rows already exist ("5 awards already recorded for Season 16") and starts unticked when there are any; the other parts start ticked.
- **Applied as chosen:** `POST /admin/season/end` takes `record_awards`, `record_champions`, `record_played` and `store_summary` (all default true, so an existing call behaves as today) and skips each part that is false; the response and the audit detail say which parts ran.
- **Champions:** with Record champions off, the dialog hides the champion pickers and sends none.
- Rows entered by hand are never changed or deleted by End Season, as today.

### The Raw Season Data Is Kept as a File
**User story**
As the league admin, I want the backup taken before a reset kept for good, so that every match of a past season can be restored or studied later.

**Acceptance criteria**
- Reset's pre-reset backup is named after the season (`fantasy.db.season-<label>-<timestamp>`) and is never deleted by the daily backup cleanup.
- Admin › Settings › Database Backups lists season backups apart from the daily ones, with the same Download button.
- If the season backup can't be taken, the reset aborts with no deletes, as today.

### One Guided End-of-Season Flow
**User story**
As the league admin, I want ending a season to lead me through both steps and show what will happen, so that I never think the slate is clean when it isn't.

**Acceptance criteria**
- After a successful End Season, the dialog's result says "Season <label> archived. The season's data is still live: continue to Reset Season to start the next season." with a **Continue to Reset Season** button.
- **Reset preview:** before the typed confirmation, the Reset dialog shows two lists from `GET /admin/season/reset-preview`: what will be deleted, with row counts (matches, weeks, cards, players…, and "N users' tokens reset to 5"), and what is kept (users, history, accolades, season summary, the season backup…).
- The preview warns, and Reset still refuses with 409, when locked weeks exist with no archive after them (End Season not run).
- After the reset, the result lists the deleted counts and the season backup's file name.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New tables `season_player_stats` and `season_team_results` (created by `create_all`; no migration) |
| `backend/season_summary.py` (new) | Build and store a season's player and team summary from live data |
| `backend/routers/admin_season.py`, `backend/accolades.py` | End Season's optional parts (`record_awards`, `record_champions`, `record_played`, `store_summary`) and a count of accolades already recorded for a label; End Season stores the summary; `POST /admin/season/summary`; `GET /admin/season/reset-preview`; Reset clears the extra tables and caches and names its backup |
| `backend/database.py` | Season backup naming; `cleanup_old_backups` and the backup list leave season backups out of the rotation |
| `backend/routers/admin_backups.py` | List season backups apart |
| `frontend/app-admin-season.js`, `frontend/app-admin-backups.js`, `frontend/index.html` | Continue to Reset, the preview lists, the result, season backups |
| `backend/tests/test_issue_133_season_reset_clean_slate.py` | Tests |
| `markdown/features/reference/season-lifecycle.md`, `markdown/features/reference/admin-db-backup.md`, `markdown/ui_description/admin.md` | Docs |

Check the line cap on `routers/admin_season.py` (test_issue_85 caps admin routers at 350 lines) before adding routes; keep handling in `season_summary.py` and a small reset helper.

### Step 1 — The full reset list
List every table in `models.py` and decide cleared or kept, as in the first story; put the lists in one place (a module constant) so a test can check that every table is in exactly one of them, and a new table added later fails that test until someone decides. Clear the caches through their existing functions (`schedule.bust_cache`, `twitch.bust_panel_cache`, the accolades and finals caches; grep for module-level caches). Confirm week id reuse with a test before relying on it.

### Step 2 — Season summary
In `season_summary.py`, build the player rows from `player_match_stats` joined to `matches` (scored matches only, `scored_match_sql`), with raw points from `stat_dict_from_row` and the current weights, and the team rows from the series results the schedule and team popup already compute (reuse `team_insights` or `schedule.resolve_series_result`; check which gives division and series counts). Call it from `end_season` before the commit. Add `POST /admin/season/summary` (admin, recent re-auth, typed confirmation like End Season) for a label that is archived but has no summary.

### Step 2b — Optional End Season parts
Add the four booleans to `SeasonEndBody` (default true). Split `accolades.record_season` so awards (with the fantasy winner tag), champions and Played can run separately, keeping `insert_ignore`. Add the per-label counts of existing accolades by kind to the data the dialog already loads (`GET /admin/season/accolades-preview` takes the label, or a small sibling route); the dialog unticks a part that already has rows. Check the End Season tests (issue 50, 212, 233, 248) for pinned body shapes and dialog text.

### Step 3 — Season backup
`backup_sqlite_db(kind="season", label=...)` writes `fantasy.db.season-<safe label>-<timestamp>`; the label is reduced to `[A-Za-z0-9-]`. `cleanup_old_backups` and the daily list match only `.backup-*`, so season files are never pruned; a second list returns season files for the admin panel. Download keeps its existing checks (typed confirmation, re-auth), extended to season file names.

### Step 4 — Guided flow
`GET /admin/season/reset-preview` returns the counts Reset would delete and keep, without changing anything. The End Season result and the Reset dialog in `app-admin-season.js` use it. Grep `backend/tests` for tests that pin the End Season and Reset dialogs and the backup panel before editing.

### Step 5 — Tests
- Every table is in exactly one of the cleared and kept lists.
- End Season with each part switched off records nothing of that part and still archives the standings; with no flags it behaves as today; the preview reports existing accolade counts per kind for a label.
- Reset clears the new tables and the caches; a week created after reset with a reused id has no revealed or seen Weekly Report; kept tables keep their rows.
- End Season stores player and team summaries matching the live data (games, wins, raw points, best game, MVPs; excluded games left out); a failure stores nothing; the summary endpoint refuses duplicates and empty data.
- Season backup: named after the label, never removed by `cleanup_old_backups`, listed apart, downloadable with the same checks.
- Preview: counts match what Reset then deletes; nothing changes on preview.

## Settled during implementation (2026-11-18)
Where these differ from the text above, these hold:
- **Caches:** `schedule.bust_cache()`, `twitch.bust_panel_cache()`, `finals.clear_caches()`, `team_insights.clear_league_cache()`, `player_insights.clear_league_cache()`, called after the commit. There is no accolades cache.
- **Table groups** live in `season_reset.TABLE_GROUPS`: cleared (the list in the first story plus `twitch_presence`), updated (users: tokens; leagues: unmonitored; demo_clock: override cleared) and kept (everything else, including `twitch_mvp_votes`, `code_redemptions`, `token_grant_claims`, `notification_dismissals`, the sign-in and session tables, `toornament_sync_log` and `scoring_state`). The raw `schema_migrations` table is outside the lists.
- **Backup:** Reset still calls `backup_sqlite_db()` with no arguments, then renames the file to `fantasy.db.season-<label>-<timestamp>`; the label is Reset's optional `season_label`, else the newest archived label, else "unarchived". `backup_sqlite_db(kind="season", label=…)` also exists.
- **Team results** come from stored matches only (series clustered by `schedule.SERIES_GAP_SECONDS`, with `series_drawn`); the division comes from the schedule cache only when it is already cached, else null. The team popup's feed-based series counts are not used, so End Season never reaches the network.
- **Player summary:** raw points without the MVP bonus, exact sums; team = the team of most games. The best game can differ from the Best Single Match award.
- **Flow:** End Season's result is its own small modal with **Continue to Reset Season** and **Later**; the Reset dialog shows the preview lists before the typed confirmation. The summary route uses a new typed phrase, SAVE SUMMARY (`season_summary`), and answers 404 for an unarchived label.
- `accolades.record_season` is split into `record_awards`, `record_champions` and `record_played`, with `record_season(..., awards=, champions_on=, played=)` kept as the wrapper End Season calls.

## Verification
- Run `bash scripts/backup-db.sh` before deploying (new tables are created on start; no migration).
- On a copy of a production backup: End Season with a test label, check the summary rows (a top player's games and points against the leaderboard), preview, Reset, then confirm every season page is empty, tokens are reset, a new week shows no old Weekly Report state, and the season backup file exists and is kept by the cleanup.
- For season 16, if End Season already ran in production: store its summary with `POST /admin/season/summary` **before** running Reset.
- Follow-up issue to open: show the season summaries in History and in the player and team popups.
