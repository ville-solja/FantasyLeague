# Temporary Password Expiry

Extends the forgot-password flow to give temporary passwords a configurable TTL and corrects
the reset email wording to accurately reflect that the previous password is invalidated
immediately on request.

---

## Overview

When `POST /forgot-password` is called, the user's password is replaced with a temporary
12-character credential and `must_change_password` is set to `True`. Without expiry, this
credential remains valid indefinitely if the user ignores the email. This feature adds a
`temp_password_expires_at` Unix timestamp to the `users` table. Login is rejected with a
clear 401 message once the timestamp has passed, prompting the user to request a fresh reset.

---

## Flow

```
POST /forgot-password
    ↓
Generate temp password
Set user.password_hash = hash(temp)
Set user.must_change_password = True
Set user.temp_password_expires_at = now + TTL
Send email (corrected wording)
    ↓
POST /login (with temp password)
    → if now > temp_password_expires_at → 401 "Temporary password has expired"
    → else → login succeeds, must_change_password flag signals Profile tab to prompt change
    ↓
PUT /profile/password
    → user.must_change_password = False
    → user.temp_password_expires_at = None
```

---

## Data Model

**`users.temp_password_expires_at`** (new column, Integer, nullable):
Unix timestamp set when a temporary password is issued. Cleared to NULL when the user
changes their password. If NULL, no expiry is enforced.

Migration: `020_temp_password_expiry` — `ALTER TABLE users ADD COLUMN temp_password_expires_at INTEGER`.

---

## Endpoints affected

### `POST /forgot-password`
Sets `temp_password_expires_at = now + TTL` alongside the existing `must_change_password`
flag. Email body updated to state that the previous password is no longer valid and that the
temporary password expires after the configured TTL.

### `POST /login`
After successful bcrypt verification, if `must_change_password` is True and
`temp_password_expires_at` is set and in the past, returns `401` with:
`"Temporary password has expired. Please request a new password reset."`

### `POST /change-password`
Clears `temp_password_expires_at = None` alongside `must_change_password = False`.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TEMP_PASSWORD_TTL_HOURS` | `24` | Hours before a temporary password expires. Set to a higher value for low-traffic deployments. |

