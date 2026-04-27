# Authentication & Account Management

User accounts, sessions, and profile management for the FantasyLeague app. Sessions are server-side, stored in a signed cookie managed by Starlette's `SessionMiddleware`.

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
| `username` | Required. 1–64 characters. | 422 if missing or exceeds limit. 409 if already taken. |
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
- Returns `{ "username", "is_admin", "tokens", "must_change_password" }` and sets the session cookie.
- Records a `user_login` audit log entry.

### `POST /logout`

Clears the session cookie. No request body required. Always returns `{ "status": "ok" }`.

### `GET /me`

Returns the current session user. Returns 401 if unauthenticated.

```json
{
  "user_id": 3,
  "username": "SomeUser",
  "is_admin": false,
  "tokens": 4,
  "must_change_password": false
}
```

`must_change_password` is `true` after a forgot-password reset. The frontend detects this flag on login and redirects to the profile password change form before allowing other actions.

---

## Viewing a Profile

### `GET /profile/{user_id}`

Returns basic public information for any user by ID. No authentication required.

```json
{
  "id": 3,
  "username": "SomeUser",
  "player_id": 123456789,
  "player_name": "SomePlayer",
  "player_avatar_url": "https://...",
  "twitch_linked": true
}
```

`twitch_linked` is `true` if the user has completed the Twitch account linking flow. See `core/twitch-extension.md`.

`player_name` and `player_avatar_url` are `null` if the user has not linked a Dota 2 account, or if the linked `player_id` does not exist in the local database.

---

## Updating Username

### `PUT /profile/username`

Changes the authenticated user's display name. Requires login.

```json
{ "username": "NewName" }
```

- Leading/trailing whitespace is stripped.
- Returns 409 if the username is already taken by another account.
- Returns 422 if the stripped value is empty.

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

### `POST /forgot-password`

Issues a temporary password to the user's registered email address.

```json
{ "username": "SomeUser" }
```

**Flow:**

1. A random 12-character temporary password is generated.
2. The user's password is immediately replaced with the temporary one.
3. The `must_change_password` flag is set to `true` on the user record.
4. The temporary password is emailed to the address on file.
5. A `password_reset_requested` audit log entry is written.

The endpoint always returns `{"status": "ok"}` regardless of whether the username exists, to prevent username enumeration.

**If SMTP is not configured** (`SMTP_HOST` unset), the email step is skipped and the temporary password is logged to stdout instead.

---

## Session Cookie

Sessions are signed with `SECRET_KEY`. In production `SECRET_KEY` must be set — the app refuses to start without it unless `DEBUG=true`.

Set `HTTPS_ONLY=true` when running behind an HTTPS reverse proxy (e.g. nginx, Caddy) to enable the `Secure` flag on the session cookie.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(insecure dev default)* | Session signing key — **must be set in production** |
| `HTTPS_ONLY` | `false` | Enables `Secure` cookie flag when behind an HTTPS reverse proxy |
| `DEBUG` | `false` | Bypasses `SECRET_KEY` requirement for local dev — **never set in production** |
| `INITIAL_TOKENS` | `5` | Tokens granted to each newly registered user |
| `SMTP_HOST` | *(empty — disables email)* | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(empty)* | SMTP login username |
| `SMTP_PASSWORD` | *(empty)* | SMTP login password |
| `SMTP_FROM` | Falls back to `SMTP_USER`, then `noreply@fantasy` | Sender address in outgoing emails |
| `SMTP_TLS` | `true` | Use STARTTLS; set to `false` for plain SMTP |
| `APP_NAME` | `Kanaliiga Fantasy` | Prefix used in email subject lines |
