# Caster Tag and Link Adoption

Approved streamers who have connected Twitch to their website account get the `caster` tag automatically, as a verified-caster badge. Admin › User Management shows who has linked Steam and Twitch, with totals. Resolves GitHub issue #201; plan: `markdown/plans/plan-issue-201-caster-tag-and-link-adoption.md`.

---

## Automatic Caster tag

A Twitch channel id is the broadcaster's Twitch user id. A website account (`account_type = "full"`) whose `users.twitch_account_id` equals an approved channel id (`twitch_channels.approved_channels`: `TWITCH_MVP_CHANNEL_IDS` plus portal-approved channels, #175) gets the `caster` tag with `user_tags.source = "caster_sync"` and `granted_by = NULL`. The tag then shows wherever tags show: leaderboard role badges, the mic symbol on cards (issue #217) and the Profile identity panel.

`caster_tags.sync(db, reason=None) -> (granted, revoked)` (`backend/caster_tags.py`) does the matching in two queries, grants missing rows, removes `caster_sync` rows that no longer match, and audits each change. The caller commits. `caster_tags.sync_safely` wraps it in a savepoint: a failure is logged by exception type only and rolled back, so the user's action still succeeds.

| When | Where | Revoke reason |
|---|---|---|
| Approve, reject, remove a channel | `routers/admin_twitch._decide`, before the commit | `channel_not_approved` |
| Connect Twitch ("connected" and "merge_ready") | `twitch_oauth.connect_account`, before each commit | — |
| Disconnect Twitch | `twitch_oauth.disconnect`, after its audit entry | `twitch_disconnected` |
| Admin reverses a Twitch merge (clears the website account's Twitch id) | `soft_accounts.reverse_merge` | `merge_reversed` |
| Startup, after `seed_tags()` (picks up `TWITCH_MVP_CHANNEL_IDS` changes) | `main._sync_caster_tags_at_startup` | `channel_not_approved` |
| Week maintenance loop (safety net) | `main._week_maintenance_loop` | `channel_not_approved` |

Notes:

- **Merge:** the Twitch id moves to the website account in `connect_account` ("merge_ready"), not in `soft_accounts.merge_soft_into`, so the merge itself needs no sync and keeps the tag.
- **Extension identity share:** no sync. It mostly stores the id on soft accounts, which are never tagged; a website account that gets its id this way (an older code-linked account) is tagged by the next maintenance-loop or startup sync.
- **Admin grants stay:** a Caster tag granted by an admin (`source = "admin"`) is never removed, and the sync doesn't add a second row for it. Rows from before this change read `admin` (migration default).
- **No hand revoke:** `DELETE /admin/users/{user_id}/tags/{tag_id}` returns 409 for a `caster_sync` row; the sync would grant it again. Remove the channel from Approved streamers instead.
- **Missing definition:** when an admin deletes the `caster` tag definition, the sync does nothing and logs a warning on each run (every maintenance tick and every other sync trigger in the table above). `seed_tags()` re-creates it at the next start, and the startup sync grants the tags again.
- **Audit:** `caster_tag_auto_grant` (`detail` = `user_id=… channel=…`) and `caster_tag_auto_revoke` (`detail` = `user_id=… reason=…`), actor `system`. The channel id is an internal id; no Steam id or viewer Twitch id is logged.
- **Demo Mode:** the sync doesn't depend on the clock, so `set_demo_clock` doesn't call it.

## Link adoption

`GET /users` returns `steam_linked` (`steam_id` set), `twitch_identity_shared` (`twitch_account_id` set: Connect Twitch, the identity the Caster match uses) and `is_demo`, all booleans. The ids themselves are never returned.

In Admin › User Management, website-account rows show **Steam** and **Twitch** badges after the username. A summary line above the table reads "{N} website accounts · Steam linked {S} ({S/N}%) · Twitch connected {T} ({T/N}%)", or "No website accounts yet" when N = 0. It counts website accounts without demo accounts, with whole-number percentages, computed in the browser from the full list (`_adoptionSummaryText` in `frontend/app-admin-users.js`), so the search box filters rows but not the totals. The Twitch viewers view shows no summary and keeps its "ID SHARED" badge.

## Endpoints

### `GET /users` (extended)
Adds `steam_linked` and `is_demo` per user, and `source` (`admin` or `caster_sync`) per tag. Admin only.

### `GET /admin/twitch/channels` (extended)
Adds `linked_username` to every row (env, approved, pending, rejected): the username of the website account whose `twitch_account_id` is that channel id, or null. Soft accounts don't count. One query (`twitch_channels.linked_usernames`). The Approved streamers lists show "Account: {username}" or "No linked account" under the channel name.

### `DELETE /admin/users/{user_id}/tags/{tag_id}` (changed)
Returns 409 "This tag is given automatically to approved streamers; remove the channel from Approved streamers instead" for a `caster_sync` row, before any audit entry. Admin rows are revoked as before.

### `POST /admin/users/{user_id}/tags/{tag_id}` (changed)
Stores the row with `source = "admin"`.

## Schema

| Table | Column | Type | Default |
|---|---|---|---|
| `user_tags` | `source` | TEXT NOT NULL | `admin` (`caster_sync` for automatic Caster tags) |

Migration `039_user_tags_source` adds the column to existing databases. Run `bash scripts/backup-db.sh` before deploying.

## Tests

`backend/tests/test_issue_201_caster_tag_and_link_adoption.py`.
