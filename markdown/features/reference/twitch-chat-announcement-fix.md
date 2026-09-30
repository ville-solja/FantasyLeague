# Twitch Chat Announcement Fix

Makes the MVP announcement actually reach the channel's Twitch chat, and makes failed Twitch calls visible in the server log. Resolves GitHub issue #140. The full chat behaviour and troubleshooting table live in the Twitch Extension Chat section of `../core/twitch-extension.md`.

---

## Cause

Twitch's Send Extension Chat Message endpoint (`POST https://api.twitch.tv/helix/extensions/chat`) requires `text`, `extension_id` and `extension_version` in the body. The EBS sent only `text`, so every announcement was rejected with 400. The response was never checked, so nothing was logged. The MVP, bonus and token drop were unaffected.

## Behaviour after the fix

All in `backend/twitch.py`, triggered by `POST /twitch/mvp` (`set_mvp`):

- `_post_chat_message(channel_id, message)` sends `{"text", "extension_id", "extension_version"}`, with `extension_id` from `TWITCH_EXTENSION_CLIENT_ID` and `extension_version` from `TWITCH_EXTENSION_VERSION`. `broadcaster_id` stays a query parameter; the JWT has `role: "external"` and `user_id` = `channel_id` = the broadcaster's channel.
- Without `TWITCH_EXTENSION_VERSION` (empty or whitespace), chat is skipped and `Twitch chat skipped: TWITCH_EXTENSION_VERSION is not set` is logged once per process (module flag `_chat_version_warned`).
- `_mvp_chat_text(player_name, winner_names, token_name, pool_empty)` builds the message within Twitch's 280 characters. The MVP name is always kept in full; winners are listed until the next one plus `", and N more"` would pass the limit. If not even one winner fits, the winners become `"{N} viewers won +1 {token}."`. Only an MVP name of about 260+ characters could push the message past 280.
- A chat or PubSub response other than 2xx logs a warning with the HTTP status and Twitch's response body truncated to 300 characters (`Twitch chat failed: …` / `Twitch PubSub broadcast failed: …`). The JWT is never logged. Timeouts and connection errors are still logged with `logger.exception`.
- Chat stays best-effort: `POST /twitch/mvp` never fails because of it. `TWITCH_LOCAL_DEV=true` still logs the message instead of calling Twitch.

Twitch also limits chat to 12 messages per minute per channel, and the **Chat** capability must be enabled on the installed extension version.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_EXTENSION_VERSION` | *(empty)* | Extension version installed on the channel, e.g. `1.1.7`. Required for chat announcements; chat is skipped with one warning when empty. Update it whenever a new version is installed. |

## Tests

`backend/tests/test_issue_140_twitch_chat_announcement_fix.py` (12 tests, `twitch._requests.post` patched).
