# Vote Extension Review Submission

What to paste into the Twitch console when submitting **Kana Cards MVP Vote** (`twitch-vote-extension/`) for review, and how a reviewer can test it. Issue #253. The extension itself is described in [Twitch MVP Vote Extension](twitch-mvp-vote-extension.md); the full extension has its own guide, [Twitch Extension Review Submission](twitch-extension-review-submission.md).

The full extension's version 1.1.7 was rejected under policy 4.5 because its only viewer value depended on an external login. This extension is built so that its viewer function, the vote, works completely on Twitch. The token drop is an optional extra, and this guide has a [vote-only variant](#vote-only-variant-tokens-switched-off) without it.

Legal pages, support contact and category are the same as for the full extension; take them from that guide.

---

## Before submitting

- [ ] Decide whether to submit with tokens on. If in doubt about policy 4.5, ask Twitch developer support first, or use the vote-only variant.
- [ ] Build the package: `bash twitch-vote-extension/package.sh 1.0.0 --ebs-origin https://kana-cards.com`.
- [ ] In the version's Capabilities, switch on **Request Identity Link** and **Chat Capabilities**, and add `https://kana-cards.com` to the Allowlist for URL Fetching Domains.
- [ ] Set the backend URL in the extension's global configuration with `twitch-extension/set-ebs-url.sh`, using this extension's client id and secret.
- [ ] Set `TWITCH_VOTE_EXTENSION_CLIENT_ID`, `TWITCH_VOTE_EXTENSION_SECRET` and `TWITCH_VOTE_EXTENSION_VERSION` on the server, and check Admin › Twitch › Twitch status.
- [ ] Move the version to Hosted Test and run the testing steps below on a test channel.

## Listing copy

**Name:** Kana Cards MVP Vote

**Summary** (one line):
> Viewers vote for the match MVP of Kanaliiga Dota 2 games, right in the panel, with only their Twitch login.

**Description** (paste as plain text, without the `**` markers; under 1,024 characters):
> After a match, the broadcaster starts a timed vote for the match MVP. Viewers logged in to Twitch vote in the panel with one click and can change their vote until it closes. Voting needs no account, sign-up or website. When the vote closes, everyone sees the result and the MVP the broadcaster confirms.
>
> **Twitch Chat:** the extension posts one message when a vote opens ("MVP vote open for Team A vs Team B, game 1: vote in the Kana Cards MVP Vote panel. Closes in 2 min.") and one when the broadcaster confirms the MVP ("Match MVP by viewer vote: PlayerName (60% of 5 votes)! 3 voters won a token."). No viewer names are posted. It never reads chat.
>
> **Optional token drop:** a voter may share their Twitch identity to enter a token drop. Tokens are for the Kana Cards game, a free fantasy card game for the same league, and have no money value. A winner claims a token by signing in with Twitch at kana-cards.com or by joining the Kana Cards extension. Voting works without either.

## EBS URL disclosure (paste into "Notes for reviewer")

> The Extension's backend (EBS) origins are fixed in this package at build time, in `ebs-origins.js` (`EBS_ALLOWED_ORIGINS`). This package allows only **`https://kana-cards.com`**. The backend URL itself is read at runtime from the Extension Configuration Service's global config segment (`ebs_url` key), and the Extension uses it only when its origin is one of the packaged origins; otherwise it shows a short error code and makes no backend call. All Extension frontend network calls go to this single host, at the paths listed below.
>
> No other external domain is contacted from the Extension's own frontend code (the Twitch Extension Helper script is loaded from Twitch's own `extension-files.twitch.tv` CDN, per Twitch's required inclusion). Fonts are packaged. The panel loads no images.
>
> Privacy Policy: https://kana-cards.com/privacy.html — Terms of Service: https://kana-cards.com/terms.html

### Endpoints the Extension frontend calls (all under `https://kana-cards.com`)

Every request carries the Twitch-signed extension token in the `Authorization` header. A test keeps this table in step with the packaged files (`test_issue_253_twitch_mvp_vote_extension.py`).

| Path | Method | Called by | Purpose |
|---|---|---|---|
| `/twitch/mvp-poll` | GET | Panel, streamer tool | The channel's current vote, or its last MVP when there is none |
| `/twitch/mvp-poll/{poll_id}/vote` | POST | Panel | Cast or change the viewer's vote |
| `/twitch/matches/current` | GET | Streamer tool | The current series and their matches, for choosing the match |
| `/twitch/mvp-poll` | POST | Streamer tool | Start a vote for a match (1, 2 or 3 minutes) |
| `/twitch/mvp-poll/{poll_id}/end` | POST | Streamer tool | End the vote now |
| `/twitch/mvp-poll/{poll_id}/cancel` | POST | Streamer tool | Cancel the vote with no MVP |
| `/twitch/mvp` | POST | Streamer tool | Confirm the MVP |
| `/twitch/ping` | GET | Configuration page | Connection check: is the backend reachable |
| `/twitch/check` | GET | Configuration page | Connection check: is the token accepted, is the channel approved |

## Chat capability disclosure

The Extension posts two kinds of message through Twitch's Extension Chat capability, both built by the backend (`open_chat_text` in `backend/twitch_mvp_poll.py`, `_mvp_chat_text` in `backend/twitch.py`). Names are cleaned (`chat_safe_name`) and each message is capped at 280 characters.

| Case | Exact message |
|---|---|
| The broadcaster starts a vote | `MVP vote open for Team A vs Team B, game 1: vote in the Kana Cards MVP Vote panel. Closes in 2 min.` (1, 2 or 3 min) |
| The broadcaster confirms the vote's winner, and voters won tokens | `Match MVP by viewer vote: PlayerName (60% of 5 votes)! 3 voters won a token.` (`1 voter won a token.` for one) |
| The broadcaster confirms the vote's winner, and no token was dropped | `Match MVP by viewer vote: PlayerName (60% of 5 votes)!` |
| The broadcaster confirms another player, or picks the MVP without a vote | `Match MVP: PlayerName!` (followed by the same token sentence when a vote's tokens were dropped) |

No viewer names or usernames are posted. The Extension never reads, stores or moderates chat. "Tokens" are the game's own free virtual currency, unrelated to Twitch Bits.

## Identity share explanation (paste into "Notes for reviewer")

> The identity share is **optional**. Voting never asks for it: every viewer logged in to Twitch can vote, and a viewer who declines the share keeps their vote.
>
> The share is used **only for the token drop**. After voting, the panel offers "Share your Twitch identity to enter the token drop", with the sentence "Kana Cards uses it only to give a token to voters picked in the drop." Pressing the button calls `Twitch.ext.actions.requestIdShare()`, and Twitch shows its own consent prompt.
>
> The backend does not store the Twitch user id for this. It stores **only a keyed hash** of it (HMAC-SHA256, keyed with a server secret), on the viewer's vote and, if the viewer wins and has no Kana Cards account yet, on one pending-token record. Votes are deleted 30 days after the vote ends. An unclaimed pending token is kept for **at most 60 days** and then deleted; a claimed one is deleted 60 days after the claim. The hash is never sent to any client, and no response contains another viewer's id or vote.
>
> A winner who already plays Kana Cards with the same Twitch account gets the token at once. A winner with no account sees "You won a token. Claim it at kana-cards.com by signing in with Twitch." in plain text; there is no link, and nothing in the panel needs it.

## Testing instructions (paste into "Testing Instructions")

The league approves a test channel before review; the reviewer needs no account outside Twitch.

**As the broadcaster**

1. Open **Stream Manager → Quick Actions** and click **Kana Cards MVP Vote**.
2. Click **Select match MVP**, choose a series, then a match.
3. With **Start viewer vote** selected, choose a vote length and click **Start viewer vote**. Chat shows the "MVP vote open…" message.
4. Wait for the timer, or click **End now**. The tool shows each player's votes, with the winner selected. On a tie or with no votes, pick a player.
5. Click **Confirm MVP**. Chat shows the "Match MVP…" message. **Cancel vote** instead ends the vote with no MVP and no message.

**As a viewer**

1. Open the channel page while logged in to Twitch. With no vote, the panel shows the last MVP and "The streamer starts the vote after the match".
2. When the vote opens, the panel shows both teams' players and a countdown. Click a player, then **Vote**. The panel confirms the vote; it can be changed until the vote closes.
3. Optional: click **Share identity** under "Share your Twitch identity to enter the token drop" and accept Twitch's prompt. The panel then says "You are in the token drop for this vote." Declining changes nothing about the vote.
4. When the vote closes, the panel shows the result, and the MVP once the broadcaster confirms it.
5. Logged out of Twitch, the panel shows the players and "Log in to Twitch to vote." with no Vote button.

## Vote-only variant (tokens switched off)

Use this variant to submit, or resubmit, without the token step.

1. Set `TWITCH_VOTE_TOKENS_ENABLED=false` on the server before submitting. The panel then never shows the share prompt, the backend stores no identity hash, Confirm MVP drops nothing, and the confirmation message in chat has no token sentence.
2. Switch **Request Identity Link** off in the version's Capabilities.
3. Use the listing below, and leave the "Identity share explanation" out of the notes for the reviewer.
4. In the testing instructions, leave out viewer step 3.

**Description (vote-only):**
> After a match, the broadcaster starts a timed vote for the match MVP. Viewers logged in to Twitch vote in the panel with one click and can change their vote until it closes. Voting needs no account, sign-up or website. When the vote closes, everyone sees the result and the MVP the broadcaster confirms.
>
> **Twitch Chat:** the extension posts one message when a vote opens ("MVP vote open for Team A vs Team B, game 1: vote in the Kana Cards MVP Vote panel. Closes in 2 min.") and one when the broadcaster confirms the MVP ("Match MVP by viewer vote: PlayerName (60% of 5 votes)!"). No viewer names are posted. It never reads chat.

## Review history

Not submitted yet.
