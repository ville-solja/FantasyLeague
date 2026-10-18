# Twitch Extension Setup Follow-ups

Fixes for silent failures found while setting up the test extension. Twitch sign-in errors show on Profile, the demo clock is requested only by admins, and the admin Twitch status lists the sign-in redirect URL and the image hosts. Also covered: the panel's live data is cached and rate-limited, and frontend files are revalidated after each deploy.

---

## Twitch sign-in errors

When Twitch refuses a sign-in before our callback runs, for example with `redirect_mismatch` (the callback URL isn't registered), it sends the browser to a URL it does have registered, with `?error=<code>&error_description=…&state=…`. `handleTwitchErrorReturn()` in `frontend/app-profile.js` handles it; `init()` (`app-init.js`) runs it after `_handleResetTokenParam()` and `handleSteamReturn()`, and before `handleTwitchReturn()`.

- It acts only when both `error` and `state` are in the query; otherwise it returns `false` and changes nothing.
- It removes `error`, `error_description`, `error_uri` and `state` from the address bar with `history.replaceState`, keeping any other parameter and the hash.
- Logged out, it stops there: no message and no login prompt.
- Logged in, it opens Profile and writes a message to the Twitch section (`#twitchStatus`, via `setStatus`, which uses `textContent`):
  - `redirect_mismatch`: "Twitch sign-in failed: this site's Twitch redirect URL isn't registered with Twitch. Tell the league admins."
  - `access_denied`: "Twitch sign-in was cancelled. Nothing was changed."
  - anything else: "Twitch sign-in did not complete. Nothing was changed. Try again. (`<code>`)"

Only the code, checked against `[a-z_]{1,64}` (otherwise `unknown`), is shown; Twitch's `error_description` never is.

## Demo clock

`renderDemoModePanel()` (`frontend/app-admin-demo.js`) renders the Demo Mode panel, and `loadDemoClock()` requests `GET /admin/demo/clock`, only when `window.demoMode && activeIsAdmin`; for anyone else the container is emptied. The panel is rendered from `applyAuthState()` (`app-auth.js`), which runs after `loadMe()` on page load and after every login or logout, no longer from `loadConfig()`. Non-admins and logged-out visitors make no `/admin/demo/*` request.

## Twitch console checklist

`GET /admin/twitch/status` → `console` (`twitch_status._console()`) adds two entries:
- **OAuth Redirect URL**: "Extension Settings › Twitch API Client Configuration › OAuth Redirect URL has this exact entry (click Add, then Save Changes)", `expected` = `TWITCH_OAUTH_REDIRECT_URI`. Listed only when all three `TWITCH_OAUTH_*` are set.
- **Allowlist for Image Domains**: "Version › Capabilities › Allowlist for Image Domains contains the team logo hosts", `expected` = the `https://` origins of `logo_hosts.logo_hosts()`, sorted and comma-separated.

The `connect_twitch` check's detail (ok, and the partly-set warning) names the client secret's source: the **Twitch API Client Secret** of the application or extension whose Client ID is `TWITCH_OAUTH_CLIENT_ID`, never the Extension Secret. No secret, token or secret length is added. The admin UI lists `console` generically, so the new rows appear in Admin › Twitch › Twitch status without a frontend change.

## Panel live data cache

`GET /twitch/panel` is served by `twitch.panel_live_route`, which calls `cached_panel_live(payload, db)`:
- The body of `panel_live()` (public data only: top performers and next match) is kept in memory, shared by all viewers, for `TWITCH_PANEL_CACHE_SECONDS` (read per call; `0` turns the cache off; not a number, negative or infinite means 30). Per process, like the rate limits.
- `twitch.bust_panel_cache()` clears it. It runs after `ingest.ingest_match()` stores a match, after `ingest.refresh_match_stats()` replaces a match's stats, in `set_mvp` (Twitch MVP), and in the admin MVP and match-status routes (`routers/admin_matches.py`) next to `schedule.bust_cache()`. A generation counter keeps a body computed before a bust from being stored after it.
- Limits: `RATE_LIMIT_TWITCH_ACTION` per viewer (`key_by_twitch_viewer_or_ip`) and `RATE_LIMIT_TWITCH_JOIN_IP` per IP, as on the other panel routes.
- `twitch.panel_live(payload, db)` stays uncached and directly callable.

The response body is unchanged.

## Frontend caching

The `/` mount in `backend/main.py` uses `_FrontendStaticFiles`, a `StaticFiles` subclass that adds `Cache-Control: no-cache` to responses for `.html`, `.js` and `.css` files and for paths without an extension (`/`, which serves `index.html`). Browsers then revalidate with the existing `ETag` / `Last-Modified` and get `304` when nothing changed, so a deploy is picked up on the next page load. Fonts, images, `/assets/*` and `/twitch-ext/*` keep the default headers.

## Endpoints

### `GET /twitch/panel`
Twitch JWT. Cached for `TWITCH_PANEL_CACHE_SECONDS`; limited by `RATE_LIMIT_TWITCH_ACTION` per viewer and `RATE_LIMIT_TWITCH_JOIN_IP` per IP (429 past either).

### `GET /admin/twitch/status`
Admin. Two more `console` entries; no secrets.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_PANEL_CACHE_SECONDS` | `30` | Seconds the panel's live data is cached; `0` turns the cache off; an invalid value means 30 |

## Setup notes (working configuration, 2026-10)

- **Connect Twitch** uses the extension's own Client ID. Set it as `TWITCH_OAUTH_CLIENT_ID`, with the extension's **Twitch API Client Secret** as `TWITCH_OAUTH_CLIENT_SECRET`. Register `https://<host>/auth/twitch/callback` under **OAuth Redirect URL**, click **Add**, then **Save Changes**; it takes up to 10 URLs, so test and production share the client.
- **`TWITCH_EXTENSION_SECRET`** is the base64 key from **Extension Secrets**. The API Client Secret in its place gives `E-TOKEN`.
- **`TWITCH_EXTENSION_CLIENT_ID`** unset on the server gives `E-REACH`: CORS refuses every extension origin.
- **Allowlist for Image Domains** empty: team logos in the panel fall back to initials.
- **Capability fields** (URL Fetching Domains, Image Domains, Chat) are editable only while the version is in Local Test.

Operator steps: `markdown/features/core/twitch-extension.md` (Prerequisites, Step 3, Panel reason codes) and `markdown/features/reference/twitch-integration-status.md` (Troubleshooting).
