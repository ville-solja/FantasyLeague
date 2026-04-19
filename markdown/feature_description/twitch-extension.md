# Twitch Extension

A Twitch Panel Extension that connects the broadcaster's stream to the FantasyLeague app. Viewers can link their Fantasy accounts, receive token drops, and see MVP announcements — all without leaving Twitch.

---

## Architecture

```
Twitch Extension (panel/live_config HTML/JS on Twitch CDN)
          ↕  HTTPS + Twitch-signed JWT
FastAPI EBS (Extension Backend Service) — /twitch/* routes
          ↕
Fantasy League SQLite database
```

The extension frontend is a standalone HTML/JS bundle uploaded to Twitch CDN. It is **not** served by FastAPI in production, but the `twitch-extension/` folder lives in this repo. The backend routes act as the EBS.

## Repository Layout

```
twitch-extension/
├── panel.html          # Viewer-facing panel (account linking + token/MVP display)
├── config.html         # Broadcaster one-time setup
├── live_config.html    # Broadcaster quick actions (giveaway, token drop, MVP)
├── extension.js        # Shared JS (EBS calls, PubSub, heartbeat)
├── extension.css       # Shared styles
├── dev-harness.html    # Local dev only — not uploaded to Twitch
└── package.sh          # Builds Twitch CDN ZIP
```

The broadcaster actions (giveaway, token drop, MVP selection) are in the **Live Config** view, which appears as the extension's **Quick Actions** in the Twitch Stream Manager dashboard — matching stories 13.1, 13.2, and 13.4.

---

## Account Linking (story 13.3)

Users link their Fantasy account to Twitch in two steps across two surfaces:

1. **Fantasy site (Profile tab):** User clicks "Generate Link Code" → `POST /twitch/link-code` (requires Fantasy session) → a 6-character code is displayed with a 10-minute countdown.
2. **Twitch extension panel:** User enters the 6-character code in the panel's text input → `POST /twitch/link` (Twitch JWT) → backend validates the code and stores `twitch_user_id` on the `User` row.

Once linked, the panel shows the viewer's token balance and they become eligible for giveaways and token drops.

---

## Broadcaster Quick Actions (live_config.html)

The Live Config view (shown in Twitch Stream Manager as the extension's Quick Actions) has a single flow: **MVP selection + token drop**.

### Flow

1. Broadcaster clicks **"Select match MVP"**
2. Current week's series are listed (only matches that have already started)
3. Broadcaster picks the series (team1 vs team2), then the specific match (Match 1, Match 2…)
4. Player grid is shown; broadcaster selects the MVP and clicks **"Confirm MVP & Drop Tokens"**
5. The MVP is saved and tokens are automatically distributed to viewers in the presence pool

### Token drop rules
- Fires automatically on MVP confirmation — no separate trigger needed
- **Once per match**: re-selecting a different MVP for the same match does not re-drop tokens
- Up to `TWITCH_DROP_MAX` (default 20) random linked viewers from the pool receive +1 token
- Result is broadcast via Twitch PubSub so all open panels see the MVP announcement

---

## Presence Pool

Viewers who open the panel call `POST /twitch/heartbeat` every ~55 seconds. Only viewers with a linked Fantasy account and a heartbeat within the last 10 minutes are eligible for drops and giveaways.

---

## Twitch PubSub

When an MVP is confirmed (which triggers a token drop) the EBS calls:

```
POST https://api.twitch.tv/helix/extensions/pubsub
```

with a broadcaster-role JWT signed by `TWITCH_EXTENSION_SECRET`. All open extension panels receive the message and display the appropriate announcement banner.

When `TWITCH_LOCAL_DEV=true`, the HTTP call is skipped and the message is printed to the server log instead.

---

## Deployment

### Step 1 — Register the extension
Go to [dev.twitch.tv/console/extensions](https://dev.twitch.tv/console/extensions) → Create Extension. Note the **Client ID** and **Extension Secret** (base64).

### Step 2 — Configure environment
Add to `.env`:
```
TWITCH_EXTENSION_CLIENT_ID=<client id from console>
TWITCH_EXTENSION_SECRET=<base64 secret from console>
TWITCH_DROP_MAX=20
```

### Step 3 — Package and upload
```bash
TWITCH_EBS_URL=https://your-domain.example.com bash twitch-extension/package.sh
```
Upload the produced ZIP in the Twitch dev console. Set the version to **Local Test** for testing on a real stream visible only to whitelisted testers.

### Step 4 — Install and test
Add the extension to the broadcast channel. Open the Twitch Stream Manager to confirm the Quick Actions (Live Config) view appears. Test the account linking flow from the Fantasy profile tab.

### Local development
The `twitch-extension/` folder is served by the backend at `/twitch-ext` when the directory is present. The dev harness is accessible at `http://localhost:8000/twitch-ext/dev-harness.html` and simulates the extension panel without requiring a real Twitch session. It is not uploaded to Twitch CDN — only the packaged ZIP is.

---

## Endpoints

### `POST /twitch/link-code`
Authenticated Fantasy session. Generates a 6-char alphanumeric linking code for the current user. TTL: 10 minutes.

### `POST /twitch/link`
Twitch JWT. Body: `{code}`. Consumes a linking code and stores the Twitch opaque user ID on the matched Fantasy account.

### `POST /twitch/heartbeat`
Twitch JWT. Records viewer presence for giveaway/drop eligibility. Call every ~55 seconds.

### `GET /twitch/status`
Twitch JWT. Returns `{linked, tokens, username}` for the calling viewer.

### `GET /twitch/matches/current`
Twitch JWT. Returns matches from the current/most-recent week with per-match player lists. Used for MVP selection.

### `POST /twitch/mvp` *(broadcaster only)*
Twitch JWT (broadcaster role). Body: `{match_id, player_id}`. Upserts the MVP selection, triggers a one-time token drop to the presence pool (skipped on re-confirm for the same match), and broadcasts via PubSub. Returns `{match_id, player_id, player_name, token_drop: {winners, pool_size, already_dropped}}`.


---

## Database Tables

| Table | Purpose |
|---|---|
| `twitch_link_codes` | Temporary 6-char codes with 10-min TTL |
| `twitch_presence` | Viewer heartbeat timestamps for pool eligibility |
| `twitch_mvp` | One MVP selection per match, broadcaster-updatable |
| `twitch_token_drops` | Once-per-series drop records; prevents duplicate drops |

`users.twitch_user_id` stores the Twitch opaque user ID once an account is linked.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_EXTENSION_CLIENT_ID` | *(empty)* | Extension client ID from Twitch dev console |
| `TWITCH_EXTENSION_SECRET` | *(empty)* | Base64-encoded extension secret from Twitch dev console |
| `TWITCH_DROP_MAX` | `20` | Server-side cap on viewers per token drop |
| `TWITCH_LOCAL_DEV` | *(unset)* | Set to `true` to bypass JWT validation and PubSub HTTP calls locally. **Never set in production.** |

---

## Notes & Constraints

- Twitch does not expose a live viewer list. The giveaway/drop pool is built from heartbeat calls — only viewers who have opened the panel recently are eligible.
- PubSub is broadcast-only from EBS to viewers. The extension cannot send PubSub to other viewers directly.
- MVP selection has no scoring impact — it is engagement/display only in this phase.
- The extension must be submitted to Twitch for review before public release, or used in developer test mode.
- The token drop deduplication key is set automatically to the match ID — once tokens are dropped for a given match they will not drop again even if the broadcaster re-confirms a different MVP.
