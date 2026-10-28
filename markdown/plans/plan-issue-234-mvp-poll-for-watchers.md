# Plan: MVP Poll for Watchers

## Context
Issue #234 asks to investigate letting the viewers choose a match MVP instead of the caster. The streamer starts a poll, viewers pick one of the 10 players before a timer runs out, and the MVP and the token drop then work much as they do now. The poll must target the right match when several are played in one night.

**Timing:** milestone S17. The owner's comment (2026-10-26): not to be built during S16, until the first version of the extension (1.3.0) has passed review.

**How MVP selection works today** (`backend/twitch.py`, `twitch-extension/live_config.*`):
- **Who picks:** the broadcaster picks in Quick Actions. They choose a series from the 5 most recent (`_current_series`), then a match, then the player, and press **Confirm MVP & Drop Tokens** (`POST /twitch/mvp`).
- **Who may:** only approved channels (`mvp_channel_allowed`), and only matches in the series window (`_eligible_mvp_match_ids`). A live match without stats can be picked from its live players (provisional MVP).
- **On confirm:**
  - one `twitch_mvp` row per match (upsert);
  - the fantasy bonus;
  - a token drop once per channel and match to up to `TWITCH_DROP_MAX` joined viewers in the presence pool (heartbeat within 10 minutes; soft accounts must be `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` old);
  - a PubSub message to every open panel;
  - one chat message (`_mvp_chat_text`).

**Investigation findings:**
- **No `!mvp` chat command.** An extension can post to chat but can't read it. Reading `!mvp` would need a chat bot holding a user token with `user:read:chat` (EventSub `channel.chat.message`): a second Twitch integration, a new secret and another review topic. The streamer starts the poll from Quick Actions instead, where the MVP tool already is, and the extension announces it in chat.
- **Twitch's own Polls are no use.** They allow at most 5 choices (we need 10) and need the broadcaster's OAuth token with `channel:manage:polls`. So voting happens in the panel.
- **Match choice is solved already.** The poll opens from the same series → match picker, so it is tied to one `match_id`. That settles the "several matches in one night" concern without a new mechanism.
- **Channels and rate limits:** PubSub can carry "poll open" and "poll closed" to every panel. Its limit (one message per second per channel) and chat's (12 per minute) are far above what a poll needs.
- **Review impact:** a new chat message is exactly what the 4.2 rejection was about. The new message and the voting view must be disclosed in a new extension version's review notes.

**Decisions** (change them in review if needed):
- **Both modes stay.** The MVP tool's match view gets two buttons: **Pick MVP** (today's flow) and **Start viewer vote**. The streamer chooses per match.
- **Timer:** 60, 120 or 180 seconds, 120 by default. The poll closes at `closes_at` without a background job: its state is worked out on every read. The streamer can **End now** (closes early) or **Cancel** (no result).
- **One poll at a time:** at most one open poll per channel. A match whose poll was confirmed can't be polled again, but the streamer can still change its MVP with Pick MVP.
- **Players:** the poll lists the match's 10 players, grouped by team. They come from ingested stats, or from the live players for a live match, as in the MVP tool.
- **Who votes:** joined viewers who are eligible for drops (an account, and a soft account old enough). This reuses the drop rules, so the same alt limit protects the vote. Others see the poll and the message "Join to vote", or "Your vote counts from <date>".
- **Voting rules:**
  - one vote per viewer, which they can change until the poll closes;
  - while the poll is open, only the total number of votes shows, to avoid bandwagoning;
  - after it closes, the results show as a percentage per player.
- **The streamer confirms.** The MVP gives fantasy points to everyone who owns that player's card, so a vote alone doesn't write it:
  - when the poll closes, the MVP tool shows the result with the winner preselected;
  - **Confirm MVP & Drop Tokens** runs the existing `set_mvp` with the poll id;
  - a tie shows the tied players, and the streamer picks one;
  - a poll with no votes falls back to Pick MVP.
  - **Override:** the streamer can confirm another player. The audit and chat then say it was the caster's pick, not the vote.
- **Drops and the bonus are unchanged:** the same presence pool, once per channel and match, applied on confirmation.
- **Chat:** two new messages, both counts only, never viewer names:
  - on open: `MVP vote open for {team1} vs {team2}, game {n}: vote in the Kana Cards panel. Closes in 2 min.`
  - on confirm: `Match MVP by viewer vote: {name} ({pct}% of {votes} votes)! {N} viewers received a token.`
  - both are cut to 280 characters, with names from `chat_safe_name`.
- **Data:** two new tables, so no migration:
  - `twitch_mvp_polls` holds the channel, match, status (`open`/`closed`/`cancelled`/`confirmed`), `opened_at`, `closes_at`, `closed_at` and the confirmed player;
  - `twitch_mvp_votes` holds the poll, the voter's opaque Twitch id, the player and the time, unique per poll and voter.
  - **Retention:** votes are deleted 30 days after the poll ends, and with the account on Leave Kana Cards. Only per-player counts are kept.
- **Code layout:** a new module `backend/twitch_mvp_poll.py` holds its own router under `/twitch`, so `twitch.py` (1,500 lines) doesn't grow. It reuses `verify_twitch_jwt`, `_require_broadcaster`, `mvp_channel_allowed`, `_eligible_mvp_match_ids`, `_active_pool` rules, `_pubsub_broadcast`, `_post_chat_message` and `chat_safe_name`.
- **Extension version:** a new version (1.4.0) with an updated review walkthrough and change log. The privacy page gains a line on votes.

Resolves GitHub issue #234.

## User Stories

### The Streamer Starts a Viewer Vote for a Match
**User story**
As a broadcaster on an approved channel, I want to start a timed MVP vote for a specific match from Quick Actions, so that my viewers choose the MVP.

**Acceptance criteria**
- **Start:** the MVP tool's match view has **Start viewer vote** next to **Pick MVP**, with a timer choice of 1, 2 or 3 minutes (2 by default).
- **Right match:** the vote opens for the match picked in the series → match picker. It works for a match with stats and for a live match without stats, using its live players.
- **Refused cases** (nothing is written):
  - a channel that isn't approved (`403`, with an approval request recorded as for MVPs);
  - a match outside the series window (`403`);
  - a second open poll on the channel (`409`);
  - a match whose poll was already confirmed (`409`).
- **Announce:** opening the poll posts one chat message naming the teams, the game number and the time left, and sends a PubSub "poll open" message to every panel.
- **Control:** while it's open, the tool shows a countdown and the number of votes, with **End now** and **Cancel**. Cancel ends the poll without a result and posts no MVP.

### Viewers Vote in the Panel
**User story**
As a viewer watching the stream, I want to vote for the MVP in the panel, so that the audience decides who played best.

**Acceptance criteria**
- **Shown:** while a poll is open on the channel, the Live tab shows it at the top: the match, a countdown, the 10 players grouped by team, and a **Vote** button. A panel opened mid-poll shows it too (`GET /twitch/mvp-poll`).
- **Who can vote:** joined viewers eligible for drops. A viewer who hasn't joined sees "Join to vote". A soft account too new for drops sees "Your vote counts from <date>". Their votes are refused with `403`.
- **One vote:** a viewer has one vote and can change it until the poll closes. A vote after `closes_at`, or for a player not in the match, is refused (`409` and `422`).
- **No bandwagon:** while the poll is open, only the total number of votes shows. After it closes, the panel shows each player's share and the viewer's own pick.
- **Limits:** voting is rate-limited per IP like the other panel actions.

### The Streamer Confirms the Vote's Result
**User story**
As a broadcaster, I want to confirm the poll's winner with one click, so that the MVP, the fantasy bonus and the token drop happen as they do today.

**Acceptance criteria**
- **Result:** when the poll closes (timer or **End now**), the tool shows each player's votes with the winner preselected. A tie preselects no one and lists the tied players. A poll with no votes says so and opens Pick MVP.
- **Confirm:** **Confirm MVP & Drop Tokens** calls `POST /twitch/mvp` with the poll id. The MVP row, bonus, token drop (once per channel and match), PubSub message and audit work as they do today, and the poll becomes `confirmed`.
- **Chat:** a confirmed vote posts "Match MVP by viewer vote: {name} ({pct}% of {votes} votes)!" and then the existing drop sentence. If the streamer confirms someone other than the vote's winner, the message is the existing "Match MVP: {name}!" one, and the audit records `override=True`.
- **Audit:** `twitch_mvp_poll_opened`, `twitch_mvp_poll_closed` (votes, winner, tie) and `twitch_mvp_poll_cancelled`, with no voter ids.

### Votes Are Kept Only as Long as Needed
**User story**
As a viewer, I want my vote stored only briefly, so that voting doesn't build a record about me.

**Acceptance criteria**
- **Retention:** individual votes are deleted 30 days after their poll ends (the daily cleanup). The poll keeps only per-player counts.
- **Leave:** Leave Kana Cards deletes the soft account's votes.
- **Disclosure:** the privacy page and the extension's review notes mention votes. The review walkthrough has a step for starting, voting in and confirming a poll, and the 1.4.0 change log lists the new chat messages.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `TwitchMvpPoll` and `TwitchMvpVote` (new tables, no migration) |
| `backend/twitch_mvp_poll.py` (new) | Router under `/twitch`: open, read, vote, end and cancel; lazy close; tally; chat text; retention cleanup |
| `backend/twitch.py` | `MVPBody.poll_id` (optional); `set_mvp` checks the poll is closed and for the same match and channel, marks it `confirmed`, and picks the vote or override chat text; Leave deletes the account's votes |
| `backend/main.py` | Mount the router; add the vote cleanup to the daily task |
| `twitch-extension/live_config.html`, `live_config.js` | Pick MVP or Start viewer vote, timer choice, countdown, End now and Cancel, result view with confirm |
| `twitch-extension/panel.html`, `panel.js`, `extension.js`, `extension.css` | Poll card on the Live tab, vote, closed results; PubSub `mvp_poll` handling |
| `frontend/privacy.html` | Votes: what is stored and for how long |
| `markdown/features/reference/twitch-extension-review-submission.md`, `twitch-extension-resubmission.md` | 1.4.0 walkthrough step, chat disclosure and change log |
| `markdown/features/core/twitch-extension.md`, `markdown/features/reference/twitch-mvp-viewer-poll.md` | Docs |
| `backend/tests/test_issue_234_mvp_poll_for_watchers.py` | Tests |

No migration (new tables only), no new env var. The timer choices and the 30-day vote retention are constants in the module.

### Step 1 — Models
`TwitchMvpPoll`: `id`, `channel_id`, `match_id`, `status`, `opened_at`, `closes_at`, `closed_at`, `confirmed_player_id`, `tally_json` (the per-player counts, written on close). `TwitchMvpVote`: `id`, `poll_id`, `twitch_user_id`, `player_id`, `voted_at`, with a unique constraint on (`poll_id`, `twitch_user_id`). One open poll per channel is checked in the open endpoint inside the transaction.

### Step 2 — Endpoints (`twitch_mvp_poll.py`)

```
POST /twitch/mvp-poll                 broadcaster  {match_id, duration_seconds}  → poll
GET  /twitch/mvp-poll                 any viewer   → open or last closed poll for the channel, own vote
POST /twitch/mvp-poll/{id}/vote       joined, eligible  {player_id}
POST /twitch/mvp-poll/{id}/end        broadcaster  → closes now, returns the tally
POST /twitch/mvp-poll/{id}/cancel     broadcaster
```

Every read closes a poll whose `closes_at` has passed (`status=closed`, `tally_json`, audit). Voter eligibility reuses the drop rules from `twitch.py` (`_panel_account`, the age check behind `_active_pool`).

### Step 3 — Confirm through `set_mvp`
`MVPBody` gains an optional `poll_id`. When it's given, the poll must be `closed`, on the same channel and match. After the existing writes, the poll is set to `confirmed`, and the chat text is the vote version when the player is the vote's sole winner (otherwise the existing text, with `override=True` in the audit).

### Step 4 — Extension
- **Live config:** two buttons in the match view, the timer select, the open-poll view (countdown from `closes_at`, vote count polled every 5 s), and the result view with confirm.
- **Panel:** the poll card on the Live tab, from PubSub `{"type":"mvp_poll","state":"open"|"closed"|"cancelled","poll_id":…}` and `GET /twitch/mvp-poll` on load. The policy 4.5 rules for viewer files apply (`package.sh` checks).

### Step 5 — Retention, privacy and review
- the daily cleanup deletes votes of polls ended over 30 days ago;
- the privacy page gets its line on votes;
- package 1.4.0;
- update the walkthrough, the chat disclosure and the change log.

### Step 6 — Tests
- **Open:** approved channel only; series window; one open poll per channel; a match already confirmed; live match players.
- **Vote:** eligibility (not joined, too-new soft account, logged out); changing a vote; player not in the match; after `closes_at`.
- **Close:** lazy close on read; End now; Cancel; tally, tie and no-vote results.
- **Confirm:** `poll_id` checks; poll `confirmed`; drop once; override audit; the open and result chat texts within 280 characters with safe names; PubSub payloads without voter ids.
- **Retention:** cleanup after 30 days; Leave deletes votes.
- **Extension:** source checks for the new views, and the review disclosure naming both chat messages.

## Verification
- **Hosted Test on an approved channel:**
  1. Open a vote on a live match.
  2. Vote from two viewer accounts, one of them changing its vote.
  3. Check that a new soft account sees "Your vote counts from…".
  4. Let the timer run out, confirm the winner, and check the chat lines, the MVP on the Schedule tab and one drop.
- **Several matches in a night:** open a poll for game 2 while game 1 has its MVP. Game 2's MVP is set, and game 1 is untouched.
- **Edge cases:** cancel mid-poll; a tie; no votes; a second poll while one is open; End now; a panel opened mid-poll.
- **Before release:** a security change review (new endpoints, viewer input); review notes for 1.4.0 list both chat messages.
