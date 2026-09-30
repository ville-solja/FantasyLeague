# Plan: Session Revocation

## Context
Sessions are signed cookies (Starlette `SessionMiddleware`, `max_age=86400` in `backend/main.py`) with no server-side record. A cookie stays valid for its full 24 hours even after the password changes, the account is compromised, or the account is deleted. `require_admin` already re-checks `is_admin` in the database, so a demoted admin loses admin routes immediately. Nothing else is revocable: `get_current_user` (`backend/deps.py`) trusts the cookie alone.

The fix adds a per-user **session version**: an integer on `users`, copied into the cookie at login. Every authenticated request compares the two, and bumping the number invalidates every existing session of that user at once. The version is bumped on password change, on password reset, on "log out everywhere", and by an admin force-logout.

This is also what issue #117 (longer sessions, 14–30 days) needs before it can ship safely. This plan makes the lifetime configurable but keeps today's 24 hours as the default. Raising it is a separate decision once revocation is live.

**Assumptions:**
- A version counter, not a table of individual sessions. It covers every case in the issue (logout everywhere, password change, forced admin action). It cannot list or revoke a single device, which the issue does not ask for. It costs one primary-key lookup per authenticated request, the same query `require_admin` already runs.
- Cookies issued before this release carry no version. They are treated as invalid, so everyone logs in once after the deploy. The release notes must say so.
- Changing your own password keeps the session you changed it from and logs out every other one. Resetting via an emailed link logs out every session.
- Revoked or deleted accounts get 401, the same as a logged-out request, so the frontend handles them the same way.

Resolves GitHub issue #119.

## User Stories

### Password Changes Log Out Other Sessions
**User story**
As a player, I want changing or resetting my password to end every other session on my account so that someone who stole my session cookie loses access.

**Acceptance criteria**
- `users.session_version` is an integer, default 0, added by migration `028_users_session_version`
- `POST /login` and `POST /register` store the user's current `session_version` in the session
- `PUT /profile/password` increments `session_version` and updates the current session to the new value, so the requester stays logged in and every other session gets 401 on its next request
- `POST /reset-password` increments `session_version`, so every existing session of that user gets 401
- A session whose stored version does not match the database, or that has no stored version, gets 401 from every route that uses `get_current_user`
- A session for a user id that no longer exists gets 401

### Log Out Everywhere
**User story**
As a player, I want a "Log out everywhere" button so that I can end sessions on devices I no longer have.

**Acceptance criteria**
- `POST /logout-everywhere` requires login, increments the caller's `session_version`, clears the current session, and returns `{"status": "ok"}`
- It writes a `user_logout_everywhere` audit entry
- After it, a second session of the same user gets 401 from `GET /me`
- Without a session it returns 401
- The Profile tab shows a "Log out everywhere" button. On success the page returns to the logged-out state

### Admin Force Logout
**User story**
As an admin, I want to force-log-out a user so that I can cut off a compromised or abusive account immediately.

**Acceptance criteria**
- `POST /users/{user_id}/force-logout` requires admin, increments that user's `session_version`, and returns `{"user_id", "username"}`
- It writes an `admin_force_logout` audit entry naming the target user
- An unknown `user_id` returns 404. A non-admin gets 403
- Forcing your own logout is allowed and ends your own sessions too
- The admin Users table shows a "Force logout" button per user, with a confirmation prompt

### All Session Checks Go Through One Place
**User story**
As a developer, I want every session-based check to validate the session version so that no route can be reached with a revoked cookie.

**Acceptance criteria**
- `get_current_user` loads the user from the database and returns `user_id`, `username` and `is_admin` from the database row, not from the cookie
- `get_session_user` in `backend/twitch.py` (used by `POST /twitch/link-code`) uses the same check
- The optional-login paths of `GET /deck` and `GET /deck/booster` treat a revoked session as logged out
- The frontend treats a 401 from `GET /me` as logged out and clears the stored username and admin flag, instead of showing a stale logged-in header

### Configurable Session Lifetime
**User story**
As an operator, I want to set the session lifetime so that longer sessions (issue #117) can be enabled once revocation exists.

**Acceptance criteria**
- `SESSION_MAX_AGE_SECONDS` sets the session cookie `max_age`. Default `86400` (unchanged behaviour)
- A non-integer or non-positive value fails startup with a clear error
- The variable is documented in `.env.example` and the feature doc, with a note that revocation makes a longer value safe

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `User.session_version = Column(Integer, nullable=False, default=0)` |
| `backend/migrate.py` | Migration `028_users_session_version`: `ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0`, guarded by `PRAGMA table_info` |
| `backend/deps.py` | `get_current_user(request, db=Depends(get_db))` validates the version against the DB; a `session_user_or_none(request, db)` helper for optional-login routes; a `bump_session_version(user)` helper |
| `backend/routers/auth.py` | Store `sv` at login and register; bump on reset-password; new `POST /logout-everywhere` |
| `backend/routers/profile.py` | Bump on password change and write the new `sv` into the current session |
| `backend/routers/admin_users.py` | New `POST /users/{user_id}/force-logout` |
| `backend/twitch.py` | `get_session_user` delegates to `get_current_user` |
| `backend/routers/cards.py` | `GET /deck` uses `session_user_or_none` |
| `backend/main.py` | `max_age` from `SESSION_MAX_AGE_SECONDS` with startup validation |
| `frontend/app-auth.js` | `loadMe` clears local auth state on 401 |
| `frontend/app-profile.js`, `frontend/index.html` | "Log out everywhere" button |
| `frontend/app-admin-users.js` | "Force logout" button per user |
| `.env.example` | `SESSION_MAX_AGE_SECONDS` |
| `markdown/features/core/auth.md` | Session validation, revocation triggers, new endpoints |
| `markdown/ui_description/profile.md`, `markdown/ui_description/admin.md` | New buttons |
| `backend/tests/test_issue_119_session_revocation.py` | Tests for the acceptance criteria |

### Step 1 — Model and migration
Add the column and migration `028_users_session_version` following the existing pattern. Run `tests/test_migrate.py`.

### Step 2 — Validate sessions in one dependency
```python
SESSION_VERSION_KEY = "sv"

def _session_user(request: Request, db) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or request.session.get(SESSION_VERSION_KEY) != (user.session_version or 0):
        request.session.clear()
        return None
    return user

def get_current_user(request: Request, db=Depends(get_db)) -> dict:
    user = _session_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user.id, "username": user.username, "is_admin": bool(user.is_admin)}

def bump_session_version(user: User) -> int:
    user.session_version = (user.session_version or 0) + 1
    return user.session_version
```
Clearing the session on a mismatch makes the response drop the stale cookie. Tests that override `get_current_user` through `app.dependency_overrides` are unaffected. Check the tests that call `get_current_user(request)` directly still work, since the logged-out path returns before touching `db`.

### Step 3 — Revocation triggers
- Login and register: `request.session["sv"] = user.session_version or 0`.
- `PUT /profile/password`: add `request: Request`, bump, commit, then set `request.session["sv"]` to the new value.
- `POST /reset-password`: bump before commit and add the bump to the existing `password_reset_completed` audit.
- `POST /logout-everywhere`: bump, audit, commit, `request.session.clear()`.
- `POST /users/{user_id}/force-logout`: `require_admin`, 404 for an unknown user, bump, audit `admin_force_logout`, commit.

### Step 4 — Other session readers
Point `twitch.get_session_user` at `get_current_user`. Use `session_user_or_none` in `GET /deck`. `rate_limit.key_by_user_or_ip` can keep reading the raw `user_id`: it only picks a rate-limit bucket, and the route's own dependency rejects the request.

### Step 5 — Session lifetime
Read `SESSION_MAX_AGE_SECONDS` (default `86400`) at import time next to the other startup checks. Raise `RuntimeError` for a non-integer or a value ≤ 0. Pass it to `SessionMiddleware(max_age=...)`.

### Step 6 — Frontend
- `loadMe`: on `res.status === 401`, reset `activeUserId`, `activeUsername` and `activeIsAdmin`, remove `username` and `is_admin` from `localStorage`, and call `applyAuthState()`.
- Profile tab: a "Log out everywhere" button under the password form. It POSTs `/logout-everywhere`, then runs the same local cleanup as `logout()`.
- Admin Users table: a "Force logout" button with `confirm()`. It POSTs `/users/{id}/force-logout` and shows a status message.

### Step 7 — Docs
Update `core/auth.md`, the two UI descriptions, `.env.example`, and the feature doc. Bump the suite-size tripwire in `test_issue_85_split_admin_router.py` by the number of new tests.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_119_session_revocation.py tests/test_migrate.py -v`, then the full suite.
- Two `TestClient`s log in as the same user. Changing the password in one keeps it logged in and gives the other 401 on `GET /me`.
- A password reset via token gives every existing session 401.
- `POST /logout-everywhere` from one client gives the other 401. Logging in again works.
- Admin force-logout gives the target's sessions 401. Non-admin gets 403, unknown id 404.
- A cookie without `sv` (built by signing `{"user_id": 1}` with the test secret) gets 401.
- Deleting a user makes their session return 401.
- `POST /twitch/link-code` with a revoked session returns 401.
- `SESSION_MAX_AGE_SECONDS=abc` and `=0` fail startup; unset keeps 86400.
- Manual: after deploying, existing browsers show the logged-out state once and can log back in. Put this in the release notes.
