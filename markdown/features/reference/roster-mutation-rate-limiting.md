# Roster Mutation Rate Limiting

Per-user rate limiting on the four roster mutation endpoints, plus a frontend in-flight guard,
closing a cheap DoS vector where rapid activate/deactivate/swap/reorder toggling (each
immediately followed by an expensive full-roster refetch) could meaningfully load the backend.

*(see `markdown/plans/plan-issue-124-roster-mutation-rate-limiting.md`, resolves GitHub issue
#124)*

---

## Approach

Reuses the shared `slowapi` `Limiter` built for issue #121 (`backend/rate_limit.py`) rather
than introducing a second rate-limiting mechanism. Unlike #121's endpoints (which key by
source IP, `slowapi.util.get_remote_address`), these four routes all require login, so they're
keyed by user instead — `key_by_user_or_ip()` in `backend/rate_limit.py` returns `user:{id}`
from `request.state.session_user_id` (set by `get_current_user`; since #117 the session cookie
carries only a session ID), falling
back to `get_remote_address()` only if somehow called unauthenticated.

The backend mutation endpoints already return lightweight confirmations, not the full roster —
the actual amplification was the frontend's immediate `loadRoster()` refetch after every single
toggle. Rather than redesigning that data flow, a frontend in-flight guard caps how often that
mutation+refetch pair can repeat, independent of the backend limit.

### Route split (implementation detail)

`backend/tests/test_issue_125_roster_limit_race_fix.py` and
`backend/tests/test_issue_40_my_team_drag_and_drop.py` both call `activate_card`,
`deactivate_card`, `reorder_roster`, and `swap_roster` directly as plain Python functions with
positional arguments (no `Request` object), bypassing `TestClient`/ASGI entirely. Since
slowapi's `@limiter.limit(...)` decorator requires a `request: Request` parameter on the
decorated function, adding it directly to those four functions would have shifted the existing
tests' positional arguments into the wrong parameters (silently, in the worst case).

Instead, `backend/routers/cards.py` keeps `activate_card`, `deactivate_card`, `reorder_roster`,
and `swap_roster` as plain, undecorated functions with their exact pre-existing signatures —
still directly importable/callable by those tests, unchanged. Each is paired with a thin
`*_route` wrapper (`activate_card_route`, `deactivate_card_route`, `reorder_roster_route`,
`swap_roster_route`) that FastAPI actually registers via `@router.post(...)`, carries the new
`request: Request` parameter and the `@limiter.limit(...)` decorator, and simply delegates to
the plain function with the already-resolved `db`/`current_user` dependencies.

## Endpoints affected

- `POST /roster/{card_id}/activate`
- `POST /roster/{card_id}/deactivate`
- `POST /roster/swap`
- `POST /roster/reorder`
- `PUT /roster` (issue #186: the whole layout; `save_roster` + `save_roster_route`)

Each enforces `RATE_LIMIT_ROSTER_MUTATION` per user, returning the same
shared 429 response, `{"detail": "Too many requests. Wait a moment and try again."}` (with `Retry-After`; the text changed in #184).

## Frontend: single-flight autosave

Since #186 My Team no longer sends one request per action. Every roster change (drag,
Enter/Space) edits the page's local layout, and the autosave in `frontend/app-roster.js`
stores the whole layout with `PUT /roster` 600 ms after the last move, one save at a time:
a move during a save marks the layout dirty and one follow-up save sends the newest layout
(`_runRosterSave`). A burst of moves therefore costs one request, and requests never overlap.
On a 429 the autosave waits for `Retry-After` (10 s without it) and retries once by itself,
still showing "Saving…"; only a second refusal shows "Couldn't save." with Retry. See
[My Team Fluid Roster](my-team-save-roster.md#autosave). The old
`_withRosterMutationGuard()` / `_rosterBusy` guard is gone.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_ROSTER_MUTATION` | `30/minute` | Per-user limit on roster activate/deactivate/swap/reorder and `PUT /roster` |
