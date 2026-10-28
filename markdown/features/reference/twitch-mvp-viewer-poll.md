# MVP Poll for Watchers

Lets a broadcaster hand the match MVP choice to the viewers: the streamer opens a timed vote for one match from Quick Actions, joined viewers vote in the panel, and the streamer confirms the winner. Planned for S17 (issue #234). Plan: `markdown/plans/plan-issue-234-mvp-poll-for-watchers.md`.

---

## Flow

1. **Start:** in the MVP tool, the streamer picks a series and a match as today, then presses **Start viewer vote** (1, 2 or 3 minutes) instead of **Pick MVP**. The vote is tied to that match. One poll can be open per channel.
2. **Announce:** one chat message names the teams, the game and the time left. A PubSub message shows the poll on every open panel's Live tab.
3. **Vote:** joined viewers who are eligible for drops pick one of the 10 players. They can change their vote until the poll closes. While it's open, only the total number of votes is shown.
4. **Close:** the poll closes when its timer ends, or when the streamer presses **End now**. **Cancel** ends it without a result.
5. **Confirm:** the tool shows the result with the winner preselected. A tie lists the tied players, and with no votes the streamer picks instead. **Confirm MVP & Drop Tokens** sets the MVP through the existing `POST /twitch/mvp` (with `poll_id`), so the fantasy bonus, the token drop and the PubSub message work as for a picked MVP. The chat says the MVP came from the viewers' vote, unless the streamer confirmed someone else.

A chat command (`!mvp`) isn't possible: an extension can post to chat but can't read it. Twitch's own Polls are limited to 5 choices.

## Endpoints

### `POST /twitch/mvp-poll` *(planned)*
Broadcaster on an approved channel: `{match_id, duration_seconds}`. Refused for a match outside the series window, a second open poll on the channel, or a match whose poll was confirmed.

### `GET /twitch/mvp-poll` *(planned)*
Any viewer: the channel's open poll (or the last closed one), with the players, the time left, the vote count, the caller's own vote, and the per-player results once it's closed.

### `POST /twitch/mvp-poll/{id}/vote` *(planned)*
Joined viewer eligible for drops: `{player_id}`. Changes the caller's vote while the poll is open.

### `POST /twitch/mvp-poll/{id}/end`, `POST /twitch/mvp-poll/{id}/cancel` *(planned)*
Broadcaster: close the poll now with its tally, or end it with no result.

### `POST /twitch/mvp` *(existing, gains `poll_id`)*
Confirms a closed poll's result; see [Twitch Extension](../core/twitch-extension.md).

## Data

- **`twitch_mvp_polls`:** channel, match, status (`open`, `closed`, `cancelled`, `confirmed`), opened, closes and closed times, the per-player tally and the confirmed player.
- **`twitch_mvp_votes`:** poll, the voter's opaque Twitch id, the player and the time; one row per poll and voter.
- **Retention:** votes are deleted 30 days after their poll ends, and on Leave Kana Cards.
- **Chat:** the chat messages carry counts only, never voter names.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
