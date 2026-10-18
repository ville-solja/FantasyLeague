# Steam Re-auth Without Leaving the Page

Sensitive actions ask for a recent identity check. Accounts without a password (Steam-only admins and players) already confirm through Steam (#150). This change runs that Steam check in a popup, so the page and any filled-in dialog are kept and the action retries on its own. Plan: `markdown/plans/plan-issue-213-steam-reauth-without-leaving-the-page.md`.

---

## How it works *(planned)*

1. **The action asks for a check:** a protected request answers 403 `reauth_required`, and `adminFetch` opens the re-auth modal.
2. **The popup opens:** **Confirm with Steam** (the only option without a password; **Confirm with Steam instead** next to the password when both exist) opens `GET /auth/steam/start?purpose=reauth&return_tab=popup` in a popup.
3. **The callback confirms:** it checks the Steam id against the logged-in account (unchanged) and redirects to `/steam-reauth-done.html?steam=<key>`.
4. **The done page reports back:** it posts `{type: "steam-reauth", result}` to the opener, targeting this site's origin, and closes.
5. **The page retries:** on `ok`, `adminFetch` retries the original request once.

- **Blocked popup:** "Continue on this page" falls back to the existing full-page round trip.
- **Steam unavailable:** a 503 `steam_unavailable` shows a clear message.

## Endpoints

### `GET /auth/steam/start` *(planned extension)*
`return_tab=popup` is accepted for `purpose=reauth` only.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
