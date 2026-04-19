# Profile & Account Management

Each user has a profile that holds their display name, linked Dota 2 player, and password. The profile tab lets users manage all of these without admin involvement.

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

`twitch_linked` is `true` if the user has completed the Twitch account linking flow. See `twitch-extension.md`.

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

Linking a player ID is optional but enables the profile tab to display the user's own Dota stats alongside their fantasy performance.

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
- Clears the `must_change_password` flag if set (see Forgot Password below).

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

**After logging in with a temporary password**, the user must change their password via `PUT /profile/password`. The frontend should detect the `must_change_password` flag (returned by `GET /me`) and prompt accordingly.

**If SMTP is not configured** (`SMTP_HOST` unset), the email step is skipped and the temporary password is logged to stdout instead. The password change and audit log still occur.

---

## Email Configuration

Outgoing emails use Python's standard `smtplib`. All settings are optional — if `SMTP_HOST` is not set, email is disabled entirely.

| Variable | Default | Description |
|---|---|---|
| `SMTP_HOST` | *(empty — disables email)* | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(empty)* | SMTP login username |
| `SMTP_PASSWORD` | *(empty)* | SMTP login password |
| `SMTP_FROM` | Falls back to `SMTP_USER`, then `noreply@fantasy` | Sender address in outgoing emails |
| `SMTP_TLS` | `true` | Use STARTTLS; set to `false` for plain SMTP |
| `APP_NAME` | `Kanaliiga Fantasy` | Prefix used in email subject lines |
