# Gmail SMTP Integration

Operators can use Gmail or Google Workspace accounts as the SMTP relay for password reset
emails. The app's SMTP client supports both port 587 (STARTTLS) and port 465 (direct SSL),
covering all Gmail connection options.

---

## Prerequisites

Gmail requires an **App Password** for SMTP authentication — your normal Google account
password will not work if 2-Step Verification is enabled (which it must be to use App
Passwords).

**Steps to create a Gmail App Password:**

1. Sign in to your Google Account and go to **Security**.
2. Under "How you sign in to Google", ensure **2-Step Verification** is enabled.
3. Search for "App Passwords" in the Google Account search bar (or navigate to
   `myaccount.google.com/apppasswords`).
4. Select **Mail** as the app and **Other** as the device (name it "Kanaliiga Fantasy" or
   similar).
5. Google generates a 16-character password (shown with spaces, e.g. `xxxx xxxx xxxx xxxx`).
   Copy it — it is shown only once.

Use this App Password as `SMTP_PASSWORD` in your `.env` file.

---

## Connection Modes

### Port 587 — STARTTLS (recommended)

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx
SMTP_TLS=true
```

### Port 465 — Direct SSL

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=you@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx
SMTP_SSL=true
```

When `SMTP_SSL=true`, the app uses `smtplib.SMTP_SSL` for the connection; the `SMTP_TLS`
value is ignored.

---

## Endpoints

This feature has no dedicated endpoints — it operates transparently via the existing
`POST /forgot-password` flow.

---

## Configuration

| Weight key | Default | Description |
|---|---|---|
| `SMTP_HOST` | *(empty)* | SMTP hostname; leave unset to disable email sending |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(empty)* | SMTP login username (your Gmail address) |
| `SMTP_PASSWORD` | *(empty)* | SMTP login password (Gmail App Password) |
| `SMTP_FROM` | Falls back to `SMTP_USER` | Sender address in outgoing emails |
| `SMTP_TLS` | `true` | Use STARTTLS; set to `false` for plain SMTP |
| `SMTP_SSL` | `false` | Use direct SSL (`smtplib.SMTP_SSL`); takes priority over `SMTP_TLS` |

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `SMTPAuthenticationError` | App Password wrong or 2-Step Verification not enabled |
| `Connection refused` on port 465 | Try port 587 with `SMTP_SSL=false`, `SMTP_TLS=true` |
| Email arrives in spam | Set `SMTP_FROM` to match `SMTP_USER`; consider SPF/DKIM on custom domains |
| Log shows "SMTP_HOST not set" | `SMTP_HOST` env var is missing or empty |
