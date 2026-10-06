# Plan: Twitch Account Connection via Twitch Sign-in (Part 2 of 2)

## Context
Part 1 (#157) makes the Twitch extension a standalone game. Viewers join with a **soft account** (`users.account_type="twitch"`), and Join stores the viewer's real Twitch user id in `users.twitch_account_id` when they accept Twitch's identity share. Part 1 also removes the panel's link-code entry and hides "Generate Twitch Code" on Profile, so linking a website account to Twitch is unavailable until this plan lands.

This plan replaces the old 6-character link code with **Twitch's own sign-in** (OpenID Connect, authorization code flow) on the website. Twitch proves both sides of a link:
- **Extension side:** the Twitch-signed JWT carries the viewer's `user_id` after the identity share.
- **Website side:** the Twitch-signed ID token from the sign-in carries the same user id.

When the two match, the website account and the soft account belong to the same person. The website then offers to **merge** the soft account's cards and tokens into the website account.

**Why not the code:**
- **It doesn't prove ownership.** It only proves someone typed it. A viewer tricked into entering another person's code would link their Twitch account to that person's website account. With soft accounts, that hands over their cards and tokens.
- **It's exposed.** Codes can be shown on stream, and they're guessable secrets.
- **It points off Twitch.** Entering the code was the extension's last reference to the website.

**Assumptions:**
- **Connecting only.** Twitch sign-in is used only to *connect* a Twitch account to a logged-in website account, never as a website login method. Website login is heading to Steam (#150), and "Sign in with Twitch" as a login could be added later on top of this.
- **Twitch endpoints:** `https://id.twitch.tv/oauth2/authorize`, `https://id.twitch.tv/oauth2/token` and the published keys at `https://id.twitch.tv/oauth2/keys`, issuer `https://id.twitch.tv/oauth2`.
- **PKCE must be proven, not assumed.** PKCE ties the authorization code to the sign-in that started it: a random `code_verifier` is kept server-side, its SHA-256 fingerprint is sent as `code_challenge` (`S256`), and the verifier is sent on the code swap. It's an extra layer against authorization-code injection. `state` (one-time, session-bound) and `nonce` (checked in the signed ID token) already cover those attacks without it.
  - **Test early:** send a `code_challenge`, then swap the code with a **wrong** verifier.
  - **The swap fails:** Twitch enforces PKCE. Keep it.
  - **The swap succeeds:** Twitch ignores it. Remove PKCE from the code so it doesn't look like a protection that isn't there, and rely on `state` and `nonce`.
  
  Record the result in `markdown/features/reference/twitch-account-connection.md`.
- **One redirect address per environment.** Twitch only sends codes to addresses registered for the app, and requires an exact match (scheme, host, path). Register one for each environment, with these example hostnames adjusted to the real ones:
  - production: `https://kana-cards.com/auth/twitch/callback`,
  - the test site, if any: `https://test.kana-cards.com/auth/twitch/callback`,
  - local development: `http://localhost:8000/auth/twitch/callback`. Twitch normally requires HTTPS with localhost as the usual exception; confirm in the console.
  
  Each environment's `TWITCH_OAUTH_REDIRECT_URI` must equal its registered address. The same value is sent in the authorize request and the code swap.
- **The session cookie must stay `SameSite=Lax`.** The return from Twitch to the callback is a cross-site, top-level GET. The website session cookie (`SameSite=Lax`, `backend/main.py:385`) is sent on it, so the callback knows which player started the flow. With `SameSite=Strict` it wouldn't be sent, and every callback would fail with "no session". Add a comment at the cookie setting saying so, and pin it with a test.
- **Registration:** the redirect URI is registered in the Twitch developer console, either for a separate Twitch application or the extension's client, whichever the console allows. Its client secret is a new secret, separate from `TWITCH_EXTENSION_SECRET` (which signs extension JWTs).
- **Library:** ID token verification uses PyJWT's `PyJWKClient`. RS256 needs the `cryptography` package, which isn't in `backend/requirements.txt` yet, so add it (`PyJWT[crypto]` or a pinned `cryptography`).
- **Password re-check:** `require_recent_reauth` (`backend/deps.py`, #117) only works for admins today. A player variant (`require_recent_player_reauth`) is added. `POST /reauth` already works for any logged-in user; check this during implementation.
- **Developer account security (manual, before launch).** Whoever controls the Twitch developer account can change the registered redirect address, which sends future sign-in codes to their own site. They can also read the client and extension secrets, which lets them forge extension tokens and act as any viewer or broadcaster. So, before #160 goes live:
  - turn on two-factor sign-in for the Twitch account that owns the extension and the sign-in app,
  - keep console access to as few people as possible,
  - check the registered redirect addresses after any console change.
  
  This is a setup step, not code, and it's listed in Verification.
- **New tables:** two, both created by `create_all`, so neither needs a migration: a short-lived table for sign-in attempts (`twitch_oauth_states`), and the merge undo log (`twitch_merge_log`, next story). `users.twitch_account_id` comes from Part 1's migration `031`. The `twitch_link_codes` table is left in place and dropped in a later migration.

Resolves GitHub issue #160. Depends on #157.

## User Stories

### Connect Twitch on the Website
**User story**
As a player logged in on kana-cards.com, I want to connect my Twitch account by signing in to Twitch so that my Twitch play and my website account are linked securely, without codes.

**Acceptance criteria**
- **The Profile section:** "Twitch" shows one of:
  - **Connect Twitch** when no Twitch account is connected,
  - "Connected to Twitch" with **Disconnect** when one is,
  - the merge prompt when a Twitch collection is waiting (next story).
- **Starting the sign-in:** Connect Twitch first requires a recent password check (`require_recent_player_reauth`; the existing in-page password prompt opens when needed). It then calls `GET /auth/twitch/start`, which:
  - stores a sign-in attempt in `twitch_oauth_states`: a SHA-256 hash of a random `state`, the user id, a random `nonce`, the PKCE verifier if used, and an expiry 10 minutes ahead,
  - redirects to Twitch's authorize URL with `response_type=code`, `scope=openid`, the exact registered `redirect_uri`, `state`, `nonce` and, if supported, `code_challenge`.
- **Finishing the sign-in:** `GET /auth/twitch/callback?code&state`:
  1. **Check the attempt:** the `state` hash must exist, be unexpired, belong to the current website session's user, and be unused. The attempt is consumed on first use.
  2. **Exchange the code:** server-side, at the token endpoint, with the client secret.
  3. **Verify the ID token:** RS256 signature against Twitch's keys, `iss`, `aud` equal to the client id, `exp`, and `nonce` equal to the stored nonce.
  4. **Keep only the Twitch user id:** take `sub`. The access and refresh tokens are discarded and never stored or logged.
  5. **Store it:** set `twitch_account_id = sub` on the website account, and audit `twitch_connected`.
  6. **Return to Profile.** If a soft account with the same `twitch_account_id` exists, Profile opens the merge prompt.
- **Conflicts:** if another website account already has this `twitch_account_id`, or this account already has a different one, the callback stores nothing and returns to Profile with "This Twitch account is connected to another Kana Cards account" or "Disconnect your current Twitch account first".
- **Failure paths** (each returns to Profile with a neutral error, stores nothing and doesn't log any Twitch token):
  - a missing, expired, reused or someone else's `state`,
  - Twitch reporting an error (the user cancelled),
  - a failed code exchange,
  - an ID token that fails any check,
  - a callback without a website session.

### Merge My Twitch Collection
**User story**
As a player who played on Twitch before connecting, I want to move my Twitch cards and tokens into my website account, after seeing what will move, so that everything is in one place.

**Acceptance criteria**
- **The prompt:** when the website account W has `twitch_account_id` X and a soft account S with `twitch_account_id = X` exists, Profile shows "Your Twitch collection: {cards} cards, {tokens} tokens. Add it to this account?" with **Add to my account** and **Not now**.
- **The call:** **Add to my account** calls `POST /twitch/merge/confirm`, which requires a recent password check. In one transaction it:
  - moves every card of S to W's **bench** (`is_active=false`, `slot_index=NULL`); duplicates are kept, and card points follow the card,
  - adds S's tokens to W,
  - deletes S's locked-week `weekly_roster_entries`, so W's past weekly scores and the leaderboards don't change,
  - deletes S and all its remaining rows through Part 1's `soft_accounts.delete_soft_account` (extended there if the merge needs more, never a second, narrower list), after the cards have moved to W: per-user rows (`weekly_summary_reveals`, `weekly_summary_seen`, `notification_dismissals`, `token_grant_claims`, `code_redemptions`, sessions, tags, link codes, reset tokens) and its presence row,
  - sets `W.twitch_user_id = S.twitch_user_id` (clearing it on S first) so the panel recognises W,
  - writes `twitch_account_merged` with both ids and the counts moved.
  
  It returns the counts, and Profile shows "12 cards and 4 tokens added".
- **One merge per website account, ever:** a website account that already absorbed a soft account (recorded in the audit log and a `users.merged_soft_account_at` timestamp) gets 409 for any further merge.
- **Not now** keeps both accounts as they are. The prompt shows again on the next Profile visit.
- **Failure paths:**
  - no soft account with that id gives 404,
  - a stale prompt (S already merged or deleted) gives 404 with a refresh,
  - an error part-way through rolls the whole merge back; a test injects one,
  - a merge without a recent password check gives 403 `reauth_required`.

### Recognised in the Panel After Connecting
**User story**
As a player who connected Twitch on the website, I want the extension to recognise my website account so that drops, draws and my roster use that one account.

**Acceptance criteria**
- **Lookup order (fixes a Part 1 conflict):** in `POST /twitch/join`, `GET /twitch/me` and every panel game route (`_joined_user`), the lookup of a website account by `twitch_account_id = X` (the JWT's `user_id`) runs **before** the lookup by opaque id leads to soft-account creation. Without it, once this plan stores X on W, Part 1's Join would call `record_twitch_account_id` / `get_or_create_soft_account` for a new soft account and fail with 409 `twitch_identity_in_use`, and `GET /twitch/me` would answer `joined: false`. With it, Join returns W (never 409, never a new soft account) and `GET /twitch/me` reports W as joined.
- **Recognising the website account:** when a panel request carries a Twitch JWT with `user_id = X`, and website account W has `twitch_account_id = X`:
  - **If no soft account uses the viewer's opaque id:** W's `twitch_user_id` is set to the JWT's opaque id. From then on the panel acts as W (its tokens, collection and roster), and W receives drops.
  - **If a soft account S still uses that opaque id (merge not confirmed yet):** the panel keeps acting as S until the merge is confirmed on the website. The panel says nothing about the website.
- **Website guidance:** if S never shared its identity (no `twitch_account_id`), the website can't find it. Profile then explains: "Joined on Twitch first? In the Kana Cards Twitch panel, open Settings and choose Share your Twitch identity, then reload this page." This text is on the website only.
- **Failure path:** a JWT without `user_id` (no identity share) never changes which account the panel acts as.

### Disconnect and Retire Link Codes
**User story**
As a player, I want to disconnect Twitch from my account, and as the publisher I want the old link-code mechanism gone, so that only the secure flow remains.

**Acceptance criteria**
- **Disconnect:** **Disconnect** (recent password check) calls `POST /twitch/disconnect`, which clears `twitch_account_id` and `twitch_user_id` on the website account and audits `twitch_disconnected`.
  - The website account keeps its cards and tokens.
  - In the panel the viewer is "not joined" again and can join a new soft account.
  - The one-merge limit still applies to that website account.
- **Retired:** `POST /twitch/link-code`, the code-based `POST /twitch/link`, the legacy `GET /twitch/status` (superseded by `GET /twitch/me` in Part 1, and the last panel-side route that still returns a `username`), the `TwitchLinkCode` usage and the old Profile code UI are removed. Requests to the removed endpoints get 404. The `twitch_link_codes` table is left for a later clean-up migration.
- **Configuration:** `TWITCH_OAUTH_CLIENT_ID`, `TWITCH_OAUTH_CLIENT_SECRET` and `TWITCH_OAUTH_REDIRECT_URI` in `.env.example`, with comments. When any is missing, Connect Twitch is hidden on Profile, `GET /auth/twitch/start` returns 503, and the app still starts.
- **Docs:** the privacy page describes the Twitch connection: the stored Twitch user id, and that tokens aren't stored.
- **Failure path:** a disconnect without a connected account returns 200 with no change.

### Recoverable and Contained
**User story**
As the operator of a hobby project, I want a bad merge to be reversible, the feature easy to switch off, and Twitch identities never exposed, so that an incident stays small and fixable.

**Acceptance criteria**
- **Merge undo log:** before deleting the soft account, `merge_soft_into` writes one `twitch_merge_log` row:
  - `id`, `full_user_id`, `merged_at`,
  - `soft_snapshot` (JSON): the soft account's `twitch_user_id`, `twitch_account_id`, `created_at`, `last_seen_at` and `tokens`,
  - `card_ids` (JSON),
  - `tokens_moved`,
  - `roster_entries` (JSON of the deleted locked-week rows: week, card, bench flags, substitution flags),
  - `reversed_at`.
  
  Rows older than 30 days are deleted by a daily job. The deleted per-user rows (reveals, seen, dismissals, claims, redemptions) aren't snapshotted. A reversal doesn't restore them; that's minor and documented.
- **Admin reverse:** `POST /admin/twitch/merges/{log_id}/reverse` (admin, recent password check) undoes a merge within 30 days, in one transaction:
  - recreates the soft account (new id) from the snapshot,
  - moves the logged cards it still finds on the website account back to it,
  - subtracts `tokens_moved` from the website account, never below 0, and records any shortfall in the reply and the audit log,
  - restores the logged locked-week roster entries,
  - clears the website account's `twitch_account_id`, `twitch_user_id` and `merged_soft_account_at`, so the legitimate owner can connect and merge again,
  - sets `reversed_at` and audits `twitch_merge_reversed`.
  
  Admin › Users shows recent merges with a **Reverse** button.
- **Reversal failure paths:** a log row older than 30 days, already reversed, or crossing a season reset (its cards no longer exist) returns 409 with a clear message, and nothing changes.
- **Kill switches, documented:**
  - unsetting any `TWITCH_OAUTH_*` variable turns Connect Twitch off (hidden on Profile, 503 on start) without affecting existing connections or the panel,
  - `TWITCH_DROPS_ENABLED=false` (from #157) stops drops.
  
  Both are listed in the incident runbook.
- **Incident runbook:** `markdown/features/reference/twitch-incident-runbook.md`, covering:
  1. switch off with the kill switches,
  2. rotate the client secret and the extension secret in the Twitch console, and update the env,
  3. review the audit log for `twitch_connected`, `twitch_account_merged` and `twitch_disconnected` in the window,
  4. reverse bad merges from the undo log, or restore the pre-deploy backup (`scripts/backup-db.sh`),
  5. check the registered redirect addresses,
  6. post a short, honest note to players.
- **No public Twitch ids:** no endpoint returns `twitch_user_id` or `twitch_account_id`. `GET /twitch/connection` returns only `connected`, never the id, and since Part 1 the admin users list returns only the booleans `twitch_linked` and `twitch_identity_shared`, never the ids. The check also covers `GET /twitch/status` until it is removed (it returns a username, not ids). A test checks every route's response model or schema for these field names. Admin exports also leave out Twitch ids.
- **Takeover containment:**
  - the panel offers nothing irreversible for a website-linked account: Leave only unlinks, and no panel action deletes cards or changes website credentials,
  - Profile shows "Last Twitch activity: {date}" from `last_seen_at` (written by panel calls at most once an hour, #157, so the date is accurate to about an hour), so a player can notice unexpected use and press Disconnect.
- **Secrets stay out of logs and backups:**
  - a test drives the callback through success and every failure path while capturing logs, and asserts that the authorization code, the ID and access tokens and the client secret never appear,
  - another test asserts that `scripts/backup-db.sh` copies only the database file and never `.env`.
- **We never ask for passwords:** the website's Profile Twitch section and the privacy page say "Kana Cards never asks for your Twitch or website password inside Twitch."

## Decisions (made at implementation)

These settle ambiguities in the stories below; where a story says otherwise, this section wins.

1. **Where the pending link lives.** `users.twitch_account_id` stays unique. On a successful callback for website account W with Twitch `sub` X: another **website** account holding X is a conflict; a **soft** account S holding X gives it up in the same transaction (`S.twitch_account_id = NULL`, `W.twitch_account_id = X`) and `W.pending_merge_user_id = S.id` records the waiting merge (new nullable column, migration `032` with `merged_soft_account_at`). The prompt reads it; "Not now" leaves it; Disconnect and a merge clear it; if S no longer exists the merge answers 404 and clears it. S keeps its opaque `twitch_user_id`, so the panel acts as S until the merge. When S shares its identity only after W connected, S becomes W's pending merge (unless one is pending or W used its merge).
2. **Panel lookup order** in `join()`, `me()` and `_joined_user()`: (a) the account holding the JWT's opaque id; (b) else the account whose `twitch_account_id` equals the JWT's `user_id` (recognised: opaque id attached, never 409, never a new soft account); (c) else Join creates a soft account. A JWT without `user_id` never switches accounts.
3. **Start is a navigation.** Without a recent password check, `GET /auth/twitch/start` redirects to `/#profile?twitch=reauth_required` (not 403 JSON); Profile opens the password prompt and navigates to start again. Every callback outcome redirects to `/#profile?twitch=<key>` and never echoes Twitch text.
4. **Player re-auth** uses the existing `POST /reauth`, audited `player_reauth` for players (`admin_reauth` for admins).
5. **Library:** `cryptography>=46.0,<51.0` in `backend/requirements.txt`; PyJWT `PyJWKClient` (keys cached) checks signature, `iss`, `aud`, `exp`; `nonce` compared separately.
6. **Admin merges list:** `GET /admin/twitch/merges` (admin + recent password check) alongside the reverse endpoint, shown in Admin › User Management.
7. `GET /twitch/connection` also returns `merge_used` and `last_twitch_activity_at` (from `last_seen_at`).
8. Retired routes are removed; an app-level catch-all answers 404 for unknown `/twitch/*` paths (the static mount would otherwise answer 405 to POST).
9. No OAuth tokens stored; nothing logs codes, tokens, ID tokens, the client secret or state; uvicorn's access log drops the `/auth/twitch/*` query string.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `TwitchOAuthState` (new table: `state_hash` PK, `user_id`, `nonce`, `code_verifier`, `expires_at`, `used_at`); `TwitchMergeLog` (new table, as in the last story); `User.merged_soft_account_at` and `User.pending_merge_user_id` (Integer, nullable) |
| `backend/migrate.py` | Migration `032_users_merged_soft_account_at` (both new columns on an existing table) |
| `backend/twitch_oauth.py` (new) | Router: `GET /auth/twitch/start`, `GET /auth/twitch/callback`, `GET /twitch/connection`, `POST /twitch/merge/confirm`, `POST /twitch/disconnect`; ID token verification with `PyJWKClient` |
| `backend/soft_accounts.py` | `merge_soft_into(db, soft, full)` per the merge story, writing the undo log; `reverse_merge(db, log)`; recognising a website account by `user_id` |
| `backend/routers/admin_twitch.py` (new; kept out of `admin_users.py`, which the #85 test caps at 350 lines) | `GET /admin/twitch/merges`, `POST /admin/twitch/merges/{log_id}/reverse` |
| `backend/twitch.py` | Remove `link-code` and code-based `link`; JWT `user_id` → website account recognition in the panel endpoints |
| `backend/deps.py` | `require_recent_player_reauth` |
| `backend/main.py` | Mount the router; daily clean-up of expired `twitch_oauth_states` and of `twitch_merge_log` rows older than 30 days, in an existing background loop |
| `backend/requirements.txt` | `cryptography` (or `PyJWT[crypto]`) |
| `frontend/index.html`, `frontend/app-profile.js` | Twitch section: Connect, Connected/Disconnect, merge prompt, guidance text; the old code UI removed |
| `frontend/privacy.html` | Twitch connection data |
| `.env.example` | The three `TWITCH_OAUTH_*` variables |
| `markdown/features/reference/twitch-account-connection.md` | Feature doc (stub at planning) |
| `markdown/features/reference/twitch-incident-runbook.md` (new) | Incident runbook (switch-off, secret rotation, audit review, reversal, communication) |
| `frontend/app-admin*.js`, `frontend/index.html` | Recent Twitch merges with Reverse in Admin › Users |
| `backend/tests/test_issue_160_twitch_account_connection_oidc.py` | Flow, verification, merge and retirement tests (Twitch mocked) |
| `backend/tests/test_issue_85_split_admin_router.py` | Suite-size tripwire bump |

### Step 1 — Configuration and keys
- **Settings:** read the `TWITCH_OAUTH_*` values on each request, and report Connect as available only when all three are set.
- **Redirect addresses:** register one per environment in the Twitch developer console (see Assumptions). Document the values in `.env.example` with a comment that the variable must exactly equal the registered address.
- **Cookie note:** next to `same_site="lax"` in `backend/main.py`, add a comment that the Twitch sign-in callback (a cross-site top-level GET) relies on Lax, and that Strict would break it.
- **Keys:** `PyJWKClient("https://id.twitch.tv/oauth2/keys")` with caching. In tests, a local key pair signs fake ID tokens.

### Step 2 — Start and callback
- **`state`, `nonce` and the PKCE verifier:** each from `secrets.token_urlsafe(32)`. `code_challenge` is the base64url SHA-256 of the verifier, without padding, with `code_challenge_method=S256`. Make PKCE switchable in one place (a module constant), so it can be removed cleanly if the early test shows Twitch ignores it.
- **What's stored:** only `sha256(state)`.
- **The callback checks in this order:**
  1. the website session and user,
  2. the `state` record,
  3. marking it used (one-time),
  4. the code exchange (requests with a timeout),
  5. the ID token checks,
  6. the id conflicts,
  7. storing the id.
- **Redirects:** to `/` with a Profile message key, never with Twitch data in the URL.
- **Rate limits:** on both endpoints.

### Step 3 — Merge
- **Function:** `merge_soft_into` implements the merge story, flushes, and lets the caller commit once.
- **Endpoint:** `POST /twitch/merge/confirm` checks the one-merge rule and the password re-check, finds S by `twitch_account_id`, merges, and sets `merged_soft_account_at`.

### Step 4 — Panel recognition
Add a helper in the panel endpoints, called first by `join()`, `me()` and `_joined_user()` in `backend/twitch.py`, before `soft_accounts.get_or_create_soft_account` or `record_twitch_account_id` run. When the JWT has `user_id` and a website account has that `twitch_account_id`, and no soft account holds the opaque id, attach the opaque id to the website account (`twitch_user_id`) and act as it. Otherwise act as the account found by opaque id, as in Part 1. Join must never answer 409 `twitch_identity_in_use` for a viewer whose id is held by a connected website account.

### Step 5 — Retire codes and update the frontend
- **Backend:** remove the two endpoints and their tests (replaced by this plan's).
- **Frontend:** Profile renders the Twitch states from `GET /twitch/connection`, which returns:
  - `connected` (bool),
  - `pending_merge` (`{cards, tokens}` or `null`),
  - `available` (whether the config is complete).

### Step 6 — Recovery and containment
- **`twitch_merge_log`:** written inside the merge transaction, before the soft account is deleted.
- **`reverse_merge`:** implements the reversal criteria in one transaction.
- **Admin UI:** the merges list and Reverse sit behind the admin password re-check.
- **Data checks:**
  - an audit over all route response schemas for the Twitch id field names,
  - a log-capture test for secrets,
  - a static test on `scripts/backup-db.sh`.
- **Docs:** write the runbook.

### Step 7 — Tests and docs
`backend/tests/test_issue_160_twitch_account_connection_oidc.py`, with Twitch's token endpoint and keys mocked:
- **Start:** requires the password re-check (redirect with `reauth_required` without it), stores a hashed state, and redirects with the right parameters.
- **Callback, happy path:** stores `twitch_account_id` and discards the tokens. Assert they appear in no DB column and no log record.
- **Callback, failures:** bad, expired, reused or someone else's `state`; a wrong `iss`, `aud`, `nonce` or signature; an expired token; a Twitch error; a missing session. None of them stores anything.
- **Conflicts:** both cases give 409-style redirects.
- **Merge:** cards land on the bench; tokens are added; S's locked-week entries are deleted and W's past leaderboard totals are unchanged; S is deleted; the audit entry is written; a second merge gives 409; a failure injected mid-merge rolls everything back; no password re-check gives 403.
- **Panel recognition:** a JWT with `user_id` attaches the opaque id to W; with a soft account present, the panel keeps acting as S.
- **Lookup order:** with W holding `twitch_account_id = X` and no account on the opaque id, `POST /twitch/join` with `user_id = X` returns W (200, `created: false`, no new row, no 409) and `GET /twitch/me` returns `joined: true` for W.
- **Merge cleanup:** the merge deletes S through `soft_accounts.delete_soft_account`; assert no row of any table in its list still references S.
- **Retired status route:** `GET /twitch/status` returns 404.
- **Disconnect:** clears both ids, and W keeps its cards.
- **Retired endpoints:** `link-code` and code-based `link` return 404.
- **Missing config:** Connect is hidden and start returns 503.
- **Merge undo log:**
  - a merge writes a complete log row,
  - a reversal recreates the soft account, moves the cards back, subtracts tokens with the shortfall reported, restores the roster entries, and clears the website account's Twitch fields,
  - reversal failures: older than 30 days, already reversed, after a season reset (409 each, no change),
  - the purge deletes rows older than 30 days.
- **No public Twitch ids:** no public or player endpoint response contains `twitch_user_id` or `twitch_account_id`.
- **Containment:** Leave for a website-linked account only unlinks, and Profile shows the last Twitch activity.
- **Secrets:** they never appear in captured logs on any callback path, and `backup-db.sh` never copies `.env`.
- **PKCE parameters:** while PKCE is on, the authorize redirect carries `code_challenge` (correct S256 of the stored verifier) and `code_challenge_method=S256`, and the mocked code swap receives the stored `code_verifier`.
- **Redirect address:** the authorize redirect and the code swap both use exactly `TWITCH_OAUTH_REDIRECT_URI`.
- **Cookie:** the session cookie is set with `SameSite=Lax` (not Strict), and the comment explaining the Twitch callback is next to it. The callback reads the session on a GET with no `Origin` header.

Then bump the suite-size tripwire. Fill in the feature doc, update the privacy page, `.env.example`, `markdown/features/core/auth.md` (Twitch connection) and the Twitch docs.

## Verification
- **Developer account (manual, before launch):** two-factor sign-in is on for the Twitch account that owns the extension and the sign-in app, console access is limited, and the registered redirect addresses are the expected ones.
- **Setup:** register the redirect address for each environment in the Twitch developer console, and set the three env vars to match.
- **Incident drill, local:**
  1. Merge a test soft account.
  2. Reverse it from Admin › Users, and check the cards and tokens are back on the recreated soft account.
  3. Unset `TWITCH_OAUTH_CLIENT_ID`: Connect disappears and the panel still works.
  4. Follow the runbook steps once to confirm they're accurate.
- **PKCE check, before relying on it:** on a test account, start a sign-in, then swap the returned code with a deliberately wrong verifier, for example by temporarily changing the stored verifier.
  - **The swap fails:** keep PKCE.
  - **The swap succeeds:** Twitch ignores it, so switch PKCE off in the code.
  
  Record which in the feature doc.
- **Redirect address:** sign-in from production returns to the production address. A deliberately wrong `TWITCH_OAUTH_REDIRECT_URI` (not registered) makes Twitch refuse the sign-in before any code is issued.
- **Cookie:** with the session cookie temporarily set to `SameSite=Strict` in a local run, the callback fails with "no session". This confirms why it must stay Lax; revert afterwards.
- **Viewer first:**
  1. Join in the panel and accept the identity share, then draw a few cards.
  2. Log in on the website and connect Twitch: you go to Twitch, then back, and the merge prompt shows the right counts.
  3. Confirm: the cards are on the bench and the tokens are added.
  4. The panel now acts as the website account, and a drop goes to it.
- **Website first:** connect Twitch with no soft account, then open the panel with the identity shared. The panel shows the website account's collection.
- **Security:**
  - change `state` in the callback URL: refused,
  - replay a callback URL: refused,
  - cancel on Twitch's page: neutral message, nothing stored,
  - check the logs: no Twitch tokens.
- **Disconnect:** the panel shows "not joined", and the website account keeps everything.
- **Retired endpoints:** `POST /twitch/link-code` returns 404.
- `cd backend && python3 -m pytest tests/ -q` passes.
