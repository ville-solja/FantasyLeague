# Plan: Twitch Extension — Card Draw Giveaway

## Context
When a Kanaliiga match is being streamed on Twitch, an extension panel on the stream could let the broadcaster trigger a giveaway that grants a free card draw to a random viewer. This increases engagement and rewards viewers who watch live matches.

---

## Architecture Overview

```
Twitch Extension (frontend JS) ←→ FastAPI EBS (Extension Backend Service)
                                         ↕
                               Fantasy League Database
```

The Twitch Extension is a Panel or Overlay extension served by Twitch CDN. It communicates with the Fantasy League backend acting as an EBS via Twitch-signed JWT calls.

---

## Components

### 1. Account Linking (Fantasy ↔ Twitch)

Users must link their Fantasy account to their Twitch identity before they can receive draws.

**Flow:**
1. User visits the Fantasy site → "Link Twitch" button in My Team tab
2. Backend generates a 6-character alphanumeric code tied to their `user_id` (stored temporarily, TTL ~10 min)
3. User opens the Twitch extension panel on any Kanaliiga stream and enters their code
4. Extension calls `POST /twitch/link` with `{code, twitch_user_id}` (Twitch user ID from extension JWT)
5. Backend validates code, stores `twitch_user_id` on the `User` row, marks code as consumed

**New `User` fields:**
```python
twitch_user_id = Column(String, nullable=True, unique=True)
```

**New endpoints:**
- `POST /twitch/link-code` (authenticated) — generate and return a 6-char linking code
- `POST /twitch/link` — consume code, store twitch_user_id (validated via Twitch JWT)

### 2. EBS JWT Validation

Every request from the Twitch extension includes a JWT signed with the extension's secret. The EBS (FastAPI) validates it before processing any request.

```python
import jwt as pyjwt

def verify_twitch_jwt(authorization: str = Header(...)):
    token = authorization.removeprefix("Bearer ")
    payload = pyjwt.decode(
        token,
        base64.b64decode(TWITCH_EXTENSION_SECRET),
        algorithms=["HS256"]
    )
    return payload  # contains channel_id, opaque_user_id, role
```

**New env vars:**
- `TWITCH_EXTENSION_CLIENT_ID`
- `TWITCH_EXTENSION_SECRET` (base64-encoded secret from Twitch dev console)

### 3. Broadcaster Giveaway Trigger

The extension's **Config / Live Config** view is shown only to the broadcaster. A "Trigger Giveaway" button calls the EBS, which:
1. Finds all viewers currently watching (Twitch does not expose this directly — see note below)
2. Picks a random linked viewer from recently active extension users
3. Grants them +1 to their `draw_limit`
4. Notifies via Twitch PubSub so all extension instances update

**Broadcaster endpoint:**
`POST /twitch/giveaway` (requires broadcaster role in JWT)
- Picks a random `twitch_user_id` from a recency pool (viewers who interacted with the extension in the last N minutes)
- Increments winner's `draw_limit` by 1
- Sends PubSub broadcast to the channel: `{type: "winner", username: "...", display_name: "..."}`
- Returns `{winner_username}`

**Viewer participation (building the pool):**
Viewers who open the extension panel call `POST /twitch/heartbeat` which records `{twitch_user_id, channel_id, seen_at}` in a `TwitchPresence` table (or in-memory dict with TTL). Only viewers with a linked Fantasy account are eligible to win.

### 4. Twitch PubSub Broadcast

When a winner is selected, the EBS pushes a message to the Twitch channel's PubSub topic using the broadcaster's access token:

```
POST https://api.twitch.tv/helix/extensions/pubsub
{
  "target": ["broadcast"],
  "broadcaster_id": "<channel_id>",
  "message": "{\"type\": \"winner\", \"username\": \"...\", \"fantasy_pts\": 0}"
}
```

All open extension panels receive this message and display a winner announcement banner.

### 5. Extension Frontend (JS)

Three views (standard Twitch extension architecture):
- **Panel / Overlay** (viewer-facing): Show link status, heartbeat, display winner banner on PubSub event
- **Config** (broadcaster setup): Enter their linked Fantasy admin credentials or channel config
- **Live Config** (broadcaster during stream): "Trigger Giveaway" button

The extension frontend is a small standalone HTML/JS bundle hosted on Twitch CDN (uploaded via Twitch dev console). It is **not** served by FastAPI.

---

## New Database Tables

### `TwitchLinkCode` (or in-memory with TTL)
```python
class TwitchLinkCode(Base):
    __tablename__ = "twitch_link_codes"
    code       = Column(String, primary_key=True)   # 6-char
    user_id    = Column(Integer, ForeignKey("users.id"))
    expires_at = Column(Integer)  # Unix timestamp
```

### `TwitchPresence` (optional, for pool tracking)
```python
class TwitchPresence(Base):
    __tablename__ = "twitch_presence"
    twitch_user_id = Column(String, primary_key=True)
    channel_id     = Column(String)
    seen_at        = Column(Integer)  # Unix timestamp
```

---

## New Backend Routes (all under `/twitch/`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/twitch/link-code` | Fantasy session | Generate 6-char linking code |
| `POST` | `/twitch/link` | Twitch JWT | Consume code, link accounts |
| `POST` | `/twitch/heartbeat` | Twitch JWT | Record viewer presence |
| `POST` | `/twitch/giveaway` | Twitch JWT (broadcaster) | Trigger giveaway, grant draw |
| `GET` | `/twitch/status` | Twitch JWT | Return viewer's link status + draw count |

---

## Critical Files
- `backend/models.py` — add `twitch_user_id` to User, add `TwitchLinkCode`, `TwitchPresence`
- `backend/main.py` (or new `backend/twitch.py` router) — all `/twitch/` routes
- `frontend/app.js` — "Link Twitch" UI in My Team tab
- New folder `twitch-extension/` — standalone extension HTML/JS bundle

---

## Notes & Constraints
- Twitch does not expose a live viewer list to extensions; presence pool is built from heartbeat calls only
- The extension bundle must be submitted to Twitch and approved (or tested in developer mode)
- PubSub requires the broadcaster's OAuth token with `channel:read:subscriptions` or `channel_read` scope — this needs a one-time OAuth flow for the broadcaster
- For Kanaliiga specifically, the broadcaster is likely a fixed known account — a simpler auth flow (admin-stored token) may suffice vs full OAuth

---

## Verification
1. User generates link code on Fantasy site, enters in extension panel → `User.twitch_user_id` populated
2. Viewer heartbeats are recorded in presence table
3. Broadcaster clicks "Trigger Giveaway" → random linked viewer's `draw_limit` incremented
4. PubSub message received by all open extension panels, winner banner shown
5. Winner sees +1 draw available on Fantasy site
