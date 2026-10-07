# Plan: Twitch, Steam and Account Hardening

## Context
A three-round security review (Twitch and Steam integrations, a second pass, then social engineering) found no way to reach a Steam inventory or act as a user on Twitch through the code, but it found fail-open defaults, a panel that trusts any configured backend URL, player-chosen names posted to Twitch chat, admin token actions without a password re-check, a reset flow that is easy to social-engineer, a username-only login lockout, easy impersonation and farmable token drops. This plan fixes the code findings in one pass, one step per sub-issue, and documents the operational ones.

Decisions taken with the product owner (2026-10-07):
- **Drops (#171):** only viewers who shared their Twitch identity (the JWT carries `user_id`) can win token drops.
- **Reset and lockout (#168):** implement now, although Steam-only login (#150) will later remove these flows.
- **Pinned backend origins (#164):** the app stays league-agnostic, so no domain is hard-coded. `package.sh` takes the allowed origins at build time; the production package lists only the production host, a test package can add the test host.
- **Usernames (#169):** case-insensitive uniqueness plus a configurable reserved-word list (generic default; a league adds its own words through the environment). No rename cooldown.

Assumptions:
- Team logo hosts (#171) are accepted rather than filtered: Twitch's image-domain allowlist for the extension already blocks unlisted hosts, and an app-side list risks breaking logos.
- The "growing delay" for per-username lockout (#168) is implemented as a much higher per-username ceiling next to the per-(username, IP) lockout; sleeping on the request would tie up server threads.
- Reset tokens are hashed in the existing `password_reset_tokens.token` column, so no migration is needed; outstanding plaintext tokens simply stop matching (they expire within an hour anyway).
- The optional daily `ebs_url` check (#164) and the admin-set display name (#166) are left out.

**Update after PR 174:** #169 and #171 shipped with the Steam login (PR 174) in their own designs (for #171, a minimum soft-account age instead of the identity share). This branch's versions of Steps 6 and 7 were dropped when merging `main`; the migration in Step 4 became `036_promo_codes_limits`.

Resolves GitHub issue #163 (sub-issues #164, #165, #166, #167, #168, #169, #170, #171).

## User Stories

### Panel Talks Only to the Approved Backend
**User story**
As a viewer, I want the Twitch panel to call only the backend it was approved with so that a leaked extension secret cannot redirect my Twitch token or show me someone else's messages.

**Acceptance criteria**
- `twitch-extension/ebs-origins.js` defines `EBS_ALLOWED_ORIGINS`; the repository copy is an empty list
- `package.sh <version> --ebs-origin <https-origin> [--ebs-origin …]` writes the listed origins into the packaged `ebs-origins.js`; packaging fails without at least one origin, or with a non-https origin, a path, or a trailing slash
- `extension.js` accepts the configured `ebs_url` only when it is `https:` and its origin is in `EBS_ALLOWED_ORIGINS`; otherwise it never calls it and the panel shows the "not available" state
- With an empty list, only the local dev harness (which sets `window.__EXT_DEV_HARNESS`) accepts any URL
- `set-ebs-url.sh` reads the secret only from the environment or the hidden prompt, has no pre-set secret variables, and never passes it on a command line

### Twitch Defaults Fail Closed
**User story**
As the league operator, I want the Twitch backend to refuse anything it was not explicitly configured to accept so that a missing setting cannot open MVP selection to every channel.

**Acceptance criteria**
- With `ENV=production` and an empty `TWITCH_MVP_CHANNEL_IDS`, `POST /twitch/mvp` returns 403 for every channel and startup logs a warning; outside production an empty list still allows any channel
- A correctly signed extension JWT without `exp` gets 401
- A JWT with `role: external` gets 403 on every `/twitch/*` route that takes a viewer token
- The invalid-token log line contains no secret length
- `TWITCH_LOCAL_DEV=true` refuses to start when `HTTPS_ONLY=true`

### No Phishing Text in Trusted Channels
**User story**
As a viewer or player, I want messages that come from the league itself to never carry links someone else chose so that I can trust them.

**Acceptance criteria**
- MVP chat announcements use a cleaned name: control, zero-width and bidi characters removed, at most 32 characters, and `Player {id}` when the name looks like a link
- The broadcaster's MVP picker shows the exact chat text before confirming
- An admin notification containing a URL that does not point to `APP_BASE_URL` is refused with 422

### Admin Token Actions Need a Fresh Password Check
**User story**
As the league operator, I want token-economy and broadcast actions to need a recent password check so that a stolen admin session cannot mint tokens or message every player.

**Acceptance criteria**
- Creating or deleting notifications, granting tokens, creating or deleting promo codes, creating or deleting token grant events and toggling tester status return 403 `reauth_required` without a recent `POST /reauth`, and the admin views prompt for the password
- Promo codes can have an optional expiry and a maximum number of redemptions
- `POST /redeem` answers unknown, expired and used-up codes with the same message

### Reset Codes and Lockouts Resist Abuse
**User story**
As a player, I want my password reset and login to resist other people so that nobody can talk me out of a reset code or lock me out of my account.

**Acceptance criteria**
- The reset email starts with a warning never to share the code
- A completed reset and a password change each send a "your password was changed" email
- The database stores only a SHA-256 hash of a reset token; the emailed link and code still work
- Failed logins lock out a username only from the IP they came from; a much higher per-username ceiling applies across all IPs
- A completed password reset clears the lockout for that username

### Harder to Impersonate Players and Admins
**User story**
As a player, I want to tell real admins and real league players apart from look-alikes so that I am not fooled by an impersonator.

**Acceptance criteria**
- Registering or renaming to a name that differs from an existing one only by letter case is refused
- Names containing a word from `RESERVED_USERNAME_WORDS` are refused for new registrations and renames; existing names keep working
- Admins carry a visible badge on the leaderboard and on profiles
- Another user's profile never shows a numeric player id or the claimed player's avatar, and marks the linked player as self-reported

### Token Drops Need the Identity Share
**User story**
As the league operator, I want only viewers who shared their Twitch identity to win token drops so that free alt accounts cannot farm tokens.

**Acceptance criteria**
- The drop pool includes only joined viewers whose account has a Twitch account id from the identity share
- The panel tells viewers that sharing their identity makes them eligible for drops
- Heartbeats from logged-out viewers write nothing, and heartbeats use the per-viewer rate limit
- When `TWITCH_EXTENSION_CLIENT_ID` is set, CORS accepts only that extension's origin

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/twitch.py` | fail-closed allowlist, `exp` and `role` checks, safe chat names, `chat_name` in matches, drop pool needs identity share, heartbeat limits |
| `backend/text_safety.py` | new: `clean_display_text`, `looks_like_url`, `contains_foreign_url` |
| `backend/main.py` | `TWITCH_LOCAL_DEV` + `HTTPS_ONLY` guard, startup warning, CORS regex from client id |
| `backend/routers/admin_notifications.py` | reauth, URL check |
| `backend/routers/admin_users.py` | reauth on token routes, promo expiry and cap, uniform redeem error |
| `backend/routers/auth.py` | reset email copy, change notice, hashed tokens, per-IP lockout, username rules |
| `backend/routers/profile.py` | username rules, change notice, profile data for others, admin flag |
| `backend/routers/leaderboard.py` | admin flag per row |
| `backend/auth.py` | `check_username_policy`, reserved words |
| `backend/models.py`, `backend/migrate.py` | `promo_codes.expires_at`, `promo_codes.max_redemptions` (migration 033) |
| `twitch-extension/ebs-origins.js`, `extension.js`, `package.sh`, `set-ebs-url.sh`, `dev-harness.html`, `*.html` | origin pin |
| `twitch-extension/live_config.js`, `panel.html`, `panel.js` | chat preview, drop eligibility text |
| `frontend/app-admin-*.js`, leaderboard and profile scripts | `adminFetch`, promo fields, admin badge, self-reported label |
| `.env.example`, docs | new variables, Steam key account, ops checklist |

### Step 1 — Twitch fail-closed defaults (#165)
- `_mvp_allowed_channels()` callers: in production (`ENV=production`) an empty set refuses every channel. Startup logs a warning once.
- `verify_twitch_jwt`: `options={"require": ["exp"]}`; refuse `role == "external"` with 403; log only the exception class.
- `main.py`: refuse `TWITCH_LOCAL_DEV=true` when `HTTPS_ONLY=true`.

### Step 2 — Pinned backend origins (#164)
- New `ebs-origins.js` (`var EBS_ALLOWED_ORIGINS = [];`) loaded before `extension.js` by every page and added to `package.sh` `FILES`.
- `package.sh` parses repeated `--ebs-origin`, validates `^https://[^/]+$`, stages the files in a temp dir with a generated `ebs-origins.js`, and zips from there.
- `extension.js` `_ebsUrlAllowed(url)` guards `_onCfgChanged`; the dev harness stub sets `window.__EXT_DEV_HARNESS = true`.
- `set-ebs-url.sh`: drop the pre-set variables, take the secret from `TWITCH_EXT_SECRET` in the environment or the hidden prompt, pass it to Python through the environment.

### Step 3 — Trusted-channel text (#166)
- `text_safety.py`: remove `Cc`/`Cf` characters (control, zero-width, bidi), collapse whitespace, cap length; URL-like = `://`, `www.`, or `.` followed by two or more letters at a word boundary.
- `_chat_safe_name(name, account_id)` used by the MVP chat text and returned as `chat_name` per player in `GET /twitch/matches/current`; `live_config.js` shows `Chat: "Match MVP: {chat_name}!"`.
- Notifications: URLs allowed only when they start with `APP_BASE_URL`.

### Step 4 — Admin reauth and promo codes (#167)
- `require_recent_reauth` on the routes in the issue table; switch the frontend calls to `adminFetch`.
- Migration `036_promo_codes_limits`: `expires_at INTEGER`, `max_redemptions INTEGER` (both nullable). Create form gets two optional fields; the list shows them.
- `/redeem`: one 404 message "Invalid or expired code" for unknown, expired and used-up codes; "already redeemed" stays 409 (it is the user's own state).

### Step 5 — Reset and lockout (#168)
- `PasswordResetToken.token` holds `sha256(token)`; `/reset-password` looks up by hash.
- Email copy warning first; `_send_password_changed_notice(user)` after reset and change (failures are logged, never block).
- Lockout keys: `(username, ip)` at `LOGIN_LOCKOUT_THRESHOLD`; username alone at `LOGIN_LOCKOUT_USERNAME_THRESHOLD` (default 100) in the same window; both cleared on success, the username keys cleared on a completed reset. `/reauth` uses the same check.

### Step 6 — Impersonation (#169)
- `check_username_policy(db, username, exclude_user_id)` in `auth.py`: case-insensitive clash → 409, reserved word → 422. Words of 4+ letters match anywhere in the lowercased name; shorter words match a whole part split on `_`, `-` and digits.
- `GET /profile/{id}` for another user: no `player_id`, no `player_avatar_url`, `player_self_reported: true`; `is_admin` added. Leaderboard rows carry `is_admin`; the frontend renders a small ADMIN badge.

### Step 7 — Drops and panel limits (#171)
- `_active_pool`: `AND u.twitch_account_id IS NOT NULL`.
- Heartbeat: return early for non-`U` ids; `@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)`.
- CORS: when `TWITCH_EXTENSION_CLIENT_ID` is set, `allow_origin_regex=^https://{re.escape(id)}\.ext-twitch\.tv$`.
- Panel copy: the share box says sharing makes the viewer eligible for MVP token drops.

### Step 8 — Operational documentation (#170)
- `.env.example`: `STEAM_API_KEY` must belong to a dedicated Steam account with no items; new variables `RESERVED_USERNAME_WORDS`, `LOGIN_LOCKOUT_USERNAME_THRESHOLD`.
- Feature doc: an operator checklist (2FA accounts, branch protection, registrar lock, secret handling, Steam key, official names, clone checks).

### Step 9 — Documentation
- Stories in `markdown/stories/security-review-fixes.md`, feature doc `markdown/features/reference/twitch-steam-account-hardening.md`, UI descriptions for the Twitch panel, admin and profile, `core/twitch-extension.md`, `core/auth.md`.

## Verification
- `cd backend && python -m pytest` passes, including `tests/test_issue_163_twitch_steam_account_hardening.py` and `tests/test_migrate.py`.
- `bash twitch-extension/package.sh 9.9.9` fails; `bash twitch-extension/package.sh 9.9.9 --ebs-origin https://example.org` builds a zip whose `ebs-origins.js` lists only that origin.
- In the dev harness the panel still loads with a localhost EBS URL.
- Manual: in production, set `TWITCH_MVP_CHANNEL_IDS` before deploying, or MVP selection is refused.
