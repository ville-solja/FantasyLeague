# Plan: Caster Tag for Approved Streamers, and Link Adoption in User Management

## Context
Approved streamers (#175) are Twitch channels allowed to set match MVPs. They are listed by channel id: `TWITCH_MVP_CHANNEL_IDS` plus `twitch_channel_approvals` rows with status `approved`. A Twitch channel id is the broadcaster's Twitch user id. A website account that has connected Twitch (#160, or a merged soft account) stores that same id in `users.twitch_account_id`. So an approved streamer who has connected Twitch can be matched to their account, and given the existing `caster` tag ("Caster", seeded in `seed.py`) without an admin granting it by hand. The tag then works as a "verified caster" badge on the leaderboard and on card stickers.

The issue also asks Admin › User Management to show who has linked Steam and Twitch, so admins can see how many people use those features. `GET /users` already returns `twitch_linked` (the extension's opaque id) and `twitch_identity_shared` (the real Twitch id). It doesn't say whether Steam is linked, and the page shows no totals.

**Decisions** (assumptions; change them in review if needed):
- **Matching:** `users.twitch_account_id` = an approved channel id, website accounts only (`account_type = "full"`). Soft accounts are hidden from tags already (#157).
- **Automatic grants are tracked:** a new `user_tags.source` column (`admin` or `caster_sync`) keeps them apart from admin grants.
  - The sync only ever removes tags it granted itself, so an admin-granted Caster tag is never removed.
  - An automatic tag is removed when the match ends: the channel is removed or rejected, or the user disconnects Twitch.
- **An automatic tag can't be revoked by hand:** the sync would grant it again. The Users table marks it "auto" and replaces its revoke button with a hint: remove the channel from Approved streamers.
- **One idempotent sync:** `caster_tags.sync(db)` runs:
  - right after each approve, reject or remove (reject only applies to pending channels, so it matters only for a stale row);
  - after Twitch connect (both commit paths of `connect_account`), disconnect, and an admin merge reversal (`soft_accounts.reverse_merge`, reason `merge_reversed`);
  - once at startup, because `TWITCH_MVP_CHANNEL_IDS` only changes on restart;
  - in the week maintenance loop, as a safety net.
- **"Twitch" in the adoption figures** means `twitch_account_id` is set: Connect Twitch, which is the identity that matching uses. "Steam" means `steam_id` is set. The API returns only booleans, never the ids.
- **Who the totals count:** website accounts, excluding demo accounts. The frontend computes them from the list it already loads (`GET /users` returns `is_demo`), so no new endpoint is needed.

Resolves GitHub issue #201.

## User Stories

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

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `UserTag.source = Column(String, nullable=False, default="admin", server_default="admin")` |
| `backend/migrate.py` | Migration `039_user_tags_source`: `ALTER TABLE user_tags ADD COLUMN source TEXT NOT NULL DEFAULT 'admin'`, guarded by `PRAGMA table_info` |
| `backend/caster_tags.py` (new) | `sync(db, reason=None) -> (granted, revoked)`: match, grant, revoke, audit. The caller commits |
| `backend/routers/admin_twitch.py` | Call `caster_tags.sync_safely` in `_decide` before the commit |
| `backend/twitch_channels.py` | `linked_username` in `list_channels` via `_row_dict` (`linked_usernames`, one query) |
| `backend/twitch_oauth.py` | Sync in `connect_account` before both commits ("connected", "merge_ready") and in `disconnect` (reason `twitch_disconnected`) |
| `backend/soft_accounts.py` | Sync in `reverse_merge` (reason `merge_reversed`); `merge_soft_into` needs none (it never sets `twitch_account_id`) |
| `backend/main.py` | Sync once at startup and in `_week_maintenance_loop` |
| `backend/routers/admin_tags.py` | `grant_tag` sets `source="admin"`; `revoke_tag` refuses `caster_sync` rows with 409 |
| `backend/routers/admin_users.py` | `GET /users` adds `steam_linked` and `is_demo`, and each tag gets `source` |
| `frontend/app-admin-users.js`, `frontend/index.html` | Badges, summary line, "Caster (auto)" display, linked account in Approved streamers |
| `markdown/features/reference/user-tag-system.md`, `markdown/ui_description/admin.md`, `markdown/features/reference/caster-tag-and-link-adoption.md`, `markdown/features/core/admin.md` (audit actions) | Docs |
| `backend/tests/test_issue_201_caster_tag_and_link_adoption.py` | Tests |

No new env var.

### Step 1 — Schema
Add the `source` column and its migration, so `test_migrate.py` passes.

### Step 2 — Sync (`caster_tags.py`)
```python
def sync(db, reason: str | None = None) -> tuple[int, int]:
    """Give the caster tag (source="caster_sync") to website accounts whose
    twitch_account_id is an approved channel; remove caster_sync rows that no
    longer match. Never touches source="admin" rows. Caller commits."""
```
- **Queries:** one query for matching users (`twitch_account_id IN approved`, `account_type == "full"`), and one for the existing caster rows.
- **Audit:** an entry per grant and per revoke. The revoke reason is `reason`, or `channel_not_approved` when none is given.

### Step 3 — Call sites
- `admin_twitch._decide`: after `decide`, before the commit.
- `twitch_oauth.connect_account`: after `user.twitch_account_id = sub`, before both commits; `disconnect`: after `_audit`, before the commit. No sync for the extension identity share.
- `soft_accounts.reverse_merge`: before its final flush (reason `merge_reversed`).
- `main.py`: `_sync_caster_tags_at_startup` after `seed_tags()` in `lifespan` (own SessionLocal, try/except + log), and inside the `try` of `_week_maintenance_loop`.
- Request-path calls use `caster_tags.sync_safely` (a savepoint; failures logged by exception type), so a sync failure never blocks a login, connect or admin action.

### Step 4 — Admin APIs
- `GET /users`: add `steam_linked` and `is_demo` per user, and `source` per tag.
- `GET /admin/twitch/channels`: add `linked_username` (one query mapping `twitch_account_id` to username for full accounts).
- Tag revoke: return 409 for a `caster_sync` row, checked before the audit write.

### Step 5 — Frontend (`app-admin-users.js`)
The badges, the summary line, the auto tag display and the linked account, following the existing User Management and Approved streamers markup and escaping.

### Step 6 — Docs and tests
**Docs:** the user tag system doc (automatic Caster tag), the admin UI spec, the new reference doc, and the audit action rows in `features/core/admin.md`.

**Tests:**
- **Grant:** a user is granted the tag on approve and on connect.
- **Skipped:** soft accounts; an existing admin grant (no duplicate, no audit).
- **Revoke:** on remove, reject and disconnect.
- **Admin grants survive** every revoke path.
- **Startup:** an env channel removed at restart revokes its tag.
- **No definition:** a missing `caster` definition is a no-op.
- **Hand revoke:** returns 409 for `caster_sync`, and still works for `admin` rows.
- **`GET /users`:** returns `steam_linked`, and never `steam_id` or the Twitch ids.
- **Channel list:** `linked_username`.
- **Migration:** coverage passes.

## Verification
- **Approve:** on test, connect Twitch on a website account whose Twitch user is a waiting channel, then approve the channel in Admin › Approved streamers. The account shows the Caster chip on the leaderboard, and Approved streamers shows "Account: {username}".
- **Disconnect:** disconnect Twitch on Profile; the chip disappears. Reconnect; it returns.
- **Remove:** remove the channel from Approved streamers; the chip disappears. An admin-granted Caster tag on another account stays.
- **Hand revoke:** User Management shows "Caster (auto)" with no revoke button. A direct `DELETE` returns 409.
- **Adoption:** User Management shows the summary line and the Steam and Twitch badges. Searching filters the rows but not the totals.
- **Deploy:** includes a migration, so run `bash scripts/backup-db.sh` first.
