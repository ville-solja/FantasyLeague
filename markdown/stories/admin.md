# Admin and Operations

## User Management

### Grant Tokens
**User story**
As an admin, I want to manually grant additional tokens to a specific user.

**Acceptance criteria**
- Admin can select any user and grant a specified number of tokens
- Token balance updates immediately
- Logged in the audit log with admin actor, target user, and amount

---

### Tester Account Flag
**User story**
As an admin, I want to mark any account as a tester so that it is excluded from public leaderboards.

**Acceptance criteria**
- The admin user list shows an "is tester" indicator for each account
- A toggle button next to each user switches `is_tester` on or off and gives inline confirmation
- Tester accounts are excluded from `GET /leaderboard/season` and `GET /leaderboard/weekly`
- Tester accounts remain visible (with a visual marker) in the admin users panel

---

## Promo Codes

### Generate Promo Codes
**User story**
As an admin, I want to create promo codes that grant tokens to users who redeem them.

**Acceptance criteria**
- Admin creates codes with a configurable token amount
- Each user can only redeem a given code once
- Admin can delete codes

---

## Scoring and Data

### Configure Scoring Weights
**User story**
As an admin, I want to configure the scoring weights for match stats.

**Acceptance criteria**
- Weights are stored in the database (`weights` table) and surfaced read-only in the Admin tab (`GET /weights`)
- Default values come from `backend/seed.py` (`DEFAULT_WEIGHTS`); optional startup overrides via `WEIGHTS_JSON` merge into DB on restart
- Tunables include per-stat weights for the scoring stat set (`kills`, `last_hits`, `denies`, `gold_per_min`, `obs_placed`, `towers_killed`, `roshan_kills`, `teamfight_participation`, `camps_stacked`, `rune_pickups`, `firstblood_claimed`, `stuns`), death formula params (`death_pool`, `death_deduction`), rarity bonuses (`rarity_*`), modifier tuning (`modifier_count_*`, `modifier_bonus_pct`), and MVP bonus (`mvp_bonus_pct`)
- Rarity modifier percentages are also configurable (same weight system)
- Changing DB weights affects scoring going forward; use **Recalculate** to recompute stored `player_match_stats.fantasy_points` (and downstream card/week totals) from the same stored raw stats

---

### Recalculate Fantasy Points
**User story**
As an admin, I want to recalculate all historical fantasy points using the current scoring weights.

**Acceptance criteria**
- Recalculate button applies the current weights to all stored player-match stats
- Does not require re-fetching data from OpenDota
- Result shows the number of records updated
- Logged in the audit log

---

### Manual League Ingestion
**User story**
As an admin, I want to trigger data ingestion for a specific league at any time.

**Acceptance criteria**
- Admin can enter a league ID and trigger ingestion from the admin tab
- Ingestion fetches new matches, calculates fantasy points, seeds player cards, and enriches player profiles
- Already-stored matches are skipped (idempotent)
- Logged in the audit log

---

### Schedule Refresh
**User story**
As an admin, I want to force a refresh of the season schedule from the Google Sheet source.

**Acceptance criteria**
- Refresh button busts the in-memory schedule cache
- Fresh data is fetched immediately from the configured Google Sheets CSV URL
- Logged in the audit log

---

## Security and Integrity

### Server-side Validation
**Acceptance criteria**
- All state-changing actions (draw, activate, admin ops) are validated server-side
- Client-side `is_admin` flag alone is not sufficient — every admin endpoint re-verifies from the session
- Roster endpoint returns 403 if a user attempts to view another user's roster

---

### Audit Logs
**User story**
As an admin, I want visibility into actions that have taken place on the app.

**Acceptance criteria**
- Tracks (non-exhaustive, current server actions): `user_register`, `user_login`, `password_reset_requested`, `token_draw`, `reroll_modifiers`, `token_redeem`, `admin_ingest`, `admin_recalculate`, `admin_schedule_refresh`, `admin_grant_tokens`, `admin_toggle_tester`, `admin_enrich_profiles`, `admin_set_match_week`, `admin_sync_match_weeks`, `admin_sync_toornament`, `admin_code_create`, `admin_code_delete`, `twitch_mvp_set`, `twitch_token_drop`
- Each entry includes timestamp, actor username, action type, and a detail string
- Visible in the Admin tab with most recent entries first
- Admin-only access

---

## Observability

### Build Version Display
**User story**
As a user reporting a bug, I want to see a faint version identifier on every page so that I can include the exact build in my report.

**Acceptance criteria**
- A version string is visible on every page in a small, low-contrast style
- Present regardless of login state
- Setting only `APP_VERSION` (image SHA) displays that value alone; setting both `APP_VERSION` and `APP_RELEASE` displays both (e.g. `v1.2.0 · b06e0c4`)
- Value is injected by CI as a Docker build argument and served via `/config`

---

## Token Grant Events

### Create a Token Grant Event
**User story**
As an admin, I want to configure a one-time token grant event with a fixed amount and
active time window so that all players are automatically rewarded on their next login
during that period.

**Acceptance criteria**
- Admin tab shows a "Token Grant Events" section listing active and upcoming events
- A form accepts: token amount (integer ≥ 1), start datetime, end datetime
- Submitting calls `POST /admin/token-grant-events` and the new event appears in the list
- Validation rejects end time ≤ start time and amount < 1
- Event is logged to the audit log as `admin_token_grant_event_created`

---

### Claim Tokens on Login During Active Event
**User story**
As a player, I want to automatically receive my event tokens on my next page load during
an active grant window so that I do not need to take any extra action.

**Acceptance criteria**
- On any authenticated request during an active event, the backend checks whether the
  player has already claimed this event
- If not yet claimed, tokens are added and the claim is recorded
- Tokens are granted at most once per player per event regardless of how many requests
  are made during the window
- No tokens are granted for requests after the event's end time
- The grant is logged to the audit log as `token_grant_event_claim`

---

### Remove a Token Grant Event
**User story**
As an admin, I want to remove a configured grant event (including a live one) so that I
can cancel a mistaken configuration without penalising players who have already claimed.

**Acceptance criteria**
- Each event row has a "Remove" button that calls `DELETE /admin/token-grant-events/{id}`
- Removing a live event immediately stops new claims; already-granted tokens are kept
- The removal is logged to the audit log as `admin_token_grant_event_deleted`
- Removed events disappear from the admin list

## Notification System

### View a Notification on Login
**User story**
As a logged-in player, I want to see an admin broadcast message once when I open the
app during the active window, so that I stay informed about important announcements.

**Acceptance criteria**
- A popup appears on page load if there is at least one active notification the player has not yet dismissed
- The popup shows the notification message and a close/dismiss button
- Dismissing the popup marks the notification as seen; it does not reappear on subsequent page loads or logins during the same window
- Players who first open the app after the notification window has ended never see it
- Players who are not logged in do not see the popup

### Create and Manage Notifications (Admin)
**User story**
As an admin, I want to create a notification with a message, start time, and end time,
and be able to remove it before it expires, so that I can control what players see.

**Acceptance criteria**
- Admin panel shows a list of all notifications with message, window, and dismiss count
- Admin can create a notification: message (required, ≤ 500 chars), start\_time, end\_time
- `end_time` must be strictly after `start_time`; invalid input is rejected with a clear error
- Admin can delete a notification at any time; deletion stops future dismissals but does not undo existing ones
- Deleting a non-existent notification returns 404

## Admin Week Management

### View All Weeks
**User story**
As an admin, I want to see all week records in a table so that I can understand the
current season structure at a glance.

**Acceptance criteria**
- Admin panel shows all weeks with label, start time, end time, locked status, and roster snapshot count
- Locked weeks are visually distinguished
- All weeks are visible including past locked ones

### Create a Custom Week
**User story**
As an admin, I want to create a week with a specific label, start time, and end time so
that tournament rounds with irregular schedules fit into the season.

**Acceptance criteria**
- Admin can submit label, start\_time, and end\_time
- `end_time` must be strictly after `start_time`; invalid input is rejected with a clear error
- The new week appears in the table immediately and is logged to the audit log

### Edit an Unlocked Week
**User story**
As an admin, I want to change the end time (and optionally label or start time) of an
unlocked week so that the lock deadline matches the actual tournament schedule.

**Acceptance criteria**
- Editing is only allowed when `is_locked = false`
- Admin can update label, start\_time, and/or end\_time
- `end_time` must remain strictly after `start_time` after the edit
- Changes are saved immediately and logged to the audit log

### Delete an Unlocked Week
**User story**
As an admin, I want to delete an unlocked week that has no roster entries so that
auto-generated placeholder weeks can be removed when the schedule changes.

**Acceptance criteria**
- Delete is only allowed when `is_locked = false` and roster entry count is 0
- Attempting to delete a locked week returns 409
- Attempting to delete a week with roster entries returns 409
- Deletion is logged to the audit log

## Env-Based Admin Seeding

### Configure the Admin Account via Environment Variables
**User story**
As an operator deploying the app, I want to set admin credentials through environment
variables so that no real password is ever committed to the repository.

**Acceptance criteria**
- If `SEED_ADMIN_USERNAME`, `SEED_ADMIN_EMAIL`, and `SEED_ADMIN_PASSWORD` are all set,
  a user with `is_admin=true` is created at startup if no user with that email already exists
- If the env vars are absent or empty, no admin account is auto-created (no crash, no warning)
- The `backend/seed/users.json` file is replaced with a safe, empty-array stub (`[]`) so
  the seeding code path remains exercisable in tests without committing real passwords
- The old `seed_users()` function still works for local dev if a non-empty `users.json` is
  placed on disk (the file is `.gitignore`d except for the stub)
- `.env.example` documents all three new variables

### Prevent Accidental Credential Leakage in CI
**User story**
As a developer, I want the CI test suite to work without real admin credentials in the
environment so that test runs do not depend on secrets.

**Acceptance criteria**
- `pytest` passes with `users.json` set to `[]` and no `SEED_ADMIN_*` env vars set
- No test hard-codes the admin username or password from the old `users.json`

## Player Pool Management

### Manage the Player Pool
**User story**
As an admin, I want to view and manage the known player pool so that I can control which
players are available for card draws.

**Acceptance criteria**
- Admin tab shows a "Player Pool" section listing all players with name, OpenDota ID, and
  the number of active cards held by users
- Rows are selectable via checkboxes
- A "Remove Selected" button is inactive until at least one row is checked

---

### Add a Player by OpenDota ID
**User story**
As an admin, I want to add a player to the pool by entering their OpenDota account ID, so
that new players can be included in card draws without a full data ingest.

**Acceptance criteria**
- An "Add Player" button opens a popup with an ID input, a Close button, and a Confirm button
- On Confirm, the backend validates the ID against OpenDota and fetches the player's name
  and avatar URL
- If the ID does not resolve on OpenDota, a clear error is shown and the player is not added
- If the player already exists in the pool (active or inactive), the endpoint returns a
  clear error and does not create a duplicate
- On success, the player is marked active and appears in the table immediately
- The action is logged to the audit log as `admin_player_added`

---

### Bulk Add Players via CSV
**User story**
As an admin, I want to paste a comma-separated list of OpenDota account IDs to add multiple
players at once, so that I can populate the pool at season start without repeated single-add
operations.

**Acceptance criteria**
- A "Bulk Add" button opens a popup with a single-line CSV text input and a Confirm button
- On Confirm, the backend processes each ID: valid new IDs are added; invalid or already-present
  IDs are skipped
- The response reports how many were added and lists skipped IDs with reasons
- The bulk add action is logged to the audit log as `admin_player_bulk_added`

---

### Remove Players with Token Refund
**User story**
As an admin, I want to remove selected players from the pool (with a confirmation step) so
that players who leave the league are excluded from future draws and card holders are
automatically compensated.

**Acceptance criteria**
- Clicking "Remove Selected" opens a confirmation popup listing the selected player names
- On Confirm, the backend sets `is_active = false` on each selected `Player` row (soft delete)
- All `Card` rows belonging to any user that reference a removed player are set to
  `is_active = false`
- Each user who loses one or more cards receives 1 token per deactivated card as a refund,
  applied immediately
- Historical `player_match_stats` rows are left unchanged
- Each removal is logged as `admin_player_removed`; each refund batch as
  `admin_player_refund_issued`
- Removing a player who has no active card holders completes silently

---

### Receive a Refund Token
**User story**
As a player, I want to automatically receive a token when an admin removes a player whose
card I hold, so that I can draw a replacement without losing my token investment.

**Acceptance criteria**
- Token balance increases by 1 for each card held that belongs to a removed player
- The refund is applied at the moment the admin confirms the removal
- Deactivated cards are no longer shown as drawable or activatable, but may still appear
  in historical views
- No notification popup is triggered; the token balance update alone is sufficient

## Admin Tab Navigation and MVP Match View

### Admin Tab Navigation
**User story**
As an admin, I want the admin panel organised into named tabs so that I can navigate directly
to the management area I need without scrolling through every section.

**Acceptance criteria**
- Admin panel shows a tab bar with five tabs: Week Management, Player Pool, Audit Log,
  Settings (League management + Token Balances + Tag Definitions), and Matches
- Clicking a tab shows only that tab's content; all other sections are hidden
- The active tab is visually highlighted
- Tab selection is preserved within the page session (switching away and back remembers the
  active tab)
- Non-admin users never see the tab navigation

---

### Admin Match Table
**User story**
As an admin, I want to view all ingested matches in a table so that I have a complete
picture of the data that has been imported from OpenDota.

**Acceptance criteria**
- Matches tab shows a table with columns: League, Series ID, Team 1, Team 2, Start Time,
  Duration, MVP
- Matches are ordered by start time descending (most recent first)
- The MVP column shows the current MVP player name, or "—" if no MVP has been set
- The table loads from `GET /admin/matches`

---

### Admin MVP Selection
**User story**
As an admin, I want to set the MVP for any match from the admin panel so that MVP bonuses
can be applied even when a Twitch broadcaster session is unavailable.

**Acceptance criteria**
- Each match row has a "Set MVP" button
- Clicking the button opens a selection UI listing the 10 players who participated in that match
- Selecting a player and confirming calls `POST /admin/matches/{match_id}/mvp`
- The MVP column updates immediately to reflect the new selection
- The action is logged to the audit log as `admin_set_mvp`
- Setting MVP via the admin panel uses the same `twitch_mvp` table row as the Twitch broadcaster flow
