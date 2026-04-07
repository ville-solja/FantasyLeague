# Plan: Twitch Extension — Card Draw Giveaway, MVP Selection & Token Drops

## Context
When a Kanaliiga match is being streamed on Twitch, an extension panel on the stream provides three broadcaster features:
1. **Card draw giveaway** — broadcaster triggers a free draw for a random eligible viewer.
2. **MVP selection** (13.1) — broadcaster picks the match MVP from the player list; stored in the DB and broadcast to viewers.
3. **Token drops** (13.2) — broadcaster drops tokens to *n* randomly selected eligible viewers (n is configurable).

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

### 3. Broadcaster Giveaway Trigger (card draw)

The extension's **Config / Live Config** view is shown only to the broadcaster. A "Trigger Giveaway" button calls the EBS, which:
1. Finds all viewers currently watching (Twitch does not expose this directly — see note below)
2. Picks a random linked viewer from recently active extension users
3. Grants them +1 token
4. Notifies via Twitch PubSub so all extension instances update

**Broadcaster endpoint:**
`POST /twitch/giveaway` (requires broadcaster role in JWT)
- Picks a random `twitch_user_id` from a recency pool (viewers who interacted with the extension in the last N minutes)
- Increments winner's `tokens` by 1
- Sends PubSub broadcast to the channel: `{type: "winner", username: "...", display_name: "..."}`
- Returns `{winner_username}`

**Viewer participation (building the pool):**
Viewers who open the extension panel call `POST /twitch/heartbeat` which records `{twitch_user_id, channel_id, seen_at}` in a `TwitchPresence` table (or in-memory dict with TTL). Only viewers with a linked Fantasy account are eligible to win.

### 4. MVP Selection (13.1)

The broadcaster can designate the MVP of a match from the extension's Live Config view. The player list is drawn from ingested match data for the current week's matches in the active league.

**Flow:**
1. Broadcaster opens the Live Config panel during a match stream
2. Extension calls `GET /twitch/matches/current` — returns matches from the current week with their player lists
3. Broadcaster selects a player → extension calls `POST /twitch/mvp`
4. MVP is stored in DB and broadcast via PubSub to all open extension panels

**New endpoint:**
`GET /twitch/matches/current` (Twitch JWT, any role)
- Returns matches from the current DB week with per-match player lists (player_id, player_name, team_name)
- Scoped to the configured `AUTO_INGEST_LEAGUES`

`POST /twitch/mvp` (requires broadcaster role in JWT)
- Body: `{match_id: int, player_id: int}`
- Upserts one MVP record per match (broadcaster can change their pick)
- PubSub broadcast: `{type: "mvp", player_name: "...", match_id: ...}`
- Returns `{match_id, player_id, player_name}`

**New DB table:**
```python
class TwitchMVP(Base):
    __tablename__ = "twitch_mvp"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    match_id    = Column(Integer, ForeignKey("matches.match_id"))
    player_id   = Column(Integer, ForeignKey("players.id"))
    channel_id  = Column(String)   # Twitch channel where it was selected
    selected_at = Column(Integer)  # Unix timestamp
```

MVP data is read-only from the Fantasy web app (no scoring impact in this phase).

### 5. Token Drops (13.2)

A separate "Token Drop" action lets the broadcaster reward *n* viewers at once with 1 token each. *n* is configurable per drop so the broadcaster can scale the reward based on stream size or event significance.

**Flow:**
1. Broadcaster enters desired drop count in Live Config panel (default: 5)
2. Clicks "Drop Tokens" → extension calls `POST /twitch/token-drop`
3. Backend randomly selects up to *n* distinct linked viewers from the presence pool
4. Each winner gets +1 token
5. PubSub broadcast: `{type: "token_drop", winners: ["user1", "user2", ...]}`

**New endpoint:**
`POST /twitch/token-drop` (requires broadcaster role in JWT)
- Body: `{count: int}` — number of tokens to drop (capped server-side at a configurable max, default 20)
- Selects up to `count` random eligible `twitch_user_id`s from presence pool
- Increments each winner's `tokens` by 1
- Audits the action (`twitch_token_drop`, detail includes channel + winner count)
- Returns `{winners: [list of fantasy usernames]}`

**New env var:**
- `TWITCH_DROP_MAX` — server-side cap on drop count per trigger (default 20)

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

### 6. Extension Frontend (JS)

Three views (standard Twitch extension architecture):
- **Panel / Overlay** (viewer-facing): Show link status, heartbeat, display winner banner and MVP announcements on PubSub events
- **Config** (broadcaster setup): Enter their linked Fantasy admin credentials or channel config
- **Live Config** (broadcaster during stream): "Trigger Giveaway" button, "Drop Tokens" button with count input, match player list with MVP selector

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

### `TwitchPresence` (for pool tracking)
```python
class TwitchPresence(Base):
    __tablename__ = "twitch_presence"
    twitch_user_id = Column(String, primary_key=True)
    channel_id     = Column(String)
    seen_at        = Column(Integer)  # Unix timestamp
```

### `TwitchMVP` (13.1 — one row per match, broadcaster can update)
```python
class TwitchMVP(Base):
    __tablename__ = "twitch_mvp"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    match_id    = Column(Integer, ForeignKey("matches.match_id"))
    player_id   = Column(Integer, ForeignKey("players.id"))
    channel_id  = Column(String)
    selected_at = Column(Integer)  # Unix timestamp
```

---

## New Backend Routes (all under `/twitch/`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/twitch/link-code` | Fantasy session | Generate 6-char linking code |
| `POST` | `/twitch/link` | Twitch JWT | Consume code, link accounts |
| `POST` | `/twitch/heartbeat` | Twitch JWT | Record viewer presence |
| `POST` | `/twitch/giveaway` | Twitch JWT (broadcaster) | Trigger giveaway, grant 1 token to 1 winner |
| `POST` | `/twitch/token-drop` | Twitch JWT (broadcaster) | Grant 1 token to n random viewers |
| `GET` | `/twitch/matches/current` | Twitch JWT | Current week matches with player lists |
| `POST` | `/twitch/mvp` | Twitch JWT (broadcaster) | Set MVP for a match |
| `GET` | `/twitch/status` | Twitch JWT | Return viewer's link status + token count |

---

## Critical Files
- `backend/models.py` — add `twitch_user_id` to User, add `TwitchLinkCode`, `TwitchPresence`, `TwitchMVP`
- `backend/main.py` (or new `backend/twitch.py` router) — all `/twitch/` routes
- `frontend/app.js` — "Link Twitch" UI in My Team tab
- New folder `twitch-extension/` — standalone extension HTML/JS bundle

---

## Notes & Constraints
- Twitch does not expose a live viewer list to extensions; presence pool is built from heartbeat calls only
- The extension bundle must be submitted to Twitch and approved (or tested in developer mode)
- PubSub requires the broadcaster's OAuth token with `channel:read:subscriptions` or `channel_read` scope — this needs a one-time OAuth flow for the broadcaster
- For Kanaliiga specifically, the broadcaster is likely a fixed known account — a simpler auth flow (admin-stored token) may suffice vs full OAuth
- `TWITCH_DROP_MAX` caps the token-drop count server-side to prevent abuse (default 20)
- MVP selection has no scoring impact in this phase — it is display/engagement only
- `/twitch/matches/current` returns players from DB week matches, not live Twitch data — no real-time match detection

---

## Verification
1. User generates link code on Fantasy site, enters in extension panel → `User.twitch_user_id` populated
2. Viewer heartbeats are recorded in presence table
3. Broadcaster clicks "Trigger Giveaway" → random linked viewer's `tokens` incremented by 1, PubSub winner banner shown
4. Broadcaster sets drop count to 5, clicks "Drop Tokens" → up to 5 linked viewers each get +1 token, PubSub broadcast lists winners
5. Broadcaster opens match player list, selects MVP → `TwitchMVP` row upserted, PubSub MVP announcement shown on all panels
6. Winner / recipient sees updated token balance on the Fantasy site
