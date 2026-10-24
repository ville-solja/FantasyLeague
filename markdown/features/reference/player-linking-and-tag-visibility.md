# Player Linking and Tag Visibility

Users link their league player in the Profile tab's **Player identity** panel, and only through
Steam (`both` and `steam_signup` login modes; issues #150, #209). This connection causes any
admin-granted tags to appear as tag symbols on their cards (issue #217) and as chips on their
leaderboard entry. The same panel shows the user's current tags so they can understand and verify the link
(issue #188). With `LOGIN_METHOD=password` there is no player linking.

---

## How it works

**One rule (issue #209):** a player link exists only when a full, non-demo account has both
`users.steam_id` and `users.player_id`. Steam sign-up and Link Steam (`steam_openid.py`) set
`player_id` to the Steam32 id of the verified Steam account; unlinking Steam clears it again.

`backend/player_links.py` is the only reader of that rule:

| Function | Returns |
|---|---|
| `verified_player_id(user)` | the user's verified player id, or None |
| `verified_users_for_player(db, player_id)` | the accounts verifiably linked to a player, lowest user id first |
| `verified_links(db)` | `{user_id: player_id}` for every verified link |

Every feature goes through it:

- **Card tag symbols** (`tags` in `GET /accolades`, `accolades.tags_by_player`; #217): the tags
  of every user in `verified_links` for that player, plus an `admin` symbol for a site admin. An
  account that holds a stale `player_id` without Steam adds none. (Until #217 these were stickers
  baked into the card image from `verified_users_for_player`; see
  [Tag Symbols on Cards](tag-symbols-on-cards.md).)
- **`GET /profile/{user_id}`**: `player_id`, `player_name`, `player_avatar_url`,
  `player_team_name` and `player_verified` come from `verified_player_id`.
- **Own player card** (`own_card.is_candidate`, `has_grant_row`, `grant_own_player_card`; #188).
- **Fantasy Winner pip** (`accolades._linked_users`; #50).

A guard test (`backend/tests/test_issue_209_steam_verified_player_links.py`) fails when backend
code outside the allow-list reads `User.player_id`, an instance's `user.player_id`, or
`users.player_id` in SQL without `steam_id` in the same statement. The allow-list is
`player_links.py`, `steam_openid.py` (Steam linking), `migrate.py` and the claims history in
`routers/admin_users.py`.

The Player identity panel has a **Your Tags** column: tag chips if any tags are granted, or a
"No tags" placeholder. If a user has tags but no player linked yet, a hint is shown prompting
them to link their player so their tags appear as symbols on their cards.

---

## Endpoints

### `GET /profile/{user_id}`
Returns profile data including a `tags` array (as seen by the owner or an admin):

```json
{
  "id": 7,
  "username": "PlayerX",
  "is_admin": false,
  "player_id": 123456789,
  "player_name": "PlayerX",
  "player_avatar_url": "https://...",
  "player_verified": true,
  "player_team_name": "Team X",
  "twitch_linked": false,
  "tags": [{"key": "caster", "label": "Caster"}]
}
```

Because a player id is a Steam32 id, other viewers never get `player_id` (the key is absent);
they get `player_name` and `player_avatar_url`. The owner and admins also get `player_id`. An
account without a verified link gets `player_id: null` (owner and admins), `player_name: null`,
`player_avatar_url: null` and `player_verified: false`, even when an old `player_id` is still
stored. The route takes an integer id only (`/profile/{user_id:int}`), so `/profile/player-id`
matches nothing.

`player_team_name` (issue #188) is the matched player's latest team (from the stats of its match
with the latest start time), or null; it is present whenever `player_name` is.

### `POST /profile/steam/unlink`
Clears `steam_id` and, in the same transaction, `player_id` (issue #209). The `steam_unlinked`
audit detail is `user_id=<id> player_id_cleared=1` when a player id was set. Steam-only accounts
(no password) get 409 and keep both. See `steam-login.md`.

### `PUT /profile/player-id` (removed in #209)
The route no longer exists: requests answer 404 in every login mode.

---

## Migration 041: typed-in links cleared

`041_clear_unverified_player_links` (`backend/migrate.py`) runs once on upgrade:

- sets `player_id = NULL` on every user with `player_id` set and `steam_id` NULL;
- writes one `player_links_cleared` audit entry (`actor_username` "system", detail
  `migration=041 count=N`), and none when N is 0;
- is idempotent: a second run changes nothing and writes no entry;
- keeps the player id of every account with Steam.

The cleared values can't be restored from the app. **Run `bash scripts/backup-db.sh` before
deploying a release that includes migration 041.** Affected accounts see the "not linked" state
with **Link Steam** on Profile.

---

## History: verified vs self-reported ids (before #209)

Before #209 a player id could also be typed in through `PUT /profile/player-id`. Such ids were
**self-reported**: nothing proved the account belonged to that player, while ids set by Steam
sign-in or Link Steam were **verified** (`player_verified` true).

- #169 hid `player_id` from other viewers and showed the avatar only for verified ids; Profile
  labelled the name "Verified with Steam" or "Self-reported" (see `impersonation-hardening.md`).
- #188 retired the id field where Steam exists (`PUT /profile/player-id` answered 410 in `both`
  and `steam_signup`, kept working in `password` mode) and showed existing self-reported ids
  read-only with "Self-reported, link Steam to verify". The own player card and later the
  Fantasy Winner pip already trusted verified ids only.
- Card stickers still used any matching `player_id`, and unlinking Steam kept the player id, so a
  claimant's tags could appear on another player's cards. #209 removed manual entry, cleared the
  typed-in ids (migration 041) and moved every reader onto `player_links.py`.

The admin "Superseded player id claims" table (`GET /admin/player-id-claims`, #150) is history
and is unchanged.

## UI behaviour

| State | Tags section | Gap hint |
|---|---|---|
| Tags granted + player ID linked | Shows tag chips | Hidden |
| Tags granted + no player ID | Shows tag chips | Visible |
| No tags + player ID linked | "No tags" | Hidden |
| No tags + no player ID | "No tags" | Hidden |
