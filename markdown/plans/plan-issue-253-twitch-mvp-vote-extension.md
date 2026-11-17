# Plan: Twitch MVP Vote Extension

## Context
Issue #253 asks for "another version entirely of the twitch extension", in which the streamer starts the MVP vote once the match is over and the watchers vote. The MVP is still selected and viewers still receive tokens. The open question in the issue: can the voters' Twitch ids reach the backend without the whole game being reproduced in the panel?

**Where we are:**
- **The current extension** (Kana Cards, 1.3.0 in review) is a full game in the panel: Join, draws, collection and roster. It was built that way because Twitch rejected 1.1.7 under policy 4.5: the panel sent viewers to an external login, and its only viewer value depended on the website ([Policy Compliance](../features/reference/twitch-extension-policy-compliance.md)).
- **The viewer vote already exists in the backend** (#234, `backend/twitch_mvp_poll.py`): open, vote, end, cancel, and confirmation through `POST /twitch/mvp`. Today only joined viewers of the full extension can vote, and it ships in that extension's 1.4.0.

**Answer to the issue's question: yes.** Every request from an extension carries a Twitch-signed token with the channel, the role and the viewer's opaque id (`U…` for a viewer logged in to Twitch). That is enough for one vote per viewer, with no game and no Join. Two limits shape the design:
- **Opaque ids are per extension.** A second extension has its own client id and secret, and a viewer's opaque id there differs from the one in the full extension. So the opaque id can't find an existing Kana Cards account.
- **The real Twitch id needs consent.** The token carries the real `user_id` only after the viewer accepts Twitch's identity share. That id matches `users.twitch_account_id`, which website accounts get through Connect Twitch and soft accounts through the share at Join.

**Decisions** (change them in review if needed):
- **A second extension, "Kana Cards MVP Vote",** with its own Twitch client id and secret, a small panel (the vote and its result) and the streamer's MVP tool. It has no Join, cards or roster. The backend stays one service.
- **Voting needs only a Twitch login.** One vote per opaque id per poll, changeable until the poll closes. Logged-out viewers see "Log in to Twitch to vote."
- **Tokens need the identity share.** After voting, the panel offers "Share your Twitch identity to enter the token drop". On confirmation, up to `TWITCH_DROP_MAX` voters who shared are picked at random and get one token each, as in today's drop.
  - A picked voter whose Twitch id belongs to a Kana Cards account (website or soft) is credited at once.
  - A picked voter with no account gets a **pending token**, stored under a keyed hash of the Twitch id, and claimed automatically when they connect Twitch on the website or join the full extension. Pending tokens expire after 60 days.
- **Policy risk, stated plainly:** tokens can only be used on kana-cards.com or in the full extension. That resembles what Twitch rejected in 1.1.7. The difference is that the vote works completely on Twitch with no external login, and the token is an optional extra. Twitch may still object. The plan keeps the token step behind one setting (`TWITCH_VOTE_TOKENS_ENABLED`), so the extension can be submitted, or resubmitted, as vote-only.
- **Same approval and rules as today:** the approved-streamers list, the series window, one MVP per match and one open poll per channel all apply. The streamer can still pick the MVP by hand on a tie or with no votes.
- **The full extension is unchanged.** Its 1.4.0 vote keeps working; both extensions use the same poll endpoints. A channel would normally install one of the two.

Resolves GitHub issue #253.

## User Stories

### The Streamer Runs an MVP Vote After the Match
**User story**
As a streamer, I want to start a viewer vote for the match MVP from a small extension, so that my viewers choose the MVP without me running the whole card game on my channel.

**Acceptance criteria**
- **Tool:** the vote extension's live configuration view lists the current series and its matches, as the MVP tool does today. A finished match (or a live one with known players) has **Start viewer vote** with a length of 1, 2 or 3 minutes.
- **Open:** opening the vote posts one chat message and updates every open panel. One poll can be open per channel; an unapproved channel gets the existing approval message.
- **Close and confirm:** the poll closes on its timer or with **End now**. The tool shows each player's votes with the sole winner selected; a tie or no votes lets the streamer pick. **Confirm MVP** sets the MVP exactly as today (MVP row, fantasy bonus, chat message, audit).
- **Cancel:** **Cancel vote** ends the poll with no MVP.

### A Viewer Votes With Only a Twitch Login
**User story**
As a viewer, I want to vote for the MVP in the panel without joining or logging in anywhere else, so that taking part is one click.

**Acceptance criteria**
- **Panel:** with no poll, the panel shows the channel's last MVP (if any) and "The streamer starts the vote after the match". With an open poll it shows the two teams' players, a countdown and **Vote**.
- **Who:** any viewer logged in to Twitch can vote; a logged-out viewer sees "Log in to Twitch to vote." and the API answers `403 twitch_login_required`.
- **One vote:** one vote per viewer per poll, changeable until it closes. While open, only the total number of votes is shown. After closing, everyone sees the result and the confirmed MVP.
- **No game:** the panel has no Join, cards, roster or link that is needed to vote.
- **Privacy:** no response contains another viewer's id or vote.

### Voters Can Win Tokens
**User story**
As a viewer who voted, I want a chance at a token, so that voting is rewarded the way watching is today.

**Acceptance criteria**
- **Enter:** after voting, the panel offers the identity share with one sentence on why. A viewer who shares is in the drop for that poll; one who doesn't can still vote.
- **Drop:** on **Confirm MVP**, up to `TWITCH_DROP_MAX` voters who shared are picked at random and get one token each. The chat message says how many tokens dropped.
- **Known account:** a picked voter whose Twitch id is on a Kana Cards account gets the token at once (`credit_tokens`), audited like today's drops.
- **No account yet:** a picked voter with no account gets a pending token. The panel says "You won a token. Claim it at kana-cards.com by signing in with Twitch." Connecting Twitch on the website, or joining the full extension with the identity share, credits every unexpired pending token once.
- **Limits:** one token per viewer per poll; pending tokens expire after 60 days; the stored key is a keyed hash, never the Twitch id.
- **Switch:** with `TWITCH_VOTE_TOKENS_ENABLED=false`, the share prompt and the drop are off and voting still works.

### The Operator Sets Up the Second Extension
**User story**
As the operator, I want the backend to accept the vote extension next to the full one, so that both can run against one service.

**Acceptance criteria**
- **Tokens:** `verify_twitch_jwt` accepts a token signed with either extension's secret and records which extension it came from. Game endpoints (join, draws, roster) refuse the vote extension's tokens with 403.
- **Messages:** PubSub and chat messages for a poll go out through the extension that opened it.
- **CORS:** the vote extension's origin is allowed, and no other.
- **Status:** Admin › Twitch › Twitch status shows the vote extension's configuration and its last token failures, separately from the full extension.
- **Package:** `bash twitch-vote-extension/package.sh <version> --ebs-origin <url>` builds its zip with the fixed EBS origins, like the full extension.

### The Extension Is Ready for Twitch Review
**User story**
As the maintainer, I want a submission guide for the vote extension, so that the review doesn't repeat the 1.1.7 rejection.

**Acceptance criteria**
- **Guide:** a submission document with the listing text, the endpoint disclosure, the chat messages, the identity-share explanation and testing steps for a reviewer.
- **Honest listing:** the listing says tokens are for the Kana Cards game and how they are claimed; the vote is described as usable without it.
- **Drift test:** every `/twitch/...` path the packaged files call is in the disclosure table, as for the full extension.
- **Vote-only fallback:** the guide has a variant for submitting with tokens switched off.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/twitch.py` | `verify_twitch_jwt` tries both secrets and tags the payload (`ext: "game"` or `"vote"`); per-extension PubSub and chat senders; a guard that refuses vote-extension tokens on game routes |
| `backend/twitch_mvp_poll.py` | Voter rule by extension (vote extension: Twitch login only); stores the voter's hashed real id when shared; drop pool from sharing voters |
| `backend/twitch_vote_rewards.py` (new) | Pending tokens: grant, claim on connect or join, expiry |
| `backend/models.py`, `backend/migrate.py` | New table `twitch_pending_tokens`; new columns `twitch_mvp_polls.extension` and `twitch_mvp_votes.account_hash` with numbered migrations |
| `backend/twitch_oauth.py`, `backend/soft_accounts.py` | Claim pending tokens when a Twitch id is attached to an account |
| `backend/main.py` | CORS origin for the second extension; startup check of the new settings |
| `backend/routers/admin_twitch.py`, `frontend/app-admin*.js` | Status rows for the vote extension |
| `twitch-vote-extension/` (new) | `panel.html/js`, `live_config.html/js`, `config.html/js`, `extension.js`, `extension.css`, `ebs-origins.js`, `package.sh` |
| `markdown/features/reference/twitch-mvp-vote-extension.md`, `twitch-vote-extension-review-submission.md`, `core/twitch-extension.md`, `.env.example` | Docs and settings |
| `backend/tests/test_issue_253_twitch_mvp_vote_extension.py` | Tests |

### Step 1 — Two extensions, one backend
Add `TWITCH_VOTE_EXTENSION_CLIENT_ID` and `TWITCH_VOTE_EXTENSION_SECRET`, and `TWITCH_VOTE_EXTENSION_VERSION` (added during implementation: Twitch needs the posting extension's version for chat messages). `verify_twitch_jwt` decodes with the game secret, then the vote secret, and sets `payload["ext"]`. Add a dependency `require_game_extension` to the game routes. Check how `verify_twitch_jwt`'s failure counters and `_remember_viewer` work, and keep them per extension.

### Step 2 — Vote rules and the reward pool
In `twitch_mvp_poll.vote`, branch on `ext`: the game extension keeps today's rules (joined, old enough); the vote extension needs a `U…` opaque id. Store on the poll which extension opened it. When the token carries `user_id`, store its keyed hash on the vote (use the hashing `twitch_starter_grants` already uses). Votes from either extension count in the same poll.

### Step 3 — Token drop for voters
On confirmation of a poll opened by the vote extension, pick up to `TWITCH_DROP_MAX` votes with an `account_hash` at random. For each: find the account by `twitch_account_id` and credit it, or insert a `twitch_pending_tokens` row (`account_hash`, `poll_id`, `created_at`, `expires_at`, `claimed_by_user_id`, `claimed_at`; unique on `account_hash` and `poll_id`). Reuse `twitch_token_drops` for the audit trail where it fits. Claim in `connect_account` and in the join path's identity share, in the same transaction as the credit, with a claimed-once update (`UPDATE … WHERE claimed_at IS NULL`).

### Step 4 — The extension package
Copy the shared pieces (`extension.js` auth and fetch helpers, `ebs-origins.js`, fonts and CSS tokens) and write a panel with three states (no poll, open poll, result) and the streamer tool with the series list, the vote controls and the manual pick. Listen for the `mvp_poll` PubSub messages. Use `Twitch.ext.actions.requestIdShare()` for the token step. The panel must fit Twitch's panel height.

### Step 5 — Admin status and docs
Add the vote extension to the Twitch status checks and the disclosure and submission documents, with the drift test.

### Step 6 — Tests
- A token signed with each secret is accepted and tagged; a bad one is refused; game routes refuse vote-extension tokens.
- Vote extension: a `U…` viewer votes without an account; an `A…` viewer gets 403; one vote per viewer; no ids in responses.
- Drop: only sharing voters are in the pool; a known account is credited once; an unknown one gets a pending token; a pending token is claimed once on connect and on join, never twice under concurrent claims; expired ones aren't claimed; the switch turns the drop off.
- PubSub and chat use the opening extension's credentials; CORS allows both origins only.
- Migration and schema coverage for the new columns.

## Verification
- In the Twitch developer rig or a hosted test with the vote extension on a test channel: open a vote, vote from two viewer accounts, confirm, and see the MVP on the website.
- A voter with a connected website account gets a token; a new viewer gets a pending token and receives it after connecting Twitch on the website.
- The full extension still works on another channel at the same time.
- Run `bash scripts/backup-db.sh` before deploying the migrations.
- Before submitting: decide whether to submit with tokens on, given the policy risk above, and ask Twitch developer support if in doubt.
