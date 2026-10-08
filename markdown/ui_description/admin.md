# Admin tab

Visible only to admin users. All actions require an active admin session cookie — client-side `is_admin` alone is not sufficient.

## Password re-entry prompt

Destructive actions (End Season, Reset Season, league data purge, every Database Backups action, Promote/Demote admin, Grant tokens) and, since issue #167, the other token-economy and broadcast actions (create or delete a promo code, create or delete a token grant event, create or delete a notification, Toggle tester) need the admin's password again if it was not confirmed on this device in the last 10 minutes. The server answers 403 `reauth_required`; `adminFetch()` then opens an in-page **Confirm your password** modal (password field, **Confirm** and **Cancel**, never a browser `confirm()`/`prompt()`). Confirm calls `POST /reauth` (Enter in the field does the same; the field is the `#reauthForm` form, with a hidden username, so password managers fill it, see `features/reference/password-manager-autofill.md`); on success the modal closes and the action is retried once. A wrong password shows the error in the modal's status line and keeps it open. Cancel (or Escape, or a backdrop click) closes it and the action reports the 403 in its usual status line. The modal stacks above the Season Reset confirmation. Token grants and Delete (Twitch viewer) need it too (issue #150).

An admin account without a password (created through Steam, issue #150) sees **Confirm with Steam** instead of the password field: a note that the action needs a fresh sign-in, a **Confirm with Steam** button and **Cancel**. The button navigates to `GET /auth/steam/start?purpose=reauth&return_tab=admin`; Steam returns to the Admin tab, whose status line at the top reads "Confirmed with Steam. Repeat the action to continue." (or the failure message). The same modal switches to this view if `POST /reauth` answers 409 `use_steam_reauth`.

## Typed confirmation

Six destructive actions also ask the admin to type the action's name (issue #150): End Season (`END SEASON`), Reset Season (`RESET SEASON`, typed in the Season Reset modal itself), Promote/Demote admin (`CHANGE ADMIN`), **Grant** tokens (`GRANT TOKENS`), backup **Download** (`DOWNLOAD BACKUP`) and **Delete** on a Twitch viewer account (`DELETE USER`). A **Confirm action** modal (`#typedConfirmModal`) shows what will happen, "Type {PHRASE} to confirm", a text field, a red **Confirm** and **Cancel**. A wrong phrase shows "Type "{PHRASE}" to confirm." in the modal and keeps it open; case does not matter. Cancel, Escape or a backdrop click does nothing. The password prompt (when needed) opens after this modal. See `features/reference/steam-login.md`.

## Ingest League panel

- Input field for an OpenDota league ID.
- **Ingest** button — fetches all matches for that league from OpenDota, calculates fantasy points, seeds player cards into the deck, and enriches player profiles with names and avatars. Safe to re-run; already-stored matches are skipped.

## Refresh Schedule Cache panel

- **Refresh** button — busts the in-memory schedule cache and re-fetches the Google Sheets CSV. Use after the sheet is updated between match weeks.

## Recalculate Fantasy Points panel

- **Recalculate** button — re-applies the current scoring weights to all stored player match stats without re-fetching from OpenDota, then rebuilds every stored per-match card point (`card_match_points`). The response includes `recalculated` (stat rows) and `card_points` (stored card-point rows written), and the status line shows both counts. If the card-point rebuild fails, the recalculated stats are kept, the previous card points stay, and the status line shows the error. Use after adjusting weights.

## Database Backups panel

Settings tab, below Season Lifecycle. See `markdown/features/reference/admin-db-backup.md`.

- Explanatory line: "Backups are stored on the server and deleted automatically after N days. Download a copy before deploying if you need to keep it." — N comes from `retention_days` in `GET /admin/backups` (`DB_BACKUP_RETENTION_DAYS`).
- **Create backup now** — calls `POST /admin/backups`. Disabled while the request is in flight. The status line shows "Created {filename}" or the error detail (e.g. the 60-second cooldown message on 429, or the non-SQLite message on 409). The table reloads only after a successful backup.
- **Refresh** — reloads the table.
- **Table** — columns Filename, Created (browser local time), Size (human-readable, e.g. `1.9 MB`), and a **Download** button per row. It asks for the typed confirmation `DOWNLOAD BACKUP`, then fetches `GET /admin/backups/{filename}?confirm=…` through `adminFetch()` (so it can ask for the password) and saves the file under its own name; errors appear in the panel's status line. Newest first. Shows "No backups yet" when empty. Filenames are HTML-escaped.
- Loading, creating and downloading backups all need a recent password re-entry (see the prompt above), so opening the panel may show the prompt.
- The list loads whenever the Settings admin sub-tab is activated.

## Promo Codes panel

- **Create** — enter a code name (auto-uppercased) and a token amount, optionally **Max uses** (total redemptions across all users) and an **Expires** date and time, then click Create (asks for the password if not confirmed recently). The code can be redeemed by users in the My Team tab.
- **Table** — columns Code, Tokens, Uses ("3" or "3 / 100" with a cap), **Limits** ("Expires …" or "Expired …", "Max N uses", or "—") and a Delete button.

## Token Balances panel (User Management)

- An **account type** select: **Website accounts** (default) or **Twitch viewers** (`GET /users?account_type=full|twitch`). The search box filters the loaded list.
- **Website accounts** lists registered users with their current token balance.
- **Twitch viewers** lists soft accounts created by the Twitch panel's Join (issue #157) as "Twitch viewer #{id}", with an "ID SHARED" badge when the viewer shared their Twitch identity, card count, created and last-seen dates, and tokens. Each row has **Grant** and **Delete** (typed confirmation `DELETE USER`, then `DELETE /admin/users/{id}` after admin re-authentication; deletes the account and all its cards). No password, tag, tester, admin or logout actions. Twitch ids are never shown.
- **Twitch collection merges** (issue #160), under the user table: a short note and a **Show recent merges** button. It loads `GET /admin/twitch/merges` (admin password re-check) into a table: Website account, Merged (date and time), Moved ("{cards} cards · {tokens} tokens"), and Actions. A reversible merge has a **Reverse** button (confirmation, then `POST /admin/twitch/merges/{log_id}/reverse` with re-check); the status line then reports the cards and tokens returned and any tokens already spent. Merges that can't be reversed show "Reversed" or the reason (older than 30 days, cards gone after a season reset). "No merges in the last 30 days" when empty. Twitch ids are never shown.
- **Twitch status** (issue #180), below the merges and above Approved streamers: why the Twitch extension may not work. A short note and a **Refresh** button; it loads with the user list from `GET /admin/twitch/status` (admin only, no password needed), and after each load the status line reads "Updated {time}" (an error shows there instead). Three blocks:
  - A checklist table (State, Check, What to do), one row per server setting: `TWITCH_EXTENSION_CLIENT_ID` (with the extension origin CORS allows), `TWITCH_EXTENSION_SECRET` (set and base64; the value and its length are never shown), `TWITCH_EXTENSION_VERSION`, `TWITCH_LOCAL_DEV`, MVP channels (counts from `TWITCH_MVP_CHANNEL_IDS`, approved and waiting), Connect Twitch (`TWITCH_OAUTH_*` and the `cryptography` package), `APP_BASE_URL` and `STEAM_API_KEY`. The State cell reads **OK** (green), **Warning** (amber) or **Problem** (red).
  - **Panel traffic since the last restart**, in the same table form: the last request from the extension (any `/twitch/*` request from an allowed extension origin; when none, the row says the panel is not reaching this server and to check `ebs_url`, the URL Fetching Domains and HTTPS reachability), the last panel request with an accepted token ("3 min ago", or "None since the last restart"), refused tokens by kind (expired, invalid, server not configured) with when the last one happened, and up to five cross-origin hosts refused on `/twitch/*` (host and port only). Anyone can send a bad token or a made-up `Origin`, so these counts and hosts are hints to compare with the checks above, not proof of a fault.
  - **Twitch console**: a table (Check, Expected value) of what only the Twitch developer console can show: URL Fetching Domains contains the backend origin, the global configuration's `ebs_url` is the backend URL, and the installed version was packaged with this backend's origin. Expected values come from `APP_BASE_URL`.
  Every value is escaped with `_escHtml`. Errors appear in the section's status line. See `features/reference/twitch-integration-status.md`.
- **Approved streamers** (issue #175), below the merges: Twitch channels that may set match MVPs. A short note and a **Refresh** button; the lists load with the user list from `GET /admin/twitch/channels` (no password needed to view). Three lists, each a table with Channel (Twitch display name and login when known, otherwise "Name unknown"), Channel id, First seen, Last seen, and Actions:
  - **Waiting for approval**: channels whose broadcaster opened the MVP tool; **Approve** and **Reject**. "No channels are waiting." when empty.
  - **Approved**: channels from `TWITCH_MVP_CHANNEL_IDS` first, with a "from server settings" note and no button, then portal-approved channels with **Remove** (confirmation). "No channels are approved. With ENV=production no channel can set match MVPs." when empty.
  - **Rejected ({n})**: collapsed (`<details>`); **Approve** moves a channel back to approved.
  Approve, Reject and Remove call `POST /admin/twitch/channels/{channel_id}/approve|reject|remove` through `adminFetch` (password prompt when not confirmed in the last 10 minutes); the status line says "{name} can now set match MVPs" or "{name} moved to Rejected", and the lists reload. Names are escaped with `_escHtml`.
- **Superseded player id claims** (issue #150), below the approved streamers: a short note and a table loaded with the user list from `GET /admin/player-id-claims`: Cleared on (the account whose self-reported player id was cleared), Verified account (the Steam-linked account that has the id now), Player id, When. "None" when empty. Rows are built with `textContent`.
- Each row has a number input and a **Grant** button to add tokens to that user's balance (typed confirmation `GRANT TOKENS` and the password prompt when needed).
- **Promote to admin** / **Demote from admin** asks for the typed confirmation `CHANGE ADMIN`. Demo accounts can't be promoted (the status line shows "Demo accounts can't be admins").
- Each row has a **Force logout** button. After a confirmation prompt it calls `POST /users/{id}/force-logout`, which ends every session of that user; the status line then reads "{username} logged out of every session". Forcing your own logout (the prompt says it includes your own session) returns the page to the logged-out state.

## Scoring Weights panel

- Read-only table of all configured weight keys and values (loaded from `GET /weights`).
- Includes scoring stat weights, death formula params (`death_pool`, `death_deduction`), rarity bonuses (`rarity_common` … `rarity_legendary`), and modifier tuning keys (`modifier_count_*`, `modifier_bonus_pct`).
- Operational changes are made outside the UI (typically `WEIGHTS_JSON` overrides merged on startup and/or direct DB edits to the `weights` table), then use **Recalculate** to backfill `player_match_stats.fantasy_points` and rebuild the stored card points if needed. A restart also rebuilds the stored card points automatically when the weights changed (see `features/reference/stored-card-points.md`).

## Matches panel

- Table columns: Match (OpenDota link), League, Team 1, Team 2, Start Time, **Live seen**, **Stats in**, **MVP picked**, **Parse**, **Scoring**, MVP, VOD, Action (**Set MVP**).
- **Live seen**, **Stats in** and **MVP picked** show when the match was first seen live, when its stats were ingested and when its MVP was first confirmed in the Twitch extension, each as minutes after Start Time ("+2 min", "+58 min"; a negative value when it came before the start). Hovering a value shows the exact time. Unknown values show "—": a dash under Live seen means live detection missed the match. See `markdown/features/reference/mvp-selection-delays.md`.
- **Parse** shows Parsed, Unparsed or Unparseable (a dash for matches with no status). Unparsed rows have a **Retry parse** button (`POST /admin/matches/{id}/retry-parse`). After it finishes, the table reloads and the status line says whether the match was refreshed with parsed stats, a parse was requested, the request was on cooldown, or OpenDota rejected it. A 409 appears in the status line while an ingest is running.
- **Scoring** has two checkboxes, **Unparseable** and **Not scored**. Each change sends `PATCH /admin/matches/{id}/scoring` with that single field, then the table reloads. On error, the checkbox reverts and the status line shows the error.
- An **Unparseable only** checkbox in the panel header filters the table client-side to matches whose status is Unparseable. The empty state reads "No unparseable matches".
- See `markdown/features/reference/unparseable-match-handling.md`.

## Week Management panel

- Form to create a week (label, start date, end date in `pp.kk.vvvv` format with a calendar picker), with **Create** and **Refresh** buttons.
- Table columns: Label, Start, End, Locked, Rosters, and an unlabelled action column. **Rosters** is the number of active roster cards snapshotted at lock (saved bench cards are not counted).
- Unlocked weeks are edited inline (label and dates) and saved with **Save Changes**; each has a **Delete** button with an inline confirmation row.
- Locked weeks are read-only. Once a locked week is past its substitution time (`end_time + SUBSTITUTION_DELAY_HOURS`), its action cell has a **Re-run substitutions** button. It calls `POST /admin/weeks/{id}/substitutions` through `adminFetch` (no password re-entry: the action is not destructive), then the status line reports how many substitutions were made and the table reloads. See `markdown/features/reference/automatic-bench-substitution.md`.
