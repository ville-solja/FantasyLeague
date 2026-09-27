# Security Review Fixes

Stories from the 2026-09-26 external security review (GitHub issue #135). The per-finding triage is in `markdown/plans/plan-issue-135-security-review-fixes.md`.

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


---

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


---

### Reliable and Safe Password Reset
**User story**
As a player who forgot my password, I want the reset request to tell me when the email could not be sent, so that I'm not locked out behind a cooldown for an email that never arrived.

**Acceptance criteria**
- When a configured SMTP send fails (`send_email()` returns `False` with `SMTP_HOST` set, or raises), `POST /forgot-password` rolls back the new token and the cooldown stamp and returns 503. The previous token is not deleted
- Registration rejects email addresses that do not match `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`, including any with CR or LF, with 422
- `PUT /profile/password` deletes the user's outstanding reset tokens
- New-password fields in register, reset and change-password reject passwords longer than 72 UTF-8 bytes with 422. Login and the current password in change-password are exempt, so accounts created with longer passwords before the cap can still log in (bcrypt 4.x truncates the same way at hash and verify time)


---

### Abuse Limits on Public and Bulk Endpoints
**User story**
As the operator, I want brute-forceable and expensive endpoints to be rate-limited and bounded so that one client cannot guess codes or exhaust the server.

**Acceptance criteria**
- `POST /redeem` is limited to 5 requests a minute per user, and `POST /reset-password` to 10 a minute per IP
- `GET /cards/{card_id}/image` is limited to 60 requests a minute per IP
- `ReorderRequest.card_ids` accepts at most 500 items (the frontend sends the whole bench, which has no size limit) and `RemovePlayersBody.player_ids` at most 500; larger lists get 422
- `POST /grant-tokens` rejects amounts over 10,000, and `GET /audit-logs` caps `limit` at 1,000
- `PUT /profile/username` updates the session's username and writes a `username_changed` audit entry


---

### Deployment and File Hardening
**User story**
As the operator, I want third-party scripts pinned and local files protected so that a CDN change or a crafted tag key cannot affect users or the server.

**Acceptance criteria**
- Alpine.js is loaded from an exact version, and both CDN scripts carry `integrity` and `crossorigin="anonymous"`
- Tag keys must match `^[a-z0-9][a-z0-9_-]*$` when created, and `_apply_stickers` skips any path that resolves outside `STICKER_DIR`
- `POST /admin/season/reset` aborts with 500 and deletes nothing when `backup_sqlite_db()` returns `None`
- Backup files are written with mode `0600`
