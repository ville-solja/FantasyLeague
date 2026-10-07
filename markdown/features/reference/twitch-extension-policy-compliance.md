# Twitch Extension Policy Compliance (Part 1)

Makes the Twitch extension a complete game on Twitch, so it passes Twitch's policy 4.5. Any viewer can see live fantasy information. A viewer logged in to Twitch can join with one button, which creates a **soft account**. They can then draw cards, keep a collection and set a weekly roster in the panel, and receive MVP token drops. Connecting a website account later is optional and is covered by Part 2 (#160). For viewers, broadcasters, players and admins. Resolves issue #157; the extension ships as version 1.2.0.

*(plan: `markdown/plans/plan-issue-157-twitch-extension-policy-compliance.md`; mockups: https://claude.ai/artifact/T4DvumfGSTbXdXTZNodkWx; extension overview: [Twitch Extension](../core/twitch-extension.md); review copy: [Review Submission](twitch-extension-review-submission.md))*

---

## Why it was rejected

Twitch rejected the extension because "Extensions cannot require viewers to login to external sites in order to use them":
- **Login prompt:** the panel opened on "Log into kana-cards.com → Generate Twitch Code".
- **Off-Twitch value:** its only viewer value (a token balance and token drops) depended on that external account.

## Soft accounts

A soft account is a `users` row with:
- `account_type="twitch"` and `twitch_user_id` set to the viewer's opaque Twitch id (`U…`; logged-out `A…` ids get 403 `twitch_login_required`),
- `username`, `email` and `password_hash` all NULL, so it can never sign in on the website,
- `tokens = INITIAL_TOKENS`, and `created_at` and `last_seen_at` set at creation.

Website accounts have `account_type="full"` (the column default, also for every row that existed before migration `031_users_twitch_soft_accounts`).

**Created by:** `POST /twitch/join` only (`soft_accounts.get_or_create_soft_account`). Join is idempotent: any account holding the opaque id, a soft account or one of the website accounts (code-linked before #160, or connected with Twitch sign-in), is returned (since #160 also an account whose `twitch_account_id` equals the JWT `user_id`) and nothing is created. Two simultaneous joins produce one row: the unique `users.twitch_user_id` makes the second insert fail, and the loser re-reads the winner's row. Migration 031 adds that unique index on legacy databases, where migration 003 had added the column without one.

**Audit:** `twitch_soft_account_created` with `user_id=…`; the opaque id is never written to an audit row. Audit rows show a soft account as `Twitch viewer #{id}` (`User.display_name`).

**Plays like any account:** the panel's game endpoints call the website's own functions in `routers/cards.py` with the soft account as the acting user (`{"user_id", "username": None, "is_admin": False}`, the `get_current_user` shape). So soft accounts:
- draw with the same token cost, rarity roll, modifiers and "unowned players first" rule,
- are snapshotted at the weekly lock, get bench substitutions and stored card points,
- get the weekly +1 token (`auto_lock_weeks`), drops, and the season reset.

**Website safety:** `POST /login` and `POST /forgot-password` look users up by username, which a soft account doesn't have; `auth.verify_password` returns False for an empty hash; `deps._session_user` returns no user for a soft account even if a session row existed. Its admin label `Twitch viewer #N` fails the username allowlist (`auth.check_username`), so no website account can take it.

## Live tab and game endpoints

All `/twitch/*` endpoints validate the extension JWT (`verify_twitch_jwt`). The game endpoints look the caller up by `twitch_user_id` and answer 404 `not_joined` when there is no account, including for anonymous `A…` viewers. The new panel and game routes listed below never return Twitch ids, email, username or another user's data. The legacy `GET /twitch/status` was retired in #160 (404).

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /twitch/panel` | Any role, incl. anonymous | Live tab: `top_performers` (3 best single-match scores of the 5 latest scored matches, from `routers.leaderboard.top_performance_rows`, the query behind `GET /top`) and `next_match` (`schedule.next_scheduled_match`, the cached data behind `GET /schedule`; team names, time and week label only, no stream links). Empty sections are `[]` / `null`, never an error |
| `GET /twitch/matches/current` | Any role | Unchanged (#161): latest series, MVPs and `(live)` provisional matches, `live_checked_at`, `live_source_configured` |
| `POST /twitch/join` | `U…` viewer, broadcaster or moderator | Create or return the account; the `GET /twitch/me` state plus `created` |
| `GET /twitch/me` | Any role | `{joined: false, can_join}` without an account; otherwise `joined`, `tokens`, `collection`, `roster`, `roster_locked`, `roster_limit`, `week_points`, `team_draw_cost`, `identity_shared`, `website_account` |
| `POST /twitch/draw` | Joined | `draw_card` |
| `GET /twitch/teams` | Joined | `{teams, cost, tokens}`; `teams` is `routers.cards.booster_deck_for_user`, the same function `GET /deck/booster` now calls |
| `POST /twitch/draw/booster/{team_id}` | Joined | `draw_booster`; a team the caller fully owns is refused with 409 "No players available for this team" (its tile is disabled in the panel) |
| `POST /twitch/roster/activate/{card_id}?slot=N` | Joined | `activate_card`; the optional `slot` puts the card in the slot the viewer picked |
| `POST /twitch/roster/deactivate/{card_id}` | Joined | `deactivate_card` (Bench it) |
| `POST /twitch/roster/swap` | Joined | `swap_roster` with `{bench_card_id, active_card_id, slot_index}`, the website's drag-and-drop swap |
| `POST /twitch/leave` | Any role | Leave (below); `{left, deleted}` |
| `GET /twitch/status` | — | Retired in #160 (404); superseded by `GET /twitch/me` |

**Collection** (`routers.cards.collection_for_user`): every owned card with player, team, rarity (`card_type`), modifiers, `is_active` and `season_points` (the card's stored points over all scored matches), rarest first then by name. No paging: a 40-card collection is one response.

**Roster:** `_build_roster_response` for the next editable week. When there is no editable week and a locked week is in progress, the panel shows that week's snapshot read-only (`roster_locked: true`) and the three roster endpoints answer 409 "Roster locked for this week". The website has no such server-side check (its locked weeks are read-only snapshots and edits apply to the next week); the panel adds it so a viewer can't change cards that would only count for a week nobody has created yet.

**Week points:** `{week_id, label, points}` for the locked week in progress (its `combined_value`), else `null`.

**Identity share:** when a JWT carries `user_id` (after Twitch's identity-share dialog), Join and every later game call store it in `users.twitch_account_id` through `soft_accounts.record_twitch_account_id`. It is set only when empty and never overwritten with a different id; an id already held by another account is refused with 409 `twitch_identity_in_use` on Join and logged (not raised) on other calls.

**Activity:** `last_seen_at` is written by Join and by game calls, at most once an hour (`soft_accounts.touch_last_seen`).

**Rate limits** (slowapi, plain functions plus `*_route` wrappers as in `routers/cards.py`): `verify_twitch_jwt` puts the opaque id on `request.state`, and `rate_limit.key_by_twitch_viewer_or_ip` keys on it.

| Variable | Default | Applies to |
|---|---|---|
| `RATE_LIMIT_TWITCH_JOIN` | `10/minute` | Join, per viewer |
| `RATE_LIMIT_TWITCH_JOIN_IP` | `60/minute` | Join and both draws, per IP |
| `RATE_LIMIT_TWITCH_ACTION` | `30/minute` | Draws, roster changes and Leave, per viewer |

## Token drops

- **Pool:** unchanged query (`_active_pool`: presence within 10 minutes joined to `users.twitch_user_id`), which now includes soft accounts. `TWITCH_DROP_MAX` and one drop per match are unchanged. Since #171 a soft account must also be `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` old (default 24); website accounts are always eligible. This limits alt-account farming without requiring the identity share or a website account, which would break policy 4.5. See [Twitch Panel Abuse Limits](twitch-panel-abuse-limits.md).
- **Heartbeat:** the panel sends `POST /twitch/heartbeat` only while the viewer is joined. Since #171 the EBS ignores heartbeats from logged-out (`A…`) viewers and limits the route per viewer and per IP.
- **Chat:** `_mvp_chat_text(player_name, winner_count, pool_empty, drops_enabled)` names the MVP and the winner count only: "Match MVP: Savu! 3 viewers received a token.", or "No tokens were dropped: no joined viewers were watching." with an empty pool.
- **PubSub:** `{"type": "mvp", "player_name", "match_id", "token_drop": {"count", "refresh"}}`, with no names or ids. Every joined panel refreshes `GET /twitch/me` and shows "+1 token from the MVP drop" when its own balance went up.
- **Broadcaster response:** `token_drop` carries `enabled`, `winner_count`, `pool_size` and `already_dropped`, with no names: a winner on one of the website accounts (code-linked before #160, or connected with Twitch sign-in) has their website username as display name, which is never shown to the channel. Winner names are kept only in the `twitch_token_drop` audit log (admin only).
- **Kill switch:** `TWITCH_DROPS_ENABLED=false` skips `_execute_token_drop`: confirming an MVP sets the MVP and the fantasy bonus only, and chat says "Match MVP: X!".

## Link codes

- The panel's link-code entry is gone (`#view-unlinked`, `#link-code-input`, `#btn-link`, all kana-cards.com text); the panel never calls `POST /twitch/link`.
- Website accounts (code-linked before #160, or connected with Twitch sign-in) keep working: the panel finds them by `twitch_user_id` and shows their own tokens, collection and roster; they stay in the drop pool, and Join returns them.
- Profile no longer offers "Generate Twitch Code". Since #160 it offers **Connect Twitch** (Twitch sign-in, `twitch-account-connection.md`), and `POST /twitch/link-code` and `POST /twitch/link` are removed (404).

## Hidden from rankings: every `users` reader

| Reader | Treatment of soft accounts |
|---|---|
| `routers/leaderboard.py` `roster_leaderboard`, `compute_season_standings` (season leaderboard and End Season), `weekly_leaderboard` | Excluded: `WHERE u.is_tester = 0 AND u.account_type = 'full'` |
| `routers/admin_season.py` `end_season` | Excluded through `compute_season_standings`, so no `season_archive` row |
| `routers/admin_season.py` `reset_season` (`db.query(User).update(tokens)`) | Included: tokens reset like everyone's |
| `routers/admin_users.py` `list_users` (`GET /users`, the admin user search) | Filtered: `?account_type=full` (default) / `twitch` / `all`; rows carry `account_type`, `card_count`, `created_at`, `last_seen_at`, `twitch_linked`, `twitch_identity_shared` (booleans, never the ids) |
| `routers/admin_users.py` `DELETE /admin/users/{id}` (new, re-auth required) | Soft accounts only; website accounts get 409 |
| `routers/admin_users.py` toggle tester/admin, force logout, grant tokens, redeem, `is_admin_fresh` | By id; grant tokens works for soft accounts (audited by display name); the others are not offered for them in the UI |
| `routers/admin_tags.py` `grant_tag` | 404 for soft accounts (hidden from tag lists) |
| `routers/profile.py` `get_profile` | 404 for soft accounts (no public profile); `me`, username, player id and password routes need a website session, which a soft account can't have |
| `routers/auth.py` login, register, forgot/reset password, reauth, sessions, claim events, notifications | Username/session based: a soft account never matches |
| `routers/cards.py` draw, booster, reroll, roster, `get_roster` | By the acting user's id; audit names use `display_name` |
| `routers/cards.py` `get_card_image` (`users WHERE player_id`) | Soft accounts have no `player_id` |
| `routers/admin_players.py`, `routers/admin_demo.py`, `seed.py` | Website accounts by id or username only |
| `weeks.py` `auto_lock_weeks` | Included: snapshot and weekly +1 token |
| `sessions.py`, `deps.py` | `_session_user` returns none for a soft account |
| `twitch.py` link, status, presence pool, drops, game routes | By `twitch_user_id` (soft and linked website accounts alike) |
| `soft_accounts.py` | Creation, identity share, Leave and the retention purge |

There is no separate public user-search endpoint; "user search" is the admin user list's search box, which filters the account-type list it loaded.

## Leave and retention

- **Leave** (`POST /twitch/leave`, panel Settings → **Leave Kana Cards**, pressed twice): a soft account is deleted with all its rows (`soft_accounts.delete_soft_account`: cards, card modifiers, stored card points, roster entries, weekly-report state, code redemptions, token-grant claims, notification dismissals, sessions, tags, link codes, reset tokens and its presence row) and `twitch_soft_account_deleted` is audited with `reason=leave`. A website account only loses `twitch_user_id` (`twitch_account_unlinked`) and keeps everything, including its Twitch connection (#160). Leaving twice, or without an account, returns 200 `{left: false}`.
- **Admin delete:** Admin › User Management › Twitch viewers › **Delete** (`reason=admin`).
- **Retention:** `_week_maintenance_loop` runs `soft_accounts.purge_inactive_soft_accounts` once a day: soft accounts whose `last_seen_at` (or, when never set, `created_at`) is older than `TWITCH_SOFT_ACCOUNT_RETENTION_DAYS` are deleted with one audit entry each (`reason=retention`). A soft account with both `last_seen_at` and `created_at` NULL (never written by Join, only possible through direct database edits) is treated as idle and purged too. Website accounts are never purged.
- **Privacy pages:** `frontend/privacy.html` and `frontend/terms.html` state the retention as "365 days" in static text. If `TWITCH_SOFT_ACCOUNT_RETENTION_DAYS` is changed from its default, update both pages to the new value; they are not templated.

## Panel (318 × 500)

`twitch-extension/panel.html`, `panel.js`, `extension.css`; styles follow `design/colors_and_type.css` (tokens copied in, Big Shoulders Text packaged under `fonts/`).
- **Header:** brand, token count and a Settings button once joined.
- **Tabs:** Live, Cards, Roster (2 px orange underline on the active tab). The panel opens on Live for every viewer.
- **Live:** latest MVPs (with `(live)` markers), top performers, next match; refreshed every 60 s and at once on an MVP PubSub message. Each section shows a short neutral message when empty or when the EBS can't be reached. A joined soft account younger than the drop age shows a note line "Drops start for your account on <date>." above the sections (#171, from `drops_from` in `GET /twitch/me`).
- **Join:** "Join Kana Cards" with the consent line "Uses your Twitch login. We store your Twitch id and game progress; leave any time in Settings." It calls `Twitch.ext.actions.requestIdShare()` and then `POST /twitch/join`. Logged-out viewers see "Log in to Twitch to join" instead. The Cards and Roster tabs show the same box until the viewer joins.
- **Cards:** Draw · 1, Team draw · 3, the card reveal (tinted art with the rarity glow on the art, name, team, rarity, "Added to your roster/bench"), and the collection: count, rarity chips with counts (All, Leg, Epic, Rare, Com) and a five-per-row grid of 48 × 66 art, rarest first.
- **Team draw:** Back, the explainer line, a two-column list of 44 px team rows (logo or 28 × 28 monogram, name, "N left" or a disabled "Complete"), available teams first, `aria-pressed` selection, and the pinned "Draw from {team} · 3" button, disabled with "You need 3 tokens for a team draw" under 3 tokens.
- **Roster:** week label, lock countdown, week points, five slots ("+ Add a card" or "Change"), bench count. A slot opens its bench picker: "Pick a card for slot N" / "Replace in slot N", "In this slot: {name}" with **Bench it**, rarity chips with counts, sort by Points (season) or Rarity, one row per bench card. Placing returns to the roster with a confirmation line ("Savu in, Pikkis to the bench."). Locked: "Roster locked for this week", no buttons. No drag-and-drop.
- **Settings:** "Share your Twitch identity" (hidden once shared), **Leave Kana Cards**, and the privacy note.
- All data is escaped with `_escHtml`; there is no emoji, no password field and no website text.

`package.sh` refuses to build when a viewer file (`panel.html`, `panel.js`, `extension.js`, `extension.css`, and any `video*` component file) contains "kana-cards.com", "Log into", "Generate Twitch Code", "Link your account" or a password field. `config.html` and `live_config.*` are broadcaster-only and not checked; `config.html` no longer names the website either.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_DROPS_ENABLED` | `true` | MVP token drops to present joined viewers; `false` turns them off (MVP and bonus still set) |
| `TWITCH_SOFT_ACCOUNT_RETENTION_DAYS` | `365` | Days without activity before a soft account is deleted by the daily job |
| `RATE_LIMIT_TWITCH_JOIN`, `RATE_LIMIT_TWITCH_JOIN_IP`, `RATE_LIMIT_TWITCH_ACTION` | see above | Panel game route limits (heartbeat too, since #171) |
| `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` | `24` | Hours before a new soft account is in drop pools; `0` turns it off (#171) |
| `LOGO_HOST_ALLOWLIST` | Steam CDN hosts | Hosts team logos may load from (#171) |

## Manual setup for 1.2.0

- Twitch dev console → Version → Capabilities: enable **Request Identity Link** for the identity share.
- Team logos in the team picker load only from `LOGO_HOST_ALLOWLIST` hosts (Steam's CDNs by default, #171); add those hosts to the image allowlist if Twitch blocks them (the panel falls back to monograms).
- Set `TWITCH_EXTENSION_CLIENT_ID` on the EBS: since #171 it is the only extension origin CORS allows.
- Set `TWITCH_EXTENSION_VERSION=1.2.0` on the EBS once 1.2.0 is installed.

