# Plan: Admin Player Pool Management

## Context
Admins currently have no UI to control which players are in the known player pool — players
enter only through bulk data ingestion. When a player leaves the league mid-season, there is
no way to deactivate them or compensate the users who hold their cards. This plan adds an
admin Player Pool panel that covers the full lifecycle: add individual players by OpenDota ID,
bulk-add via CSV, and remove players with automatic per-card token refunds. Soft-deletion
(an `is_active` flag on the `Player` row) is used so that historical `player_match_stats`
records and card history are preserved. *Resolves GitHub issue #71.*

## User Stories

### Manage the Player Pool (Admin)
**User story**
As an admin, I want to view and manage the known player pool so that I can control which
players are available for card draws.

**Acceptance criteria**
- Admin tab shows a "Player Pool" section listing all players with name, OpenDota ID, and
  the number of active cards held by users
- Rows are selectable via checkboxes
- A "Remove Selected" button is inactive until at least one row is checked

---

### Add a Player by OpenDota ID (Admin)
**User story**
As an admin, I want to add a player to the pool by entering their OpenDota account ID, so
that new players can be included in card draws without a full data ingest.

**Acceptance criteria**
- An "Add Player" button opens a popup with an ID input, a Close button, and a Confirm button
- On Confirm, the backend validates the ID against OpenDota and fetches the player's name
  and avatar URL
- If the ID does not resolve on OpenDota, a clear error is shown and the player is not added
- If the player already exists in the pool (active or inactive), the endpoint returns a
  clear error and does not create a duplicate
- On success, the player is marked active and appears in the table immediately
- The action is logged to the audit log as `admin_player_added`

---

### Bulk Add Players via CSV (Admin)
**User story**
As an admin, I want to paste a comma-separated list of OpenDota account IDs to add multiple
players at once, so that I can populate the pool at season start without repeated single-add
operations.

**Acceptance criteria**
- A "Bulk Add" button opens a popup with a single-line CSV text input and a Confirm button
- On Confirm, the backend processes each ID: valid new IDs are added; invalid or already-present
  IDs are skipped
- The response reports how many were added and lists skipped IDs with reasons
- The bulk add action is logged to the audit log as `admin_player_bulk_added`

---

### Remove Players with Token Refund (Admin)
**User story**
As an admin, I want to remove selected players from the pool (with a confirmation step) so
that players who leave the league are excluded from future draws and card holders are
automatically compensated.

**Acceptance criteria**
- Clicking "Remove Selected" opens a confirmation popup listing the selected player names
- On Confirm, the backend sets `is_active = false` on each selected `Player` row (soft delete)
- All `Card` rows belonging to any user that reference a removed player are set to
  `is_active = false`
- Each user who loses one or more cards receives 1 token per deactivated card as a refund,
  applied immediately
- Historical `player_match_stats` rows are left unchanged
- Each removal is logged to the audit log as `admin_player_removed`; each refund batch is
  logged as `admin_player_refund_issued`
- Removing a player who has no active card holders completes silently (no refunds, no error)

---

### Receive a Refund Token (Player)
**User story**
As a player, I want to automatically receive a token when an admin removes a player whose
card I hold, so that I can draw a replacement without losing my token investment.

**Acceptance criteria**
- Token balance increases by 1 for each card the player holds that belongs to a removed player
- The refund is applied at the moment the admin confirms the removal
- Deactivated cards are no longer shown as drawable or activatable, but may still appear in
  historical views
- No additional notification popup is triggered (the token balance update alone is sufficient)

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | Add `is_active` column to `Player` |
| `backend/migrate.py` | Migration to add `is_active` column to `players` table |
| `backend/routers/admin.py` | Add player pool endpoints: list, add, bulk-add, remove |
| `frontend/app-admin.js` | Player pool panel functions |
| `frontend/index.html` | Player pool section in admin tab |

### Step 1 — Model change and migration

Add `is_active` to `Player` in `backend/models.py`:

```python
class Player(Base):
    __tablename__ = "players"

    id         = Column(Integer, primary_key=True)  # OpenDota account_id
    name       = Column(String)
    avatar_url = Column(String)
    is_active  = Column(Boolean, default=True, nullable=False)
```

Add a migration to `backend/migrate.py` inside `run_migrations()`:

```python
cols = {r[1] for r in db.execute(text("PRAGMA table_info(players)")).fetchall()}
if "is_active" not in cols:
    db.execute(text("ALTER TABLE players ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"))
    db.commit()
```

Run `cd backend && python -m pytest tests/test_migrate.py -v` to confirm.

### Step 2 — Admin endpoints

Add to `backend/routers/admin.py`:

```python
class AddPlayerBody(BaseModel):
    player_id: int

class BulkAddPlayersBody(BaseModel):
    player_ids: str = Field(..., min_length=1, max_length=2000)  # CSV string

class RemovePlayersBody(BaseModel):
    player_ids: List[int]
```

**`GET /admin/players`** — list all players (active and inactive) with active card count:

```python
@router.get("/admin/players")
def list_players(db=Depends(get_db), _=Depends(require_admin)):
    rows = db.query(Player).order_by(Player.name).all()
    result = []
    for p in rows:
        card_count = db.query(Card).filter(
            Card.player_id == p.id, Card.is_active == True
        ).count()
        result.append({
            "id": p.id, "name": p.name,
            "is_active": p.is_active, "active_card_count": card_count
        })
    return result
```

**`POST /admin/players`** — add one player by OpenDota ID:

```python
@router.post("/admin/players")
def add_player(body: AddPlayerBody, db=Depends(get_db), admin=Depends(require_admin)):
    existing = db.get(Player, body.player_id)
    if existing:
        raise HTTPException(409, "Player already exists in pool")
    # Fetch from OpenDota
    resp = requests.get(f"https://api.opendota.com/api/players/{body.player_id}", timeout=10)
    if resp.status_code != 200 or not resp.json().get("profile"):
        raise HTTPException(422, "Player not found on OpenDota")
    data = resp.json()["profile"]
    p = Player(id=body.player_id, name=data.get("personaname", str(body.player_id)),
               avatar_url=data.get("avatarfull", ""), is_active=True)
    db.add(p)
    _audit(db, "admin_player_added", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"player_id={body.player_id}")
    db.commit()
    return {"id": p.id, "name": p.name}
```

**`POST /admin/players/bulk`** — add multiple players by CSV:

```python
@router.post("/admin/players/bulk")
def bulk_add_players(body: BulkAddPlayersBody, db=Depends(get_db),
                     admin=Depends(require_admin)):
    raw_ids = [s.strip() for s in body.player_ids.split(",") if s.strip()]
    added, skipped = [], []
    for raw in raw_ids:
        try:
            pid = int(raw)
        except ValueError:
            skipped.append({"id": raw, "reason": "not an integer"})
            continue
        if db.get(Player, pid):
            skipped.append({"id": pid, "reason": "already exists"})
            continue
        resp = requests.get(f"https://api.opendota.com/api/players/{pid}", timeout=10)
        if resp.status_code != 200 or not resp.json().get("profile"):
            skipped.append({"id": pid, "reason": "not found on OpenDota"})
            continue
        data = resp.json()["profile"]
        db.add(Player(id=pid, name=data.get("personaname", str(pid)),
                      avatar_url=data.get("avatarfull", ""), is_active=True))
        added.append(pid)
    if added:
        _audit(db, "admin_player_bulk_added", actor_id=admin["user_id"],
               actor_username=admin["username"], detail=f"added={len(added)}")
    db.commit()
    return {"added": len(added), "skipped": skipped}
```

**`POST /admin/players/remove`** — soft-delete players and issue refunds:

```python
@router.post("/admin/players/remove")
def remove_players(body: RemovePlayersBody, db=Depends(get_db),
                   admin=Depends(require_admin)):
    for pid in body.player_ids:
        player = db.get(Player, pid)
        if not player or not player.is_active:
            continue
        player.is_active = False
        # Deactivate cards and refund owners
        cards = db.query(Card).filter(Card.player_id == pid, Card.is_active == True).all()
        refund_totals: dict[int, int] = {}
        for card in cards:
            card.is_active = False
            refund_totals[card.owner_id] = refund_totals.get(card.owner_id, 0) + 1
        for user_id, token_count in refund_totals.items():
            user = db.get(User, user_id)
            if user:
                user.tokens = (user.tokens or 0) + token_count
                _audit(db, "admin_player_refund_issued", actor_id=admin["user_id"],
                       actor_username=admin["username"],
                       detail=f"player_id={pid} user_id={user_id} tokens={token_count}")
        _audit(db, "admin_player_removed", actor_id=admin["user_id"],
               actor_username=admin["username"], detail=f"player_id={pid}")
    db.commit()
    return {"ok": True}
```

Note: Use `POST /admin/players/remove` rather than `DELETE` to support a JSON body with a list
of IDs, which is consistent with multi-select semantics and avoids body-on-DELETE issues.

### Step 3 — Frontend: Player Pool panel

In `frontend/index.html`, add a "Player Pool" section to the admin tab alongside other admin
panels. It needs:
- A table (`<table id="playerPoolTable">`) with columns: checkbox, Name, OpenDota ID,
  Active Cards
- "Add Player" button → triggers the single-add popup
- "Bulk Add" button → triggers the CSV popup
- "Remove Selected" button (disabled by default, enabled when ≥1 checkbox checked)

In `frontend/app-admin.js`, add:

```js
async function loadPlayerPool() { /* GET /admin/players, render table */ }
async function addPlayer(playerId) { /* POST /admin/players */ }
async function bulkAddPlayers(csv) { /* POST /admin/players/bulk */ }
async function removeSelectedPlayers() { /* POST /admin/players/remove with checked IDs */ }
```

Call `loadPlayerPool()` from the admin tab init in `frontend/app-globals.js`.

The "Remove Selected" button must display a confirmation popup listing the player names
before calling `removeSelectedPlayers()`.

---

## Verification
- Add a player by valid OpenDota ID → appears in the table, name populated from OpenDota
- Add a player by invalid ID → 422 returned, error shown in popup
- Add an already-existing player → 409 returned, clear error shown
- Bulk add a CSV of mixed valid/invalid/duplicate IDs → summary shows correct added/skipped counts
- Remove a player who has no active cards → completes silently, no token change for any user
- Remove a player whose cards are held by two different users → each user gains 1 token per
  card; cards set to `is_active = false`; `player_match_stats` rows unchanged
- Removed player still appears in audit log
- After removal, the player row is still in the DB (`is_active = false`); historical scores
  still display correctly
- `cd backend && python -m pytest tests/test_migrate.py -v` passes
