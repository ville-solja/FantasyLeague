# Password Reset Token Flow

Replaces the forgot-password flow's immediate password-overwrite design with a single-use,
expiring reset token — closing a vulnerability where knowing a username alone was enough to
destroy that account's real password, with no verification the caller controls the email.

*(see `markdown/plans/plan-issue-123-password-reset-token-flow.md`, resolves GitHub issue #123)*

---

## The vulnerability

`POST /forgot-password` used to, in order: generate a random temp password, **immediately
overwrite the account's real `password_hash`**, then email the temp password. It never
verified the caller controlled the registered email before mutating real credentials — anyone
who knew (or enumerated) a username could invalidate that account's actual password on demand,
repeatedly. Issues #121 (per-IP rate limit) and #122 (per-username cooldown) already limited
*how often* this could be triggered, but neither addressed the underlying mutate-before-verify
design.

## Fix

`POST /forgot-password` no longer touches `password_hash` at all. It creates a single-use
`PasswordResetToken` (new table: `token` PK, `user_id`, `expires_at`) with a short TTL
(`PASSWORD_RESET_TOKEN_TTL_HOURS`, default `1`), invalidating any prior unused token for the
account, and emails a link/code containing it. The account's real password is only ever changed
by the new `POST /reset-password` endpoint, which requires that token — knowing a username no
longer has any effect on an account's actual credentials.

## Endpoints

### `POST /forgot-password` — reworked
Unchanged externally (`{"username": "..."}`, always `{"status": "ok"}`, enumeration-safe,
subject to issue #121's per-IP limit and issue #122's per-username cooldown, both applied
before any token work). Internally:

1. Deletes any existing `PasswordResetToken` row for the account (mirrors `TwitchLinkCode`'s
   invalidate-on-regenerate pattern in `twitch.py`'s `generate_link_code()`).
2. Creates a new token via `secrets.token_urlsafe(32)` (256 bits of entropy) with
   `expires_at = now + PASSWORD_RESET_TOKEN_TTL_HOURS * 3600`.
3. Writes a `password_reset_requested` audit log entry.
4. Emails the address on file: a clickable link `{APP_BASE_URL}/?reset_token={token}` (only if
   `APP_BASE_URL` is set) plus the raw token as a manual-entry fallback (always present). The
   wording states the current password remains valid and nothing changes until the reset is
   completed — the reader can safely ignore the email if they didn't request it.

Never sets `user.password_hash`, `must_change_password`, or `temp_password_expires_at`.

### `POST /reset-password` — new
`{"token": "...", "new_password": "..."}` (`new_password` subject to
`Field(min_length=6, max_length=128)`, same constraint used elsewhere).

- Invalid, unknown, already-used, or expired token → `400 {"detail": "Invalid or expired reset
  link"}`, no side effects (nothing is deleted or mutated).
- Valid, unexpired token:
  1. `user.password_hash = hash_password(new_password)`.
  2. `user.must_change_password = False`, `user.temp_password_expires_at = None` (cleanup,
     matching `PUT /profile/password`).
  3. The token row is deleted — resubmitting it afterward returns 400 (single-use, enforced by
     the row simply no longer existing).
  4. A `password_reset_completed` audit log entry is written.
  5. Returns `{"status": "ok"}`.

No authentication required for either endpoint — the token itself is the credential for
`POST /reset-password`.

## What this does *not* touch

- **Existing pre-fix temp passwords**: `users.must_change_password`/`temp_password_expires_at`
  (from issue #77) are not removed or migrated. `/forgot-password` simply never sets them
  again going forward; `/login`'s existing expiry check and the frontend's must-change-password
  redirect remain in place for whatever accounts still hold an outstanding pre-fix temp
  password until it's used or expires. See `reference/temp-password-expiry.md`.
- **Session revocation**: a session created before a password reset is not invalidated by the
  reset. This is the general gap tracked in issue #119, not solved narrowly here.
- **Rate-limiting `POST /reset-password` itself**: the token has 256 bits of entropy
  (`secrets.token_urlsafe(32)`) and is single-use; the app-wide `RATE_LIMIT_GLOBAL` baseline
  already applies automatically with no per-route opt-in needed.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PASSWORD_RESET_TOKEN_TTL_HOURS` | `1` | Hours before a password-reset token expires |
| `APP_BASE_URL` | *(empty)* | Public base URL used to build a clickable reset link in emails; if unset, the email includes only the raw reset code |

## Frontend

- The existing "Forgot password" modal (`frontend/index.html#forgotModal`) copy was updated to
  describe a reset link/code, not a temporary password; `submitForgotPassword()`
  (`frontend/app-auth.js`) success message follows suit.
- A new "Set new password" modal (`#resetPasswordModal`) accepts a token (pre-fillable) and a
  new password, submitted via `submitResetPassword()` against `POST /reset-password`.
- `frontend/app-init.js`'s `init()` calls `_handleResetTokenParam()`, which detects
  `?reset_token=...` via `URLSearchParams`, strips it from the visible URL with
  `history.replaceState`, and opens the reset-password modal pre-filled with the token — so a
  clicked email link lands the user directly on the reset form.

## Test coverage

`backend/tests/test_issue_123_password_reset_token_flow.py` (20 tests) covers both backend
stories end-to-end: token creation/invalidation/TTL/email content for `/forgot-password`, and
validation/expiry/single-use/audit-logging for `/reset-password`. The UI story (modal auto-open,
URL stripping) has no backend test surface and isn't covered there.

---

*Implemented — resolves GitHub issue #123.*
