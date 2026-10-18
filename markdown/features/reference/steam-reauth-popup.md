# Steam Re-auth Without Leaving the Page

Sensitive actions ask for a recent identity check. Accounts without a password (Steam-only admins and players) already confirm through Steam (#150). Since issue #213 that Steam check runs in a popup, so the page and any filled-in dialog are kept and the action retries on its own. Accounts with both a password and a linked Steam account can choose either method. Plan: `markdown/plans/plan-issue-213-steam-reauth-without-leaving-the-page.md`. The rest of Steam sign-in is in `reference/steam-login.md`.

---

## How it works

1. **The action asks for a check:** a protected request answers 403 `reauth_required`, and `adminFetch` (`frontend/app-admin.js`) opens the re-auth modal.
2. **The popup opens:** **Confirm with Steam** (the only option without a password) or **Confirm with Steam instead** (under the password field, for an account with a password and a linked Steam account in a Steam login mode) calls `startSteamReauth()`. It opens `GET /auth/steam/start?purpose=reauth&return_tab=popup` with `window.open` straight from the click, in a window named `steamReauth` of 800×700.
3. **The callback confirms:** it checks the Steam id against the logged-in account (unchanged since #150), marks the same session (`sessions.mark_reauth`) and audits `admin_reauth` or `player_reauth` with `method=steam`. It then redirects to `/steam-reauth-done.html?steam=<key>`.
4. **The done page reports back:** `frontend/steam-reauth-done.js` maps the key (table below) and posts `{type: "steam-reauth", result}` to `window.opener`, targeting `location.origin`, never `*`. Then it closes the window.
5. **The page retries:** `adminFetch` accepts the message only when it comes from `location.origin`, from the popup it opened (`event.source`), with that exact shape and a known result. On `ok` the prompt resolves and `adminFetch` retries the original request once, as after a password.

| `?steam=` | Posted `result` | What the modal does |
|---|---|---|
| `reauth_ok` | `ok` | Closes; the action is retried once |
| `reauth_failed` | `reauth_failed` | Stays open: "That Steam account is not the one linked to this account. Nothing was confirmed." |
| `no_session` | `no_session` | Stays open: "Log in to Kana Cards first, then try again." |
| `not_linked` | `not_linked` | Stays open: "This account has no Steam link to confirm with." |
| anything else or missing | `failed` | Stays open: "Steam sign-in did not complete. Nothing was changed. Try again." |

The raw query value is never posted. Nothing is retried for any result other than `ok`; **Cancel** then hands the original 403 back to the caller.

### Edge cases
- **Popup closed early:** the modal polls `popup.closed` every 500 ms. After a close it waits another 500 ms for a result that may still be on its way, then counts the check as not confirmed: the modal closes and `adminFetch` returns the original 403.
- **Popup blocked:** if `window.open` returns nothing, the modal shows "Your browser blocked the Steam window" with **Continue on this page**. That runs `startSteamReauthFullPage()`, the full-page round trip from #150 (`return_tab=admin|profile`, the `reauthResume` resume for Connect Twitch), whose behaviour and messages are unchanged.
- **Steam unavailable:** `GET /config` returns `steam_reauth_available`: true only when `LOGIN_METHOD` enables Steam and `APP_BASE_URL` is set. When it is false, Confirm with Steam shows "Steam confirmation is unavailable on this server" and opens no window. The password stays available where the account has one. If the setting changes between page load and click, the popup lands on the 503 JSON. Closing it counts as not confirmed.
- **Cancel while the popup is open:** the modal closes the popup and resolves as not confirmed.
- **Connect Twitch:** `_promptReauth("connectTwitch").then(ok => ...)` resolves in place after a popup `ok`, so the page goes straight on to Twitch. `reauthResume` is used only by the full-page fallback.
- **No opener:** if the done page has no opener (opened directly, or the opener was closed), it posts nothing and asks the user to close the window and return to the site.

## Server changes (`backend/steam_openid.py`)

- `POPUP = "popup"` and `DONE_PAGE = "/steam-reauth-done.html"`. `start()` accepts `return_tab=popup` only when `purpose=reauth`; for login and link it is ignored, so `RETURN_TABS` (`profile`, `admin`) still decides the full-page targets.
- `_redirect(tab, key)` sends `tab == "popup"` to `/steam-reauth-done.html?steam=<key>`. Every redirect of a popup attempt goes there: start's `login_required` and `not_linked`, the callback's `cancelled`, `failed`, `unavailable`, `no_session`, `reauth_ok` and `reauth_failed`, and a replayed or expired popup state (`failed`). Redirects use the allowlist's own constants (`_reauth_tab`), never the request's string.
- No change to the identity check, the one-time state, the nonce check or the audit. `return_tab` was already stored on `SteamLoginState`, so there is no migration and no new env var.

## Endpoints

### `GET /auth/steam/start?purpose=reauth&return_tab=popup`
As for the other re-auth targets: needs a session and a linked Steam id, 303 to Steam with the state cookie, 503 `steam_unavailable` without `APP_BASE_URL`. Early refusals redirect to the done page (`login_required`, `not_linked`).

### `GET /config`
Adds `steam_reauth_available` (boolean): `login_mode.steam_enabled() and login_mode.app_base_url() is not None`.

### `GET /steam-reauth-done.html`, `GET /steam-reauth-done.js`
Static files from the frontend mount, with the usual security headers and `Cache-Control: no-cache`. The page has no inline script or event handlers and loads only its own script; it carries no data beyond the result.

## Tests

`backend/tests/test_issue_213_steam_reauth_without_leaving_the_page.py`: server redirects and audit (on the `web` fixture of `test_issue_150_steam_login.py`, Steam mocked), the done page under Node, and the `adminFetch` popup flow under a Node harness with fake `window.open`, `message` events and timers.

## Known limitation

**Reverse tabnabbing (accepted, Low):** the popup keeps `window.opener`, because `postMessage` and closed-window detection need it. While the popup shows steamcommunity.com, a page the user navigates to inside it could redirect the original tab (`window.opener.location`).
- **What it can't do:** it cannot read the page or forge a confirmation. A forged "ok" only makes the page retry, and the server still requires the session's recent re-auth.
- **The alternative:** a `noopener` popup plus a same-origin `BroadcastChannel`. It was set aside because the flow is short, runs through Steam's own pages and is used mostly by admins.
