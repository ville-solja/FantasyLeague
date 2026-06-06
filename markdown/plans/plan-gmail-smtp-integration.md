# Plan: Gmail SMTP Integration

## Context
Password reset emails are sent via a generic SMTP client in `backend/email_utils.py`. The
existing implementation supports STARTTLS (port 587) and plain SMTP, but not direct SSL
(port 465). Gmail — the most common operator choice — works on both port 587 (STARTTLS) and
port 465 (SSL); the current code cannot use the SSL path. This plan adds SSL mode to
`email_utils.py`, updates `.env.example` with a ready-to-copy Gmail block, and creates an
operator setup guide. *Resolves GitHub issue #67.*

## User Stories

### Configure Gmail as the SMTP Sender
**User story**
As an operator, I want to configure Gmail (or Google Workspace) as the SMTP server for
password reset emails, so that I can leverage a trusted, high-deliverability email service
without running my own mail server.

**Acceptance criteria**
- Setting `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD` (App Password), and `SMTP_TLS=true` results in password reset emails being sent successfully via Gmail STARTTLS
- The `.env.example` file contains a commented Gmail example block that operators can copy-paste and fill in
- The operator guide in `markdown/features/reference/gmail-smtp-integration.md` describes the App Password setup steps

### Support Gmail SSL Connection (Port 465)
**User story**
As an operator, I want the app to support Gmail's direct SSL connection mode on port 465,
so that I have the full range of Gmail SMTP options and am not limited to STARTTLS.

**Acceptance criteria**
- Setting `SMTP_SSL=true` causes the email client to use `smtplib.SMTP_SSL` instead of STARTTLS
- `SMTP_SSL=true` with `smtp.gmail.com:465` and a valid App Password sends email successfully
- `SMTP_SSL` and `SMTP_TLS` are mutually exclusive: when `SMTP_SSL=true`, the `SMTP_TLS` value is ignored
- The `SMTP_SSL` env var is documented in `.env.example` and `markdown/features/reference/commands.md`

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/email_utils.py` | Add `SMTP_SSL` env var support using `smtplib.SMTP_SSL` |
| `.env.example` | Add commented Gmail example block and `SMTP_SSL` var |
| `markdown/features/reference/commands.md` | Add `SMTP_SSL` row to env vars table |
| `markdown/features/reference/gmail-smtp-integration.md` | New operator guide (created by product-planner) |

### Step 1 — Add SSL mode to `email_utils.py`

Extend the module docstring to mention `SMTP_SSL` and add a third connection branch:

```python
"""Minimal SMTP email sender using Python stdlib.

Configuration via environment variables:
  SMTP_HOST      — required; if not set, sending is disabled and a warning is printed
  SMTP_PORT      — default 587
  SMTP_USER      — optional SMTP login username
  SMTP_PASSWORD  — optional SMTP login password
  SMTP_FROM      — sender address; defaults to SMTP_USER if set, else "noreply@fantasy"
  SMTP_TLS       — "true" (default) uses STARTTLS; "false" uses plain SMTP
  SMTP_SSL       — "true" uses smtplib.SMTP_SSL (direct SSL, typically port 465);
                   takes priority over SMTP_TLS when set
"""
```

In `send_email()`, read `SMTP_SSL` and branch before the existing `use_tls` check:

```python
use_ssl = os.getenv("SMTP_SSL", "false").lower() == "true"
use_tls = os.getenv("SMTP_TLS", "true").lower() != "false"

try:
    if use_ssl:
        with smtplib.SMTP_SSL(host, port) as smtp:
            if user:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_address], msg.as_string())
    elif use_tls:
        with smtplib.SMTP(host, port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_address], msg.as_string())
    else:
        with smtplib.SMTP(host, port) as smtp:
            if user:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_address], msg.as_string())
    ...
```

### Step 2 — Update `.env.example`

Replace the current generic SMTP block with one that includes a Gmail example and the new
`SMTP_SSL` variable:

```dotenv
# SMTP settings for outgoing email (used for forgot-password temporary passwords).
# Leave SMTP_HOST unset to disable email sending (resets will be logged but not sent).
#
# --- Gmail / Google Workspace (App Password, port 587 STARTTLS) ---
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=you@gmail.com
# SMTP_PASSWORD=xxxx xxxx xxxx xxxx   # 16-char App Password from Google Account > Security
# SMTP_TLS=true
#
# --- Gmail / Google Workspace (App Password, port 465 SSL) ---
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=465
# SMTP_USER=you@gmail.com
# SMTP_PASSWORD=xxxx xxxx xxxx xxxx
# SMTP_SSL=true
#
# --- Generic SMTP server ---
# SMTP_HOST=smtp.example.com
# SMTP_PORT=587
# SMTP_USER=you@example.com
# SMTP_PASSWORD=yourpassword
# SMTP_FROM=noreply@example.com
# SMTP_TLS=true
```

### Step 3 — Update `commands.md` env vars table

Add a row for `SMTP_SSL` immediately after the `SMTP_TLS` row in the Environment variables
table in `markdown/features/reference/commands.md`.

### Step 4 — Fill in the feature doc stub

Update `markdown/features/reference/gmail-smtp-integration.md` with the completed operator
guide, including the App Password steps and both connection mode examples.

---

## Verification
- Set `SMTP_HOST=smtp.gmail.com`, port 587, a real Gmail address, a valid App Password, `SMTP_TLS=true` → password reset email arrives in inbox
- Repeat with port 465 and `SMTP_SSL=true` → email arrives
- Set `SMTP_SSL=true` and `SMTP_TLS=false` → SSL path is taken (not plain SMTP)
- Leave `SMTP_HOST` unset → log line printed, no exception raised
- Run `cd backend && python -m pytest tests/ -v` → all existing tests still pass (no new model changes)
