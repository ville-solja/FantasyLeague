# Security Review Fixes

Fixes for the 2026-09-26 external security review attached to GitHub issue #135. Each finding was checked against the code on 2026-09-27. The plan is `markdown/plans/plan-issue-135-security-review-fixes.md`; tests are in `backend/tests/test_issue_135_security_review_fixes.py`.

---

## Triage

| # | Finding | Our severity | Decision |
|---|---|---|---|
| 1 | `/twitch/mvp` accepts any `match_id` and drops tokens for it | Critical | Fixed |
| 2 | Player bio and hero names rendered unescaped | High | Fixed |
| 3 | OpenDota names, avatar URLs, schedule fields rendered unescaped | High | Fixed |
| 4 | Reset returns "ok" when the email fails to send | High | Fixed |
| 5 | Audit log `action` and `detail` rendered unescaped | Medium | Fixed |
| 6 | Floating `alpinejs@3.x.x`, no SRI on CDN scripts | Medium | Fixed |
| 7 | Link code uses `random.choices` | Medium | Fixed |
| 8 | No route limits on `/reset-password`, `/redeem`, `/twitch/link` | Medium | Fixed |
| 9 | Passwords over 72 bytes (bcrypt 4.x truncates; not a 500 as reported) | Low | Fixed |
| 10 | `auto_lock_weeks` race (demo mode only) | Low | Accepted |
| 11 | Season reset proceeds when backup returns `None` | Low | Fixed |
| 12 | Tag key used in sticker file path | Medium | Fixed |
| 13 | Email not checked for CR/LF (send fails rather than injects) | Low | Fixed |
| 14 | Public card image endpoint renders per call | Medium | Fixed (rate limit) |
| 15 | Username change keeps old session name; no audit | Low | Fixed |
| 16 | Unbounded `card_ids` and `player_ids` lists | Low | Fixed |
| 17 | No cap on `grant_tokens` amount or audit-log `limit` | Low | Fixed |
| 18 | Reset tokens stay valid after a password change | Low | Fixed |
| 19 | Container runs as root; backups world-readable | Low | Backups fixed; non-root user deferred |
| 20 | `/deck` and `/deck/booster` public | Info | Accepted |

## Twitch MVP eligibility

`POST /twitch/mvp` (`set_mvp` in `backend/twitch.py`) runs these checks, in order, before any MVP row, score bonus, token drop or audit entry is written:

1. When `TWITCH_MVP_CHANNEL_IDS` is set, the channel from the JWT is in the list, or 403. Unset keeps the old behaviour: any channel with the extension can set an MVP. This runs first, so a channel outside the list gets the same 403 for every request and learns nothing about which match or player IDs exist.
2. The match exists, or 404.
3. The match is one `GET /twitch/matches/current` offers, or 403. Both endpoints use `_current_series()`: started matches with ingested stats, grouped into series by team pair, 5 most recent series. `_eligible_mvp_match_ids()` flattens that to match IDs. The output of `GET /twitch/matches/current` is unchanged.
4. The player has a `player_match_stats` row for the match, or 404.

Monitored-league status is not checked separately: eligibility is exactly the 5-series window. Only monitored leagues are ingested, and adding a league filter would have changed what `GET /twitch/matches/current` shows.

The link code from `POST /twitch/link-code` is now drawn with `secrets.choice`, and `POST /twitch/link` is limited to 10 requests a minute per IP.

## Escaping

`_safeUrl(u)` in `frontend/app-globals.js` returns `u` only when it starts with `http://` or `https://`, otherwise `""`. `_escHtml` now also escapes `'`.

- `app-players.js`: `bio_text` (rendered with `white-space: pre-wrap` so line breaks survive), hero names, every `facts.*` value, player and team names in the tables, player modal and team modal, schedule `time`, `stream_label`, unlinked team labels and `data.error` go through `_escHtml`. Avatar, stream and hero-icon URLs go through `_escHtml(_safeUrl(...))`; avatars set via `.src` go through `_safeUrl`.
- `app-roster.js`: the card `alt` escapes the player name. The image `onerror` fallback no longer builds HTML inline; it calls `_cardImgFallback(this)`, which builds the placeholder with `textContent` from a `data-player-name` attribute.
- `app-admin-ingest.js`: audit log `action` and `detail`.

Static checks in the test file parse every `${...}` in these files and fail if a listed field is used outside `_escHtml(...)`, `playerLink(...)`, `teamLink(...)` or `heroSection(...)`.

## Password reset and passwords

- `POST /forgot-password` checks `send_email()`'s return value. When SMTP is configured (`email_utils.email_configured()`) and the send returns `False`, or the send raises, it rolls back the new token and the audit row, restores the previous token, clears the per-username cooldown stamp, and returns 503. With `SMTP_HOST` unset, `send_email()` returns `False` without trying; the request still commits and returns `{"status": "ok"}` (the local-dev fallback).
- **Enumeration trade-off:** a 503 only happens for an existing username with an email on file, and only while a configured send is failing. During an SMTP outage the 503 therefore tells a caller the account exists. This is accepted so that real users learn the email didn't send instead of waiting out the cooldown for an email that never arrives.
- `RegisterBody.email` must fully match `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`, so CR, LF and spaces are rejected with 422.
- New-password fields on `POST /register`, `POST /reset-password` and `PUT /profile/password` reject passwords over 72 UTF-8 bytes with 422 (`check_password_bytes` in `backend/auth.py`, shared as a Pydantic field validator). `POST /login` and the change-password `current_password` are exempt: accounts created before the cap may have longer passwords, and bcrypt 4.x truncates the same way at hash and verify time, so they keep working.
- `PUT /profile/password` deletes the user's outstanding reset tokens.

## Limits and bounds

| Endpoint | Limit | Env var |
|---|---|---|
| `POST /redeem` | 5 a minute per user | `RATE_LIMIT_REDEEM` |
| `POST /reset-password` | 10 a minute per IP | `RATE_LIMIT_RESET_PASSWORD` |
| `GET /cards/{card_id}/image` | 60 a minute per IP | `RATE_LIMIT_CARD_IMAGE` |
| `POST /twitch/link` | 10 a minute per IP | `RATE_LIMIT_TWITCH_LINK` |

`redeem_code`, `get_card_image` and `link_account` stay plain functions; the registered routes are `*_route` wrappers, as for the roster mutations. See `reference/rate-limiting.md`.

- `ReorderRequest.card_ids`: at most 500 items. The frontend sends the whole bench on every move and bench size is unlimited, so the cap is set well above any real collection. `RemovePlayersBody.player_ids`: at most 500. Larger lists get 422.
- `POST /grant-tokens`: `amount` at most 10,000 (`GRANT_TOKENS_MAX`).
- `GET /audit-logs`: `limit` between 1 and 1,000 (`AUDIT_LOG_LIMIT_MAX`).
- `PUT /profile/username` updates `session["username"]` and writes a `username_changed` audit entry (`old=… new=…`) when the name changes.

## Hardening

- `frontend/index.html` loads `lucide@0.453.0` and `alpinejs@3.17.4` (the version `3.x.x` resolved to on 2026-09-27) with `integrity="sha384-…"` and `crossorigin="anonymous"`. To upgrade, change the version and recompute the hash with `curl -sL <url> | openssl dgst -sha384 -binary | openssl base64 -A`.
- `TagBody.key` must match `^[a-z0-9][a-z0-9_-]*$`. `_apply_stickers` in `backend/image.py` resolves each sticker path and skips any outside `STICKER_DIR`.
- `POST /admin/season/reset` returns 500 and deletes nothing when `backup_sqlite_db()` returns `None`.
- `backup_sqlite_db()` creates the backup file with mode `0600`; `scripts/backup-db.sh` copies under `umask 077` and runs `chmod 600`.

## Accepted and deferred

- **#10:** the `auto_lock_weeks` race only happens with `DEMO_MODE=true`.
- **#20:** public `/deck` and `/deck/booster` are intentional public game data.
- **#19 (non-root container), deploy follow-up:** add a non-root `USER` to the Dockerfile in a deploy where the host's `./data` directory is re-owned to that user's UID first (for example `sudo chown -R 10001:10001 ./data`), or the app will not be able to write `fantasy.db` or its backups.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_MVP_CHANNEL_IDS` | *(empty)* | Comma-separated Twitch channel IDs allowed to set match MVPs and trigger token drops. Empty allows any channel with the extension |
| `RATE_LIMIT_REDEEM` | `5/minute` | Per-user limit on `POST /redeem` |
| `RATE_LIMIT_RESET_PASSWORD` | `10/minute` | Per-IP limit on `POST /reset-password` |
| `RATE_LIMIT_CARD_IMAGE` | `60/minute` | Per-IP limit on `GET /cards/{card_id}/image` |
| `RATE_LIMIT_TWITCH_LINK` | `10/minute` | Per-IP limit on `POST /twitch/link` |
