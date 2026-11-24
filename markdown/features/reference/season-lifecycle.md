# Season Lifecycle Management

Admin-driven flow for ending a season and starting the next one: archive final standings,
reset per-season data, and create the new season's weeks manually — no env edits or redeploys
between seasons.

---

## Lifecycle Flow

```
Season running
    ↓  admin: POST /admin/season/end        (archive standings, the chosen accolade parts, season summary)
Standings snapshotted to season_archive; awards, champions and Played kept in season_accolades;
player and team results kept in season_player_stats / season_team_results (issue #133)
    ↓  admin: GET /admin/season/reset-preview, then POST /admin/season/reset
       (clean slate; permanent season backup; users retained; players/teams cleared)
Empty season state
    ↓  admin: add monitored league, add players (Player Management tab), create weeks (date-only forms)
Next season running
```

Week auto-generation is removed — weeks are created manually in the Week Management tab.
The background maintenance loop still auto-locks weeks whose start time has passed.

## Endpoints

### `POST /admin/season/end`
Body: `{"season_label": "Season 15"}`. Snapshots the current season leaderboard
(username, points, rank; testers and Twitch viewer soft accounts excluded, issue #157) into `season_archive`, computed via the shared
`compute_season_standings()` helper also used by `GET /leaderboard/season`. 409 if the label
is already archived, under any spelling (issue #257: case and spacing are ignored, and the message names the existing label, its date and user count). Logged as `admin_season_archived`. The stored `points` are the standings' one-decimal display values (`scoring.display_points`, issue #149).

Issue #50: the body also takes optional `champions: [{division, team_name, player_account_ids}]`.
In the same transaction the call records the season's accolades in `season_accolades`: the
five awards (Most Points, Best Average, Best Single Match, Most MVPs, Fantasy Winner), the champions and one `played` row per player with a scored match. If that fails,
nothing is committed (500). The audit detail adds `accolades=N champions=M`. The admin UI shows
a preview first (`GET /admin/season/accolades-preview`), with the label prefilled from the
current season: "Season N" parsed from the monitored leagues' OpenDota names ("Kanaliiga Season
16", "Kanaliiga Season 16 Lower"), which stay monitored until Reset; without such a name it is
inferred from the archives and accolades. Past seasons' Played rows (S4–S15) are backfilled with
`backend/scripts/backfill_played.py --all`, using the league ids in `backend/scripts/kanaliiga_leagues.json`
(#212; S1–S3 have no OpenDota league and use the Played paste). See
[Season Participation Backfill](season-participation-backfill.md) and
[Season Champions, Accolades and Holo Cards](season-winners-and-holo-cards.md).

Issue #133: the body also takes `record_awards`, `record_champions`, `record_played` and
`store_summary` (default true); the standings archive always runs. In the same transaction End
Season stores the season summary (`season_player_stats`, `season_team_results`). The response adds
`parts` and `summary`. End Season deletes nothing: the season's data stays live until Reset.
`POST /admin/season/summary` stores the summary for a season archived without one, before Reset.
See [Season Reset Clean Slate](season-reset-clean-slate.md).

### `POST /admin/season/reset`
Body: `{"force": false, "season_label": null}`. Issue #133 extended Reset: the full list of cleared,
updated and kept tables, the cache clearing, the season backup's name and the preview are in
[Season Reset Clean Slate](season-reset-clean-slate.md); the summary below is the original behaviour.
Before any deletes, takes an automatic online backup of the live
SQLite database (`backup_sqlite_db()` in `backend/database.py`, using SQLite's online backup
API so it's safe against a WAL-mode connection). If the backup fails, or returns no file
because the database is not a local SQLite file or the SQLite file is missing (issue #135), the reset aborts with a
500 and **no deletes are performed** — there's no code path that wipes season data without a
fresh backup existing first. The backup is renamed to a permanent season backup,
`fantasy.db.season-<label>-<timestamp>`, which the daily cleanup never deletes. Deletes all rows from `card_match_points`, `player_match_stats`, `match_bans`,
`matches`, `weekly_roster_entries`, `weeks`, `twitch_mvp`, `twitch_token_drops`, `players`,
`teams`, `card_modifiers`, `cards` and `own_player_card_grants` (issue #188, so next season's
league players get their own player card again), plus (issue #133) the Weekly Report tables,
`live_matches`, `match_timings`, `twitch_presence` and the demo clock override. Resets every user's `tokens` to `INITIAL_TOKENS` and
unmonitors all leagues. Retains users, tags, audit logs, `season_archive` rows and
`season_accolades` rows (issue #50), the season summary tables (issue #133) and every other kept table; the response's `kept` counts each of them. Since issue #257 Reset also deletes the finals tables (`finals_brackets`, `finals_predictions`), promo codes and redemptions, token grant events and claims, and notifications and dismissals. Returns 409
if any locked week exists with no `season_archive` row archived at or after that week's start
time (unless `force=true`) — the guard that makes skipping End Season difficult. Response
includes `{"status", "initial_tokens", "counts": {...}, "kept": {...}, "season_label", "backup_path", "backup_file"}` with a per-table
deleted-row count (including `own_player_card_grants`) and the path of the pre-reset backup file. Logged as `admin_season_reset`,
with the backup path prefixed to the counts in the detail string.

**Players, Teams, and Cards are wiped entirely — not just deactivated.** The `players` table
doubles as the admin-curated Player Pool (see `reference/admin-player-pool.md`), so reset
also empties the draft pool: the admin repopulates it via Player Management once the new
season's roster is known. Rosters fluctuate season to season, so retaining players/cards
tied to a roster that no longer exists is a real risk, not just clutter. Cards are deleted
(not soft-deactivated) for the same reason — a genuine clean slate means every user starts
the new season by drawing a fresh collection with their reset tokens, rather than keeping
cards for players who may no longer play. This is a deliberate trade-off, most relevant when
the same instance is reused for a different league.

### `GET /admin/season/archives` and `DELETE /admin/season/archive` (issue #257)
List the archived seasons for Admin › Settings › Season, and remove one season's archived
standings (recent re-auth, typed REMOVE ARCHIVE) so End Season can run again before Reset.
Details in [Season Reset Clean Slate](season-reset-clean-slate.md#season-end-workflow-257).

### `GET /leaderboard/seasons`
Lists archived seasons, one row per distinct `season_label`, newest first:
`[{id, season_label, archived_at, user_count}]`. `id` is the lowest `season_archive.id` in
that label's group and is the identifier `GET /leaderboard/seasons/{season_id}` expects.

### `GET /leaderboard/seasons/{season_id}`
Returns the archived standings for the season containing that `season_archive` row:
`{id, season_label, archived_at, standings: [{user_id, username, points, rank}]}`. 404 if
`season_id` does not match any archived row.

### `GET /profile/{user_id}` (extended)
Response gains `past_seasons`: `[{season_label, points, rank}]`, one entry per archived
season the user appears in, most recent first.

### `POST /admin/weeks` and `PATCH /admin/weeks/{week_id}` (extended)
Accept `start_date` / `end_date` (ISO `YYYY-MM-DD`) alongside the existing `start_time`/
`end_time` integer fields (still accepted for backward compatibility; date fields take
precedence when both are present). Derivation: `start_time` = start date 03:00:00 UTC;
`end_time` = 02:59:59 UTC on the day **after** the end date — the same 3-hour grace period
applied to both ends, so matches running past midnight still count toward the week and a
normal Monday-to-Sunday week never overlaps the next Monday-start week by default (see
`reference/week-boundary-formula-fix.md`). Existing validation (end after start, locked weeks
cannot be edited/deleted) is unchanged.

## Database

| Table | Purpose |
|---|---|
| `season_archive` | One row per user per archived season: label, user_id, username (denormalised), points, rank, archived_at. Unique on (season_label, user_id). |
| `season_accolades` | Champions, awards, fantasy winners and seasons played (issue #50); never touched by Reset. See [Season Champions, Accolades and Holo Cards](season-winners-and-holo-cards.md). |
| `season_player_stats`, `season_team_results` | The season summary End Season stores (issue #133): per player games, wins, raw points, best game, K/D/A, MVPs; per team series and games won, lost and drawn. Never touched by Reset. See [Season Reset Clean Slate](season-reset-clean-slate.md). |

## Retired Configuration

| Variable | Replacement |
|---|---|
| `SEASON_LOCK_START` | Manual week creation (Week Management tab) |
| `SEASON_END` | No auto-generation — nothing to stop |
| `AUTO_INGEST_LEAGUES` | Monitored leagues admin (`/admin/leagues/*`) |

Deployments that still set these vars start cleanly; the values are ignored.

`SCHEDULE_SHEET_URL` remains supported but loses its hardcoded Kanaliiga fallback (default is
now `""`): unset means an empty schedule tab. Instances hosting Kanaliiga must set it
explicitly in `.env`.

## Admin UI

The Settings tab (admin panel) has a "Season Lifecycle" section: a season-label input with
an "End Season (Archive)" button. It opens a dialog with the season's awards, the Played count
and the Div 1 and Div 2 champion pickers (issue #50) and a checkbox per part (issue #133), then asks the
admin to type `END SEASON`; on success a result dialog offers **Continue to Reset Season**. A "Reset Season…"
button opens a modal that lists what will be deleted and kept (`GET /admin/season/reset-preview`) above
the type-to-confirm field (must type `RESET SEASON`; the backend checks it as
`confirm`, issue #150), and a table of previously archived seasons, each with **Remove archive…**
(issue #257). Both season dialogs fit the screen: the body scrolls, the typed field and buttons stay in view. The Leaderboard tab
shows a "Past Seasons" panel with a season selector once at least one archive exists. The
Profile view shows a "Past Seasons" line per archived season the user appears in
(e.g. "Season 15 — 3rd, 1240.0 pts"). Week Management's create/edit forms use `<input
type="date">` instead of `datetime-local`.

## Season 16 → 17 runbook

Issue #257. For the operator ending Season 16 and starting Season 17 in production. Season 16 was
archived before #133, by an End Season that recorded awards and champions on top of rows entered by
hand, so check for duplicates before Reset. Each step says what to check before going on.

1. **Take a backup.** Admin › Backups › Create, then Download it (no host access needed; `bash scripts/backup-db.sh` on the server does the same).
   Check: the new file is listed under Backups.
2. **Download the backup and run the check on it**, never on the live database:
   `python3 scripts/season_end_check.py ~/Downloads/fantasy.db.backup-… --label "Season 16"`.
   It opens the file read-only. Exit 0 and "No problems found." means go on to step 4.
3. **When the check finds duplicates**, fix them in the app, not in the file:
   - *Matching labels* ("Season 16" and "season 16"): a second archive under the wrong spelling is
     removed with **Remove archive…** in Admin › Settings › Season (typed REMOVE ARCHIVE). It only works
     on the newest archive: with a later archive present it answers 409. If the misspelled archive is
     not the newest, remove the newer one(s) first, newest first, then the misspelled one, and run End
     Season again under the correct label for any season you removed that should stay archived (only
     possible while the live data is there, i.e. before Reset). Removing an archive never touches
     accolades: remove the duplicate accolades recorded under the variant label row by row in Player
     management (the accolade rows table).
   - *More than one champion team, or a `season_end` and an `admin` row for the same player and
     award*: keep one and remove the other in Player management (the accolade rows table).
   - Take a fresh backup, download it and run the check again until it reports no problems.
4. **Open Reset Season** (Admin › Settings › Season › Reset Season…). If it says Season 16 has no
   stored summary, press **Save season summary** (typed SAVE SUMMARY). Check: the dialog then reads
   "Season summary stored: N players, M teams."
5. **Read the Deleted and Kept lists.** The dialog has no label field: Reset names the season backup
   after the newest archived label. Check that the dialog names Season 16 (the summary line and the
   Kept list's "Season backup named after "Season 16"" line show the label) and that Kept lists the
   accolades, the season archive and the season summaries; then type RESET SEASON and press
   **Reset Season**.
6. **Check the result**: the History tab shows Season 16 once, with its champions and awards; a
   player popup shows that player's Season 16 accolades; Admin › Backups lists the season backup
   `fantasy.db.season-Season-16-…`. Keep that file.
7. **Never run End Season again for Season 16.** It is refused anyway, under any spelling. If an
   archive is wrong, use **Remove archive…** *before* Reset; after Reset it is refused (409), since
   the season's data is gone and End Season could not rebuild the standings.

Then start Season 17 as in the Lifecycle Flow above: add the monitored leagues, the players and the weeks.

