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

### Understand the Link Between Your Player and Tag Stickers
**User story**
As a user, I want to understand that linking my player is what connects my tags to my card
images so that I know what action to take to make my stickers appear.

**Acceptance criteria**
- The tags column of the Profile tab's **Player identity** panel includes a short note: "Link
  your player so your tags appear as stickers on your cards and on the leaderboard." (issue #188)
- The note is only visible when the user has at least one tag but no player linked (the
  actionable gap state); it is hidden otherwise
- No changes to any other page or workflow

## Automatic Caster Tag and Link Adoption (issue #201)

Plan: `markdown/plans/plan-issue-201-caster-tag-and-link-adoption.md`.

### Approved Streamers Get the Caster Tag Automatically
**User story**
As an approved streamer with a website account, I want the Caster tag to appear on my account without asking an admin, so that players can see I'm a verified caster for the tournament.

**Acceptance criteria**
- **When it's granted:** a website account whose `twitch_account_id` equals an approved channel id (`twitch_channels.approved_channels(db)`) gets the `caster` tag with `source = "caster_sync"` and `granted_by = NULL`.
- **When it runs:** within the same request after the channel is approved, and after the user connects Twitch (both the "connected" and the "merge_ready" outcome of `connect_account`, which is where a soft account's Twitch id moves to the website account; the later merge keeps the tag).
- **Display:** the tag shows wherever tags already show: leaderboard chips, card stickers and the Profile identity panel (#188).
- **Already tagged:** a user who already has the Caster tag (from an admin or an earlier sync) gets no second row, and no audit entry is written.
- **Audit:** each new automatic grant writes `caster_tag_auto_grant` (actor `system`, `detail` = `user_id=… channel=…`). The channel id is an internal id, not personal data.
- **Soft accounts:** a soft account (`account_type = "twitch"`) is never tagged, even when its Twitch id matches.
- **Missing tag:** when the `caster` tag definition doesn't exist (deleted by an admin), the sync does nothing and logs a warning on each run until `seed_tags()` re-creates it at the next start.

### The Automatic Tag Follows the Approval
**User story**
As an admin, I want the automatic Caster tag to disappear when a streamer is no longer approved or unlinks Twitch, so that the badge stays trustworthy without me tracking it.

**Acceptance criteria**
- **When it's removed:** within the same request, when the channel is removed or rejected, the user disconnects Twitch (`POST /twitch/disconnect`), or an admin reverses the user's Twitch merge (which clears the Twitch id). Only `source = "caster_sync"` rows are removed.
- **Audit:** each removal writes `caster_tag_auto_revoke` (actor `system`, `detail` = `user_id=… reason=channel_not_approved|twitch_disconnected|merge_reversed`).
- **Admin grants stay:** a Caster tag granted by an admin (`source = "admin"`) is never removed by the sync.
- **Server-settings channels:** a channel from `TWITCH_MVP_CHANNEL_IDS` counts as approved. A restart without that channel removes the automatic tags it gave (sync at startup).
- **No hand revoke:** `DELETE /admin/users/{user_id}/tags/{tag_id}` on a `caster_sync` row returns 409 "This tag is given automatically to approved streamers; remove the channel from Approved streamers instead".
- **Existing rows:** rows that existed before this change read as `source = "admin"` (migration default), so no existing tag is touched.

### Admins See Which Channel Belongs to Which Account
**User story**
As an admin reviewing approved streamers, I want to see whether a channel is linked to a website account, so that I know who gets the Caster tag.

**Acceptance criteria**
- **API:** each channel row in `GET /admin/twitch/channels` adds `linked_username` (the matching website account's username, or null).
- **Approved streamers lists:** the Channel cell shows "Account: {username}" under the channel name, or "No linked account". Text is escaped (`_escHtml`).
- **User Management tags:** an automatic Caster tag shows as "Caster (auto)", with no revoke button, and a title explaining it follows Approved streamers.

### Admins See Steam and Twitch Link Adoption
**User story**
As an admin, I want to see which users have linked Steam and Twitch, and how many in total, so that I can follow how those features are adopted.

**Acceptance criteria**
- **API:** `GET /users` adds `steam_linked` (bool, `steam_id` set) and `is_demo` (bool, for the totals) per user, and `source` per tag. The Steam and Twitch ids are never returned.
- **Website accounts table:** each row shows **Steam** and **Twitch** badges when `steam_linked` or `twitch_identity_shared` is true. Absent badges mean not linked.
- **Totals:** a summary line above the table: "{N} website accounts · Steam linked {S} ({S/N}%) · Twitch connected {T} ({T/N}%)".
  - It counts website accounts, excluding demo accounts.
  - Percentages are rounded to whole numbers; with N = 0 it reads "No website accounts yet".
- **Search:** the search box filters the rows, not the totals, which always describe all website accounts.
- **Twitch viewers view:** unchanged; it keeps its "ID SHARED" badge.
