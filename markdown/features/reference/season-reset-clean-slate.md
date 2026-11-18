# Season Reset Clean Slate

Ending a season leaves nothing of it in the live tables while keeping what matters across seasons: a stored summary of each player's and team's season, and a permanent backup file of the raw data. For the league admin running End Season and Reset Season. Issue #133. Plan: `markdown/plans/plan-issue-133-season-reset-clean-slate.md`. The rest of the flow is in [Season Lifecycle](season-lifecycle.md).

Code: `backend/season_reset.py` (table groups, preview, clear, caches), `backend/season_summary.py` (the summary), `backend/routers/admin_season.py` (routes), `backend/database.py` (season backups), `frontend/app-admin-season.js`.

---

## Reset clears every season table

`season_reset.TABLE_GROUPS` puts every model table in exactly one group; `test_issue_133` fails when a new table is in none, so whoever adds a table decides what Reset does with it. The raw `schema_migrations` table has no model and is outside the lists.

| Group | Tables |
|---|---|
| Cleared (deleted) | `matches`, `player_match_stats`, `card_match_points`, `match_bans`, `weeks`, `weekly_roster_entries`, `twitch_mvp`, `twitch_token_drops`, `players`, `teams`, `cards`, `card_modifiers`, `own_player_card_grants`, `weekly_summaries`, `weekly_summary_reveals`, `weekly_summary_seen`, `live_matches`, `match_timings`, `twitch_presence` |
| Updated | `users` (tokens reset to `INITIAL_TOKENS`), `leagues` (unmonitored), `demo_clock` (override cleared, row kept) |
| Kept | `season_archive`, `season_accolades`, `season_player_stats`, `season_team_results`, tags and user tags, `audit_logs`, finals tables, team signup tables, promo codes and redemptions, token grant events and claims, notifications and dismissals, `weights`, `player_profiles`, Twitch vote polls, votes and pending vote tokens, the sign-in and session tables, Twitch link and merge records, channel approvals, `toornament_sync_log`, `scoring_state` |

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
