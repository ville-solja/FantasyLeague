# Twitch Incident Runbook

What to do if something goes wrong with the Twitch sign-in, the Twitch developer account, the extension's secrets or soft-account merges. For the operator. Built with issue #160.

*(see `twitch-account-connection.md`, `twitch-extension-policy-compliance.md`, `markdown/plans/plan-issue-160-twitch-account-connection-oidc.md`)*

---

## Before anything goes wrong

- **Developer account:** two-factor sign-in is on for the Twitch account that owns the extension and the sign-in app, and console access is limited to the people who need it.
- **Redirect addresses:** you know which addresses are registered (one per environment, for example `https://kana-cards.com/auth/twitch/callback`), and each environment's `TWITCH_OAUTH_REDIRECT_URI` equals its address.
- **Backups:** `bash scripts/backup-db.sh` runs before every deploy (see `db-sustainability.md`). It copies only the database file, never `.env`.

## 1. Switch off

- **Twitch sign-in:** unset any of `TWITCH_OAUTH_CLIENT_ID`, `TWITCH_OAUTH_CLIENT_SECRET` or `TWITCH_OAUTH_REDIRECT_URI` and restart. Profile shows "Connecting Twitch is not available right now." and `GET /auth/twitch/start` returns 503. Existing connections, merges and the panel keep working.
- **Drops:** set `TWITCH_DROPS_ENABLED=false` and restart. MVP confirmations stop granting tokens.
- **Everything Twitch-related** (for example a suspected extension secret leak): also unset `TWITCH_EXTENSION_SECRET`. Panel requests then fail with 500 and the website is unaffected.

## 2. Rotate secrets

In the Twitch developer console (https://dev.twitch.tv/console):
1. **Sign-in client secret:** open the application used for sign-in (Applications › Manage) and create a new client secret. Set it as `TWITCH_OAUTH_CLIENT_SECRET`.
2. **Extension secret:** open the extension's settings, create a new extension secret and set it as `TWITCH_EXTENSION_SECRET`. The console says whether the old secret stays valid for a while; until it expires, a leaked old secret can still sign tokens. *(Confirm the exact menu names on the next rotation and note them here.)*
3. Restart the app. Check that the panel loads (`GET /twitch/me`) and that **Connect Twitch** on a test account reaches Twitch and returns to Profile with "Twitch connected."

No Twitch tokens are stored, so nothing else needs revoking on our side.

## 3. Review what happened

In Admin › Audit Log, look in the affected period for:
- `twitch_connected` (detail `user_id=…`, plus `pending_merge_user_id=…` when a collection was waiting),
- `twitch_account_merged` (`full_user_id`, `soft_user_id`, counts, `log_id`),
- `twitch_disconnected`,
- `twitch_merge_reversed`, `twitch_panel_recognised`, `twitch_soft_account_created`, `twitch_soft_account_deleted`,
- `player_reauth` / `admin_reauth` (password checks before those actions).

Server logs show failed sign-ins as `Twitch sign-in failed for user N: <reason>` with no codes or tokens. Check the registered redirect addresses in the console: an unexpected address is a sign of console compromise.

## 4. Repair

- **Bad merges:** within 30 days, Admin › User Management › **Twitch collection merges** › **Show recent merges** (password check) › **Reverse**, or `POST /admin/twitch/merges/{log_id}/reverse`. The Twitch viewer account is recreated with its cards, tokens and locked-week rosters; the website account is disconnected and can connect and merge again. Tokens already spent are reported as a shortfall. Reversal is refused after 30 days, if already reversed, or after a season reset.
- **A wrongly connected account:** the player (or an admin acting for them) presses **Disconnect** on Profile.
- **Wider damage:** restore the latest good backup made by `scripts/backup-db.sh` or the automatic backup loop (see `db-sustainability.md`).

## 5. Tell players

Post a short, honest note in the usual Kanaliiga channels:
- what happened,
- what was affected (game state, or the link between Twitch and website accounts),
- what was done,
- what players should do (for example, disconnect and reconnect Twitch on Profile).

Kana Cards never stores Twitch passwords or tokens. Say so if relevant.
