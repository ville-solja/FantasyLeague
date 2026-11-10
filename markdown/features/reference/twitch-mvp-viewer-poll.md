# MVP Poll for Watchers

Lets a broadcaster hand the match MVP choice to the viewers: the streamer opens a timed vote for one match from Quick Actions, joined viewers vote in the panel, and the streamer confirms the winner. Issue #234, milestone S17: the backend is in place, and the extension changes ship as version 1.4.0 after 1.3.0 passes review. Plan: `markdown/plans/plan-issue-234-mvp-poll-for-watchers.md`.

---

## Flow

1. **Start:** in the MVP tool (`live_config.html`), the streamer picks a series and a match as before. The match view has two buttons: **Pick MVP** (the player grid, unchanged) and **Start viewer vote**, which shows the vote length (1, 2 or 3 minutes, 2 by default) and **Open vote**. The vote is tied to that match, with stats or live (its live players). One poll can be open per channel.
2. **Announce:** one chat message names the teams, the game number and the time left. A PubSub message makes every open panel load the poll at the top of its Live tab.
3. **Vote:** joined viewers who are eligible for drops pick one of the match's players and press **Vote**. They can change their vote (**Change vote**) until the poll closes. While it's open, everyone sees only the total number of votes.
4. **Close:** the poll closes when its timer ends, or when the streamer presses **End now**. **Cancel vote** ends it with no result and no MVP.
5. **Confirm:** the tool shows each player's votes and share with the sole winner selected. A tie selects no one and marks the tied players; the streamer picks one. With no votes the tool says so and opens Pick MVP (on the same match when it is still selected, otherwise the series list). **Confirm MVP & Drop Tokens** calls `POST /twitch/mvp` with `poll_id`, so the MVP row, fantasy bonus, token drop, PubSub message and audit work exactly as for a picked MVP. The chat says the MVP came from the viewers' vote unless the streamer confirmed someone else.

A chat command (`!mvp`) isn't possible: an extension can post to chat but can't read it. Twitch's own Polls allow at most 5 choices and need the broadcaster's OAuth token.

## Who can vote

The same rules as the token drop (`twitch.py`):

| Viewer | Panel shows | Vote |
|---|---|---|
| Logged out of Twitch (`A…` opaque id) | "Log in to Twitch to vote." | `403 twitch_login_required` |
| Logged in, not joined | "Join to vote." (the Join box is above) | `403 not_joined` |
| Soft account younger than `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` | "Your vote counts from <date>." (`voter.votes_from`, from `drops_from`) | `403 too_new` |
| Joined and old enough, or a recognised website account | The player buttons and **Vote** | Recorded |

The viewer doesn't need to be in the presence pool to vote; the pool matters only for the drop on confirmation.

## Endpoints

All in `backend/twitch_mvp_poll.py` (its own router under `/twitch`, mounted in `main.py` before the `/twitch/{rest:path}` catch-all), authenticated with the extension JWT (`twitch.verify_twitch_jwt`). Each route is a plain function plus a rate-limited `*_route` wrapper.

### `POST /twitch/mvp-poll` *(broadcaster only)*
Body `{match_id, duration_seconds}` (`duration_seconds` defaults to 120). Checks run before anything is written, in this order:

| Case | Status |
|---|---|
| Caller isn't the broadcaster | `403` |
| `duration_seconds` not 60, 120 or 180 | `422` |
| Channel not approved (`mvp_channel_allowed`); an approval request is recorded as for MVPs | `403` |
| Unknown match | `404` |
| Match outside the series window (`_eligible_mvp_match_ids`) | `403` |
| A poll for this match was already confirmed, on any channel (a match has one MVP) | `409` |
| Another poll is open on the channel (also enforced by a partial unique index) | `409` |
| The match has no players yet | `409` |

On success it stores the poll (with the teams, game number and players as `GET /twitch/matches/current` lists them, in `info_json`), audits `twitch_mvp_poll_opened`, sends PubSub `{"type": "mvp_poll", "state": "open", "poll_id": N}` and posts the open chat line. Returns the poll view (below). Limited by `RATE_LIMIT_TWITCH_JOIN_IP`, like `POST /twitch/mvp`.

### `GET /twitch/mvp-poll` *(any viewer)*
`{"poll": <view>}` for the channel's latest poll when it is open, or closed or confirmed less than 30 minutes ago (`RESULT_SHOWN_SECONDS`); `{"poll": null}` otherwise. Only the latest poll counts: once it is cancelled the answer is `{"poll": null}`, even if an earlier poll closed within the 30 minutes. The view has:

- `poll_id`, `match_id`, `status`, `opened_at`, `closes_at`, `closed_at`, `now` (server time, for the countdown), `seconds_left`;
- `team1_name`, `team2_name`, `match_number`, and `teams: [{team_name, players: [{player_id, player_name, chat_name}]}]`;
- `total_votes` and `confirmed_player_id`;
- once closed only: `results` (`player_id`, `player_name`, `chat_name`, `votes`, `pct`, most votes first), `winner_player_id` (the sole leader, else null) and `tied_player_ids`;
- the caller's own `my_vote` and `voter: {can_vote, reason, votes_from}` (`reason` is `ok`, `login`, `join` or `too_new`).

No other viewer's id or individual vote is ever in a response. Limited like `GET /twitch/panel` (per viewer and per IP).

### `POST /twitch/mvp-poll/{poll_id}/vote` *(joined viewer, eligible for drops)*
Body `{player_id}`. Checks in this order: a logged-out viewer gets `403 twitch_login_required` before the poll is looked up; then `404` for an unknown poll or one on another channel; then `403 not_joined` or `403 too_new` as in the table above; `409 poll_closed` once the poll is closed or cancelled (a poll past `closes_at` is closed by this call), `422` for a player not in the match. An upsert on (`poll_id`, `twitch_user_id`) keeps one vote per viewer. Before the upsert, the vote claims the poll row with a conditional `UPDATE … WHERE status = 'open' AND closes_at > now` in the same transaction; a close that got there first makes it `409 poll_closed`, so no vote is stored after the tally is counted. Returns `{poll_id, my_vote, total_votes}`. Limited per viewer (`RATE_LIMIT_TWITCH_ACTION`) and per IP (`RATE_LIMIT_TWITCH_JOIN_IP`), like the draws.

### `POST /twitch/mvp-poll/{poll_id}/end` *(broadcaster only)*
Closes an open poll now and returns its view with the result. `409` when it is not open (already closed by its timer, cancelled or confirmed).

### `POST /twitch/mvp-poll/{poll_id}/cancel` *(broadcaster only)*
Ends an open, or closed but unconfirmed, poll with no result: status `cancelled`, audit `twitch_mvp_poll_cancelled`, PubSub `state: "cancelled"`. No MVP, bonus, drop or chat. `409` for a poll already cancelled or confirmed.

### `POST /twitch/mvp` *(existing, gains `poll_id`)*
`MVPBody.poll_id` is optional (bounded to a database id). With it, after the existing channel, match and player checks and before any write, `twitch_mvp_poll.confirmable_poll` requires the poll to be on the caller's channel (`404`), for the same match (`409`) and closed (`409` when open, cancelled or already confirmed). Then, still before the MVP, bonus or drop is written, `mark_confirmed` claims the poll with a conditional `UPDATE … WHERE status = 'closed'` that sets it `confirmed` with the chosen player; if a concurrent cancel or confirm got there first, the transaction rolls back and the answer is `409`, so nothing is written. The audit `twitch_mvp_set` gains `poll=N`, plus `override=True` when the player isn't the vote's sole winner (a tie counts as an override). Without `poll_id` nothing changes. See [Twitch Extension](../core/twitch-extension.md).

## Closing without a background job

A poll's state is worked out when it's read: every `GET`, vote, End now, open on the same channel, confirm and the daily cleanup closes a poll whose `closes_at` has passed. Closing is a conditional `UPDATE … WHERE status = 'open'`, so only the request that flips it counts the votes (after the flip, inside the same transaction) and writes `tally_json` (`{"<player_id>": votes}`), audits `twitch_mvp_poll_closed` (`votes=`, `winner=`, `tie=`, never voter ids) and sends PubSub `state: "closed"`. The panel and the tool read the poll again when their countdown reaches zero, which closes it and tells every other panel.

## Chat

Both lines carry counts only and are capped at 280 characters. Player names come from `chat_safe_name`; team names are cleaned the same way and become `TBD` when they look like a link.

| When | Message |
|---|---|
| Poll opened | `MVP vote open for Team A vs Team B, game 1: vote in the Kana Cards panel. Closes in 2 min.` (`twitch_mvp_poll.open_chat_text`) |
| Confirmed, the vote's sole winner | `Match MVP by viewer vote: PlayerName (60% of 5 votes)!` followed by the usual drop sentence (`twitch._mvp_chat_text(..., vote=(pct, total))`) |
| Confirmed, another player | The usual `Match MVP: PlayerName!` message |

Both are disclosed in [Twitch Extension Review Submission](twitch-extension-review-submission.md#from-version-140-mvp-viewer-vote).

## Data

New tables, created by `create_all` (no migration):

- **`twitch_mvp_polls`** (`TwitchMvpPoll`): `channel_id`, `match_id` (no foreign key: a live match has no `matches` row yet), `status` (`open`, `closed`, `cancelled`, `confirmed`), `opened_at`, `closes_at`, `closed_at`, `confirmed_player_id`, `tally_json` (written on close) and `info_json` (teams, game number and players at open). The partial unique index `ux_twitch_mvp_polls_open_channel` allows one open poll per channel.
- **`twitch_mvp_votes`** (`TwitchMvpVote`): `poll_id`, `twitch_user_id` (the voter's opaque id), `player_id`, `voted_at`; unique on (`poll_id`, `twitch_user_id`).

Retention:

- Only a poll that closed (by its timer or End now) keeps per-player counts in `tally_json`. A poll cancelled while open keeps no tally, and its votes go with the same 30-day cleanup.
- `cleanup_votes` deletes the votes of polls that ended more than 30 days ago (`VOTE_RETENTION_DAYS`). `main._week_maintenance_loop` runs it once a day through `_run_mvp_vote_cleanup`, which logs and rolls back on failure. The poll keeps its tally.
- Leave Kana Cards deletes the caller's votes: `soft_accounts.delete_soft_account` for a soft account (also used by the idle-account purge) and `twitch.leave` for a website account that unlinks.
- The privacy page describes votes and their retention.

## Extension

- **`live_config.html`, `live_config.js`:** the match view's **Pick MVP** / **Start viewer vote** buttons, the vote length select and **Open vote**; step 4, the vote view: countdown from `closes_at` (corrected by the server's `now`), the vote count refreshed every 5 s (`POLL_REFRESH_MS`), **End now** and **Cancel vote**; then the result view (`pollResultState`: winner, tie or none) with a chat preview and **Confirm MVP & Drop Tokens**. A vote left with **Back**, or still open after a reload, comes back when the streamer opens the tool.
- **`panel.html`, `panel.js`, `extension.css`:** the `#live-poll` card at the top of the Live tab, loaded on start, on PubSub `mvp_poll` and `mvp`, and every 15 s while a vote is open. Untrusted names go through `_escHtml`. The viewer-file policy checks in `package.sh` apply.

## Tests

`backend/tests/test_issue_234_mvp_poll_for_watchers.py`: open, vote, close, confirm and retention rules, the chat lines, PubSub payloads without voter ids, the rate limit, the extension source and the review documents.
