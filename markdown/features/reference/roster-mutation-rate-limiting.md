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
keyed by session `user_id` instead — `key_by_user_or_ip()` in `backend/rate_limit.py`, falling
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

Each enforces `RATE_LIMIT_ROSTER_MUTATION` per user, returning the same
`{"detail": "Rate limit exceeded: ..."}` shape established by issue #121's rate limiting.

## Frontend guard

`frontend/app-roster.js` ignores a new activate/deactivate/swap/reorder interaction while a
previous one is still in flight, rather than allowing overlapping requests — no new UI
affordance, just a guard (`_rosterMutationInFlight` / `_withRosterMutationGuard()`) around the
existing click (`activateCard`/`deactivateCard`, also used by the keyboard Enter/Space
toggle via `toggleCardZone`) and HTML5 drag-and-drop interactions (in-zone reorder, bench→active
swap, active→bench deactivate+reorder, and drops onto empty active slots).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_ROSTER_MUTATION` | `30/minute` | Per-user limit on roster activate/deactivate/swap/reorder |
