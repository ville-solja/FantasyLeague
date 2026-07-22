# My Team — Drag-and-Drop Roster Ordering

Adds full drag-and-drop to the My Team tab: reorder cards within the active roster or bench,
and move cards between zones by dragging. Also adds backdrop-click dismissal for the card
viewer modal.

---

## Drag Zones

The My Team tab has two drop zones:

- **Active grid** — up to 5 cards. Empty slots are rendered as placeholders when the count
  is below the roster limit.
- **Bench** — all remaining cards. No fixed slot count.

When the current week is locked, all drag handles are disabled.

---

## Drag Scenarios

| Drag from | Drop onto | Result |
|---|---|---|
| Active card | Active card | Swap positions (in-zone reorder) |
| Bench card | Bench card | Swap positions (in-zone reorder) |
| Active card | Bench zone or bench card | Deactivate; card inserts at start of bench (or between bench cards if ordered-list bench) |
| Bench card | Empty active slot | Activate into that slot |
| Bench card | Populated active slot | Atomic swap — bench card activates into the slot, active card deactivates to bench |

---

## Data Model

**`cards.slot_index`** (new column, Integer, nullable):
Zero-based integer recording the card's preferred position within its current zone. Shared
between active and bench: after a zone transfer the frontend issues a reorder call to assign
the card a position in its new zone. `NULL` means unordered — cards sort after positioned
cards, then by `card.id`.

Migration: `021_card_slot_index` — `ALTER TABLE cards ADD COLUMN slot_index INTEGER`.

---

## Endpoints

### `GET /roster/{user_id}` *(modified)*
Active and bench lists are both returned sorted by `slot_index` (nulls last), then by
`card.id` as a tiebreaker.

### `POST /roster/reorder`
Accepts `{"card_ids": [int, ...]}`. Sets `slot_index` to the list position for each card.
Used for in-zone reorder and for assigning a bench position after a zone transfer. Only
cards owned by the authenticated user are updated; unrecognised IDs are silently skipped.

### `POST /roster/swap`
Accepts `{"bench_card_id": int, "active_card_id": int, "slot_index": int}`. Atomically
deactivates the active card (clearing its `slot_index` to `NULL`) and activates the bench
card into the given slot. Applies the same duplicate-player guard as the existing activate
endpoint. Returns 404 if either card is not found or not in the expected zone; 409 if the
duplicate-player guard fires.

### `POST /roster/{card_id}/activate` and `POST /roster/{card_id}/deactivate` *(existing)*
Used for bench→empty-slot and active→bench drags respectively, followed by a reorder call.

---

## Backdrop Dismiss

Clicking the dark overlay surrounding the card viewer closes the modal (`e.target === modal`
guard, same pattern as draw result modal). Clicks inside the card content box are stopped by
`stopPropagation()` on the inner container.

