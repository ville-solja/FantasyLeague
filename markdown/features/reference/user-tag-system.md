# User Tag System

A generic tagging mechanism that lets admins grant named badges to users. Tags appear as
symbols on player cards ([Tag Symbols on Cards](tag-symbols-on-cards.md), issue #217) and as
role badges in the leaderboard. Adding a new tag type requires only a new database row — no
code change.

---

## How it works

Two new tables power the system:

- **`TagDefinition`** — each row defines a tag type: a unique `key` (slug), a `label`
  (display name).
- **`UserTag`** — records which user holds which tag, who granted it, when, and its
  `source`: `admin` (granted by hand) or `caster_sync` (the automatic Caster tag, issue #201).

Tags are granted to **users** (app accounts). On cards, a player shows the tags of the
user with a Steam-verified link to that player (`player_links.verified_links`, issue #209)
in the card viewer's Tags section (`tagDetailsHtml`, issue #228) and as tag pips in the
player popup header, fed by `tags` in `GET /accolades` (`accolades.tags_by_player`). Card
images and card faces carry no tags (issues #217, #228).

Initial seed tags: `caster` ("Caster") and `season_winner` ("Season Winner").

---

## Automatic Caster tag (issue #201)

A website account whose connected Twitch id (`users.twitch_account_id`) is an approved
streamer's channel id gets the `caster` tag automatically, with `source = "caster_sync"` and
`granted_by = NULL`. `caster_tags.sync(db)` grants and removes these rows and never touches
`source = "admin"` rows. It runs after approve, reject and remove in Approved streamers,
after Twitch connect and disconnect, after a merge reversal, at startup and in the week
maintenance loop. Soft accounts are never tagged. When the `caster` definition is missing,
the sync does nothing and logs a warning; `seed_tags()` re-creates the definition at the
next start. See [Caster Tag and Link Adoption](caster-tag-and-link-adoption.md).

---

## Endpoints

### `GET /admin/tags`
Returns all defined tag types ordered by key.

### `POST /admin/tags`
Creates a new tag definition. Body: `{"key": "...", "label": "..."}`. The key must match `^[a-z0-9][a-z0-9_-]*$` (lowercase letters, digits, `_` and `-`, not
starting with `_` or `-`, at most 50 characters); anything else returns 422 (issue #135).
Returns 409 if the key already exists. Returns 422 "This tag name is reserved" when the key or
label is `admin` (any case): the ADMIN badge comes only from `users.is_admin` (issue #169).
Logged as `admin_tag_definition_created`.

### `DELETE /admin/tags/{tag_id}`
Deletes a tag definition and cascade-revokes all grants for it. Returns 404 if not found.
Logged as `admin_tag_definition_deleted`.

### `POST /admin/users/{user_id}/tags/{tag_id}`
Grants a tag to a user (`source = "admin"`). Idempotent — granting twice has no effect.
Returns 404 if the user or tag does not exist. Logged as `admin_tag_grant`.

### `DELETE /admin/users/{user_id}/tags/{tag_id}`
Revokes a tag from a user. Returns 404 if the user does not hold the tag. Returns 409
"This tag is given automatically to approved streamers; remove the channel from Approved
streamers instead" for an automatic (`caster_sync`) row, which stays. Logged as
`admin_tag_revoke`.

---

## Tag symbols on cards

Until issue #217, card images composited a 60 × 60 PNG sticker per tag from
`assets/stickers/{key}.png`. That is retired: `backend/image.py` has no sticker code and the
card image route reads no tags. Cards show tags as HTML symbols instead: admin (shield),
caster (mic) and any other tag (a generic tag icon, its label as the tooltip); the
`season_winner` tag shows no symbol because the Fantasy Winner accolade covers it. See
[Tag Symbols on Cards](tag-symbols-on-cards.md). The sticker PNGs stay in the repo, unused.

---

## Leaderboard integration

Season and weekly leaderboard rows include a `tags` array:

```json
{ "username": "PlayerX", "points": 340.5, "tags": [{"key": "caster", "label": "Caster"}] }
```

The frontend renders each tag as a role badge next to the username (`tagBadgeHtml` in `frontend/app-globals.js`): Caster and Season Winner in their own colours, any other tag neutral, each with its reason on hover. See the design system's "States and emphasis" rules and `ui-feedback-polish.md` (issue #202).

---

## Admin UI

The Token Balances table in the admin tab gains:
- A **search bar** — client-side, case-insensitive substring filter on username
- Per-row **role badges** showing the user's current tags
- A **Manage** button per row to grant or revoke any defined tag. An automatic Caster tag
  shows as "Caster (auto)" with no revoke button (issue #201)

A separate **Tag Definitions** panel allows creating and deleting tag types.

---

## Adding a new tag

1. Call `POST /admin/tags` with the new key and label (or insert via admin UI).
2. Grant the tag to relevant users via the admin panel.

No backend or frontend code changes are required: a new tag shows on cards with the generic
tag symbol and its label as the tooltip. A dedicated icon and colour need an entry in
`TAG_SYMBOLS` (`frontend/app-globals.js`).
