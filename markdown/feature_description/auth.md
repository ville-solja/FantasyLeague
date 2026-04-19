# Authentication

User accounts and sessions for the FantasyLeague app. Sessions are server-side, stored in a signed cookie managed by Starlette's `SessionMiddleware`.

---

## Endpoints

### `POST /register`

Creates a new user account and logs the user in immediately.

```json
{ "username": "SomeUser", "email": "user@example.com", "password": "securepass" }
```

- Username must be unique — 409 if taken.
- Email must be a valid address and unique — 409 if already registered.
- Password minimum length: 6 characters.
- New users receive `INITIAL_TOKENS` tokens on registration (default: 5).
- Returns `{ "username", "is_admin", "tokens" }` and sets the session cookie.
- Records a `user_register` audit log entry.

---

### `POST /login`

Authenticates with username and password.

```json
{ "username": "SomeUser", "password": "password" }
```

- Returns 401 if credentials are invalid.
- Returns `{ "username", "is_admin", "tokens" }` and sets the session cookie.
- Records a `user_login` audit log entry.

---

### `POST /logout`

Clears the session cookie. No request body required. Always returns `{ "status": "ok" }`.

---

### `GET /me`

Returns the current session user. Returns 401 if not logged in.

```json
{
  "user_id": 3,
  "username": "SomeUser",
  "is_admin": false,
  "tokens": 4,
  "must_change_password": false
}
```

`must_change_password` is `true` after a forgot-password reset (see `profile.md`). The frontend should detect this flag on login and redirect to the profile password change form before allowing other actions.

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
