# Season Reset Clean Slate

Ending a season leaves nothing of it in the live tables while keeping what matters across seasons: a stored summary of each player's and team's season, and a permanent backup file of the raw data. For the league admin running End Season and Reset Season. Issue #133. Plan: `markdown/plans/plan-issue-133-season-reset-clean-slate.md`. The rest of the flow is in [Season Lifecycle](season-lifecycle.md).

Code: `backend/season_reset.py` (table groups, preview, clear, caches), `backend/season_summary.py` (the summary), `backend/routers/admin_season.py` (routes), `backend/database.py` (season backups), `frontend/app-admin-season.js`.

---

## Reset clears every season table

`season_reset.TABLE_GROUPS` puts every model table in exactly one group; `test_issue_133` fails when a new table is in none, so whoever adds a table decides what Reset does with it. The raw `schema_migrations` table has no model and is outside the lists.

| Group | Tables |
|---|---|
| Cleared (deleted) | `matches`, `player_match_stats`, `card_match_points`, `match_bans`, `weeks`, `weekly_roster_entries`, `twitch_mvp`, `twitch_token_drops`, `players`, `teams`, `cards`, `card_modifiers`, `own_player_card_grants`, `weekly_summaries`, `weekly_summary_reveals`, `weekly_summary_seen`, `live_matches`, `match_timings`, `twitch_presence`; since #257 also `finals_predictions`, `finals_brackets`, `code_redemptions`, `promo_codes`, `token_grant_claims`, `token_grant_events`, `notification_dismissals`, `notifications` (children before parents) |
| Updated | `users` (tokens reset to `INITIAL_TOKENS`), `leagues` (unmonitored), `demo_clock` (override cleared, row kept) |
| Kept | `season_archive`, `season_accolades`, `season_player_stats`, `season_team_results`, tags and user tags, `audit_logs`, team signup tables, `weights`, `player_profiles`, Twitch vote polls, votes and pending vote tokens, the sign-in and session tables, Twitch link and merge records, channel approvals, `toornament_sync_log`, `scoring_state` |

Why the Weekly Report tables matter: SQLite reuses week ids once `weeks` is empty, so a stale `weekly_summaries` row would show next season's Week 1 as already revealed.

After the commit, Reset empties the in-memory season caches: `schedule.bust_cache()` (schedule and per-game players), `twitch.bust_panel_cache()`, `finals.clear_caches()`, `team_insights.clear_league_cache()` and `player_insights.clear_league_cache()`.

The response: `counts` (every cleared table, plus `users_tokens_reset`, `leagues_unmonitored`, `demo_clock_override`), `kept` (every kept table's row count), `season_label`, `backup_path` and `backup_file`. The audit detail keeps `kept_season_accolades=N`.

## Season summary

End Season stores, in the same transaction as the archive and accolades:

- **`season_player_stats`**, one row per player with a scored match (`scored_stat_sql`, as the awards): `player_name`, `team_name` (the team of most of their games, ties by name), `games`, `wins`, `raw_points_total`, `raw_points_avg`, `best_raw_points`, `best_match_id`, `kills`, `deaths`, `assists`, `mvps`. Raw points are `scoring.fantasy_score(stat_dict_from_row(row), weights)` with the weights in force at End Season: no MVP bonus, no rarity or modifiers (issue #244's definition). Values are exact sums; round with `display_points` when showing them. **The best game can differ from the Best Single Match award**, which uses stored `fantasy_points` including the MVP bonus.
- **`season_team_results`**, one row per team in a scored match with both sides known: `team_name`, `division`, `series_won`, `series_lost`, `series_drawn`, `games_won`, `games_lost`. Computed from stored matches only: each team pair's games are clustered into series by `schedule.SERIES_GAP_SECONDS` (6 hours), a series with equal wins is a draw. `division` comes from the schedule cache only when it is already cached (`schedule.cached_team_divisions()`, never a fetch), otherwise null.

Unique keys: `(season_label, player_id)` and `(season_label, team_id)`. Both tables come from `create_all` (no migration). If storing the summary fails, End Season rolls back and answers 500 "Storing the season summary failed; nothing was archived". Reset never deletes them. Showing them in History and the popups is a follow-up.

## Choosing End Season's parts

`POST /admin/season/end` takes `record_awards`, `record_champions`, `record_played` and `store_summary` (booleans, default true; anything else is 422). Archiving the standings always runs. The response adds `parts` (`{"archive", "awards", "champions", "played", "summary"}` as applied) and `summary` (`{"players", "teams"}` or null); the audit detail adds `parts=…` and `summary_players=N summary_teams=M`. With `record_champions` false, any champions sent are ignored and no champions warning is returned.

In code, `accolades.record_season(db, label, champions, actor_id, *, awards=True, champions_on=True, played=True)` calls `record_awards` (the four awards, the fantasy winner rows and the `season_winner` tag), `record_champions` and `record_played`. All use `insert_ignore`, so hand-entered rows are never changed.

The End Season dialog shows a checkbox per part. `GET /admin/season/accolades-preview?season_label=…` returns `recorded` (`awards` including fantasy_winner, `champion`, `played`, `by_kind`) for the label; a part with rows already starts unticked ("5 awards already recorded for Season 16"). The dialog refetches the counts 400 ms after the label stops changing. Unticking Record champions hides the pickers.

## Season backup

Reset still calls `backup_sqlite_db()` (no arguments), then `database.rename_to_season_backup(path, label)` renames the file to `fantasy.db.season-<label>-<timestamp>`; a path that is not an existing file (a test stub) is left as returned. If either step fails, the reset aborts with 500 and deletes nothing. `backup_sqlite_db(kind="season", label=…)` writes such a file directly.

The label is Reset's optional `season_label` (max 100 characters), else the newest `season_archive` label by `archived_at`, else "unarchived". `season_label_slug` reduces it to `[A-Za-z0-9-]` (runs of anything else become one dash, capped at 60 characters, "season" when nothing is left).

`list_sqlite_backups()` and `cleanup_old_backups()` match only `fantasy.db.backup-*`, so season files are never pruned; `list_season_backups()` lists them. `.gitignore` ignores `data/*.season-*` and `.dockerignore` `*.db.season-*`: the files hold password hashes and emails. See [Admin Database Backups](admin-db-backup.md).

## Guided flow

After End Season succeeds, a small result dialog says "Season <label> archived. The season's data is still live: continue to Reset Season to start the next season." with **Continue to Reset Season** (opens the Reset dialog) and **Later**. The Reset dialog loads the preview and lists what is deleted (non-zero counts, and "N users' tokens reset to 5") and kept (user accounts, non-zero kept tables, the season backup's label) above the typed RESET SEASON input, with the "Run End Season first" warning when it applies. Above the lists, for an archived label without a summary (a season ended before this change, such as Season 16), it says "Season <label> has no stored summary. Save it before resetting, or its player and team results are lost." with **Save season summary**: the typed confirmation SAVE SUMMARY and re-auth, `POST /admin/season/summary` through `adminFetch`, then the preview reloads. With a summary stored it reads "Season summary stored: N players, M teams." After the reset, the status line lists the deleted counts and the season backup's file name.

## Endpoints

### `GET /admin/season/reset-preview`
Admin. Read-only: `season_label` (the backup's label: the newest archived label, else "unarchived"), `archived`, `has_summary`, `summary_players`, `summary_teams` (that label's stored summary rows), `initial_tokens`, `delete` (the same keys and counts Reset returns in `counts`), `keep` (kept tables' counts), `end_season_missing` and `warning` (set when locked weeks exist with no newer archive; Reset then answers 409 without `force`).

### `POST /admin/season/summary`
Admin, recent re-auth, typed confirmation `season_summary` ("SAVE SUMMARY"). Body `{season_label}`. Stores the summary for an archived label from the live data, the same rows End Season stores, and writes an `admin_season_summary` audit row. 404 when the label isn't archived; 409 when it already has a summary or there are no live matches (the season was reset). Use it for a season ended before this change, **before** running Reset.

### `GET /admin/season/accolades-preview`
Adds the optional `season_label` query (max 100, 422 beyond) and the `recorded` counts above.

### `GET /admin/backups`
Adds `season_backups` beside `backups`; `GET /admin/backups/{filename}` downloads either kind with the same checks.

## Season end workflow (#257)

Plan: `markdown/plans/plan-issue-257-season-end-workflow.md`. The Season 16 → 17 steps are the runbook in [Season Lifecycle](season-lifecycle.md#season-16--17-runbook).

- **Archiving twice is refused under any spelling.** `accolades.normalise_label` trims, collapses inner spaces and ignores case; `accolades.archived_match(db, label)` compares it with every distinct `season_archive.season_label`. `POST /admin/season/end` answers 409 "Season 16 is already archived (archived 2026-11-20, 42 users)" (the existing label, its newest `archived_at` as a UTC date, its user count) before it writes anything, for an exact repeat as well as "season 16" or "Season  16". `GET /admin/season/accolades-preview` adds `archived: {label, archived_at, users, has_summary}` or `null`; the End Season dialog shows the note above its buttons, disables **Continue to END SEASON**, and, when that season has no summary, points to **Save season summary** in the Reset dialog.
- **Removing an archive.** `GET /admin/season/archives` (admin) lists `[{season_label, archived_at, users, has_summary}]`, newest first. `DELETE /admin/season/archive?season_label=…` (admin, recent re-auth, typed confirmation `season_archive_remove` "REMOVE ARCHIVE", as a query parameter or JSON `confirm`) deletes only that label's `season_archive` rows, writes `admin_season_archive_removed` (`season_label=… users=N`) and answers `{season_label, removed, kept}`. Accolades, `season_player_stats`, `season_team_results` and season backups are not touched: remove wrong accolades row by row in Player management. 404 when the label has no archive; 409 when there are no live matches or no stats rows (Reset has run) or a newer archive exists. Only the newest archive can be removed: to remove an older, misspelled one, remove the newer ones first, since End Season could no longer rebuild the standings. Admin › Settings › Season lists the archives with **Remove archive…**, which uses the shared in-page typed confirmation (never `confirm()`).
- **Reset clears the season-only records**: finals brackets and predictions, promo codes and redemptions, token grant events and claims, notifications and dismissals (table above). Audit logs keep the record of codes, grants and notifications; the History tab doesn't show past finals.
- **The dialogs fit the screen.** The Reset and End Season dialogs (`.modal.season-dialog`) are capped at `calc(100vh - 32px)` as a flex column: a fixed head (title, close), a scrolling body (`.season-dialog-body`) and a fixed footer (`.season-dialog-foot`: the typed RESET SEASON input, the buttons and the status). Deleted and Kept each sit in a `<details>` whose `<summary>` shows the totals ("Deleted: 14 tables, 12 345 rows"; Kept counts user accounts as a table); Deleted is open, Kept closed. Side by side on wide screens, stacked at 640 px and below.
- **Check script.** `python3 scripts/season_end_check.py <backup file> [--label L]` opens the file read-only (`mode=ro&immutable=1`; no -wal/-shm files, a missing file is not created) and prints the archived labels with dates and users, labels that match after normalising, accolade counts per label, kind and source, possible duplicates (the same player and kind under two matching labels; more than one champion team per label and division; a `season_end` and an `admin` row for the same player and kind), whether each archived label has a stored summary, and Reset's deleted and kept row counts. Exit 0 when nothing needs attention, 1 when it finds a problem (a missing summary counts only for the newest archive while the copy still has matches, since only then can it be saved), 2 when the file can't be read. It keeps a copy of `normalise_label` (a test checks they agree) and reads the table groups from `season_reset` with `DATABASE_URL=sqlite://`, so it never opens the app database.
