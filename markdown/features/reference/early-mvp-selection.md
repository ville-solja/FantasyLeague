# Early MVP Selection

Lets a streamer confirm a match MVP in the Twitch extension as soon as the game ends, instead of waiting 5–10 minutes for OpenDota to publish the finished match. Resolves issue #139.

---

## How it works

1. A live check stores the games of monitored leagues in `live_matches`, with both teams and all ten players. Since issue #161 the live source is Steam's `IDOTA2Match_570/GetLiveLeagueGames`, checked by its own thread, `_live_poll_loop`, every `LIVE_POLL_INTERVAL` seconds (see [MVP Selection Delays](mvp-selection-delays.md)). Originally every ingest poll called OpenDota's `/live`, which turned out not to list Kanaliiga's amateur games.
2. `GET /twitch/matches/current` lists a stored live match with no ingested stats as **provisional**: `"provisional": true`, `"live"` while the game is in the live list, and players with `fantasy_points: 0`.
3. `POST /twitch/mvp` on a provisional match stores the MVP, drops tokens and posts to chat as usual. The player must be one of the match's live players. No bonus is applied yet.
4. When ingest fetches the finished match, `_reapply_mvp_bonus` applies the bonus to the chosen player and the `live_matches` row is deleted.
5. For a while after a game ends, the poll loop keeps the fast live interval so the real stats arrive sooner.

A stored live match that is never ingested, such as a game shorter than 15 minutes, is deleted 24 hours after it was last seen. An MVP row already confirmed for it stays but has no effect.

## Steam `GetLiveLeagueGames` fields used

`steam_live.get_live_league_games()` normalises each game to the entry keys `store_live_matches()` reads:

| Steam field | Entry key | Notes |
|---|---|---|
| `match_id` | `match_id` | Cast to int; a game without one is dropped |
| `league_id` | `league_id` | Only games of monitored leagues are kept (filtered locally) |
| `radiant_team.team_id`, `dire_team.team_id` | `team_id_radiant`, `team_id_dire` | `0` or missing becomes `None`, stored as `NULL` |
| `radiant_team.team_name`, `dire_team.team_name` | `team_name_radiant`, `team_name_dire` | `""` or missing becomes `None`, stored as `NULL` |
| `players[].account_id` | `players[].account_id` | Players without one are skipped |
| `players[].team` | `players[].team` | `0` radiant, `1` dire (stored as `side`); `2` or more are casters and spectators, skipped |
| `players[].name` | `players[].name` | Stored when present |

The shape comes from Steam's documentation and is **not yet checked against a real response**: `backend/tests/fixtures/steam_live_league_games.json` is a stand-in. See [MVP Selection Delays](mvp-selection-delays.md#manual-follow-up).

Before #161 the entries were OpenDota `/live` games (checked against a real response on 2026-09-30), which use the same keys, with `match_id` as a string; `store_live_matches()` still accepts both.

## Storage — `live_matches`

The Schedule tab also reads this table to mark a series as live (`get_live_pairs` in `backend/schedule.py`); see [Schedule Visuals](schedule-visuals.md).

New table (model `LiveMatch`, created by `create_all`, no migration):

| Column | Meaning |
|---|---|
| `match_id` | Primary key |
| `league_id` | Monitored league |
| `radiant_team_id`, `dire_team_id`, `radiant_name`, `dire_name` | Nullable; missing values are `NULL` |
| `players_json` | `[{"account_id", "name", "side": "radiant"\|"dire"}]` |
| `first_seen_at`, `last_seen_at` | Unix times of the first and latest live check that saw the game |
| `ended_at` | Set by the first successful live check that no longer sees the game; cleared if it reappears |

`backend/ingest.py`:
- `store_live_matches(entries, monitored_league_ids, db=None, now=None)` upserts the monitored-league entries, sets `ended_at` on rows no longer present, and deletes rows whose match has `player_match_stats` rows or whose `last_seen_at` is over 24 hours old. It also records `match_timings.live_first_seen_at` on first sight. The live thread (`main._live_poll_once`) calls it once per successful Steam check, only when a league is monitored; a failed check does not call it, so no row is marked ended.
- `ingest_match()` deletes the match's `live_matches` row once its stats are written, and records `match_timings.ingested_at`.
- `get_live_matches()` (the OpenDota `/live` call) was removed in #161.
- `_reapply_mvp_bonus()` logs a warning naming the match and player when the confirmed MVP has no stats row in the ingested match.

Live players are **not** added to `players`; ingest stays that table's only writer.

## Endpoints

### `GET /twitch/matches/current`
Every match now carries `provisional` and `live`. Since #161 the response also has `live_checked_at` and `live_source_configured` next to `series` (see [MVP Selection Delays](mvp-selection-delays.md)). Ingested matches are listed as before with `"provisional": false, "live": false`; a match with stats is never listed twice.

`twitch._current_series()` adds each stored live match without stats as a stand-in with `start_time = first_seen_at`, in the series of its team pair. When both team ids are missing, it is grouped by its team names instead. The 5-series window applies as before. For a provisional match:
- `players` come from `players_json`: `player_id` is the account id, `player_name` the display name, `team_name` the stored name for that side (else the `teams` name, else `Team {id}` when only the id is known, else `Radiant`/`Dire`; `""` for a player with no side), `fantasy_points` `0`.
- A series grouped by team names shows `TBD` for a side whose name is empty.
- Provisional matches are listed from the moment they are first seen live; they are not filtered by `start_time`.
- Series header names fall back to the stored live names when a team is not in `teams`.
- `mvp_player_name` is the display name of the confirmed MVP.

**Display name:** the known `players.name`, else the live `name`, else `Player {account_id}`.

### `POST /twitch/mvp`
Check order is unchanged: channel allowlist (403), existence (404 `Match not found`; an ingested match or a `live_matches` row), series window (403), player (404).

A match is provisional when it has a `live_matches` row and no stats rows. Then:
- the player must be in its `players_json`, otherwise 404 `Player did not play in this match` (the `players` table is not consulted);
- no bonus is applied (`_apply_mvp_bonus` is skipped), for the new or a replaced MVP;
- the chat message, PubSub message, response and audit detail use the display name;
- the `twitch_mvp_set` audit detail ends with `provisional=True`.

The token drop and re-select behaviour are the same as for an ingested match: one drop per channel and match.

## Poll interval after a game

`_ingest_poll_loop` makes no live calls. A league counts as live when it has a `live_matches` row with `ended_at IS NULL` seen in the last 15 minutes (`main._live_league_ids`), so a stored game stops counting as live if the live thread can't see it for a while. `main._has_recently_ended_live_match(monitored)` is true when a `live_matches` row of a monitored league has `ended_at` within the last `INGEST_POST_MATCH_FAST_POLL_MINUTES` and no stats rows. `_ingest_poll_loop` then uses `INGEST_LIVE_MATCH_POLL_INTERVAL`, as it does while a game is live. Otherwise the active-week and default intervals apply unchanged.

## Extension

`twitch-extension/live_config.js` (released as extension version 1.1.7):
- A provisional match row shows **Live** while `live` is true, otherwise **Stats pending**.
- Player tiles of a provisional match show the team name without points.
- After confirming on a provisional match, the banner adds "Fantasy bonus is applied when the stats arrive".
- The empty state reads "No recent matches found. A match appears here as soon as it goes live."
- Every name still goes through `_escHtml`.

Version 1.1.6 keeps working against the new backend: it ignores the new fields and shows provisional players as "0 pts".

## Configuration

| Variable | Default | Description |
|---|---|---|
| `STEAM_API_KEY` | *(empty)* | Steam Web API key for live-game detection. Unset: no live checks run, so matches appear only after ingest |
| `LIVE_POLL_INTERVAL` | `60` | Seconds between live checks |
| `INGEST_POST_MATCH_FAST_POLL_MINUTES` | `20` | Minutes after a monitored game ends during which the poll loop keeps `INGEST_LIVE_MATCH_POLL_INTERVAL`, until the match is ingested. `0` disables |

## Tests

`backend/tests/test_issue_139_early_mvp_selection.py`; the Steam source and live thread in `backend/tests/test_issue_161_mvp_selection_delays.py`.
