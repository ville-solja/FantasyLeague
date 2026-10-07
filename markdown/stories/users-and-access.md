# Users and Access

### Registration
**User story**
As a new user, I want to register an account by providing a unique email and username so that I can participate in the fantasy league.

**Acceptance criteria**
- User can register with required credentials
- Registration fails if the username or email is already in use
- After successful registration, the user account is created
- After successful registration, the user receives their initial tokens automatically
- The system records the date and time of registration

---

### Login
**User story**
As a registered user, I want to log in securely so that I can access my cards, team, and leaderboard.

**Acceptance criteria**
- User can log in with valid credentials (username AND password)
- Invalid credentials show an error
- Session persists according to configured authentication rules
- Logged-out users cannot access pages that require authentication

---

### Password Reset Request
**User story**
As a user, I want to request a password reset link if I've forgotten my current password,
without that request alone being able to change or invalidate my actual password.

**Acceptance criteria**
- User that does not remember their password can request a reset via their username; a
  single-use reset link/code is sent to the email listed on their profile
- Requesting a reset does **not** change the account's actual password — the real password
  remains valid and usable until the reset is completed via the emailed link/code
- If no account matches, or the matched account has no email, the endpoint still returns
  success (no enumeration signal) and no email is sent

---

### Password Reset
**User story**
As a user, once logged in, I want to be able to reset my password.

**Acceptance criteria**
- Profile page has a flow for setting a new password
- Current password is required before a new one is accepted

---

### Logout
**User story**
As a logged-in user, I want to log out so that my account stays secure on shared devices.

**Acceptance criteria**
- User can log out from any page
- Session is invalidated on logout

---

### Admin-only Access
**User story**
As an admin, I want a protected admin area so that only authorized users can manage league configuration and season operations.

**Acceptance criteria**
- Only admin users can access the admin tab
- Non-admin cannot see the admin tab
- Admin status is verified server-side on every admin request — client-side state alone is not sufficient

---

### Profile Tab
**User story**
As a logged-in user, I want a profile page where I can update my account details.

**Acceptance criteria**
- User can change their display username; must remain unique
- User can change their password via a current password + new password form
- User can optionally link their account to an OpenDota player ID
- When a valid player ID is saved and the player exists in league data, the player's name and avatar are shown as a preview

---

### Require Login to View a Profile
**User story**
As an operator, I want `GET /profile/{user_id}` to require an authenticated session so that
the user base can't be enumerated anonymously by iterating IDs.

**Acceptance criteria**
- `GET /profile/{user_id}` returns 401 for an unauthenticated request, for any `user_id`
- Any logged-in user (not just the profile's owner) can still view any other user's profile —
  this is not restricted to "view your own profile only"
- The response shape and content for an authenticated request are completely unchanged
- No frontend changes are needed — the only existing call site always runs within an
  authenticated session already

---

### Profile Header Link
**User story**
As a logged-in user, I want to click my username in the header to open my Profile tab so that I can reach profile settings without hunting through the tab strip.

**Acceptance criteria**
- When logged in, the username in the top-right header is rendered as a button, not plain text
- Clicking the username button switches the active tab to Profile
- The button is visually distinct from surrounding text but cohesive with the header style
- When logged out the username button is hidden (no empty button visible)
- After a successful username change, the header button text updates immediately without a page reload

---

## Gmail SMTP Integration

### Configure Gmail as the SMTP Sender
**User story**
As an operator, I want to configure Gmail (or Google Workspace) as the SMTP server for
password reset emails, so that I can leverage a trusted, high-deliverability email service
without running my own mail server.

**Acceptance criteria**
- Setting `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD` (App Password), and `SMTP_TLS=true` results in password reset emails being sent successfully via Gmail STARTTLS
- The `.env.example` file contains a commented Gmail example block that operators can copy-paste and fill in
- The operator guide in `markdown/features/reference/gmail-smtp-integration.md` describes the App Password setup steps

### Support Gmail SSL Connection (Port 465)
**User story**
As an operator, I want the app to support Gmail's direct SSL connection mode on port 465,
so that I have the full range of Gmail SMTP options and am not limited to STARTTLS.

**Acceptance criteria**
- Setting `SMTP_SSL=true` causes the email client to use `smtplib.SMTP_SSL` instead of STARTTLS
- `SMTP_SSL=true` with `smtp.gmail.com:465` and a valid App Password sends email successfully
- `SMTP_SSL` and `SMTP_TLS` are mutually exclusive: when `SMTP_SSL=true`, the `SMTP_TLS` value is ignored
- The `SMTP_SSL` env var is documented in `.env.example` and `markdown/features/reference/commands.md`

## Temporary Password Expiry

### Temporary Password Expiry
**User story**
As a user, I want temporary passwords issued via the forgot-password flow to expire after a
set period so that my account is not left permanently accessible via a temporary credential
if I forget to change my password.

**Acceptance criteria**
- A temporary password expires after `TEMP_PASSWORD_TTL_HOURS` hours (default: 24)
- Attempting to log in with an expired temporary password returns 401 with a clear message prompting the user to request a new reset
- `temp_password_expires_at` is cleared (set to NULL) when the user successfully changes their password via `PUT /profile/password`
- The expiry timestamp is stored in the `users` table and covered by a schema migration

### Accurate Password Reset Email
**User story**
As a user, I want the password reset email to accurately state that my previous password
has been invalidated so that I understand the security implications of the request
immediately.

**Acceptance criteria**
- The email body states that the previous password is no longer valid and the temporary password expires after the configured TTL
- The email does not contain the incorrect statement that the password change is deferred until login

---

## Rate Limiting

### Global Rate Limiting Baseline
**User story**
As an operator, I want every endpoint to enforce a baseline request-rate limit so that no
single client can flood the app with requests regardless of which endpoint they target.

**Acceptance criteria**
- A default per-IP rate limit applies globally to every route via a single middleware
  registration, not per-endpoint opt-in
- Exceeding the limit returns HTTP 429 with a `{"detail": "..."}` body matching the app's
  existing error response shape (not slowapi's default `{"error": "..."}` shape)
- The limit is configurable via `RATE_LIMIT_GLOBAL` (default `200/minute`) so operators can
  tune it without a code change
- The default is generous enough that Docker's own healthcheck (`GET /health` every 30s) and
  normal frontend polling are never blocked by legitimate traffic

### Brute-Force Protection on Login
**User story**
As a security-conscious operator, I want `POST /login` to reject excessive attempts so that
an attacker cannot brute-force a password by sending unlimited login requests.

**Acceptance criteria**
- `POST /login` enforces a stricter per-IP limit than the global baseline, configurable via
  `RATE_LIMIT_LOGIN` (default `5/minute`)
- Independently of IP, repeated failed login attempts against the same username within a
  rolling window trigger a temporary per-username lockout, configurable via
  `LOGIN_LOCKOUT_THRESHOLD` (default `10` attempts) and `LOGIN_LOCKOUT_WINDOW_SECONDS`
  (default `300`) — this catches an attacker rotating source IPs against one account, which
  the per-IP limit alone would not
- A successful login for a username resets that username's failed-attempt counter
- Exceeding either limit returns a generic rate-limit message that does not reveal whether
  the submitted username exists

### Rate Limiting on Registration
**User story**
As an operator, I want `POST /register` to enforce a stricter per-IP limit than the baseline
so the endpoint can't be used to mass-create accounts or probe for taken usernames/emails via
its 409 conflict response.

**Acceptance criteria**
- `POST /register` enforces a per-IP limit configurable via `RATE_LIMIT_REGISTER` (default
  `5/minute`), stricter than the global baseline
- Exceeding the limit returns 429 with the same `{"detail": "..."}` shape as other
  rate-limited responses

### Rate Limiting on Forgot Password
**User story**
As an operator, I want `POST /forgot-password` to enforce a stricter per-IP limit so the
endpoint's existing username-enumeration-safe design isn't undermined by unlimited automated
requests from one source.

**Acceptance criteria**
- `POST /forgot-password` enforces a per-IP limit configurable via
  `RATE_LIMIT_FORGOT_PASSWORD` (default `3/minute`), stricter than the global baseline
- The endpoint's existing behavior (always returning `{"status": "ok"}` regardless of whether
  the username exists, and the bcrypt timing-equalization on the fast-exit path) is unchanged
- Per-account cooldown independent of source IP, and the password-overwrite-before-verification
  issue, are explicitly out of scope here — see GitHub issues #122 and #123
- If the user did not request the reset, the email advises them to contact support immediately

---

### Per-Account Cooldown on Forgot Password
**User story**
As an operator, I want `POST /forgot-password` to allow at most one password-reset email per
account within a cooldown window, independent of source IP, so that an attacker spread across
multiple IPs (or simply patient) can't repeatedly spam a target's inbox once the per-IP limit
resets.

**Acceptance criteria**
- A second `/forgot-password` request for the same username within
  `FORGOT_PASSWORD_COOLDOWN_SECONDS` (default `300`) of the first does not send another email
  or issue another temporary password, even from a different source IP
- The suppressed request still returns `{"status": "ok"}` — identical to both the "username
  doesn't exist" and "email successfully sent" responses, so no new information about account
  existence or cooldown state is exposed by the response body
- The cooldown is keyed by the submitted username string, populated only when the username
  resolves to a real account (the existing nonexistent-username fast-exit path is unchanged)
- The cooldown is configurable via `FORGOT_PASSWORD_COOLDOWN_SECONDS` and is independent of,
  and stacks with, the existing per-IP `RATE_LIMIT_FORGOT_PASSWORD` limit from issue #121 —
  either one suppressing a request is sufficient, neither depends on the other
- A legitimate user who didn't receive the first email (e.g. spam filter, typo'd address they
  then fixed via support) is not permanently blocked — the cooldown expires on its own after
  the configured window, no admin action needed

---

## Password Reset Token Flow

### Request a Password Reset Without Touching the Real Password
**User story**
As a user, I want requesting a password reset to leave my actual password untouched until I
complete the reset myself, so that no one else can lock me out of my account just by knowing my
username.

**Acceptance criteria**
- `POST /forgot-password` no longer sets `user.password_hash`, `must_change_password`, or
  `temp_password_expires_at` — the account's real credentials are completely unaffected by the
  request itself
- A single-use `PasswordResetToken` is created for the account, invalidating any prior unused
  token for that same user
- The token's validity window is configurable via `PASSWORD_RESET_TOKEN_TTL_HOURS` (default
  `1`)
- An email is sent containing both a clickable link (if `APP_BASE_URL` is configured) and the
  raw token as a manual-entry fallback (always included)
- The email wording reflects that the current password remains valid and nothing changes until
  the reset is completed
- The endpoint's existing behavior is otherwise unchanged: always returns `{"status": "ok"}`
  regardless of username/email existence, the bcrypt timing-equalization fast-exit is
  preserved, and the existing per-IP limit (issue #121) and per-username cooldown (issue #122)
  both continue to apply

---

### Complete a Password Reset with a Valid Token
**User story**
As a user, I want to actually set a new password using the link or code I was emailed, so that
I can recover my account without anyone else being able to trigger the change on my behalf.

**Acceptance criteria**
- A new `POST /reset-password` endpoint accepts a token and a new password (same
  `min_length=6, max_length=128` constraint used elsewhere)
- A valid, unexpired token sets the new password, clears any legacy
  `must_change_password`/`temp_password_expires_at` state on the account, deletes the token
  (single-use), and returns `{"status": "ok"}`
- An invalid, already-used, or expired token returns 400 with a clear error and makes no
  change to any account
- The action is recorded in the audit log (`password_reset_completed`)

---

### Reset Password UI
**User story**
As a user who clicked the reset link in my email, I want the app to recognize it and let me set
a new password directly, so I don't have to manually construct any requests myself.

**Acceptance criteria**
- Loading the app with a `?reset_token=...` query parameter automatically opens a "Set new
  password" modal with the token pre-filled, and the URL parameter is cleared from the visible
  address bar
- The same modal also accepts manual token entry, for the `APP_BASE_URL`-unset fallback case
  where the email only contains a raw code
- The existing "Forgot password" modal's copy is updated to describe a reset link/code being
  sent, not a temporary password

---

## Session Revocation

### Password Changes Log Out Other Sessions
**User story**
As a player, I want changing or resetting my password to end every other session on my account so that someone who stole my session cookie loses access.

**Acceptance criteria**
- `users.session_version` is an integer, default 0, added by migration `028_users_session_version`
- `POST /login` and `POST /register` store the user's current `session_version` in the session
- `PUT /profile/password` increments `session_version` and updates the current session to the new value, so the requester stays logged in and every other session gets 401 on its next request
- `POST /reset-password` increments `session_version`, so every existing session of that user gets 401
- A session whose stored version does not match the database, or that has no stored version, gets 401 from every route that uses `get_current_user`
- A session for a user id that no longer exists gets 401

### Log Out Everywhere
**User story**
As a player, I want a "Log out everywhere" button so that I can end sessions on devices I no longer have.

**Acceptance criteria**
- `POST /logout-everywhere` requires login, increments the caller's `session_version`, clears the current session, and returns `{"status": "ok"}`
- It writes a `user_logout_everywhere` audit entry
- After it, a second session of the same user gets 401 from `GET /me`
- Without a session it returns 401
- The Profile tab shows a "Log out everywhere" button. On success the page returns to the logged-out state

### Admin Force Logout
**User story**
As an admin, I want to force-log-out a user so that I can cut off a compromised or abusive account immediately.

**Acceptance criteria**
- `POST /users/{user_id}/force-logout` requires admin, increments that user's `session_version`, and returns `{"user_id", "username"}`
- It writes an `admin_force_logout` audit entry naming the target user
- An unknown `user_id` returns 404. A non-admin gets 403
- Forcing your own logout is allowed and ends your own sessions too
- The admin Users table shows a "Force logout" button per user, with a confirmation prompt

### All Session Checks Go Through One Place
**User story**
As a developer, I want every session-based check to validate the session version so that no route can be reached with a revoked cookie.

**Acceptance criteria**
- `get_current_user` loads the user from the database and returns `user_id`, `username` and `is_admin` from the database row, not from the cookie
- `get_session_user` in `backend/twitch.py` (used by `POST /twitch/link-code`) uses the same check *(both retired in #160; the session-cookie Twitch routes in `twitch_oauth.py` use `get_current_user`)*
- The optional-login paths of `GET /deck` and `GET /deck/booster` treat a revoked session as logged out
- The frontend treats a 401 from `GET /me` as logged out and clears the stored username and admin flag, instead of showing a stale logged-in header

### Configurable Session Lifetime
**User story**
As an operator, I want to set the session lifetime so that longer sessions (issue #117) can be enabled once revocation exists.

**Acceptance criteria**
- `SESSION_MAX_AGE_SECONDS` sets the session cookie `max_age`. Default `86400` (unchanged behaviour)
- A non-integer or non-positive value fails startup with a clear error
- The variable is documented in `.env.example` and the feature doc, with a note that revocation makes a longer value safe

> Since issue #117 (Longer Sessions below), session checks use server-side `user_sessions` rows instead of the session version, and `SESSION_MAX_AGE_SECONDS` is a deprecated alias for `SESSION_ABSOLUTE_SECONDS` (default 30 days).

---

## Longer Sessions

### Stay Logged In While Active
**User story**
As a player, I want to stay logged in while I keep using the site so that I don't have to log in again every day.

**Acceptance criteria**
- A player session stays valid until it has had no authenticated request for `SESSION_IDLE_SECONDS` (default `1209600`, 14 days), or until `SESSION_ABSOLUTE_SECONDS` (default `2592000`, 30 days) after login, whichever comes first
- Both limits are checked on the server against the session row (`last_seen_at`, `created_at`), not only by the cookie's lifetime
- `last_seen_at` is updated at most once per `SESSION_TOUCH_SECONDS` (default `300`)
- A session past either limit gets 401 on its next request, and its row is deleted

### Logout Ends the Session on the Server
**User story**
As a player, I want logging out to end my session for real so that a copy of my cookie can't be used afterwards.

**Acceptance criteria**
- Each login creates a `user_sessions` row with a new random session ID; the cookie holds only that ID
- `user_sessions` stores the SHA-256 hash of the session ID, never the ID itself
- `POST /logout` deletes the current session row and clears the cookie; replaying the old cookie afterwards gets 401
- `POST /logout-everywhere`, a password change (all other sessions), a password reset (all sessions) and admin force logout delete the matching rows. Their behaviour stays as in #119
- A cookie whose session ID has no row, including every cookie issued before this release, gets 401

### New Session ID on Login and Privilege Change
**User story**
As an operator, I want a fresh session ID whenever a user's privileges or credentials change so that an old or planted cookie can't inherit them.

**Acceptance criteria**
- Login and register always create a new session row and cookie, even if a valid session cookie was sent
- Changing your own password replaces the current session with a new one (new ID) and deletes all others
- Toggling a user's admin flag deletes all of that user's sessions, so their next login starts with the limits for their new role
- The cookie is named `__Host-session` when `HTTPS_ONLY=true` (`Secure`, `Path=/`, no `Domain`), and `session` otherwise for local development. `HttpOnly` and `SameSite=Lax` stay

### Shorter Sessions and Re-Authentication for Admins
**User story**
As an operator, I want admin sessions to be short and destructive admin actions to ask for the password again so that a stolen admin cookie is worth very little.

**Acceptance criteria**
- An admin's session uses `ADMIN_SESSION_IDLE_SECONDS` (default `7200`, 2 hours) and `ADMIN_SESSION_ABSOLUTE_SECONDS` (default `43200`, 12 hours) instead of the player limits
- `POST /reauth` with `{"password"}` checks the current user's password and stores `reauth_at` on the session row. It shares the login lockout and rate limit, and writes an `admin_reauth` audit entry on success and on failure
- These endpoints need a `reauth_at` within `ADMIN_REAUTH_SECONDS` (default `600`, 10 minutes), and otherwise return 403 with `{"detail": "reauth_required"}`:
  - `POST /admin/season/end` and `POST /admin/season/reset`
  - `DELETE /admin/leagues/{league_id}/data`
  - `POST /admin/backups`, `GET /admin/backups` and `GET /admin/backups/{filename}`
  - `POST /users/{user_id}/toggle-admin`
- On `reauth_required` the admin panel shows an in-page password prompt, retries the action once confirmed, and shows the error if the password is wrong. It never uses `confirm()` or `prompt()`
- Non-destructive admin endpoints keep working without re-authentication

### See and End My Sessions
**User story**
As a player, I want to see where I'm signed in and end a session I don't recognise so that I stay in control of my account.

**Acceptance criteria**
- `GET /sessions` lists the caller's sessions with created time, last active time, and which one is the current device. It never returns the session ID or its hash, only an opaque row handle
- `DELETE /sessions/{id}` ends one of the caller's own sessions; another user's session id returns 404
- The Profile tab lists the sessions with a "Sign out" button per row, next to "Log out everywhere"
- Expired session rows are deleted by the daily maintenance loop

### Operators Can Tune and Audit the Limits
**User story**
As an operator, I want every limit configurable and documented so that I can match them to my deployment's risk.

**Acceptance criteria**
- `.env.example`, `markdown/features/core/auth.md` and the feature doc describe:
  - `SESSION_IDLE_SECONDS`, `SESSION_ABSOLUTE_SECONDS` and `SESSION_TOUCH_SECONDS`
  - `ADMIN_SESSION_IDLE_SECONDS`, `ADMIN_SESSION_ABSOLUTE_SECONDS` and `ADMIN_REAUTH_SECONDS`
  - their defaults, and the accepted-risk note for the 14-day player idle limit
- Startup fails with a clear error when a value is not a positive integer, when an idle limit is larger than its absolute limit, or when `SESSION_TOUCH_SECONDS` is not smaller than the admin idle limit
- `SESSION_MAX_AGE_SECONDS` from #119 is still accepted as an alias for `SESSION_ABSOLUTE_SECONDS`, with a startup warning

## Password Manager Autofill

### Password Manager Fills the Login
**User story**
As a player who uses a password manager, I want it to fill my username and password in the login popup so that I can log in without typing them.

**Acceptance criteria**
- `#loginUsername` and `#loginPassword` sit inside one `<form id="loginForm" autocomplete="on">` in `#loginModal`.
- `#loginUsername` has `name="username"`, `autocomplete="username"`, `autocapitalize="none"` and `spellcheck="false"`.
- `#loginPassword` has `name="password"` and `autocomplete="current-password"`.
- The Login button is `type="submit"`. Pressing Enter in either field submits the form once, so the old `onkeydown` Enter handlers are removed.
- The form's submit handler calls `preventDefault()` and then `login()`. The page doesn't reload, and the request is the same `POST /login` as before.
- "Forgot password" and "Create new account" are `type="button"`, so they never submit the login form.
- **Failure path:** a failed login still shows the error in `#loginStatus`, keeps the typed username and password (as today; neither field is cleared on failure), and doesn't reload the page.

### Only the Login Looks Like a Login
**User story**
As a player, I want my password manager to treat each password field correctly so that it fills the login and offers to save new passwords in the right places.

**Acceptance criteria**
- **Registration** (`#registerModal`): one `<form id="registerForm">`. Fields: `#regUsername` with `autocomplete="username"`, `#regEmail` with `type="email"` and `autocomplete="email"`, `#regPassword` with `autocomplete="new-password"`. Create account is `type="submit"`; Back to login is `type="button"`.
- **Password reset** (`#resetPasswordModal`): one `<form>`. Fields:
  - `#resetToken` with `autocomplete="one-time-code"`,
  - `#resetNewPassword` with `autocomplete="new-password"`,
  - a visually hidden, read-only username field with `autocomplete="username"`, so managers store the new password under the right login. It's prefilled from the username entered on the forgot-password step when known, and empty otherwise (for example when the reset link is opened from the email).
- **Profile change password**: one `<form>`. Fields: `#pwCurrent` with `autocomplete="current-password"`, `#pwNew` with `autocomplete="new-password"`, and a visually hidden, read-only username field with `autocomplete="username"` holding the logged-in username.
- **Admin re-login** (`#reauthModal`): one `<form>`. `#reauthPassword` keeps `autocomplete="current-password"` and gains a visually hidden, read-only username field (`autocomplete="username"`, the logged-in username), so it pairs with the same saved login and isn't mistaken for a separate login.
- **Every password input** in `index.html` is inside a `<form>` and has an `autocomplete` value of `current-password` or `new-password`. No password input lacks one. A static test checks this, which is the failure path.
- **Hidden helper fields** are visually hidden with a class (not `display:none`, which some managers ignore). They aren't focusable (`tabindex="-1"`) and are `aria-hidden="true"`, so keyboard and screen-reader users don't meet them.

### No Change for Everyone Else
**User story**
As a player who types my password, I want the login and the other forms to behave exactly as before so that the fix doesn't break anything.

**Acceptance criteria**
- Every form submits through its existing function (`login()`, `register()`, `submitResetPassword()`, `changePassword()`, `submitReauth()`). Each fires once per submit, with no page reload or URL change, and none of them sends a password in the URL.
- The visible layout of the popups and the profile page is unchanged.
- After a successful login, the password field is cleared as today (the username stays, as before). Password managers that watch the submit event get the chance to offer saving or updating.
- **Failure path:** a form submit that fails validation, such as an empty username, shows the same error as today.

---

## Steam Login (#150)

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
- On success, `users.steam_id` is set and `player_id` becomes the verified Steam32 id, replacing any self-reported value. The action is audited as `steam_linked`, and the callback redirects to `/#profile?steam=linked`.
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
- **Failure path:** a direct `POST /register` in `steam_signup` mode answers 404 and creates nothing. An unknown `LOGIN_METHOD` value is logged and treated as `password`, except `steam` (issue #172, not built yet), which is logged as not available yet and treated as `steam_signup`, so it never reopens registration. `LOGIN_METHOD` is read at call time.

### Admins Come In Through Steam
**User story**
As the operator, I want admins to be named by Steam ID, so that a deploy's admins don't depend on passwords and existing admins keep their rights after linking Steam.

**Acceptance criteria**
- A new env var, `SEED_ADMIN_STEAM_IDS`: comma-separated Steam64 IDs. An entry that isn't exactly 17 digits is logged and skipped, and start-up continues.
- A verified Steam sign-in or link whose Steam ID is in the list makes the account an admin. A first-time Steam ID is created as an admin after the display-name step; an existing account is promoted. This is audited as `admin_seeded_from_env` (written only for Steam seeding; password seeding from `SEED_ADMIN_USERNAME` is not audited).
- Removing an ID from the list does not demote the account. Demotion stays the existing audited admin toggle, and the docs say so.
- A password admin who links Steam keeps admin rights.
- Destructive admin actions ask the admin to type the action name in the confirmation, in addition to the recent re-auth. The backend checks a `confirm` value (JSON body field, or query parameter) equal to the action name and otherwise answers 400 `confirmation_required`. This covers season end (`END SEASON`), season reset (`RESET SEASON`), the admin toggle (`CHANGE ADMIN`), token grants (`GRANT TOKENS`, which now also needs the recent re-auth), DB backup download (`GET /admin/backups/{filename}?confirm=DOWNLOAD BACKUP`) and deleting a Twitch viewer account (`DELETE /admin/users/{id}`, which only deletes soft accounts; `DELETE USER`).
- Admin accounts without a password re-authenticate through Steam (`purpose=reauth`, with an optional `return_tab` of `profile` or `admin`, never a free URL), which marks the session only when the verified Steam ID equals the admin's, and returns to `/#<tab>?steam=reauth_ok`. Connect Twitch, merge and Disconnect (#160) accept the same Steam re-auth for passwordless players.
- The docs require Steam Guard's mobile authenticator for every listed admin, and describe how to demote an admin quickly if their Steam account is compromised.
- Demo accounts are marked by `users.is_demo` (migration 033, set by `POST /admin/demo/seed-accounts`; earlier `demoN@demo.local` accounts are flagged by the migration). They keep their passwords, never link Steam and are never matched by the Steam callback.
- **Failure path:** an unlisted Steam ID signs in as a normal player. A demo account can never become an admin, neither from `SEED_ADMIN_STEAM_IDS` nor through the admin toggle (409).

---

## Impersonation Hardening (#169)

### Usernames Are Unique Regardless of Case
**User story**
As a player, I want nobody else to register a name that differs from mine only in letter case, so that people can't pose as me with `ville` when I'm `Ville`.

**Acceptance criteria**
- `POST /register`, `PUT /profile/username`, `POST /auth/steam/signup`, env admin seeding and demo seeding treat names that differ only in case as the same name. A taken name is refused with 409 "Username already taken".
- A shared helper, `auth.username_taken(db, name, exclude_user_id=None)`, compares `lower(username)`, and every one of these places uses it.
- Migration `034` adds a unique index on `lower(username)`. It first checks for case-insensitive duplicates; if any exist, it skips the index and logs a warning naming the user ids.
- Twitch viewer soft accounts, which have no username, are unaffected.
- **Failure path:** registering `ville` while `Ville` exists answers 409 and creates nothing. Renaming yourself from `Ville` to `VILLE` is allowed, because the account excluded from the check is your own.

### Reserved Words Can't Be Used in New Names
**User story**
As an admin, I want names like `admin`, `kanaliiga` or `support` to be unavailable, so that players can't pose as staff or the league.

**Acceptance criteria**
- `auth.check_reserved`, called by the handlers, refuses a new name whose normalised form contains a reserved word, with 422 "This name is reserved". `check_username` (the Pydantic field validator) keeps only the ASCII format check. The normalised form is lower-case, with `0→o`, `1→i`, `3→e`, `4→a`, `5→s`, `7→t`, `rn→m`, `vv→w`, and `_` and `-` removed.
- The list comes from `RESERVED_USERNAME_WORDS` (comma-separated). Default: `admin,kana,liiga,support,official,staff,mod`. Entries are normalised like names (lower-case, look-alikes mapped, `_` and `-` removed), so `m0d` or `kana_liiga` still match. A value with no usable entry (unset, blank or only commas) uses the default, so the check can't be switched off by accident.
- The check applies to registration, renames, the Steam sign-up and demo seeding. It doesn't apply to env admin seeding, so an operator can still name a seeded admin `admin`.
- Existing accounts keep their names. They still log in, and saving the unchanged name on Profile succeeds: a rename skips the reserved check when the new name equals the current one ignoring case.
- **Failure path:** `SuperAdmin1`, `4dmin`, `Kana_Liiga` and `rn0d` are refused. An existing account named `admin_old` still logs in.

### Real Admins Carry a Badge
**User story**
As a player, I want to see at a glance who is really an admin, so that a look-alike name can't fool me.

**Acceptance criteria**
- Every response row that shows another user's name carries `is_admin` (boolean): the roster, season and weekly leaderboards, the season archive standings, and `GET /profile/{user_id}`. Roster leaderboard rows also gain the user `id`.
- The website shows an **ADMIN** badge next to those usernames: the season and weekly leaderboards, past season standings, and the player's own Profile (the website has no view of another user's profile). It uses the design system (display type, uppercase, the accent colour, a 2 px radius, no pill), and is visually distinct from user tags.
- No user or tag can produce the same badge: tags with the key or label `admin` are refused at tag creation.
- **Failure path:** a non-admin named `Admin_Helper` (an existing name) shows no badge.

### Profiles Don't Lend Out Other Players' Identities
**User story**
As a league player, I want my picture and Steam-linked id not to appear on someone else's profile just because they typed in my player id, so that nobody can pose as me or pull my Steam profile from Kana Cards.

**Acceptance criteria**
- `GET /profile/{user_id}` for another user:
  - never returns the numeric `player_id`;
  - returns `player_name` and `player_verified`, true when the account has a `steam_id` and a player id;
  - returns `player_avatar_url` only when `player_verified` is true.
- The profile shows the in-game name with "Verified with Steam" or "Self-reported", and the avatar only when verified.
- The player themselves (`GET /profile/{own id}`) and admins (checked against the database, not the session) still see the numeric id and the avatar. `GET /me` is unchanged regarding `player_id`.
- No other endpoint returns another user's `player_id`. A test checks every response that carries other users' data (leaderboards, weekly report, season archive, profile with its tags) and asserts that no row carrying a user identity (`id`/`user_id` with `username`) has a `player_id` key; card rows carrying a league player's id are fine. Another user's roster view stays admin-only.
- The privacy page says that a linked player id identifies a Steam account, and that Kana Cards shows it only to the player and to admins.
- **Failure path:** a profile with a self-reported id of a well-known player shows "Self-reported" and that player's name, with no avatar and no number.

### Renames Are Limited
**User story**
As an admin, I want players to be able to rename at most once a week, so that a name can't keep changing to imitate whoever is active.

**Acceptance criteria**
- `PUT /profile/username` refuses a change within `USERNAME_CHANGE_COOLDOWN_DAYS` (default 7) of the last one, with 429 and the date it becomes possible again.
- A successful change sets `users.username_changed_at`, a new column added in migration `034`.
- Saving the unchanged name, or changing only its letter case, doesn't count as a change.
- `USERNAME_CHANGE_COOLDOWN_DAYS=0` turns the limit off.
- `GET /me` and `PUT /profile/username` return `username_change_available_at` (Unix time, or null when a rename is allowed now or the cooldown is off). Profile shows "You can rename again on <date>" when it is set.
- **Failure path:** a second rename two days after the first answers 429 and keeps the current name.
