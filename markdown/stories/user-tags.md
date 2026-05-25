# User Tags

## Card Stickers and Leaderboard Badges

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
- The frontend renders tag labels or small icon chips next to the username in the leaderboard table
- Users with no tags have an empty `tags` array — no visual element rendered

## Admin Management

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

## Profile Tag Visibility

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
