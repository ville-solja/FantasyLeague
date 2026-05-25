# Env-Based Admin Seeding

Replaces hardcoded admin credentials in `backend/seed/users.json` with environment-variable
injection at startup, so no real password is ever committed to the repository.

---

## How it works

On startup, `seed_admin_from_env()` reads three env vars. If all three are present and
non-empty, it creates an admin user if one with that email does not already exist. The call
is idempotent — re-deploying with the same vars is safe.

`backend/seed/users.json` is kept in the repo as an empty stub (`[]`) so the existing
`seed_users()` code path does not crash. Local dev accounts can be added to a private copy
of the file (never committed).

## Endpoints

No new API endpoints — this is a startup-only concern.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SEED_ADMIN_USERNAME` | *(empty)* | Username for the auto-created admin account |
| `SEED_ADMIN_EMAIL` | *(empty)* | Email for the auto-created admin account |
| `SEED_ADMIN_PASSWORD` | *(empty)* | Plaintext password (hashed with bcrypt before storage); never stored in the DB as plaintext |

All three variables must be set for the account to be created. If any are absent the step
is silently skipped — no error is raised.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
