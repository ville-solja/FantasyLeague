# Admin Features

Admin users have access to a set of management endpoints not available to regular users. An admin is identified by the `is_admin` flag on their `User` record. The initial admin account (and optionally further admins) is bootstrapped at startup via the `SEED_ADMIN_USERNAME`/`SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` environment variables and their `_2`, `_3`, ... suffixed counterparts (see `reference/env-based-admin-seeding.md`). Additional admins can also be promoted in-app by an existing admin via the User Management tab's admin toggle, with no DB access required.

All admin endpoints require an active admin session. Unauthorized requests receive a 403 response.

Admin sessions are short: 2 hours idle and 12 hours from login by default
(`ADMIN_SESSION_IDLE_SECONDS`, `ADMIN_SESSION_ABSOLUTE_SECONDS`; issue #117, see
`reference/longer-sessions.md`).

### Re-authentication for destructive actions

These endpoints also need a password re-entry (`POST /reauth`, see `core/auth.md`) on the same
session within `ADMIN_REAUTH_SECONDS` (default 600, 10 minutes); otherwise they return 403
`{"detail": "reauth_required"}` and do nothing:

- `POST /admin/season/end` and `POST /admin/season/reset`
- `DELETE /admin/leagues/{league_id}/data`
- `POST /admin/backups`, `GET /admin/backups` and `GET /admin/backups/{filename}`
- `POST /users/{user_id}/toggle-admin`
- `DELETE /admin/users/{user_id}` (Twitch viewer soft accounts, issue #157)
- Issue #167, the token economy and the site-wide broadcast: `POST /grant-tokens`, `POST /codes`,
  `DELETE /codes/{code_id}`, `POST /admin/token-grant-events`,
  `DELETE /admin/token-grant-events/{event_id}`, `POST /admin/notifications`,
  `DELETE /admin/notifications/{notification_id}` and `POST /users/{user_id}/toggle-tester`
  (it hides a user from every leaderboard)

The check is the `require_recent_reauth` dependency (`backend/deps.py`), added at route level so
the endpoint functions themselves are unchanged. In the admin panel these calls go through
`adminFetch()` (`frontend/app-admin.js`), which shows an in-page password prompt on
`reauth_required`, calls `POST /reauth`, and retries the action once. All other admin endpoints
work without re-authentication.

**Support rule (issue #167).** Admins never grant tokens or cards, move accounts or change account
details because someone asks in chat or a DM, however urgent or official it sounds. Lost items
are restored only from what the audit log shows. A request that pushes for an exception is
treated as a social-engineering attempt and mentioned to the other admins.

---

## User Management

### `GET /users?account_type=full|twitch|all`
Returns the user list, filtered by account type (issue #157): `full` (website accounts, the
default), `twitch` (Twitch viewer soft accounts created by the panel's Join) or `all`. Any other
value returns 422. Each entry contains `id`, `username`, `account_type`, `tokens`, `card_count`,
`created_at`, `last_seen_at`, `twitch_linked`, `twitch_identity_shared`, `is_tester`, `is_admin`,
and `tags` (array of `{id, key, label}` objects for admin-granted tags; empty array if none).
`username` is the user's display name: a soft account has no username and shows as
`Twitch viewer #{id}`. `twitch_linked` and `twitch_identity_shared` are booleans; the Twitch ids
themselves are never returned. The admin search box filters the loaded list, so soft accounts
only appear under the **Twitch viewers** filter. See
`reference/twitch-extension-policy-compliance.md`.

### `DELETE /admin/users/{user_id}`
Deletes a Twitch viewer soft account and every row it owns (cards, modifiers, stored card
points, roster entries, per-user state, presence) through `soft_accounts.delete_soft_account`.
Requires re-authentication. Website accounts cannot be deleted here (409); unknown ids return
404. Returns `{ deleted: true, user_id }`. Logged as `twitch_soft_account_deleted` with
`reason=admin`.

### `POST /users/{user_id}/toggle-tester`
Flips the `is_tester` flag for the given user. Tester accounts are excluded from all leaderboards (season and weekly) while remaining fully visible in the admin panel. Returns `{ user_id, username, is_tester }`. Logged as `admin_toggle_tester`. Requires a recent re-authentication (issue #167).

### `POST /users/{user_id}/toggle-admin`
Flips the `is_admin` flag for the given user. Returns `{ user_id, username, is_admin }`. Logged
as `admin_toggle_admin`. Requires a recent re-authentication (see above). Deletes all of the
target's sessions, so their next login gets a new session ID and the limits of the new role. Two guards prevent the app from ever ending up with zero admins: an
admin cannot toggle their own admin status (409 `"Cannot change your own admin status"`), and
the last remaining admin cannot be demoted (409 `"Cannot demote the last remaining admin"`).
Admin status is read from the database on every request (`get_current_user` and
`require_admin` in `backend/deps.py`), so a promotion or demotion takes effect on the very next
request. The frontend's Admin tab visibility (`activeIsAdmin`) comes from `GET /me`, which runs
on each page load, so it updates on the next reload.

### `POST /users/{user_id}/force-logout`
Ends every session of the given user by deleting their `user_sessions` rows (see
`core/auth.md`, Session Validation and Revocation). Returns `{ user_id, username }`. Logged as
`admin_force_logout` with the target's username and id in the detail. 404 for an unknown user,
403 for a non-admin. An admin may force their own logout, which ends their own sessions too.

### `POST /grant-tokens`
Grants a configurable number of tokens to a specific user.

```json
{ "target_user_id": 5, "amount": 3 }
```

Amount must be between 1 and 10,000 — the endpoint returns 422 for values outside that range. All grants are recorded in the audit log. Requires a recent re-authentication (issue #167).

---

## Token Distribution: Redeemable Codes

Redeemable codes allow token grants to be distributed without per-user admin action. Each code can be redeemed once per user. Codes are not restricted to promotional use — they can serve any purpose (event rewards, onboarding, giveaways, etc.).

### `POST /codes`
Creates a new redeemable code.
```json
{ "code": "LAUNCH2026", "token_amount": 5, "expires_at": 1767225600, "max_redemptions": 100 }
```
Codes are stored uppercased. Duplicate codes return 409. `expires_at` (Unix time) and
`max_redemptions` (total redemptions across all users, at least 1) are optional (issue #167,
migration `033_promo_codes_limits`); an expiry in the past returns 422. Requires a recent
re-authentication. The admin panel has optional "Max uses" and "Expires" fields.

### `GET /codes`
Lists all created codes with their redemption counts, `expires_at` and `max_redemptions`; the
admin panel shows them in a Limits column.

### `DELETE /codes/{code_id}`
Deletes a code. Users who already redeemed it keep their tokens.

### `POST /redeem` *(user-facing)*
Regular users redeem a code via this endpoint. Returns the number of tokens granted.
```json
{ "code": "LAUNCH2026" }
```
Limited to 5 requests a minute per user (`RATE_LIMIT_REDEEM`), so codes cannot be guessed by
brute force; the next request returns 429. An unknown, expired or used-up code all return 404
`"Invalid or expired code"`, so a code's existence can't be probed (issue #167); a code this user
already redeemed returns 409. Two simultaneous redemptions of a code's last use can both succeed,
so `max_redemptions` can be exceeded by one.

---

## Scoring Weights

### `GET /weights`
Returns all scoring weight keys, labels, and current values. Available to all users (used to display weights in the UI).

### Changing weights
Weights are configured via the `WEIGHTS_JSON` environment variable (a JSON object mapping weight keys to float values). Changes take effect on the next container restart, which also rebuilds the stored card points when the weights differ from the last build ([Stored Card Points](../reference/stored-card-points.md)). See `commands.md` for the full variable reference and `seed.py` for the list of all weight keys and their defaults.

### `POST /recalculate`
Recalculates fantasy points for every `PlayerMatchStats` row using the current weights, then rebuilds every stored card point row (`card_match_points`). Returns `{"status": "ok", "recalculated": <stat rows>, "card_points": <stored rows written>}`. Run this after changing weights to update historical scores. Takes several seconds on large datasets.

---

## Match & Week Management

### `PUT /matches/{match_id}/week`
Manually assigns a match to a specific fantasy week, overriding the week derived from its `start_time`. Used when a match is played outside its scheduled week.
```json
{ "week_id": 3 }
```
Set `week_id` to `null` to clear the override.

### `POST /admin/sync-match-weeks`
Automatically bulk-assigns `week_override_id` for all matches based on the configured schedule source. Uses a ±3-day proximity window to map each scheduled series to the closest actual matches played between those two teams. Clears overrides for matches already in the correct week. Returns a summary of changes and errors.

---

## Player Profile Enrichment

### `POST /admin/enrich-profiles`
Triggers a synchronous enrichment batch for players whose profile facts are missing or stale. Enrichment runs automatically in the background (see `reference/player-profile-enrichment.md`); this endpoint forces an immediate pass. Returns `{ "enriched": N, "skipped": M, "errors": K }`. Logged as `admin_enrich_profiles`.

---

## Data Ingest

### `POST /ingest/league/{league_id}`
Starts a full ingest cycle for the specified OpenDota league ID in a background thread and
returns immediately with `{"status": "started", "league_id": ...}` — a full ingest can take
minutes under OpenDota's rate limit, so the request no longer blocks for that long. The
background job:
1. Fetches all match IDs from OpenDota
2. Ingests new matches and player stats
3. Refreshes Dotabuff team logos
4. Runs `run_enrichment()` — a name/avatar backfill only, not the AI-driven profile enrichment
   (facts + bio). That separate pass (`run_profile_enrichment()`) only runs via
   `POST /admin/enrich-profiles` or the background loop — see `reference/player-profile-enrichment.md`.

The `admin_ingest` audit log entry is written once the background job finishes, not when the
endpoint returns. A shared lock (`ingest.INGEST_LOCK`) prevents this from ever running
concurrently with the automatic ingest poll loop; calling it while a run (manual or automatic)
is already in progress returns 409.

Note: card generation was removed from the ingest pipeline. Cards are now created dynamically at draw time.

Ingest also runs automatically every 15 minutes in the background (`INGEST_POLL_INTERVAL`), or
every 2 minutes (`INGEST_LIVE_POLL_INTERVAL`) while any week is currently active, so live-series
results land faster during play. The manual endpoint is useful immediately after new matches are
played. See `reference/toornament.md`.

### `POST /ingest/retry-unparsed?max_age_hours=<int>`
Re-checks recently ingested matches whose stats were stored before OpenDota parsed the replay
(all-zero teamfight/stun/ward stats), replaces their stat rows once a parsed version exists, and
asks OpenDota to parse the rest. Runs in a background thread and returns
`{"status": "started", "max_age_hours": ...}` immediately; 409 if any ingest is already
running (same `ingest.INGEST_LOCK`). The optional `max_age_hours` (1–8760) widens the default
`INGEST_PARSE_RETRY_HOURS` window for a one-off backfill. The `parse_retry_triggered` audit row
is written at trigger time; the run's counts go to the server log. Matches marked `unparseable`
are skipped. After the first poll following the `027_match_parse_status` deploy, every historical
signature-zero match older than the window is flagged `unparseable`, so a wide manual backfill
no longer re-checks those matches. Clear the flag, or use the Matches tab's Retry parse, to retry
one. See `reference/opendota-parse-retry.md` and `reference/unparseable-match-handling.md`.

---

## Schedule

The fixture list has two possible sources: a structured JSON feed (`SCHEDULE_FIXTURES_URL`, preferred when set) or the legacy Google Sheets CSV (`SCHEDULE_SHEET_URL`, the fallback). Both are parsed into the same shape, so everything downstream is source-agnostic. See [Schedule Fixtures API Source](../reference/schedule-fixtures-api.md).

### `GET /schedule`
Returns the current season fixture list from the active source (cached for 1 hour). No authentication required. Used by the Schedule tab. The response includes a top-level `source` field (`"fixtures_json"` | `"sheet_csv"`); JSON-sourced series also carry a `scheduled` boolean. Two fields are added on every request and never cached: `live` (team pairs with a game in progress, from `live_matches`) and `fantasy_weeks` (the admin weeks, ordered by start time). See [Schedule Visuals](../reference/schedule-visuals.md).

### `POST /schedule/refresh`
Clears the 1-hour schedule cache, forcing the next `GET /schedule` request to re-fetch from the active source. Returns the same shape as `GET /schedule`, including `live` and `fantasy_weeks`.

### `GET /schedule/debug`
Returns detailed schedule parsing information for troubleshooting. Reports the active `source`. For the CSV source: team-name mapping and row parsing details. For the JSON feed: HTTP `status_code`/`content_type`, the feed's `season`/`count`, `weeks_parsed`, and `fixtures_dropped` (fixtures with a missing/unknown `week` or `division`), or a clear `error` string on a bad response.

---

## Toornament Sync

### `POST /admin/sync-toornament`
Pushes current series results from the database to toornament.com. Idempotent — matches that already have the correct score in toornament are skipped. Returns:
```json
{ "pushed": 3, "skipped": 12, "errors": [] }
```
Also runs automatically after each ingest poll cycle. Requires `TOORNAMENT_*` environment variables to be set.

---

## Audit Log

### `GET /audit-logs?limit=200`
Returns the most recent audit log entries, newest first. `limit` defaults to 200 and must be
between 1 and 1,000 (422 otherwise). The Audit Log tab escapes `action` and `detail` before
rendering them, since `detail` can carry user-supplied text such as usernames. All significant admin actions are recorded here automatically:

| Action | Trigger |
|---|---|
| `user_register` | New user registration |
| `user_login` | Successful user login |
| `password_reset_requested` | Forgot-password flow issued a single-use password-reset token |
| `password_reset_completed` | User completed a password reset via `POST /reset-password` (all their sessions are revoked) |
| `user_logout_everywhere` | User ended all their sessions via `POST /logout-everywhere` |
| `username_changed` | User renamed themselves via `PUT /profile/username` (`detail` has `old=` and `new=`) |
| `token_draw` | Card drawn |
| `token_booster_draw` | Team draw: one card from a chosen team |
| `reroll_modifiers` | User spent a token to reroll card modifiers |
| `token_redeem` | User redeemed a code |
| `token_grant_event_claim` | User auto-claimed tokens during an active token grant event |
| `weekly_token_grant` | Automatic token grant at week lock |
| `weekly_substitutions` | Automatic (or re-run) bench substitution pass for a week (`detail` has the week and `substitutions=N`) |
| `admin_grant_tokens` | Admin granted tokens to a user |
| `admin_toggle_tester` | Admin toggled tester flag on a user |
| `admin_toggle_admin` | Admin toggled admin flag on a user |
| `admin_force_logout` | Admin ended every session of a user via `POST /users/{user_id}/force-logout` |
| `admin_reauth` | An admin confirmed their password via `POST /reauth` (`detail` is `ok` or `failed: …`) |
| `player_reauth` | A non-admin user confirmed their password via `POST /reauth`, e.g. before connecting, merging or disconnecting Twitch (issue #160; `detail` is `ok` or `failed: …`) |
| `admin_code_create` | Admin created a redeemable code |
| `admin_code_delete` | Admin deleted a redeemable code |
| `admin_ingest` | Manual league ingest triggered |
| `parse_retry_triggered` | Manual unparsed-match re-check triggered (`detail` holds the window used) |
| `admin_recalculate` | Fantasy points recalculated |
| `admin_schedule_refresh` | Schedule cache busted via `POST /schedule/refresh` |
| `admin_set_match_week` | Admin manually assigned a match to a week |
| `admin_sync_match_weeks` | Bulk week override sync |
| `admin_sync_toornament` | Toornament result push |
| `admin_enrich_profiles` | Admin triggered a manual profile enrichment batch |
| `admin_player_added` | Admin added a player to the pool by OpenDota ID |
| `admin_player_bulk_added` | Admin bulk-added players via CSV |
| `admin_player_removed` | Admin soft-deleted a player from the pool |
| `admin_player_refund_issued` | Tokens granted to a card holder after player removal |
| `admin_league_add_monitor` | Admin added a league to monitoring |
| `admin_league_remove_monitor` | Admin removed a league from monitoring (data untouched) |
| `admin_league_purge` | Admin purged a league's matches/stats/bans |
| `admin_week_created` | Admin created a week (Week Management tab) |
| `admin_week_edited` | Admin edited an unlocked week |
| `admin_week_deleted` | Admin deleted an unlocked, roster-free week |
| `admin_substitutions_rerun` | Admin re-ran a finished week's bench substitutions (`detail` has the week and `substitutions=N`) |
| `admin_token_grant_event_created` | Admin created a token grant event |
| `admin_token_grant_event_deleted` | Admin deleted a token grant event |
| `twitch_soft_account_created` | A viewer pressed Join in the Twitch panel and a soft account was created (`detail` has `user_id=`; the opaque Twitch id is never logged) |
| `twitch_soft_account_deleted` | A soft account was deleted (`detail` has `user_id=` and `reason=leave` from the panel's Leave, `reason=admin` from `DELETE /admin/users/{user_id}`, or `reason=retention` from the daily purge) |
| `twitch_account_unlinked` | A website account — connected with Twitch sign-in or code-linked before #160 — that pressed Leave in the panel; only `twitch_user_id` was cleared |
| `twitch_connected` | A player connected Twitch on Profile with Twitch sign-in (issue #160; `detail` has `user_id=` and, when a Twitch collection is waiting, `pending_merge_user_id=`; no Twitch ids) |
| `twitch_disconnected` | A player disconnected Twitch on Profile (`detail` has `user_id=`) |
| `twitch_account_merged` | A soft account's cards and tokens were merged into a website account (`detail` has `full_user_id=`, `soft_user_id=`, `cards=`, `tokens=`, `roster_entries=`, `log_id=`) |
| `twitch_merge_reversed` | An admin reversed a merge (`detail` has `log_id=`, `full_user_id=`, the new `soft_user_id=`, `cards=`, `tokens=`, `token_shortfall=`, `roster_entries=`) |
| `twitch_panel_recognised` | The Twitch panel recognised a connected account by the JWT's `user_id` and attached the viewer's opaque id to it (`detail` has `user_id=`) |
| `admin_notification_created` | Admin created a broadcast notification |
| `admin_notification_deleted` | Admin deleted a notification |
| `admin_tag_definition_created` | Admin created a tag definition |
| `admin_tag_definition_deleted` | Admin deleted a tag definition |
| `admin_tag_grant` | Admin granted a tag to a user |
| `admin_tag_revoke` | Admin revoked a tag from a user |
| `admin_set_mvp` | Admin set match MVP via the Matches tab |
| `admin_match_vod_set` | Admin set/edited/cleared a match's VOD link via the Matches tab |
| `admin_match_retry_parse` | Admin retried a match's parse via the Matches tab (`detail` has the fetch result and outcome) |
| `admin_match_scoring` | Admin changed a match's unparseable / excluded-from-scoring flags (`detail` has old and new values) |
| `match_marked_unparseable` | Background parse-retry pass auto-marked a match still unparsed past the retry window (no actor) |
| `twitch_mvp_set` | Broadcaster set match MVP via the Twitch extension |
| `twitch_token_drop` | Token drop fired on MVP confirmation |
| `admin_season_archived` | Admin archived final season standings via End Season |
| `admin_season_reset` | Admin reset per-season data for the next season |
| `admin_db_backup` | Admin created a database backup from the admin panel (`detail` has the filename) |
| `admin_db_backup_download` | Admin downloaded a database backup (`detail` has the filename) |
| `admin_demo_clock_set` | Operator set the demo clock override (`DEMO_MODE` only) |
| `admin_demo_clock_cleared` | Operator cleared the demo clock override (`DEMO_MODE` only) |
| `admin_demo_accounts_seeded` | Operator seeded disposable demo accounts (`DEMO_MODE` only) |

---

## App Config

### `GET /config`
Returns public configuration values used by the frontend. No authentication required.

```json
{
  "token_name": "Kana Tokens",
  "initial_tokens": 5,
  "app_version": "...",
  "app_release": "...",
  "team_booster_cost": 3,
  "draw_rates": { "common": 60.0, "rare": 25.0, "epic": 10.0, "legendary": 5.0 },
  "demo_mode": false,
  "tour_autostart": false
}
```

`draw_rates` values are normalised from the live `draw_rate_*` scoring weights (always sum to 100%). See `reference/draw-panel-redesign.md`.

`demo_mode` is `true` only when the server has `DEMO_MODE=true` set. See `reference/demo-mode.md`.

`tour_autostart` is `true` only when `GUIDED_TOUR_AUTOSTART` is `true` (any case), read on each request. See `reference/guided-tour.md`.

### `GET /health`
No authentication required. Checks DB connectivity (`SELECT 1`), not just process liveness —
returns `{"status": "ok"}` (200) normally, or `{"status": "error"}` (503) if the DB is
unreachable. Used by `backend/Dockerfile`'s `HEALTHCHECK` instruction and by
`docker-compose.yml`'s `healthcheck:` block. See `reference/container-health-check.md`.

---

## Additional Admin Features

These features have dedicated reference documents:

| Feature | Endpoints | Reference |
|---|---|---|
| Player Pool Management | `GET/POST /admin/players/*` | `reference/admin-player-pool.md` |
| User Tags | `GET/POST/DELETE /admin/tags`, `POST/DELETE /admin/users/{id}/tags/{tag_id}` | `reference/user-tag-system.md` |
| League Monitoring | `GET/POST/DELETE /admin/leagues/*` | `reference/monitored-leagues-admin.md` |
| Token Grant Events | `GET/POST/DELETE /admin/token-grant-events` | `reference/token-grant-event.md` |
| Notifications | `GET/POST/DELETE /admin/notifications/*` | `reference/notification-system.md` |
| Week Management | `GET/POST/PATCH/DELETE /admin/weeks/*` (date-only `start_date`/`end_date` inputs) | `reference/admin-week-management.md` |
| Bench Substitution Re-run | `POST /admin/weeks/{week_id}/substitutions` | `reference/automatic-bench-substitution.md` |
| Match MVP Selection | `GET /admin/matches`, `GET /admin/matches/{id}/players`, `POST /admin/matches/{id}/mvp`, `PATCH /admin/matches/{id}/vod` | `reference/admin-tab-navigation-mvp.md` |
| Unparseable Match Handling | `POST /admin/matches/{id}/retry-parse`, `PATCH /admin/matches/{id}/scoring` (`GET /admin/matches` carries `parse_status` / `excluded_from_scoring`) | `reference/unparseable-match-handling.md` |
| Season Lifecycle | `POST /admin/season/end`, `POST /admin/season/reset`, `GET /leaderboard/seasons(/{id})` | `reference/season-lifecycle.md` |
| Database Backups | `POST /admin/backups`, `GET /admin/backups`, `GET /admin/backups/{filename}` | `reference/admin-db-backup.md` |
| Demo Mode | `GET/POST/DELETE /admin/demo/clock`, `POST /admin/demo/seed-accounts` (all `DEMO_MODE`-gated) | `reference/demo-mode.md` |
| Weekly Summary Report | `GET /weekly-summary`, `GET /weekly-summary/{week_id}`, `POST /weekly-summary/{week_id}/reveal`, `POST /weekly-summary/reveal-all`, `POST /weekly-summary/seen`, `POST /weekly-summary/prompted` | `core/weekly-summary.md` |
