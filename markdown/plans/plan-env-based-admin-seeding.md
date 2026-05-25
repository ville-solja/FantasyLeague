# Plan: Env-Based Admin Seeding

## Context
Admin credentials are currently stored as plaintext passwords in `backend/seed/users.json`,
which is tracked in version control. This means any clone of the repo exposes working
credentials directly. The issue asks for a pattern that keeps the seeding mechanism
visible in version control while moving the actual credentials to environment variables
— the standard twelve-factor approach for secret injection. The fix is to read admin
account details from env vars at startup and remove (or replace with a safe stub) the
committed `users.json`. Resolves GitHub issue #57.

## User Stories

### Configure the Admin Account via Environment Variables
**User story**
As an operator deploying the app, I want to set admin credentials through environment
variables so that no real password is ever committed to the repository.

**Acceptance criteria**
- If `SEED_ADMIN_USERNAME`, `SEED_ADMIN_EMAIL`, and `SEED_ADMIN_PASSWORD` are all set,
  a user with `is_admin=true` is created at startup if no user with that email already exists
- If the env vars are absent or empty, no admin account is auto-created (no crash, no warning)
- The `backend/seed/users.json` file is replaced with a safe, empty-array stub (`[]`) so
  the seeding code path remains exercisable in tests without committing real passwords
- The old `seed_users()` function still works for local dev if a non-empty `users.json` is
  placed on disk (the file is `.gitignore`d except for the stub)
- `.env.example` documents all three new variables

### Prevent Accidental Credential Leakage in CI
**User story**
As a developer, I want the CI test suite to work without real admin credentials in the
environment so that test runs do not depend on secrets.

**Acceptance criteria**
- `pytest` passes with `users.json` set to `[]` and no `SEED_ADMIN_*` env vars set
- No test hard-codes the admin username or password from the old `users.json`

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/seed.py` | Add `seed_admin_from_env()`; keep `seed_users()` for local dev |
| `backend/seed/users.json` | Replace with empty-array stub `[]` |
| `backend/main.py` | Call `seed_admin_from_env()` at startup alongside `seed_users()` |
| `.env.example` | Document `SEED_ADMIN_USERNAME`, `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD` |
| `.gitignore` | Optionally note that a populated `users.json` is secrets-on-disk |

### Step 1 — Add `seed_admin_from_env()` to `backend/seed.py`

```python
def seed_admin_from_env():
    username = os.environ.get("SEED_ADMIN_USERNAME", "").strip()
    email    = os.environ.get("SEED_ADMIN_EMAIL",    "").strip()
    password = os.environ.get("SEED_ADMIN_PASSWORD", "").strip()

    if not (username and email and password):
        return  # env vars absent — skip silently

    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(email=email).first()
        if not existing:
            db.add(User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                is_admin=True,
                is_tester=False,
            ))
            db.commit()
            logger.info("Seeded admin account from env: %s", username)
        else:
            logger.debug("Admin account already exists, skipping env seed")
    finally:
        db.close()
```

### Step 2 — Update `backend/seed/users.json`

Replace the file contents with:

```json
[]
```

This keeps the file present so `seed_users()` does not crash on startup. For local
development, operators can create a private `users.json` with test accounts (which will
be ignored by git once the `.gitignore` entry is added).

### Step 3 — Call `seed_admin_from_env()` at startup in `backend/main.py`

Locate the startup block that calls `seed_users()` and `seed_weights()` and add the new
call immediately after `seed_users()`:

```python
seed_users()
seed_admin_from_env()
seed_weights()
```

### Step 4 — Update `.env.example`

Add a new block documenting the three variables:

```dotenv
# Bootstrap admin account credentials (set on first deploy or in development).
# If all three are set, an admin user is created at startup if the email is not
# already registered. Leave unset to skip admin auto-creation.
# SEED_ADMIN_USERNAME=admin
# SEED_ADMIN_EMAIL=admin@example.com
# SEED_ADMIN_PASSWORD=change-me-before-deploy
```

### Step 5 — Update `.gitignore` (optional but recommended)

Add a comment noting that a local `users.json` with real accounts should never be committed:

```
# Local dev seed accounts — do not commit real credentials
# backend/seed/users.json is intentionally tracked as an empty stub
```

---

## Verification
- Set `SEED_ADMIN_USERNAME=admin`, `SEED_ADMIN_EMAIL=admin@example.com`,
  `SEED_ADMIN_PASSWORD=secret` and start the backend — admin account appears in the DB
- Start the backend a second time with the same vars — no duplicate user is created
- Start the backend with no `SEED_ADMIN_*` vars set — no crash, no admin auto-created
- `git diff backend/seed/users.json` shows `[]` — no passwords in the diff
- `pytest` passes without any `SEED_ADMIN_*` env vars
