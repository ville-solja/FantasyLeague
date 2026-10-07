# Twitch Account Connection

Lets a player on kana-cards.com connect their Twitch account through **Twitch's own sign-in** (OpenID Connect), and move a Twitch soft account's cards and tokens into their website account. It replaces the old 6-character link code. For players who play both on Twitch and on the website. Resolves issue #160 (Part 2; Part 1 is #157, `twitch-extension-policy-compliance.md`).

*(see `markdown/plans/plan-issue-160-twitch-account-connection-oidc.md`)*

---

## Why not link codes

A code only proves someone typed it. A viewer tricked into entering another person's code would link their Twitch account to that person's website account, and with soft accounts, hand over their cards and tokens. Codes can also be shown on stream, and entering them was the extension's last reference to the website.

## How it works

Twitch proves both sides of a link:
- **Extension side:** after the identity share at Join (Part 1), the Twitch-signed extension JWT carries the viewer's real Twitch user id (`user_id`), stored as `users.twitch_account_id`.
- **Website side:** Profile → **Connect Twitch** runs Twitch's sign-in with the authorization code flow and the `openid` scope only. The Twitch-signed ID token's `sub` is the same user id.

Code: `backend/twitch_oauth.py` (routes, sign-in checks, `connect_account`), `backend/soft_accounts.py` (`merge_soft_into`, `reverse_merge`, `purge_old_merge_logs`), `backend/twitch.py` (`_panel_account`, `_record_identity_share`), `backend/deps.py` (`require_recent_player_reauth`), `backend/routers/admin_twitch.py` (admin merges list and reverse).

### The sign-in

1. **Connect Twitch** navigates to `GET /auth/twitch/start`. Without a recent password check (`POST /reauth`, `ADMIN_REAUTH_SECONDS`, default 10 minutes) it redirects back to `/#profile?twitch=reauth_required`; Profile opens the password prompt and then navigates to start again. Logged out, it redirects with `login_required`.
   An account created through Steam has no password (issue #150). Its prompt offers **Confirm with Steam** instead: a Steam round trip (`GET /auth/steam/start?purpose=reauth`) that marks the same per-session check (`sessions.mark_reauth`) when the verified Steam ID is the account's, and returns to `/#profile?steam=reauth_ok`. The player then presses Connect Twitch again. The same applies to **Add to my account** and **Disconnect**. See `reference/steam-login.md`.
2. Start stores a row in `twitch_oauth_states`: `sha256(state)` (never the state itself), the user id, the `nonce`, the PKCE `code_verifier`, and an expiry 10 minutes ahead. Any earlier unused attempt of the same user is dropped. `state`, `nonce` and verifier each come from `secrets.token_urlsafe(32)`.
3. It redirects to `https://id.twitch.tv/oauth2/authorize` with `client_id`, the exact `redirect_uri`, `response_type=code`, `scope=openid`, `state`, `nonce`, `code_challenge` (base64url SHA-256 of the verifier, no padding) and `code_challenge_method=S256`.
4. Twitch returns the browser to `GET /auth/twitch/callback`, which checks, in order:
   1. the website session (the cookie must reach this cross-site GET: see **Session cookie**),
   2. the `state` row: known, unexpired, unused and this user's; otherwise `failed`,
   3. marks the row used (one-time, whatever happens next),
   4. `error` from Twitch (the user cancelled): `cancelled`,
   5. swaps the code server-side at `https://id.twitch.tv/oauth2/token` (`client_secret`, `code`, `redirect_uri`, `code_verifier`, 10 s timeout),
   6. verifies the ID token: RS256 signature against Twitch's keys (`https://id.twitch.tv/oauth2/keys`, PyJWT `PyJWKClient`, keys cached for an hour), `iss = https://id.twitch.tv/oauth2`, `aud` = client id, `exp`, and `nonce` equal to the stored nonce,
   7. keeps only `sub`. The access and refresh tokens are dropped at once and never stored or logged,
   8. conflicts, then stores the id (`connect_account`).
5. Every outcome redirects to `/#profile?twitch=<key>`, never with Twitch data in the URL. Profile maps the key to a message and strips it from the address bar.

| Key | Meaning |
|---|---|
| `connected` | Stored (or the same id was already stored) |
| `merge_ready` | Stored, and a soft account's collection is waiting |
| `in_use` | "This Twitch account is connected to another Kana Cards account" |
| `disconnect_first` | "Disconnect your current Twitch account first" |
| `cancelled` | Twitch reported an error (the player cancelled); nothing stored |
| `failed` | Bad, expired, reused or someone else's state; failed code swap; ID token rejected |
| `no_session` / `login_required` | No website session |
| `reauth_required` | Start without a recent password check |
| `unavailable` | Connect is switched off |

### Where the pending link lives

`users.twitch_account_id` is unique (#157), so the id can't sit on both accounts. When the callback finds a **soft** account S holding the id (it shared its identity in the panel), it moves the id from S to the website account W in the same transaction and records `W.pending_merge_user_id = S.id` (migration `032`). S keeps its opaque `twitch_user_id`, so the panel keeps acting as S until the merge. Another **website** account holding the id is a conflict (`in_use`); soft accounts never are.

If S joined without the identity share and shares it later, the panel's identity-share step finds W holding the id and makes S W's pending merge (unless one is already pending or W has used its merge). That is what the Profile guidance "Joined on Twitch first? In the Kana Cards Twitch panel, open Settings and choose Share your Twitch identity, then reload this page." relies on.

### The merge

Profile shows **"Your Twitch collection: N cards, M tokens. Add it to this account?"** with **Add to my account** and **Not now** ("Not now" changes nothing; the prompt returns on the next Profile visit). **Add to my account** calls `POST /twitch/merge/confirm` (recent password check), which runs `soft_accounts.merge_soft_into` in one transaction:
- writes the `twitch_merge_log` undo row first,
- deletes S's locked-week `weekly_roster_entries`, so W's past weekly scores and the leaderboards don't change,
- moves every card of S to W's bench (`is_active=false`, `slot_index=NULL`); duplicates are kept and stored card points follow the card,
- adds S's tokens to W,
- clears S's opaque id, deletes S and every remaining row through `delete_soft_account` (after the cards moved), and deletes the presence row of that opaque id,
- sets `W.twitch_user_id` to S's former opaque id, `W.merged_soft_account_at`, clears `W.pending_merge_user_id`,
- audits `twitch_account_merged` (`full_user_id`, `soft_user_id`, counts, `log_id`; no Twitch ids).

Any error rolls the whole merge back. One merge per website account, ever: with `merged_soft_account_at` set, the merge answers 409 (also after a disconnect), and Profile says the collection stays in the panel. No pending merge gives 404; a stale one (S left or was purged) gives 404 and clears the pending id.

### Panel recognition

`_panel_account` in `backend/twitch.py`, used by `POST /twitch/join`, `GET /twitch/me` and every game route (`_joined_user`):
1. the account holding the JWT's opaque id;
2. else the account whose `twitch_account_id` equals the JWT's `user_id`: its `twitch_user_id` is set to the opaque id (audited `twitch_panel_recognised`), so drops reach it too. Join returns it (`created: false`) and never answers 409 or creates a soft account;
3. else Join creates a soft account.

A JWT without `user_id` never switches accounts. While S still holds the opaque id, the panel acts as S; the panel says nothing about the website.

### Disconnect

`POST /twitch/disconnect` (recent password check) clears `twitch_account_id`, `twitch_user_id` and any pending merge, deletes the presence row, and audits `twitch_disconnected`. The account keeps its cards and tokens, and `merged_soft_account_at` stays (the one-merge limit applies). In the panel the viewer is "not joined" again and can join a new soft account. Without a connection it returns 200 with `changed: false` and no audit entry.

Panel **Leave** for a website account only clears `twitch_user_id`; the connection stays. While connected with the identity shared, the panel recognises the account again on the next call. Disconnect is on the website.

## PKCE result

PKCE is on (`twitch_oauth.USE_PKCE = True`) and covered by tests against the mocked token endpoint. **Not yet verified against real Twitch:** before relying on it, start a sign-in on a test account and swap the returned code with a deliberately wrong verifier (for example by changing the stored `code_verifier` row). If the swap fails, keep PKCE; if it succeeds, Twitch ignores PKCE: set `USE_PKCE = False` and rely on `state` and `nonce`. Record the result here.

## Recovery and containment

- **Merge undo log:** `twitch_merge_log` (`id`, `full_user_id`, `merged_at`, `soft_snapshot` JSON with the soft account's `twitch_user_id`, `twitch_account_id`, `created_at`, `last_seen_at`, `tokens`; `card_ids` JSON; `tokens_moved`; `roster_entries` JSON of the deleted rows with week, card, bench and substitution flags; `reversed_at`). Rows older than 30 days, and used or expired `twitch_oauth_states`, are deleted once a day by the week maintenance loop (`twitch_oauth.cleanup`). Deleted per-user rows (reveals, seen, dismissals, claims, redemptions) aren't snapshotted and aren't restored by a reversal.
- **Admin reverse:** `POST /admin/twitch/merges/{log_id}/reverse` (`soft_accounts.reverse_merge`, one transaction) recreates the soft account (new id) from the snapshot, moves the logged cards still on the website account back (to the bench), gives the soft account its `tokens_moved` and subtracts them from the website account (never below 0; the shortfall is in the reply and the audit), restores the logged roster rows whose week and card still exist, clears the website account's `twitch_account_id`, `twitch_user_id`, `merged_soft_account_at` and pending merge, sets `reversed_at`, and audits `twitch_merge_reversed`. If the opaque or real id is held by another account since, the soft account is recreated without it. 409 with a message, and no change, when the row is older than 30 days, already reversed, its website account is gone, or none of its cards exist (season reset).
- **Admin list:** `GET /admin/twitch/merges` returns merges of the last 30 days, newest first and at most 100 rows, with `reversible` and `blocked_reason`. `POST /admin/twitch/merges/{log_id}/reverse` returns 404 for an unknown `log_id`. Admin › User Management shows them under **Twitch collection merges** with **Reverse**.
- **Kill switches:** unsetting any `TWITCH_OAUTH_*` variable turns Connect off (`available: false`, Profile shows "Connecting Twitch is not available right now.", start returns 503) without affecting existing connections or the panel. `TWITCH_DROPS_ENABLED=false` stops drops.
- **No public Twitch ids:** no endpoint returns `twitch_user_id` or `twitch_account_id`; `GET /twitch/connection` returns only booleans and counts; the admin users list returns only `twitch_linked` and `twitch_identity_shared`; merge and connect audit entries carry user ids only. Tests check the response schemas and the route sources.
- **Takeover containment:** nothing irreversible is available in the panel for a website account. Profile shows "Last Twitch activity: {date}" from `last_seen_at` (written by panel calls at most once an hour).
- **Secrets:** nothing logs a code, token, ID token, state, nonce or the client secret; failures log the exception class or HTTP status. uvicorn's access log line for `/auth/twitch/*` has its query string replaced by `[redacted]` (`twitch_oauth.RedactSignInQuery`). A reverse proxy's own access log still records the full callback URL (one-time code and state, already consumed): turn off query logging there or keep those logs short-lived. Backups (`scripts/backup-db.sh`) copy only the database file.
- **Runbook:** `twitch-incident-runbook.md`.

## Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /auth/twitch/start` | Session + recent password check (redirects when missing) | Store the attempt, redirect to Twitch; 503 when unconfigured |
| `GET /auth/twitch/callback` | Session | Verify and store `twitch_account_id`; redirect to `/#profile?twitch=<key>` |
| `GET /twitch/connection` | Session | `{available, connected, pending_merge: {cards, tokens} or null, merge_used, last_twitch_activity_at}` |
| `POST /twitch/merge/confirm` | Session + recent password check | Merge the pending soft account: `{merged, cards, tokens}` |
| `POST /twitch/disconnect` | Session + recent password check | Clear the connection: `{connected: false, changed}` |
| `GET /admin/twitch/merges` | Admin + recent password check | Merges of the last 30 days |
| `POST /admin/twitch/merges/{log_id}/reverse` | Admin + recent password check | Undo a merge within 30 days |
| `POST /twitch/link-code`, `POST /twitch/link`, `GET /twitch/status` | — | **Removed**: 404 (an app-level catch-all answers 404 for unknown `/twitch/*` paths) |

`POST /twitch/merge/confirm` and `POST /twitch/disconnect` use the session cookie, so the Origin check (#136) covers them (`_COOKIE_AUTH_TWITCH_PATHS` in `main.py`). `POST /reauth` works for every logged-in user with a password; it audits `admin_reauth` for admins and `player_reauth` for everyone else. Accounts without a password get 409 `use_steam_reauth` and use the Steam re-auth above.

The `twitch_link_codes` table and the `TwitchLinkCode` model remain for a later clean-up migration; only `soft_accounts.delete_soft_account` still deletes its rows, and no route reads or writes it.

## Data

| Where | What |
|---|---|
| `users.twitch_account_id` | Verified Twitch user id (unique) |
| `users.twitch_user_id` | Opaque per-extension id, set when the panel recognises the account or by a merge |
| `users.pending_merge_user_id` | Soft account waiting to be merged (migration `032`) |
| `users.merged_soft_account_at` | When this account used its one merge (migration `032`) |
| `twitch_oauth_states` | Sign-in attempts (new table, `create_all`) |
| `twitch_merge_log` | Merge undo log, 30 days (new table, `create_all`) |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_OAUTH_CLIENT_ID` | *(empty)* | Client id of the Twitch application used for sign-in |
| `TWITCH_OAUTH_CLIENT_SECRET` | *(empty)* | Its client secret (not the extension JWT secret) |
| `TWITCH_OAUTH_REDIRECT_URI` | *(empty)* | Exact callback URL registered in the Twitch developer console, for example `https://<host>/auth/twitch/callback` |
| `RATE_LIMIT_TWITCH_OAUTH` | `10/minute` | Per-IP limit on each of start and callback |

Read on each request. When any of the three is missing, Connect Twitch is unavailable and the start endpoint returns 503. Requires `cryptography` (in `backend/requirements.txt`) for RS256.

**Redirect addresses:** register one per environment in the Twitch developer console, an exact match of scheme, host and path. For example:
- `https://kana-cards.com/auth/twitch/callback` (production),
- `https://test.kana-cards.com/auth/twitch/callback` (test site),
- `http://localhost:8000/auth/twitch/callback` (local; confirm the console accepts plain HTTP for localhost).

Each environment's `TWITCH_OAUTH_REDIRECT_URI` must equal its registered address; the same value is sent in the authorize request and the code swap.

**Session cookie:** must stay `SameSite=Lax` (comment at the `SessionMiddleware` in `main.py`). The return from Twitch is a cross-site top-level GET, and with `Strict` the website session wouldn't reach the callback (`no_session`).

**Manual setup before launch:** two-factor sign-in on the Twitch account that owns the extension and the sign-in app; console access limited; registered redirect addresses checked.

---

*This document was a stub created at feature planning time; implementation details were filled in when #160 was built.*
