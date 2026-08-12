# Plan: Multi-Admin Support

## Context
GitHub issue #90 asks for two related capabilities: (1) an environment-based way to seed
**multiple** admin accounts at startup, not just the single account `SEED_ADMIN_USERNAME`/
`SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` currently support, and (2) an in-app way for an
existing admin to promote another user to admin (and demote them back), mirroring the existing
"Mark tester" toggle button in the User Management tab. `core/admin.md`'s own User Management
section already states the gap plainly: *"Additional admins require a direct DB update: `UPDATE
users SET is_admin = 1 WHERE username = '...'`; there is no in-app admin promotion flow."* This
plan closes that gap on both the seeding side and the in-app side.

**Seeding format decision:** rather than comma-separated lists (fragile once list lengths
disagree, and awkward for passwords containing commas) or a `SEED_ADMINS_JSON` blob (this
repo's `WEIGHTS_JSON` var sets a precedent for JSON-in-env, but embedding several plaintext
passwords in one JSON string in a `.env` file is more error-prone to hand-edit and escape than
plain vars), this plan extends the existing three vars with **numbered suffixes**:
`SEED_ADMIN_USERNAME`/`_EMAIL`/`_PASSWORD` continue to mean "admin #1" exactly as today (fully
backward compatible with existing deployments), and `SEED_ADMIN_USERNAME_2`/`_EMAIL_2`/
`_PASSWORD_2`, `_3`, etc. add further admins. Seeding stops at the first fully-absent numbered
set.

**In-app promotion safety:** unlike the tester flag (losing tester status doesn't lock anyone
out of anything), losing admin status is consequential — this plan adds two guards absent from
the tester-toggle precedent: an admin cannot toggle their own admin status (no accidental
self-demotion), and the last remaining admin cannot be demoted (the system can never end up with
zero admins). Both are enforced server-side; the frontend also simply omits the button on the
acting admin's own row.

Because `reference/env-based-admin-seeding.md` and `core/admin.md`'s User Management section
already document the exact areas this plan touches, both are **updated in place** rather than
duplicated into new stub files, per the project's "do not duplicate documentation" rule.

Resolves GitHub issue #90.

## User Stories

### Seed Multiple Admin Accounts via Environment Variables
**User story**
As an operator deploying this app, I want to configure more than one admin account via
environment variables so that I don't have to bootstrap a single admin and then manually
promote everyone else via direct database access.

**Acceptance criteria**
- `SEED_ADMIN_USERNAME`/`SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` (unsuffixed) continue to
  behave exactly as today — this remains "admin #1" with no breaking change for existing
  deployments
- Setting `SEED_ADMIN_USERNAME_2`/`SEED_ADMIN_EMAIL_2`/`SEED_ADMIN_PASSWORD_2` (and `_3`, `_4`,
  ...) creates additional admin accounts at startup under the same rules as admin #1: all three
  values in a numbered set must be present and non-empty, creation is skipped if a user with
  that email already exists, and the step is idempotent across restarts
- Seeding stops at the first numbered suffix where the set is incomplete or absent — there is
  no need to declare a total admin count anywhere
- Each created account logs at `INFO` level; each already-existing account is skipped at
  `DEBUG` level, matching the existing single-admin behavior

### Promote or Demote a User's Admin Status In-App
**User story**
As an admin, I want to promote another user to admin (and demote them back) from the User
Management tab so that I don't need direct database access to manage who else has admin rights.

**Acceptance criteria**
- The User Management table shows an "ADMIN" badge next to the username of any user with
  `is_admin = true`, next to the existing "TESTER" badge pattern
- Each row (except the acting admin's own row) has a "Promote to admin" / "Demote from admin"
  toggle button, matching the existing "Mark tester" / "Unmark tester" button
- An admin cannot toggle their own admin status — the button is not rendered on their own row,
  and the backend independently rejects the attempt with 409 if it is somehow submitted anyway
- Demoting the last remaining admin is rejected with 409 — the system can never end up with zero
  admin accounts
- The action is recorded in the audit log, following the existing `admin_toggle_tester` pattern

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/seed.py` | `seed_admin_from_env()`: loop over numbered env var suffixes instead of a single fixed set |
| `backend/routers/admin_users.py` | `GET /users`: add `is_admin` to each row. New `POST /users/{user_id}/toggle-admin`: mirrors `toggle-tester` plus the two safety guards |
| `frontend/app-admin.js` | `_renderUsers()`: add ADMIN badge + conditional toggle button (hidden on the acting admin's own row); new `toggleAdmin(userId)` function mirroring `toggleTester()` |
| `markdown/features/reference/env-based-admin-seeding.md` | Update in place to describe numbered-suffix multi-admin seeding |
| `markdown/features/core/admin.md` | Update in place: replace the "no in-app admin promotion flow" sentence; document `is_admin` on `GET /users` and the new `POST /users/{user_id}/toggle-admin` endpoint |
| `markdown/stories/admin.md` | Append the two stories above under a new `## Multi-Admin Support` heading |

### Step 1 — Multi-admin env seeding
In `backend/seed.py`, change `seed_admin_from_env()` to loop:
```python
def seed_admin_from_env():
    db = SessionLocal()
    try:
        i = 1
        created_any = False
        while True:
            suffix = "" if i == 1 else f"_{i}"
            username = os.environ.get(f"SEED_ADMIN_USERNAME{suffix}", "").strip()
            email    = os.environ.get(f"SEED_ADMIN_EMAIL{suffix}",    "").strip()
            password = os.environ.get(f"SEED_ADMIN_PASSWORD{suffix}", "").strip()
            if not (username and email and password):
                break
            existing = db.query(User).filter_by(username=username).first()
            if not existing:
                db.add(User(username=username, email=email,
                             password_hash=hash_password(password),
                             is_admin=True, is_tester=False))
                logger.info("Seeded admin account from env: %s", username)
                created_any = True
            else:
                logger.debug("Admin account %s already exists, skipping", username)
            i += 1
        if created_any:
            db.commit()
    finally:
        db.close()
```
(Match this repo's existing try/finally + logging conventions exactly — read the current
function body first since exact commit/error-handling details may differ slightly from this
sketch.)

### Step 2 — In-app promotion endpoint
In `backend/routers/admin_users.py`, add `is_admin` to `GET /users`'s per-user dict, and add:
```python
@router.post("/users/{user_id}/toggle-admin")
def toggle_admin(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=409, detail="Cannot change your own admin status")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_admin and db.query(User).filter_by(is_admin=True).count() <= 1:
        raise HTTPException(status_code=409, detail="Cannot demote the last remaining admin")
    user.is_admin = not bool(user.is_admin)
    _audit(db, "admin_toggle_admin", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"{user.username} is_admin={user.is_admin}")
    db.commit()
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin}
```

### Step 3 — Frontend
In `frontend/app-admin.js`'s `_renderUsers()`, add an ADMIN badge next to `testerBadge`
(same visual pattern, different label/color so the two badges are distinguishable), and add a
toggle button to the Actions cell — conditionally omitted when `u.id === activeUserId`:
```js
const adminBadge = u.is_admin
  ? ` <span class="badge" style="background:var(--k-flame-700,#8a2e0c);color:#fff;font-size:0.7rem;">ADMIN</span>`
  : "";
// ...
const adminToggleBtn = u.id === activeUserId ? "" :
  `<button class="ghost" style="font-size:0.8rem;" onclick="toggleAdmin(${u.id})">${u.is_admin ? "Demote from admin" : "Promote to admin"}</button>`;
```
Add `toggleAdmin(userId)` mirroring `toggleTester(userId)` exactly (same fetch/status/reload
pattern, different endpoint and status message).

### Step 4 — Documentation
Update `reference/env-based-admin-seeding.md`: describe the numbered-suffix loop, update the
Configuration table to show the pattern (`SEED_ADMIN_USERNAME[_N]` style) rather than three
fixed rows, and update `.env.example` with a comment showing the `_2` example.
Update `core/admin.md`: remove the "no in-app admin promotion flow" sentence from the intro
paragraph, add `is_admin` to the `GET /users` field list, and document
`POST /users/{user_id}/toggle-admin` alongside `toggle-tester`.
Append the two stories to `markdown/stories/admin.md`.

## Verification
- Set only the unsuffixed `SEED_ADMIN_*` vars; confirm startup behavior is identical to before
  this change (one admin created, idempotent on restart)
- Add `SEED_ADMIN_USERNAME_2`/`_EMAIL_2`/`_PASSWORD_2`; confirm a second admin is created on
  next startup, and that restarting again does not duplicate it
- Leave a gap (set `_2` fully but not `_3`); confirm seeding stops after admin #2 and no error
  is raised
- As an admin, promote a regular user via the User Management tab; confirm they gain admin
  access on next login (session-based `is_admin` is set at login time, so an already-logged-in
  promoted user will not see admin access until they log in again — this is consistent with how
  the session already works, not a new limitation introduced here)
- Attempt to demote the sole remaining admin; confirm 409 and no state change
- Confirm the acting admin's own row never shows the toggle button, and that calling the
  endpoint directly against one's own `user_id` still 409s
- No migration needed — `User.is_admin` already exists as a column
