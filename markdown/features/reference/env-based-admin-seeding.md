# Env-Based Admin Seeding

Replaces hardcoded admin credentials in `backend/seed/users.json` with environment-variable
injection at startup, so no real password is ever committed to the repository. Supports seeding
any number of admin accounts, not just one.

---

## How it works

On startup, `seed_admin_from_env()` reads `SEED_ADMIN_USERNAME`/`SEED_ADMIN_EMAIL`/
`SEED_ADMIN_PASSWORD` for admin #1, then `SEED_ADMIN_USERNAME_2`/`SEED_ADMIN_EMAIL_2`/
`SEED_ADMIN_PASSWORD_2` for admin #2, `_3` for admin #3, and so on. For each numbered set, if
all three values are present and non-empty, it creates an admin user unless one with that
**username** already exists (existence is checked by username, not email — a duplicate email
under a different username is not caught here). Seeding stops at the first numbered suffix
whose set is incomplete or absent —
there is no separate "how many admins" variable. The call is idempotent — re-deploying with the
same vars is safe, and existing admins created via this mechanism or promoted in-app
(see `core/admin.md`'s `POST /users/{user_id}/toggle-admin`) are left untouched.

`backend/seed/users.json` is kept in the repo as an empty stub (`[]`) so the existing
`seed_users()` code path does not crash. Local dev accounts can be added to a private copy
of the file (never committed).

## Endpoints

No new API endpoints for seeding itself — this is a startup-only concern. See `core/admin.md`
for the separate in-app `POST /users/{user_id}/toggle-admin` promotion endpoint, which is the
recommended way to add admins after initial deployment without touching env vars or the DB
directly.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SEED_ADMIN_USERNAME` | *(empty)* | Username for auto-created admin #1 |
| `SEED_ADMIN_EMAIL` | *(empty)* | Email for auto-created admin #1 |
| `SEED_ADMIN_PASSWORD` | *(empty)* | Plaintext password for admin #1 (hashed with bcrypt before storage); never stored in the DB as plaintext |
| `SEED_ADMIN_USERNAME_2`, `SEED_ADMIN_EMAIL_2`, `SEED_ADMIN_PASSWORD_2` | *(empty)* | Same fields for admin #2. Continue with `_3`, `_4`, ... for further admins. |

All three variables in a given numbered set must be set for that admin to be created. If any
one of the three is absent, seeding stops at that suffix — earlier numbered admins are still
seeded, later ones are not attempted.

## Call site

`seed_admin_from_env()` is called in the `lifespan` startup handler in `backend/main.py`,
after `seed_users()` and before `seed_weights()`. Both `seed_users()` and
`seed_admin_from_env()` are called on every startup; `seed_users()` is harmless with the
empty `users.json` stub.

On successful account creation the event is logged at `INFO` level. If the account already
exists it is logged at `DEBUG` level and silently skipped.
