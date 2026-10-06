# Longer Sessions

Server-side session management: players stay logged in while active (14 days idle, 30 days at most), admins get short sessions and confirm their password before destructive actions, and logging out ends the session on the server. Designed against the OWASP Session Management Cheat Sheet. Resolves GitHub issue #117 and replaces the session-version check from #119 (`reference/session-revocation.md`).

---

## How it works

- **Session rows.** Each login or registration creates a row in `user_sessions` (`UserSession` in `backend/models.py`; a new table, so no migration) with a random session ID from `secrets.token_urlsafe(32)`. The signed cookie carries only `{"sid": "<token>"}`; the row stores `sha256(sid)` in `sid_hash`, so a database leak exposes no live session IDs. Columns: `id` (opaque handle), `sid_hash` (unique), `user_id` (indexed), `created_at`, `last_seen_at`, `reauth_at`.
- **Validation in one place.** `get_current_user` (`backend/deps.py`) calls `sessions.validate_request` (`backend/sessions.py`). It finds the row by hash, loads the user, picks the limits from `user.is_admin`, and rejects the session (401, row deleted, cookie cleared) when `now - last_seen_at` exceeds the idle limit or `now - created_at` exceeds the absolute limit. It writes `last_seen_at` only when the stored value is at least `SESSION_TOUCH_SECONDS` old, so a busy user causes about one write every 5 minutes. All timing reads `sessions._now()`.
- **Rotation and revocation.**
  - Login and register always issue a new session ID; a session the browser already held is deleted.
  - `POST /logout` deletes the current row.
  - `POST /logout-everywhere`, `POST /reset-password` and admin `POST /users/{id}/force-logout` delete all of the user's rows.
  - `PUT /profile/password` deletes the user's other rows and replaces the current one with a new ID.
  - `POST /users/{id}/toggle-admin` deletes all of the target's rows, so their next login gets the new role's limits.
- **Admin re-authentication.** Destructive admin endpoints use the `require_recent_reauth` dependency (route-level, after `require_admin`): the current row's `reauth_at` must be within `ADMIN_REAUTH_SECONDS`, otherwise 403 `{"detail": "reauth_required"}`. `reauth_at` is per session, so re-authenticating on one device does not cover another. Covered endpoints:
  - `POST /admin/season/end`, `POST /admin/season/reset`
  - `DELETE /admin/leagues/{league_id}/data`
  - `POST /admin/backups`, `GET /admin/backups`, `GET /admin/backups/{filename}`
  - `POST /users/{user_id}/toggle-admin`
- **Cookie.** Under `HTTPS_ONLY=true` the cookie is named `__Host-session` (`Secure`, `Path=/`, no `Domain`); otherwise `session` for local development. `HttpOnly` and `SameSite=Lax` are always set. Its `Max-Age` is the larger of the two absolute limits; the server enforces the real limits.
- **Per-user rate limits.** The cookie no longer carries a user id, so `get_current_user` puts it on `request.state.session_user_id`, and `rate_limit.key_by_user_or_ip` reads it from there.
- **Cleanup.** The week maintenance loop (`_week_maintenance_loop` in `backend/main.py`) calls `sessions.cleanup_expired(db)` on its first pass after the app starts and then once a day (the first pass at least 24 hours after the previous cleanup), deleting rows past their role's limits or whose user is gone.
- **Existing cookies.** Cookies from before this release carry no `sid` and are treated as logged out.
- **Twitch.** Extension requests use Twitch JWTs and are unaffected. The website's Twitch connection routes (#160, `twitch_oauth.py`; `POST /twitch/link-code` before them) use the session cookie and get the same checks; Connect, merge and Disconnect also need a recent `POST /reauth` (`require_recent_player_reauth`).
- **`users.session_version`** (#119) stays in the schema but is no longer read or written.

### Frontend

- `adminFetch(url, options)` in `frontend/app-admin.js` wraps the destructive admin calls (season end/reset, league purge, backup create/list/download, toggle admin). On 403 `reauth_required` it opens the in-page `#reauthModal` password prompt, calls `POST /reauth`, and retries the original request once. A wrong password shows the error in the modal. Backup downloads go through it too, as a blob download instead of a plain link.
- The Profile tab lists the caller's sessions (`loadSessions` / `_renderSessions` in `frontend/app-profile.js`, built with `textContent`) with a **Sign out** button per row. See `markdown/ui_description/profile.md`.

## Endpoints

### `POST /reauth`
Login required; open to any logged-in user, not only admins (the audit action is still `admin_reauth`). Body `{"password"}`. Checks the current user's password and sets `reauth_at` on the current session row; returns `{"status": "ok", "valid_seconds": ADMIN_REAUTH_SECONDS}`. Wrong password: 401 `"Incorrect password"`, recorded as a failed login for the username. Locked-out username (`LOGIN_LOCKOUT_THRESHOLD` failures within `LOGIN_LOCKOUT_WINDOW_SECONDS`): 429 with the login lockout message. If the current session row is missing (defensive; `get_current_user` has just validated it): 401 `"Not authenticated"`. Rate limit `RATE_LIMIT_LOGIN`. Audit `admin_reauth` with detail `ok`, `failed: wrong password` or `failed: locked out`.

### `GET /sessions`
Login required. The caller's unexpired sessions, newest activity first: `[{"id", "created_at", "last_seen_at", "current"}]`. `id` is the row handle; the session ID and its hash are never returned.

### `DELETE /sessions/{id}`
Login required. Ends one of the caller's sessions and returns `{"status": "ok", "current": <bool>}`. 404 for an unknown id or anyone else's. Ending the current session also clears the cookie.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SESSION_IDLE_SECONDS` | `1209600` (14 days) | Player idle limit |
| `SESSION_ABSOLUTE_SECONDS` | `2592000` (30 days) | Player limit from login (`SESSION_MAX_AGE_SECONDS` accepted as a deprecated alias) |
| `SESSION_TOUCH_SECONDS` | `300` | Minimum interval between `last_seen_at` writes |
| `ADMIN_SESSION_IDLE_SECONDS` | `7200` (2 h) | Admin idle limit |
| `ADMIN_SESSION_ABSOLUTE_SECONDS` | `43200` (12 h) | Admin limit from login |
| `ADMIN_REAUTH_SECONDS` | `600` (10 min) | How long a password re-entry covers destructive admin actions |

The values are read and validated when `backend/sessions.py` is imported, so `import main` fails with a `RuntimeError` naming the variable when:

- a value is not a positive integer,
- an idle limit is larger than its absolute limit (the error names both variables),
- `SESSION_TOUCH_SECONDS` is not smaller than `ADMIN_SESSION_IDLE_SECONDS`.

`SESSION_MAX_AGE_SECONDS` (issue #119) is used as `SESSION_ABSOLUTE_SECONDS` when that is unset, with a deprecation warning naming both; it is ignored, with a warning, when both are set. An invalid alias value also stops startup.

## Accepted risk

The 14-day player idle limit is longer than the OWASP Session Management Cheat Sheet's typical examples. It is accepted because player accounts hold no payment data, every session can be revoked on the server, and the 30-day absolute limit meets NIST SP 800-63B AAL1 (re-authenticate at least every 30 days). Admin limits are much shorter, plus password re-entry, because admin actions can destroy data or expose password hashes (backup download).

## Release note

Sessions now last 14 days without a visit (30 days at most). Admins: sessions last up to 12 hours, and destructive actions ask for your password again. Everyone logs in once after this update.

## Tests

`backend/tests/test_issue_117_longer_sessions.py`; `backend/tests/test_issue_119_session_revocation.py` covers the revocation triggers.
