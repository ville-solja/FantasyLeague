# Plan: SMTP Password Recovery

## Context

Issue #56 raised the question of whether Gmail SMTP could be used to deliver temporary
passwords in the forgot-password flow without relying on personal accounts or phone-based
two-factor authentication. The implementation uses `email_utils.send_email()` triggered from
`POST /forgot-password`; Gmail works via App Passwords with either STARTTLS (port 587) or
direct SSL (port 465). A stdout fallback is provided for local development when no SMTP host
is configured. Resolves GitHub issue #56.

## User Stories

### Temporary Password via Email
**User story**
As a user who has forgotten their password, I want to receive a temporary password at my
registered email address so that I can regain access to my account without admin intervention.

**Acceptance criteria**
- `POST /forgot-password` with a valid username sends a temporary 12-character password to the user's registered email
- The user's password is immediately replaced and `must_change_password` is set, forcing a change on next login
- The endpoint always returns `{"status": "ok"}` regardless of whether the username or email exists (prevents enumeration)
- If `SMTP_HOST` is not configured, the temporary password is logged to stdout instead of emailed

### SMTP Configuration for Email Delivery
**User story**
As an operator, I want to configure an SMTP server so that forgot-password emails are
delivered reliably without running a self-hosted mail server.

**Acceptance criteria**
- Setting `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_TLS=true` routes emails through the configured SMTP relay
- Gmail is supported via App Passwords on port 587 (STARTTLS) and port 465 (direct SSL via `SMTP_SSL=true`)
- When SMTP delivery fails, the error is caught and logged; the endpoint still returns `{"status": "ok"}`
- Omitting `SMTP_HOST` silently disables email (stdout fallback) without breaking startup

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/main.py` | `POST /forgot-password` handler |
| `backend/email_utils.py` | `send_email()` — unified SMTP client |
| `backend/models.py` | `User.must_change_password` flag |
| `markdown/features/core/auth.md` | Forgot-password flow documentation |
| `markdown/features/reference/gmail-smtp-integration.md` | Gmail SMTP operator guide |
| `markdown/features/reference/smtp-password-recovery.md` | Combined flow cross-reference |

### Status: Implemented

This plan is retrospective — all implementation steps are complete as of the `fb7f5d1` commit
("SMTP and vulnerability patching"). No further implementation is required.

**What was built:**

1. `email_utils.send_email(to, subject, body)` — unified SMTP client supporting STARTTLS
   (port 587) and direct SSL (port 465) via `SMTP_SSL=true`.
2. `POST /forgot-password` — generates a 12-character temporary password, writes it to the
   DB, sets `must_change_password=True`, calls `send_email()`, and writes a
   `password_reset_requested` audit log entry.
3. `must_change_password` flag forces a password change on the next login before any other
   actions are available; cleared by `PUT /profile/password`.
4. Stdout fallback when `SMTP_HOST` is unset, so local development requires no email config.

## Verification

- With `SMTP_HOST` set to a valid Gmail config, `POST /forgot-password` sends an email and
  the user can log in with the temporary password
- Without `SMTP_HOST`, the temporary password appears in stdout and the endpoint still returns
  `{"status": "ok"}`
- `must_change_password=true` after a reset; cleared by `PUT /profile/password`
- SMTP paths covered by `backend/tests/test_gmail_smtp_integration.py` (9 tests)
