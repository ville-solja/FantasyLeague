# Schedule Player Performance

Each game in an unfolded Schedule series can open a table of its players with their raw points, the game's fantasy score from each player's own stats before card rarity, card modifiers and the MVP bonus. For fantasy players judging who performed well. Issue #244. Plan: `markdown/plans/plan-issue-244-schedule-player-performance.md`.

---

## Player table

- **Where:** `frontend/app-players.js`. `gameRowsHtml` (inside `loadSchedule`) adds a **Players** button (`.game-players-btn`, `aria-expanded`, `aria-controls="game-players-<match id>"`) to each game row's meta cell, after the duration and before the OpenDota link. `toggleSchedulePlayers(matchId)` opens or closes the table and fetches it once per match; `_schedPlayersHtml(mid, data)` renders it as a sibling after the game row (`.game-players`), never inside `.game-row`.
- **State:** `_schedPlayersOpen` (Set of open match ids) and `_schedPlayersData` (Map of match id to the response, `"loading"` or `"error"`) are module state, so every re-render (quiet refresh, any handler) keeps an open table. A failed load shows a retry message and is fetched again on the next press.
- **Hidden results:** `_schedPlayersShown` is rebuilt on each render from the games of shown, unfolded series; `toggleSchedulePlayers` ignores any other match id, so a hidden result (which renders through `hiddenRow`, with no game rows) never fetches player data. `hideScheduleWeekAgain` removes that week's match ids (a played series' key is its match ids) from the open set, so a later Reveal does not reopen them.
- **Columns:** player (`playerLink`, opens the player popup; the MVP has a ★), hero icon, K/D/A, raw points to one decimal. Players are grouped under their team names, radiant then dire, each team sorted by raw points. The top raw score (all ties) is bold amber (`.mark-winner`) with a visually hidden "(top performer)" label. A note reads "Raw points: from the player's own stats, before card rarity, modifiers and the MVP bonus."
- **Badges:** "Not scored" (`_NOT_SCORED_TOOLTIP`) for an excluded game and "Partial stats" (`_PARTIAL_STATS_TOOLTIP`) for an unparsed or unparseable one. The Partial stats tooltip and `_popupIsPartial` moved from `app-player-popup.js` to `app-players.js`, next to `_NOT_SCORED_TOOLTIP`, so the Schedule and the player popup share them.
- **No stats:** a game with no stored player rows reads "No player stats for this game yet."
- **Styles:** `frontend/style.css`, after the game-row rules. The table is `width: 100%`; below 480 px (`@media (max-width: 479px)`) the hero column is hidden.

## Raw points

`schedule.game_players(db, match_id)` computes `scoring.fantasy_score(stat_dict_from_row(row), weights)` for each `player_match_stats` row, with the weights read from the `weights` table, and rounds it once with `display_points`. It never reads `fantasy_points`, which includes the MVP bonus. This is the Weekly Report's RAW chip. An unparsed replay's missing stats are stored as 0 and count as 0, as in the player popup. Hero icons come from `schedule.cached_hero_maps()`, which never fetches: on a cold cache `hero_icon` is null and the background warm-up starts.

## Endpoints

### `GET /matches/{match_id}/players`
Public, in `backend/routers/players.py`. `match_id` is bounded with `Path(ge=1, le=2**63 - 1)`, so an id outside that range answers 422. 404 `"Match not found"` for an unknown match.

Response: `match_id`, `parse_status` (`parsed`, `unparsed`, `unparseable` or null), `excluded_from_scoring`, and `teams`. Each team has `team_id`, `team_name` and `players`; each player has `player_id`, `player_name`, `hero_id`, `hero_icon`, `kills`, `deaths`, `assists`, `raw_points`, `is_mvp` and `top`. A match with no stored stats still lists its two teams (radiant, then dire) with empty `players`; a manual match without radiant or dire ids lists its teams in the order they appear in its stats. A stats row with no team gives a team entry with `team_id` and `team_name` null, shown as "Unknown team"; a player with no ingested name has `player_name` null, shown as "—". No user, card or ownership data.

## Cache

`schedule._game_players_cache` keeps one response per match, stored with the time it was built. An entry expires after `schedule.CACHE_TTL` (an hour, the schedule cache's own lifetime), so a game first opened while its replay was unparsed, or a match deleted by a season reset, is served stale for at most an hour: league ingest (`ingest_league` and the background poll), parse retries in `main.py`, profile enrichment and the season reset don't call `bust_cache()`. `schedule.bust_cache()` empties it at once; the manual-match store in `ingest.py`, `POST /schedule/refresh`, the Twitch MVP confirm and the admin MVP, retry-parse and scoring-toggle routes call it. The key holds no weights fingerprint: weights change only at startup (`seed.py` applies `WEIGHTS_JSON`; there is no weights write route), and a restart empties the cache. `POST /recalculate` does not call `bust_cache()`, which is safe for the same reason. A response built on a cold hero cache is not stored, so icons appear once the cache warms. Only stored matches are cached, so the cache is bounded by the number of league matches.

