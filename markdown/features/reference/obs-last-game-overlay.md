# OBS Last Game Overlay

A page a streamer adds to OBS as a Browser Source for the pause screen between games: the last finished game of the series being streamed, with the series score and each player's raw points, hero and K/D/A. No login and no Twitch extension needed. Issue #246. Plan: `markdown/plans/plan-issue-246-obs-last-game-overlay.md`.

---

## Overlay page

`frontend/obs/last-game.html`, `last-game.js` and `last-game.css`, served by the `/` static mount (`Cache-Control: no-cache`, the usual security headers; the CSP has only `frame-ancestors`, which doesn't apply to a top-level OBS page). The page loads `/colors_and_type.css` for the site's tokens and font, its own stylesheet and its own script; no app modules, no Alpine, no tour, no login. It has its own HTML escaper.

- **URL:** `/obs/last-game.html?teams=<team id>,<team id>`, optionally `&theme=transparent`. The first team is the left column and the first number of the score ("Series 2–1"), whatever side it played on.
- **Stage:** a fixed 1920×1080 layout, scaled with `transform: scale(min(w/1920, h/1080))` on load and on `resize`. Text is at least 28px at 1920 wide.
- **Content:** both team names, "Game N", the winner (marked "Winner"), the duration (m:ss) and the series score; per team the players sorted by raw points with hero icon, `K / D / A` and points to one decimal. The game's top raw score is highlighted (`obs-top`) and the confirmed MVP has a star. A line under the table says "Raw fantasy points: before card bonuses".
- **States:**
  - Before the series has a game with stats: the team names and "Stats appear here a few minutes after each game ends."
  - A game has ended and its stats are not in yet: "Game N stats are on their way" above the last game. For game 1 that line replaces the waiting line, with no older game.
  - No valid `teams` (missing, one id, not numbers, the same id twice): no request; a setup line pointing to How to Play › Streamers.
- **Refresh:** the page fetches once on load and then every 30 seconds (`setInterval`). It redraws only when the answer differs from the last one (compared as JSON). A failed request (an error status or a network failure) keeps the last view on screen and shows nothing; the next refresh tries again.
- **Theme:** `theme=transparent` adds `theme-transparent` to `<html>`; the stylesheet then sets `background: transparent` on `html`, `body` and the stage, and gives the header and team panels a dark translucent background so the text stays readable over the streamer's art. The default is the site's dark background (`--bg`).

## URL builder

How to Play › Streamers › **Pause screen overlay** (`frontend/index.html`, `frontend/app-init.js`): two team pickers filled once from `GET /teams` and sorted by name, a **Transparent background** checkbox, the URL in a read-only field (built from `location.origin`), **Copy** (Clipboard API, falling back to selecting the field) and **Open preview** (new tab). Copy and the preview link stay disabled until two different teams are picked. Below it, the OBS steps: add a Browser Source, paste the URL, set width 1920 and height 1080. See [How to Play Tab](how-to-play-tab.md) for the rest of the Streamers subtab.

## Endpoints

### `GET /obs/last-game?teams=<id>,<id>`
`backend/routers/obs.py`, registered in `main.py` before the `/` static mount. Public, no session. Per-IP limit of `RATE_LIMIT_GLOBAL` (200/minute by default) on the route itself: SlowAPIMiddleware's default limit does not reach routes added with `include_router` in the FastAPI version the project runs, so the route carries `@limiter.limit(RATE_LIMIT_GLOBAL)`. One overlay polling every 30 seconds uses 2 requests a minute.

- **`teams`:** split on the comma, whitespace around each part ignored; exactly two whole numbers in 1..2**63-1 and different from each other, at most 64 characters. Anything else, or no `teams`, is **422**. A well-formed id with no row in the `teams` table is **404**. Two known teams with no current series answer **200** with `game: null`.
- **Response** (`obs_overlay.last_game(db, team_a, team_b, now)`):

```json
{
  "teams": [{"team_id": 1, "team_name": "Reds"}, {"team_id": 2, "team_name": "Blues"}],
  "series_score": {"1": 2, "2": 0},
  "pending_game": 3,
  "game": {
    "match_id": 902, "game_number": 2, "winner_team_id": 1, "duration": 2145, "start_time": 1760007200,
    "parse_status": "parsed", "excluded_from_scoring": false,
    "teams": [{"team_id": 1, "team_name": "Reds", "players": [...]}, {"team_id": 2, "team_name": "Blues", "players": [...]}]
  }
}
```

`teams`, `series_score` and `game.teams` follow the order of the URL. Each `game.teams` entry is the one `schedule.game_players` returns (issue 244; cached, the same player keys: `player_id`, `player_name`, `hero_id`, `hero_icon`, `kills`, `deaths`, `assists`, `raw_points`, `is_mvp`, `top`); a team with no stats rows gets an empty `players` list. No user, card or ownership data.

## How the series is found

`backend/obs_overlay.py`:

- **Matches of the pair:** `matches` rows whose `radiant_team_id` and `dire_team_id` are exactly the two teams, either way round. A match with a missing side is never part of the series (the rule of `schedule._build_unscheduled_results` and `resolve_series_result`).
- **Current series:** walk back from the newest such match while each game started at most `schedule.SERIES_GAP_SECONDS` (6 hours, inclusive) before the next one. If the newest game started more than 6 hours before now, there is no current series and `game` is null, so an old meeting of the two teams is never shown.
- **Game number and score:** the games are numbered by start time; wins come from `radiant_win` through `schedule._tally_wins` (a NULL result counts for nobody); `winner_team_id` is null then too.
- **Pending game:** `live_matches` rows of the pair (both sides set) with `ended_at` within the last `PENDING_WINDOW_MINUTES` and no `player_match_stats` rows. `pending_game` is the series' game count plus the number of such rows, or null. `PENDING_WINDOW_MINUTES` reads `INGEST_POST_MATCH_FAST_POLL_MINUTES` (default 20, the window in which ingest polls fast after a game ends; `main.py` parses the same variable); 0 or less means nothing is pending. `live_matches` rows exist only while the Steam live check runs (`STEAM_API_KEY` set), so without it `pending_game` is always null.

`SERIES_GAP_SECONDS` lives in `backend/schedule.py`; `routers/weekly_summary._SERIES_GAP`, the clustering in `schedule._build_unscheduled_results` and `routers/admin_ingest.SERIES_GAP_SECONDS` use it. `frontend/app-admin-matches.js` keeps its own `_SERIES_GAP_SECONDS`.

## Tests

`backend/tests/test_issue_246_obs_last_game_overlay.py`: the series rules, the endpoint (shape, 422/404, no user data, rate limit), the page in a Node harness (rendering, escaping, polling, redraw, failures, theme, scaling) and the Streamers subtab text against the Twitch submission guides.

Not tried in OBS or a browser yet: check the stage at 1920×1080 and at a 720p output, `theme=transparent` over a coloured scene, and a live series moving from game 1 to game 2.
