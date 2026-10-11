# Plan: Twitch Extension Setup Follow-ups

## Context
Setting up the test extension (1.2.1 on test.kana-cards.com, 2026-10-08 to 10-11) surfaced problems that cost hours, because each one failed silently:
- the panel reported `E-REACH` until `TWITCH_EXTENSION_CLIENT_ID` was set for CORS;
- it reported `E-TOKEN` while the Twitch API Client Secret sat where the Extension Secret belongs;
- Connect Twitch went through Steam and stopped, which is fixed in PR #183: the Steam confirmation now resumes Connect Twitch;
- Connect Twitch then landed on the leaderboard with no message. Twitch answered `redirect_mismatch` because the callback URL was typed into the extension's OAuth Redirect URL list without clicking **Add**, so Twitch sent the browser to the site root (`/?error=redirect_mismatch&…`), which the page ignores;
- team logos in the panel fall back to initials, because the version's Image Domains allowlist is empty;
- the console showed `GET /admin/demo/clock 403` on every page load for non-admins in demo mode.

This plan makes these failures visible and writes the working setup into the docs. It also takes two improvements raised alongside: the `/systems-architect` review's top finding, that `GET /twitch/panel` is uncached, unthrottled and polled by every open panel; and the frontend files being served without `Cache-Control`, so browsers may run stale scripts after a deploy. The extension's own Client ID is the supported Connect Twitch client: the Extension Settings page accepts up to 10 OAuth redirect URLs, so test and production share it. Assumption: the panel cache is per process and in memory, matching the single-process design (`markdown/features/reference/rate-limiting.md`).

## User Stories

### See Why Twitch Sign-in Failed
**User story**
As a player connecting Twitch, I want to see a message when Twitch refuses the sign-in so that I know it failed and what to tell the league, instead of landing on the leaderboard with nothing changed.

**Acceptance criteria**
- When the page loads with `?error=` and `state=` in its query (Twitch's error return, which lands on whichever redirect URL Twitch has registered), a logged-in player is taken to Profile and the Twitch section shows a message
- `redirect_mismatch` shows "Twitch sign-in failed: this site's Twitch redirect URL isn't registered with Twitch. Tell the league admins."; `access_denied` shows the existing "cancelled" message; any other code shows "Twitch sign-in did not complete. Nothing was changed. Try again." followed by the code
- Twitch's `error_description` is never inserted as HTML; only the error code, matched against `[a-z_]{1,64}`, appears in the text
- The `error`, `error_description` and `state` parameters are removed from the address bar; any other query parameter (for example `reset_token`) keeps its current handling
- Logged out, the parameters are removed and the login prompt is not opened

### Demo Clock Only for Admins
**User story**
As a player on a demo-mode server, I want the page to load without admin-only requests so that the browser console shows no 403 noise that hides real errors.

**Acceptance criteria**
- With demo mode on, `GET /admin/demo/clock` is requested only when the logged-in user is an admin
- The Demo Mode panel still renders in the admin tab for admins and loads the clock there
- For non-admins and logged-out visitors no `/admin/demo/*` request is made on page load

### Twitch Console Checklist Covers Sign-in and Images
**User story**
As the operator, I want the admin Twitch status page to list every Twitch console value that has to match this server so that I can check the redirect URL and the image allowlist without reading code.

**Acceptance criteria**
- The `console` list of `GET /admin/twitch/status` adds: "Extension Settings › Twitch API Client Configuration › OAuth Redirect URL has this exact entry (click **Add**, then **Save Changes**)" with the `TWITCH_OAUTH_REDIRECT_URI` value as expected, shown only when Connect Twitch is configured
- It adds "Version › Capabilities › Allowlist for Image Domains contains the team logo hosts", with the `https://` origins of `logo_hosts()` as expected
- The `connect_twitch` check's detail names where the client secret comes from: the **Twitch API Client Secret** of the application or extension whose Client ID is `TWITCH_OAUTH_CLIENT_ID`, never the Extension Secret
- No secret, token or secret length is added to the response

### Panel Live Data Under Audience Load
**User story**
As the operator, I want the Twitch panel's live data served from a short cache so that a stream with hundreds of open panels doesn't turn into hundreds of identical database queries a minute.

**Acceptance criteria**
- `GET /twitch/panel` returns a cached body for up to `TWITCH_PANEL_CACHE_SECONDS` (default 30; `0` turns the cache off), shared by all viewers, because the response holds public data only
- The cache is cleared when ingest stores new matches and when an MVP is confirmed, so a new MVP or result appears on the next poll
- The route gets the per-viewer and per-IP limits the other panel routes use (`RATE_LIMIT_TWITCH_ACTION` keyed by `key_by_twitch_viewer_or_ip`, `RATE_LIMIT_TWITCH_JOIN_IP` per IP)
- The response body is unchanged

### Fresh Scripts After a Deploy
**User story**
As a player, I want the site to pick up a new release on my next page load so that I never run a mix of old and new scripts.

**Acceptance criteria**
- Responses for the frontend's `.html`, `.js` and `.css` files carry `Cache-Control: no-cache`, so browsers revalidate with the existing `ETag` and get a `304` when nothing changed
- Images, fonts and `/assets/*` keep their current caching
- `/twitch-ext/*` (local dev harness) is unaffected

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-profile.js` | `handleTwitchErrorReturn()`: reads `?error=&state=`, maps the code, opens Profile, strips the parameters |
| `frontend/app-init.js` | Call the new handler next to `handleSteamReturn()` / `handleTwitchReturn()` |
| `frontend/app-globals.js` | `renderDemoModePanel()` no longer called from `loadConfig` for everyone |
| `frontend/app-admin-demo.js` | Render the panel and call `loadDemoClock()` only when `activeIsAdmin` |
| `backend/twitch_status.py` | Two new `_console()` entries; clearer `connect_twitch` detail |
| `backend/twitch.py` | In-memory cache for `panel_live`, `bust_panel_cache()`, rate limits on `/twitch/panel` |
| `backend/ingest.py`, `backend/twitch.py` (`set_mvp`) | Call `bust_panel_cache()` where `schedule.bust_cache()` is already called |
| `backend/main.py` | `Cache-Control: no-cache` for frontend `.html`/`.js`/`.css` responses (small middleware or a `StaticFiles` subclass) |
| `.env.example` | `TWITCH_PANEL_CACHE_SECONDS` |
| `markdown/features/core/twitch-extension.md` | Console prerequisites and env steps (Step 7) |
| `markdown/features/reference/twitch-account-connection.md` | Extension client as the sign-in client; error return |
| `markdown/features/reference/twitch-integration-status.md` | New console entries; troubleshooting rows |
| `markdown/ui_description/profile.md`, `markdown/ui_description/admin.md` | Error message; demo panel admin-only |
| `backend/tests/test_twitch_extension_setup_followups.py` | New tests |

### Step 1 — Twitch error return on Profile
In `app-profile.js`, add `handleTwitchErrorReturn()`:
```js
const _TWITCH_ERROR_MESSAGES = {
  redirect_mismatch: "Twitch sign-in failed: this site's Twitch redirect URL isn't registered with Twitch. Tell the league admins.",
  access_denied: _TWITCH_RETURN_MESSAGES.cancelled[0],
};
function handleTwitchErrorReturn() {
  const q = new URLSearchParams(window.location.search);
  if (!q.has("error") || !q.has("state")) return false;
  const raw = q.get("error") || "";
  const code = /^[a-z_]{1,64}$/.test(raw) ? raw : "unknown";
  history.replaceState(null, "", window.location.pathname);
  if (!activeUserId) return true;
  switchTab("profile");
  setStatus("twitchStatus", _TWITCH_ERROR_MESSAGES[code] ||
    `Twitch sign-in did not complete. Nothing was changed. Try again. (${code})`, false);
  return true;
}
```
In `init()` (app-init.js): `if (!handleSteamReturn() && !handleTwitchErrorReturn()) handleTwitchReturn();`. `_handleResetTokenParam()` runs first and only acts on `reset_token`.

### Step 2 — Demo clock for admins only
Move the `renderDemoModePanel()` call out of `loadConfig()` to after `loadMe()` / `applyAuthState()`, and guard it: render and load the clock only when `window.demoMode && activeIsAdmin`. Keep the empty-container branch for everyone else.

### Step 3 — Console checklist
In `twitch_status._console()` append:
```python
{"label": "Extension Settings › Twitch API Client Configuration › OAuth Redirect URL has this exact entry "
          "(click Add, then Save Changes)",
 "expected": redirect_uri}   # only when all three TWITCH_OAUTH_* are set
{"label": "Version › Capabilities › Allowlist for Image Domains contains the team logo hosts",
 "expected": ", ".join(f"https://{h}" for h in logo_hosts.logo_hosts())}
```
Update the `connect_twitch` ok/warning detail text to name the Twitch API Client Secret. Render the new entries in the existing Admin › Users › Twitch status block (no frontend change expected; it lists `console` generically — confirm).

### Step 4 — Panel cache and limits
In `twitch.py`, keep `_panel_cache = {"at": 0, "body": None}` behind a lock; `panel_live` returns the cached body when younger than `TWITCH_PANEL_CACHE_SECONDS` (read per call, invalid → 30). `bust_panel_cache()` clears it; call it where `bust_cache()` is called after ingest and from `set_mvp`. Add `@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)` and the per-IP limit, following `heartbeat_route`. The route needs `request: Request` in its signature for slowapi.

### Step 5 — No-cache for frontend files
Add `Cache-Control: no-cache` to responses from the `/` `StaticFiles` mount when the path ends in `.html`, `.js`, `.css` or is `/`. `StaticFiles` already sends `ETag` and `Last-Modified`, so revalidation answers `304`.

### Step 6 — Tests
`backend/tests/test_twitch_extension_setup_followups.py`:
- static checks on `app-profile.js` / `app-init.js` for the error handler (code allowlist, `textContent`/`setStatus` only, parameters stripped, called in `init`);
- static check that `loadDemoClock` / `renderDemoModePanel` are gated on `activeIsAdmin`;
- `build_status` console entries with and without the `TWITCH_OAUTH_*` values, and that no secret appears;
- `/twitch/panel`: second call within the window doesn't query (count `panel_live` work or patch the query helper), `bust_panel_cache()` forces a refresh, `TWITCH_PANEL_CACHE_SECONDS=0` disables, 429 past the limit;
- `Cache-Control: no-cache` on `/`, `/app-auth.js`, `/style.css`; absent on an image.
Keep `test_issue_85_split_admin_router.py`'s suite-size check in step.

### Step 7 — Documentation
- **twitch-extension.md, Prerequisites table**, add rows:
  - **Twitch API Client Secret** (Extension Settings, mid-page): goes in `TWITCH_OAUTH_CLIENT_SECRET`, never in `TWITCH_EXTENSION_SECRET`.
  - **OAuth Redirect URL** (Twitch API Client Configuration): `https://<host>/auth/twitch/callback` for each environment, up to 10. The common mistake is typing it without clicking **Add**, or not clicking **Save Changes**; Twitch then answers `redirect_mismatch` and sends the browser to another registered URL.
  - **Allowlist for Image Domains** (per version): the Steam CDN hosts from `logo_hosts.py`.
  - A note that capability fields are editable only while the version is in **Local Test**.
- **twitch-extension.md, Step 3:** the `TWITCH_OAUTH_*` block with the extension's Client ID as `TWITCH_OAUTH_CLIENT_ID`.
- **twitch-extension.md, panel reason codes:** `E-TOKEN` gets "most often the Twitch API Client Secret pasted into `TWITCH_EXTENSION_SECRET`"; `E-REACH` gets "`TWITCH_EXTENSION_CLIENT_ID` unset on the server" first.
- **twitch-account-connection.md, Configuration:** the extension client is the default sign-in client; the error return on Profile.
- **twitch-integration-status.md:** the two console entries; a troubleshooting row "Connect Twitch lands on the leaderboard → Twitch `redirect_mismatch`".
- **twitch-panel-abuse-limits.md / rate-limiting.md:** the `/twitch/panel` limits and cache.

## Verification
- On test: temporarily remove the callback URL in the Twitch console, click Connect Twitch, and see the `redirect_mismatch` message on Profile with a clean address bar; restore the URL and connect.
- As a non-admin on test (demo mode on): no `/admin/demo/clock` request on page load; as an admin, the Demo Mode panel shows the clock.
- Admin › Users › Twitch status lists the redirect URL and image hosts.
- `curl -I https://<host>/app-auth.js` shows `Cache-Control: no-cache`; a second request with `If-None-Match` answers `304`.
- Panel: open several panels, confirm one database query per cache window (log or counter), and that confirming an MVP shows on the next poll.
- `cd backend && python3 -m pytest tests/ -q`.
