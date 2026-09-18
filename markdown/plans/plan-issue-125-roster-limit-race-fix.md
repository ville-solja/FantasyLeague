# Plan: Roster Limit Race Fix

## Context
A community security disclosure (2026-09-18) found that the active-roster limit (`ROSTER_LIMIT`,
default 5) can be bypassed by firing many concurrent `POST /roster/{card_id}/activate` requests —
reportedly around 40 active cards ended up on one account. `activate_card`
(`backend/routers/cards.py`) does a plain read-check-write: it counts current active cards, checks
that count against `ROSTER_LIMIT`, then sets `is_active = True` and commits, with no locking or
atomicity between the count and the write. Concurrent requests can all read the same
pre-activation count, all pass the check, and all commit — the exact same class of bug already
fixed this session for token spending (`database.py::spend_tokens`, a conditional `UPDATE ...
WHERE tokens >= :amt` in place of a naive read-then-decrement). This plan applies the same
atomic-conditional-UPDATE pattern here.

`swap_roster`'s duplicate-player guard has the identical shape (read the guard, then write) and
is included for the same reason, even though a swap's *count* can never exceed the limit on its
own (it deactivates one card for every one it activates — net zero). `reorder_roster` only
assigns `slot_index` within a card's current zone and never touches `is_active`, so it cannot
cause a limit violation and is out of scope here. *Resolves GitHub issue #125.*

## User Stories

### Atomic Roster Activation Limit Enforcement
**User story**
As a player, I want the active-roster limit to be enforced correctly even under concurrent
activation requests, so that I can never end up with more active cards than the game intends
(and no one can exploit this for an unfair scoring advantage).

**Acceptance criteria**
- Firing many concurrent `POST /roster/{card_id}/activate` requests for the same user against
  distinct bench cards never results in more than `ROSTER_LIMIT` active cards, regardless of
  how many requests race
- A single, sequential activation request still behaves exactly as before: success when under
  the limit, 404 for a missing/foreign card, 409 "Card already active", 409 "Roster full ({N}
  cards max)" at the limit, 409 duplicate-player guard when another active card already has
  the same player
- The fix does not change the existing successful-path response shape
  (`{"status": "ok", "card_id": ...}`)

### Atomic Duplicate-Player Guard on Roster Swap
**User story**
As a player, I want `POST /roster/swap`'s duplicate-player guard to hold up under concurrent
swap requests, so that I can never end up with two active cards for the same player even if
overlapping swap requests race.

**Acceptance criteria**
- Firing concurrent `POST /roster/swap` requests that could both pass a naive read-then-write
  duplicate-player check never results in two active cards for the same player
- A single, sequential swap request still behaves exactly as before: 404 for missing cards, 409
  duplicate-player guard, and the existing bench↔active flip with `slot_index` handling
  unchanged

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/card_utils.py` | Add `_activate_card_atomic()` and `_swap_roster_atomic()` helpers — same module that already hosts card-domain-specific shared logic (`_assign_modifiers`, `_card_modifiers_map`) |
| `backend/routers/cards.py` | `activate_card` and `swap_roster` call the new atomic helpers instead of doing their own read-then-write |

No model changes, no migrations — this is a query-shape fix, not a schema change.

### Step 1 — Atomic activation helper
Add to `backend/card_utils.py`, following the exact pattern `database.py::spend_tokens` already
established this session (single conditional `UPDATE`, checked via `rowcount`, instead of a
separate read-then-write):
```python
def _activate_card_atomic(db, card_id: int, user_id: int, player_id: int, roster_limit: int) -> bool:
    """Atomically activate a card if the user still has room and no duplicate-player
    conflict exists. Returns True if activated, False if any condition failed.

    A single UPDATE...WHERE (not a separate SELECT COUNT then UPDATE) closes the race
    where concurrent requests all read the same pre-activation count and all pass —
    SQLite serializes writers, so the WHERE clause's subqueries and the row mutation
    are evaluated atomically with respect to any other in-flight transaction.
    """
    result = db.execute(text("""
        UPDATE cards
        SET is_active = 1
        WHERE id = :card_id
          AND owner_id = :user_id
          AND is_active = 0
          AND (
              SELECT COUNT(*) FROM cards
              WHERE owner_id = :user_id AND is_active = 1
          ) < :roster_limit
          AND NOT EXISTS (
              SELECT 1 FROM cards c2
              WHERE c2.owner_id = :user_id
                AND c2.player_id = :player_id
                AND c2.is_active = 1
                AND c2.id != :card_id
          )
    """), {"card_id": card_id, "user_id": user_id, "player_id": player_id,
           "roster_limit": roster_limit})
    return result.rowcount > 0
```

### Step 2 — Wire into `activate_card`
Keep the existing pre-checks in `backend/routers/cards.py::activate_card` as-is (card exists,
owned by caller, not already active, roster count, duplicate-player) — they give the caller a
specific, informative error on the common single-request path. Add the atomic helper as the
authoritative gate immediately before commit, mirroring how `spend_tokens()` was wired into
`draw_card`/`draw_booster`/`reroll_modifiers`:
```python
if not _activate_card_atomic(db, card_id, user_id, card.player_id, ROSTER_LIMIT):
    db.rollback()
    raise HTTPException(status_code=409, detail=f"Roster full ({ROSTER_LIMIT} cards max)")
db.commit()
return {"status": "ok", "card_id": card_id}
```
Since the atomic UPDATE bypasses the ORM's identity map for the `card` object already loaded
earlier in the function, no `db.refresh()` is needed here (unlike the token-spend sites) because
nothing after this point reads `card.is_active` from the stale in-memory object.

### Step 3 — Atomic swap helper
```python
def _swap_roster_atomic(db, bench_card_id: int, active_card_id: int, user_id: int,
                         bench_player_id: int, slot_index) -> bool:
    """Atomically flip bench_card active and active_card inactive, only if bench_card's
    player has no other active card. Returns True if the swap happened."""
    result = db.execute(text("""
        UPDATE cards
        SET is_active = 1, slot_index = :slot_index
        WHERE id = :bench_card_id
          AND owner_id = :user_id
          AND is_active = 0
          AND NOT EXISTS (
              SELECT 1 FROM cards c2
              WHERE c2.owner_id = :user_id
                AND c2.player_id = :bench_player_id
                AND c2.is_active = 1
                AND c2.id != :active_card_id
          )
    """), {"bench_card_id": bench_card_id, "user_id": user_id,
           "bench_player_id": bench_player_id, "active_card_id": active_card_id,
           "slot_index": slot_index})
    if result.rowcount == 0:
        return False
    db.execute(text("""
        UPDATE cards SET is_active = 0, slot_index = NULL
        WHERE id = :active_card_id AND owner_id = :user_id AND is_active = 1
    """), {"active_card_id": active_card_id, "user_id": user_id})
    return True
```
Two statements, not one, since a card can't hold two roles at once mid-statement — but both run
inside the same DB transaction/session before `db.commit()`, so the pair is still atomic from
any other transaction's point of view (SQLite's writer serialization means no other write can
observe the intermediate state between them). Order matters: activate the bench card first
(gated on the duplicate check) so a failed guard never deactivates the existing active card.

### Step 4 — Wire into `swap_roster`
Replace the existing duplicate-check-then-flip block with:
```python
if not _swap_roster_atomic(db, body.bench_card_id, body.active_card_id, user_id,
                            bench_card.player_id, body.slot_index):
    db.rollback()
    raise HTTPException(status_code=409, detail="A card for this player is already active")
db.commit()
return {"ok": True}
```
Keep the existing pre-fetch of `bench_card`/`active_card` (for the 404 check) ahead of this.

---

## Verification
- `cd backend && python -m pytest tests/ -v` — existing roster/card tests must stay green,
  especially any covering `activate_card`/`swap_roster`'s existing error paths (404, already
  active, roster full, duplicate player)
- New tests: fire many concurrent `activate_card` calls (via threads or a tight loop against
  `TestClient`, or by calling the atomic helper directly across multiple DB sessions sharing one
  SQLite file) against more bench cards than `ROSTER_LIMIT` allows, and assert the final active
  count never exceeds `ROSTER_LIMIT`; same shape for `swap_roster` against two bench cards for
  the same player racing to fill one active slot, asserting only one ever lands
- Confirm the single-request (non-concurrent) behavior for every existing status code
  (200/404/409 variants) is unchanged
