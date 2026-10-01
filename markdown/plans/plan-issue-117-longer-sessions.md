# Plan: Longer Sessions with Server-Side Session Management

## Context
Users are logged out 24 hours after logging in, even when they use the site every day. The session cookie lives for `SESSION_MAX_AGE_SECONDS` (default `86400`, `backend/main.py`), and Starlette's `SessionMiddleware` only re-issues it when the session data changes, which in practice means only at login. Issue #117 asks for 14–30 days.

A first draft simply raised the lifetime and slid it while users were active. A review against the **OWASP Session Management Cheat Sheet** found three gaps that a longer lifetime makes worse:

| OWASP guidance | Current state | Gap |
|---|---|---|
| Invalidate the session on the server at logout | Sessions are signed cookies; `POST /logout` only clears the cookie in that browser | A copied cookie stays valid until it expires, which becomes 14–30 days instead of 1 |
| Enforce idle and absolute timeouts on the server | Only the cookie's signed timestamp limits a session | Idle tracking and an absolute cap need server-side state |
| Shorter timeouts and re-authentication for high-privilege accounts and sensitive actions | Admins get the same lifetime as players; season reset, league purge and backup download need only a session | A stolen admin cookie could do the most damage, for the longest time |
| Renew the session ID at login and on privilege change | No session ID; the cookie content stays the same until logout | No rotation on password change or on promotion to admin |
| Restrictive cookie attributes | `HttpOnly`, `SameSite=Lax`, and `Secure` with `HTTPS_ONLY` | Good. A `__Host-` name prefix would also pin the cookie to the exact host |

This plan moves sessions to a **server-side session table** with random session IDs, enforces every timeout on the server, gives admins shorter sessions plus re-authentication before destructive actions, and then raises the player session lifetime as #117 asks.

**Target behaviour:**

| Account | Idle limit | Absolute limit | Extra |
|---|---|---|---|
| Player | 14 days | 30 days | — |
| Admin | 2 hours | 12 hours | Password re-entry within 10 minutes before destructive admin actions |

**Decisions and assumptions:**
- **Risk level.** The app holds usernames, emails, password hashes and game tokens, with no payments, so player sessions follow NIST SP 800-63B AAL1: log in again at least every 30 days. The 14-day idle limit is a deliberate usability choice for a low-risk consumer app and is documented as an accepted risk. Admin limits are much shorter because admin actions can destroy data or expose password hashes (backup download).
- **Session ID.** 32 random bytes from `secrets.token_urlsafe(32)`, carried in the signed cookie. The database stores only its SHA-256 hash, so a database leak does not expose live session IDs.
- **This replaces the #119 session version check.** Revocation becomes "delete the session rows": logout deletes one row, "Log out everywhere", password change, password reset and force logout delete all of a user's rows. `users.session_version` is left in place, with no destructive migration, but is no longer read.
- **Existing cookies** (#119 cookies without a session ID) are treated as logged out, so everyone logs in once after the release. If this ships in the same release as #119, that is the same single re-login.
- **Write load.** `last_seen_at` is updated at most once per `SESSION_TOUCH_SECONDS` (default 300), so a busy user causes about one session write every 5 minutes, not one per request. SQLite handles this easily at league scale.
- **Twitch extension requests** use Twitch JWTs and are unaffected. `POST /twitch/link-code` uses the session cookie and gets the same checks.

Resolves GitHub issue #117.

## User Stories

### Stay Logged In While Active
**User story**
As a player, I want to stay logged in while I keep using the site so that I don't have to log in again every day.

**Acceptance criteria**
- A player session stays valid until it has had no authenticated request for `SESSION_IDLE_SECONDS` (default `1209600`, 14 days), or until `SESSION_ABSOLUTE_SECONDS` (default `2592000`, 30 days) after login, whichever comes first
- Both limits are checked on the server against the session row (`last_seen_at`, `created_at`), not only by the cookie's lifetime
- `last_seen_at` is updated at most once per `SESSION_TOUCH_SECONDS` (default `300`)
- A session past either limit gets 401 on its next request, and its row is deleted

### Logout Ends the Session on the Server
**User story**
As a player, I want logging out to end my session for real so that a copy of my cookie can't be used afterwards.

**Acceptance criteria**
- Each login creates a `user_sessions` row with a new random session ID; the cookie holds only that ID
- `user_sessions` stores the SHA-256 hash of the session ID, never the ID itself
- `POST /logout` deletes the current session row and clears the cookie; replaying the old cookie afterwards gets 401
- `POST /logout-everywhere`, a password change (all other sessions), a password reset (all sessions) and admin force logout delete the matching rows. Their behaviour stays as in #119
- A cookie whose session ID has no row, including every cookie issued before this release, gets 401

### New Session ID on Login and Privilege Change
**User story**
As an operator, I want a fresh session ID whenever a user's privileges or credentials change so that an old or planted cookie can't inherit them.

**Acceptance criteria**
- Login and register always create a new session row and cookie, even if a valid session cookie was sent
- Changing your own password replaces the current session with a new one (new ID) and deletes all others
- Toggling a user's admin flag deletes all of that user's sessions, so their next login starts with the limits for their new role
- The cookie is named `__Host-session` when `HTTPS_ONLY=true` (`Secure`, `Path=/`, no `Domain`), and `session` otherwise for local development. `HttpOnly` and `SameSite=Lax` stay

### Shorter Sessions and Re-Authentication for Admins
**User story**
As an operator, I want admin sessions to be short and destructive admin actions to ask for the password again so that a stolen admin cookie is worth very little.

**Acceptance criteria**
- An admin's session uses `ADMIN_SESSION_IDLE_SECONDS` (default `7200`, 2 hours) and `ADMIN_SESSION_ABSOLUTE_SECONDS` (default `43200`, 12 hours) instead of the player limits
- `POST /reauth` with `{"password"}` checks the current user's password and stores `reauth_at` on the session row. It shares the login lockout and rate limit, and writes an `admin_reauth` audit entry on success and on failure
- These endpoints need a `reauth_at` within `ADMIN_REAUTH_SECONDS` (default `600`, 10 minutes), and otherwise return 403 with `{"detail": "reauth_required"}`:
  - `POST /admin/season/end` and `POST /admin/season/reset`
  - `DELETE /admin/leagues/{league_id}/data`
  - `POST /admin/backups`, `GET /admin/backups` and `GET /admin/backups/{filename}`
  - `POST /users/{user_id}/toggle-admin`
- On `reauth_required` the admin panel shows an in-page password prompt, retries the action once confirmed, and shows the error if the password is wrong. It never uses `confirm()` or `prompt()`
- Non-destructive admin endpoints keep working without re-authentication

### See and End My Sessions
**User story**
As a player, I want to see where I'm signed in and end a session I don't recognise so that I stay in control of my account.

**Acceptance criteria**
- `GET /sessions` lists the caller's sessions with created time, last active time, and which one is the current device. It never returns the session ID or its hash, only an opaque row handle
- `DELETE /sessions/{handle}` ends one of the caller's own sessions; another user's handle returns 404
- The Profile tab lists the sessions with a "Sign out" button per row, next to "Log out everywhere"
- Expired session rows are deleted by the daily maintenance loop

### Operators Can Tune and Audit the Limits
**User story**
As an operator, I want every limit configurable and documented so that I can match them to my deployment's risk.

**Acceptance criteria**
- `.env.example`, `markdown/features/core/auth.md` and the feature doc describe:
  - `SESSION_IDLE_SECONDS`, `SESSION_ABSOLUTE_SECONDS` and `SESSION_TOUCH_SECONDS`
  - `ADMIN_SESSION_IDLE_SECONDS`, `ADMIN_SESSION_ABSOLUTE_SECONDS` and `ADMIN_REAUTH_SECONDS`
  - their defaults, and the accepted-risk note for the 14-day player idle limit
- Startup fails with a clear error when a value is not a positive integer, when an idle limit is larger than its absolute limit, or when `SESSION_TOUCH_SECONDS` is not smaller than the admin idle limit
- `SESSION_MAX_AGE_SECONDS` from #119 is still accepted as an alias for `SESSION_ABSOLUTE_SECONDS`, with a startup warning

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New `UserSession` table (`user_sessions`); new table, so no migration |
| `backend/sessions.py` *(new)* | Create, look up, touch, rotate and delete sessions; limits by role; re-auth check; expiry cleanup |
| `backend/deps.py` | `get_current_user` validates the cookie's session ID against `user_sessions` (role-based idle and absolute limits) instead of `session_version`; new `require_recent_reauth` dependency |
| `backend/main.py` | Read and validate the new settings; `SessionMiddleware(session_cookie=...)` uses `__Host-session` under `HTTPS_ONLY`; cookie `max_age` = the larger absolute limit |
| `backend/routers/auth.py` | Login and register create a session; logout deletes it; `/logout-everywhere` and reset delete all; new `POST /reauth`, `GET /sessions`, `DELETE /sessions/{handle}` |
| `backend/routers/profile.py` | Password change rotates the current session and deletes the others |
| `backend/routers/admin_users.py` | Force logout deletes rows; toggle-admin deletes the target's sessions and requires re-auth |
| `backend/routers/admin_season.py`, `admin_leagues.py`, `admin_backups.py` | Add `require_recent_reauth` to the listed endpoints |
| `backend/main.py` (week maintenance loop) | Daily delete of expired session rows |
| `frontend/app-auth.js`, `app-admin*.js`, `app-profile.js`, `index.html` | In-page re-auth prompt with one retry; Profile sessions list with "Sign out" |
| `.env.example`, `markdown/features/core/auth.md`, `markdown/features/reference/session-revocation.md`, `markdown/features/reference/longer-sessions.md`, `markdown/ui_description/profile.md`, `markdown/ui_description/admin.md` | Docs |
| `backend/tests/test_issue_117_longer_sessions.py` | Tests; update `test_issue_119_session_revocation.py` where it checks `sv` directly |

### Step 1 — Session table
```python
class UserSession(Base):
    __tablename__ = "user_sessions"
    id           = Column(Integer, primary_key=True, autoincrement=True)  # opaque handle for /sessions
    sid_hash     = Column(String(64), unique=True, nullable=False)       # sha256(session id)
    user_id      = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    created_at   = Column(Integer, nullable=False)
    last_seen_at = Column(Integer, nullable=False)
    reauth_at    = Column(Integer, nullable=True)
```
The cookie payload becomes `{"sid": "<token>"}` only. The username and admin flag already come from the database (#119).

### Step 2 — Validation in one place
`_session_user(request, db)` takes the `sid` from the cookie and looks up the row by `sha256(sid)`. It then:
1. Loads the user.
2. Picks the limits from `user.is_admin`.
3. Rejects the session and deletes the row when `now - last_seen_at > idle` or `now - created_at > absolute`.
4. Touches `last_seen_at` when it is older than `SESSION_TOUCH_SECONDS`.

`require_recent_reauth` additionally checks `reauth_at`. All timing reads `time.time()` through one helper so tests can control the clock.

### Step 3 — Rotation and revocation
- Login and register always issue a new session: create a row, then replace the cookie.
- Logout deletes the current row.
- Logout everywhere and password reset delete all of the user's rows.
- Password change deletes the other rows, then deletes and re-creates the current one, so the cookie gets a new ID.
- Force logout deletes all rows.
- Toggle-admin deletes the target's rows.

### Step 4 — Re-authentication
`POST /reauth` reuses the login lockout (`_is_locked_out` / `_record_failed_login`) and `RATE_LIMIT_LOGIN`. Success sets `reauth_at = now` on the current row. Each destructive endpoint adds `Depends(require_recent_reauth)` after `require_admin`.

In the frontend, a shared `adminFetch()` wrapper catches 403 `reauth_required`, shows the password prompt (a small modal using the existing modal styles), calls `/reauth`, and retries the original request once.

### Step 5 — Sessions list
`GET /sessions` returns `[{"id", "created_at", "last_seen_at", "current"}]`; `DELETE /sessions/{id}` is scoped to the caller. The Profile tab gets a small table and per-row buttons, built with `textContent` and no HTML from data.

### Step 6 — Settings, cookie name, cleanup
Validate the six settings at startup next to the existing guards. Set `session_cookie` from `HTTPS_ONLY`. Add expired-row deletion to the week maintenance loop.

### Step 7 — Docs and release note
Update the docs listed above, and add a risk-acceptance paragraph for the 14-day player idle limit with its OWASP and NIST references. Release note: "Sessions now last 14 days without a visit (30 days at most). Admins: sessions last up to 12 hours, and destructive actions ask for your password again. Everyone logs in once after this update."

## Verification
- `cd backend && python3 -m pytest tests/test_issue_117_longer_sessions.py tests/test_issue_119_session_revocation.py -v`, then the full suite.
- **Logout:** after `POST /logout`, the same cookie replayed with a second client gets 401.
- **Idle limit:** with the clock moved forward, a player idle for 15 days gets 401, and a player active once a week stays logged in until day 30, then gets 401.
- **Touching:** `last_seen_at` changes at most once per `SESSION_TOUCH_SECONDS`, counting writes over 50 requests.
- **Admin limits:** an admin idle for 3 hours gets 401; an admin session older than 12 hours gets 401.
- **Re-auth:** season reset without re-auth gets 403 `reauth_required`. After `POST /reauth` it succeeds; 11 minutes later it gets 403 again. A wrong password counts toward the login lockout.
- **Rotation:** password change gives a new cookie value, and the old cookie gets 401. Promoting a user ends their sessions.
- **Storage:** the database contains no raw session IDs (only 64-character hex hashes).
- **Cookie:** under `HTTPS_ONLY=true` the cookie is `__Host-session` with `Secure; HttpOnly; SameSite=lax; Path=/` and no `Domain`.
- **Sessions list:** shows only the caller's sessions, and deleting another user's handle gets 404.
- **Startup:** fails for an idle limit larger than its absolute limit and for non-integer values.
- **Manual on test.kana-cards.com:**
  - log in, come back the next day and still be logged in,
  - as an admin, a backup download asks for the password,
  - logging out on one device leaves the other device logged in.
