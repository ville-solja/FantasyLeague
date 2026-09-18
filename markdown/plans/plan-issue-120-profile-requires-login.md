# Plan: Profile Requires Login

## Context
Issue #120 reported that `GET /profile/{user_id}` (`backend/routers/profile.py`) requires no
authentication at all, and since `user_id` is a small sequential integer, the entire user base
can be scraped anonymously — every username, linked-Twitch status, tags, and season history —
with no auth trail. The issue explicitly asked this repo to *decide* between two paths: keep it
public with added rate limiting, or gate it behind login.

Before picking a direction, the actual frontend usage was checked rather than guessed at:
`grep`ing every call site across `frontend/*.js` and `twitch-extension/*.js` finds exactly one
caller, `frontend/app-profile.js`'s `fetch(${API}/profile/${activeUserId})` — the logged-in
user's own profile tab, always reached from within an authenticated session. Nothing in this
codebase ever fetches *another* user's profile, logged in or not, and nothing relies on
anonymous access. The existing doc (`core/auth.md`) describes the endpoint as public with no
stated rationale for why — consistent with this being an oversight (endpoints default to
public unless explicitly guarded) rather than a deliberate "profiles are shareable links"
design.

Given that, this plan gates the endpoint behind login (`Depends(get_current_user)` — any
authenticated account, not restricted to viewing only your own profile, matching the issue's
own phrasing) rather than adding rate limiting to a public endpoint nothing actually needs
public. This is a clean, low-risk fix: since the only real caller already always has a session,
no frontend change is needed and no legitimate current usage is affected. Worth noting: issue
#121's `RATE_LIMIT_GLOBAL` baseline (200/minute per IP) already applies to this route today
regardless of this plan — that's a separate, already-shipped mitigation layer, not a
replacement for closing the actual access-control gap. *Resolves GitHub issue #120.*

## User Stories

### Require Login to View a Profile
**User story**
As an operator, I want `GET /profile/{user_id}` to require an authenticated session so that
the user base can't be enumerated anonymously by iterating IDs.

**Acceptance criteria**
- `GET /profile/{user_id}` returns 401 for an unauthenticated request, for any `user_id`
- Any logged-in user (not just the profile's owner) can still view any other user's profile —
  this is not restricted to "view your own profile only," matching current behavior for
  everyone once they're authenticated
- The response shape and content for an authenticated request are completely unchanged
- No frontend changes are needed — the only existing call site
  (`frontend/app-profile.js`) always runs within an authenticated session already

### Documentation Reflects the New Requirement
**User story**
As a developer reading the API docs, I want `GET /profile/{user_id}` documented accurately as
requiring login, so I don't assume it's still publicly callable.

**Acceptance criteria**
- `markdown/features/core/auth.md`'s "Viewing a Profile" section no longer says "No
  authentication required" and instead states login is required

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/profile.py` | Add `current_user: dict = Depends(get_current_user)` to `get_profile()` |
| `markdown/features/core/auth.md` | Update the "Viewing a Profile" section |
| `markdown/features/reference/profile-requires-login.md` | New reference doc (stub created by product-planner) |

No model changes, no migrations, no new env vars. `get_current_user` is already imported in
`backend/routers/profile.py` (used by the existing `me()` endpoint) — no new import needed.

### Step 1 — Gate the endpoint
```python
@router.get("/profile/{user_id}")
def get_profile(user_id: int, db=Depends(get_db),
                current_user: dict = Depends(get_current_user)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ...
```
(`current_user` is intentionally unused beyond requiring authentication — this is not an
ownership check, any logged-in account can view any profile, same as today's behavior minus
the anonymous-access path.)

### Step 2 — Update documentation
In `markdown/features/core/auth.md`, change "No authentication required." to state login is
required, and note the response is otherwise unchanged.

### Step 3 — Fill in the feature doc stub
Update `markdown/features/reference/profile-requires-login.md` with final confirmed behavior.

---

## Verification
- `cd backend && python -m pytest tests/ -v` — existing tests calling this endpoint must be
  updated if any assume anonymous access; the suite must stay green otherwise
- New tests: an unauthenticated `GET /profile/{user_id}` returns 401; an authenticated request
  for *any* user_id (including one that isn't the caller's own) succeeds with the unchanged
  response shape; a request for a nonexistent user_id still returns 404 (auth check happens
  via the dependency before the handler body, so this ordering doesn't change)
- Manually confirm the Profile tab still loads normally for a logged-in user (the one real
  call site) — nothing else in the app should be affected
