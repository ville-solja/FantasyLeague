# Roster Limit Race Fix

Fixes a race condition that let a user activate more than `ROSTER_LIMIT` cards by firing
concurrent activation requests.

*(see `markdown/plans/plan-issue-125-roster-limit-race-fix.md`, resolves GitHub issue #125)*

---

## The vulnerability

`activate_card` (`backend/routers/cards.py`) did a plain read-check-write: count the user's
current active cards, compare against `ROSTER_LIMIT`, then set `is_active = True` and commit —
with no atomicity between the count and the write. Concurrent requests could all read the same
pre-activation count, all pass the check, and all commit, exceeding the limit by as much as the
number of concurrent requests fired. A community security disclosure (2026-09-18) reported
around 40 active cards on one account versus the intended limit of 5. `swap_roster`'s
duplicate-player guard had the same read-then-write shape, though a swap's net active count
can't itself exceed the limit (it deactivates one card for every one it activates).

## Fix

Both endpoints now use a single conditional `UPDATE ... WHERE` statement as the authoritative
gate immediately before commit — the same atomic-conditional-update pattern already applied to
the token-spend race condition this session (`database.py::spend_tokens`). SQLite serializes
writers, so the `WHERE` clause's subqueries (active-card count, duplicate-player check) and the
row mutation are evaluated atomically with respect to any other in-flight transaction — no
window exists for two concurrent requests to both pass the same stale check.

1. **`_activate_card_atomic()`** (`backend/card_utils.py`) — one `UPDATE` that only flips
   `is_active` if the card is owned by the caller, not already active, the active count is
   still under `ROSTER_LIMIT`, and no other active card belongs to the same player. Existing
   pre-checks in `activate_card` are kept for informative error messages on the normal
   (non-racing) path; the atomic helper is the real gate.
2. **`_swap_roster_atomic()`** (`backend/card_utils.py`) — activates the bench card only if no
   other active card belongs to the same player, then deactivates the previously-active card.
   Two statements, but both inside one transaction before `db.commit()`, so the pair is atomic
   from any other transaction's point of view.

`reorder_roster` was not touched — it only assigns `slot_index` within a card's current zone and
never changes `is_active`, so it cannot cause a limit violation.

Covered by new concurrency tests in `backend/tests/test_issue_125_roster_limit_race_fix.py`:
firing many concurrent activate/swap requests and asserting the final active count and
per-player uniqueness invariants hold, alongside regression coverage for every existing
single-request status code (200/404/409 variants unchanged).
