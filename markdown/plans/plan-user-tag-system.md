# Plan: User Tag System

## Context
Admins want to visually recognise notable users — casters who stream Kanaliiga matches,
previous season winners, and other future categories — both on their player cards and in
the leaderboard. Rather than hard-coding per-category logic, this plan introduces a generic
tag system: admins define tags (name + sticker asset) and grant them to users. New tag
types require no code change — just a new row and a sticker image. The feature also adds a
search bar to the Token Balances table in the admin tab to cope with large user lists.
Resolves GitHub issue #54.

*Assumptions:*
- *Tags are granted to **users** (app accounts). The sticker appears on cards belonging to
  a player whose OpenDota `account_id` matches the tagged user's `player_id`.*
- *Sticker images are PNG assets stored at `assets/stickers/{tag_key}.png`. Placeholder
  images are included for `caster` and `season_winner` at plan time.*
- *A user can hold multiple tags; all stickers are composited on their card.*

## User Stories

### See Tag Stickers on a Player Card
**User story**
As a fantasy user, I want to see sticker badges on cards belonging to tagged users (e.g.
casters, season winners) so that I can recognise notable personalities in my roster.

**Acceptance criteria**
- Any card whose underlying player is linked to a user with one or more tags displays
  each tag's sticker image composited onto the card PNG
- Users with no tags have no stickers on their cards
- Sticker positions do not overlap the player avatar or name plate
- The card PNG returned by `GET /cards/{card_id}/image` reflects the current tag state

### See Tags in the Leaderboard
**User story**
As a fantasy user, I want to see a user's tags alongside their name in the leaderboard
so that notable participants are identifiable at a glance.

**Acceptance criteria**
- Season and weekly leaderboard entries include a `tags` array (`[{"key": "caster", "label": "Caster"}, ...]`)
- The frontend renders tag labels (or small icon chips) next to the username in the leaderboard table
- Users with no tags have an empty `tags` array — no visual element rendered

### Manage Tags in the Admin Panel
**User story**
As an admin, I want to define tag types and grant or revoke them from users directly in
the Token Balances table so that I can recognise any user without touching code.

**Acceptance criteria**
- Admin tab "Token Balances" section shows each user's current tags as chips
- A "Manage Tags" control per user row allows granting and revoking any defined tag
- Changes are logged to the audit log as `admin_tag_grant` and `admin_tag_revoke`
- A separate "Tag Definitions" section allows creating new tag types (key, label) and
  deleting unused ones
- Creating a tag with a duplicate key returns a 409 error

### Search Users in the Token Balances Table
**User story**
As an admin, I want to search the Token Balances table by username so that I can quickly
find a specific user in a large list.

**Acceptance criteria**
- A search input above the Token Balances table filters rows client-side as the admin types
- The filter is case-insensitive and matches any substring of the username
- Clearing the search restores all rows
- The filter state does not persist across page reloads

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | Add `TagDefinition` and `UserTag` models |
| `backend/migrate.py` | Add migration for the two new tables |
| `backend/routers/admin.py` | Add tag definition CRUD + grant/revoke endpoints |
| `backend/routers/leaderboard.py` | Include `tags` in leaderboard response rows |
| `backend/routers/cards.py` (or image endpoint) | Pass user tags to image generator |
| `backend/image.py` | Composite sticker PNGs onto card image |
| `backend/seed.py` | Seed initial tag definitions: `caster`, `season_winner` |
| `assets/stickers/` | Add placeholder PNGs: `caster.png`, `season_winner.png` |
| `frontend/app-admin.js` | Tag management UI; search bar for Token Balances table |
| `frontend/index.html` | Tag Definitions panel; search input; tag chips in user rows |

### Step 1 — Models

Add to `backend/models.py`:

```python
class TagDefinition(Base):
    __tablename__ = "tag_definitions"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    key         = Column(String, unique=True, nullable=False)   # e.g. "caster"
    label       = Column(String, nullable=False)                # e.g. "Caster"
    created_at  = Column(Integer)                               # Unix timestamp


class UserTag(Base):
    __tablename__ = "user_tags"
    __table_args__ = (UniqueConstraint("user_id", "tag_id", name="uq_user_tag"),)

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    tag_id      = Column(Integer, ForeignKey("tag_definitions.id"), nullable=False)
    granted_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_at  = Column(Integer)
```

### Step 2 — Migration

Add to `run_migrations()` in `backend/migrate.py`:

```python
# Migration N — User tag system
tables = {r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
if "tag_definitions" not in tables:
    db.execute(text("""
        CREATE TABLE tag_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL,
            created_at INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE user_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            tag_id INTEGER NOT NULL REFERENCES tag_definitions(id),
            granted_by INTEGER REFERENCES users(id),
            granted_at INTEGER,
            UNIQUE(user_id, tag_id)
        )
    """))
    db.commit()
```

### Step 3 — Seed initial tag definitions

Add to `backend/seed.py` (a new `seed_tags()` function, called from the lifespan startup):

```python
INITIAL_TAGS = [
    {"key": "caster",        "label": "Caster"},
    {"key": "season_winner", "label": "Season Winner"},
]

def seed_tags():
    db = SessionLocal()
    try:
        for t in INITIAL_TAGS:
            if not db.query(TagDefinition).filter_by(key=t["key"]).first():
                db.add(TagDefinition(key=t["key"], label=t["label"],
                                     created_at=int(time.time())))
        db.commit()
    finally:
        db.close()
```

### Step 4 — Admin endpoints

Add to `backend/routers/admin.py`:

```python
# --- Tag definitions ---

class TagBody(BaseModel):
    key:   str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)

@router.get("/admin/tags")
def list_tags(db=Depends(get_db), _=Depends(require_admin)):
    return [{"id": t.id, "key": t.key, "label": t.label}
            for t in db.query(TagDefinition).order_by(TagDefinition.key).all()]

@router.post("/admin/tags")
def create_tag(body: TagBody, db=Depends(get_db), admin=Depends(require_admin)):
    if db.query(TagDefinition).filter_by(key=body.key).first():
        raise HTTPException(409, "Tag key already exists")
    tag = TagDefinition(key=body.key, label=body.label, created_at=int(time.time()))
    db.add(tag); db.flush()
    _audit(db, "admin_tag_definition_created", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"key={body.key}")
    db.commit()
    return {"id": tag.id}

@router.delete("/admin/tags/{tag_id}")
def delete_tag(tag_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    tag = db.get(TagDefinition, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    db.query(UserTag).filter_by(tag_id=tag_id).delete()
    _audit(db, "admin_tag_definition_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"key={tag.key}")
    db.delete(tag); db.commit()
    return {"ok": True}

# --- User tag grants ---

@router.post("/admin/users/{user_id}/tags/{tag_id}")
def grant_tag(user_id: int, tag_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    if not db.get(User, user_id):
        raise HTTPException(404, "User not found")
    if not db.get(TagDefinition, tag_id):
        raise HTTPException(404, "Tag not found")
    existing = db.query(UserTag).filter_by(user_id=user_id, tag_id=tag_id).first()
    if not existing:
        db.add(UserTag(user_id=user_id, tag_id=tag_id,
                       granted_by=admin["user_id"], granted_at=int(time.time())))
        tag = db.get(TagDefinition, tag_id)
        _audit(db, "admin_tag_grant", actor_id=admin["user_id"],
               actor_username=admin["username"],
               detail=f"user_id={user_id} tag={tag.key}")
        db.commit()
    return {"ok": True}

@router.delete("/admin/users/{user_id}/tags/{tag_id}")
def revoke_tag(user_id: int, tag_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    row = db.query(UserTag).filter_by(user_id=user_id, tag_id=tag_id).first()
    if not row:
        raise HTTPException(404, "User does not have this tag")
    tag = db.get(TagDefinition, tag_id)
    _audit(db, "admin_tag_revoke", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"user_id={user_id} tag={tag.key}")
    db.delete(row); db.commit()
    return {"ok": True}
```

Also update `GET /users` to include each user's tags:
```python
# In the users list response, add a "tags" field per user:
"tags": [{"id": ut.tag_id, "key": ut.tag.key, "label": ut.tag.label}
         for ut in user.user_tags]
```

### Step 5 — Leaderboard includes tags

In `backend/routers/leaderboard.py`, update the season and weekly leaderboard queries to
join `UserTag` and `TagDefinition` and include a `tags` list per row:

```python
# For each leaderboard row, resolve user tags:
user_tags = db.query(UserTag).filter_by(user_id=row.user_id).all()
tags = [{"key": t.tag_definition.key, "label": t.tag_definition.label}
        for t in user_tags]
# Add to the row dict: "tags": tags
```

### Step 6 — Card image stickers

In `backend/image.py`, add a sticker compositing step after the template overlay:

```python
STICKER_DIR = os.path.join(ASSETS_DIR, "stickers")
STICKER_SIZE = (60, 60)
STICKER_START_X = 10   # left edge, stack horizontally
STICKER_Y = 10

def _apply_stickers(img: Image.Image, tag_keys: list[str]) -> Image.Image:
    for i, key in enumerate(tag_keys):
        path = os.path.join(STICKER_DIR, f"{key}.png")
        if not os.path.exists(path):
            continue
        sticker = Image.open(path).convert("RGBA").resize(STICKER_SIZE)
        x = STICKER_START_X + i * (STICKER_SIZE[0] + 4)
        img.alpha_composite(sticker, (x, STICKER_Y))
    return img
```

The card image endpoint must resolve the player's linked user (via `User.player_id ==
card.player_id`), look up their tags, and pass the tag keys to `_apply_stickers`.

### Step 7 — Placeholder sticker assets

Create `assets/stickers/` and add two placeholder PNGs at 60 × 60 px:
- `caster.png` — simple coloured square or text label (for CI/testing)
- `season_winner.png` — same

These placeholders are replaced by real artwork before the first live deploy.

### Step 8 — Frontend: search bar

In `frontend/app-admin.js`, wrap the `loadUsers()` render with a filter:

```js
document.getElementById("userSearch").addEventListener("input", filterUsers);

function filterUsers() {
  const q = document.getElementById("userSearch").value.toLowerCase();
  document.querySelectorAll("#usersBody tr").forEach(row => {
    row.style.display = row.textContent.toLowerCase().includes(q) ? "" : "none";
  });
}
```

In `frontend/index.html`, add `<input id="userSearch" placeholder="Search users…">` above
the Token Balances table.

### Step 9 — Frontend: tag management UI

In `frontend/app-admin.js`, add:
- `loadTags()` — fetches `GET /admin/tags` and renders the Tag Definitions panel
- `createTag(key, label)` — calls `POST /admin/tags`
- `deleteTag(tagId)` — calls `DELETE /admin/tags/{id}`
- Per user row in `loadUsers()`: render tag chips from `u.tags`; add a "Manage" dropdown
  that lists all tags with Grant/Revoke buttons

In `frontend/index.html`, add a "Tag Definitions" panel before the Token Balances section
in the admin tab.

---

## Verification
- Create a tag `caster` via admin panel; grant it to user A; fetch `GET /cards/{card_id}/image`
  for a card owned by the player linked to user A — sticker visible in top-left
- Revoke the tag; fetch the image again — sticker absent (no-cache headers ensure fresh PNG)
- Add `caster.png` placeholder to `assets/stickers/`; missing sticker file is silently skipped
- Create a second tag `season_winner`; grant both to user A; card shows two stickers side by side
- Check season leaderboard response — user A's row contains `"tags": [{"key": "caster", ...}]`
- Search "xyz" in Token Balances — only matching rows visible; clear → all rows restored
- Create a tag with a duplicate key → 409 returned
- Attempt `DELETE /admin/tags/{id}` for a tag with active grants — grants are cascade-deleted,
  tag removed, audit logged
- Run migration against a DB without the tables — tables are created; no crash
