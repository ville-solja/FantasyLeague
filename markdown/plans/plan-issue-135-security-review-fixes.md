# Plan: Security Review Fixes (Issue #135)

## Context
An external manual review dated 2026-09-26, attached to issue #135 as `SECURITY_REVIEW.md`, lists 20 findings. On 2026-09-27 each finding was checked against the current code. 17 hold as written. Three need their severity adjusted:

- **#9 does not return HTTP 500.** The installed bcrypt 4.3.0 hashes a 100-byte password without error. It silently uses only the first 72 bytes. The real risk is the truncation, which is Low. bcrypt 5.x would raise, as the review describes, so capping at 72 bytes still fixes both.
- **#10 cannot happen in production.** Its second caller, `POST /admin/demo/clock`, returns 404 unless `DEMO_MODE=true`. Production runs a single maintenance thread.
- **#13 is partly blocked already.** Python's `email.message` refuses header values that contain CR or LF, so a crafted address makes the send fail rather than add a recipient. Strict validation is still cheap.

The Critical finding (#1) matters most before the Twitch extension is released publicly. Any channel that installs it gets a broadcaster JWT and can currently mint token drops for arbitrary match IDs.

### Triage

| # | Finding | Verified | Our severity | Decision |
|---|---|---|---|---|
| 1 | `/twitch/mvp` accepts any `match_id` and drops tokens for it | Yes | Critical | Fix (Story 1) |
| 2 | Player bio and hero names rendered unescaped | Yes | High | Fix (Story 2) |
| 3 | OpenDota names, avatar URLs, schedule fields rendered unescaped | Yes | High | Fix (Story 2) |
| 4 | Reset returns "ok" when the email fails to send | Yes | High | Fix (Story 3) |
| 5 | Audit log `action` and `detail` rendered unescaped | Yes | Medium | Fix (Story 2) |
| 6 | Floating `alpinejs@3.x.x`, no SRI on CDN scripts | Yes | Medium | Fix (Story 5) |
| 7 | Link code uses `random.choices` | Yes | Medium | Fix (Story 1) |
| 8 | No route limits on `/reset-password`, `/redeem`, `/twitch/link` | Yes | Medium | Fix (Story 4) |
| 9 | Passwords over 72 bytes | Partly: truncation, not 500 | Low | Fix (Story 3) |
| 10 | `auto_lock_weeks` race | Demo mode only | Low | Accept; documented |
| 11 | Season reset proceeds when backup returns `None` | Yes | Low | Fix (Story 5) |
| 12 | Tag key used in sticker file path | Yes | Medium | Fix (Story 5) |
| 13 | Email not checked for CR/LF | Yes; send fails rather than injects | Low | Fix (Story 3) |
| 14 | Public card image endpoint fetches and renders per call | Yes | Medium | Fix (Story 4) |
| 15 | Username change keeps old session name; no audit | Yes | Low | Fix (Story 4) |
| 16 | Unbounded `card_ids` and `player_ids` lists | Yes | Low | Fix (Story 4) |
| 17 | No cap on `grant_tokens` amount or audit-log `limit` | Yes | Low | Fix (Story 4) |
| 18 | Reset tokens stay valid after a password change | Yes | Low | Fix (Story 3) |
| 19 | Container runs as root; backups world-readable | Yes | Low | Fix `chmod 600` on backups (Story 5); defer non-root `USER` |
| 20 | `/deck` and `/deck/booster` public | Yes | Info | Accept; intentional public game data |

The non-root container user (#19) is deferred, not rejected. It needs the host's `./data` directory re-owned during a deploy, so it belongs in the hoster's deploy notes.

Resolves GitHub issue #135.

## User Stories

### Twitch MVP and Token Drops Only for Real, Recent Matches
**User story**
As the league operator, I want MVP selection and token drops to accept only real, recent league matches so that no broadcaster can mint tokens or change scores for arbitrary match IDs.

**Acceptance criteria**
- `POST /twitch/mvp` returns 404 when the match does not exist, before any MVP row, bonus or drop is written
- It returns 403 when the match is not one of the series `GET /twitch/matches/current` offers, meaning a started match with ingested stats in one of the 5 most recent series. There is no separate monitored-league check (only monitored leagues are ingested)
- It returns 404 when the player did not play in that match
- When `TWITCH_MVP_CHANNEL_IDS` is set (comma-separated channel IDs), only those channels can set an MVP; others get 403, checked before the match and player checks so they learn nothing about IDs. Unset keeps today's behaviour for any channel
- The linking code in `POST /twitch/link-code` is generated with `secrets`, not `random`
- `POST /twitch/link` is limited to 10 requests a minute per client IP

### External Text Is Always Escaped
**User story**
As a player, I want names and bios from outside sources to be shown as plain text so that a crafted player name or generated bio cannot run script in my browser.

**Acceptance criteria**
- In the player profile, `bio_text`, hero names and every `facts.*` value are escaped with `_escHtml` or set with `textContent`
- Player names, team names, schedule `time`, `stream_label`, team labels and `data.error` in `app-players.js` are escaped
- `alt` attributes and the image `onerror` fallback in `app-roster.js` escape the player name
- `avatar_url` and other URLs placed in `src` or `href` are escaped and must start with `http://` or `https://`, otherwise they are dropped
- The admin audit log escapes `action` and `detail`
- A static test fails if any of these template sites interpolates the listed fields without `_escHtml`

### Reliable and Safe Password Reset
**User story**
As a player who forgot my password, I want the reset request to tell me when the email could not be sent, so that I'm not locked out behind a cooldown for an email that never arrived.

**Acceptance criteria**
- When a configured SMTP send fails (`send_email()` returns `False` with `SMTP_HOST` set, or raises), `POST /forgot-password` rolls back the new token and the cooldown stamp and returns 503. The previous token is not deleted
- Registration rejects email addresses that do not match `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`, including any with CR or LF, with 422
- `PUT /profile/password` deletes the user's outstanding reset tokens
- New-password fields in register, reset and change-password reject passwords longer than 72 UTF-8 bytes with 422. Login and the current password in change-password are exempt, so accounts created with longer passwords before the cap can still log in (bcrypt 4.x truncates the same way at hash and verify time)

### Abuse Limits on Public and Bulk Endpoints
**User story**
As the operator, I want brute-forceable and expensive endpoints to be rate-limited and bounded so that one client cannot guess codes or exhaust the server.

**Acceptance criteria**
- `POST /redeem` is limited to 5 requests a minute per user, and `POST /reset-password` to 10 a minute per IP
- `GET /cards/{card_id}/image` is limited to 60 requests a minute per IP
- `ReorderRequest.card_ids` accepts at most 500 items (the frontend sends the whole bench, which has no size limit) and `RemovePlayersBody.player_ids` at most 500; larger lists get 422
- `POST /grant-tokens` rejects amounts over 10,000, and `GET /audit-logs` caps `limit` at 1,000
- `PUT /profile/username` updates the session's username and writes a `username_changed` audit entry

### Deployment and File Hardening
**User story**
As the operator, I want third-party scripts pinned and local files protected so that a CDN change or a crafted tag key cannot affect users or the server.

**Acceptance criteria**
- Alpine.js is loaded from an exact version, and both CDN scripts carry `integrity` and `crossorigin="anonymous"`
- Tag keys must match `^[a-z0-9][a-z0-9_-]*$` when created, and `_apply_stickers` skips any path that resolves outside `STICKER_DIR`
- `POST /admin/season/reset` aborts with 500 and deletes nothing when `backup_sqlite_db()` returns `None`
- Backup files are written with mode `0600`

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/twitch.py` | Match, eligibility and player checks in `set_mvp`; optional channel allowlist; `secrets` link code; rate limit on `/link` |
| `frontend/app-players.js`, `frontend/app-roster.js`, `frontend/app-admin-ingest.js` | Escape every external string; validate URL schemes |
| `frontend/app-globals.js` | Add a `_safeUrl()` helper beside `_escHtml` |
| `backend/routers/auth.py` | Check `send_email()`'s result (503 only when SMTP is configured); strict email regex; 72-byte validator on new passwords (login exempt); rate limit `/reset-password` (`RATE_LIMIT_RESET_PASSWORD`) |
| `backend/routers/profile.py` | Delete reset tokens on password change; refresh session username and audit the rename |
| `backend/routers/admin_users.py` | Rate limit `/redeem`; cap `grant_tokens` amount |
| `backend/routers/cards.py` | Rate limit card images; cap `card_ids` |
| `backend/routers/admin_players.py`, `backend/routers/admin_season.py` | Cap `player_ids`; cap audit-log `limit`; abort reset without a backup |
| `backend/routers/admin_tags.py`, `backend/image.py` | Tag key pattern; sticker path containment |
| `backend/database.py` | Create the backup file with mode `0600` before copying, then `os.chmod(backup_path, 0o600)`; `scripts/backup-db.sh` copies under `umask 077` and runs `chmod 600` |
| `frontend/index.html` | Exact Alpine.js version and SRI on both CDN scripts |
| `.env.example` | Document `TWITCH_MVP_CHANNEL_IDS` and the four new env-configurable limits: `RATE_LIMIT_TWITCH_LINK`, `RATE_LIMIT_REDEEM`, `RATE_LIMIT_RESET_PASSWORD`, `RATE_LIMIT_CARD_IMAGE` |
| `backend/tests/test_issue_135_security_review_fixes.py` | Tests for every acceptance criterion |

No model change and no migration.

### Step 1 — Twitch MVP guard (Critical, do first)
Extract the series-window selection from `current_matches()` into a helper returning the eligible match IDs. `set_mvp` then checks, in order: channel is allowed when `TWITCH_MVP_CHANNEL_IDS` is set (403), match exists (404), match is eligible (403), and player has a stat row for that match (404). All checks run before `upsert_mvp`. Replace `random.choices` with `secrets.choice`. Rate-limit `/link` with `@limiter.limit(RATE_LIMIT_TWITCH_LINK)` (env-configurable, default `10/minute`) on a `link_account_route` wrapper.

### Step 2 — Escaping
Add `_safeUrl(u)`, which returns `u` only if it starts with `http://` or `https://`, otherwise `""`. Wrap every listed interpolation in `_escHtml(...)` and every URL in `_escHtml(_safeUrl(...))`. Render `bio_text` with `_escHtml` so line breaks are kept as text.

### Step 3 — Password reset
Replace the `try: send_email(...)` block with a check on the return value. On `False` with SMTP configured (`email_utils.email_configured()`), or an exception, `db.rollback()` and return 503; with `SMTP_HOST` unset keep the local-dev fallback (commit, `{"status": "ok"}`). Apply a shared Pydantic validator for the 72-byte cap (new-password fields only; login exempt) and the email regex.

### Step 4 — Limits and bounds
Use the existing `limiter` and `key_by_user_or_ip` from `backend/rate_limit.py`. Wrap the handlers in `*_route` functions the way roster mutations do, so direct calls in tests keep working. Use `Field(max_length=...)` on list fields and `Field(le=...)` or `Query(le=...)` on numbers.

### Step 5 — Hardening
- Pin Alpine.js to the exact version currently served and compute SRI hashes for both scripts. Record the pinned versions in a comment.
- Add the tag key pattern to `TagBody`, and a `Path.resolve()` containment check in `_apply_stickers`.
- `reset_season`: `if backup_path is None: raise HTTPException(500, ...)`.
- `backup_sqlite_db`: create the new file with mode `0600` (and chmod it after the copy).

### Step 6 — Docs
- Update `twitch-extension.md` for the MVP eligibility rules and `TWITCH_MVP_CHANNEL_IDS`, and `rate-limiting.md` for the new route limits.
- Add the triage table to the feature doc.
- Add the non-root container user to the hoster's deploy notes as a follow-up.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_135_security_review_fixes.py -v`, then the full suite. Bump the suite-size tripwire in `test_issue_85_split_admin_router.py`.
- `POST /twitch/mvp` with a random `match_id` returns 404 and writes no `twitch_token_drops` or `twitch_mvp` row. With a real match outside the series window it returns 403. With an eligible match it works as before.
- Seed a player named `<img src=x onerror=alert(1)>` with a bio containing the same text. The Players tab, the player and team popups, and My Team show the text literally.
- With SMTP pointed at a closed port, `POST /forgot-password` returns 503, and a second request is not blocked by the cooldown.
- Registering `a@b.com\nc@d.com` returns 422. A 73-byte password returns 422 on register and login.
- The browser console shows no SRI errors, and Alpine-driven UI such as the How to Play subtabs still works.
- On the host, a new backup file has mode `-rw-------`.
