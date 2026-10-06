# Authentication & Account Management

User accounts, sessions, and profile management for the Kana Cards app. Sessions are server-side: each login creates a `user_sessions` row, and the signed cookie (Starlette's `SessionMiddleware`) carries only a random session ID. Idle and absolute limits depend on the role, and admins confirm their password before destructive actions (issue #117; see Session Validation and Revocation below and `reference/longer-sessions.md`).

---

## Registration

### `POST /register`

Creates a new user account and immediately starts a session. No authentication required.

```json
{ "username": "SomeUser", "email": "user@example.com", "password": "secret123" }
```

On success, returns `{ username, is_admin, tokens }` and sets the session cookie.

#### Field validation rules

| Field | Rule | Error |
|---|---|---|
| `username` | Required. 1–64 characters. Only letters `A-Z` `a-z`, digits `0-9`, underscore `_` and hyphen `-` (`^[A-Za-z0-9_-]+$`, `check_username()` in `backend/auth.py`; see `reference/security-audit-3.md`). | 422 if missing, exceeds limit, or contains any other character; the message lists the allowed characters. 409 if already taken. |
| `email` | Required. 3–254 characters. Must fully match `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`, so spaces, CR and LF are rejected. | 422 if missing, malformed, or exceeds limit. 409 if already registered. |
| `password` | Required. 6–128 characters and at most 72 UTF-8 bytes (bcrypt's limit). | 422 if missing or outside length bounds. |

`POST /login` does not apply the 72-byte cap: accounts created before the cap may have longer
passwords, and bcrypt 4.x truncates the same way when hashing and verifying. Nor does it apply
the username character rule, so accounts created before the rule keep logging in with their
existing name.

The register form shows the allowed username characters under the field before submission.

The frontend validates all three fields before submitting and highlights the offending field inline. Server-side 409 conflicts (duplicate username or email) are also mapped back to the relevant field.

New users receive `INITIAL_TOKENS` tokens on registration (default: 5). Records a `user_register` audit log entry.

---

## Session Endpoints

### `POST /login`

Authenticates with username and password.

```json
{ "username": "SomeUser", "password": "password" }
```

- Returns 401 if credentials are invalid.
- Returns 401 with `"Temporary password has expired. Please request a new password reset."` if the
  account still holds an outstanding **pre-fix legacy** temporary password (`must_change_password`
  set and `temp_password_expires_at` in the past). This check is legacy-only — no current code
  path sets these fields anymore. See `reference/temp-password-expiry.md`.
- Returns `{ "username", "is_admin", "tokens" }` and sets the session cookie. (`must_change_password` is only returned by `GET /me`.)
- Records a `user_login` audit log entry.
- Always starts a new session: a new `user_sessions` row and a new session ID in the cookie, even
  when the request already carried a valid session (that older session of the browser is deleted).
  `POST /register` does the same. The cookie payload is only `{"sid": "<token>"}`.
- **Twitch soft accounts can't log in** (issue #157). Accounts created by the Twitch panel's Join
  (`account_type="twitch"`) have no username, email or password, so login and forgot-password never
  find them by username; `auth.verify_password` returns False for an empty hash; and
  `deps._session_user` treats a soft account as no user even if a session row existed. Only
  `POST /twitch/join` creates them; registration always creates `account_type="full"`. See
  `reference/twitch-extension-policy-compliance.md`.

### `POST /logout`

Deletes the current session row and clears the cookie, so a copy of the cookie stops working.
No request body required. Always returns `{ "status": "ok" }`. Other devices stay logged in.

### `POST /logout-everywhere`

Login required (401 without a session). Deletes every session row of the caller, which ends every
session on every device, then clears the current cookie. Writes a `user_logout_everywhere` audit
entry and returns `{ "status": "ok" }`.

### `POST /reauth`

Login required; open to any logged-in user, not only admins. Body `{ "password" }`. Confirms the
current user's password for this session and stores `reauth_at` on the session row; destructive
admin endpoints (`deps.require_recent_reauth`) and a player's Twitch connection actions
(`deps.require_recent_player_reauth`: Connect, merge and Disconnect, issue #160) then accept the
session for `ADMIN_REAUTH_SECONDS` (default 600). Wrong password: 401 `"Incorrect password"`, counted toward
the per-username login lockout (`LOGIN_LOCKOUT_THRESHOLD`); a locked-out username gets 429 with the
same message as `/login`. If the current session row is missing (a defensive check), 401
`"Not authenticated"`. Limited by `RATE_LIMIT_LOGIN`. Writes an audit entry on success (`ok`) and
on failure (`failed: …`): `admin_reauth` for admins, `player_reauth` for everyone else.

### `GET /sessions`

Login required. Lists the caller's unexpired sessions as
`[{ "id", "created_at", "last_seen_at", "current" }]`, newest activity first. `id` is an opaque
row handle; the session ID and its hash are never returned.

### `DELETE /sessions/{id}`

Login required. Ends one of the caller's own sessions; any other id returns 404. Ending the current
session also clears the cookie. Returns `{ "status": "ok", "current": <bool> }`.

### `GET /me`

Returns the current session user. Returns 401 if unauthenticated. Implemented in
`backend/routers/profile.py`, not `routers/auth.py`, despite living in this "Session Endpoints"
section alongside the other endpoints below (which are all in `auth.py`).

```json
{
  "user_id": 3,
  "username": "SomeUser",
  "is_admin": false,
  "tokens": 4,
  "must_change_password": false
}
```

`must_change_password` is `true` only for an account still holding an outstanding **pre-fix
legacy** temporary password (see `reference/temp-password-expiry.md`). The frontend detects this
flag on login and redirects to the profile password change form before allowing other actions.
`POST /forgot-password` no longer sets this flag — see the Forgot Password section below.

---

## Viewing a Profile

### `GET /profile/{user_id}`

Returns basic profile information for any user by ID. Requires login — any authenticated
account can view any other user's profile (this is not an ownership restriction, just a
login requirement; see `reference/profile-requires-login.md`). Returns 401 if unauthenticated.
The response shape and content for an authenticated request are otherwise unchanged.

```json
{
  "id": 3,
  "username": "SomeUser",
  "player_id": 123456789,
  "player_name": "SomePlayer",
  "player_avatar_url": "https://...",
  "twitch_linked": true,
  "tags": [{"key": "caster", "label": "Caster"}],
  "past_seasons": [{"season_label": "Season 15", "points": 1240.0, "rank": 3}]
}
```

`twitch_linked` is `true` when the panel recognises the account (`users.twitch_user_id` is set). Profile's Twitch section reads `GET /twitch/connection` instead (see **Twitch Connection** below).

`player_name` and `player_avatar_url` are `null` if the user has not linked a Dota 2 account, or if the linked `player_id` does not exist in the local database.

`tags` is an array of admin-granted tag objects (`key` + `label`); empty array when the user holds no tags.

`past_seasons` lists every archived season the user appears in (most recent first); empty array if none. See `reference/season-lifecycle.md`.

---

## Updating Username

### `PUT /profile/username`

Changes the authenticated user's display name. Requires login.

```json
{ "username": "NewName" }
```

- Returns 409 if the username is already taken by another account.
- Returns 422 unless the value matches the same rule as registration: 1–64 characters of
  letters, digits, `_` and `-` (see `reference/security-audit-3.md`). Surrounding whitespace
  is rejected rather than stripped; the profile form trims it before sending and shows the
  allowed characters under the field.
- On success, writes a `username_changed` audit entry (`old=… new=…`). The session cookie does not
  carry the username; `GET /me` reads it from the database, so the change shows at once.

---

## Linking a Dota 2 Player

### `PUT /profile/player-id`

Links the authenticated user's account to an OpenDota player ID. Requires login.

```json
{ "player_id": 123456789 }
```

Set `player_id` to `null` to unlink. The response includes `player_name` and `player_avatar_url` resolved from the local database (null if the player has not been ingested yet).

---

## Changing Password

### `PUT /profile/password`

Changes the authenticated user's password. Requires login and the current password.

```json
{
  "current_password": "old-password",
  "new_password": "new-password"
}
```

- Returns 401 if `current_password` does not match the stored hash.
- `new_password` must be at least 6 characters and at most 72 UTF-8 bytes (422 otherwise).
  `current_password` is not byte-capped.
- Clears the `must_change_password` flag if set.
- Deletes the user's outstanding password-reset tokens, so an old reset link stops working.
- Deletes every other session of the user and gives the requester's session a new ID (a new row
  and cookie): the requester stays logged in and every other session gets 401 on its next request.
  A rejected change (wrong current password) changes nothing.

---

## Forgot Password

Password reset is a two-step, token-based flow (see `reference/password-reset-token-flow.md` for
the full design rationale — this replaced an earlier design that mutated the real password
immediately on `POST /forgot-password`, resolving GitHub issue #123). Requesting a reset never
touches the account's real password; only completing the reset with a valid token does.

### `POST /forgot-password`

Requests a password reset for the given username. Does **not** change the account's password.

```json
{ "username": "SomeUser" }
```

**Flow:**

1. If the username doesn't resolve to an account with an email, or the account is within its
   per-username cooldown (see `reference/forgot-password-cooldown.md`), the endpoint fast-exits
   with the bcrypt timing-equalization call and returns `{"status": "ok"}` — no state changes.
2. Any existing `PasswordResetToken` row for the account is deleted (only one live token per
   user at a time — same invalidate-on-regenerate precedent as the retired `TwitchLinkCode`).
3. A new single-use token is generated (`secrets.token_urlsafe(32)`) and stored with an
   `expires_at` of `now + PASSWORD_RESET_TOKEN_TTL_HOURS` hours (default `1`).
4. A `password_reset_requested` audit log entry is written.
5. An email is sent to the address on file containing a clickable link
   (`{APP_BASE_URL}/?reset_token={token}`, only if `APP_BASE_URL` is configured) and the raw
   token as a manual-entry fallback (always included). The wording states the current password
   remains valid and nothing changes until the reset is completed.

The endpoint returns `{"status": "ok"}` regardless of whether the username exists, to
prevent username enumeration. The one exception: when SMTP is configured and the send fails or
raises, the new token, the audit entry and the cooldown stamp are rolled back (any previous token
is kept) and the endpoint returns 503, so the user knows to retry. It never sets `user.password_hash`, `must_change_password`, or
`temp_password_expires_at` — those fields are untouched by this endpoint entirely.

**If SMTP is not configured** (`SMTP_HOST` unset), the email step is skipped with a logged
warning — the endpoint still returns `{"status": "ok"}` and the token row is still created, but the token is
not visible anywhere (it is not logged). To use this flow locally, configure a real SMTP relay
or temporarily set `SMTP_HOST` for testing.

### `POST /reset-password`

Completes a password reset using a token obtained from the forgot-password email. No
authentication required (the token itself is the credential).

```json
{ "token": "...", "new_password": "new-password" }
```

- `new_password` is subject to `Field(min_length=6, max_length=128)` and at most 72 UTF-8 bytes.
- An invalid, unknown, already-used, or expired token returns 400 with no side effects — the
  account is completely untouched.
- A valid, unexpired token:
  1. Sets `user.password_hash` to the new password.
  2. Clears any legacy `must_change_password`/`temp_password_expires_at` state on the account
     (cleanup matching what `PUT /profile/password` already does).
  3. Deletes every session row of the user, so every existing session gets 401.
  4. Deletes the token row (single-use — resubmitting the same token afterward returns 400).
  5. Records a `password_reset_completed` audit log entry (detail `all sessions revoked`).
  6. Returns `{"status": "ok"}`.

Limited to 10 requests a minute per IP (`RATE_LIMIT_RESET_PASSWORD`); the next returns 429.

---

## Session Validation and Revocation

Every route that needs login goes through `get_current_user` (`backend/deps.py`), which calls
`sessions.validate_request` (`backend/sessions.py`). It looks up the `user_sessions` row by
`sha256(sid)` and rejects the session (401, cookie cleared) when there is no row, the user no longer
exists, or the row is past its role's limits:

| Account | Idle limit (`now - last_seen_at`) | Absolute limit (`now - created_at`) |
|---|---|---|
| Player | `SESSION_IDLE_SECONDS` (14 days) | `SESSION_ABSOLUTE_SECONDS` (30 days) |
| Admin | `ADMIN_SESSION_IDLE_SECONDS` (2 hours) | `ADMIN_SESSION_ABSOLUTE_SECONDS` (12 hours) |

An expired row is deleted on the spot, and the week maintenance loop deletes the rest on its first pass after
the app starts and then once a day.
`last_seen_at` is written at most once per `SESSION_TOUCH_SECONDS` (5 minutes). The returned
`user_id`, `username` and `is_admin` come from the database row, not the cookie.
The session-cookie Twitch routes (`GET /twitch/connection`, `POST /twitch/merge/confirm`,
`POST /twitch/disconnect`, the `/auth/twitch/*` sign-in, issue #160) use the same check, and the optional-login routes `GET /deck` and
`GET /deck/booster` treat an invalid session as logged out (`session_user_or_none`).

Revocation deletes rows: `POST /logout` (this session), `PUT /profile/password` (all others; the
requester gets a new ID), `POST /reset-password`, `POST /logout-everywhere`, the admin-only
`POST /users/{user_id}/force-logout` and `POST /users/{user_id}/toggle-admin` (all of the target's
sessions; see `core/admin.md`). `users.session_version` from issue #119 stays in the schema but is
no longer read. Cookies issued before #117 carry no `sid`, so every user logs in once after that
release. When `GET /me` returns 401 the frontend clears its stored username and admin flag and
shows the logged-out state. Design, accepted risk and trade-offs: `reference/longer-sessions.md`
and `reference/session-revocation.md`.

---

## Session Cookie

Sessions are signed with `SECRET_KEY`. In production `SECRET_KEY` must be set — the app refuses
to start without it unless `DEBUG=true` **or** `TWITCH_LOCAL_DEV=true` (both are treated as
equivalent local-dev bypasses at startup, `backend/main.py`). Conversely, setting
`TWITCH_LOCAL_DEV=true` together with a real `SECRET_KEY` raises a startup `RuntimeError` —
that combination would silently accept the insecure Twitch JWT bypass in what looks like a
production config, so the app refuses to boot rather than risk it.

The cookie holds only the session ID. Its `Max-Age` is the larger absolute limit (default 30 days);
the server enforces the actual limits above. Under `HTTPS_ONLY=true` the cookie is named
`__Host-session` (`Secure`, `Path=/`, no `Domain`), which pins it to the exact host; without it
(local dev) it is named `session`, since browsers reject the `__Host-` prefix without `Secure`.
`HttpOnly` and `SameSite=Lax` are always set. `SameSite` must stay `Lax`, not `Strict`: the
Twitch sign-in callback (`GET /auth/twitch/callback`, #160) is a cross-site top-level GET from
Twitch and needs the session cookie (a comment at the setting in `main.py` says so).

The six session settings are validated at startup: a non-integer or non-positive value, an idle
limit larger than its absolute limit, or `SESSION_TOUCH_SECONDS` not smaller than
`ADMIN_SESSION_IDLE_SECONDS` stops the app with a `RuntimeError`. `SESSION_MAX_AGE_SECONDS` from
issue #119 is still accepted as an alias for `SESSION_ABSOLUTE_SECONDS`, with a deprecation warning.

**Accepted risk:** the 14-day player idle limit is longer than the OWASP Session Management Cheat
Sheet's typical examples. It is accepted because player accounts hold no payment data, every session
can be revoked on the server, and the 30-day absolute limit meets NIST SP 800-63B AAL1. Admins get
much shorter limits plus re-authentication. See `reference/longer-sessions.md`.

Set `HTTPS_ONLY=true` when running behind an HTTPS reverse proxy (e.g. nginx, Caddy) to enable the `Secure` flag on the session cookie. It is required outside local dev: the app refuses to start without it unless `DEBUG=true` or `TWITCH_LOCAL_DEV=true` (the latter only with `SECRET_KEY` unset; issue #118, see `reference/https-enforcement.md`).

---

## Twitch Connection

Players connect a Twitch account on Profile with Twitch's own sign-in (OpenID Connect; issue #160).
It never logs anyone in: it stores the verified Twitch user id on the logged-in account
(`users.twitch_account_id`), so the Kana Cards Twitch panel plays with the website account, and
offers once to merge a Twitch panel collection into the account. Connect, merge and Disconnect need
a recent `POST /reauth`. Twitch's tokens are never stored. Endpoints, checks and configuration
(`TWITCH_OAUTH_CLIENT_ID`, `TWITCH_OAUTH_CLIENT_SECRET`, `TWITCH_OAUTH_REDIRECT_URI`):
`reference/twitch-account-connection.md`.

---

## Password Manager Autofill

The login, registration, password reset, profile change-password and admin re-login fields are each a `<form>` (`#loginForm`, `#registerForm`, `#resetPasswordForm`, `#changePasswordForm`, `#reauthForm`) with `name` and `autocomplete` tokens (`username`, `current-password`, `new-password`, `email`, `one-time-code`), so password managers fill the login and offer to save or update passwords (issue #158). Each form's `submit` event calls `preventDefault()` and the existing function, so the requests above are unchanged and the page never reloads. Forms with a lone password field carry a visually hidden, read-only username helper. See `reference/password-manager-autofill.md`.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(insecure dev default)* | Session signing key — **must be set in production** |
| `HTTPS_ONLY` | `false` | Enables `Secure` cookie flag when behind an HTTPS reverse proxy — **must be `true` in production**; startup fails without it unless `DEBUG`/`TWITCH_LOCAL_DEV` is set (`TWITCH_LOCAL_DEV` only with `SECRET_KEY` unset) |
| `SESSION_IDLE_SECONDS` | `1209600` (14 days) | Player idle limit (accepted risk, see above) |
| `SESSION_ABSOLUTE_SECONDS` | `2592000` (30 days) | Player limit from login; also the cookie `Max-Age` when it is the larger absolute limit |
| `SESSION_TOUCH_SECONDS` | `300` | Minimum interval between `last_seen_at` writes; must be smaller than `ADMIN_SESSION_IDLE_SECONDS` |
| `ADMIN_SESSION_IDLE_SECONDS` | `7200` (2 h) | Admin idle limit |
| `ADMIN_SESSION_ABSOLUTE_SECONDS` | `43200` (12 h) | Admin limit from login |
| `ADMIN_REAUTH_SECONDS` | `600` (10 min) | How long a `POST /reauth` covers destructive admin actions |
| `SESSION_MAX_AGE_SECONDS` | *(unset)* | Deprecated alias for `SESSION_ABSOLUTE_SECONDS` (issue #119), with a startup warning; ignored when `SESSION_ABSOLUTE_SECONDS` is set. Session revocation is server-side row deletion |
| `DEBUG` | `false` | Bypasses the `SECRET_KEY` requirement and the `HTTPS_ONLY` startup check for local dev — **never set in production** |
| `INITIAL_TOKENS` | `5` | Tokens granted to each newly registered user |
| `TEMP_PASSWORD_TTL_HOURS` | `24` | Legacy-only — no current code path issues new temp passwords. See `reference/temp-password-expiry.md` |
| `PASSWORD_RESET_TOKEN_TTL_HOURS` | `1` | Hours before a `POST /forgot-password` reset token expires |
| `APP_BASE_URL` | *(empty)* | Public base URL used to build a clickable reset link in emails; if unset, only the raw code is emailed |
| `SMTP_HOST` | *(empty — disables email)* | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(empty)* | SMTP login username |
| `SMTP_PASSWORD` | *(empty)* | SMTP login password |
| `SMTP_FROM` | Falls back to `SMTP_USER`, then `noreply@fantasy` | Sender address in outgoing emails |
| `SMTP_TLS` | `true` | Use STARTTLS; set to `false` for plain SMTP |
| `SMTP_SSL` | `false` | Use direct SSL (`smtplib.SMTP_SSL`, port 465); takes priority over `SMTP_TLS` |
| `APP_NAME` | `Kana Cards` | Prefix used in email subject lines |
