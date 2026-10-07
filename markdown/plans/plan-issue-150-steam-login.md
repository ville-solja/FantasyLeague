# Plan: Steam Login

## Context
Kana Cards logs players in with a username and password, with password reset by email (SMTP). Issue #150 adds Steam sign-in through Steam OpenID 2.0 (Option B1 in `markdown/features/reference/kana-hub-integration-feasibility.md`, #108). Players get the same identity as on Kana Hub, `player_id` becomes verified instead of self-reported, and new accounts eventually come only from Steam.

**Timeline** (decided after the first draft of this plan):
- **Rest of S16 and the break after it:** both login methods are accepted. Players can still register and log in with a password, and anyone can sign in with Steam. Logged-in password players can **Link Steam**.
- **From the start of S17:** Steam is the only way to **create** an account. Registration with a password is closed. Existing password accounts keep logging in, and can still reset their password and link Steam.
- **Later (separate issue):** Steam becomes the only way to **sign in** at all. That issue removes password login, the password and email code, and SMTP. It also covers the admin merge of accounts that never linked Steam, and moves demo accounts to one-time login links.

**Login modes,** set by a new `LOGIN_METHOD` env var:

| Mode | Sign in | Create an account | When |
|---|---|---|---|
| `password` (default) | Password | Password registration. Steam routes answer 404. | Other deployments; before the release |
| `both` | Password or Steam | Password registration or Steam | Now, for the rest of S16 and the break |
| `steam_signup` | Password (existing accounts) or Steam | Steam only. `POST /register` answers 404. | From the start of S17 |

The separate issue adds a fourth mode, `steam`, in which password sign-in ends.

**What exists today:**
- **Routes:** `backend/routers/auth.py` has `POST /login`, `/register`, `/logout`, `/logout-everywhere`, `/reauth`, `/forgot-password` and `/reset-password`, plus `GET`/`DELETE /sessions`. `backend/routers/profile.py` has `PUT /profile/password` and `PUT /profile/player-id`, which writes the self-reported, unverified `users.player_id`.
- **Sessions:** `backend/sessions.py` (#117) keeps hashed server-side session ids. `start_session` issues a new id at login. `reauth_is_recent` checks the session's last password check, which `POST /reauth` sets. `require_recent_reauth` / `require_recent_player_reauth` in `backend/deps.py` use it for destructive admin actions and for Connect Twitch (#160).
- **Seeding:** `backend/seed.py::seed_admin_from_env()` creates password admins from `SEED_ADMIN_USERNAME`, `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD` (plus `_2`, `_3`…).
- **Demo:** `POST /admin/demo/seed-accounts` creates `demo1`, `demo2`… with random passwords, only while `DEMO_MODE` is on.
- **Pattern to follow:** `backend/twitch_oauth.py` (#160) already has a one-time hashed state, a server-side check with a short timeout, redirects back to the site with a message key, and `RedactSignInQuery` for access logs.

**Assumptions** (flagged for review):
- **The default stays `password`,** so other deployments are unaffected. Production sets `LOGIN_METHOD=both` when this ships, and `steam_signup` at the start of S17.
- **New Steam players choose a display name on first sign-in.** No Steam Web API key is used and the Steam persona name is never fetched, so #163's name cleaning doesn't apply. The verified Steam ID waits in a short-lived pending sign-up row until the player picks a name that passes the existing username rules; only then is the account created.
- **Accounts created through Steam have no password and no email.** They re-authenticate through a Steam round trip (`purpose=reauth`), which sets the same per-session recent-check time as `POST /reauth`, so Connect Twitch, Link/unlink Steam and admin re-auth work for them too. Password accounts keep password re-auth. Password reset doesn't apply to Steam-only accounts.
- **A typed confirmation for destructive admin actions.** Admins created from Steam IDs re-authenticate through Steam, and Steam OpenID can't force a fresh password prompt. So these actions also require typing the action's name, for every admin: season end, season reset, admin toggle, token grant and DB backup download.
- **Superseded player-id claims.** When a verified Steam ID's `player_id` is already self-reported on another account, the verified account gets it and the other account's `player_id` is cleared. The change is audited and listed for admins.
- **Password admin seeding stays for now.** `SEED_ADMIN_USERNAME`/`_EMAIL`/`_PASSWORD` keep working in `password` and `both` modes. In `steam_signup` mode they are ignored with a warning, because they would create password accounts. The separate issue removes them.
- **Demo accounts keep their passwords here.** They are admin-made throwaways that exist only in demo mode and are exempt from "Steam only for new accounts". They are now marked by `users.is_demo`. One-time demo login links move to the separate issue, where passwords go away.
- **Local development over plain HTTP.** The `__Host-` cookie prefix needs `Secure`, which needs HTTPS. When `APP_BASE_URL` starts with `http://localhost`, the state cookie drops the prefix and `Secure`. Anything else keeps both.

Resolves GitHub issue #150. Steam-only sign-in, removal of the password code and SMTP, demo login links and the admin merge of unlinked accounts are in the follow-up issue #172.

## Decisions (applied at implementation)

Open points resolved before implementation:
1. `POST /grant-tokens` gets `require_recent_reauth` plus the typed confirmation.
2. The backup download `GET /admin/backups/{filename}` takes the confirmation as a query parameter, `?confirm=DOWNLOAD BACKUP`. Every covered route accepts `confirm` as a query parameter or a JSON body field.
3. `users.is_demo` (Boolean, default false) ships in migration 033 with `steam_id`; `POST /admin/demo/seed-accounts` sets it. Demo accounts keep their passwords, can never be promoted to admin, never link Steam and are never matched by the Steam callback. Username rules are unchanged.
4. `DELETE /admin/users/{id}` (deleting a Twitch viewer account; it only deletes soft accounts) is the sixth typed-confirmation action. Phrases: `END SEASON`, `RESET SEASON`, `CHANGE ADMIN`, `GRANT TOKENS`, `DOWNLOAD BACKUP`, `DELETE USER` (`deps.CONFIRM_PHRASES`; case and surrounding spaces ignored).
5. The Profile reminder shows when `LOGIN_METHOD` is `steam_signup` and the account has a password and no Steam link.
6. `POST /profile/steam/unlink` answers 404 in `password` mode like the `/auth/steam/*` routes; a `/auth/steam/{rest:path}` catch-all in `main.py` gives 404 instead of the static mount's 405.
7. One rate-limit variable, `RATE_LIMIT_STEAM_CALLBACK` (default `10/minute`), covers start, callback and sign-up. The pending sign-up cookie is `__Host-kc_steam_signup` (same localhost rule as the state cookie). Redirects: sign-in → `/`; sign-up needed → `/#welcome?steam=choose_name`; link → `/#profile?steam=linked`; re-auth → `/#<tab>?steam=reauth_ok`, where start accepts `return_tab` limited to `profile` and `admin`.
8. Without `APP_BASE_URL` in `both`/`steam_signup`, Steam start answers 503 `steam_unavailable` and start-up logs a warning.
9. `POST /reauth` for an account without a password answers 409 `use_steam_reauth` and does not count as a failed login.
10. `LOGIN_METHOD` is read at call time. Unknown values are logged once and treated as `password`, except `steam` (#172), which is logged as not available yet and treated as `steam_signup`.
11. #157, #160 and #161 behaviour stays intact; Connect Twitch accepts Steam re-auth for passwordless accounts.

## User Stories

### Sign In with Steam
**User story**
As a player, I want to sign in with my Steam account, so that I don't need another password and my Kana Cards account carries my verified Dota identity.

**Acceptance criteria**
- In `both` and `steam_signup` modes, the login page shows **Sign in with Steam** next to the password form. It is a full-page redirect to `https://steamcommunity.com/openid/login`, never a pop-up or an embedded frame.
- The login page says: "Sign-in happens on steamcommunity.com. Kana Cards never asks for your Steam password."
- `GET /auth/steam/start?purpose=login` stores `sha256(state)` with purpose, optional user id and a 10-minute expiry. It sets the state in a cookie (`__Host-kc_steam_state`, `Secure`, `HttpOnly`, `SameSite=Lax`, max-age 600) and binds it into `openid.return_to`. `openid.return_to` and `openid.realm` are built from `APP_BASE_URL`.
- `GET /auth/steam/callback` accepts the sign-in only when all of these hold, each covered by a test with forged input:
  - `openid.ns` is `http://specs.openid.net/auth/2.0` and `openid.mode` is `id_res`. `cancel`, `setup_needed` or a missing mode is a failed sign-in.
  - `openid.op_endpoint` is exactly `https://steamcommunity.com/openid/login`.
  - `openid.claimed_id` fully matches `https://steamcommunity.com/openid/id/` followed by exactly 17 ASCII digits (nothing after them, not even a newline) and equals `openid.identity`.
  - `openid.return_to` equals the callback URL built from `APP_BASE_URL`, including the state.
  - The state in `return_to` equals the cookie, its hash is a known, unexpired, unused row, and the row is used up on first use. The cookie is deleted.
  - `openid.signed` lists at least `op_endpoint`, `claimed_id`, `identity`, `return_to`, `response_nonce` and `assoc_handle`.
  - `openid.response_nonce` is no older than 5 minutes and hasn't been seen before. Used nonces are stored and pruned after a day.
  - No `openid.*` parameter repeats, no value is longer than 2048 characters, and the query string is at most 8 KB.
  - A server-side POST to the hard-coded `https://steamcommunity.com/openid/login` succeeds. It never uses a URL from the request. It sends exactly the received `openid.*` fields with only `openid.mode=check_authentication`, uses verified TLS, doesn't follow redirects and times out after 10 s. The answer must contain a line that is exactly `is_valid:true`. A timeout, an error or anything else fails the sign-in.
- A known Steam ID (`users.steam_id`) starts a session with a new session id through `sessions.start_session`. The callback then redirects to `/` with no `next=` parameter.
- An unknown Steam ID never signs in to an existing account by `player_id`, username or email. It creates a pending sign-up (hashed token cookie `__Host-kc_steam_signup`, 15 minutes) and redirects to the display-name step (`/#welcome?steam=choose_name`). `POST /auth/steam/signup` with a valid username creates the account, with `steam_id` set, no password, no email, and `player_id` = Steam64 − 76561197960265728. It then starts the session.
- **Rate limits:** the callback is limited per IP (`RATE_LIMIT_STEAM_CALLBACK`, default `10/minute`), as are start and sign-up (the same variable covers all three).
- If `APP_BASE_URL` is unset in `both` or `steam_signup` mode, start-up logs a warning and `GET /auth/steam/start` answers 503 `steam_unavailable`.
- **Logging:** nothing logs the callback query string. `RedactSignInQuery` covers `/auth/steam/`, and failures log a reason only.
- **Steam outage:** if the `check_authentication` POST fails, the sign-in fails closed with "Steam sign-in is unavailable right now". Password sign-in and existing sessions are unaffected.
- **Failure path:** a failed check redirects to `/#login?steam=failed` with no account created and no session started. With `LOGIN_METHOD=password`, every `/auth/steam/*` route and `POST /profile/steam/unlink` answer 404 (a `/auth/steam/{rest:path}` catch-all keeps unknown paths at 404, not the static mount's 405).

### Link Steam to an Existing Account
**User story**
As an existing player, I want to link my Steam account, so that my player id is verified and my account carries over when Steam becomes the only way to sign in.

**Acceptance criteria**
- In `both` and `steam_signup` modes, Profile shows **Link Steam** for a logged-in player without a `steam_id`. It needs a recent check (`require_recent_player_reauth`). Without one, it redirects back to Profile with `steam=reauth_required`, and Profile opens the password prompt and starts again.
- `GET /auth/steam/start?purpose=link` binds the state row to the logged-in user. The callback accepts the link only when the session user is that user and every check from "Sign In with Steam" passes.
- On success, `users.steam_id` is set and `player_id` becomes the verified Steam32 id, replacing any self-reported value. The action is audited as `steam_linked`.
- If another account had self-reported the same `player_id`, that account's `player_id` is cleared and audited as `player_id_claim_superseded` (both user ids). Admin › User Management lists these claims.
- A Steam ID already stored on another account is refused with "This Steam account is linked to another Kana Cards account". Nothing changes, and only an admin can move it.
- **Unlink Steam** on Profile needs a recent check, clears `steam_id` (`player_id` stays) and is audited as `steam_unlinked`. It is refused for an account without a password, because it would lock the player out.
- `PUT /profile/player-id` answers 409 for an account with a linked Steam ID, whose id is verified. Accounts without Steam can still set it as today.
- From the start of S17 (`LOGIN_METHOD=steam_signup`), Profile reminds accounts that have a password and no Steam link: "Link Steam now. Password sign-in will end in a later update."
- Demo accounts never see Link Steam and can't link Steam.
- **Failure path:** a link callback with another user's state, or with no session, changes nothing and redirects with `steam=failed` or `steam=no_session`.

### Steam Is the Only Way to Create Accounts in S17
**User story**
As the operator, I want new accounts in S17 to come only from Steam while existing players keep their password sign-in, so that every new player has a verified identity without locking anyone out.

**Acceptance criteria**
- With `LOGIN_METHOD=steam_signup`, `POST /register` answers 404. The login page hides the registration form and says "New players: sign in with Steam to create your account."
- Password sign-in, password reset (`/forgot-password`, `/reset-password`), `PUT /profile/password` and `POST /reauth` keep working for existing password accounts.
- Password admin seeding (`SEED_ADMIN_USERNAME` and the numbered sets) is ignored in `steam_signup` mode, with one warning at start-up, so no account is created outside Steam.
- Demo accounts (`DEMO_MODE` only) are exempt and are still created by `POST /admin/demo/seed-accounts`.
- Switching from `both` to `steam_signup` needs no migration or data change, only the env var.
- `POST /reauth` for an account without a password answers 409 `use_steam_reauth` and does not count as a failed login; such accounts confirm through Steam.
- **Failure path:** a direct `POST /register` in `steam_signup` mode answers 404 and creates nothing. An unknown `LOGIN_METHOD` value is logged and treated as `password`, except `steam` (issue #172, not built yet), which is logged as not available yet and treated as `steam_signup`. `LOGIN_METHOD` is read at call time.

### Admins Come In Through Steam
**User story**
As the operator, I want admins to be named by Steam ID, so that a deploy's admins don't depend on passwords and existing admins keep their rights after linking Steam.

**Acceptance criteria**
- A new env var, `SEED_ADMIN_STEAM_IDS`: comma-separated Steam64 IDs. An entry that isn't exactly 17 digits is logged and skipped, and start-up continues.
- A verified Steam sign-in or link whose Steam ID is in the list makes the account an admin. A first-time Steam ID is created as an admin after the display-name step; an existing account is promoted. This is audited as `admin_seeded_from_env` (written only for Steam seeding).
- Removing an ID from the list does not demote the account. Demotion stays the existing audited admin toggle, and the docs say so.
- A password admin who links Steam keeps admin rights.
- Destructive admin actions ask the admin to type the action name in the confirmation, in addition to the recent re-auth. The backend checks a `confirm` field equal to the action name and otherwise answers 400 `confirmation_required`. This covers season end (`END SEASON`), season reset (`RESET SEASON`), the admin toggle (`CHANGE ADMIN`), token grants (`GRANT TOKENS`, which now also needs the recent re-auth), DB backup download (`?confirm=DOWNLOAD BACKUP` query parameter) and deleting a Twitch viewer account (`DELETE /admin/users/{id}`, `DELETE USER`).
- Admin accounts without a password re-authenticate through Steam (`purpose=reauth`), which marks the session only when the verified Steam ID equals the admin's.
- The docs require Steam Guard's mobile authenticator for every listed admin, and describe how to demote an admin quickly if their Steam account is compromised.
- Demo accounts are marked by `users.is_demo` (migration 033). They keep their passwords, never link Steam and are never matched by the Steam callback.
- **Failure path:** an unlisted Steam ID signs in as a normal player. A demo account can never become an admin.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/steam_openid.py` *(new)* | Routes `GET /auth/steam/start`, `GET /auth/steam/callback`, `POST /auth/steam/signup`, `POST /profile/steam/unlink`. Contains the OpenID checks, the `check_authentication` POST, the state cookie and the nonce store. |
| `backend/login_mode.py` *(new)* | Reads `LOGIN_METHOD` (`password`/`both`/`steam_signup`). Provides a `require_login_methods(...)` dependency so routes answer 404 outside their modes. Built so the follow-up issue can add `steam`. |
| `backend/models.py` | `User.steam_id` (String(17), unique, nullable) and `User.is_demo` (Boolean, default false) on the existing table. New tables: `SteamLoginState`, `SteamOpenIdNonce`, `SteamPendingSignup`. |
| `backend/migrate.py` | Migration `033_users_steam_id`: both columns, PRAGMA-guarded, with a unique index on `steam_id`; flags earlier `demoN@demo.local` accounts as demo. |
| `backend/routers/auth.py` | `POST /register` gated to `password`/`both`. `POST /reauth` refuses accounts without a password (they use Steam re-auth). |
| `backend/routers/profile.py` | `PUT /profile/player-id` answers 409 for Steam-linked accounts. `/me` adds `steam_linked` and `has_password` (booleans, never the Steam id). |
| `backend/sessions.py` | `mark_reauth(row)`, shared by password and Steam re-auth. |
| `backend/deps.py` | `require_typed_confirmation(action)` for destructive admin routes. The demo-account guard on promotion. |
| `backend/seed.py` | Parsing of `SEED_ADMIN_STEAM_IDS`, which the callback uses. Password seeding skipped with a warning in `steam_signup` mode. |
| `backend/routers/admin_users.py`, `admin_season.py`, `admin_backups.py` | Typed confirmation on destructive actions. The list of superseded player-id claims. Demo accounts can't be promoted. |
| `backend/twitch_oauth.py` | `RedactSignInQuery` also covers `/auth/steam/`. Connect Twitch keeps `require_recent_player_reauth`, which Steam re-auth also satisfies. |
| `backend/main.py` | Mounts the new router, adds the `/auth/steam/{rest:path}` 404 catch-all, and prunes Steam states, nonces and pending sign-ups daily. The existing `OriginCheckMiddleware` already covers the cookie-authenticated Steam POSTs (`POST /auth/steam/signup`, `POST /profile/steam/unlink`), since it applies to every unsafe method outside `/twitch/`; no change was made there. |
| `frontend/index.html`, `frontend/app-auth.js`, `frontend/app-profile.js`, `frontend/app-admin-*.js` | Login page by mode, with Sign in with Steam, the anti-phishing line and the S17 registration notice. Display-name step. Profile Link/Unlink Steam and the S17 reminder. Re-auth through Steam for accounts without a password. Typed confirmations. Superseded claims for admins. |
| `frontend/privacy.html`, `frontend/terms.html` | Steam ID as personal data, not shown publicly beyond what the player id already shows; Steam outage note. |
| `.env.example` | Add `LOGIN_METHOD`, `SEED_ADMIN_STEAM_IDS`, `RATE_LIMIT_STEAM_CALLBACK`. |
| `backend/tests/test_issue_150_steam_login.py` | New tests. Existing register and seed tests are updated per mode. |

### Step 1 — Mode setting, model and migration
- `login_mode.py`: `LOGIN_METHOD` defaults to `password`; an unknown value is logged and treated as `password`.
- Add `users.steam_id`, migration `033`, and the three tables (`create_all`, no migration).
- `tests/test_migrate.py` must pass.

### Step 2 — OpenID verification
`steam_openid.py`, modelled on `twitch_oauth.py`:

```python
STEAM_OPENID = "https://steamcommunity.com/openid/login"   # hard-coded, never from the request
NS = "http://specs.openid.net/auth/2.0"
CLAIMED_RE = re.compile(r"https://steamcommunity\.com/openid/id/([0-9]{17})")  # used with fullmatch
REQUIRED_SIGNED = {"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce", "assoc_handle"}
STEAM32_OFFSET = 76561197960265728

def verify_assertion(params: dict[str, str], expected_return_to: str) -> str:
    """Every check from the story, in order; returns the Steam64 id or raises _SignInFailed
    (a log-safe reason, never the query)."""

def _check_authentication(params) -> bool:
    data = {k: v for k, v in params.items() if k.startswith("openid.")}
    data["openid.mode"] = "check_authentication"
    resp = requests.post(STEAM_OPENID, data=data, timeout=10, allow_redirects=False)
    return resp.status_code == 200 and "is_valid:true" in resp.text.splitlines()
```

Repeated parameters are detected from `request.query_params.multi_items()`. Nonces are stored in `steam_openid_nonces` (unique), and a duplicate insert fails the sign-in.

### Step 3 — Start, callback, sign-up, link and re-auth
- **Start:** `purpose` is `login`, `link` or `reauth`. `link` and `reauth` need a session; `link` also needs a recent check. Start stores the state row and sets the cookie, then redirects (303) to Steam with `openid.mode=checkid_setup`, `openid.ns`, `openid.return_to`, `openid.realm`, and `identity`/`claimed_id` set to `http://specs.openid.net/auth/2.0/identifier_select`.
- **Callback:** check the cookie and state row, use it up, run `verify_assertion`, then branch on the purpose:
  - **login:** a known Steam ID starts a session; an unknown one creates a pending sign-up, allowed in `both` and `steam_signup`.
  - **link:** conflicts, then store the id and supersede any matching player-id claim.
  - **reauth:** if the Steam ID matches the session user, mark the session re-authenticated.
  - **Admin seeding:** applies on login, link and sign-up when the ID is listed.
- **Redirects:** every outcome redirects to `/#login?steam=<key>` or `/#profile?steam=<key>`.

### Step 4 — Registration gate and seeding by mode
- `require_login_methods("password", "both")` on `POST /register`.
- In `steam_signup` mode, `seed_admin_from_env` skips password admins with one warning.
- `POST /reauth` refuses accounts without a password with 409 `use_steam_reauth`. The frontend's re-auth prompt starts the Steam round trip for them.

### Step 5 — Typed confirmations and admin tools
- `require_typed_confirmation(action)` on season end and reset, the admin toggle, token grants and backup download. The frontend asks the admin to type the action name.
- The superseded-claims list appears under Admin › User Management.

### Step 6 — Frontend, privacy and docs
- **Frontend:** the login page by mode, the display-name step, Profile's Steam section (linked: yes/no only, never the id), the S17 reminder, re-auth, admin confirmations and claims.
- **Pages:** privacy and terms updated.
- **Docs:**
  - `core/auth.md`;
  - a new `reference/steam-login.md`;
  - the Profile, login and admin UI descriptions;
  - stories;
  - `.env.example`;
  - the Twitch account connection doc (re-auth through Steam for accounts without a password).

## Verification
- **Unit tests, one per check with forged input:**
  - wrong `ns` or mode; foreign `op_endpoint`; mismatched `claimed_id`/`identity`; bad `claimed_id` format; wrong `return_to`;
  - missing state cookie, cookie/state mismatch, expired or used state;
  - a missing name in `openid.signed`; old nonce; replayed nonce; repeated parameter; over-long value;
  - `check_authentication` answering `is_valid:false`, timing out, redirecting, or answering a near miss such as `is_valid:true ` or `xis_valid:true`.
  
  All of them fail closed, with no session and no account created.
- **Flows (with `check_authentication` mocked):**
  - new player sign-up through Steam, giving an account with no password or email and a verified `player_id`;
  - known player sign-in, with a new session id;
  - link with and without a recent check;
  - link conflict, and a superseded player-id claim;
  - unlink refused for an account without a password;
  - Steam re-auth, which satisfies Connect Twitch;
  - every `/auth/steam/*` route answering 404 in `password` mode.
- **Modes:** `POST /register` works in `password` and `both` and answers 404 in `steam_signup`. Password sign-in and reset work in all three modes. Password admin seeding is skipped in `steam_signup`.
- **Admin seeding:** a listed ID becomes admin on first sign-in; an unlisted one doesn't; an invalid entry is skipped; removing an ID doesn't demote; demo accounts can't be promoted.
- **Typed confirmation:** each covered admin action answers 400 without it.
- **Logs:** no callback query string, signature, nonce or assoc handle in captured logs; `RedactSignInQuery` covers `/auth/steam/`.
- **Manual, on the test environment:**
  1. Set `LOGIN_METHOD=both`. Sign in with a real Steam account, then link Steam on an existing password account and check that `player_id` equals the Steam32 id.
  2. Add your Steam64 id to `SEED_ADMIN_STEAM_IDS` and confirm admin rights.
  3. Switch to `steam_signup`: registration is gone, and password sign-in and reset still work.
  4. Confirm Connect Twitch works for a Steam-created account.
- **Migration:** `033` on a copy of production. Existing users have no `steam_id`.
- Run `/security-reviewer`; it must report no High findings. Run the full suite and update the suite-size check in `tests/test_issue_85_split_admin_router.py`.
