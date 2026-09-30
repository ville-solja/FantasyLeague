# Plan: Twitch Chat Announcement Fix

## Context
On 2026-09-29 an admin saw a `twitch_token_drop` audit entry during a stream, but no MVP announcement appeared in the channel's chat.

`_post_chat_message` in `backend/twitch.py` calls Twitch's Send Extension Chat Message endpoint, `POST https://api.twitch.tv/helix/extensions/chat`. Twitch's API reference (checked 2026-09-30) lists three **required** body fields: `text`, `extension_id` and `extension_version`. The code sends only `{"text": message}`, so Twitch rejects every announcement with 400 Bad Request.

The failure is silent: the code never checks the response status, and it only logs exceptions such as timeouts. The same applies to `_pubsub_broadcast`.

Two smaller problems:
- Twitch limits a chat message to **280 characters**. The announcement lists every token-drop winner, up to `TWITCH_DROP_MAX` (20) usernames, so a large drop would also be rejected.
- Twitch allows **12 messages per minute per channel**.

The MVP, bonus and token drop are unaffected, since they're saved before the chat call. The issue notes that chat isn't needed for the extension's review scope, so this is a low-priority fix. Chat must stay best-effort: a chat failure never fails `POST /twitch/mvp`.

**Assumptions:**
- `extension_id` is the extension's client ID, already configured as `TWITCH_EXTENSION_CLIENT_ID`.
- `extension_version` must be the version installed on the channel, for example `1.1.6` today and `1.1.7` after the next release. The server can't infer it, so it becomes a new setting, `TWITCH_EXTENSION_VERSION`. Without it, chat is skipped with one warning log line instead of calling Twitch.
- The **Chat** capability must be enabled on that version in the Twitch developer console. The operator checks this; the code can only report the error Twitch returns.

Resolves GitHub issue #140.

## User Stories

### MVP Announcement Reaches Chat
**User story**
As a streamer, I want the MVP and token-drop winners announced in my channel's chat so that viewers without the panel open see them too.

**Acceptance criteria**
- `_post_chat_message` sends `{"text", "extension_id", "extension_version"}`, with `extension_id` from `TWITCH_EXTENSION_CLIENT_ID` and `extension_version` from `TWITCH_EXTENSION_VERSION`
- The request keeps `broadcaster_id` as a query parameter and a JWT with `role: "external"`, `user_id` and `channel_id` equal to the broadcaster's channel
- When `TWITCH_EXTENSION_VERSION` is unset, no request is sent and a warning is logged once per process naming the missing setting
- Local dev (`TWITCH_LOCAL_DEV=true`) still logs the message instead of calling Twitch

### Announcements Fit Twitch's Limit
**User story**
As a streamer, I want a large token drop still announced so that a long winner list doesn't stop the message.

**Acceptance criteria**
- The announcement text is at most 280 characters
- When the winners don't all fit, the message lists as many as fit, followed by "and N more"
- The MVP name is always included in full

### Failures Are Visible to Operators
**User story**
As an operator, I want failed Twitch calls logged with Twitch's reason so that the next problem can be diagnosed from the server log.

**Acceptance criteria**
- A chat or PubSub response other than 2xx logs a warning with the HTTP status and Twitch's error message (response body, truncated to 300 characters), and never the JWT
- A timeout or connection error is still logged, as today
- `POST /twitch/mvp` returns 200 and keeps the MVP, bonus and token drop when the chat or PubSub call fails

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/twitch.py` | Add the required body fields; skip and warn without `TWITCH_EXTENSION_VERSION`; cap text at 280; check and log response status for chat and PubSub |
| `.env.example` | `TWITCH_EXTENSION_VERSION` with a note that it must match the version installed on the channel and have Chat enabled |
| `markdown/features/core/twitch-extension.md` | Twitch Extension Chat section: required fields, the new setting, the length and rate limits, troubleshooting |
| `backend/tests/test_issue_140_twitch_chat_announcement_fix.py` | Tests with `_requests.post` patched |

### Step 1 — Request body
```python
json={
    "text": text,
    "extension_id": client_id,
    "extension_version": version,
}
```
Read `version = os.getenv("TWITCH_EXTENSION_VERSION", "").strip()`. If it is empty, log `"Twitch chat skipped: TWITCH_EXTENSION_VERSION is not set"` once (a module flag) and return.

### Step 2 — Fit 280 characters
Build the message in `set_mvp` via a helper `_mvp_chat_text(player_name, winner_names, token_name, pool_empty)`. It appends winners until adding the next one plus `", and N more"` would pass 280 characters. Keep the existing "(No linked viewers in the drop pool.)" suffix.

### Step 3 — Check responses
Keep the `requests.post` result. If `not resp.ok`, log `logger.warning("Twitch chat failed: %s %s", resp.status_code, resp.text[:300])`. Do the same in `_pubsub_broadcast`. Keep the existing `except Exception` logging.

### Step 4 — Docs and config
Update `.env.example` and the Twitch Extension Chat section of `core/twitch-extension.md`. Add a troubleshooting table there:

| Twitch status | Likely cause |
|---|---|
| 400 | Missing field or message too long |
| 401 | JWT or client ID wrong, or `broadcaster_id` ≠ `channel_id` |
| 403 | Chat capability not enabled on that version, or the extension isn't activated on the channel |

Add the new setting to the release checklist for the hoster, with a value matching the extension version installed on the channel.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_140_twitch_chat_announcement_fix.py -v`, then the full suite.
- With `_requests.post` patched, confirming an MVP sends a body with all three fields and a `broadcaster_id` equal to the channel.
- Without `TWITCH_EXTENSION_VERSION`, no chat request is made and one warning is logged across two confirmations.
- A 20-winner drop with long usernames yields a message of 280 characters or fewer ending in "and N more".
- A patched 403 response logs the status and body and does not include the JWT; `POST /twitch/mvp` still returns 200 with the drop recorded.
- Manual, on test.kana-cards.com with the Hosted Test extension:
  1. Set `TWITCH_EXTENSION_VERSION` to the installed version and confirm Chat is enabled for it.
  2. Confirm an MVP: the announcement appears in chat.
  3. If it doesn't, the server log shows Twitch's status and reason.
