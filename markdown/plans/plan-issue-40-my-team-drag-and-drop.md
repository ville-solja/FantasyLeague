# Plan: My Team — Drag-and-Drop Roster Ordering

## Context
The My Team tab displays up to five active cards in a grid and any remaining cards on a
bench, but neither zone can be reordered and moving cards between zones requires clicking
Activate/Deactivate buttons. Issue #40 requests full drag-and-drop: reorder within zones
and move cards between the active roster and bench by dragging. The issue also notes that
clicking outside an open card should close it — this backdrop-dismiss behaviour exists on the
draw result modal but was not applied to the card viewer path.
*Resolves GitHub issue #40.*

## User Stories

### Active Roster Drag-and-Drop Reorder
**User story**
As a player, I want to drag cards within my active roster to change their display order so
that I can arrange my lineup in a way that is meaningful to me.

**Acceptance criteria**
- Cards in the active roster grid are draggable
- Dragging a card onto another active card swaps their positions
- The new order is persisted to the backend so it survives a page refresh
- When the week is locked, drag is disabled and no visual drag handles are shown
- A visual drag-over indicator shows the drop target while dragging

### Cross-Zone Drag — Active to Bench
**User story**
As a player, I want to drag an active card onto the bench to deactivate it without clicking
a button, so that roster management is faster.

**Acceptance criteria**
- Dragging an active card and dropping it on the bench zone deactivates it
- The card appears at the start of the bench (or between existing bench cards if
  the bench renders as an ordered list)
- The active grid immediately re-renders to reflect the vacancy

### Bench Drag-and-Drop Reorder
**User story**
As a player, I want to drag cards within my bench to change their order so that I can
organise my reserve cards the same way I can my active roster.

**Acceptance criteria**
- Bench cards are draggable (when the week is unlocked)
- Dragging a bench card onto another bench card repositions it at that target position
- The new bench order is persisted to the backend so it survives a page refresh
- A visual drag-over indicator shows the drop target while dragging

### Cross-Zone Drag — Bench to Empty Active Slot
**User story**
As a player, I want to drag a bench card onto an empty slot in my active roster to activate
it without clicking a button.

**Acceptance criteria**
- When the active roster has fewer than five cards, empty drop zones are shown
- Dragging a bench card onto an empty slot activates the card into that position
- The bench immediately re-renders to reflect the card's removal
- The existing duplicate-player guard still applies (cannot activate if the same player is already active)

### Cross-Zone Drag — Bench to Populated Active Slot
**User story**
As a player, I want to drag a bench card onto an occupied active slot to swap the two cards
atomically, so that I can substitute one player for another without intermediate steps.

**Acceptance criteria**
- Dragging a bench card onto a card that is already active swaps their zones
- The bench card occupies the vacated slot index; the displaced active card moves to the bench
- The swap is a single backend operation (not two sequential activate/deactivate calls)
- The duplicate-player guard still applies; if the swap would violate it, the drop is rejected

### Card Viewer Backdrop Dismiss
**User story**
As a player, I want clicking outside an open card to close it so that I can dismiss the
card viewer without hunting for the close button.

**Acceptance criteria**
- Clicking the dark overlay area around the card viewer closes the modal
- Clicking inside the card content area does not close the modal
- The close button (X) continues to work as before
- The behaviour applies when a card is opened from the roster, bench, or any other context

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `slot_index` (Integer, nullable) to `Card` |
| `backend/migrate.py` | Migration `021_card_slot_index`: `ALTER TABLE cards ADD COLUMN slot_index INTEGER` |
| `backend/routers/cards.py` | New `POST /roster/reorder`, `POST /roster/swap`; sort by `slot_index` in `_build_roster_response` |
| `frontend/app-roster.js` | Full drag-and-drop: in-zone reorder + cross-zone move/swap |
| `frontend/app-cards.js` | Add backdrop-click listener on `#revealModal` overlay |

### Step 1 — Model column

Add to `Card` in `backend/models.py`:

```python
slot_index = Column(Integer, nullable=True)
```

`slot_index` records the card's preferred position within its current zone (active or bench).
`NULL` means unordered — cards sort after positioned cards, then by `card.id`. The field is
reused for both zones: after a zone transfer the frontend sends a reorder call to assign a
bench position to the newly deactivated card.

### Step 2 — Migration

```python
def _m021_card_slot_index(conn):
    cols = {r[1] for r in conn.execute(text("PRAGMA table_info(cards)")).fetchall()}
    if "slot_index" not in cols:
        conn.execute(text("ALTER TABLE cards ADD COLUMN slot_index INTEGER"))
        conn.commit()
```

Register as `("021_card_slot_index", _m021_card_slot_index)` in `MIGRATIONS`.

### Step 3 — Reorder endpoint

Handles in-zone reorder for either active or bench. Accepts an ordered list of card IDs;
sets `slot_index` to their position in that list.

```python
class ReorderRequest(BaseModel):
    card_ids: list[int]  # ordered list; zone inferred from is_active on each card

@router.post("/roster/reorder")
def reorder_roster(body: ReorderRequest, user=Depends(get_current_user), db=Depends(get_db)):
    user_id = user["user_id"]
    for idx, card_id in enumerate(body.card_ids):
        card = db.query(Card).filter_by(id=card_id, owner_id=user_id).first()
        if card:
            card.slot_index = idx
    db.commit()
    return {"ok": True}
```

The caller is responsible for only including cards from a single zone in one call. The
endpoint does not enforce zone consistency — it just assigns slot positions.

### Step 4 — Swap endpoint

Handles bench → populated-active-slot in a single atomic operation, bypassing the
`active_count >= ROSTER_LIMIT` guard that would block the sequential approach.

```python
class SwapRequest(BaseModel):
    bench_card_id: int   # card moving from bench → active
    active_card_id: int  # card moving from active → bench
    slot_index: int      # the active slot the bench card should occupy

@router.post("/roster/swap")
def swap_roster(body: SwapRequest, user=Depends(get_current_user), db=Depends(get_db)):
    user_id = user["user_id"]
    bench_card = db.query(Card).filter_by(id=body.bench_card_id, owner_id=user_id, is_active=False).first()
    active_card = db.query(Card).filter_by(id=body.active_card_id, owner_id=user_id, is_active=True).first()
    if not bench_card or not active_card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Duplicate-player guard
    duplicate = db.query(Card).filter(
        Card.owner_id == user_id,
        Card.player_id == bench_card.player_id,
        Card.is_active == True,
        Card.id != active_card.id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="A card for this player is already active")

    active_card.is_active = False
    active_card.slot_index = None  # or assign bench position
    bench_card.is_active = True
    bench_card.slot_index = body.slot_index
    db.commit()
    return {"ok": True}
```

### Step 5 — Sort order in roster GET

In `_build_roster_response` (or wherever active/bench lists are built), sort each zone by
`slot_index` (nulls last) then `card.id`:

```python
active = sorted(active_cards, key=lambda c: (c.slot_index is None, c.slot_index or 0, c.id))
bench  = sorted(bench_cards,  key=lambda c: (c.slot_index is None, c.slot_index or 0, c.id))
```

### Step 6 — Frontend drag-and-drop

Four drag scenarios handled in `app-roster.js`. Each card element carries `data-card-id`
and `data-zone="active"|"bench"`. Empty active slots are rendered as placeholder divs with
`data-zone="active" data-slot-index="N"` when the active count is below ROSTER_LIMIT.

**State carried on drag:**
```javascript
// dragstart on any card
e.dataTransfer.setData("application/json", JSON.stringify({ cardId: card.id, zone: card.is_active ? "active" : "bench" }));
```

**Drop handlers:**

| Drop target | Dragged from | Action |
|---|---|---|
| Active card | Active card | In-zone reorder → `POST /roster/reorder` |
| Bench card | Bench card | In-zone reorder → `POST /roster/reorder` |
| Active card | Bench card | Swap → `POST /roster/swap` |
| Empty active slot | Bench card | `POST /roster/{id}/activate` then `POST /roster/reorder` |
| Bench zone / bench card | Active card | `POST /roster/{id}/deactivate` then `POST /roster/reorder` to insert at position |

**Bench insertion position:** When an active card is dragged to the bench, the drop target
is either a specific bench card (insert before it, shifting subsequent `slot_index` values)
or the bench container itself (insert at `slot_index = 0`, i.e. start of bench). If the
bench is a simple grid rather than an ordered list, insert at slot 0 as the fallback —
implement the between-card insertion only if the bench renders as a list with clear
per-item drop zones.

**Visual feedback:** Add `.drag-over` CSS (subtle ring/background) to drop targets on
`dragover`; remove on `dragleave` or `drop`.

**Lock check:** Set `draggable="false"` on all card elements when `weekLocked` is true.

### Step 7 — Backdrop dismiss for card viewer

In `frontend/app-cards.js`, inside `showCard()` after `modal.classList.remove("hidden")`:

```javascript
modal.onclick = e => {
    if (e.target === modal) {
        modal.classList.add("hidden");
        _openCardId = null;
    }
};
```

`e.target === modal` ensures only clicks on the backdrop (not bubbled from card content)
close the modal. Same pattern used by the draw result modal.

---

## Verification

- Drag an active card to a different active position; reload — order persists.
- Drag a bench card onto another bench card; reload — bench order persists.
- Drag an active card to the bench; verify it deactivates and appears at the start of the bench.
- With a vacancy in the active grid, drag a bench card to the empty slot — it activates into that position.
- Drag a bench card onto a populated active slot — both cards swap zones atomically; the swapped-out card appears on the bench.
- Attempt a bench→active swap where the bench card shares a player with another active card — verify 409 rejection.
- Lock the week (or view a past week); confirm drag is disabled.
- Open a card from the roster; click the dark overlay — modal closes.
- Run `cd backend && python -m pytest tests/test_migrate.py -v` to confirm migration 021 is covered.
