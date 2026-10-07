# Plan: Approved Streamers Admin

## Context
Only approved Twitch channels may set match MVPs, which also moves fantasy points and drops tokens. Today the list is the `TWITCH_MVP_CHANNEL_IDS` env var, so adding a streamer means editing the server environment and restarting, and an admin has to find the channel's numeric id first. This plan moves approval into the admin portal. When a broadcaster opens the MVP tool on a channel that isn't approved, the backend records a request, and the tool says the channel is waiting for the league's approval. Admins see the waiting channels (with their Twitch names when the Twitch sign-in credentials are configured) and approve or reject them with one click. Resolves GitHub issue #175.

Decisions taken with the product owner (2026-10-07):
- **Requests, not typing:** admins approve channels that tried the MVP tool; nobody types a numeric id.
- **Keep the env var:** channels listed in `TWITCH_MVP_CHANNEL_IDS` stay approved and can't be removed in the portal; the portal adds more.

Assumptions:
- The fail-closed rule from #165 still holds when both the env list and the portal list are empty: no channel may set MVPs with `ENV=production`, any channel may outside production. Once any channel is approved, every other channel needs approval.
- A request is recorded only from a Twitch-signed JWT with `role: broadcaster`, so only real channels with the extension installed can appear. The waiting list is capped (oldest pending dropped beyond 200) so it can't grow without bound.
- Approve, reject and remove need a recent password check (`require_recent_reauth`) and are audited: an approved channel can drop tokens.
- Twitch names come from Helix `GET /users?id=…` with an app access token (client credentials from `TWITCH_OAUTH_CLIENT_ID` / `TWITCH_OAUTH_CLIENT_SECRET`, issue #160). Without them, or when the call fails, the list shows the numeric id only; the lookup never blocks a request or an approval.
- New table only, so no `migrate.py` entry is needed (`create_all` creates it).

## User Stories

### Broadcaster Asks to Be Approved
**User story**
As a broadcaster who installed the extension, I want the MVP tool to tell me my channel is waiting for the league's approval so that I know why I can't set MVPs yet and that the league has been asked.

**Acceptance criteria**
- When a channel that isn't approved opens the MVP tool (`GET /twitch/matches/current` with `role: broadcaster`) or tries `POST /twitch/mvp`, the backend records a pending request for that channel id, with first and last seen times; repeated visits update the last seen time and create no duplicates
- `GET /twitch/matches/current` returns `mvp_allowed` (true or false) and `approval` (`approved`, `pending` or `rejected`)
- When `mvp_allowed` is false, the MVP tool shows "This channel is waiting for the league's approval to set match MVPs." instead of the series list (`rejected`: "This channel isn't approved to set match MVPs.")
- `POST /twitch/mvp` from a channel that isn't approved still returns 403 before any MVP, bonus or drop is written
- Viewer and moderator tokens never create a request
- A rejected channel's later visits update its last seen time but don't move it back to pending

### Approve Streamers in the Portal
**User story**
As an admin, I want to see channels waiting for approval and approve or reject them in the portal so that adding a streamer doesn't need a server change.

**Acceptance criteria**
- The admin panel has an **Approved streamers** section with three lists: Waiting for approval, Approved, and Rejected (collapsed)
- Each row shows the Twitch display name and login when known, the numeric channel id, and first and last seen dates
- **Approve** on a waiting or rejected channel makes it approved at once: its next MVP confirmation is accepted
- **Reject** on a waiting channel moves it to Rejected; **Remove** on an approved channel moves it to Rejected
- Approve, Reject and Remove ask for the admin's password if it wasn't confirmed in the last 10 minutes, and each writes an audit entry (`twitch_channel_approved`, `twitch_channel_rejected`, `twitch_channel_removed`) with the channel id
- Channels from `TWITCH_MVP_CHANNEL_IDS` are listed as Approved with a "from server settings" note and no Remove button
- Non-admins get 403 on every endpoint

### Env Var and Portal Together
**User story**
As the league operator, I want the existing `TWITCH_MVP_CHANNEL_IDS` setting to keep working alongside the portal so that nothing breaks when this ships.

**Acceptance criteria**
- A channel may set MVPs when it is in `TWITCH_MVP_CHANNEL_IDS` or approved in the portal
- With both lists empty, no channel may set MVPs when `ENV=production` and any channel may otherwise (unchanged from #165); the start-up warning names both places
- Removing a channel in the portal never affects a channel that is also in the env var

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New `TwitchChannelApproval` table |
| `backend/twitch.py` | Approval check from env ∪ approved rows; record requests; `mvp_allowed` / `approval` in `GET /twitch/matches/current` |
| `backend/twitch_channels.py` | New: request recording, list, approve / reject / remove, Helix name lookup |
| `backend/routers/admin_twitch.py` | `GET /admin/twitch/channels`, `POST …/{channel_id}/approve`, `…/reject`, `…/remove` |
| `twitch-extension/live_config.js`, `live_config.html` | Waiting / rejected message |
| `frontend/index.html`, `frontend/app-admin-users.js` (or a new `app-admin-twitch.js`) | Approved streamers section |
| `.env.example`, `markdown/features/core/twitch-extension.md`, `markdown/ui_description/admin.md` | Docs |
| `backend/tests/test_issue_175_approved_streamers_admin.py` | Tests |

### Step 1 — Model
```python
class TwitchChannelApproval(Base):
    __tablename__ = "twitch_channel_approvals"
    channel_id    = Column(String, primary_key=True)        # numeric Twitch channel id
    status        = Column(String, nullable=False)          # pending | approved | rejected
    display_name  = Column(String, nullable=True)           # from Helix, best effort
    login         = Column(String, nullable=True)
    first_seen_at = Column(Integer, nullable=False)
    last_seen_at  = Column(Integer, nullable=False)
    decided_at    = Column(Integer, nullable=True)
    decided_by    = Column(Integer, ForeignKey("users.id"), nullable=True)
```

### Step 2 — Approval check and requests (`twitch.py`, `twitch_channels.py`)
- `approved_channels(db) = env_channels() | {rows with status approved}`.
- `mvp_channel_allowed(db, channel_id)`: in that set; when the set is empty, the #165 rule (`not _is_production()`).
- `record_request(db, channel_id, now)`: insert pending or bump `last_seen_at`; called for `role: broadcaster` tokens in `current_matches` and in `set_mvp` before its 403. Validate the id is digits, at most 20 characters. Cap pending rows at 200 (delete the oldest by `last_seen_at`).
- `current_matches` adds `mvp_allowed` and `approval`; when not allowed it returns an empty `series` list.

### Step 3 — Admin endpoints (`routers/admin_twitch.py`)
- `GET /admin/twitch/channels` (admin): `{env: [...], approved: [...], pending: [...], rejected: [...]}`; fills missing names through Helix in one batched call (up to 100 ids), stores them, never fails the request on a Helix error.
- `POST /admin/twitch/channels/{channel_id}/approve | reject | remove` (admin + `require_recent_reauth`): status change, `decided_at` / `decided_by`, audit entry; 404 for an unknown id; 409 for removing an env channel.

### Step 4 — MVP tool (`live_config.*`)
Read `mvp_allowed` / `approval` from `GET /twitch/matches/current`; show the waiting or rejected message instead of the list.

### Step 5 — Admin UI
An **Approved streamers** panel near the Twitch merges section, built with `adminFetch` for the three actions. Escape every name with `_escHtml`.

### Step 6 — Docs
`.env.example` (env list still works, portal adds more), `core/twitch-extension.md` (approval flow), `ui_description/admin.md`, the MVP tool in `ui_description/twitch-panel.md` or the extension doc, and a feature doc.

## Verification
- `cd backend && python -m pytest tests/test_issue_175_approved_streamers_admin.py tests/test_issue_163_twitch_steam_account_hardening.py tests/test_issue_157_twitch_extension_policy_compliance.py`
- Tests: a broadcaster visit creates one pending row and repeats only bump it; viewer tokens create none; approve lets `POST /twitch/mvp` through; remove / reject block it again; env channels are approved and can't be removed (409); empty lists keep the #165 rule; actions without a recent reauth get 403 `reauth_required`; the pending cap holds; a Helix failure leaves names empty and the list still loads.
- Manual: with the extension in Local Test on an unapproved channel, the MVP tool shows the waiting message; the channel appears in the admin list with its Twitch name; Approve, then refresh the MVP tool and confirm an MVP.
