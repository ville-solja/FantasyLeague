# Player Linking and Tag Visibility

Users link their league player in the Profile tab's **Player identity** panel: through Steam
(`both` and `steam_signup` login modes, issue #150), or by typing their OpenDota account id in
`password` mode. This connection causes any admin-granted tags to appear as sticker badges on
their cards and as chips on their leaderboard entry. The same panel shows the user's current
tags so they can understand and verify the link (issue #188).

---

## How it works

The `User.player_id` column stores the player's OpenDota account id (a Steam32 id): set and
verified by Link Steam or Steam sign-up, or self-reported via `PUT /profile/player-id` in
`password` mode. When a card image is generated for a player, the system looks up
any `User` whose `player_id` matches `Card.player_id` and composites that user's tag stickers
onto the card PNG.

The Player identity panel has a **Your Tags** column: tag chips if any tags are granted, or a
"No tags" placeholder. If a user has tags but no player linked yet, a hint is shown prompting
them to link their player so stickers appear on their cards.

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
  "player_verified": false,
  "player_team_name": "Team X",
  "twitch_linked": false,
  "tags": [{"key": "caster", "label": "Caster"}]
}
```

### Verified vs self-reported player ids (issue #169)

A player id typed in through `PUT /profile/player-id` is **self-reported**: nothing proves the
account belongs to that player. An id set by Steam sign-in or Link Steam (#150, `users.steam_id`)
is **verified**, and `player_verified` is true. Because a player id is a Steam32 id:

- other viewers never get `player_id` (the key is absent);
- they get `player_name`, and `player_avatar_url` only when the id is verified;
- the owner and admins still get the id and the avatar.

Profile labels the linked name "Verified with Steam" or "Self-reported" and shows the avatar only
for a verified id. See `impersonation-hardening.md`.

`player_team_name` (issue #188) is the matched player's latest team (from the stats of its match
with the latest start time), or null; it is present whenever `player_name` is.

### `PUT /profile/player-id`
Links (or unlinks) the user's Dota 2 player ID, self-reported. Body: `{"player_id": 123456789}` or
`{"player_id": null}` to unlink. Limited per user by `RATE_LIMIT_USER_ACTION`.

- `LOGIN_METHOD` `both` or `steam_signup`: **410** "Link Steam to verify your player id" and
  nothing changes (issue #188). Steam is the only way to link a player.
- `LOGIN_METHOD=password`: works as before; 409 for an account that still has a Steam link.

---

### Manual id retired where Steam exists (issue #188)

With `LOGIN_METHOD` `both` or `steam_signup` the Profile id field is gone and the route answers
410. Existing self-reported ids stay: the panel shows the player read-only, labelled
"Self-reported", with "Self-reported, link Steam to verify" and **Link Steam**; their tags and
admin-granted stickers keep working. Linking Steam replaces the id with the verified one. With
`LOGIN_METHOD=password` the field stays, labelled "Self-reported". The former Steam, Dota 2 Player
and Your Tags panels are one **Player identity** panel (see `markdown/ui_description/profile.md`).

## UI behaviour

| State | Tags section | Gap hint |
|---|---|---|
| Tags granted + player ID linked | Shows tag chips | Hidden |
| Tags granted + no player ID | Shows tag chips | Visible |
| No tags + player ID linked | "No tags" | Hidden |
| No tags + no player ID | "No tags" | Hidden |
