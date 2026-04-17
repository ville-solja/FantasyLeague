# Plan: Twitch Extension — Card Draw Giveaway, MVP Selection & Token Drops

## Context
When a Kanaliiga match is being streamed on Twitch, an extension panel on the stream provides three broadcaster features:
1. **Card draw giveaway** — broadcaster triggers a free draw for a random eligible viewer.
2. **MVP selection** (13.1) — broadcaster picks the match MVP from the player list; stored in the DB and broadcast to viewers.
3. **Token drops** (13.2) — broadcaster drops tokens to *n* randomly selected eligible viewers (n is configurable).

---

## Implementation Status

### ✅ DONE

| Component | Location | Notes |
|---|---|---|
| EBS router mounted | `backend/main.py` | `twitch_router` included |
| `POST /twitch/link-code` | `backend/twitch.py` | Generates 6-char code, 10-min TTL |
| `POST /twitch/link` | `backend/twitch.py` | Consumes code, sets `User.twitch_user_id` |
| `POST /twitch/heartbeat` | `backend/twitch.py` | Updates `TwitchPresence.seen_at`, 10-min TTL pool |
| `GET /twitch/status` | `backend/twitch.py` | Returns link status + token count |
| `GET /twitch/matches/current` | `backend/twitch.py` | Current week matches + player lists |
| `POST /twitch/mvp` | `backend/twitch.py` | Upserts `TwitchMVP`, returns match/player info |
| `POST /twitch/giveaway` | `backend/twitch.py` | Picks random linked viewer from presence pool, grants +1 token |
| `POST /twitch/token-drop` | `backend/twitch.py` | Grants +1 token to up to *n* random linked viewers |
| DB models | `backend/models.py` | `TwitchLinkCode`, `TwitchPresence`, `TwitchMVP`; `User.twitch_user_id` |
| JWT validation | `backend/twitch.py` | `verify_twitch_jwt()` with `TWITCH_LOCAL_DEV` bypass |
| Viewer panel | `twitch-extension/panel.html` | Linked/unlinked states, heartbeat timer, PubSub listener |
| Broadcaster controls | `twitch-extension/live_config.html` | Giveaway button, token drop count + button, MVP selector |
| Broadcaster setup | `twitch-extension/config.html` | EBS URL config |
| Shared extension JS | `twitch-extension/extension.js` | `init()`, `ebsGet()`, `ebsPost()`, `startHeartbeat()` |
| Dev harness | `twitch-extension/dev-harness.html` | Local dev, stubs `window.Twitch.ext` |
| Packaging script | `twitch-extension/package.sh` | Produces CDN-ready ZIP |

---

### ✅ RESOLVED GAPS

#### Gap 1 — "Link Twitch" UI (resolved)

The backend link-code flow is complete, but the main Fantasy web app has no UI entry point for users to initiate account linking. `app.js` has zero Twitch references.

**Required changes:**
- Add a "Link Twitch Account" section to the **Profile tab** in `frontend/app.js`
- Show current link status (linked / not linked + Twitch username if linked)
- "Generate Code" button → calls `POST /twitch/link-code` (auth required) → displays the 6-char code and instructions to enter it in the extension panel
- Add a corresponding section to the Profile tab HTML in `index.html` (or wherever the profile tab markup lives)
- The code has a 10-min TTL — show a countdown or at minimum note the expiry

**Why this matters:** Story 13.3 AC — "User can navigate to their profile and start process for linking their Twitch account." Without this, no viewer can ever link, so token drops and giveaway eligibility are permanently empty.

---

#### Gap 2 — PubSub broadcast (resolved)

The giveaway and token-drop endpoints return winner data to the broadcaster's extension client, but never call the Twitch PubSub API. As a result:
- The winner banner in `panel.html` (`window.Twitch.ext.listen("broadcast", ...)`) never fires
- MVP announcements in `panel.html` never fire
- Viewers see nothing when the broadcaster triggers an event

**Required changes in `backend/twitch.py`:**

Add a helper that posts to the Twitch Extensions PubSub API:

```python
import httpx

async def _pubsub_broadcast(channel_id: str, message: dict):
    secret = base64.b64decode(os.getenv("TWITCH_EXTENSION_SECRET", ""))
    # Build a broadcaster-role JWT signed with the extension secret
    payload = {
        "exp": int(time.time()) + 60,
        "user_id": channel_id,
        "role": "external",
        "channel_id": channel_id,
        "pubsub_perms": {"send": ["broadcast"]},
    }
    token = pyjwt.encode(payload, secret, algorithm="HS256")
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.twitch.tv/helix/extensions/pubsub",
            headers={
                "Authorization": f"Bearer {token}",
                "Client-Id": os.getenv("TWITCH_EXTENSION_CLIENT_ID", ""),
                "Content-Type": "application/json",
            },
            json={
                "target": ["broadcast"],
                "broadcaster_id": channel_id,
                "is_global_broadcast": False,
                "message": json.dumps(message),
            },
        )
```

Call `_pubsub_broadcast` at the end of:
- `POST /twitch/giveaway` — `{type: "winner", username: "...", display_name: "..."}`
- `POST /twitch/token-drop` — `{type: "token_drop", winners: [...]}`
- `POST /twitch/mvp` — `{type: "mvp", player_name: "...", match_id: ...}`

**Notes:**
- Use an async route or run the broadcast in a background task (`BackgroundTasks`) to avoid blocking the response
- If `TWITCH_LOCAL_DEV=true`, skip the HTTP call and print the message instead
- Add `httpx` to `backend/requirements.txt`

---

#### Gap 3 — Once-per-series rate limit (resolved)

Story 13.2 AC: *"Streamer can do this only once per series."* The current `POST /twitch/token-drop` has no rate limiting — a broadcaster can call it repeatedly for the same series.

**Required changes:**

Add a `series_id` field to the token-drop request and record each completed drop:

```python
class TwitchTokenDrop(Base):
    __tablename__ = "twitch_token_drops"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String)
    series_id  = Column(String)   # opaque identifier for the series
    dropped_at = Column(Integer)  # Unix timestamp
    count      = Column(Integer)  # how many tokens were dropped
```

In the `POST /twitch/token-drop` handler:
1. Require `series_id` in the request body
2. Check `TwitchTokenDrop` for an existing row with `(channel_id, series_id)` — if found, return `409 Conflict`
3. After a successful drop, insert the `TwitchTokenDrop` row

The `series_id` can be any string the broadcaster chooses to identify the series (e.g. `"week3-series2"`). It does not need to reference a DB series — it is broadcaster-provided and opaque.

---

#### Gap 4 — Extension setup instructions (resolved)

Story 13.4 AC: *"Streamer is able to take the extension into use with instructions documented in fantasy league app."* No setup instructions exist in the app or docs.

**Required changes:**
- Add a short setup guide to `markdown/feature_description/twitch-extension.md` covering:
  1. Register extension in Twitch dev console (link to dev console)
  2. Set `EBS_URL` in `package.sh` to the production FastAPI hostname
  3. Run `bash twitch-extension/package.sh` to produce the ZIP
  4. Upload ZIP in Twitch dev console, set version to "Local Test" for testing
  5. Configure `TWITCH_EXTENSION_CLIENT_ID` and `TWITCH_EXTENSION_SECRET` env vars
  6. Broadcaster OAuth: how to obtain a broadcaster token for PubSub (one-time flow)
  7. Link Twitch account from Fantasy profile tab

---

## Architecture Overview

```
Twitch Extension (frontend JS) ←→ FastAPI EBS (Extension Backend Service)
                                         ↕
                               Fantasy League Database
```

The Twitch Extension is a Panel or Overlay extension served by Twitch CDN. It communicates with the Fantasy League backend acting as an EBS via Twitch-signed JWT calls.

---

## Env Vars

| Variable | Default | Description |
|---|---|---|
| `TWITCH_EXTENSION_CLIENT_ID` | *(empty)* | Extension Client-Id from Twitch dev console |
| `TWITCH_EXTENSION_SECRET` | *(empty)* | Base64-encoded extension secret from Twitch dev console |
| `TWITCH_DROP_MAX` | `20` | Server-side cap on token-drop count per trigger |
| `TWITCH_LOCAL_DEV` | `false` | Skip JWT validation and PubSub HTTP calls in local dev |

---

## All Backend Routes (under `/twitch/`)

| Method | Path | Auth | Status |
|---|---|---|---|
| `POST` | `/twitch/link-code` | Fantasy session | ✅ Done |
| `POST` | `/twitch/link` | Twitch JWT | ✅ Done |
| `POST` | `/twitch/heartbeat` | Twitch JWT | ✅ Done |
| `GET` | `/twitch/status` | Twitch JWT | ✅ Done |
| `GET` | `/twitch/matches/current` | Twitch JWT | ✅ Done |
| `POST` | `/twitch/mvp` | Twitch JWT (broadcaster) | ✅ Done (PubSub send: ❌ Gap 2) |
| `POST` | `/twitch/giveaway` | Twitch JWT (broadcaster) | ✅ Done (PubSub send: ❌ Gap 2) |
| `POST` | `/twitch/token-drop` | Twitch JWT (broadcaster) | ✅ Done (PubSub send: ❌ Gap 2; rate limit: ❌ Gap 3) |

---

## Extension Files (`twitch-extension/`)

| File | Status |
|---|---|
| `panel.html` | ✅ Done |
| `config.html` | ✅ Done |
| `live_config.html` | ✅ Done |
| `extension.js` | ✅ Done |
| `dev-harness.html` | ✅ Done |
| `package.sh` | ✅ Done |

---

## Local Development

### Phase A — Harness (no Twitch account)
1. Set `TWITCH_LOCAL_DEV=true` in `.env`, restart Docker.
2. Open `http://localhost:8000/twitch-ext/dev-harness.html`.
3. The harness renders all three views in tabs, stubs `window.Twitch.ext`, and includes a PubSub simulator. EBS skips JWT verification and PubSub HTTP calls.

### Phase B — Twitch Developer Rig
Register the extension in the Twitch dev console (free). The [Developer Rig](https://dev.twitch.tv/docs/extensions/rig/) renders iframes with real Twitch JWTs so all role-based flows can be tested without going live.

### Phase C — Twitch test version
`bash twitch-extension/package.sh` → upload ZIP → set version to "Local Test" in Twitch dev console. PubSub, heartbeat, and broadcaster flows can be verified end-to-end.

---

## ✅ All gaps resolved

### Drift fix: panel.html linking flow

The original `panel.html` called `POST /twitch/link-code` via `ebsPost()`, which sends a Twitch JWT. That endpoint requires a Fantasy session cookie — unavailable inside the extension. Fixed by inverting the flow to match user stories 13.3/13.4:

- **Fantasy site** (Profile tab): user generates the code via `POST /twitch/link-code` (Fantasy session), sees it with a countdown.
- **Extension panel**: user types the 6-char code into an input field → `POST /twitch/link` (Twitch JWT only). ✓

### Quick actions alignment

Stories 13.1, 13.2, and 13.4 all require broadcaster controls to be in **Quick Actions**. Twitch's Live Config view (`live_config.html`) IS the Quick Actions interface in the Twitch Stream Manager dashboard. The current architecture is already aligned — no structural changes needed.

All four implementation gaps have been resolved:

---

## Verification

1. User opens Profile tab → sees "Link Twitch Account" section → generates code → enters it in extension panel → `User.twitch_user_id` populated *(Gap 1)*
2. Viewer opens extension panel → heartbeat recorded in `TwitchPresence`
3. Broadcaster clicks "Trigger Giveaway" → winner's `tokens` +1, PubSub winner banner appears on all open panels *(Gap 2)*
4. Broadcaster sets drop count to 5, enters `series_id`, clicks "Drop Tokens" → up to 5 viewers get +1 token, PubSub broadcast lists winners *(Gap 2)*
5. Second drop attempt with same `series_id` → `409 Conflict` returned *(Gap 3)*
6. Broadcaster selects MVP from player list → `TwitchMVP` upserted, PubSub MVP announcement shown *(Gap 2)*
7. Token balance on Fantasy site reflects giveaway/drop winnings
