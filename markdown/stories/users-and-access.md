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
