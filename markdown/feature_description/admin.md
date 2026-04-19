# Admin Features

Admin users have access to a set of management endpoints not available to regular users. An admin is identified by the `is_admin` flag on their `User` record, set at user creation time (via `seed/users.json` for initial seed users, or database manipulation for subsequent admins).

All admin endpoints require an active admin session. Unauthorized requests receive a 403 response.

---

## User Management

### `GET /users`
Returns a list of all registered users. Each entry contains `id`, `username`, and `tokens`.

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

## Data Ingest

### `POST /ingest/league/{league_id}`
Triggers a full ingest cycle for the specified OpenDota league ID:
1. Fetches all match IDs from OpenDota
2. Ingests new matches and player stats
3. Runs player profile enrichment
4. Seeds new player cards
5. Refreshes Dotabuff team logos

Ingest also runs automatically every 15 minutes in the background. The manual endpoint is useful immediately after new matches are played.

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
| `token_draw` | Card drawn |
| `reroll_modifiers` | User spent a token to reroll card modifiers |
| `token_redeem` | User redeemed a code |
| `admin_grant_tokens` | Admin granted tokens to a user |
| `admin_ingest` | Manual league ingest triggered |
| `admin_recalculate` | Fantasy points recalculated |
| `admin_schedule_refresh` | Schedule cache busted via `POST /schedule/refresh` |
| `admin_set_match_week` | Admin manually assigned a match to a week |
| `admin_sync_match_weeks` | Bulk week override sync |
| `admin_sync_toornament` | Toornament result push |
| `admin_code_create` | Admin created a redeemable code |
| `admin_code_delete` | Admin deleted a redeemable code |
| `weekly_token_grant` | Automatic token grant at week lock |
| `password_reset_requested` | Forgot-password flow issued a temporary password |

---

## App Config

### `GET /config`
Returns public configuration values used by the frontend. No authentication required.

```json
{ "token_name": "Kana Tokens", "initial_tokens": 5 }
```

### `GET /health`
Returns `{"status": "ok"}`. No authentication required. Used by container health checks.
