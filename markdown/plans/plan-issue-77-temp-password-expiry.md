# Plan: Temporary Password Expiry

## Context
When a user requests a password reset via `POST /forgot-password`, a temporary password is
issued and stored immediately — replacing the user's real password — but it currently has no
TTL. If the user does not act on the reset email, the temporary credential remains valid
indefinitely, creating an unnecessary exposure window. Issue #77 also identified that the
reset email body contains an incorrect statement ("the password was not changed until you
log in and update it") when in fact the password is replaced at the moment of the request.
This plan adds a configurable expiry to temporary passwords and corrects the email wording.
*Resolves GitHub issue #77.*

## User Stories

### Temporary Password Expiry
**User story**
As a user, I want temporary passwords issued via the forgot-password flow to expire after a
set period so that my account is not left permanently accessible via a temporary credential
if I forget to change my password.

**Acceptance criteria**
- A temporary password expires after `TEMP_PASSWORD_TTL_HOURS` hours (default: 24)
- Attempting to log in with an expired temporary password returns 401 with a clear message prompting the user to request a new reset
- `temp_password_expires_at` is cleared (set to NULL) when the user successfully changes their password via `POST /change-password`
- The expiry timestamp is stored in the `users` table and covered by a schema migration

### Accurate Password Reset Email
**User story**
As a user, I want the password reset email to accurately state that my previous password
has been invalidated so that I understand the security implications of the request
immediately.

**Acceptance criteria**
- The email body states that the previous password is no longer valid and the temporary password expires after 24 hours (or the configured TTL)
- The email does not contain the incorrect statement that the password change is deferred until login
- If the user did not request the reset, the email advises them to contact support immediately

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `temp_password_expires_at` (Integer, nullable) to `User` |
| `backend/migrate.py` | Migration `020_temp_password_expiry`: ALTER TABLE users ADD COLUMN |
| `backend/routers/auth.py` | Set expiry in `forgot_password()`; check expiry in `login()`; fix email body |
| `backend/routers/profile.py` | Clear `temp_password_expires_at` in `change_password()` |

### Step 1 — Model column

Add to `User` in `backend/models.py`:

```python
temp_password_expires_at = Column(Integer, nullable=True)
# Set to a Unix timestamp when a temporary password is issued; NULL otherwise.
```

### Step 2 — Migration

Add to `backend/migrate.py` before the existing `_m019` entry and register it:

```python
def _m020_temp_password_expiry(conn):
    cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
    if "temp_password_expires_at" not in cols:
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN temp_password_expires_at INTEGER"
        ))
        conn.commit()
```

Register as `("020_temp_password_expiry", _m020_temp_password_expiry)` in `MIGRATIONS`.

### Step 3 — Set expiry and fix email body in `forgot_password()`

In `backend/routers/auth.py`, inside the `forgot_password()` handler, after generating the
temp password:

```python
ttl_hours = int(os.getenv("TEMP_PASSWORD_TTL_HOURS", "24"))
user.temp_password_expires_at = int(time.time()) + ttl_hours * 3600
```

Replace the email body with:

```python
body=(
    f"Hi {user_username},\n\n"
    f"A temporary password has been issued for your account:\n\n"
    f"    {temp_password}\n\n"
    f"Your previous password is no longer valid.\n"
    f"This temporary password expires in {ttl_hours} hour(s). "
    f"Log in and go to your Profile to set a permanent password.\n\n"
    f"If you did not request this reset, contact support immediately.\n"
),
```

### Step 4 — Enforce expiry in `login()`

In `backend/routers/auth.py`, after the password is verified in `login()`, add:

```python
if user.must_change_password and user.temp_password_expires_at:
    if int(time.time()) > user.temp_password_expires_at:
        raise HTTPException(
            status_code=401,
            detail="Temporary password has expired. Please request a new password reset.",
        )
```

### Step 5 — Clear expiry on password change

In `backend/routers/profile.py`, inside `change_password()`, add alongside the existing
`must_change_password = False` line:

```python
user.temp_password_expires_at = None
```

---

## Verification

- Request a password reset; verify the email body no longer says "the password was not changed until you log in"
- Log in with the temporary password within the TTL window — should succeed
- Set `TEMP_PASSWORD_TTL_HOURS=0` (or wait past the TTL); attempt login — should return 401 with expiry message
- Change password via Profile; verify `temp_password_expires_at` is NULL and login works normally
- Run `cd backend && python -m pytest tests/test_migrate.py -v` to confirm migration coverage
