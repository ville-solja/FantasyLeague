# Admin Features

Admin users have access to a set of management endpoints not available to regular users. An admin is identified by the `is_admin` flag on their `User` record. The initial admin account (and optionally further admins) is bootstrapped at startup via the `SEED_ADMIN_USERNAME`/`SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` environment variables and their `_2`, `_3`, ... suffixed counterparts (see `reference/env-based-admin-seeding.md`). Additional admins can also be promoted in-app by an existing admin via the User Management tab's admin toggle, with no DB access required.

All admin endpoints require an active admin session. Unauthorized requests receive a 403 response.

---

## User Management

### `GET /users`
Returns a list of all registered users. Each entry contains `id`, `username`, `tokens`, `is_tester`, `is_admin`, and `tags` (array of `{id, key, label}` objects for admin-granted tags; empty array if none).

### `POST /users/{user_id}/toggle-tester`
Flips the `is_tester` flag for the given user. Tester accounts are excluded from all leaderboards (season and weekly) while remaining fully visible in the admin panel. Returns `{ user_id, username, is_tester }`. Logged as `admin_toggle_tester`.

### `POST /users/{user_id}/toggle-admin`
Flips the `is_admin` flag for the given user. Returns `{ user_id, username, is_admin }`. Logged
as `admin_toggle_admin`. Two guards prevent the app from ever ending up with zero admins: an
admin cannot toggle their own admin status (409 `"Cannot change your own admin status"`), and
the last remaining admin cannot be demoted (409 `"Cannot demote the last remaining admin"`).
`require_admin` (`backend/deps.py`) re-checks `is_admin` against the database on every
admin-gated request rather than trusting the session's cached value, so a promotion or
demotion takes effect on the very next request — not just at the next login. This closes what
would otherwise be a real gap: without it, a demoted admin would keep destructive access
(season reset, league purge, user management) for the rest of their existing session. One
UI-only asymmetry remains: the frontend's Admin tab visibility (`activeIsAdmin`, populated from
`GET /me`) is still session-cached and only refreshes at next login, so a freshly-promoted user
can call admin endpoints directly before the Admin tab appears in their own browser.

### `POST /grant-tokens`
Grants a configurable number of tokens to a specific user.

```json
{ "target_user_id": 5, "amount": 3 }
```

Amount must be at least 1 — the endpoint returns 422 for values below 1. All grants are recorded in the audit log.

---

## Token Distribution: Redeemable Codes

Redeemable codes allow token grants to be distributed without per-user admin action. Each code can be redeemed once per user. Codes are not restricted to promotional use — they can serve any purpose (event rewards, onboarding, giveaways, etc.).

### `POST /codes`
Creates a new redeemable code.
```json
{ "code": "LAUNCH2026", "token_amount": 5 }
```
Codes are stored uppercased. Duplicate codes return 409.

### `GET /codes`
Lists all created codes with their redemption counts.

### `DELETE /codes/{code_id}`
Deletes a code. Users who already redeemed it keep their tokens.

### `POST /redeem` *(user-facing)*
Regular users redeem a code via this endpoint. Returns the number of tokens granted.
```json
{ "code": "LAUNCH2026" }
```

---

## Scoring Weights

### `GET /weights`
Returns all scoring weight keys, labels, and current values. Available to all users (used to display weights in the UI).

### Changing weights
Weights are configured via the `WEIGHTS_JSON` environment variable (a JSON object mapping weight keys to float values). Changes take effect on the next container restart. See `commands.md` for the full variable reference and `seed.py` for the list of all weight keys and their defaults.

### `POST /recalculate`
Recalculates fantasy points for every `PlayerMatchStats` row using the current weights. Run this after changing weights to update historical scores. Takes several seconds on large datasets.

---

## Match & Week Management

### `PUT /matches/{match_id}/week`
Manually assigns a match to a specific fantasy week, overriding the week derived from its `start_time`. Used when a match is played outside its scheduled week.
```json
{ "week_id": 3 }
```
Set `week_id` to `null` to clear the override.

### `POST /admin/sync-match-weeks`
Automatically bulk-assigns `week_override_id` for all matches based on the Google Sheets schedule. Uses a ±3-day proximity window to map each scheduled series to the closest actual matches played between those two teams. Clears overrides for matches already in the correct week. Returns a summary of changes and errors.

---

## Player Profile Enrichment

### `POST /admin/enrich-profiles`
Triggers a synchronous enrichment batch for players whose profile facts are missing or stale. Enrichment runs automatically in the background (see `reference/player-profile-enrichment.md`); this endpoint forces an immediate pass. Returns `{ "enriched": N, "skipped": M, "errors": K }`. Logged as `admin_enrich_profiles`.

---

## Data Ingest

### `POST /ingest/league/{league_id}`
Triggers a full ingest cycle for the specified OpenDota league ID:
1. Fetches all match IDs from OpenDota
2. Ingests new matches and player stats
3. Refreshes Dotabuff team logos
4. Runs `run_enrichment()` — a name/avatar backfill only, not the AI-driven profile enrichment
   (facts + bio). That separate pass (`run_profile_enrichment()`) only runs via
   `POST /admin/enrich-profiles` or the background loop — see `reference/player-profile-enrichment.md`.

Note: card generation was removed from the ingest pipeline. Cards are now created dynamically at draw time.

Ingest also runs automatically every 15 minutes in the background (`INGEST_POLL_INTERVAL`), or
every 2 minutes (`INGEST_LIVE_POLL_INTERVAL`) while any week is currently active, so live-series
results land faster during play. The manual endpoint is useful immediately after new matches are
played. See `reference/toornament.md`.

---

## Schedule

### `GET /schedule`
Returns the current season fixture list parsed from the Google Sheets source (cached for 1 hour). No authentication required. Used by the frontend to display upcoming and past series.

### `POST /schedule/refresh`
Clears the 1-hour schedule cache, forcing the next `GET /schedule` request to re-fetch from the Google Sheets source.

### `GET /schedule/debug`
Returns detailed schedule parsing information for troubleshooting team name mapping or CSV parsing issues.

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
Returns the most recent audit log entries, newest first. All significant admin actions are recorded here automatically:

| Action | Trigger |
|---|---|
| `user_register` | New user registration |
| `user_login` | Successful user login |
| `password_reset_requested` | Forgot-password flow issued a temporary password |
| `token_draw` | Card drawn |
| `token_booster_draw` | Team booster pack drawn |
| `reroll_modifiers` | User spent a token to reroll card modifiers |
| `token_redeem` | User redeemed a code |
| `token_grant_event_claim` | User auto-claimed tokens during an active token grant event |
| `weekly_token_grant` | Automatic token grant at week lock |
| `admin_grant_tokens` | Admin granted tokens to a user |
| `admin_toggle_tester` | Admin toggled tester flag on a user |
| `admin_toggle_admin` | Admin toggled admin flag on a user |
| `admin_code_create` | Admin created a redeemable code |
| `admin_code_delete` | Admin deleted a redeemable code |
| `admin_ingest` | Manual league ingest triggered |
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
| `admin_token_grant_event_created` | Admin created a token grant event |
| `admin_token_grant_event_deleted` | Admin deleted a token grant event |
| `admin_notification_created` | Admin created a broadcast notification |
| `admin_notification_deleted` | Admin deleted a notification |
| `admin_tag_definition_created` | Admin created a tag definition |
| `admin_tag_definition_deleted` | Admin deleted a tag definition |
| `admin_tag_grant` | Admin granted a tag to a user |
| `admin_tag_revoke` | Admin revoked a tag from a user |
| `admin_set_mvp` | Admin set match MVP via the Matches tab |
| `admin_match_vod_set` | Admin set/edited/cleared a match's VOD link via the Matches tab |
| `twitch_mvp_set` | Broadcaster set match MVP via the Twitch extension |
| `twitch_token_drop` | Token drop fired on MVP confirmation |
| `admin_season_archived` | Admin archived final season standings via End Season |
| `admin_season_reset` | Admin reset per-season data for the next season |
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
  "demo_mode": false
}
```

`draw_rates` values are normalised from the live `draw_rate_*` scoring weights (always sum to 100%). See `reference/draw-panel-redesign.md`.

`demo_mode` is `true` only when the server has `DEMO_MODE=true` set. See `reference/demo-mode.md`.

### `GET /health`
Returns `{"status": "ok"}`. No authentication required. Used by container health checks.

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
| Match MVP Selection | `GET /admin/matches`, `GET /admin/matches/{id}/players`, `POST /admin/matches/{id}/mvp`, `PATCH /admin/matches/{id}/vod` | `reference/admin-tab-navigation-mvp.md` |
| Season Lifecycle | `POST /admin/season/end`, `POST /admin/season/reset`, `GET /leaderboard/seasons(/{id})` | `reference/season-lifecycle.md` |
| Demo Mode | `GET/POST/DELETE /admin/demo/clock`, `POST /admin/demo/seed-accounts` (all `DEMO_MODE`-gated) | `reference/demo-mode.md` |
| Weekly Summary Report | `GET /weekly-summary`, `GET /weekly-summary/{week_id}`, `POST /weekly-summary/{week_id}/reveal`, `POST /weekly-summary/seen` | `core/weekly-summary.md` |
