# Steam Login

Players can sign in with their Steam account through Steam OpenID 2.0, alongside username and password. This gives accounts a verified Steam identity and sets `player_id` from it. From the start of S17, Steam is the only way to create a new account. Resolves issue #150; making Steam the only way to sign in is issue #172.

Code: `backend/steam_openid.py` (routes, checks, clean-up), `backend/login_mode.py` (the mode setting), `backend/seed.py::seed_admin_steam_ids`, `backend/deps.py::require_typed_confirmation`. Tests: `backend/tests/test_issue_150_steam_login.py`.

---

## Login modes

`LOGIN_METHOD` selects the mode. It is read on every request. Switching modes needs only the env var, with no migration or data change.

| Mode | Sign in | Create an account | When |
|---|---|---|---|
| `password` (default) | Password | Password; every Steam route answers 404 | Other deployments |
| `both` | Password or Steam | Password or Steam | Rest of S16 and the break |
| `steam_signup` | Password (existing accounts) or Steam | Steam only; `POST /register` answers 404 | From the start of S17 |

- An unknown value is logged once and treated as `password`. An empty value is the same as unset.
- `steam` is reserved for issue #172 (password sign-in ends). Until #172 ships it is logged as "not available yet" and treated as `steam_signup`, so setting it early never reopens registration.
- `GET /config` returns `login_method`; the login page and Profile follow it.
- In `both` and `steam_signup` without `APP_BASE_URL`, start-up logs a warning and `GET /auth/steam/start` answers 503 `steam_unavailable`.

In `steam_signup` mode password sign-in, `POST /forgot-password`, `POST /reset-password`, `PUT /profile/password` and `POST /reauth` keep working for existing password accounts. Demo accounts (`DEMO_MODE` only) are still created by `POST /admin/demo/seed-accounts`.

## Sign-in flow

1. **Start:** `GET /auth/steam/start?purpose=login` stores `sha256(state)` in `steam_login_states` (purpose, optional user id, 10-minute expiry) and sets the state in a cookie (`__Host-kc_steam_state`, `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, max-age 600). It then redirects (303) to `https://steamcommunity.com/openid/login` with `openid.mode=checkid_setup`, `openid.return_to` = `{APP_BASE_URL}/auth/steam/callback?state=<state>`, `openid.realm` = `{APP_BASE_URL}/`, and `identifier_select` as identity and claimed id. The address is never built from the request's Host header.
2. **Callback:** `GET /auth/steam/callback` first checks the attempt: the `state` query value equals the cookie, and its hash is a known, unexpired, unused row. The row is used up on first use and the cookie is deleted. Then `verify_assertion` checks, in order:
   - `openid.ns` is `http://specs.openid.net/auth/2.0` and `openid.mode` is `id_res` (`cancel`, `setup_needed` or a missing mode fail);
   - `openid.op_endpoint` is exactly `https://steamcommunity.com/openid/login`;
   - `openid.claimed_id` fully matches `https://steamcommunity.com/openid/id/<17 digits>` and equals `openid.identity`;
   - `openid.return_to` equals the callback address with this attempt's state;
   - `openid.signed` lists at least `op_endpoint`, `claimed_id`, `identity`, `return_to`, `response_nonce` and `assoc_handle`;
   - `openid.response_nonce` is at most 5 minutes old (or ahead) and has not been seen before. `sha256(nonce)` goes into `steam_openid_nonces` (primary key) before the network call, so a replay fails;
   - no parameter repeats, no value is longer than 2048 characters, and the query string is at most 8 KB;
   - a server-side POST to the hard-coded `https://steamcommunity.com/openid/login` with exactly the received `openid.*` fields and `openid.mode=check_authentication` (verified TLS, `timeout=10`, `allow_redirects=False`) answers HTTP 200 with a line that is exactly `is_valid:true`.
3. **Outcome (purpose `login`):** a known Steam ID (`users.steam_id`; demo accounts and Twitch viewer soft accounts are excluded from the lookup) starts a session with a new session id (`sessions.start_session`), writes `user_login` with `method=steam`, and redirects to `/`. An unknown Steam ID never signs in to an existing account by `player_id`, username or email. It creates a pending sign-up (`steam_pending_signups`, hashed token, 15 minutes) with the cookie `__Host-kc_steam_signup` and redirects to `/#welcome?steam=choose_name`, where the player picks a display name.
4. **Sign-up:** `POST /auth/steam/signup` with `{ "username" }` (the registration username rules) creates the account with `steam_id` set, no password, no email, `INITIAL_TOKENS` tokens and `player_id` = Steam64 − 76561197960265728. It writes `user_register` with `method=steam`, uses up the pending row and starts the session.

When `APP_BASE_URL` starts with `http://localhost`, the state and sign-up cookies drop the `__Host-` prefix and `Secure` (browsers refuse both over plain HTTP). Any other base URL keeps both.

**Failures** redirect with a message key and create no account and no session. Before the attempt is known the target is `/#login?steam=failed`; afterwards it is the purpose's tab. A timeout, network error or HTTP 5xx from Steam gives `steam=unavailable` ("Steam sign-in is unavailable right now"). Password sign-in and existing sessions are unaffected.

**Logging:** nothing logs the callback query string, the signature, the nonce or the assoc handle; failures log `Steam sign-in failed: <reason>`. `twitch_oauth.RedactSignInQuery` strips the query of `/auth/twitch/*` and `/auth/steam/*` lines from uvicorn's access log. No Steam Web API key is used and the Steam persona name is never fetched.

### Redirect keys

| Redirect | Meaning |
|---|---|
| `/` | Signed in |
| `/#welcome?steam=choose_name` | New Steam ID: choose a display name |
| `/#login?steam=failed` / `cancelled` / `unavailable` | Sign-in failed, was cancelled on Steam, or Steam could not be reached |
| `/#profile?steam=linked` | Steam linked |
| `/#profile?steam=reauth_required` | Link needs a recent identity check first; Profile opens the password prompt and starts again |
| `/#profile?steam=in_use` | "This Steam account is linked to another Kana Cards account" |
| `/#profile?steam=unlink_first` / `not_allowed` / `no_session` / `login_required` | Another Steam account is linked; demo account; no website session |
| `/#<tab>?steam=reauth_ok` / `reauth_failed` / `not_linked` | Steam re-auth result; `<tab>` is `profile` or `admin` |

The frontend (`handleSteamReturn` in `frontend/app-auth.js`) strips the hash from the address bar and shows the message.

## Link Steam

Profile shows **Link Steam** in `both` and `steam_signup` modes for a logged-in account without a Steam link (never for demo accounts). `GET /auth/steam/start?purpose=link` needs a session and a recent identity check (`POST /reauth`); without one it redirects to `/#profile?steam=reauth_required`. The state row is bound to the user, and the callback accepts the link only when the session user is that user. Starting a link or re-auth drops the user's older unused attempts, so only the newest one is live. On an account that is already linked, start redirects straight to `/#profile?steam=linked` without going to Steam.

On success `users.steam_id` is set and `player_id` becomes the verified Steam32 id, replacing any self-reported value; audited as `steam_linked`. Every other account that self-reported the same `player_id` has it cleared, audited as `player_id_claim_superseded` (`user_id=<cleared> verified_user_id=<linked> player_id=<id>`); sign-up does the same. A Steam ID already on another account is refused (`in_use`) and nothing changes; only an admin can move it.

`PUT /profile/player-id` answers 409 for a Steam-linked account. Accounts without Steam set it as before.

From the start of S17 (`steam_signup`), Profile reminds password accounts without Steam: "Link Steam now. Password sign-in will end in a later update."

## Re-authentication through Steam

Accounts created through Steam have no password. `POST /reauth` answers 409 `use_steam_reauth` for them, without counting a failed login. The re-auth prompt instead offers **Confirm with Steam**, which navigates to `GET /auth/steam/start?purpose=reauth&return_tab=<profile|admin>` (any other `return_tab` returns to Profile; never a free URL). The callback calls `sessions.mark_reauth` on the current session only when the verified Steam ID equals the session user's, so every check that reads it passes: destructive admin actions (`require_recent_reauth`), Connect Twitch, merge and Disconnect (`require_recent_player_reauth`, #160), and Link/Unlink Steam. The round trip leaves the page, so the player repeats the action afterwards, except Connect Twitch: `_promptReauth("connectTwitch")` stores it in `sessionStorage` (`reauthResume`) and `handleSteamReturn` resumes it on `reauth_ok` (only actions listed in `_REAUTH_RESUMABLE` in `app-auth.js`). Audited as `admin_reauth` / `player_reauth` with `method=steam`.

## Admins

`SEED_ADMIN_STEAM_IDS` lists Steam64 IDs (comma-separated, whitespace tolerated). An entry that is not exactly 17 digits is logged by position and skipped; start-up continues. A verified Steam sign-in, sign-up or link with a listed ID makes the account an admin, audited as `admin_seeded_from_env` (this action is written only for Steam seeding; password seeding is not audited). A first-time ID becomes an admin after the display-name step; an existing account is promoted. A password admin who links Steam keeps admin rights. Demo accounts are never promoted.

**Removing an ID from the list does not demote** the account. Demotion stays the audited admin toggle (Admin › User Management › Demote from admin).

**The list promotes each account at most once.** The first time a listed Steam ID signs in, signs up or links, the account is marked (`users.admin_seed_applied_at`, migration `035`), even if it is already an admin. After that the list never promotes it again, so an in-app demotion holds while the ID is still listed. To make a demoted account admin again, use the admin toggle.

**Steam Guard:** every listed admin must have Steam Guard's mobile authenticator enabled on their Steam account. A Steam account without it is one stolen password away from an admin session.

**Demote an admin quickly** if their Steam account may be compromised:
1. Another admin opens Admin › User Management and chooses **Demote from admin** on the account (types `CHANGE ADMIN`). This ends every session of the account at once.
2. Remove the Steam ID from `SEED_ADMIN_STEAM_IDS` at the next deploy. This is cleanup only: the demotion already holds, because the list promotes each account once.
3. If the account itself should stop signing in, an admin can also use **Force logout**; Steam sign-in keeps working for it until the Steam account is secured.

Password admin seeding (`SEED_ADMIN_USERNAME`, `_EMAIL`, `_PASSWORD` and the numbered sets) keeps working in `password` and `both`. In `steam_signup` it is skipped with one start-up warning, because it would create password accounts; #172 removes it.

### Typed confirmations

Steam OpenID cannot force a fresh password prompt, so destructive admin actions also need the action's name typed in, for every admin. The backend dependency `require_typed_confirmation(action)` checks a `confirm` value (query parameter or JSON body field, case and surrounding spaces ignored) and otherwise answers 400 `confirmation_required`. It runs after the recent re-auth check.

| Action | Route | Phrase |
|---|---|---|
| Season end | `POST /admin/season/end` | `END SEASON` |
| Season reset | `POST /admin/season/reset` | `RESET SEASON` |
| Admin toggle | `POST /users/{id}/toggle-admin` | `CHANGE ADMIN` |
| Token grant | `POST /grant-tokens` (now also needs the recent re-auth) | `GRANT TOKENS` |
| Backup download | `GET /admin/backups/{filename}?confirm=…` | `DOWNLOAD BACKUP` |
| Delete Twitch viewer account | `DELETE /admin/users/{id}` (soft accounts only) | `DELETE USER` |

## Demo accounts

`users.is_demo` (migration 033) marks the throwaway accounts made by `POST /admin/demo/seed-accounts`; the migration flags earlier ones by their `demoN@demo.local` email. Demo accounts keep their passwords in this issue, can never be promoted to admin, never link Steam and are never matched by the Steam callback. One-time demo login links are issue #172.

## Endpoints

All four answer 404 in `password` mode; `main.py` also routes any unknown `/auth/steam/*` path to 404 (instead of the static mount's 405). Start, callback and sign-up are limited per IP by `RATE_LIMIT_STEAM_CALLBACK`.

### `GET /auth/steam/start?purpose=login|link|reauth[&return_tab=profile|admin]`
Begins a Steam sign-in, link (session and recent check) or re-auth (session and a linked Steam ID). 303 to Steam with the state cookie; 400 for another purpose; 503 `steam_unavailable` without `APP_BASE_URL`.

### `GET /auth/steam/callback`
Verifies Steam's answer, then signs in, starts a sign-up, links or marks the re-auth. Always redirects back to the site (see Redirect keys).

### `POST /auth/steam/signup`
Body `{ "username" }`. Creates the account for the pending Steam ID and starts the session; returns `{ "username", "is_admin", "tokens" }`. 400 `signup_expired` without a valid pending sign-up; 422 for a username failing the format rules, or 422 "This name is reserved" for a reserved word (#169); 409 when the username is taken, ignoring letter case (the pending sign-up stays usable) or the Steam ID got linked to another account meanwhile ("This Steam account is linked to another Kana Cards account"; this uses up the pending sign-up). Like `POST /profile/steam/unlink`, it uses the session cookie and is covered by the cross-origin Origin check (`OriginCheckMiddleware` in `main.py`, #136), which applies to every unsafe method outside `/twitch/`.

### `POST /profile/steam/unlink`
Needs a recent identity check (403 `reauth_required`). Clears `steam_id`; `player_id` stays; audited as `steam_unlinked`. 409 for an account without a password, since it would lock the player out.

### `GET /admin/player-id-claims`
Admin only. Superseded self-reported player ids, newest first: `[{ "timestamp", "player_id", "superseded_user_id", "superseded_username", "verified_user_id", "verified_username" }]`, read from the `player_id_claim_superseded` audit rows. Shown under Admin › User Management.

`GET /me` adds `steam_linked`, `has_password` and `is_demo` (booleans only; the Steam ID is never returned anywhere).

## Data

- `users.steam_id` (String(17), unique, nullable) and `users.is_demo` (Boolean, default false): migration `033_users_steam_id`.
- New tables (`create_all`): `steam_login_states`, `steam_openid_nonces`, `steam_pending_signups`. The week maintenance loop deletes used or expired attempts and pending sign-ups, and nonces older than a day, once a day (`steam_openid.cleanup`).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LOGIN_METHOD` | `password` | `password`, `both` or `steam_signup` (`steam` is #172 and acts as `steam_signup` until then) |
| `SEED_ADMIN_STEAM_IDS` | *(empty)* | Comma-separated Steam64 IDs that become admins on a verified Steam sign-in, sign-up or link |
| `RATE_LIMIT_STEAM_CALLBACK` | `10/minute` | Per-IP limit on the Steam start, callback and sign-up routes |

`APP_BASE_URL` builds the OpenID `return_to` and `realm`, and is required in `both` and `steam_signup`. No `STEAM_API_KEY` is needed for sign-in.
