# Twitch Extension

A Twitch Panel Extension that connects the broadcaster's stream to the FantasyLeague app. Viewers link their Fantasy accounts, receive token drops on MVP selection, and see MVP announcements — all without leaving Twitch.

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

### Responsibilities by role

| Role | Responsibility |
|---|---|
| **Kanaliiga developer** | Register extension in Twitch dev console; set EBS URL once via `set-ebs-url.sh`; upload packaged ZIP |
| **Broadcaster (streamer)** | Install the extension; use Quick Actions to select MVP |
| **Viewer** | Open panel to link account, see token balance, receive drops |

Broadcasters do **not** configure the EBS URL. It is set globally by the developer once and propagates to all channel installs automatically.

---

## Repository Layout

```
twitch-extension/
├── panel.html          # Viewer-facing panel (account linking + token/MVP display)
├── config.html         # Broadcaster one-time setup page
├── live_config.html    # Broadcaster quick actions (MVP selection + token drop)
├── extension.js        # Shared JS (EBS URL resolution, API calls, PubSub, heartbeat)
├── extension.css       # Shared styles
├── dev-harness.html    # Local dev only — not uploaded to Twitch
├── package.sh          # Builds Twitch CDN ZIP
└── set-ebs-url.sh      # Sets EBS URL in the global Configuration Service segment
```

---

## Deployment

### Prerequisites — Developer Console Settings

> **Read this before running any scripts.** These settings are easy to get wrong. All are on the Extension Settings page: `dev.twitch.tv/console/extensions` → click extension → **Extension Settings**.

| Setting | Required value | Common mistake |
|---|---|---|
| **Configure method** (under "Select how you will configure your extension") | **Extension Configuration Service** — click Save after selecting | Left at default, or saved without clicking Save |
| **Developer Writable Channel Segment Version** | **Leave empty** | Entering a value here gates the extension per-channel and may deactivate it on installed channels |
| **Extension status** | **Local Test** or higher | Configuration Service API returns 401 if extension is still in "Created" status |
| **Client ID** | Shown in the top-right corner of Extension Settings | Used as `TWITCH_EXTENSION_CLIENT_ID` |
| **Extension Secret** | "Extension Secrets" table → **Key column** (long base64 string) | Using the "Twitch API Client Secret" shown mid-page instead — these are different values |

### Step 1 — Register the extension

Go to [dev.twitch.tv/console/extensions](https://dev.twitch.tv/console/extensions) → Create Extension → fill in name and type (Panel). Note the **Client ID**.

### Step 2 — Enable the Configuration Service

In Extension Settings, under "Select how you will configure your extension", choose **Extension Configuration Service** and click **Save Changes**. Do not enter anything in "Developer Writable Channel Segment Version".

### Step 3 — Configure the backend environment

Add to `.env`:
```
TWITCH_EXTENSION_CLIENT_ID=<Client ID from Extension Settings top-right>
TWITCH_EXTENSION_SECRET=<Key from Extension Secrets table at bottom of Extension Settings>
TWITCH_DROP_MAX=20
```

`TWITCH_EXTENSION_SECRET` is the **base64 key** from the Extension Secrets table. It is not the "Twitch API Client Secret" that appears mid-page.

### Step 4 — Package and upload

The EBS URL is not baked into the package — it is set separately in Step 5. No environment variables are needed for packaging:

```bash
bash twitch-extension/package.sh
```

Upload the produced ZIP in the Twitch dev console. Set the version to **Local Test** to test on whitelisted channels, or release for public use after Twitch review.

### Step 5 — Set the EBS URL (one-time global, operator only)

Run once after the first deploy, and again any time the backend URL changes:

```bash
bash twitch-extension/set-ebs-url.sh https://your-domain.example.com
```

The script prompts for three values if not pre-filled at the top of the file:
- **Client ID** — Extension Settings, top-right
- **Extension Secret** — Extension Secrets table → Key column (bottom of Extension Settings)
- **Your Twitch User ID** — the numeric ID of the account that owns the extension (look up at https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/) It writes the URL into the extension's **global** Configuration Service segment. All channel installs pick up the change immediately on next panel load — no rebuild or re-upload required.

To debug a failed run:
```bash
bash twitch-extension/set-ebs-url.sh --debug https://your-domain.example.com
```

### Step 6 — Install and test (broadcaster)

The broadcaster adds the extension to their channel from the Twitch extension directory or via a developer test install link. Once installed, the Quick Actions (Live Config view) appear automatically in Twitch Stream Manager. No further configuration is needed on the broadcaster's side.

---

## Account Linking (story 13.3)

Users link their Fantasy account to Twitch across two surfaces:

1. **Fantasy site (Profile tab):** User clicks "Generate Twitch Code" → `POST /twitch/link-code` → a 6-character alphanumeric code appears with a 10-minute countdown.
2. **Twitch extension panel:** User enters the code in the panel → `POST /twitch/link` → backend validates and stores `twitch_user_id` on the user record.

Once linked, the panel shows token balance and the viewer enters the drop pool.

---

## Broadcaster Quick Actions (live_config.html)

The Live Config view (Twitch Stream Manager → Quick Actions) has one flow: **MVP selection + token drop**.

### Flow

1. Broadcaster clicks **"Select match MVP"**
2. Series from the current/most-recent week are listed
3. Broadcaster selects the series (team1 vs team2), then the specific match (Match 1, Match 2…)
4. Player grid is shown; broadcaster selects the MVP and clicks **"Confirm MVP & Drop Tokens"**
5. MVP is saved; tokens drop automatically to the presence pool

### Token drop rules
- Fires on MVP confirmation — no separate trigger
- **Once per match**: re-confirming a different MVP for the same match does not re-drop tokens
- Up to `TWITCH_DROP_MAX` (default 20) random linked viewers from the pool receive +1 token
- Result broadcast via Twitch PubSub — all open panels show the MVP announcement

---

## Viewer Panel (panel.html)

1. Panel reads EBS URL from `Twitch.ext.configuration.global.content` at startup
2. Calls `GET /twitch/status` to determine linked state
3. **Unlinked:** shows account linking instructions (enter 6-char code from Fantasy Profile)
4. **Linked:** shows token balance and username; heartbeat keeps viewer in the drop pool
5. PubSub messages trigger MVP banner and token drop announcements
6. If EBS URL is missing from config or unreachable after 8 seconds, shows `"Extension not configured — contact the broadcaster."` rather than a blank panel

---

## Presence Pool

Viewers call `POST /twitch/heartbeat` every ~55 seconds while the panel is open. Only viewers with a linked account and a heartbeat within the last 10 minutes are eligible for drops.

---

## Twitch PubSub

On MVP confirmation the EBS calls:
```
POST https://api.twitch.tv/helix/extensions/pubsub
```
with a broadcaster-role JWT signed by `TWITCH_EXTENSION_SECRET`. When `TWITCH_LOCAL_DEV=true` the HTTP call is skipped and the message is printed to the server log.

---

## Local Development

The `twitch-extension/` folder is served by the backend at `/twitch-ext` when present. The dev harness at `http://localhost:8000/twitch-ext/dev-harness.html` simulates the extension panel without a real Twitch session. It is not uploaded to Twitch CDN.

---

## Endpoints

### `POST /twitch/link-code`
Authenticated Fantasy session. Generates a 6-char linking code. TTL: 10 minutes.

### `POST /twitch/link`
Twitch JWT. Body: `{code}`. Consumes code, stores Twitch opaque user ID on the user record.

### `POST /twitch/heartbeat`
Twitch JWT. Records viewer presence. Call every ~55 seconds.

### `GET /twitch/status`
Twitch JWT. Returns `{linked, tokens, username}` for the calling viewer.

### `GET /twitch/matches/current`
Twitch JWT. Returns matches from the current/most-recent week with per-match player lists.

### `POST /twitch/mvp` *(broadcaster only)*
Twitch JWT (broadcaster role). Body: `{match_id, player_id}`. Upserts MVP, triggers one-time token drop (skipped if match already dropped), broadcasts via PubSub. Returns `{match_id, player_id, player_name, token_drop: {winners, pool_size, already_dropped}}`.

---

## Database Tables

| Table | Purpose |
|---|---|
| `twitch_link_codes` | Temporary 6-char codes with 10-min TTL |
| `twitch_presence` | Viewer heartbeat timestamps for pool eligibility |
| `twitch_mvp` | One MVP selection per match, broadcaster-updatable |
| `twitch_token_drops` | Once-per-match drop records; prevents duplicate drops |

`users.twitch_user_id` stores the Twitch opaque user ID once linked.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_EXTENSION_CLIENT_ID` | *(empty)* | Client ID from Extension Settings (top-right corner) |
| `TWITCH_EXTENSION_SECRET` | *(empty)* | Base64 key from Extension Secrets table (bottom of Extension Settings). Not the Twitch API Client Secret. |
| `TWITCH_DROP_MAX` | `20` | Max viewers per token drop |
| `TWITCH_LOCAL_DEV` | *(unset)* | `true` bypasses JWT validation and PubSub HTTP calls. Never set in production. |

---

## Notes

- Twitch does not expose a live viewer list — the drop pool is built from heartbeat calls only.
- PubSub is EBS→panel only; the extension cannot send messages to other viewers.
- MVP selection has no scoring impact — engagement and drops only.
- The extension must pass Twitch review before public release, or be used in developer test mode.
- Token drop deduplication is keyed on match ID — once dropped for a match, it will not drop again even if the broadcaster re-confirms a different MVP.
