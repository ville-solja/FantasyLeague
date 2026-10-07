# Approved Streamers Admin

Admins choose which Twitch channels may set match MVPs (and so move fantasy points and drop tokens) in the admin portal, instead of only through the `TWITCH_MVP_CHANNEL_IDS` env var. Broadcasters ask by opening the MVP tool; admins approve or reject. Issue #175; plan `markdown/plans/plan-issue-175-approved-streamers-admin.md`.

Code: `backend/twitch_channels.py` (requests, lists, decisions, Helix lookup), `backend/twitch.py` (`mvp_channel_allowed`, `channel_approval`, `current_matches`, `set_mvp`), `backend/routers/admin_twitch.py` (admin routes), `frontend/app-admin-users.js` (`loadTwitchChannels`, `twitchChannelAction`), `twitch-extension/live_config.js` (`approvalMessage`).

---

## Approval flow

- A channel may set MVPs when it is in `TWITCH_MVP_CHANNEL_IDS` or has a `twitch_channel_approvals` row with status `approved` (`twitch_channels.approved_channels(db)`). With both empty, the #165 rule applies: no channel with `ENV=production`, any channel otherwise. Once any channel is approved in either place, every other channel needs approval, also outside production.
- `twitch.mvp_channel_allowed(channel_id, db=None)`: the portal list counts only when `db` is passed. Called with one argument it keeps the env-only #165 behaviour (the #165 tests call it that way).
- When a broadcaster (`role: broadcaster` JWT) of a channel that may not set MVPs opens the MVP tool (`GET /twitch/matches/current`) or tries `POST /twitch/mvp`, `twitch_channels.record_request` inserts a `pending` row or bumps `last_seen_at` on the existing row (a rejected channel stays rejected). Only digit-only ids of at most 20 characters are recorded. At most 200 rows stay pending: a new request drops the oldest pending rows by `last_seen_at`. `set_mvp` commits the request before raising its 403; no MVP, bonus, drop or audit entry is written. Viewer and moderator tokens never create a request.
- The MVP tool shows "This channel is waiting for the league's approval to set match MVPs." (`approval: pending`) or "This channel isn't approved to set match MVPs." (`approval: rejected`) instead of the series list.
- Admins approve, reject or remove channels in the **Approved streamers** section of the admin Users tab. Each action needs a recent password check (`require_recent_reauth`) and is audited with `detail="channel={id} status={old}->{new}"`. Env-var channels are listed as approved "from server settings" and can't be removed in the portal.
- Twitch display names and logins are looked up through Helix `GET https://api.twitch.tv/helix/users?id=…` (one call, at most 100 ids, env channels first, then the most recently seen rows) with an app access token (client credentials at `https://id.twitch.tv/oauth2/token`), cached in memory until a minute before it expires. Credentials come from `twitch_oauth.oauth_config()`, so all three `TWITCH_OAUTH_*` values must be set. Names found are stored on the rows (env channels without a row get them in the response only). Any failure (no credentials, timeout of 5 s, non-200) leaves the names empty and the list still loads; the token and secret are never logged.

## Data

`twitch_channel_approvals` (new table, created by `create_all`; no migration): `channel_id` (PK, numeric string), `status` (`pending` | `approved` | `rejected`), `display_name`, `login`, `first_seen_at`, `last_seen_at`, `decided_at`, `decided_by` (users.id).

## Endpoints

### `GET /admin/twitch/channels`
`require_admin`. Returns `{env, approved, pending, rejected}`; each is a list of `{channel_id, display_name, login, status, first_seen_at, last_seen_at, decided_at, from_env}`. A channel in `TWITCH_MVP_CHANNEL_IDS` appears only under `env` (`from_env: true`, `status: approved`, dates from its row when it has one). Other lists are newest `last_seen_at` first.

### `POST /admin/twitch/channels/{channel_id}/approve`
`require_admin` + route-level `require_recent_reauth`. Approves a pending or rejected channel at once. Audited as `twitch_channel_approved`. 404 when there is no row; 409 for an env channel without a row.

### `POST /admin/twitch/channels/{channel_id}/reject`
`require_admin` + `require_recent_reauth`. Moves a pending channel to rejected. Audited as `twitch_channel_rejected`. 404 unknown, 409 for an env channel or a channel that isn't pending.

### `POST /admin/twitch/channels/{channel_id}/remove`
`require_admin` + `require_recent_reauth`. Moves an approved channel to rejected. Audited as `twitch_channel_removed`. 404 unknown, 409 for an env channel or a channel that isn't approved.

All three set `decided_at` / `decided_by` and return the updated row. Without a recent password check they answer 403 `{"detail": "reauth_required"}`; non-admins get 403.

### `GET /twitch/matches/current` (changed)
Adds `mvp_allowed` (bool) and `approval` (`approved`, `pending`, `rejected`) for the token's channel. A broadcaster on a channel that may not set MVPs gets `series: []` and leaves a request; viewers still get the series (the panel's Live tab shows MVP results).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_MVP_CHANNEL_IDS` | *(empty)* | Channels always approved, in addition to the portal list; they can't be removed in the portal. With `ENV=production` and an empty value, a start-up warning says only portal-approved channels can set MVPs |
| `TWITCH_OAUTH_CLIENT_ID`, `TWITCH_OAUTH_CLIENT_SECRET`, `TWITCH_OAUTH_REDIRECT_URI` | *(empty)* | Also used for the Twitch name lookup; without them the list shows numeric ids only |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
