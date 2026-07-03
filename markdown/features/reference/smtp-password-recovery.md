# SMTP Password Recovery

The forgot-password flow generates a temporary password and delivers it to the user's
registered email address via SMTP. When no SMTP provider is configured the password falls back
to stdout, allowing local development without an email account.

---

## Flow

1. User submits `POST /forgot-password` with their username.
2. A random 12-character temporary password is generated.
3. The user's password is replaced with the temporary one and `must_change_password` is set to `true`.
4. The temporary password is emailed to the address on file (or logged to stdout if SMTP is unconfigured).
5. A `password_reset_requested` audit log entry is written.
6. The endpoint always returns `{"status": "ok"}` regardless of username or email existence, preventing account enumeration.

On next login the app detects `must_change_password=true` and redirects to the Profile tab's
password form before granting access to any other tab. The flag is cleared by
`PUT /profile/password`.

---

## Endpoints

### `POST /forgot-password`

No authentication required. Accepts `{ "username": "..." }`. See
[Auth & Accounts](../core/auth.md) for the full schema and flow description.

---

## SMTP Configuration

See [Gmail SMTP Integration](gmail-smtp-integration.md) for the operator guide — App Password
setup, connection mode selection (STARTTLS vs SSL), and troubleshooting.

| Variable | Default | Description |
|---|---|---|
| `SMTP_HOST` | *(empty — stdout fallback)* | SMTP hostname; leave unset for local dev |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(empty)* | SMTP login username |
| `SMTP_PASSWORD` | *(empty)* | App Password or SMTP credential |
| `SMTP_FROM` | Falls back to `SMTP_USER` | Sender address shown in outgoing emails |
| `SMTP_TLS` | `true` | Use STARTTLS (port 587) |
| `SMTP_SSL` | `false` | Use direct SSL (port 465); takes priority over `SMTP_TLS` |
