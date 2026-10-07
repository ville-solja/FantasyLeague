# Approved Streamers Admin

Admins choose which Twitch channels may set match MVPs (and so move fantasy points and drop tokens) in the admin portal, instead of only through the `TWITCH_MVP_CHANNEL_IDS` env var. Broadcasters ask by opening the MVP tool; admins approve or reject. Issue #175; plan `markdown/plans/plan-issue-175-approved-streamers-admin.md`.

---

## Approval flow *(planned)*

- A channel may set MVPs when it is in `TWITCH_MVP_CHANNEL_IDS` or approved in the portal. With both empty, the #165 rule applies: no channel with `ENV=production`, any channel otherwise.
- When a broadcaster (`role: broadcaster` JWT) of a channel that isn't approved opens the MVP tool or tries to set an MVP, a pending request is recorded (`twitch_channel_approvals`, at most 200 pending). The MVP tool shows "This channel is waiting for the league's approval to set match MVPs."
- Admins approve, reject or remove channels in the **Approved streamers** section. Each action needs a recent password check and is audited. Env-var channels are listed as approved and can't be removed in the portal.
- Twitch display names and logins are looked up through Helix `GET /users` with an app access token from `TWITCH_OAUTH_CLIENT_ID` / `TWITCH_OAUTH_CLIENT_SECRET`, best effort.

## Endpoints

### `GET /admin/twitch/channels` *(planned)*
Admin. `{env, approved, pending, rejected}` lists of channels with id, display name, login and first / last seen times.

### `POST /admin/twitch/channels/{channel_id}/approve` *(planned)*
Admin + recent re-auth. Approves a pending or rejected channel. Audited as `twitch_channel_approved`.

### `POST /admin/twitch/channels/{channel_id}/reject` *(planned)*
Admin + recent re-auth. Rejects a pending channel. Audited as `twitch_channel_rejected`.

### `POST /admin/twitch/channels/{channel_id}/remove` *(planned)*
Admin + recent re-auth. Moves an approved channel to rejected; 409 for an env-var channel. Audited as `twitch_channel_removed`.

`GET /twitch/matches/current` gains `mvp_allowed` and `approval` (`approved`, `pending`, `rejected`) *(planned)*.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_MVP_CHANNEL_IDS` | *(empty)* | Channels always approved, in addition to the portal list; they can't be removed in the portal |
| `TWITCH_OAUTH_CLIENT_ID`, `TWITCH_OAUTH_CLIENT_SECRET` | *(empty)* | Also used for the Twitch name lookup; without them the list shows numeric ids only |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
