# Temporary Password Expiry

Extends the forgot-password flow to give temporary passwords a configurable TTL and corrects
the reset email wording to accurately reflect that the previous password is invalidated
immediately on request.

> **Legacy-only since issue #123.** `POST /forgot-password` was redesigned
> (`reference/password-reset-token-flow.md`) to stop generating temp passwords entirely — it now
> only creates a single-use `PasswordResetToken` and never touches `password_hash`,
> `must_change_password`, or `temp_password_expires_at`. **No current code path sets these
> fields anymore.** Everything below describes what *used to* happen on every
> `POST /forgot-password` call, and what *still* happens today only for the narrow case of an
> account that already held an outstanding temp password issued before this redesign shipped:
> `POST /login` still rejects it once `temp_password_expires_at` has passed (or accepts it before
> then), and `PUT /profile/password` still clears both fields on a successful change, exactly as
> described below. This is a deliberately narrow, self-resolving legacy window — see the "Data
> Model" and "Endpoints affected" sections for what remains live vs. dead. A follow-up cleanup
> (dropping the columns and the login-side check once no legacy temp passwords remain
> outstanding) is out of scope and not currently planned.

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
POST /forgot-password   [PRE-#123 BEHAVIOR — NO LONGER HAPPENS]
    ↓
Generate temp password
Set user.password_hash = hash(temp)
Set user.must_change_password = True
Set user.temp_password_expires_at = now + TTL
Send email (corrected wording)
    ↓
POST /login (with temp password)                      [STILL LIVE, for legacy accounts only]
    → if now > temp_password_expires_at → 401 "Temporary password has expired"
    → else → login succeeds, must_change_password flag signals Profile tab to prompt change
    ↓
PUT /profile/password                                  [STILL LIVE — unconditionally, for any account]
    → user.must_change_password = False
    → user.temp_password_expires_at = None
```

As of issue #123, `POST /forgot-password` no longer performs the first block above at all —
see `reference/password-reset-token-flow.md` for what it does instead. The `POST /login` and
`PUT /profile/password` blocks are unchanged and still execute exactly as shown, since both
checks are keyed off the (now write-once-in-the-past) `users` columns rather than off
`/forgot-password` itself.

---

## Data Model

**`users.temp_password_expires_at`** (new column, Integer, nullable):
Unix timestamp set when a temporary password is issued. Cleared to NULL when the user
changes their password. If NULL, no expiry is enforced.

Migration: `020_temp_password_expiry` — `ALTER TABLE users ADD COLUMN temp_password_expires_at INTEGER`.

---

## Endpoints affected

### `POST /forgot-password` — **no longer applicable**
Previously set `temp_password_expires_at = now + TTL` alongside `must_change_password`. Since
issue #123, this endpoint never touches either field (or `password_hash`) — it creates a
`PasswordResetToken` instead. See `reference/password-reset-token-flow.md`.

### `POST /login`
After successful bcrypt verification, if `must_change_password` is True and
`temp_password_expires_at` is set and in the past, returns `401` with:
`"Temporary password has expired. Please request a new password reset."`

### `PUT /profile/password`
Clears `temp_password_expires_at = None` alongside `must_change_password = False`.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TEMP_PASSWORD_TTL_HOURS` | `24` | Hours before a temporary password expires. Set to a higher value for low-traffic deployments. |

