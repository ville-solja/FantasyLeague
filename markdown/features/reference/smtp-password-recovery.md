# SMTP Password Recovery

The forgot-password flow creates a single-use reset token and delivers a link/code containing
it to the user's registered email address via SMTP (see `password-reset-token-flow.md` for the
full design — this replaced an earlier design that emailed a working temporary password). When
no SMTP provider is configured (`SMTP_HOST` unset), the email is silently skipped — the token
row is still created, but it is not visible anywhere. A real SMTP relay is required to use this
flow end-to-end in local development.

---

## Flow

1. User submits `POST /forgot-password` with their username. This never changes the account's
   real password — it remains valid and usable throughout.
2. Any existing `PasswordResetToken` for the account is invalidated (deleted), then a new
   single-use token is created with an expiry of `PASSWORD_RESET_TOKEN_TTL_HOURS` hours
   (default `1`).
3. A `password_reset_requested` audit log entry is written.
4. An email is sent to the address on file containing a clickable link
   (`{APP_BASE_URL}/?reset_token={token}`, if configured) and the raw token as a manual-entry
   fallback (always included). If SMTP is not configured (`SMTP_HOST` unset), the email step is
   silently skipped — the token row still exists but is not logged or otherwise visible.
5. The endpoint always returns `{"status": "ok"}` regardless of username or email existence,
   preventing account enumeration.
6. The user completes the reset via `POST /reset-password` with the token and a new password —
   this is the only step that actually changes `user.password_hash`. See the full endpoint
   contract in [Auth & Accounts](../core/auth.md).

---

## Endpoints

### `POST /forgot-password`

No authentication required. Accepts `{ "username": "..." }`. Always returns `{"status": "ok"}`
and never mutates the account's password. See [Auth & Accounts](../core/auth.md) for the full
schema and flow description.

### `POST /reset-password`

No authentication required (the token is the credential). Accepts
`{ "token": "...", "new_password": "..." }`. Valid token → password changed, token consumed.
Invalid/expired/reused token → 400, no side effects. See [Auth & Accounts](../core/auth.md).

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
