# Plan: Season End Workflow

## Context
Season 16 is already archived in production by the End Season of before #133, which recorded the awards and champions automatically on top of rows entered by hand. That left duplicates, which the admin is removing by hand. The issue asks four things:
- what happens when a season is archived twice;
- a fix for the Reset Season dialog, which is too tall to use on a normal screen (the screenshot is 1676 px tall);
- clearing finals predictions, promo codes and their redemptions, token events and notifications for Season 17;
- a confirmed way to end Season 16 and start Season 17 without breaking the data.

**What the code does today** (checked for this plan):
- **End Season on a label that is already archived** answers 409 "Season '<label>' is already archived" before it writes anything. Nothing changes.
- **Accolade rows are unique** on (season, kind, division, player, user) (`ux_season_accolades_key`). Any End Season part, run again for the same label, adds no duplicate rows (`accolades.insert_ignore`).
- **The real risk is a label variant.** The archive check compares the exact trimmed label. End Season with "season 16" or "Season  16" therefore creates a second archived season, with its own standings and a second set of awards and Played rows. History then shows two seasons. Duplicates can also come from a hand-entered row under a different label, or a champion entered for the wrong division or under a different player id.
- **An archive can't be removed in the UI.** Only single accolade rows can be removed (Player management, `DELETE /admin/season-accolades/{id}`).
- **Reset Season keeps** `finals_brackets`, `finals_predictions`, `promo_codes`, `code_redemptions`, `token_grant_events`, `token_grant_claims`, `notifications` and `notification_dismissals` (`season_reset.TABLE_GROUPS["kept"]`).

**What this plan adds:**
- End Season refuses a label that matches an existing archive after ignoring case and spacing, and its dialog shows when a label is already archived.
- An admin can remove one season's archived standings (and nothing else) to redo End Season.
- Reset Season clears the eight tables above.
- The Reset dialog fits the screen.
- A read-only check script that runs on a downloaded backup.
- A written runbook for Season 16 → 17.

**Assumptions:**
- **"Not needed" means deleted at Reset**, not kept and hidden. Finals predictions are only meaningful for the season they were made in, and the History tab doesn't show past finals. Audit logs keep the record of codes, grants and notifications.
- **Removing an archive deletes only `season_archive` rows for that label.** Accolades, the season summary and the season backup stay. The admin removes accolades row by row as today. Removing needs a recent re-auth and the typed phrase REMOVE ARCHIVE, and is refused (409) once Reset has run for that season, since End Season could then no longer rebuild the standings.
- **The check script reads a copy**, never the live database: `python3 scripts/season_end_check.py <backup file> [--label "Season 16"]`, using a file from Admin › Backups.

Resolves GitHub issue #257.

## User Stories

### Archiving a Season Twice Is Refused
**User story**
As a league admin, I want End Season to refuse a season that is already archived, including under a slightly different spelling, so that no second copy of a season's standings and awards is created.

**Acceptance criteria**
- `POST /admin/season/end` answers 409 when an archive exists whose label equals the new one after trimming, collapsing inner spaces and ignoring case. The message names the existing label ("Season 16 is already archived (archived <date>, N users)"). Nothing is written
- The End Season dialog checks the label as it is typed, through `GET /admin/season/accolades-preview`, which now also returns `archived: {label, archived_at, users, has_summary}` or null. For an archived label, the dialog:
  - says so;
  - disables **Continue to END SEASON**;
  - points to **Save season summary** in the Reset dialog when that label has no summary
- An exact repeat still answers 409, as today

### Remove a Season's Archived Standings
**User story**
As a league admin, I want to remove one season's archived standings so that I can redo End Season after archiving under a wrong label or too early.

**Acceptance criteria**
- `DELETE /admin/season/archive?season_label=…` deletes that label's `season_archive` rows. It needs admin, a recent re-auth and the typed phrase REMOVE ARCHIVE, writes an `admin_season_archive_removed` audit entry (`season_label=… users=N`), and answers `{season_label, removed, kept}` (`kept` says what was not touched)
- Accolades, `season_player_stats`, `season_team_results` and season backups are not touched; the response says so
- 404 when the label has no archive. 409 when the season's data has been reset (no live matches, or matches without any stats rows), or a newer archive exists. End Season could then not rebuild it
- Admin › Settings › Season shows the archived seasons (label, date, users), each with **Remove archive…** and an in-page confirmation. It never uses `confirm()`

### Clear Season-Only Records at Reset
**User story**
As a league admin, I want Reset Season to also clear finals predictions, promo codes and redemptions, token grant events and claims, and notifications so that Season 17 starts without Season 16's leftovers.

**Acceptance criteria**
- `season_reset.TABLE_GROUPS["cleared"]` now includes these tables, deleted child-first:
  - `finals_predictions`, `finals_brackets`
  - `code_redemptions`, `promo_codes`
  - `token_grant_claims`, `token_grant_events`
  - `notification_dismissals`, `notifications`
- The Reset preview lists their counts under Deleted, and the reset response's `counts` includes them
- The table-coverage test still places every model table in exactly one group
- Audit logs, accolades, season archives, summaries, tags and accounts are still kept

### Reset Dialog Fits the Screen
**User story**
As a league admin, I want the Reset Season dialog to fit a normal screen so that I can read it and reach the confirmation without a vertical monitor.

**Acceptance criteria**
- The dialog's height is capped at the viewport (with a margin) and its body scrolls. The title, the typed-confirmation input and the buttons stay visible
- Deleted and Kept show their totals ("Deleted: 14 tables, 12 345 rows"), with the per-table lists folded under `<details>`. Deleted is open by default, Kept closed
- On wide screens the two lists sit side by side; at 640 px and below (`max-width: 640px`) they stack, and at phone width (360 px) nothing scrolls sideways
- The same cap applies to the End Season dialog

### End a Season Without Breaking the Data
**User story**
As the operator, I want a checked, written procedure for ending Season 16 and starting Season 17 so that the history stays correct and nothing is lost.

**Acceptance criteria**
- `scripts/season_end_check.py <backup file> [--label L]` opens the file read-only and prints:
  - the archived labels with dates and user counts;
  - labels that match after normalising;
  - accolade counts per label, kind and source;
  - possible duplicates: the same player and kind under two matching labels, more than one champion team per label and division, or a `season_end` and an `admin` row for the same player and award;
  - whether each archived label has a stored summary (a missing one counts as a problem only for the newest archive while the copy still has matches, since only then can it be saved);
  - what Reset would delete and keep.
  It never writes, and exits 0 when clean, 1 when it finds a problem, 2 when the file is missing or unreadable
- `markdown/features/reference/season-lifecycle.md` gets a "Season 16 → 17 runbook" with the order of steps and what to check after each, including what to do when the check finds duplicates

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/accolades.py` | `normalise_label()`; `archived_match(db, label)` |
| `backend/routers/admin_season.py` | End Season uses the normalised check; accolades-preview returns `archived`; `GET /admin/season/archives`; `DELETE /admin/season/archive` |
| `backend/season_reset.py` | Eight tables move from `kept` to `cleared`, in child-first order |
| `backend/deps.py`, `frontend/app-admin.js` | Typed phrase `season_archive_remove`: "REMOVE ARCHIVE" |
| `frontend/app-admin-season.js`, `frontend/index.html`, `frontend/style.css` (or the stylesheet holding `.modal-overlay`) | Already-archived state in End Season; archive list with Remove; Reset dialog layout (height cap, scrolling body, sticky footer, `<details>` lists) |
| `scripts/season_end_check.py` *(new)* | Read-only checks on a backup file |
| `markdown/features/reference/season-lifecycle.md`, `season-reset-clean-slate.md`, `core/admin.md`, `ui_description/admin.md` | Runbook, table groups, endpoints, audit action, dialog spec |
| `backend/tests/test_issue_257_season_end_workflow.py` | Tests |

### Step 1 — Label matching
```python
def normalise_label(label: str) -> str:
    return " ".join((label or "").split()).casefold()
```
`archived_match(db, label)` returns the existing archive's label, its newest `archived_at` and its user count, when any archived label normalises to the same value. End Season answers 409 with that label before computing standings. The accolades preview adds `archived`.

### Step 2 — Archive list and removal
`GET /admin/season/archives` (admin) returns `[{season_label, archived_at, users, has_summary}]`, newest first. `DELETE /admin/season/archive`:
- **Dependencies:** `require_recent_reauth`, then `require_typed_confirmation("season_archive_remove")`.
- **Refusals:** 404 when the label has no archive. 409 when `season_summary.has_live_data(db)` is false, or when an archive with a later `archived_at` exists.
- **Effect:** deletes the label's `season_archive` rows, writes the audit entry and commits.

### Step 3 — Reset clears the season-only records
Move the eight tables into `cleared`, in child-first order. `season_reset.clear` deletes in list order, so children must come before parents. Check the order against the foreign keys: `code_redemptions.code_id`, `token_grant_claims.event_id`, `notification_dismissals.notification_id` and `finals_predictions.bracket_id`. Update the #133 docs table and the coverage test's expectations. `finals.clear_caches()` already runs in `bust_caches`.

### Step 4 — Dialogs fit the screen
- `.modal-overlay .modal` for the two season dialogs: `max-height: calc(100vh - 32px)` and a flex column. The body is `overflow-y: auto`; the footer (input and buttons) is outside the scrolling area.
- `seasonResetPreviewLists` returns totals, and the lists render inside `<details>`.
- Check at 360 px and 1366×768.

### Step 5 — Check script and runbook
`scripts/season_end_check.py` opens the backup with `sqlite3.connect("file:…?mode=ro", uri=True)`, imports nothing that opens the app database, and prints a short report. It reuses `normalise_label`, imported from `accolades` with `DATABASE_URL=sqlite://` set first, or copied with a test that the two match.

The runbook in `season-lifecycle.md`:
1. Take a backup: `scripts/backup-db.sh`, or Admin › Backups › Create.
2. Download the backup and run the check script on it.
3. Remove the duplicates it lists in Player management. Run the check again on a fresh backup until it reports none.
4. Open Reset Season. If Season 16 has no summary, press **Save season summary**.
5. Read the Deleted and Kept lists, then run Reset Season with the label "Season 16".
6. Check History, the player popup accolades and the new season backup file.
7. Never run End Season again for Season 16; if an archive is wrong, use **Remove archive…** before Reset.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_257_season_end_workflow.py tests/test_issue_133_season_reset_clean_slate.py tests/test_issue_50*.py -q`, then the full suite.
- End Season with "season 16" and with "Season  16" after "Season 16" is archived: 409 naming "Season 16", and no rows are added.
- Remove archive: rows are gone, accolades and summary are unchanged, and End Season under the same label then works. It answers 409 after a Reset, 403 without a re-auth and 400 without the phrase.
- Reset with finals, promo codes, redemptions, token grants and notifications present: all eight tables are empty afterwards, and audit logs and accolades are unchanged.
- Run the check script on a copy with a duplicate champion and a near-duplicate label: it reports both and exits 1. On a clean copy it exits 0, and the file's modification time is unchanged.
- Manual: the Reset dialog at 1366×768 and 360 px shows the input and buttons without scrolling the page.
- Production, by the operator, following the runbook: run the check on a downloaded Season 16 backup before Reset.
