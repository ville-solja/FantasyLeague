# Plan: Password Reset Token Flow

## Context
Issue #123 — flagged as the most severe finding in this session's security disclosure batch.
`POST /forgot-password` (`backend/routers/auth.py`) currently, in order: generates a random temp
password, **immediately overwrites the account's real `password_hash`**, sets
`must_change_password = True`, then emails the temp password. It never verifies the caller
controls the registered email before mutating real credentials — knowing a username alone is
enough to destroy that account's actual password, on demand, repeatedly (issues #121/#122
already rate-limit and cooldown *how often* this can be triggered, but neither stops the
underlying mutate-before-verify design).

This plan replaces the immediate-swap design with a token/link-based flow, per the issue's own
recommendation: `POST /forgot-password` no longer touches `password_hash` at all — it creates a
single-use, expiring `PasswordResetToken` and emails a link containing it. The account's real
password is only ever changed by a new `POST /reset-password` endpoint, which requires that
token. Knowing a username no longer has any effect on an account's actual credentials; only
someone who can read the registered inbox can complete a reset.

**Deliberate scope decision on the existing temp-password mechanism:** `users.must_change_password`
and `users.temp_password_expires_at` (added for issue #77's temp-password-expiry feature) are
**not removed or migrated**. Once this fix ships, `/forgot-password` simply never sets them
again — they become write-once-in-the-past fields, relevant only to whatever accounts still
hold an outstanding pre-fix temp password until it's used or expires. This is deliberately the
narrower, lower-risk option: removing the columns/login-check would need a schema migration and
touches `/login`'s existing 401-on-expiry path and the frontend's must-change-password redirect,
for a legacy window that self-resolves within `TEMP_PASSWORD_TTL_HOURS`. A follow-up cleanup once
no legacy temp passwords remain outstanding is explicitly out of scope here.

**Also out of scope:** session revocation on password reset (a stolen session survives a
password change today — this is the general gap tracked in issue #119, not something to solve
narrowly here) and rate-limiting `/reset-password` itself (the token has 256 bits of entropy via
`secrets.token_urlsafe(32)` and is single-use; the existing app-wide `RATE_LIMIT_GLOBAL` baseline
from issue #121 already applies automatically with no per-route opt-in needed, and a dedicated
stricter limit isn't warranted by the actual threat model here). *Resolves GitHub issue #123.*

## User Stories

### Request a Password Reset Without Touching the Real Password
**User story**
As a user, I want requesting a password reset to leave my actual password untouched until I
complete the reset myself, so that no one else can lock me out of my account just by knowing my
username.

**Acceptance criteria**
- `POST /forgot-password` no longer sets `user.password_hash`, `must_change_password`, or
  `temp_password_expires_at` — the account's real credentials are completely unaffected by the
  request itself
- A single-use `PasswordResetToken` (new table: `token` as primary key, `user_id`, `expires_at`)
  is created for the account, invalidating any prior unused token for that same user (same
  precedent as `TwitchLinkCode`'s link-code invalidation)
- The token's validity window is configurable via `PASSWORD_RESET_TOKEN_TTL_HOURS` (default `1`
  — intentionally short, unlike the old 24h temp-password TTL, since this token alone never
  grants access on its own the way a temp password did)
- An email is sent containing both a clickable link (`{APP_BASE_URL}/?reset_token={token}`, if
  `APP_BASE_URL` is configured) and the raw token as a manual-entry fallback (if
  `APP_BASE_URL` is unset, only the manual-entry fallback is shown)
- The email wording reflects the new reality: the current password remains valid, nothing
  changes until the reset is completed, and the recipient can safely ignore the email if they
  didn't request it — the exact inverse of the old wording (which correctly said the previous
  password was "already... replaced," since under the old design it was)
- The endpoint's existing behavior is otherwise unchanged: always returns `{"status": "ok"}`
  regardless of username/email existence, the bcrypt timing-equalization fast-exit is
  preserved, and issue #121's per-IP limit + issue #122's per-username cooldown both continue
  to apply exactly as before (this plan does not touch either)

### Complete a Password Reset with a Valid Token
**User story**
As a user, I want to actually set a new password using the link or code I was emailed, so that
I can recover my account without anyone else being able to trigger the change on my behalf.

**Acceptance criteria**
- A new `POST /reset-password` endpoint accepts `{"token": "...", "new_password": "..."}`
  (`new_password` subject to the same `min_length=6, max_length=128` constraint used elsewhere)
- A valid, unexpired token sets `user.password_hash` to the new password, clears any legacy
  `must_change_password`/`temp_password_expires_at` state on the account (cleanup, matching
  what `PUT /profile/password` already does), deletes the token (single-use), and returns
  `{"status": "ok"}`
- An invalid, already-used, or expired token returns 400 with a clear error and makes no
  change to any account
- The action is recorded in the audit log (`password_reset_completed`)

### Reset Password UI
**User story**
As a user who clicked the reset link in my email, I want the app to recognize it and let me set
a new password directly, so I don't have to manually construct any requests myself.

**Acceptance criteria**
- Loading the app with a `?reset_token=...` query parameter automatically opens a "Set new
  password" modal with the token pre-filled (hidden) and the URL parameter cleared from the
  visible address bar (`history.replaceState`) so the token doesn't linger in browser history
- The same modal also accepts manual token entry, for the `APP_BASE_URL`-unset fallback case
  where the email only contains a raw code, not a clickable link
- The existing "Forgot password" modal's copy is updated (`frontend/index.html`,
  `submitForgotPassword()`'s success message in `frontend/app-auth.js`) to describe a reset
  link/code being sent, not a temporary password

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New `PasswordResetToken` model |
| `backend/routers/auth.py` | Rework `forgot_password()`; add `reset_password()` + `ResetPasswordBody` |
| `.env.example` | Document `PASSWORD_RESET_TOKEN_TTL_HOURS`, `APP_BASE_URL` |
| `frontend/app-auth.js` | New reset-password modal logic; update forgot-password copy |
| `frontend/index.html` | New reset-password modal markup; update forgot-password modal copy |
| `frontend/app-init.js` | On load, detect `?reset_token=` and open the new modal |
| `markdown/features/core/auth.md` | Rewrite the Forgot Password section; document `POST /reset-password` |
| `markdown/features/reference/smtp-password-recovery.md` | Rewrite the flow section for the new design |
| `markdown/features/reference/temp-password-expiry.md` | Add a note that this mechanism is legacy-only going forward (no new code path sets these fields) |
| `markdown/features/reference/password-reset-token-flow.md` | New reference doc (stub created by product-planner) covering the vulnerability + redesign |
| `markdown/stories/users-and-access.md` | Existing "Temporary Password" story updated (already done by product-planner, see below) |

No migration needed for `PasswordResetToken` — it's a new table
(`Base.metadata.create_all()` covers it; per CLAUDE.md, only new *columns on existing tables*
need a migration entry).

### Step 1 — New model
```python
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token      = Column(String, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"))
    expires_at = Column(Integer)  # Unix timestamp
```

### Step 2 — Rework `forgot_password()`
Replace the temp-password generation/`password_hash` overwrite block with token creation.
Invalidate prior tokens for the user first (mirrors `TwitchLinkCode`'s
`db.query(TwitchLinkCode).filter_by(user_id=user_id).delete()` pattern in `twitch.py`):
```python
db.query(PasswordResetToken).filter_by(user_id=user_id).delete()
token = secrets.token_urlsafe(32)
ttl_hours = int(os.getenv("PASSWORD_RESET_TOKEN_TTL_HOURS", "1"))
db.add(PasswordResetToken(token=token, user_id=user_id,
                          expires_at=int(time.time()) + ttl_hours * 3600))
_audit(db, "password_reset_requested", actor_id=user_id, actor_username=user_username)

app_name = os.getenv("APP_NAME", "Kana Cards")
base_url = os.getenv("APP_BASE_URL", "").rstrip("/")
link_block = f"    {base_url}/?reset_token={token}\n\n" if base_url else ""
body = (
    f"Hi {user_username},\n\n"
    f"A password reset was requested for your account.\n\n"
    f"{link_block}"
    f"    Reset code: {token}\n\n"
    f"Enter this code on the login screen's 'Reset password' form if you don't use the link "
    f"above. This code expires in {ttl_hours} hour(s).\n\n"
    f"Your current password has not been changed and remains valid — nothing happens to your "
    f"account until you complete this step. If you did not request this, you can safely "
    f"ignore this email.\n"
)
```
Keep the existing `try/except` around `send_email` (rollback + 503 on failure) and the existing
nonexistent-username/no-email fast-exit untouched.

### Step 3 — `POST /reset-password`
```python
class ResetPasswordBody(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


@router.post("/reset-password")
def reset_password(body: ResetPasswordBody, db=Depends(get_db)):
    token_row = db.get(PasswordResetToken, body.token)
    if not token_row or token_row.expires_at < int(time.time()):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user = db.get(User, token_row.user_id)
    if not user:
        db.delete(token_row)
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.temp_password_expires_at = None
    db.delete(token_row)
    _audit(db, "password_reset_completed", actor_id=user.id, actor_username=user.username)
    db.commit()
    return {"status": "ok"}
```

### Step 4 — Frontend
- `frontend/index.html`: add a new modal (e.g. `resetPasswordModal`) with a token input
  (pre-fillable), a new-password input, and a submit button calling a new
  `submitResetPassword()` in `app-auth.js`. Update the existing `forgotModal`'s description
  text and `submitForgotPassword()`'s success message to describe a link/code, not a temporary
  password.
- `frontend/app-init.js`: in `init()` (or a small helper called from it), check
  `new URLSearchParams(window.location.search).get("reset_token")`; if present, open the new
  modal with the token pre-filled and strip the parameter from the URL via
  `history.replaceState(null, "", window.location.pathname)`.

### Step 5 — Env vars
```
# Hours before a password-reset token expires. Default: 1 — intentionally short, since this
# token alone never grants access the way the old immediate temp password did.
# PASSWORD_RESET_TOKEN_TTL_HOURS=1

# Public base URL of this deployment, used to build a clickable link in reset-password emails.
# If unset, the email includes only the raw reset code (manual entry) with no link.
# APP_BASE_URL=https://your-deployment.example.com
```

### Step 6 — Documentation rewrite
Update `core/auth.md`'s Forgot Password section and add `POST /reset-password`;
`reference/smtp-password-recovery.md`'s flow section; `reference/temp-password-expiry.md` gets
a note that no current code path sets these fields anymore, they're legacy-only. Fill in the
new `reference/password-reset-token-flow.md` stub with final confirmed behavior.

---

## Verification
- `cd backend && python -m pytest tests/ -v` — existing forgot-password tests (enumeration
  safety, timing equalization, rate limit, cooldown from #121/#122) must stay green; existing
  temp-password-expiry tests (#77) covering the *login-side* 401-on-expiry check must also stay
  green, since that check is intentionally untouched
- New tests: `POST /forgot-password` for an existing user does not change `password_hash`;
  creates exactly one `PasswordResetToken` row (and removes any prior one for repeated
  requests); `POST /reset-password` with a valid token changes the password and the token
  cannot be reused; an expired or unknown token is rejected with no side effects; a completed
  reset clears any pre-existing legacy `must_change_password`/`temp_password_expires_at` state
- Manual check: with `APP_BASE_URL` set, trigger a reset and confirm the emailed link opens the
  app with the modal pre-filled; with it unset, confirm the email still contains a usable
  manual code and the modal accepts pasted-in tokens
- Confirm a user who already has an outstanding *pre-fix* temp password can still log in with
  it (or gets the existing expiry message if it's expired) — the legacy path must not break
