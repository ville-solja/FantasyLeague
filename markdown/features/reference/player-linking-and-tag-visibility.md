# Player Linking and Tag Visibility

Users link their Dota 2 player ID in the Profile tab; this connection causes any admin-granted
tags to appear as sticker badges on their cards and as chips on their leaderboard entry. The
Profile tab surfaces the user's current tags so they can understand and verify the link.

---

## How it works

The `User.player_id` column stores the OpenDota account ID the user has self-reported via
`PUT /profile/player-id`. When a card image is generated for a player, the system looks up
any `User` whose `player_id` matches `Card.player_id` and composites that user's tag stickers
onto the card PNG.

The Profile tab shows a **Your Tags** section: tag chips if any tags are granted, or a "No
tags" placeholder. If a user has tags but no Dota ID linked yet, a hint is shown prompting
them to link their ID so stickers appear on their cards.

---

## Endpoints

### `GET /profile/{user_id}`
Returns profile data including a `tags` array:

```json
{
  "id": 7,
  "username": "PlayerX",
  "player_id": 123456789,
  "player_name": "PlayerX",
  "player_avatar_url": "https://...",
  "twitch_linked": false,
  "tags": [{"key": "caster", "label": "Caster"}]
}
```

### `PUT /profile/player-id`
Links (or unlinks) the user's Dota 2 player ID. Body: `{"player_id": 123456789}` or
`{"player_id": null}` to unlink.

---

## UI behaviour

| State | Tags section | Gap hint |
|---|---|---|
| Tags granted + player ID linked | Shows tag chips | Hidden |
| Tags granted + no player ID | Shows tag chips | Visible |
| No tags + player ID linked | "No tags" | Hidden |
| No tags + no player ID | "No tags" | Hidden |
