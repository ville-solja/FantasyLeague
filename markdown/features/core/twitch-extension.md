# Twitch Extension

A Twitch Panel Extension that brings Kana Cards into the stream as a complete game on Twitch (issue #157, version 1.2.0). Every viewer sees live fantasy results; a viewer logged in to Twitch joins with one button (a **soft account**, no sign-up), then draws cards, keeps a collection, sets a weekly roster and receives MVP token drops, all inside the panel. The broadcaster names match MVPs from Quick Actions. The extension never requires, mentions or links to the website. Details: [Twitch Extension Policy Compliance](../reference/twitch-extension-policy-compliance.md).

---

## Architecture

```
Twitch Extension (panel/live_config HTML/JS on Twitch CDN)
          ↕  HTTPS + Twitch-signed JWT
FastAPI EBS (Extension Backend Service) — /twitch/* routes
          ↕
Kana Cards SQLite database
```

The extension frontend is a standalone HTML/JS bundle uploaded to Twitch CDN. It is **not** served by FastAPI in production, but the `twitch-extension/` folder lives in this repo. The backend routes act as the EBS.

### Responsibilities by role

| Role | Responsibility |
|---|---|
| **Kana Cards developer** | Register extension in Twitch dev console; set EBS URL once via `set-ebs-url.sh`; upload packaged ZIP |
| **Broadcaster (streamer)** | Install the extension; use Quick Actions to select MVP |
| **Viewer** | Open the panel: follow live results; join with the Twitch login to draw, collect, set a roster and receive drops |

Broadcasters do **not** configure the EBS URL. It is set globally by the developer once and propagates to all channel installs automatically.

---

## Repository Layout

```
twitch-extension/
├── panel.html          # Viewer panel: Live / Cards / Roster tabs, Join, Settings
├── panel.js            # Viewer panel logic (live data, join, draws, collection, roster, leave)
├── config.html         # Broadcaster one-time setup page
├── live_config.html    # Broadcaster quick actions (MVP selection + token drop)
├── ebs-origins.js      # Backend origins the panel may call; empty here, written by package.sh (#164)
├── extension.js        # Shared JS (EBS URL resolution and origin check, API calls, PubSub, heartbeat)
├── extension.css       # Shared styles (Kanaliiga design tokens)
├── fonts/              # Big Shoulders Text (packaged; the extension is self-contained)
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
| **Capabilities** | Enable **Chat** and **Request Identity Link** on the version installed on the channel | Without Chat, Twitch rejects MVP chat announcements with 403 (logged by the EBS) — PubSub/token drops still work. Without Request Identity Link, Join still works but the identity share never reaches the EBS |
| **Asset Hosting paths** (per version: Version → Asset Hosting) | Panel Viewer Path `panel.html`, Config Path `config.html`, Live Config Path `live_config.html` | A folder prefix such as `twitch-extension/panel.html` or a leading `/` — Twitch's CDN then returns 404 for the Extension iframe |
| **Testing Base URI** (per version: Version → Asset Hosting) | `http://localhost:8080/`, serving the `twitch-extension/` folder with `python3 -m http.server 8080` | Pointing it at the production site (`https://kana-cards.com/`), which does not serve the extension pages, so every Local Test view returns 404. Used in Local Test only; Hosted Test and review load from the Twitch CDN |
| **Allowlist for URL Fetching Domains** (per version: Version → Capabilities) | `https://kana-cards.com` (the EBS host; no other entry needed) | Left empty — Twitch's Content Security Policy then blocks every EBS call (`connect-src` violation) |

### Step 1 — Register the extension

Go to [dev.twitch.tv/console/extensions](https://dev.twitch.tv/console/extensions) → Create Extension → fill in name and type (Panel). Note the **Client ID**.

### Step 2 — Enable the Configuration Service

In Extension Settings, under "Select how you will configure your extension", choose **Extension Configuration Service** and click **Save Changes**. Do not enter anything in "Developer Writable Channel Segment Version".

### Step 3 — Configure the backend environment

Add to `.env`:
```
TWITCH_EXTENSION_CLIENT_ID=<Client ID from Extension Settings top-right>
TWITCH_EXTENSION_SECRET=<Key from Extension Secrets table at bottom of Extension Settings>
TWITCH_EXTENSION_VERSION=<version installed on the channel, e.g. 1.2.0>
TWITCH_DROP_MAX=20
```

Update `TWITCH_EXTENSION_VERSION` whenever a new extension version is installed on the channel; without it, chat announcements are skipped.

`TWITCH_EXTENSION_SECRET` is the **base64 key** from the Extension Secrets table. It is not the "Twitch API Client Secret" that appears mid-page.

CORS allows only our own extension's iframe origin, `https://<TWITCH_EXTENSION_CLIENT_ID>.ext-twitch.tv` (the client id is regex-escaped into `^https://<id>\.ext-twitch\.tv$`), which covers Hosted Test and released versions; other extensions' origins get no `Access-Control-Allow-Origin` (#171). Without `TWITCH_EXTENSION_CLIENT_ID`, no `ext-twitch.tv` origin is allowed and start-up logs one warning, so set it wherever the extension runs (the test extension uses its own client id). For **Local Test**, the panel is served from the Testing Base URI (`http://localhost:8080`), so add that origin:
```
CORS_EXTRA_ORIGINS=http://localhost:8080
```
Leave it unset in production. See `reference/security-headers.md`.

### Step 4 — Package and upload

**Where the panel's backend address comes from (issue #164).** Two settings work together, and neither is written into the code, so every deployment chooses its own:

| Setting | Where it lives | What it does |
|---|---|---|
| Allowed backend origins | Baked into the extension package when it is built (`package.sh --ebs-origin`, written to the packaged `ebs-origins.js`) | The only origins the panel will ever call. Changing them needs a new extension version and a Twitch review |
| The backend URL (`ebs_url`) | The extension's Twitch configuration, set by `set-ebs-url.sh` (Step 5) | The URL the panel calls. Used only when it is `https:` and its origin is one of the allowed ones |

So someone holding the extension secret can change `ebs_url` but cannot point every panel at their own server. The repository copy of `ebs-origins.js` is an empty list, which only the local dev harness accepts (it sets `window.__EXT_DEV_HARNESS`).

Give each allowed origin with `--ebs-origin` (an `https://` origin, no path or trailing slash). A production package lists only the production host; a package for a test server may add the test host:

```bash
bash twitch-extension/package.sh 1.2.0 --ebs-origin https://fantasy.example.org
# test build: … --ebs-origin https://fantasy.example.org --ebs-origin https://test.fantasy.example.org
```

CI (`.github/workflows/docker-publish.yml`) packages every push to `main` with the origins in the repository variable `EBS_ORIGINS` (space-separated, Settings → Secrets and variables → Actions → Variables). Without it the extension isn't packaged (a notice in the run says so) and the Docker image is still built. The script refuses to run without a version or without an origin, refuses to overwrite an existing `twitch-extension-<version>.zip` (Twitch needs a new version per upload), and fails naming the file if any local `src`/`href` in a packaged HTML file is not in its `FILES` list. It also refuses to build when a viewer file (`panel.html`, `panel.js`, `extension.js`, `extension.css`, any `video*` file) contains "kana-cards.com", "Log into", "Generate Twitch Code", "Link your account" or a password field (Twitch policy 4.5). On success it prints the packaged origins, the Asset Hosting paths and the URL Fetching allowlist entries (the same origins) to set in the dev console. `backend/tests/test_twitch_review_resubmission.py` runs the same reference check in CI.

Upload the produced ZIP in the Twitch dev console. Set the version to **Local Test** to test on whitelisted channels, move it to **Hosted Test** and verify all three views before submitting for review. See [Twitch Extension Review Submission](../reference/twitch-extension-review-submission.md).

### Step 5 — Set the EBS URL (one-time global, operator only)

Run once after the first deploy, and again any time the backend URL changes:

```bash
bash twitch-extension/set-ebs-url.sh https://your-domain.example.com
```

The script prompts for three values unless they are exported in the environment (`TWITCH_CLIENT_ID`, `TWITCH_EXT_SECRET`, `TWITCH_OWNER_USER_ID`). Never write the secret into the script: it is tracked in git. The secret prompt is hidden, and the secret reaches the embedded Python through the environment, never as a command-line argument (issue #164):
- **Client ID** — Extension Settings, top-right
- **Extension Secret** — Extension Secrets table → Key column (bottom of Extension Settings)
- **Your Twitch User ID** — the numeric ID of the account that owns the extension (look up at https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/) It writes the URL into the extension's **global** Configuration Service segment. All channel installs pick up the change immediately on next panel load — no rebuild or re-upload required. The URL must be `https://` and its origin must be one the installed package was built with (`--ebs-origin`, Step 4), or the panel refuses to call it.

To debug a failed run:
```bash
bash twitch-extension/set-ebs-url.sh --debug https://your-domain.example.com
```

### Step 6 — Install and test (broadcaster)

The broadcaster adds the extension to their channel from the Twitch extension directory or via a developer test install link. Once installed, the Quick Actions (Live Config view) appear automatically in Twitch Stream Manager. No further configuration is needed on the broadcaster's side.

**After uploading a new version for a Hosted Test / invite-only release:** a fresh upload does not appear in "My Extensions" and is not what testers are already running — it lands in the dev console's **Invite Only** tab and each invited broadcaster must explicitly (re)install it from there. There is no propagation delay to wait out; "uploaded but not visible" almost always means it hasn't been installed on that surface yet, not that Twitch is still processing it.

---

## Joining and soft accounts

- **Join:** the panel's **Join Kana Cards** calls `Twitch.ext.actions.requestIdShare()` (Twitch's own consent dialog) and `POST /twitch/join`. The EBS creates a `users` row with `account_type="twitch"`, `twitch_user_id` = the opaque id and no username, email or password. Logged-out viewers (`A…` ids) get 403 `twitch_login_required`; the panel shows "Log in to Twitch to join".
- **Identity share:** when the viewer agrees, the JWT carries `user_id`, stored in `users.twitch_account_id` (unique, never overwritten).
- **Website accounts (#160):** a player connects Twitch on the website's Profile with Twitch sign-in ([Twitch Account Connection](../reference/twitch-account-connection.md)). The panel looks the caller up by opaque id first, then by `twitch_account_id` = the JWT's `user_id`, and acts as that website account (its opaque id is attached; drops reach it). A soft account that played first keeps playing until its collection is merged on the website. A website account linked with a code before 1.2.0 is still recognised by `twitch_user_id`.
- **Link codes:** retired. The panel has no code field (since #157), and `POST /twitch/link-code`, `POST /twitch/link` and `GET /twitch/status` were removed in #160 (404).
- **Hidden:** soft accounts never appear on leaderboards, season standings, archives, tag lists or public profiles; admins see them under User Management › Twitch viewers.
- **Leave and retention:** Settings › **Leave Kana Cards** deletes a soft account with all its data (a website account is only unlinked; its Twitch connection stays until Disconnect on Profile); soft accounts idle for `TWITCH_SOFT_ACCOUNT_RETENTION_DAYS` (365) are purged daily.

---

## Broadcaster Quick Actions (live_config.html)

The Live Config view (Twitch Stream Manager → Quick Actions) has one flow: **MVP selection + token drop**.

### Flow

1. Broadcaster clicks **"Select match MVP"**. On a channel the league hasn't approved
   (`mvp_allowed: false`, issue #175) the tool shows "This channel is waiting for the league's
   approval to set match MVPs." (or, once rejected, "This channel isn't approved to set match
   MVPs.") instead of the list, and the channel appears under **Approved streamers → Waiting for
   approval** in the admin portal (see [Approved Streamers Admin](../reference/approved-streamers-admin.md))
2. The 5 most recently played series (regardless of week boundaries) are listed. A match appears
   about a minute after it goes live (Steam's live league list, checked every
   `LIVE_POLL_INTERVAL` seconds), before its stats are ingested. Above the list, a line says
   "Live games checked N s ago" (or "N min ago"), with a **Refresh** button that reloads the
   list. When the last check is over 5 minutes old, there has been none, or `STEAM_API_KEY` is
   not set, the line instead reads "Live games not checked recently — your match will appear
   once its stats are in" in amber (see `reference/mvp-selection-delays.md`)
3. Broadcaster selects the series (team1 vs team2), then the specific match (Match 1, Match 2…).
   A match without ingested stats is marked **Live** while the game runs, otherwise
   **Stats pending**
4. Player grid is shown; broadcaster selects the MVP and clicks **"Confirm MVP & Drop Tokens"**.
   Tiles of a Live / Stats pending match show the team name without points. Under the confirm bar
   a line shows the exact start of the chat message, "Chat will say: "Match MVP: {chat_name}!"",
   using the cleaned name (issue #166)
5. MVP is saved; tokens drop automatically to the presence pool. On a Live / Stats pending match
   the banner adds that the fantasy bonus is applied when the stats arrive (see
   `reference/early-mvp-selection.md`)

### Token drop rules
- Fires on MVP confirmation — no separate trigger
- **Once per match**: re-confirming a different MVP for the same match does not re-drop tokens
- Up to `TWITCH_DROP_MAX` (default 20) random joined viewers (soft accounts and website accounts the panel recognises) from the pool receive +1 token
- **Account age (#171):** a soft account is in the pool only once it is `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` old (default 24; `0` turns it off), so alts made during a broadcast can't farm it. Website accounts are always eligible. See [Twitch Panel Abuse Limits](../reference/twitch-panel-abuse-limits.md)
- Each drop is audited as `twitch_token_drop` with `count`, `pool_size`, `excluded_new` and, for a pool more than three times the channel's recent median, `pool_spike=true` (also logged as a warning)
- `TWITCH_DROPS_ENABLED=false` turns drops off: the MVP and the fantasy bonus are still set
- Result broadcast via Twitch PubSub with the winner count only — all open panels show the MVP, and joined panels refresh their balance and show "+1 token from the MVP drop" when it went up
- The confirmation banner shows how many viewers received a token, not their names

---

## Viewer Panel (panel.html)

A 318 × 500 panel styled with the Kanaliiga design system. Full description: [Twitch Extension Policy Compliance](../reference/twitch-extension-policy-compliance.md#panel-318--500).

1. Reads the EBS URL from `Twitch.ext.configuration.global.content` at startup
2. Opens on the **Live** tab for every viewer: latest MVPs (`GET /twitch/matches/current`, with `(live)` markers), top performers and the next match (`GET /twitch/panel`); refreshed every 60 s and on an MVP PubSub message
3. Calls `GET /twitch/me`: not joined shows the Join box (or "Log in to Twitch to join"); joined shows the token count, the Cards tab (draw, team draw picker, card reveal, collection with rarity filters) and the Roster tab (slot-first bench picker, lock countdown, week points). While a new soft account is too young for drops, the Live tab says "Drops start for your account on <date>." (`drops_from`)
4. Settings: share the Twitch identity, Leave Kana Cards
5. A section the EBS can't fill shows a short neutral message; a missing EBS URL after 8 seconds shows "Kana Cards is not available on this channel right now." — never a blank panel or a login prompt

---

## Presence Pool

Joined viewers' panels call `POST /twitch/heartbeat` every ~55 seconds while open (viewers who haven't joined send none). The EBS ignores heartbeats from logged-out viewers (opaque ids not starting with `U`): it answers `{"ok": true}` and writes nothing (#171). Only viewers with an account (soft, or a website account the panel recognises) and a heartbeat within the last 10 minutes are eligible for drops, and a soft account must also be `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` old.

---

## Twitch PubSub

On MVP confirmation the EBS calls:
```
POST https://api.twitch.tv/helix/extensions/pubsub
```
with an `external`-role JWT signed by `TWITCH_EXTENSION_SECRET` (same role as the chat announcement below — extensions never hold the `broadcaster` role, which is reserved for incoming JWTs Twitch issues to the broadcaster's own client). When `TWITCH_LOCAL_DEV=true` the HTTP call is skipped and the message is printed to the server log.

---

## Twitch Extension Chat

On the same MVP confirmation, the EBS also posts a plain-text announcement directly to the
channel's Twitch chat (visible to every viewer, not just those with the extension panel
open):
```
POST https://api.twitch.tv/helix/extensions/chat?broadcaster_id={channel_id}
```
with an extension-signed JWT (`role: external`, `user_id` and `channel_id` both set to the
broadcaster's channel; Twitch rejects the call if `broadcaster_id` differs from `channel_id`)
— no bot account is required. The JSON body carries the three fields Twitch requires:

| Field | Value |
|---|---|
| `text` | The announcement, kept within 280 characters (see below) |
| `extension_id` | `TWITCH_EXTENSION_CLIENT_ID` |
| `extension_version` | `TWITCH_EXTENSION_VERSION`, the version installed on the channel |

Message text (built by `_mvp_chat_text` in `backend/twitch.py`) names the MVP and only how many
viewers received a token, never their names (issue #157: soft accounts have no username, and a
linked player's website username is not revealed in chat):
`"Match MVP: {player_name}! {N} viewers received a token."` ("1 viewer" for one), or
`"Match MVP: {player_name}! No tokens were dropped: no eligible viewers were watching."` when the
pool was empty. A re-selection on a match that already dropped, or a confirmation with
`TWITCH_DROPS_ENABLED=false`, posts just `"Match MVP: {player_name}!"`. The text is cut at
Twitch's **280-character** limit.

`{player_name}` is the cleaned name from `chat_safe_name` (issue #166): players choose their own
Dota/Steam names, so control, zero-width and bidi characters are removed, the name is cut to 32
characters, and a name that looks like a link (`://`, `www.`, or a dot followed by letters such as
`.gg`) becomes `Player {account_id}`. The PubSub message carries the same name, and
`GET /twitch/matches/current` returns it per player as `chat_name`, which the MVP picker shows as
"Chat will say: …" before the broadcaster confirms.

Twitch also allows **12 messages per minute per channel**; one MVP confirmation sends one message.

Requires the **Chat** capability to be enabled on the installed extension version in the
Twitch developer console (Extension Settings → Capabilities), in addition to the
Configuration Service setup in Step 2 below.

Chat is best-effort: `POST /twitch/mvp` never fails because of it, and the MVP, bonus and
token drop are saved before the call. The call is skipped (logged instead) when
`TWITCH_LOCAL_DEV=true`, skipped silently if `TWITCH_EXTENSION_SECRET`/`TWITCH_EXTENSION_CLIENT_ID`
are unset, and skipped with one warning per process
(`Twitch chat skipped: TWITCH_EXTENSION_VERSION is not set`) when `TWITCH_EXTENSION_VERSION`
is unset. A response other than 2xx logs `Twitch chat failed: <status> <body>` (PubSub:
`Twitch PubSub broadcast failed: <status> <body>`), with Twitch's response body truncated to
300 characters; the JWT is never logged. Timeouts and connection errors are logged with a
traceback.

### Troubleshooting

| Twitch status | Likely cause |
|---|---|
| 400 | Missing field or message too long |
| 401 | JWT or client ID wrong, or `broadcaster_id` ≠ `channel_id` |
| 403 | Chat capability not enabled on that version, or the extension isn't activated on the channel |
| 429 | More than 12 messages per minute on the channel |

---

## Local Development

The `twitch-extension/` folder is served by the backend at `/twitch-ext` when present. The dev harness at `http://localhost:8000/twitch-ext/dev-harness.html` simulates the extension panel without a real Twitch session. It is not uploaded to Twitch CDN.

The dev harness is same-origin with the backend, so it needs no CORS entry. `/twitch/*` routes are exempt from the cross-origin Origin check (`reference/security-audit-3.md`) because they authenticate with the Twitch JWT, not the session cookie. `POST /twitch/merge/confirm` and `POST /twitch/disconnect` (#160) are the exceptions: they use the session cookie (called from the main site's Profile tab), so they get the Origin check like other cookie routes (`_COOKIE_AUTH_TWITCH_PATHS` in `main.py`).

---

## Endpoints

### Panel game endpoints (issue #157)
`GET /twitch/panel`, `POST /twitch/join`, `GET /twitch/me`, `POST /twitch/draw`, `GET /twitch/teams`,
`POST /twitch/draw/booster/{team_id}`, `POST /twitch/roster/activate/{card_id}`,
`POST /twitch/roster/deactivate/{card_id}`, `POST /twitch/roster/swap`, `POST /twitch/leave`. All take
the Twitch JWT; the game routes answer 404 `not_joined` without an account and run the website's
own card functions for the caller's account. Shapes, limits and errors:
[Twitch Extension Policy Compliance](../reference/twitch-extension-policy-compliance.md#live-tab-and-game-endpoints).

### Website Twitch connection (issue #160)
`GET /auth/twitch/start`, `GET /auth/twitch/callback`, `GET /twitch/connection`,
`POST /twitch/merge/confirm`, `POST /twitch/disconnect` use the website session (not a Twitch JWT)
and live in `backend/twitch_oauth.py`; admin `GET /admin/twitch/merges` and
`POST /admin/twitch/merges/{log_id}/reverse` in `routers/admin_twitch.py`. See
[Twitch Account Connection](../reference/twitch-account-connection.md).

### Approved streamers (issue #175)
Admin `GET /admin/twitch/channels` and `POST /admin/twitch/channels/{channel_id}/approve|reject|remove`
(the three actions need a recent password check) in `routers/admin_twitch.py`, logic in
`backend/twitch_channels.py`. See [Approved Streamers Admin](../reference/approved-streamers-admin.md).

### Retired: `POST /twitch/link-code`, `POST /twitch/link`, `GET /twitch/status`
Removed in #160 and answer 404. The 6-character link code (#135 drew it with `secrets` and
rate-limited `POST /twitch/link`) is replaced by Twitch sign-in; `GET /twitch/status` by
`GET /twitch/me`. The `twitch_link_codes` table and the `TwitchLinkCode` model remain for a later clean-up migration; only `soft_accounts.delete_soft_account` still deletes its rows, and no route reads or writes it.

### `POST /twitch/heartbeat`
Twitch JWT. Records viewer presence (upserts `twitch_presence`). Call every ~55 seconds. A logged-out viewer's heartbeat returns `{"ok": true}` without writing. Rate-limited per viewer (`RATE_LIMIT_TWITCH_ACTION`) and per IP (`RATE_LIMIT_TWITCH_JOIN_IP`).

### `GET /twitch/matches/current`
Twitch JWT. Returns the 5 most-recently-played series (team-pair groups) with ingested match
data, regardless of week boundaries, with per-match player lists. Games seen live (Steam's live
league list since #161) but not yet ingested are included with `"provisional": true` and a `live` flag (issue
#139). The response also carries `live_checked_at` and `live_source_configured`, which the MVP
picker uses for its freshness line (see `reference/mvp-selection-delays.md`), and `mvp_allowed` /
`approval` (`approved`, `pending`, `rejected`) for the token's channel (issue #175). A broadcaster
on a channel that may not set MVPs gets an empty `series` list and leaves a pending approval
request; viewers still get the series. See `reference/approved-streamers-admin.md`. See `reference/twitch-mvp-series-window.md` and `reference/early-mvp-selection.md`. The series selection lives in
`twitch._current_series()`; `POST /twitch/mvp` checks eligibility against the same helper.

### `POST /twitch/mvp` *(broadcaster only)*
Twitch JWT (broadcaster role). Body: `{match_id, player_id}`.

Before anything is written (MVP row, score bonus, token drop, audit entry), the request must
pass these checks in order (issue #135):

| Check | Failure |
|---|---|
| The calling channel is in `TWITCH_MVP_CHANNEL_IDS` or approved in the admin portal (checked first, so other channels learn nothing about IDs; a refused broadcaster leaves an approval request, issue #175). With both lists empty any channel may outside production, and no channel with `ENV=production` (issue #165) | 403 |
| The match exists: an ingested match or a stored live match (`live_matches`) | 404 `Match not found` |
| The match is one `GET /twitch/matches/current` offers: started, has ingested stats or is a stored live match, and belongs to one of the 5 most recent series (`twitch._eligible_mvp_match_ids()`) | 403 |
| The player has a stat row for that match, or for a provisional match is one of its stored live players | 404 `Player did not play in this match` |

Without these checks any channel with the extension installed could mint token drops and change
scores for arbitrary match IDs. The admin MVP endpoint (`POST /admin/matches/{match_id}/mvp`)
is not restricted to the series window.

On a provisional match (no stats yet) no score bonus is applied at confirm time; ingest applies
it when the match arrives (`ingest._reapply_mvp_bonus`), and the audit detail carries
`provisional=True`. The player's display name is the known `players` name, else the live feed
name, else `Player {account_id}`.

On success it upserts the MVP, triggers one-time token drop (skipped if match already dropped), broadcasts via PubSub, and posts a chat announcement (see Twitch Extension Chat below). Also busts the schedule cache so the new MVP appears on the Schedule tab immediately — see `reference/mvp-schedule-cache-bust.md`. Returns `{match_id, player_id, player_name, token_drop: {enabled, winner_count, pool_size, already_dropped}}`. No winner names are returned (a website-account winner's name is their username); chat and PubSub carry the count, and the names stay in the admin-only audit log.

---

## Database Tables

| Table | Purpose |
|---|---|
| `twitch_link_codes` | Retired 6-char link codes (#160). The table and `TwitchLinkCode` model remain until a clean-up migration; only `soft_accounts.delete_soft_account` still deletes its rows, and no route reads or writes it |
| `twitch_oauth_states` | Twitch sign-in attempts (#160): sha256(state), nonce, PKCE verifier, 10-minute expiry, one-time |
| `twitch_merge_log` | Soft-account merge undo log (#160), kept 30 days for admin reversal |
| `twitch_presence` | Viewer heartbeat timestamps for pool eligibility |
| `twitch_mvp` | One MVP selection per match, broadcaster-updatable. Unique on `match_id`; both MVP paths write through `twitch.upsert_mvp()` (`INSERT ... ON CONFLICT DO UPDATE`), so simultaneous confirmations update one row |
| `live_matches` | Monitored-league games seen in Steam's live league list (OpenDota's `/live` before #161), kept until their stats are ingested (or 24 h after last seen) so the MVP panel can offer them early. See `reference/early-mvp-selection.md` |
| `match_timings` | Per match: when it was first seen live, ingested and given its first MVP (`mvp_provisional` when before ingest). Shown in the admin Matches table. See `reference/mvp-selection-delays.md` |
| `twitch_token_drops` | Once-per-match drop records; prevents duplicate drops. Its dedup key column is named `series_id` for historical reasons but actually stores a **match ID** (`str(match_id)`) — see the dedup note above. Unique on `(channel_id, series_id)`: `_claim_drop()` inserts this row (`ON CONFLICT DO NOTHING`) before any tokens are granted, and only the request whose insert lands pays out, so two simultaneous confirmations cannot drop twice. Migration `026_twitch_mvp_drop_unique` removed pre-existing duplicates and added both unique indexes. |

`users.twitch_user_id` stores the Twitch opaque user ID of a soft account or a website account the panel recognises. `users.account_type` (`full` / `twitch`), `users.last_seen_at` and `users.twitch_account_id` (real Twitch id after the identity share or Twitch sign-in, unique) were added by migration `031_users_twitch_soft_accounts`; `users.merged_soft_account_at` and `users.pending_merge_user_id` by `032_users_merged_soft_account_at` (#160).

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_EXTENSION_CLIENT_ID` | *(empty)* | Client ID from Extension Settings (top-right corner). Also the only `ext-twitch.tv` origin CORS allows; unset, no extension origin is allowed (#171) |
| `TWITCH_EXTENSION_SECRET` | *(empty)* | Base64 key from Extension Secrets table (bottom of Extension Settings). Not the Twitch API Client Secret. |
| `TWITCH_EXTENSION_VERSION` | *(empty)* | Extension version installed on the channel, e.g. `1.2.0`. Required for chat announcements (sent as `extension_version`); chat is skipped with one warning when empty. Must have the Chat capability enabled. |
| `TWITCH_DROP_MAX` | `20` | Max viewers per token drop |
| `TWITCH_DROPS_ENABLED` | `true` | Kill switch for MVP token drops; `false` sets the MVP and bonus only |
| `TWITCH_SOFT_ACCOUNT_RETENTION_DAYS` | `365` | Days without activity before a soft account is purged by the daily job |
| `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` | `24` | Hours before a new soft account is in drop pools; `0` turns the rule off. Website accounts are always eligible (#171) |
| `LOGO_HOST_ALLOWLIST` | Steam CDN hosts | Comma-separated hosts a team logo URL may use (stored at ingest, returned, or fetched for card images); empty means the default list (#171) |
| `RATE_LIMIT_TWITCH_JOIN` / `RATE_LIMIT_TWITCH_JOIN_IP` / `RATE_LIMIT_TWITCH_ACTION` | `10/minute` / `60/minute` / `30/minute` | Join per viewer; Join, draws and heartbeats per IP; draws, heartbeats, roster changes and Leave per viewer |
| `STEAM_API_KEY` | *(empty)* | Steam Web API key; required for listing live games in the MVP picker before their stats are ingested (see [MVP Selection Delays](../reference/mvp-selection-delays.md)) |
| `LIVE_POLL_INTERVAL` | `60` | Seconds between live-game checks |
| `TWITCH_MVP_CHANNEL_IDS` | *(empty)* | Comma-separated Twitch channel IDs always allowed to set match MVPs (and so trigger token drops), in addition to channels approved in the admin portal (issue #175); others get 403. Both empty: no channel with `ENV=production` (a start-up warning is logged), any channel otherwise (issue #165) |
| `TWITCH_OAUTH_CLIENT_ID` / `TWITCH_OAUTH_CLIENT_SECRET` / `TWITCH_OAUTH_REDIRECT_URI` | *(empty)* | Twitch sign-in for Connect Twitch on Profile (#160); any missing turns it off. See [Twitch Account Connection](../reference/twitch-account-connection.md#configuration) |
| `RATE_LIMIT_TWITCH_OAUTH` | `10/minute` | Per-IP limit on each of `GET /auth/twitch/start` and `/auth/twitch/callback` |
| `TWITCH_LOCAL_DEV` | *(unset)* | `true` bypasses JWT validation, and logs PubSub and chat messages instead of calling Twitch. Never set in production. |
| `CORS_EXTRA_ORIGINS` | *(empty)* | Extra comma-separated CORS origins on top of `https://<TWITCH_EXTENSION_CLIENT_ID>.ext-twitch.tv`; `http://localhost:8080` for Local Test |
| `ENV` | *(unset)* | Set `production` in production. Startup then refuses `TWITCH_LOCAL_DEV=true` (and `DEBUG=true`, or a `SECRET_KEY` under 32 characters). As a second line of defence the JWT bypass also refuses to run (500). |

---

## Notes

- Twitch does not expose a live viewer list — the drop pool is built from heartbeat calls only.
- PubSub is EBS→panel only; the extension cannot send messages to other viewers. The chat
  announcement is the one channel that reaches everyone watching, not just panel viewers.
- MVP selection **does** have a scoring impact — not engagement/drops only. The confirmed MVP's
  `player_match_stats.fantasy_points` for that match is multiplied by `1 + mvp_bonus_pct / 100`
  (default 10%), which is visible on the player's own match history and in the
  player-performance leaderboard/Top Single-Match Performances. It does **not** currently reach
  card, roster, weekly-leaderboard, or season-leaderboard totals — those recompute from raw
  stats independently and have no MVP term. See `reference/mvp-fantasy-bonus.md`.
- The extension must pass Twitch review before public release, or be used in developer test mode.
- Token drop deduplication is keyed on `(channel_id, match_id)` — once dropped for a match on a
  given channel, it will not drop again even if the broadcaster re-confirms a different MVP.
