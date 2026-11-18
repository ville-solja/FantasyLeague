# Plan: OBS Last Game Overlay

## Context
Issue #246: "Last match performance for OBS streamer showcase. When streaming a series it would be good for the pause screen data to have last match performance listed if possible." Between the games of a series, streamers show a pause screen. Today Kana Cards gives them nothing to put on it.

This plan adds a page a streamer loads in OBS as a **Browser Source**. It shows the last finished game of the series being streamed: the result, the series score, and each player's raw points with hero and K/D/A. It reuses the per-game player data built for #244 (`schedule.game_players`: raw points before card rarity, modifiers and the MVP bonus) and needs no login.

**Decisions** (change them in review if needed):
- **One page, chosen by team.** A streamer streams one series, so the overlay URL names its two teams: `/obs/last-game.html?teams=<team id>,<team id>`. The page always shows the most recent ingested game between those two teams, so it follows the series on its own with no action between games.
- **This series only.** A game counts as part of the current series when it is within the 6-hour series gap the Weekly Report already uses (now `schedule.SERIES_GAP_SECONDS`, shared by the schedule, Weekly Report, admin ingest and the overlay). Before game 1 has stats, the page shows a waiting line instead of the previous meeting of the two teams, which may be weeks old.
- **Stats arrive a few minutes after a game.** After a monitored game ends, ingest polls every 30 seconds for up to 20 minutes (`INGEST_POST_MATCH_FAST_POLL_MINUTES`), but the stats come from OpenDota and can take a few minutes. While a game between the two teams has ended (`live_matches.ended_at`) and has no stats yet, the page says "Game N stats are on their way" above the previous game's table. That is honest about the gap.
- **The page refreshes itself** every 30 seconds; OBS needs no refresh setting.
- **Readable on stream:** a fixed 1920×1080 layout scaled to the browser source, large type, the site's colours. `theme=transparent` drops the background for streamers who lay it over their own art.
- **A URL builder** on How to Play › Streamers: pick the two teams, copy the URL, open a preview. No account needed.
- **No spoiler rule:** the streamer chooses to show the result, so the page shows it.
- **No Twitch extension change.** The overlay works for any streamer, whether or not the extension is approved.
- **How to Play › Streamers covers every streamer tool** (added at the user's request during planning). Today the subtab describes only installing the full extension and picking an MVP by hand, and still says the extension is in Local Test. It gains a short section for each tool a streamer can use: the pause screen overlay (this issue), the viewer MVP vote in the full extension (#234), and the separate Kana Cards MVP Vote extension (#253). The text says plainly which extensions are approved by Twitch, and that is checked against the submission guides when this is built.

Resolves GitHub issue #246.

## User Stories

### Show the Last Game on the Pause Screen
**User story**
As a streamer casting a series, I want an OBS browser source that shows how each player did in the last game, so that my pause screen between games has something worth looking at.

**Acceptance criteria**
- **URL:** `/obs/last-game.html?teams=<id>,<id>` loads without a login and shows the most recent ingested game between those two teams, in the current series (games no more than 6 hours apart).
- **Header:** both team names, "Game N" (its number in the series), the winner, the game's duration and the series score so far (e.g. "Series 1–0"). The columns and the score follow the URL's team order (first team left, its wins first), not radiant/dire.
- **Players:** two columns, one per team, five players each, sorted by raw points (highest first): name, hero icon, kills / deaths / assists, raw points to one decimal. The game's top raw score is highlighted; the confirmed MVP has a star.
- **Label:** a small line says "Raw fantasy points: before card bonuses", so viewers don't confuse it with card points.
- **Size:** laid out for 1920×1080 and scaled to the browser source's size, with text large enough to read on a stream at 720p.
- **Theme:** `theme=transparent` leaves the page background transparent; the default is the site's dark background.
- **Not set up:** with a missing or malformed `teams` the page makes no request and shows a short line pointing to How to Play › Streamers.

### Follow the Series Without Touching OBS
**User story**
As a streamer, I want the overlay to move on to each new game by itself, so that I don't have to change anything in OBS during the series.

**Acceptance criteria**
- The page re-reads its data every 30 seconds and redraws only when the game or its data changed.
- When game 2 has stats, the page shows game 2 without a reload.
- While a game between the two teams has ended and has no stats yet, the page shows "Game N stats are on their way" above the last game it has.
- Before the series' first game has stats, the page shows the two team names and "Stats appear here a few minutes after each game ends." and no older game. If game 1 has already ended, it shows the team names and "Game 1 stats are on their way" instead.
- A failed request keeps the last good view on screen and tries again at the next refresh; it never shows an error over the stream.

### Build the Overlay URL
**User story**
As a streamer, I want to pick the two teams and copy a ready URL, so that I don't have to look up team ids.

**Acceptance criteria**
- How to Play › Streamers has a **Pause screen overlay** section: two team pickers (the league's teams by name), a Transparent background checkbox, the resulting URL in a read-only field, a **Copy** button and an **Open preview** link.
- The section explains the OBS steps in three lines: add a Browser Source, paste the URL, set width 1920 and height 1080.
- Copy is disabled until two different teams are picked.

### Streamers Tab Lists Every Streamer Tool
**User story**
As a streamer, I want How to Play › Streamers to show everything Kana Cards offers a streamer, so that I can pick what fits my stream without asking the league.

**Acceptance criteria**
- **Overview:** the subtab opens with a short list of the tools, each one line with a link to its section: **Pause screen overlay** (an OBS browser source, no extension needed), **Kana Cards extension** (the full panel game with match MVP and token drops), **Viewer MVP vote** (in the Kana Cards extension) and **Kana Cards MVP Vote** (a small vote-only extension).
- **Pause screen overlay:** the section from the story above, with the URL builder and the OBS steps.
- **Viewer MVP vote:** how to start a vote from Quick Actions (Select match MVP → series → match → **Start viewer vote**, 1, 2 or 3 minutes), that joined viewers vote in the panel, **End now** and **Cancel vote**, and that **Confirm MVP & Drop Tokens** sets the MVP and drops tokens as a hand pick does. The section says the vote comes with extension version 1.4.0 and is not yet available on Twitch.
- **Kana Cards MVP Vote:** what it is for (a vote without the card game on the channel), that any viewer logged in to Twitch can vote, that voters who share their Twitch identity can win a token claimed at kana-cards.com, and that a channel normally installs one of the two extensions. Its confirm button is **Confirm MVP**. The section says the extension has not been submitted to Twitch yet and is not yet available on Twitch.
- **Status is accurate:** the text does not say an extension is in testing or released unless that is true when it ships; the existing "Getting access" text is updated to match the current Twitch review status of each extension. As of #246: the Kana Cards extension is not yet approved by Twitch and so not yet available on Twitch, so channels install it as testers with a test install link from the league (the "Local Test" wording is gone); the viewer vote comes with version 1.4.0, not yet released; Kana Cards MVP Vote has not been submitted.
- **Approval:** each extension section repeats that a channel needs the league's approval before it can set MVPs, and that the overlay needs none.

### Public Endpoint for the Last Game
**User story**
As the overlay page, I want one call that returns the last game of a series and its players, so that the page stays simple.

**Acceptance criteria**
- `GET /obs/last-game?teams=<id>,<id>` is public and returns `teams` (both ids and names), `series_score`, `pending_game` (the number of a game that ended without stats, or null) and `game` (null before the first game) with `match_id`, `game_number`, `winner_team_id`, `duration`, `start_time` and the `game_players` payload (`parse_status`, `excluded_from_scoring`, both teams' players with raw points, `is_mvp`, `top`).
- `teams` must be exactly two different positive team ids (1..2**63-1, comma-separated, whitespace around each allowed); anything else answers 422. An unknown team id answers 404. Two known teams with no current series answer 200 with `game: null`.
- It returns no user, card or ownership data.
- It is limited per IP at the global rate (`RATE_LIMIT_GLOBAL`, set on the route itself, since the middleware's default limit doesn't reach included routers); one overlay polling every 30 seconds is far below it.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/obs_overlay.py` (new) | `last_game(db, team_a, team_b, now)`: the current series between two teams, its last game with `schedule.game_players`, the series score, a pending game from `live_matches` |
| `backend/routers/players.py` | `GET /obs/last-game` (public), or a new small router if `players.py` is crowded |
| `frontend/obs/last-game.html`, `frontend/obs/last-game.js`, `frontend/obs/last-game.css` (new) | The overlay page; self-contained, no app modules |
| `frontend/index.html`, `frontend/app-*.js` (the How to Play module) | Streamers subtab: overview of the streamer tools, the Pause screen overlay section with the URL builder, the Viewer MVP vote and Kana Cards MVP Vote sections, updated Getting access text |
| `backend/tests/test_issue_246_obs_last_game_overlay.py` | Tests |
| `markdown/features/reference/obs-last-game-overlay.md`, `markdown/features/reference/how-to-play-tab.md` (Streamers row) | Docs |

No migration and no new setting.

### Step 1 — Find the series and its last game
In `obs_overlay.py`, select matches whose `{radiant_team_id, dire_team_id}` equals the two teams, newest first. Walk back from the newest while the gap to the next one is at most 6 hours (reuse or move `weekly_summary._SERIES_GAP`; do not copy the number). If the newest game is more than 6 hours older than `now`, there is no current series: `game` is null. Otherwise number the series' games by `start_time`, take wins from `radiant_win`, and build `game` from the newest one with `schedule.game_players`.

Pending game: a `live_matches` row with both team ids, `ended_at` set within the last `INGEST_POST_MATCH_FAST_POLL_MINUTES`, and no `player_match_stats`. Its number is the series' game count plus one.

Check first how `_build_games` and `team_insights` decide a match's teams when one side's id is missing, and follow the same rule.

### Step 2 — Endpoint
Parse `teams` as a comma-separated pair of ints bounded like other ids (`1..2**63-1`); 422 unless exactly two different ids. 404 when either team is missing. Return a plain dict. Look at how `GET /schedule` and `GET /matches/{id}/players` are registered (public, global limit) and do the same.

### Step 3 — Overlay page
A standalone page under `frontend/obs/` that the existing static mount serves. It loads only its own script and stylesheet (no app modules, no guided tour, no login), links `/colors_and_type.css` for the colour tokens and fonts (no copy), and escapes every name with its own escaper. A 1920×1080 stage scaled with `transform: scale(...)` to the window. Poll every 30 seconds; compare a key built from `match_id`, the stats and `pending_game` before redrawing. On error keep the last view. Check that the site's security headers (Content-Security-Policy in `main.py`) allow the page's own script and style files; an OBS browser source loads it as a top-level page, so `frame-ancestors` does not apply.

### Step 4 — Streamers subtab and URL builder
Restructure the How to Play › Streamers subtab: an overview list of the four tools at the top (in-page links), then one section per tool. Write the Viewer MVP vote section from `markdown/features/reference/twitch-mvp-viewer-poll.md` and the MVP Vote section from `markdown/features/reference/twitch-mvp-vote-extension.md`, and check the extensions' Twitch status against the review history in both submission guides before writing it. Grep `backend/tests` (`test_how_to_play_role_subtabs.py`, `test_issue_157_*`) for tests that pin the subtab's text, such as the Local Test wording and the "No URL configuration" line, and update them with the text.

In the Pause screen overlay section: team pickers filled from `GET /teams`, the Transparent checkbox, the URL field built from `location.origin`, Copy (Clipboard API, with a select-all fallback) and Open preview. Grep `backend/tests` for tests that pin the How to Play subtabs' content before editing.

### Step 5 — Tests
- `last_game`: the newest game of the current series with its number and the series score; games more than 6 hours apart start a new series; no current series gives `game: null`; a pending game is reported while its stats are missing and not after; teams given in either order give the same answer.
- Endpoint: public 200; 422 for one id, three ids, the same id twice, a non-number or an id out of range; 404 for an unknown team; no user or card fields.
- Page (source and Node harness): it calls only `/obs/last-game`, escapes names, keeps the last view on a failed request, shows the waiting and pending lines, and applies `theme=transparent`.
- URL builder: Copy disabled until two different teams are picked; the URL is `/obs/last-game.html?teams=A,B` (plus `&theme=transparent` when checked).
- Streamers subtab: the overview lists the four tools with working in-page links; the Viewer MVP vote and MVP Vote sections name the real controls (`Start viewer vote`, `End now`, `Cancel vote`, `Confirm MVP`); no text claims a Twitch status the submission guides don't support.

## As built (corrections to the plan)
- `GET /schedule` is in `routers/admin_ingest.py`, not `players.py`. The endpoint got its own router, `backend/routers/obs.py`, registered before the `/` static mount.
- The global default limit of SlowAPIMiddleware does not reach routes added with `include_router` (newer FastAPI wraps them in `_IncludedRouter`), so the route carries `@limiter.limit(RATE_LIMIT_GLOBAL)` itself.
- `obs_overlay.PENDING_WINDOW_MINUTES` reads `INGEST_POST_MATCH_FAST_POLL_MINUTES` with main's default and parsing; `main` is never imported.
- Status of the extensions when this shipped: the Kana Cards extension is not yet approved by Twitch and not yet available (testers install it with a test install link); the viewer vote comes with version 1.4.0, not yet released; Kana Cards MVP Vote has not been submitted. The full extension's confirm button is "Confirm MVP & Drop Tokens"; the MVP Vote extension's is "Confirm MVP".
- Feature doc: `markdown/features/reference/obs-last-game-overlay.md`.

## Verification
- Add the URL as an OBS Browser Source at 1920×1080 and play a series on a local copy (or replay ingest of two stored games): game 1 shows after its stats arrive, game 2 replaces it without touching OBS, and the pending line shows in between.
- Before game 1: the waiting line, not an older meeting of the two teams.
- `theme=transparent` over a coloured OBS background.
- Readability at a 720p stream output.
- How to Play › Streamers on desktop and phone: every tool listed, links jump to their sections, the builder works.
