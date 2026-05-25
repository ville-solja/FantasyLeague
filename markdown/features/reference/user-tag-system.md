# User Tag System

A generic tagging mechanism that lets admins grant named badges to users. Tags appear as
sticker overlays on player card images and as label chips in the leaderboard. Adding a new
tag type requires only a new database row and a sticker image asset — no code change.

---

## How it works

Two new tables power the system:

- **`TagDefinition`** — each row defines a tag type: a unique `key` (slug), a `label`
  (display name), and an optional sticker asset resolved at `assets/stickers/{key}.png`.
- **`UserTag`** — records which user holds which tag, who granted it, and when.

Tags are granted to **users** (app accounts). When rendering a card image, the system
resolves the player's linked user (`User.player_id == card.player_id`) and composites the
relevant sticker PNGs onto the card. Multiple tags produce multiple stickers stacked
horizontally in the top-left corner.

Initial seed tags: `caster` ("Caster") and `season_winner` ("Season Winner").

---

## Endpoints

### `GET /admin/tags`
Returns all defined tag types ordered by key.

### `POST /admin/tags`
Creates a new tag definition. Body: `{"key": "...", "label": "..."}`. Returns 409 if the
key already exists. Logged as `admin_tag_definition_created`.

### `DELETE /admin/tags/{tag_id}`
Deletes a tag definition and cascade-revokes all grants for it. Returns 404 if not found.
Logged as `admin_tag_definition_deleted`.

### `POST /admin/users/{user_id}/tags/{tag_id}`
Grants a tag to a user. Idempotent — granting twice has no effect. Returns 404 if the
user or tag does not exist. Logged as `admin_tag_grant`.

### `DELETE /admin/users/{user_id}/tags/{tag_id}`
Revokes a tag from a user. Returns 404 if the user does not hold the tag. Logged as
`admin_tag_revoke`.

---

## Card image stickers

Sticker images live at `assets/stickers/{tag_key}.png`, 60 × 60 px, RGBA. The image
pipeline in `backend/image.py` composites each sticker starting at `(10, 10)`, spaced
64 px apart horizontally. Missing sticker files are silently skipped.

Placeholder assets for `caster.png` and `season_winner.png` are included for CI/testing
and replaced by real artwork before deploy.

---

## Leaderboard integration

Season and weekly leaderboard rows include a `tags` array:

```json
{ "username": "PlayerX", "points": 340.5, "tags": [{"key": "caster", "label": "Caster"}] }
```

The frontend renders tag labels as small chips next to the username.

---

## Admin UI

The Token Balances table in the admin tab gains:
- A **search bar** — client-side, case-insensitive substring filter on username
- Per-row **tag chips** showing the user's current tags
- A **Manage** button per row to grant or revoke any defined tag

A separate **Tag Definitions** panel allows creating and deleting tag types.

---

## Adding a new tag

1. Call `POST /admin/tags` with the new key and label (or insert via admin UI).
2. Place a 60 × 60 px RGBA PNG at `assets/stickers/{key}.png`.
3. Grant the tag to relevant users via the admin panel.

No backend or frontend code changes are required.
