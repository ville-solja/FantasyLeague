# Plan: Player Linking and Tag Visibility

## Context
Users can already link their Dota 2 player ID in the Profile tab (`PUT /profile/player-id`),
and the tag system already composites sticker badges onto card images by resolving
`User.player_id == Card.player_id`. However, the Profile tab does not currently show the
user's own tags, so users have no way to see which badges they hold or understand why those
badges appear on their cards. This plan adds tag visibility to the profile page and enriches
the `GET /profile/{user_id}` response to include tags, closing the feedback loop between
linking a Dota ID and seeing stickers on cards. Resolves GitHub issue #64.

## User Stories

### See Your Tags on the Profile Page
**User story**
As a user, I want to see which tags have been granted to me on my Profile page so that I
know what badges will appear on my cards and leaderboard entry.

**Acceptance criteria**
- The Profile tab shows the user's current tags as labelled chips (e.g. "Caster", "Season Winner")
- If the user has no tags, a neutral "No tags" message is shown instead
- Tags are loaded from `GET /profile/{user_id}` alongside the existing profile data
- The tag display updates immediately when the profile is loaded; no extra button press required

### Understand the Link Between Dota ID and Tag Stickers
**User story**
As a user, I want to understand that linking my Dota ID is what connects my tags to my card
images so that I know what action to take to make my stickers appear.

**Acceptance criteria**
- The Dota ID linking section on the Profile tab includes a short note explaining that tags
  granted by an admin will appear as stickers on cards belonging to the linked player
- The note is only visible when the user has at least one tag but no Dota ID linked (the
  actionable gap state); it is hidden otherwise
- No changes to any other page or workflow

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/profile.py` | `GET /profile/{user_id}` — add `tags` array to response |
| `frontend/app-profile.js` | `loadProfile()` — render tag chips; show gap-state hint |
| `frontend/index.html` | Profile tab — add tag chip container and gap hint element |

### Step 1 — Extend `GET /profile/{user_id}` to include tags

Import `UserTag` and `TagDefinition` in `backend/routers/profile.py`. After the existing
player lookup, fetch the user's tags and append them to the response:

```python
from models import Player, User, UserTag, TagDefinition

# inside get_profile():
tag_rows = (
    db.query(UserTag, TagDefinition)
    .join(TagDefinition, TagDefinition.id == UserTag.tag_id)
    .filter(UserTag.user_id == user.id)
    .all()
)
result["tags"] = [{"key": td.key, "label": td.label} for _, td in tag_rows]
```

No migration needed — no new columns or tables.

### Step 2 — Render tags in `loadProfile()`

After the existing `data.player_id` block in `loadProfile()`, render tag chips into a
dedicated container `#profileTagsContainer` and show/hide the gap hint based on whether
the user has tags but no linked player:

```js
const tags = data.tags || [];
const container = document.getElementById("profileTagsContainer");
if (container) {
  container.innerHTML = tags.length
    ? tags.map(t => `<span class="tag-chip">${t.label}</span>`).join("")
    : `<span style="color:#555;font-size:0.85rem;">No tags</span>`;
}
const gapHint = document.getElementById("profileTagGapHint");
if (gapHint) {
  gapHint.style.display = (tags.length > 0 && !data.player_id) ? "block" : "none";
}
```

### Step 3 — Add HTML elements in the Profile tab

Add a Tags section below the existing Dota ID panel in `frontend/index.html`, inside the
Profile tab:

```html
<div class="panel">
  <h3 style="margin-bottom:8px;">Your Tags</h3>
  <div id="profileTagsContainer" style="display:flex;flex-wrap:wrap;gap:6px;"></div>
  <p id="profileTagGapHint" style="display:none;font-size:0.8rem;color:#888;margin-top:8px;">
    Link your Dota player ID above so your tag badges appear as stickers on your cards.
  </p>
</div>
```

The tag chip styling reuses the orange flame chip style already used in the admin table and
leaderboard (inline style or a shared class).

## Verification
- Log in as a user with tags granted and a linked player ID — tags should appear as chips on
  the Profile tab
- Log in as a user with tags but no player ID linked — chips appear and the gap hint is visible
- Log in as a user with no tags — "No tags" message shown, no gap hint
- Log in as a user with a linked player ID but no tags — chips area shows "No tags", no hint
- Confirm `GET /profile/{user_id}` JSON includes a `tags` array in all cases
- Existing player ID linking flow is unaffected
