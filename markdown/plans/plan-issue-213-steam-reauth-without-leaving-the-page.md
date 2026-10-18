# Plan: Steam Re-auth Without Leaving the Page

## Context
Issue #213 asks whether the admin re-auth works for an admin who signs in with Steam and has no password. **It is handled already** (issue #150):
- **The 409:** `POST /reauth` answers 409 `use_steam_reauth` for an account without a password.
- **The prompt:** `adminFetch` (`frontend/app-admin.js`) shows "Confirm with Steam" instead of the password field when `activeHasPassword` is false.
- **The round trip:** `GET /auth/steam/start?purpose=reauth&return_tab=admin` runs Steam OpenID. `steam_openid._reauth` checks that the returning Steam id is the one linked to the logged-in account, and only then marks the *same session* re-authenticated (`sessions.mark_reauth`, audited as `admin_reauth` with `method=steam`). A different Steam account is refused and audited.
- **Coverage:** every admin endpoint behind `require_recent_reauth` uses this path through `adminFetch`, as does Unlink Steam behind `require_recent_player_reauth`. That includes End Season, Reset, Mark champions, accolades, approving streamers, promo codes, notifications, token grants, backups, admin toggles and user deletion. The flows are covered by tests (#117, #150, #163, #175).

**What isn't good enough:** the Steam path leaves the page.
- **Lost work:** after confirming, the admin lands back on the Admin tab with "Confirmed with Steam. Repeat the action to continue." Anything typed into a dialog is gone: the End Season form, a Mark champions roster, a notification text.
- **No retry:** with a password, by contrast, `adminFetch` retries the original request by itself. Only Twitch Connect (`_reauthResume = "connectTwitch"`) resumes after Steam.
- **Admins with both:** an admin who has a password *and* Steam only sees the password prompt.

**Decisions** (change them in review if needed):
- **Steam in a popup:**
  - "Confirm with Steam" opens the Steam round trip in a small popup window (`window.open`, named, about 800×700), while the Admin page stays as it is.
  - The callback ends on a tiny static page, `frontend/steam-reauth-done.html`, which tells the opener the result with `postMessage({type: "steam-reauth", result})`. It targets this site's own origin, and the page then closes itself.
  - `adminFetch` waits for that message, accepting it only from `location.origin` with the expected shape. On `ok` it retries the original request exactly once, as for a password.
- **Popup blocked or closed:** the modal says so and offers the current full-page path, which keeps working unchanged as the fallback.
  - Closing the popup without finishing resolves as "not confirmed".
- **Server side:** a third allowed return target, `popup`, next to `profile` and `admin` in `RETURN_TABS`. `_redirect` for a `popup` attempt goes to `/steam-reauth-done.html?steam=<key>` instead of `/#tab?steam=<key>`.
  - No change to the identity checks, the audit or the one-time state.
  - `return_tab` is already stored on `SteamLoginState`, so there is no migration.
- **Both methods offered:** an admin with a password and a linked Steam account sees the password field plus **Confirm with Steam instead**. Without Steam, only the password.
- **Steam unavailable:** if `/auth/steam/start` answers 503 `steam_unavailable` (no `APP_BASE_URL`), the modal says "Steam confirmation is unavailable on this server" instead of opening a dead window.
- **The done page is inert:** it carries no data beyond the result key from a fixed list, has no external scripts, and posts only to its own origin.

Resolves GitHub issue #213.

## User Stories

### Steam-Only Admins Confirm Without Losing Their Work
**User story**
As an admin who signs in only with Steam, I want to confirm a sensitive action with Steam without leaving the page, so that the form I filled in is kept and the action completes on its own.

**Acceptance criteria**
- **Popup:** when a protected admin action answers 403 `reauth_required` for an account without a password, **Confirm with Steam** opens the Steam check in a popup window. The Admin page and any open dialog stay as they are.
- **Success:**
  - The popup ends on `/steam-reauth-done.html`, posts `{type: "steam-reauth", result: "ok"}` to the opener and closes.
  - `adminFetch` then retries the original request once; it accepts the message only from the site's own origin.
  - The dialog's input is not lost.
- **Failure:**
  - A different Steam account ends the popup with `result: "reauth_failed"`. The modal shows "That Steam account is not the one linked to this account. Nothing was confirmed", and nothing is retried.
  - Closing the popup early counts as not confirmed.
- **Blocked popup:** the modal shows "Your browser blocked the Steam window" with **Continue on this page**, which runs today's full-page path. The full-page path's behaviour and messages are unchanged.
- **Server:**
  - `GET /auth/steam/start?purpose=reauth&return_tab=popup` is accepted.
  - The callback redirects a `popup` attempt to `/steam-reauth-done.html?steam=<key>`, where the key comes from the existing fixed set.
  - Login and link never accept `popup`.
  - The identity check, the one-time state and the `admin_reauth` / `player_reauth` audit are unchanged.
- **Same path for players:** Unlink Steam and the Twitch connection actions use the same popup.

### Admins With a Password Can Use Steam Too
**User story**
As an admin with both a password and a linked Steam account, I want to choose either method when asked to confirm, so that I can use whichever is at hand.

**Acceptance criteria**
- **Both offered:** the re-auth modal shows the password field and **Confirm with Steam instead** when the account has a password and a linked Steam id (`activeSteamLinked`) and Steam is enabled.
- **Password only:** without a linked Steam account, the modal shows only the password, as today.
- **Steam unavailable:** if Steam answers 503 `steam_unavailable`, the modal says "Steam confirmation is unavailable on this server", and the password stays available where the account has one.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/steam_openid.py` | `RETURN_TABS` gains `popup`, for `purpose=reauth` only; `_redirect` sends popup attempts to `/steam-reauth-done.html?steam=<key>` |
| `frontend/steam-reauth-done.html` (new) | Static page: reads the `steam` key from a fixed allowlist, `postMessage` to `window.opener` with `location.origin` as target, then `window.close()`; shows a short message if no opener |
| `frontend/app-admin.js` | `startSteamReauth` opens the popup; a `message` listener with an origin and shape check; detects a closed or blocked popup; falls back to the full page; shows both methods |
| `frontend/index.html` | Re-auth modal: "Confirm with Steam instead" button, blocked-popup and unavailable messages |
| `backend/main.py` | Only if the static mount doesn't already serve the new page (check); keep the CSP compatible (no inline script: put the page's script in `frontend/steam-reauth-done.js`) |
| `markdown/features/reference/steam-login.md`, `markdown/features/reference/longer-sessions.md` (re-auth section), `markdown/ui_description/admin.md` | Docs |
| `backend/tests/test_issue_213_steam_reauth_without_leaving_the_page.py` | Tests |

No migration, no new env var.

### Step 1 — Server
Allow `return_tab=popup` for reauth only, and branch `_redirect` for popup attempts. Login and link reject `popup`.

### Step 2 — Done page
Write a static HTML file plus a small JS file. No inline script, to stay within the CSP. It reads `?steam=` against the allowlist `reauth_ok`, `reauth_failed`, `no_session` and `not_linked` (anything else becomes `failed`), posts to the opener and closes.

### Step 3 — `adminFetch`
- Open the popup from the click handler, so it isn't treated as an unrequested popup.
- Wait for the message or the window closing.
- On `ok`, retry once; otherwise return the original 403.
- Keep `_reauthResume` only for the full-page fallback.

### Step 4 — Modal
Offer both methods when both exist, and add the blocked and unavailable messages.

### Step 5 — Docs and tests
**Tests:**
- `return_tab=popup` is accepted for reauth and rejected for login and link.
- The popup redirect target and its keys come from the fixed set.
- The identity mismatch is still refused and audited.
- Done page (source and Node harness): the origin-targeted `postMessage` and the allowlist.
- `adminFetch` harness:
  - an `ok` message retries once;
  - a wrong-origin message is ignored;
  - a closed popup counts as not confirmed;
  - a blocked popup offers the fallback.
- The modal shows both methods only when the account has both.

## Verification
- **Steam-only admin:** on a Steam-mode test server, open End Season, fill the form and confirm. The Steam popup opens, closes after confirming, and End Season continues without retyping.
- **Wrong Steam account:** the popup closes, the modal says nothing was confirmed, and the audit shows the failure.
- **Popup blocked:** Continue on this page uses the old path and still works.
- **Admin with both:** both options show, and either one confirms.
