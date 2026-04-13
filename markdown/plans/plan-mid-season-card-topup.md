# Plan: Mid-Season Card Top-Up

## Context

The current card pool is generated once per season via `seed_cards(league_id)` in `backend/seed.py`. It creates **1 legendary, 2 epic, 4 rare, 8 common** cards per player per league. If more users join than anticipated, the deck runs dry and new users have nothing to draw. The goal is to allow an admin to top up the pool mid-season while keeping distribution proportions intact (scarcity of legendaries must be preserved).

## Current State

- `seed_cards()` in `backend/seed.py` is fully idempotent: if **any** card exists for a `(player_id, league_id)` pair, the whole player is skipped.
- `CARD_SCHEMA = [("legendary", 1), ("epic", 2), ("rare", 4), ("common", 8)]` — 15 cards per player.
- `Card` model has: `id`, `player_id`, `owner_id` (NULL = unowned), `card_type`, `league_id`, `is_active`.
- No unique constraint prevents multiple cards of the same rarity per player per league.
- Draw logic queries `owner_id IS NULL` — a growing pool is fully compatible.

## Approach Comparison

Three viable approaches, evaluated against the core constraint (distribution stays proportional, legendaries remain scarce):

### Option A — Generation batches (recommended)

Add a `generation` integer column to `Card` (default `1`). Each top-up adds one full `CARD_SCHEMA` batch as `generation=2`, `generation=3`, etc. Idempotency is per-generation: "skip player if a card for this (player, league, generation) already exists."

- **Distribution**: identical to the original — each generation is exactly 1L/2E/4R/8C.
- **Admin control**: explicit; admin picks when to add a generation.
- **Idempotency**: safe to re-run; won't double-add.
- **Auditability**: generation column makes it easy to see how many rounds have been issued.
- **DB change**: one new nullable column with default 1 on `cards`; existing rows get `generation=1` via ALTER TABLE default.

### Option B — Admin-supplied counts, no schema change

Add `POST /admin/top-up-cards` that accepts `extra_per_rarity: dict` and adds the specified counts per player. No DB schema change.

- **Distribution**: depends entirely on admin input — easy to accidentally issue too many legendaries.
- **Admin control**: flexible but error-prone.
- **No generation tracking**: cannot tell how many top-ups have been applied or re-run safely.

### Option C — Automatic threshold-based top-up

When the unowned card count drops below a threshold (e.g. `< num_users * 2`), automatically generate another batch in the poll loop or on draw.

- **Distribution**: fine if it triggers at the right moment.
- **Unpredictable for admins**: fires silently, hard to audit, harder to explain to users.
- **Complexity**: requires tuning the threshold and handling edge cases.

**Recommendation: Option A.** It preserves distribution exactly, is idempotent, adds a clear audit trail, and requires one small schema change.

---

## Implementation Plan (Option A)

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `generation` column to `Card` |
| `backend/seed.py` | Update `seed_cards()` to accept and respect `generation` |
| `backend/main.py` | Add `POST /admin/top-up-cards` endpoint; existing call sites unchanged |

### Step 1 — `backend/models.py`: Add `generation` to `Card`

```python
class Card(Base):
    ...
    generation = Column(Integer, default=1, nullable=False)
```

Migration in `lifespan()` (existing PRAGMA pattern already used for other columns):

```python
cols = [r[1] for r in conn.execute(text("PRAGMA table_info(cards)")).fetchall()]
if "generation" not in cols:
    conn.execute(text("ALTER TABLE cards ADD COLUMN generation INTEGER NOT NULL DEFAULT 1"))
    conn.commit()
```

### Step 2 — `backend/seed.py`: Update `seed_cards()`

Change signature to `seed_cards(league_id: int, generation: int = 1)`.

Change the idempotency check from "any card for this player+league" to "any card for this player+league+generation":

```python
already_seeded = db.query(Card).filter(
    Card.player_id == player_id,
    Card.league_id == league_id,
    Card.generation == generation,
).count()
```

Pass `generation=generation` when creating each `Card` row. All existing call sites pass no `generation` argument, so they continue to target generation 1 unchanged.

### Step 3 — `backend/main.py`: Top-up endpoint

Add a `TopUpCardsBody` Pydantic model and the endpoint:

```python
class TopUpCardsBody(BaseModel):
    league_id: int

@app.post("/admin/top-up-cards")
def top_up_cards(body: TopUpCardsBody, admin: dict = Depends(require_admin)):
    """Add one more full card batch (1L/2E/4R/8C per player) to the unowned pool."""
    from sqlalchemy import func
    db = SessionLocal()
    max_gen = db.query(func.max(Card.generation)).filter(
        Card.league_id == body.league_id
    ).scalar() or 1
    next_gen = max_gen + 1
    db.close()

    seed_cards(body.league_id, generation=next_gen)

    db2 = SessionLocal()
    _audit(db2, "admin_top_up_cards", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"league_id={body.league_id} generation={next_gen}")
    db2.commit()
    db2.close()
    return {"league_id": body.league_id, "generation_added": next_gen}
```

---

## What Stays the Same

- Draw logic is unaffected — it queries `owner_id IS NULL` across all generations.
- `CARD_SCHEMA` is untouched — distribution is always 1L/2E/4R/8C per generation per player.
- Past weekly roster snapshots are unaffected.
- Existing `seed_cards()` call sites (auto-ingest, manual ingest endpoint) continue to target generation 1 with no argument change.

## Verification

1. Seed a league normally; confirm deck shows expected counts (e.g. 1 legendary per player in pool).
2. Call `POST /admin/top-up-cards` with that `league_id`.
3. Confirm deck counts doubled (2 legendary, 4 epic, 8 rare, 16 common per player in pool).
4. Call again — confirm it adds generation 3, not duplicates.
5. Draw all cards; confirm draw still works and prefers unseen players across generations.
