# Session Revocation

Lets existing login sessions be ended before they expire. Players can log out everywhere, a password change or reset ends other sessions, and admins can force-log-out a user. Resolves GitHub issue #119.

---

## How it works

> **Superseded mechanism (issue #117).** This feature first used a per-user counter,
> `users.session_version` (integer, default 0, migration `028_users_session_version`), copied into
> the cookie as `sv`. Since #117 sessions are server-side rows in `user_sessions` and the cookie
> carries only a random session ID; revoking a session deletes its row. `users.session_version`
> stays in the schema (no destructive migration) but is no longer read or written. See
> `reference/longer-sessions.md` for the session model, limits and re-authentication.

Every request that needs login goes through `get_current_user` (`backend/deps.py`). A cookie whose
session ID has no row, or whose user no longer exists, is cleared and gets 401. The returned
`user_id`, `username` and `is_admin` come from the database row, not the cookie.

The revocation triggers from #119 keep their behaviour, now as row deletions:

| Trigger | Rows deleted | Current session |
|---|---|---|
| `PUT /profile/password` | All other sessions of the user | Kept, with a new session ID |
| `POST /reset-password` | All sessions of the user | Not applicable |
| `POST /logout-everywhere` | All sessions of the caller | Ended |
| `POST /users/{user_id}/force-logout` | All sessions of the target | Ended if the admin targets themselves |

Unlike the old counter, rows can be listed and ended one device at a time (`GET /sessions`,
`DELETE /sessions/{id}`, issue #117).

### Other session readers

- `POST /twitch/link-code`: `twitch.get_session_user` delegated to `get_current_user` (both retired in #160; the session-cookie Twitch routes in `twitch_oauth.py` use `get_current_user` directly).
- `GET /deck` and `GET /deck/booster` (login optional): use `session_user_or_none`, so a revoked session counts as logged out.
- `rate_limit.key_by_user_or_ip` reads the user id that `get_current_user` puts on `request.state` (the cookie no longer carries it), so per-user limits stay per user.

### Frontend

- `loadMe` (`frontend/app-auth.js`): a 401 from `GET /me` runs `_clearLocalAuthState()` (the same cleanup `logout()` uses), so the header shows the logged-out state instead of a stale username.
- Profile tab: **Log out everywhere** button (`logoutEverywhere()` in `frontend/app-profile.js`).
- Admin Users table: **Force logout** button per user, with a confirmation prompt (`forceLogout()` in `frontend/app-admin-users.js`).

## Release note

Cookies issued before #119 had no `sv`, so every user was logged out once after that release. #117 does the same again for cookies without a `sid`.

## Endpoints

### `POST /logout-everywhere`
Login required (401 otherwise). Ends every session of the caller, including this one. Returns `{"status": "ok"}`. Audit: `user_logout_everywhere`.

### `POST /users/{user_id}/force-logout`
Admin only (403 otherwise). Ends every session of the user and returns `{"user_id", "username"}`. 404 for an unknown user. An admin may target themselves. Audit: `admin_force_logout`, detail `target={username} user_id={id}`.

## Configuration

`SESSION_MAX_AGE_SECONDS` (#119's cookie lifetime, default `86400`) is now a deprecated alias for
`SESSION_ABSOLUTE_SECONDS`; see `reference/longer-sessions.md` for the six session settings.

## Tests

`backend/tests/test_issue_119_session_revocation.py` (updated for #117 to assert session rows) and
`backend/tests/test_issue_117_longer_sessions.py`.
