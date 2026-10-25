# Admin tab

Visible only to admin users. All actions require an active admin session cookie — client-side `is_admin` alone is not sufficient.

## Sub-tabs

User Management, **Twitch**, Week Management, Player Management, Matches, Audit Log and Settings (issue 214). When Twitch channels are waiting for approval, the **Twitch** sub-tab button and the top-level **Admin** tab show a count badge ("2", `aria-label` "2 streamers waiting for approval"). The count comes from `GET /admin/twitch/channels` when an admin loads the page and again whenever the Approved streamers list loads (after Approve or Reject). With nothing waiting, or when the request fails, there is no badge. See `features/reference/admin-enhancements.md`.

## Password re-entry prompt

Destructive actions (End Season, Reset Season, league data purge, every Database Backups action, Promote/Demote admin, Grant tokens) and, since issue #167, the other token-economy and broadcast actions (create or delete a promo code, create or delete a token grant event, create or delete a notification, Toggle tester) need the admin's password again if it was not confirmed on this device in the last 10 minutes. The server answers 403 `reauth_required`; `adminFetch()` then opens an in-page **Confirm your password** modal (password field, **Confirm** and **Cancel**, never a browser `confirm()`/`prompt()`). Confirm calls `POST /reauth` (Enter in the field does the same; the field is the `#reauthForm` form, with a hidden username, so password managers fill it, see `features/reference/password-manager-autofill.md`); on success the modal closes and the action is retried once. A wrong password shows the error in the modal's status line and keeps it open. Cancel (or Escape, or a backdrop click) closes it and the action reports the 403 in its usual status line. The modal stacks above the Season Reset confirmation. Token grants and Delete (Twitch viewer) need it too (issue #150).

An admin account without a password (created through Steam, issue #150) sees **Confirm with Steam** instead of the password field: a note that the action needs a fresh sign-in, a **Confirm with Steam** button and **Cancel**. The same modal switches to this view if `POST /reauth` answers 409 `use_steam_reauth`. An admin with a password and a linked Steam account (in a Steam login mode) sees the password field plus **Confirm with Steam instead** (issue #213).

Confirm with Steam opens the Steam check in a small popup window (`return_tab=popup`); the Admin page and any open dialog (End Season, Mark champions, a notification text) stay as they are. When Steam confirms, the popup closes, the modal closes and the action is retried once. Otherwise the popup closes and the modal shows the reason, e.g. "That Steam account is not the one linked to this account. Nothing was confirmed."; nothing is retried. Closing the popup early counts as not confirmed: the modal closes and the action reports the 403. If the browser blocks the popup, the modal says "Your browser blocked the Steam window" with **Continue on this page**, which navigates to `GET /auth/steam/start?purpose=reauth&return_tab=admin`; Steam then returns to the Admin tab, whose status line at the top reads "Confirmed with Steam. Repeat the action to continue." (or the failure message). If Steam can't work on this server (`GET /config` `steam_reauth_available` false), the modal says "Steam confirmation is unavailable on this server" and opens nothing.

## Typed confirmation

Six destructive actions also ask the admin to type the action's name (issue #150): End Season (`END SEASON`), Reset Season (`RESET SEASON`, typed in the Season Reset modal itself), Promote/Demote admin (`CHANGE ADMIN`), **Grant** tokens (`GRANT TOKENS`), backup **Download** (`DOWNLOAD BACKUP`) and **Delete** on a Twitch viewer account (`DELETE USER`). A **Confirm action** modal (`#typedConfirmModal`) shows what will happen, "Type {PHRASE} to confirm", a text field, a red **Confirm** and **Cancel**. A wrong phrase shows "Type "{PHRASE}" to confirm." in the modal and keeps it open; case does not matter. Cancel, Escape or a backdrop click does nothing. The password prompt (when needed) opens after this modal. See `features/reference/steam-login.md`.

## Ingest League panel

- Input field for an OpenDota league ID.
- **Ingest** button — fetches all matches for that league from OpenDota, calculates fantasy points, seeds player cards into the deck, and enriches player profiles with names and avatars. Safe to re-run; already-stored matches are skipped.

## Refresh Schedule Cache panel

- **Refresh** button — busts the in-memory schedule cache and re-fetches the Google Sheets CSV. Use after the sheet is updated between match weeks.

## Recalculate Fantasy Points panel

- **Recalculate** button — re-applies the current scoring weights to all stored player match stats without re-fetching from OpenDota, then rebuilds every stored per-match card point (`card_match_points`). The response includes `recalculated` (stat rows) and `card_points` (stored card-point rows written), and the status line shows both counts. If the card-point rebuild fails, the recalculated stats are kept, the previous card points stay, and the status line shows the error. Use after adjusting weights.

## Player Management: Add and Bulk add (issue 214)

OpenDota id inputs here and in Mark champions, Add accolade, End Season and Add league are text fields with a numeric keyboard (`inputmode="numeric"`), never number spinners. A non-digit id shows "OpenDota ids are digits only" and sends nothing.

- **Add player**: leaving the id field (or pressing Enter) looks the id up (`GET /admin/players/lookup`) and shows under it "Glete · not in the pool" (green), "Glete · already in the pool" (amber) or "No OpenDota player with this id" (red). **Confirm** adds the id as before (`POST /admin/players`) whatever the preview says.
- **Bulk add**: ids separated by commas, spaces or new lines, at most 50. **Preview** (or Enter) lists each id with its name and status: new, already in pool, not found. **Add N players** sends only the new ids to `POST /admin/players/bulk`, and the progress list then shows each id as it is processed. Changing the ids clears the preview; with no new ids the button is disabled and the status line reads "No new players to add".

## Player Management: champions and accolades (issue #50)

- **Mark champions** and **Add accolade** buttons sit next to **Add**. Each pool row shows the player's titles as chips beside the name (pips at phone width).
- **Mark champions** modal: **From this season** (the current season, a division, and a team whose players for the season fill the roster) or **Past season** (Season 1 to the last ended season, a typed team name, players by OpenDota id). One editable roster: OpenDota id, name and **Remove** on one line per row (the name field takes the remaining width; the modal is up to 720 px wide and rows stack below 640 px), and **+ Add player**. The paste box was removed in issue 214. Typing an id fills the name from the pool or earlier accolades. A note reads "5 players", or "6 players (usually 5)" for another count. Ids must be positive whole numbers listed once, and every row needs a name. **Save champions** replaces that season and division's champions with the list shown.
- **Add accolade** modal: season, kind (Most Points, Best Average, Best Single Match, Fantasy Winner, Played), a player (OpenDota id and name) or a username for Fantasy Winner, an optional value (`inputmode="decimal"`, no spinner); Played takes several "`<id> <name>`" lines.
- **Champions and accolades** table under the pool: Season, Title (chip), Winner, Value, Source, **Edit** and **Remove**. A season and division's champions are one row, "[Team] · N players": Edit opens Mark champions filled in, Remove clears the set after a confirmation. Saves need the password re-entry prompt. See `markdown/features/reference/season-winners-and-holo-cards.md`.

## Season Lifecycle: End Season dialog (issue #50)

**End Season (Archive)** opens a dialog: the season label (the typed one, else the current season), the four awards with their winners and values, the Played count, and a Div 1 and a Div 2 winner picker. Picking a team ticks the players who played for it this season; a stand-in can be unticked and a player added by OpenDota id. With no champion picked the dialog warns "No champions recorded; add them in Player management". **Continue to END SEASON** opens the typed confirmation.

## Settings tab (issue 214)

Six sections, each a heading with its panels: **Season** (League Management, Refresh Schedule Cache, Season Lifecycle), **Scoring** (Scoring Weights, Recalculate Fantasy Points), **Tokens and rewards** (Promo Codes, Token Grant Events), **Announcements** (Notifications), **Players and tags** (Tag Definitions, Re-enrich Player Profiles) and **Maintenance** (Database Backups, Demo Mode).

- A section nav sits on the left and stays in view while scrolling (sticky); at phone width it becomes a row of chips above the sections. Selecting a section scrolls to it and marks it selected; the browser remembers the last one and Settings opens there next time.
- Every panel has the same header: title, a one-line description and its primary action on the right (Refresh where the panel has no other action).
- Destructive actions are red and last: **Reset Season…** at the bottom of Season Lifecycle, the last panel of Season; **Recalculate** in the last panel of Scoring.
- Panels behave as before; every element id is unchanged.

## Database Backups panel

Settings › Maintenance. See `markdown/features/reference/admin-db-backup.md`.

- Explanatory line: "Backups are stored on the server and deleted automatically after N days. Download a copy before deploying if you need to keep it." — N comes from `retention_days` in `GET /admin/backups` (`DB_BACKUP_RETENTION_DAYS`).
- **Create backup now** — calls `POST /admin/backups`. Disabled while the request is in flight. The status line shows "Created {filename}" or the error detail (e.g. the 60-second cooldown message on 429, or the non-SQLite message on 409). The table reloads only after a successful backup.
- **Refresh** — reloads the table.
- **Table** — columns Filename, Created (browser local time), Size (human-readable, e.g. `1.9 MB`), and a **Download** button per row. It asks for the typed confirmation `DOWNLOAD BACKUP`, then fetches `GET /admin/backups/{filename}?confirm=…` through `adminFetch()` (so it can ask for the password) and saves the file under its own name; errors appear in the panel's status line. Newest first. Shows "No backups yet" when empty. Filenames are HTML-escaped.
- Loading, creating and downloading backups all need a recent password re-entry (see the prompt above), so opening the panel may show the prompt.
- The list loads whenever the Settings admin sub-tab is activated.

## Demo Mode panel

Below Database Backups, only when `GET /config` reports `demo_mode: true` and the logged-in user is an admin (`renderDemoModePanel()`, run from `applyAuthState()`; see `features/reference/demo-mode.md`). Clock (datetime field, **Set Clock**, **Clear Clock**, **Refresh**, and the override / effective-now line) and **Seed Demo Accounts**. The clock is loaded from `GET /admin/demo/clock` when the panel renders; for non-admins and logged-out visitors the panel is not rendered and no `/admin/demo/*` request is made.

## Promo Codes panel

- **Create** — enter a code name (auto-uppercased) and a token amount, optionally **Max uses** (total redemptions across all users) and an **Expires** date and time, then click Create (asks for the password if not confirmed recently). The code can be redeemed by users in the My Team tab.
- **Table** — columns Code, Tokens, Uses ("3" or "3 / 100" with a cap), **Limits** ("Expires …" or "Expired …", "Max N uses", or "—") and a Delete button.

## Token Balances panel (User Management)

- An **account type** select: **Website accounts** (default) or **Twitch viewers** (`GET /users?account_type=full|twitch`). The search box filters the loaded list.
- **Website accounts** lists registered users with their current token balance. After the username: **TESTER** and **ADMIN** badges, then **Steam** and **Twitch** badges when the account has linked Steam or connected Twitch (`steam_linked`, `twitch_identity_shared`; issue #201). No badge means not linked. ADMIN is the role badge used on the leaderboards (`adminBadgeHtml`); TESTER, Steam and Twitch are neutral status badges (`statusBadgeHtml`) with their meaning on hover. See the design system's "States and emphasis" rules (`.claude/skills/README.md`).
- **Adoption summary** (issue #201), above the table in the Website accounts view only: "{N} website accounts · Steam linked {S} ({S/N}%) · Twitch connected {T} ({T/N}%)", counting website accounts without demo accounts, whole-number percentages; "No website accounts yet" when there are none. The search box filters rows, not the totals.
- **Tags** column and **Manage tags**: tags show as role badges (`tagBadgeHtml`), as on the leaderboards. An automatic Caster tag (given to approved streamers, issue #201) shows as "Caster (auto)" with a title saying it follows Approved streamers. In the tag manager it has no **Revoke** button; remove the channel from Approved streamers instead.
- **Twitch viewers** lists soft accounts created by the Twitch panel's Join (issue #157) as "Twitch viewer #{id}", with an "ID SHARED" status badge when the viewer shared their Twitch identity, card count, created and last-seen dates, and tokens. Each row has **Grant** and **Delete** (typed confirmation `DELETE USER`, then `DELETE /admin/users/{id}` after admin re-authentication; deletes the account and all its cards). No password, tag, tester, admin or logout actions. Twitch ids are never shown.
- **Superseded player id claims** (issue #150), below the user table: a short note and a table loaded with the user list from `GET /admin/player-id-claims`: Cleared on (the account whose self-reported player id was cleared), Verified account (the Steam-linked account that has the id now), Player id, When. "None" when empty. Rows are built with `textContent`.
- Each row has a number input and a **Grant** button to add tokens to that user's balance (typed confirmation `GRANT TOKENS` and the password prompt when needed).
- **Promote to admin** / **Demote from admin** asks for the typed confirmation `CHANGE ADMIN`. Demo accounts can't be promoted (the status line shows "Demo accounts can't be admins").
- Each row has a **Force logout** button. After a confirmation prompt it calls `POST /users/{id}/force-logout`, which ends every session of that user; the status line then reads "{username} logged out of every session". Forcing your own logout (the prompt says it includes your own session) returns the page to the logged-out state.

## Twitch tab (issue 214)

Three panels, each with the shared admin panel header (title, one-line note, action on the right), in this order. They load with the user list and again when the tab opens (Approved streamers).

- **Approved streamers** (issue #175), first: Twitch channels that may set match MVPs. A short note and a **Refresh** button; the lists load with the user list from `GET /admin/twitch/channels` (no password needed to view). Three lists, each a table with Channel (Twitch display name and login when known, otherwise "Name unknown"; below it "Account: {username}" for the website account that connected this Twitch channel and gets the Caster tag, or "No linked account", issue #201), Channel id, First seen, Last seen, and Actions:
  - **Waiting for approval**: channels whose broadcaster opened the MVP tool; **Approve** and **Reject**. "No channels are waiting." when empty.
  - **Approved**: channels from `TWITCH_MVP_CHANNEL_IDS` first, with a "from server settings" note and no button, then portal-approved channels with **Remove** (confirmation). "No channels are approved. With ENV=production no channel can set match MVPs." when empty.
  - **Rejected ({n})**: collapsed (`<details>`); **Approve** moves a channel back to approved.
  Approve, Reject and Remove call `POST /admin/twitch/channels/{channel_id}/approve|reject|remove` through `adminFetch` (password prompt when not confirmed in the last 10 minutes); the status line says "{name} can now set match MVPs" or "{name} moved to Rejected", and the lists reload. Names are escaped with `_escHtml`.
- **Twitch status** (issue #180), below Approved streamers: why the Twitch extension may not work. A short note and a **Refresh** button; it loads with the user list from `GET /admin/twitch/status` (admin only, no password needed), and after each load the status line reads "Updated {time}" (an error shows there instead). Three blocks:
  - A checklist table (State, Check, What to do), one row per server setting: `TWITCH_EXTENSION_CLIENT_ID` (with the extension origin CORS allows), `TWITCH_EXTENSION_SECRET` (set and base64; the value and its length are never shown), `TWITCH_EXTENSION_VERSION`, `TWITCH_LOCAL_DEV`, MVP channels (counts from `TWITCH_MVP_CHANNEL_IDS`, approved and waiting), Connect Twitch (`TWITCH_OAUTH_*` and the `cryptography` package), `APP_BASE_URL` and `STEAM_API_KEY`. The State cell reads **OK** (green), **Warning** (amber) or **Problem** (red).
  - **Panel traffic since the last restart**, in the same table form: the last request from the extension (any `/twitch/*` request from an allowed extension origin; when none, the row says the panel is not reaching this server and to check `ebs_url`, the URL Fetching Domains and HTTPS reachability), the last panel request with an accepted token ("3 min ago", or "None since the last restart"), refused tokens by kind (expired, invalid, server not configured) with when the last one happened, and up to five cross-origin hosts refused on `/twitch/*` (host and port only). Anyone can send a bad token or a made-up `Origin`, so these counts and hosts are hints to compare with the checks above, not proof of a fault.
  - **Twitch console**: a table (Check, Expected value) of what only the Twitch developer console can show: URL Fetching Domains contains the backend origin, the global configuration's `ebs_url` is the backend URL, and the installed version was packaged with this backend's origin (expected values from `APP_BASE_URL`); the OAuth Redirect URL list has the exact `TWITCH_OAUTH_REDIRECT_URI` entry ("click Add, then Save Changes"; shown only when Connect Twitch is configured); and the version's Allowlist for Image Domains contains the team logo hosts (their `https://` origins). The Connect Twitch row's text says its client secret is the Twitch API Client Secret, never the Extension Secret.
  Every value is escaped with `_escHtml`. Errors appear in the section's status line. See `features/reference/twitch-integration-status.md`.
- **Twitch collection merges** (issue #160), last: a short note and a **Show recent merges** button in the panel header. It loads `GET /admin/twitch/merges` (admin password re-check) into a table: Website account, Merged (date and time), Moved ("{cards} cards · {tokens} tokens"), and Actions. A reversible merge has a **Reverse** button (confirmation, then `POST /admin/twitch/merges/{log_id}/reverse` with re-check); the status line then reports the cards and tokens returned and any tokens already spent. Merges that can't be reversed show "Reversed" or the reason (older than 30 days, cards gone after a season reset). "No merges in the last 30 days" when empty. Twitch ids are never shown.

## Scoring Weights panel

- Read-only table of all configured weight keys and values (loaded from `GET /weights`).
- Includes scoring stat weights, death formula params (`death_pool`, `death_deduction`), rarity bonuses (`rarity_common` … `rarity_legendary`), and modifier tuning keys (`modifier_count_*`, `modifier_bonus_pct`).
- Operational changes are made outside the UI (typically `WEIGHTS_JSON` overrides merged on startup and/or direct DB edits to the `weights` table), then use **Recalculate** to backfill `player_match_stats.fantasy_points` and rebuild the stored card points if needed. A restart also rebuilds the stored card points automatically when the weights changed (see `features/reference/stored-card-points.md`).

## Matches panel

- **Out-of-week banner** (above the table, hidden when empty): "N series played outside their scheduled week", from `GET /admin/matches/out-of-week`. One line per series: teams, played date, scheduled week, counted week, and two buttons. **Count for Week N** sets the series to its scheduled week; **Keep in Week M** sets an explicit override to the week it counts for now (not shown when it counts in no week). Both send `PUT /matches/{id}/week` with `apply_to_series: true`, then the page reloads and the status line shows the summary below.
- **Add match** (issue 224), next to **Refresh**, opens a dialog for a match played outside the league lobby. Two tabs: **From OpenDota** (first: a match id and **Fetch**) and **From replay** (a `match-<id>.json` file from `scripts/replay_to_match.py`, at most 56 KB, and **Check file**). Fetch or Check file calls `POST /admin/matches/manual/preview`. The preview shows the match id, teams, start time, duration (mm:ss) and winner, a "Partial stats: …" note when the replay lacks stats, an "Already added" note when it would replace an earlier manual match, a count of players outside the season's pool, and the ten players (side, name with a **Not in pool** chip, hero, K/D/A). Below it are **League** (the monitored leagues, "Name (Div 1)"), **Radiant team** and **Dire team** pickers, prefilled when a team name matches. **Add** (disabled until a preview loads) sends `POST /admin/matches/manual` through `adminFetch`, so a stale re-auth opens the confirm popup. A 409 asking to replace an earlier manual match asks for confirmation, then resends with `confirm: true`. Refusals (a league duplicate, "… Use a replay import instead.", too short, a missing team) show in the dialog's status line. On success the dialog closes, the table reloads and the status line reads "Match 8100000001 added as Replay (partial stats: teamfight_participation)". See `markdown/features/reference/matches-outside-the-league.md`.
- **Filters** in one row (issue 214), combined: **MVP missing** (checked on the first load when any match lacks an MVP), **League** (All, Div 1, Div 2), **Unparseable only** and **Manual only** (issue 224: matches added from OpenDota or a replay). A count reads "12 matches" or "3 of 12 matches". When nothing passes, the empty state names the active filters ("No matches for the filters: MVP missing, Div 2").
- **Grouped by series**: a header row per schedule-feed series, "Reds vs Blues · Div 1 · Week 4 · Stream ↗", newest series first, with its games below in play order. Each game shows the series' team 1 vs team 2 in the same order in every game, not radiant/dire. Matches the feed doesn't know are listed under **Not in the schedule**.
- Table columns: Match (OpenDota link, plus a **Manual** or **Replay** chip for a match added through Add match, whose tooltip reads "Added by <admin>, <time>"), Teams, League (league name · Div 1/Div 2), Start, MVP (name and **Set MVP**), Stream (the series' stream link from the feed, opening in a new tab; "—" when none), **Week**, **Scoring**, **Parse**, **Live seen**, **Stats in**, **MVP picked**, and **More**.
- **More** opens a details row under the game with the VOD link editor (the caster VOD the Weekly Report shows; **Save** sends `PATCH /admin/matches/{id}/vod`) and the exact Live seen, Stats in and MVP picked times.
- **Live seen**, **Stats in** and **MVP picked** show when the match was first seen live, when its stats were ingested and when its MVP was first confirmed in the Twitch extension, each as minutes after Start Time ("+2 min", "+58 min"; a negative value when it came before the start). Hovering a value shows the exact time. Unknown values show "—": a dash under Live seen means live detection missed the match. See `markdown/features/reference/mvp-selection-delays.md`.
- **Parse** shows Parsed, Unparsed or Unparseable (a dash for matches with no status). Unparsed rows (except replay matches, which are never re-fetched) have a **Retry parse** button (`POST /admin/matches/{id}/retry-parse`). After it finishes, the table reloads and the status line says whether the match was refreshed with parsed stats, a parse was requested, the request was on cooldown, or OpenDota rejected it. A 409 appears in the status line while an ingest is running.
- **Scoring** has two checkboxes, **Unparseable** and **Not scored**, aligned in a two-column grid (checkbox, label). Each change sends `PATCH /admin/matches/{id}/scoring` with that single field, then the table reloads. On error, the checkbox reverts and the status line shows the error.
- **Week** shows the scoring week: "Week 4" by time, "Week 4 (set)" for an override, "—" when no week contains the match. Below it, a picker offers **By time (Week N)** (clears the override) and every fantasy week label. Choosing one asks for confirmation naming the series' game count ("Count 2 games for Week 4?"; a series is the same two teams within 6 hours), then sends `PUT /matches/{id}/week` with `apply_to_series: true`. The table reloads and the status line reads, for example, "2 games updated; Week 4: substitutions re-run (3)". Cancelling restores the previous choice. See `markdown/features/core/weeks.md#week-override`.
- See `markdown/features/reference/unparseable-match-handling.md`.

## Week Management panel

- Form to create a week (label, start date, end date in `pp.kk.vvvv` format with a calendar picker), with **Create** and **Refresh** buttons.
- Table columns: Label, Start, End, Locked, Rosters, and an unlabelled action column. **Rosters** is the number of active roster cards snapshotted at lock (saved bench cards are not counted).
- Unlocked weeks are edited inline (label and dates) and saved with **Save Changes**; each has a **Delete** button with an inline confirmation row.
- Locked weeks are read-only. Once a locked week is past its substitution time (`end_time + SUBSTITUTION_DELAY_HOURS`), its action cell has a **Re-run substitutions** button. It calls `POST /admin/weeks/{id}/substitutions` through `adminFetch` (no password re-entry: the action is not destructive), then the status line reports how many substitutions were made and the table reloads. See `markdown/features/reference/automatic-bench-substitution.md`.
