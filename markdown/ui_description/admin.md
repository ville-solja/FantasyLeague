# Admin tab

Visible only to admin users. All actions require an active admin session cookie — client-side `is_admin` alone is not sufficient.

## Ingest League panel

- Input field for an OpenDota league ID.
- **Ingest** button — fetches all matches for that league from OpenDota, calculates fantasy points, seeds player cards into the deck, and enriches player profiles with names and avatars. Safe to re-run; already-stored matches are skipped.

## Refresh Schedule Cache panel

- **Refresh** button — busts the in-memory schedule cache and re-fetches the Google Sheets CSV. Use after the sheet is updated between match weeks.

## Recalculate Fantasy Points panel

- **Recalculate** button — re-applies the current scoring weights to all stored player match stats without re-fetching from OpenDota. Use after adjusting weights.

## Database Backups panel

Settings tab, below Season Lifecycle. See `markdown/features/reference/admin-db-backup.md`.

- Explanatory line: "Backups are stored on the server and deleted automatically after N days. Download a copy before deploying if you need to keep it." — N comes from `retention_days` in `GET /admin/backups` (`DB_BACKUP_RETENTION_DAYS`).
- **Create backup now** — calls `POST /admin/backups`. Disabled while the request is in flight. The status line shows "Created {filename}" or the error detail (e.g. the 60-second cooldown message on 429, or the non-SQLite message on 409). The table reloads only after a successful backup.
- **Refresh** — reloads the table.
- **Table** — columns Filename, Created (browser local time), Size (human-readable, e.g. `1.9 MB`), and a **Download** link per row (`GET /admin/backups/{filename}`, saved as an attachment). Newest first. Shows "No backups yet" when empty. Filenames are HTML-escaped.
- The list loads whenever the Settings admin sub-tab is activated.

## Promo Codes panel

- **Create** — enter a code name (auto-uppercased) and a token amount, then click Create. The code can be redeemed by users in the My Team tab.
- **Table** — lists all existing codes with their token amount and redemption count. Each row has a Delete button.

## Token Balances panel

- Lists all registered users with their current token balance.
- Each row has a number input and a **Grant** button to add tokens to that user's balance.

## Scoring Weights panel

- Read-only table of all configured weight keys and values (loaded from `GET /weights`).
- Includes scoring stat weights, death formula params (`death_pool`, `death_deduction`), rarity bonuses (`rarity_common` … `rarity_legendary`), and modifier tuning keys (`modifier_count_*`, `modifier_bonus_pct`).
- Operational changes are made outside the UI (typically `WEIGHTS_JSON` overrides merged on startup and/or direct DB edits to the `weights` table), then use **Recalculate** to backfill `player_match_stats.fantasy_points` if needed.

## Matches panel

- Table columns: Match (OpenDota link), League, Team 1, Team 2, Start Time, **Parse**, **Scoring**, MVP, VOD, Action (**Set MVP**).
- **Parse** shows Parsed, Unparsed or Unparseable (a dash for matches with no status). Unparsed rows have a **Retry parse** button (`POST /admin/matches/{id}/retry-parse`). After it finishes, the table reloads and the status line says whether the match was refreshed with parsed stats, a parse was requested, the request was on cooldown, or OpenDota rejected it. A 409 appears in the status line while an ingest is running.
- **Scoring** has two checkboxes, **Unparseable** and **Not scored**. Each change sends `PATCH /admin/matches/{id}/scoring` with that single field, then the table reloads. On error, the checkbox reverts and the status line shows the error.
- An **Unparseable only** checkbox in the panel header filters the table client-side to matches whose status is Unparseable. The empty state reads "No unparseable matches".
- See `markdown/features/reference/unparseable-match-handling.md`.
