# Plan: Early MVP Selection

## Context
Streamers report waiting 5–10 minutes after a game ends before they can pick its MVP in the Twitch extension. `GET /twitch/matches/current` only lists matches that have `player_match_stats` rows, and those exist only after `ingest_league` fetches the finished match from OpenDota. That wait has three parts:
- OpenDota adds the match to `/leagues/{id}/matchIds` some minutes after it ends.
- Once the game ends, the league drops off OpenDota's `/live` list, so polling slows from `INGEST_LIVE_MATCH_POLL_INTERVAL` (30 s) back to `INGEST_LIVE_POLL_INTERVAL` (120 s).
- The streamer has to reopen the panel after the next ingest.

The poll loop already calls OpenDota's `/live` every cycle, but keeps only the league ids (`get_live_match_league_ids`). That response also carries each live game's `match_id`, both teams and all ten players' account ids. This plan stores it, so a match appears in the MVP panel as soon as it is seen live. The streamer can confirm the MVP right after the game. The fantasy bonus is applied when the full match is ingested, which `ingest.py` already does through `_reapply_mvp_bonus`.

**Assumptions:**
- A match counts as started once it appears in OpenDota's `/live` for a monitored league. The schedule sheet is not used, because it has no match id.
- The `/live` shape was checked against a real response on 2026-09-30:
  - The top-level fields include `match_id` **(a string)**, `league_id`, `team_id_radiant`, `team_id_dire`, `team_name_radiant`, `team_name_dire`, `activate_time`, `deactivate_time`, `game_time` and `players[]`.
  - Each player has `account_id`, `hero_id`, `team` (0 radiant, 1 dire) and `team_slot`. **There is usually no `name`.**
  - A missing team comes as `0` or `""`.
- The implementation therefore:
  - casts `match_id` to int,
  - treats team id `0` and name `""` as missing,
  - takes a player's display name from the `players` table when the account is known, then from `name` if the live entry has one, and otherwise shows `Player {account_id}`.
- The MVP can be confirmed while the game is still live. The panel marks it "Live" so the streamer knows. The token drop fires on confirm, as today.
- `TwitchMVP.match_id` has a foreign key to `matches`, but SQLite doesn't enforce it here (no `PRAGMA foreign_keys=ON`). An MVP row for a match that is not ingested yet is therefore allowed, and `_reapply_mvp_bonus` already handles the order.
- Live players are not added to the `players` table. That table is the card pool, and ingest stays its only writer.
- Twitch reviews extension files, so the panel changes ship as a new extension version. The backend stays compatible with the current version (1.1.6): provisional players are sent with `fantasy_points: 0`, which it shows as "0 pts".

Resolves GitHub issue #139.

## User Stories

### Pick the MVP Right After the Game
**User story**
As a streamer, I want a match to appear in the MVP panel as soon as it starts so that I can confirm the MVP the moment the game ends, while viewers are still watching.

**Acceptance criteria**
- The ingest poll stores every `/live` game of a monitored league in a `live_matches` table: match id, league id, both team ids and names, the ten players (account id, name if given, side), and first and last seen times
- `GET /twitch/matches/current` includes a stored live match that has no ingested stats yet, in the series of its team pair, within the existing 5-series window
- Such a match has `"provisional": true`, `"live": true` while it is still in `/live` and `false` after, and a `players` list built from the stored players with `fantasy_points: 0`
- A match with ingested stats is listed exactly as today with `"provisional": false`, and is never listed twice
- A live match whose team ids are missing is still listed, grouped under its team names

### Confirm an MVP Before Stats Exist
**User story**
As a streamer, I want confirming an MVP on a provisional match to work like any other confirmation so that the chat message and token drop happen immediately.

**Acceptance criteria**
- `POST /twitch/mvp` accepts a provisional match id in the series window, when the player is one of that match's stored live players
- It stores the MVP row, runs the token drop, posts the chat message using the player's display name (known `players` name, else live `name`, else `Player {account_id}`), and writes the `twitch_mvp_set` audit entry with `provisional=True` in the detail
- No fantasy bonus is applied at confirm time, because there is no stats row yet
- A player not among the match's stored live players gets 404 "Player did not play in this match"
- The channel allowlist and series-window checks run first and behave as today
- Changing the MVP on a provisional match updates the row and does not drop tokens again

### Bonus Applied When Stats Arrive
**User story**
As a player owner, I want an MVP picked early to get the same fantasy bonus as one picked after ingest so that early selection changes nothing about scoring.

**Acceptance criteria**
- When the match is ingested, `_reapply_mvp_bonus` sets `is_mvp` and the bonus on the chosen player's stats row, as for any MVP
- If the chosen player has no stats row in the ingested match, a warning is logged naming the match and player, and nothing else changes
- Once a match has stats rows, its `live_matches` row is deleted
- A stored live match that has not been ingested 24 hours after it was last seen (for example because ingest skipped a game shorter than 15 minutes) is deleted and no longer listed. An MVP row already confirmed for it stays but has no effect

### Faster Ingest Right After a Game Ends
**User story**
As a streamer, I want the final stats to arrive soon after the game so that the panel shows real points shortly after I pick.

**Acceptance criteria**
- While any stored live match of a monitored league has ended but has no ingested stats, the poll loop keeps using `INGEST_LIVE_MATCH_POLL_INTERVAL`
- This faster polling stops after `INGEST_POST_MATCH_FAST_POLL_MINUTES` (default 20) from the end of the match, even if the match is still not ingested
- With no live or recently ended matches, intervals are unchanged

### Panel Shows Which Matches Are Provisional *(extension release)*
**User story**
As a streamer, I want the panel to show when a match is live or waiting for stats so that I know the points are not final.

**Acceptance criteria**
- A provisional match row shows "Live" while `live` is true, otherwise "Stats pending"
- Player tiles of a provisional match show the team name without a points value
- After confirming on a provisional match, the confirmation says the bonus is applied when the stats arrive
- The empty-state text no longer says to wait for the next ingest cycle
- `live_config.js` passes the extension package self-check (`twitch-extension/package.sh`) and is released as a new extension version

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New `LiveMatch` table (`live_matches`); new table, so `create_all` handles it and no migration is needed |
| `backend/ingest.py` | `get_live_matches()` returns the raw `/live` entries (`store_live_matches()` filters to monitored leagues); `store_live_matches()` upserts and marks ended; cleanup after ingest; warning in `_reapply_mvp_bonus` when the MVP has no stats row |
| `backend/main.py` | Poll loop stores live matches and uses the fast interval after a game ends; `INGEST_POST_MATCH_FAST_POLL_MINUTES` |
| `backend/twitch.py` | `_current_series` and `current_matches` merge provisional matches; `set_mvp` validates provisional players and skips the bonus |
| `twitch-extension/live_config.js` | Provisional and live labels, no points on provisional tiles, updated copy |
| `.env.example` | `INGEST_POST_MATCH_FAST_POLL_MINUTES` |
| `markdown/features/reference/twitch-mvp-series-window.md`, `markdown/features/core/twitch-extension.md` | Response shape and flow |
| `backend/tests/test_issue_139_early_mvp_selection.py` | Tests |

### Step 1 — `/live` shape (done)
The shape was confirmed on 2026-09-30; see Context. Use a fixture in the tests with a string `match_id`, players without `name`, and one entry with team id `0`. Record the field list in the feature doc.

### Step 2 — Store live matches
```python
class LiveMatch(Base):
    __tablename__ = "live_matches"
    match_id        = Column(Integer, primary_key=True)
    league_id       = Column(Integer)
    radiant_team_id = Column(Integer, nullable=True)
    dire_team_id    = Column(Integer, nullable=True)
    radiant_name    = Column(String, nullable=True)
    dire_name       = Column(String, nullable=True)
    players_json    = Column(Text)             # [{"account_id", "name", "side": "radiant"|"dire"}]
    first_seen_at   = Column(Integer)
    last_seen_at    = Column(Integer)
    ended_at        = Column(Integer, nullable=True)  # set when a poll no longer sees it
```
Replace `get_live_match_league_ids()` with `get_live_matches()`, which returns the raw entries. The poll loop derives the league-id set from them as before and calls `store_live_matches(entries, monitored)`. That function:
- upserts the entries of monitored leagues,
- sets `ended_at` on rows no longer present,
- deletes rows whose match now has stats, or that were last seen more than 24 hours ago.

Skip players without an `account_id`. Update the tests that patch `get_live_match_league_ids`.

### Step 3 — List provisional matches
In `_current_series`, after collecting ingested matches, add `LiveMatch` rows with no stats as lightweight objects: `match_id`, team ids, and `start_time = first_seen_at`, plus a `provisional` flag. Group them into the same series by team pair, keyed by names when both ids are missing, and keep the 5-series cut. In `current_matches`, build `players` for provisional matches from `players_json`. Take `team_name` from the stored name for that side, set `fantasy_points` to 0, and add `provisional` and `live`. Team names for the series header fall back to the stored names when the team is not in `teams`.

### Step 4 — Confirm on provisional matches
In `set_mvp`, replace the `db.get(Match, ...)` 404 check with "the id is an ingested match or a stored live match". Then:
- **Ingested matches:** keep the existing `PlayerMatchStats` and `Player` checks.
- **Provisional matches:**
  - Require the player's account id to be in `players_json`, otherwise 404 "Player did not play in this match".
  - Use the display name (known `players` name, else live `name`, else `Player {account_id}`) for the chat message, the PubSub message and the response.
  - Skip `_apply_mvp_bonus`, and add `provisional=True` to the audit detail.

Keep the check order: allowlist, then existence, then window, then player.

### Step 5 — Poll interval after a game
In `_ingest_poll_loop`, when no league is live, check for `LiveMatch` rows with `ended_at` inside the last `INGEST_POST_MATCH_FAST_POLL_MINUTES` minutes and no stats. If there are any, use `_INGEST_LIVE_MATCH_POLL_INTERVAL`.

### Step 6 — Extension
Update `live_config.js` as in the last story. Every name goes through `_escHtml`, as it does now. Bump the extension version, run `package.sh`, and note the change in the review change log.

### Step 7 — Docs and tests
Update the two feature docs, `.env.example`, and the tripwire in `test_issue_85_split_admin_router.py`.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_139_early_mvp_selection.py -v`, then the full suite.
- A seeded `LiveMatch` with no stats appears in `GET /twitch/matches/current` with `provisional: true`, grouped with an ingested game of the same team pair.
- Confirming the MVP on it returns 200, drops tokens once, posts chat with the display name and applies no bonus. A player outside its stored players gets 404.
- Ingesting the match (mocked OpenDota payload) applies the bonus to the chosen player, deletes the `LiveMatch` row, and lists the match once with real points.
- A `LiveMatch` last seen more than 24 hours ago is deleted, and one whose chosen MVP has no stats row logs a warning.
- The poll loop picks the 30 s interval for 20 minutes after a game ends, then falls back.
- Extension 1.1.6 still renders the list (manual, Hosted Test). The new version shows the Live and Stats pending labels.
- Manual, on test.kana-cards.com during a league game: the match appears in the panel within one poll of starting, and the MVP can be confirmed right after the game ends.
