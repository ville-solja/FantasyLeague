# Twitch, Steam and Account Hardening

Fixes from the 2026-10 security review of the Twitch and Steam integrations and of social-engineering risks (GitHub issue #163, sub-issues #164–#171; #169 and #171 shipped separately with PR 174, see below). The review found no way to reach a Steam inventory or to act as a user on Twitch through the code. These changes close fail-open defaults, make leaked secrets less useful, keep player-chosen text out of the league's trusted channels, and make impersonation and lockout abuse harder. The plan is `markdown/plans/plan-issue-163-twitch-steam-account-hardening.md`.

---

## What changed, by sub-issue

| Issue | Change | Where |
|---|---|---|
| #164 | The panel calls the configured backend URL only if its origin was baked into the package (`package.sh --ebs-origin`); `set-ebs-url.sh` keeps the secret off the command line and the screen | `twitch-extension/ebs-origins.js`, `extension.js`, `package.sh`, `set-ebs-url.sh` |
| #165 | Empty `TWITCH_MVP_CHANNEL_IDS` refuses every channel in production; extension JWTs must carry `exp`; `role: external` tokens are refused on viewer routes; no secret length in logs; `TWITCH_LOCAL_DEV` refused with `HTTPS_ONLY=true` | `backend/twitch.py`, `backend/main.py` |
| #166 | MVP names in chat and PubSub are cleaned (`chat_safe_name`); the MVP picker previews the chat text; admin notifications may only link to `APP_BASE_URL` | `backend/text_safety.py`, `backend/twitch.py`, `backend/routers/admin_notifications.py`, `live_config.*` |
| #167 | Recent password check for token grants, promo codes, token grant events, notifications and the tester toggle; promo code expiry and redemption cap; one answer for unknown, expired and used-up codes | `backend/routers/admin_users.py`, `backend/routers/admin_notifications.py`, migration `036_promo_codes_limits`, admin frontend |
| #168 | Reset email opens with a never-share warning; "password changed" email after a reset or change; reset tokens stored as SHA-256 hashes; login lockout per username **and** IP, with a high per-username ceiling | `backend/routers/auth.py`, `backend/routers/profile.py` |
| #169 | Shipped in PR 174 with the Steam login: see `reference/impersonation-hardening.md` | — |
| #170 | Operator checklist below; `.env.example` notes for the Steam key and extension secret | docs only |
| #171 | Shipped in PR 174: see `reference/twitch-panel-abuse-limits.md` | — |

---

## Pinned backend origins (#164)

`Twitch.ext.configuration.global` holds `ebs_url`, and anyone with the extension secret can rewrite it instantly, without a Twitch review. Before this change every panel would then have sent its viewers' Twitch tokens to whatever URL it named.

- `twitch-extension/ebs-origins.js` defines `EBS_ALLOWED_ORIGINS`. The repository copy is `[]`.
- `bash twitch-extension/package.sh <version> --ebs-origin <https-origin> [--ebs-origin …]` stages the packaged files in a temporary directory, writes the listed origins into that copy of `ebs-origins.js`, and zips it. It refuses to build without an origin or with an origin that is not `https://host[:port]` (no path, no trailing slash). The production package lists only the production host; a test build can add the test host. The app itself stays league-agnostic: no host is hard-coded.
- `extension.js` `_ebsUrlAllowed(url)` accepts the configured URL only when it is `https:` and its origin is in the list. With an empty list, only the local dev harness (which sets `window.__EXT_DEV_HARNESS = true`) accepts any URL. A refused URL is never called; the panel shows its "not available" state after the usual 8-second timeout.
- Changing the allowed origins therefore needs a new extension version and a Twitch review, which a leaked secret cannot provide.
- `set-ebs-url.sh` reads the client ID, secret and owner ID from the environment or prompts for them (the secret prompt is hidden). It no longer has fill-in variables in the tracked file, passes the secret to Python through the environment instead of `argv` (visible in `ps`), no longer prints the secret in `--debug` mode, and accepts only `https://` URLs.

## Fail-closed Twitch defaults (#165)

- `twitch.mvp_channel_allowed(channel_id)`: a listed channel is allowed; with an empty list, any channel outside production and **no** channel when `ENV=production`. `warn_if_mvp_channels_unset()` logs a warning at start-up in that case. **Set `TWITCH_MVP_CHANNEL_IDS` before deploying**, or MVP selection is refused.
- `verify_twitch_jwt` requires `exp`, logs only the exception class on an invalid token, and returns 403 `"Viewer token required"` for `role: external` (only this server signs those, for Twitch's PubSub and chat APIs).
- `main.py` refuses to start with `TWITCH_LOCAL_DEV=true` and `HTTPS_ONLY=true` together, a production signal independent of `ENV`.

## Text in trusted channels (#166)

`backend/text_safety.py`:

- `clean_display_text(value, max_len)` removes Unicode control and format characters (`Cc`, `Cf`: control, zero-width, bidi overrides), collapses whitespace and caps the length.
- `strip_invisible(value)` does the same for longer text but keeps line breaks and tabs.
- `looks_like_url(value)` is true for `://`, `www.`, or a dot followed by two or more letters at a word end.
- `foreign_urls(text, allowed_base)` lists link-like parts whose host differs from the host of `allowed_base`.

`twitch.chat_safe_name(name, account_id)` cleans the MVP name to at most 32 characters and replaces a link-like name with `Player {account_id}`. The chat announcement, the PubSub `player_name` and each player's `chat_name` in `GET /twitch/matches/current` use it; the MVP picker shows "Chat will say: "Match MVP: {chat_name}!"" before confirming.

`POST /admin/notifications` strips invisible characters and returns 422 when `foreign_urls(message, APP_BASE_URL)` is not empty.

## Admin reauth and promo codes (#167)

See `core/admin.md` (re-authentication list, promo codes, support rule). The frontend calls these routes through `adminFetch()`, which prompts for the password on `reauth_required`.

## Reset and lockout (#168)

See `core/auth.md` (`POST /login`, `POST /forgot-password`, `POST /reset-password`, `PUT /profile/password`). Lockout state is in memory: `_failed_login_attempts` (per username, ceiling `LOGIN_LOCKOUT_USERNAME_THRESHOLD`) and `_failed_login_attempts_by_ip` (per username and IP, `LOGIN_LOCKOUT_THRESHOLD`); stale keys are swept once a store passes 10 000 entries. The source IP is slowapi's `get_remote_address`, the same one the rate limits use.

## Impersonation (#169) and drops and panel limits (#171)

Both shipped with PR 174, which implemented them differently from this plan's first draft (for
example, token drops need a minimum soft-account age instead of the identity share). See
`reference/impersonation-hardening.md` and `reference/twitch-panel-abuse-limits.md`.

---

## Operator checklist (#170)

No code; confirm each item in issue #170.

**Accounts that hold the keys.** Use app-based or hardware 2FA (never SMS) and keep recovery codes offline on:
- the Twitch account that owns the extension (secrets, configuration, new versions);
- every GitHub account with push rights to the repository;
- the hosting / server account and its SSH keys (the `.env` holds every secret, plus the database and backups);
- the domain registrar and DNS;
- the mailbox behind `SMTP_*`, and each admin's own email (password resets).

**Repository.** Branch protection on `main` (required review and CI, no force-push). GitHub secret scanning with push protection on.

**Domain.** Registrar lock on.

**Secrets.**
- `TWITCH_EXTENSION_SECRET` lives only in the production environment (or a secret manager). List who can read it. To rotate: Twitch developer console → Extension Settings → Extension Secrets → create a new secret (the old one keeps working during the rollover), deploy it, then revoke the old one. Rotate at once if it was ever pasted into chat, a ticket, a CI log or a shared `.env`.
- `STEAM_API_KEY` belongs to a dedicated Steam account with no items and no trade history, never an admin's or the organisation's main account: a Web API key acts for its account, including that account's trade offers. To revoke and replace: steamcommunity.com/dev/apikey on that account.

**Team rule.** No secret, `.env`, backup or 2FA code is ever sent in Discord, Twitch or email, whoever asks. A request for one is treated as an attack and reported in the team channel. Admins follow the support rule in `core/admin.md`.

**Look-alikes.** Publish the official extension name and the one official domain on the site, in the Discord and in stream panels. Check Twitch for clone extensions now and then and report them; optionally register obvious typo domains.

**Twitch console.**
- URL Fetching Domains: exactly the origins the package was built with.
- Ship the origin pin in a new extension version (`package.sh <version> --ebs-origin …`); until that version is approved and installed, channels run the old panel without the check.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_MVP_CHANNEL_IDS` | *(empty)* | Channels allowed to set MVPs. Empty: none in production, any otherwise |
| `APP_BASE_URL` | *(empty)* | The only host admin notifications may link to |
| `LOGIN_LOCKOUT_THRESHOLD` | `10` | Failures per username and IP before that IP is locked out |
| `LOGIN_LOCKOUT_USERNAME_THRESHOLD` | `100` | Failures per username from all IPs before it is locked out everywhere |

## Tests

`backend/tests/test_issue_163_twitch_steam_account_hardening.py`, one class per sub-issue.
