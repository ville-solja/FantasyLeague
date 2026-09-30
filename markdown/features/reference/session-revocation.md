# Session Revocation

Lets existing login sessions be ended before they expire. Players can log out everywhere, a password change or reset ends other sessions, and admins can force-log-out a user. Resolves GitHub issue #119.

---

## How it works

Sessions are signed cookies with no server-side store. Each user has a `session_version` number (`users.session_version`, integer, default 0, added by migration `028_users_session_version`), copied into the cookie as `sv` at login and register. Every request that needs login compares the two in `get_current_user` (`backend/deps.py`). If they differ, or the cookie has no `sv`, or the user no longer exists, the session is cleared and the request gets 401. The returned `user_id`, `username` and `is_admin` come from the database row, not the cookie.

Increasing `session_version` therefore ends every session of that user at once. It is increased by:

| Trigger | Current session |
|---|---|
| `PUT /profile/password` | Kept (updated to the new version) |
| `POST /reset-password` | Not applicable, all sessions end |
| `POST /logout-everywhere` | Ended |
| `POST /users/{user_id}/force-logout` | Ended for the target user |

A counter cannot list or end a single device; it ends all of them. The cost is one primary-key lookup per authenticated request.

### Other session readers

- `POST /twitch/link-code`: `twitch.get_session_user` delegates to `get_current_user`.
- `GET /deck` and `GET /deck/booster` (login optional): use `session_user_or_none`, so a revoked session counts as logged out.
- `rate_limit.key_by_user_or_ip` still reads the raw `user_id` from the cookie. It only picks a rate-limit bucket; the route's own dependency rejects a revoked session.

### Frontend

- `loadMe` (`frontend/app-auth.js`): a 401 from `GET /me` runs `_clearLocalAuthState()` (the same cleanup `logout()` uses), so the header shows the logged-out state instead of a stale username.
- Profile tab: **Log out everywhere** button (`logoutEverywhere()` in `frontend/app-profile.js`).
- Admin Users table: **Force logout** button per user, with a confirmation prompt (`forceLogout()` in `frontend/app-admin-users.js`).

## Release note

Cookies issued before this feature have no `sv`, so every user is logged out once after the release and has to log in again.

## Endpoints

### `POST /logout-everywhere`
Login required (401 otherwise). Ends every session of the caller, including this one. Returns `{"status": "ok"}`. Audit: `user_logout_everywhere`.

### `POST /users/{user_id}/force-logout`
Admin only (403 otherwise). Ends every session of the user and returns `{"user_id", "username"}`. 404 for an unknown user. An admin may target themselves. Audit: `admin_force_logout`, detail `target={username} user_id={id}`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SESSION_MAX_AGE_SECONDS` | `86400` | Session cookie lifetime. Must be a positive integer; otherwise startup fails with a `RuntimeError`. Revocation makes a longer value (issue #117) safe to use. |

## Tests

`backend/tests/test_issue_119_session_revocation.py`.
