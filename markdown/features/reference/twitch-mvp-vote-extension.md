# Twitch MVP Vote Extension

A second, small Twitch extension, "Kana Cards MVP Vote". The streamer starts an MVP vote after a match, viewers vote with only their Twitch login, and voters who share their Twitch identity can win a token. It has no Join, cards or roster. Issue #253. Plan: `markdown/plans/plan-issue-253-twitch-mvp-vote-extension.md`.

Related: the full extension is in [Twitch Extension](../core/twitch-extension.md), the vote's backend in [MVP Poll for Watchers](twitch-mvp-viewer-poll.md), and the Twitch review material in [Vote Extension Review Submission](twitch-vote-extension-review-submission.md).

---

## Two extensions, one backend

Both extensions call the same backend. Each has its own Twitch client id and secret, and a channel normally installs one of the two.

| | Full extension ("game") | MVP Vote ("vote") |
|---|---|---|
| Package | `twitch-extension/` | `twitch-vote-extension/` |
| Settings | `TWITCH_EXTENSION_CLIENT_ID`, `_SECRET`, `_VERSION` | `TWITCH_VOTE_EXTENSION_CLIENT_ID`, `_SECRET`, `_VERSION` |
| Who votes | Joined viewers old enough for drops | Any viewer logged in to Twitch |
| Token drop on Confirm MVP | Joined viewers with the panel open | Voters who shared their Twitch identity |
| Game routes (Join, draws, roster) | Yes | Refused with 403 |

**How the backend tells them apart.** `verify_twitch_jwt` (`backend/twitch.py`) checks the token against the full extension's secret, then the vote extension's, and sets `payload["ext"]` to `"game"` or `"vote"`. The tag comes from the secret that verified the token; a claim of that name inside the token is overwritten. `require_game_extension` guards the game routes (`/twitch/join`, `/twitch/me`, `/twitch/draw`, `/twitch/draw/booster/{team_id}`, `/twitch/teams`, `/twitch/roster/*`, `/twitch/heartbeat`, `/twitch/leave`) and answers 403 to a vote-extension token.

**Messages.** A poll stores the extension that opened it (`twitch_mvp_polls.extension`). Its PubSub and chat messages are signed and sent with that extension's credentials (`broadcast_as`, `chat_as`). If those credentials are missing the message is skipped; the other extension's are never used instead.

**CORS.** `main.py` allows `https://<client id>.ext-twitch.tv` for each of the two client ids and nothing else (`twitch_status.extension_origin_regex`).

## Voting

The vote extension uses the poll routes that the full extension uses; see [MVP Poll for Watchers](twitch-mvp-viewer-poll.md) for the poll's life cycle.

- **Open, end, cancel, confirm:** unchanged. The approved-streamers list, the series window, one MVP per match and one open poll per channel all apply. A poll opened by either extension blocks a second one on the channel.
- **Who may vote:** in the vote extension a viewer needs only a Twitch login (an opaque id starting with `U`). A logged-out viewer gets `403 twitch_login_required`. No account is created. The full extension's rule (joined, and old enough for drops) is unchanged for its own tokens.
- **Both count:** votes from both extensions count in one poll. Opaque ids differ per extension, so a viewer with both panels open could vote twice; a channel is expected to install one.
- **No poll:** `GET /twitch/mvp-poll` from the vote extension returns `{"poll": null, "last_mvp": {...}}` with the channel's last confirmed MVP (`match_id`, `player_id`, `player_name`), or `last_mvp: null`.
- **Chat on open:** "MVP vote open for Team A vs Team B, game 1: vote in the Kana Cards MVP Vote panel. Closes in 2 min."

## Token drop for voters

The vote extension has no presence pool. A voter enters a poll's drop by accepting Twitch's identity share in the panel.

1. **Share.** After voting, the panel offers "Share your Twitch identity to enter the token drop". On acceptance Twitch issues a token that carries the real Twitch id, and the panel sends the vote again.
2. **Stored.** The vote row keeps `account_hash`: a keyed hash of the Twitch id (`soft_accounts.starter_grant_hash`, HMAC-SHA256 keyed from `SECRET_KEY`). The id itself is not stored. Only votes in a vote-extension poll get a hash.
3. **Drop.** On **Confirm MVP** of a vote-extension poll, `twitch_vote_rewards.drop_for_poll` picks up to `TWITCH_DROP_MAX` distinct hashes at random, one token each.
   - **Known account:** when the hash matches an account's `twitch_account_id` (a website account with Connect Twitch, or a soft account that shared its identity at Join), the token is credited at once.
   - **No account:** a row is added to `twitch_pending_tokens`, expiring after 60 days.
4. **Once per match.** The drop claims the same `twitch_token_drops` row as the full extension's presence drop, so one match never drops twice. The audit entry is `twitch_token_drop` with `poll=` and `pending=` added.
5. **Chat on confirm:** "Match MVP by viewer vote: PlayerName (60% of 5 votes)! 3 voters won a token." With nobody in the pool the drop sentence is left out.

An MVP picked by hand in the vote extension, without a poll, drops no tokens.

### Pending tokens

A pending token is claimed when its Twitch id is attached to an account:

- **Connect Twitch** on the website (`twitch_oauth.connect_account`), in the same commit as the connection.
- **Identity share in the full extension**, at Join or on a later panel request (`soft_accounts.record_twitch_account_id`, `get_or_create_soft_account`).

`twitch_vote_rewards.claim_pending` claims with one `UPDATE … WHERE claimed_at IS NULL AND expires_at > now`, so two simultaneous claims credit each token once. The claim is audited as `twitch_pending_tokens_claimed`.

**One Twitch account per Kana Cards account.** An account that has claimed tokens won by one Twitch id claims nothing for another: connecting and disconnecting a series of Twitch accounts can't collect their tokens in one account, which is what the one-merge limit prevents for soft accounts. The refused tokens stay unclaimed and expire, and the refusal is audited as `twitch_pending_tokens_refused`.

The daily maintenance job deletes unclaimed rows past `expires_at`, and claimed rows 60 days after the claim; until then the claimed row is the record that enforces the rule above.

After confirmation, the poll view tells a pending winner so (`token_drop.pending_win`), and the panel shows "You won a token. Claim it at kana-cards.com by signing in with Twitch."

### Poll view additions

For a vote-extension poll, `poll_view` adds `token_drop`:

| Field | Meaning |
|---|---|
| `enabled` | Tokens are on (`TWITCH_DROPS_ENABLED` and `TWITCH_VOTE_TOKENS_ENABLED`) |
| `entered` | This viewer's vote carries a hash, so it is in the drop |
| `pending_win` | The poll is confirmed and this viewer's Twitch id has an unclaimed pending token from it |

No response or PubSub message contains another viewer's id, hash or vote.

### Switching tokens off

`TWITCH_VOTE_TOKENS_ENABLED=false` turns the token step off: no hash is stored, the panel shows no share prompt, Confirm MVP drops nothing and chat has no drop sentence. Voting and confirmation still work. This is the setting to use if Twitch objects to the token step in review. `TWITCH_DROPS_ENABLED=false` turns it off as well, along with the full extension's drops.

## Package

`twitch-vote-extension/` is self-contained, like the full extension's folder.

| File | Purpose |
|---|---|
| `panel.html`, `panel.js` | Viewer panel: no vote (last MVP), open vote, result |
| `live_config.html`, `live_config.js` | Streamer tool in Quick Actions: series, match, **Start viewer vote** (1, 2 or 3 minutes), **End now**, **Cancel vote**, **Confirm MVP**, or a hand pick |
| `config.html`, `config.js` | Setup text and the connection check |
| `extension.js`, `extension.css`, `ebs-origins.js`, `fonts/` | Shared helpers, styles, packaged backend origins |
| `package.sh` | Builds the zip |

```
bash twitch-vote-extension/package.sh 1.0.0 --ebs-origin https://kana-cards.com
```

The script writes the given origins into the packaged `ebs-origins.js` and refuses to build when a viewer file contains a link, a login form or a game route. Set the backend URL in the vote extension's global configuration with `twitch-extension/set-ebs-url.sh`, run with the vote extension's client id and secret.

In the Twitch console, the version needs **Request Identity Link** (for the identity share) and **Chat Capabilities** switched on.

## Admin status

Admin › Twitch › Twitch status lists the vote extension's three settings as their own rows, and counts its accepted and refused tokens apart from the full extension's (`traffic.vote` in `GET /admin/twitch/status`). Unset settings show as a warning: a league may run only the full extension. A client id without a secret, or the reverse, shows as a problem and is logged at start-up.

A refused token is counted for the vote extension when its secret verified the signature (an expired token), or when the request's `Origin` is the vote extension's.

## Database

| Table | Change |
|---|---|
| `twitch_mvp_polls` | New column `extension` (`game` or `vote`, default `game`); migration `045_twitch_mvp_polls_extension` |
| `twitch_mvp_votes` | New nullable column `account_hash`; migration `046_twitch_mvp_votes_account_hash`. Rows are deleted 30 days after the poll ends |
| `twitch_pending_tokens` | New table: `id`, `account_hash`, `poll_id`, `created_at`, `expires_at`, `claimed_by_user_id`, `claimed_at`; unique on (`account_hash`, `poll_id`) |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_VOTE_EXTENSION_CLIENT_ID` | *(empty)* | Client id of the vote extension. Its origin is allowed by CORS |
| `TWITCH_VOTE_EXTENSION_SECRET` | *(empty)* | Its extension secret (base64), from Extension Secrets in the Twitch console. A secret: keep it only in the environment |
| `TWITCH_VOTE_EXTENSION_VERSION` | *(empty)* | Installed version of the vote extension. Needed for its chat messages; unset, they are skipped |
| `TWITCH_VOTE_TOKENS_ENABLED` | `true` | `false` turns off the identity-share prompt and the voter token drop |

`TWITCH_DROP_MAX`, `TWITCH_DROPS_ENABLED` and `TWITCH_MVP_CHANNEL_IDS` apply to both extensions.

## Limits

- **Local development:** `TWITCH_LOCAL_DEV=true` returns a fixed broadcaster payload without an `ext` tag, so requests follow the full extension's rules. The vote extension's viewer rules are covered by tests, and need a hosted test on Twitch to try by hand.
- **Many Twitch accounts:** a vote needs only a Twitch login, and the drop has no account-age rule (the full extension's `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` applies to soft accounts, which this extension does not create). One person with several Twitch accounts gets several votes and several entries. The vote route is limited per viewer and per IP (`RATE_LIMIT_TWITCH_ACTION`, `RATE_LIMIT_TWITCH_JOIN_IP`), each entry is one Twitch-verified id, and a drop gives at most `TWITCH_DROP_MAX` tokens.
- **Policy risk:** tokens are only usable on kana-cards.com or in the full extension, which resembles what Twitch rejected in version 1.1.7 of the full extension. The vote itself works entirely on Twitch. See the submission guide for the vote-only variant.
