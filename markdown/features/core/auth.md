# Authentication & Account Management

User accounts, sessions, and profile management for the Kana Cards app. Sessions are server-side, stored in a signed cookie managed by Starlette's `SessionMiddleware`.

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
| `username` | Required. 1–64 characters. May not contain `<`, `>`, `"`, or `'` (see `reference/username-xss-fix.md`). | 422 if missing, exceeds limit, or contains a rejected character. 409 if already taken. |
| `email` | Required. 3–254 characters. Must match `user@domain.tld` format. | 422 if missing, malformed, or exceeds limit. 409 if already registered. |
| `password` | Required. 6–128 characters. | 422 if missing or outside length bounds. |

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

### `POST /logout`

Clears the session cookie. No request body required. Always returns `{ "status": "ok" }`.

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

`twitch_linked` is `true` if the user has completed the Twitch account linking flow. See `core/twitch-extension.md`.

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

- Leading/trailing whitespace is stripped.
- Returns 409 if the username is already taken by another account.
- Returns 422 if the stripped value is empty, or if it contains `<`, `>`, `"`, or `'`
  (see `reference/username-xss-fix.md`).

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
- `new_password` must be at least 6 characters.
- Clears the `must_change_password` flag if set.

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
   user at a time — same invalidate-on-regenerate precedent as `TwitchLinkCode`).
3. A new single-use token is generated (`secrets.token_urlsafe(32)`) and stored with an
   `expires_at` of `now + PASSWORD_RESET_TOKEN_TTL_HOURS` hours (default `1`).
4. A `password_reset_requested` audit log entry is written.
5. An email is sent to the address on file containing a clickable link
   (`{APP_BASE_URL}/?reset_token={token}`, only if `APP_BASE_URL` is configured) and the raw
   token as a manual-entry fallback (always included). The wording states the current password
   remains valid and nothing changes until the reset is completed.

The endpoint always returns `{"status": "ok"}` regardless of whether the username exists, to
prevent username enumeration. It never sets `user.password_hash`, `must_change_password`, or
`temp_password_expires_at` — those fields are untouched by this endpoint entirely.

**If SMTP is not configured** (`SMTP_HOST` unset), the email step is silently skipped — the
endpoint still returns `{"status": "ok"}` and the token row is still created, but the token is
not visible anywhere (it is not logged). To use this flow locally, configure a real SMTP relay
or temporarily set `SMTP_HOST` for testing.

### `POST /reset-password`

Completes a password reset using a token obtained from the forgot-password email. No
authentication required (the token itself is the credential).

```json
{ "token": "...", "new_password": "new-password" }
```

- `new_password` is subject to `Field(min_length=6, max_length=128)`.
- An invalid, unknown, already-used, or expired token returns 400 with no side effects — the
  account is completely untouched.
- A valid, unexpired token:
  1. Sets `user.password_hash` to the new password.
  2. Clears any legacy `must_change_password`/`temp_password_expires_at` state on the account
     (cleanup matching what `PUT /profile/password` already does).
  3. Deletes the token row (single-use — resubmitting the same token afterward returns 400).
  4. Records a `password_reset_completed` audit log entry.
  5. Returns `{"status": "ok"}`.

Not separately rate-limited beyond the app-wide baseline — the token has 256 bits of entropy and
is single-use, so a dedicated stricter limit wasn't warranted.

---

## Session Cookie

Sessions are signed with `SECRET_KEY`. In production `SECRET_KEY` must be set — the app refuses
to start without it unless `DEBUG=true` **or** `TWITCH_LOCAL_DEV=true` (both are treated as
equivalent local-dev bypasses at startup, `backend/main.py`). Conversely, setting
`TWITCH_LOCAL_DEV=true` together with a real `SECRET_KEY` raises a startup `RuntimeError` —
that combination would silently accept the insecure Twitch JWT bypass in what looks like a
production config, so the app refuses to boot rather than risk it.

Set `HTTPS_ONLY=true` when running behind an HTTPS reverse proxy (e.g. nginx, Caddy) to enable the `Secure` flag on the session cookie.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(insecure dev default)* | Session signing key — **must be set in production** |
| `HTTPS_ONLY` | `false` | Enables `Secure` cookie flag when behind an HTTPS reverse proxy |
| `DEBUG` | `false` | Bypasses `SECRET_KEY` requirement for local dev — **never set in production** |
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
