# Plan: Roster Mutation Rate Limiting

## Context
A community security disclosure (2026-09-18) found that `POST /roster/{card_id}/activate`,
`/roster/{card_id}/deactivate`, `/roster/swap`, and `/roster/reorder`
(`backend/routers/cards.py`) have no rate limiting at all, and every one of them is
immediately followed by a frontend re-fetch of the full scored roster (`loadRoster()` →
`GET /roster/{user_id}` → `_build_roster_response()`, several multi-join queries over
match/stat history). On this app's single-process, single-SQLite-file deployment, rapid
toggling from even one account is enough to meaningfully load the backend — described as a
usable DoS vector on its own.

The backend mutation endpoints themselves already return lightweight confirmations
(`{"status": "ok", "card_id": ...}` / `{"ok": true}`), not the full roster — so the report's
"lighter-weight response" recommendation is already satisfied on the mutation side; the actual
amplification is the immediate frontend re-fetch after every single toggle. This plan addresses
both remaining parts of the report's recommendation: **per-user rate limiting** on the four
endpoints, reusing the shared `slowapi` `Limiter` already built for issue #121
(`backend/rate_limit.py`) rather than introducing a second rate-limiting mechanism, and a
**frontend in-flight guard** that prevents a user from queuing more mutation+refetch pairs than
one at a time — capping the achievable rate below what the backend limit even needs to reject,
and improving UX (accidental double-clicks) as a side effect.

Issue #121's `Limiter` defaults to a per-*IP* key (`slowapi.util.get_remote_address`). These four
endpoints all require login, so a per-*user* limit is more correct here — the report explicitly
asks for "per-user rate limiting," and IP-based limiting alone would either be too strict for
users sharing a network or too generous for one user hopping between IPs. This plan adds a
reusable per-user (falling back to per-IP if somehow unauthenticated) key function to
`rate_limit.py` rather than duplicating one per call site. *Resolves GitHub issue #124.*

## User Stories

### Per-User Rate Limiting on Roster Mutations
**User story**
As an operator, I want the roster activate/deactivate/swap/reorder endpoints to enforce a
per-user rate limit so that rapid toggling — accidental or deliberate — can't meaningfully
load the backend.

**Acceptance criteria**
- `POST /roster/{card_id}/activate`, `/roster/{card_id}/deactivate`, `/roster/swap`, and
  `/roster/reorder` each enforce a per-user limit, configurable via
  `RATE_LIMIT_ROSTER_MUTATION` (default `30/minute`)
- The limit is keyed by the authenticated user's session `user_id`, not source IP, so it
  follows the account regardless of network; an unauthenticated caller (should never happen
  given these routes already require login, but as a defensive fallback) is keyed by IP
  instead
- Exceeding the limit returns HTTP 429 with the same `{"detail": "Rate limit exceeded: ..."}`
  shape already established by issue #121, not a new/different error format
- The default is generous enough that normal roster-building activity (a handful of swaps
  while setting up a 5-card active roster) is never blocked

### Prevent Rapid Re-Fire from the Roster UI
**User story**
As a player, I want the roster UI to ignore extra activate/deactivate/swap clicks or drops
while a previous one is still in flight, so that impatient clicking can't queue up more
requests than the app can usefully process (and so I don't see a confusing partial-update
state from overlapping requests).

**Acceptance criteria**
- While an activate, deactivate, swap, or reorder request is in flight, a new interaction of
  the same kind (click, Enter/Space keyboard toggle, or drag-drop) for the same user is
  ignored rather than firing another request
- The guard clears once the in-flight request resolves (success or failure), so normal
  sequential use is unaffected
- No new UI affordance is required — `frontend/app-roster.js`'s existing interactions
  (card-image click/keyboard toggle, HTML5 drag-and-drop) are unchanged in appearance,
  only guarded against overlap

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/rate_limit.py` | Add a reusable per-user (fallback per-IP) key function |
| `backend/routers/cards.py` | Add `request: Request` param + `@limiter.limit(...)` to the four roster mutation routes |
| `.env.example` | Document `RATE_LIMIT_ROSTER_MUTATION` |
| `frontend/app-roster.js` | Add a shared in-flight guard checked by `activateCard`, `deactivateCard`, `toggleCardZone`, and the drag-drop swap/reorder handlers |
| `markdown/features/reference/roster-mutation-rate-limiting.md` | New reference doc (stub created by product-planner) |

No model changes, no migrations.

### Step 1 — Per-user key function
Add to `backend/rate_limit.py`, alongside the existing `limiter`:
```python
from starlette.requests import Request

def key_by_user_or_ip(request: Request) -> str:
    """Rate-limit key for authenticated routes: the session's user_id if present,
    otherwise fall back to source IP (defensive — these routes require login, so this
    branch should not normally be reached)."""
    user_id = request.session.get("user_id")
    return f"user:{user_id}" if user_id else get_remote_address(request)
```
This works the same way `login()`/`register()` already read `request.session[...]` directly —
`SessionMiddleware` has already decoded the session by the time slowapi's key function runs.

### Step 2 — Apply to the four routes
In `backend/routers/cards.py`:
```python
from rate_limit import limiter, key_by_user_or_ip

RATE_LIMIT_ROSTER_MUTATION = os.getenv("RATE_LIMIT_ROSTER_MUTATION", "30/minute")


@router.post("/roster/{card_id}/activate")
@limiter.limit(RATE_LIMIT_ROSTER_MUTATION, key_func=key_by_user_or_ip)
def activate_card(request: Request, card_id: int, db=Depends(get_db),
                   current_user: dict = Depends(get_current_user)):
    ...
```
Repeat for `deactivate_card`, `reorder_roster`, `swap_roster` — each gains a `request: Request`
parameter (slowapi requires it) and the same decorator. `Request` is already imported in this
file (`from fastapi import ... Request`), so no new import beyond `limiter`/`key_by_user_or_ip`.

### Step 3 — Document the env var
Add to `.env.example`, near the existing `RATE_LIMIT_*` block from issue #121:
```
# Per-user limit on roster activate/deactivate/swap/reorder. Default: 30/minute.
# RATE_LIMIT_ROSTER_MUTATION=30/minute
```

### Step 4 — Frontend in-flight guard
In `frontend/app-roster.js`, add a module-level flag and check it at the top of each mutating
path, mirroring the existing `window._rosterDragging` guard already used to suppress the
card-viewer click during a drag:
```javascript
let _rosterMutationInFlight = false;

async function _withRosterMutationGuard(fn) {
  if (_rosterMutationInFlight) return;
  _rosterMutationInFlight = true;
  try {
    await fn();
  } finally {
    _rosterMutationInFlight = false;
  }
}
```
Wrap the bodies of `activateCard`, `deactivateCard`, and the drag-drop swap/reorder branches
(around the existing `fetch(...)` calls at the swap/deactivate+reorder/reorder call sites) in
this helper, so a second interaction while one is already resolving is a no-op rather than a
second overlapping request.

### Step 5 — Fill in the feature doc stub
Update `markdown/features/reference/roster-mutation-rate-limiting.md` with the final values
and confirmed behavior once implemented.

---

## Verification
- `cd backend && python -m pytest tests/ -v` — existing roster tests (including the
  concurrency tests from issue #125) must stay green; a rate limit tight enough to interfere
  with those tests' rapid-fire concurrent calls would be a real regression, so verify the
  issue #125 concurrency tests still pass under whatever `RATE_LIMIT_ROSTER_MUTATION` default
  is chosen (they call the router functions directly / via `TestClient`, not necessarily as
  fast as 30 calls within a minute, but check)
- New tests: exceed `RATE_LIMIT_ROSTER_MUTATION` from one user and assert 429 with the
  established `{"detail": "Rate limit exceeded: ..."}` shape; confirm the limit is keyed by
  user (two different users each get their own budget) rather than shared IP-wide; confirm a
  single, normal-paced sequence of activate/deactivate/swap calls is unaffected
- Manual UI check: rapidly click/drag roster cards and confirm only one request fires at a
  time, with no visible glitching from overlapping in-flight responses
