# Plan: Mock OpenDota

## Context
Ingest, parse retry and early MVP selection can only be tried against the real league as it plays. This issue adds a small local stand-in for the outside match-data services. A tester can release a match, make a game live or mark a match parsed, and the app's real polling code ingests it.

It is split from the umbrella plan `plan-issue-114-testing-tooling.md`, with three changes for the code as it is now:

- **Live games come from Steam, not OpenDota.** Since #161, `backend/steam_live.py` reads Steam's `IDOTA2Match_570/GetLiveLeagueGames`, and nothing calls OpenDota `/live`. To make "a live game appears as provisional in the Twitch panel" work, the mock serves that Steam path too. A new `STEAM_LIVE_URL` setting points the app at it. The `/live` endpoint and the "string `match_id`" detail are dropped.
- **Polling with `DEMO_MODE`.** `main._start_background_threads` skips ingest and live polling when `DEMO_MODE=true`, but scenarios (#145) need `DEMO_MODE`. Rule: Demo Mode skips polling only while `OPENDOTA_BASE_URL` is the real OpenDota address. With a mock address, polling runs, so a demo server never calls the real API with a fake clock.
- **Compose profiles can't change the app's environment.** A profile only switches services on. The mock setup is therefore a third Compose file, `docker-compose.mock.yml`, which adds the mock service and sets the app's addresses. It replaces "`--profile mock`".

**Assumptions:**
- The mock is a dev tool. It lives in `tools/mock_opendota/`, is never in the production image and never on a public port: Compose publishes it on `127.0.0.1` only.
- The mock imports `backend/season_generator.py` (#145) from a read-only mount of `backend/`. By default it scripts the mid-season scenario's unplayed weeks (6–10) in league `SCENARIO_LEAGUE_ID`, so released matches score against scenario rosters. `MOCK_SEED` gives a standalone league with its own teams. Building this issue before #145 is possible: the generator then comes with this issue.
- With `ENV=production`, startup refuses a non-https `OPENDOTA_BASE_URL` or `STEAM_LIVE_URL`.

Resolves GitHub issue #146.

## User Stories

### Drive Ingest with a Mock OpenDota
**User story**
As a developer, I want the app to ingest matches from a local mock OpenDota so that I can test ingest, live polling, parse retry and early MVP selection exactly as they run in production.

**Acceptance criteria**
- `OPENDOTA_BASE_URL` (default `https://api.opendota.com/api`) replaces the hard-coded address, and every OpenDota call uses it. `STEAM_LIVE_URL` (default Steam's `GetLiveLeagueGames` address) does the same for the live check
- `tools/mock_opendota/` serves the paths the app calls: `/leagues/{id}`, `/leagues/{id}/matchIds`, `/matches/{id}`, `POST /request/{id}`, `/constants/heroes`, `/players/{id}` and Steam's `/IDOTA2Match_570/GetLiveLeagueGames/v1/`. Responses follow the field shapes the app reads
- Control endpoints:
  - `POST /_control/next-match` releases the next scripted match
  - `POST /_control/live` with `{"minutes"}` makes the next scripted game live for N minutes
  - `POST /_control/parse/{id}` turns an unparsed match into a parsed one
  - `POST /_control/reset` resets the script
  - `GET /_control/state` lists released, live and unparsed matches
- By default the script is the mid-season scenario's unplayed weeks, so mock matches score against scenario rosters. `MOCK_SEED` gives a standalone league
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.mock.yml up` starts the app with the mock and both addresses pointing at it. Ingest and live polling run there, also with `DEMO_MODE=true`
- With `ENV=production`, startup refuses a non-https `OPENDOTA_BASE_URL` or `STEAM_LIVE_URL`

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/opendota_client.py` | `OPEN_DOTA_URL = os.getenv("OPENDOTA_BASE_URL", DEFAULT).rstrip("/")`; `is_default_base_url()` |
| `backend/steam_live.py` | `_URL` from `STEAM_LIVE_URL` |
| `backend/main.py` | https guard for both under `ENV=production`; Demo Mode skips polling only with the default OpenDota address |
| `tools/mock_opendota/app.py`, `README.md`, `Dockerfile` *(new)* | The mock: scripted state, OpenDota and Steam paths, control endpoints |
| `docker-compose.mock.yml` *(new)* | Mock service on `127.0.0.1:8090`; app environment `OPENDOTA_BASE_URL`, `STEAM_LIVE_URL`, `STEAM_API_KEY=mock` |
| `.env.example`, `markdown/features/reference/testing-tooling.md`, `markdown/features/reference/ingest.md` | Docs |
| `backend/tests/test_issue_146_mock_opendota.py` | Tests: settings, guards, polling rule, and an ingest run against the mock app through `TestClient` |

### Step 1 — Configurable addresses
Read both settings at import. Every caller already uses `OPEN_DOTA_URL` (`ingest`, `enrich`, `schedule`, `player_lookup`, `manual_match`, `routers/admin_players`); confirm with a grep that no other `api.opendota.com` literal remains. Add the production https check next to the existing `ENV=production` checks in `main.py`.

### Step 2 — Polling rule
In `_start_background_threads`, replace `if _DEMO_MODE:` with `if _DEMO_MODE and opendota_client.is_default_base_url():`. Log which rule applied.

### Step 3 — The mock
A FastAPI app with an in-memory state built from `season_generator.generate()`. Match JSON uses OpenDota's fields as `ingest.py` reads them: `match_id`, `start_time`, `duration`, `radiant_win`, `radiant_team_id`, `dire_team_id`, `radiant_name`, `dire_name`, `picks_bans`, and per player `account_id`, `isRadiant`, `player_slot`, `hero_id`, `personaname` and each scored stat. An unparsed match omits the parsed-only stats, as OpenDota does, until `/_control/parse/{id}` adds them. The Steam live response follows `steam_live.parse_live_league_games`, including players without names. `POST /request/{id}` answers like OpenDota's job response.

### Step 4 — Compose and docs
`docker-compose.mock.yml` adds the `mock_opendota` service (build `tools/mock_opendota`, mount `./backend:/backend:ro`) and sets the backend's environment. The folder README lists the control calls with `curl` examples. `testing-tooling.md` gets a "Mock OpenDota" walkthrough: start, monitor league 990001 in Admin › Leagues, release a match, watch it ingest.

## Verification
- `cd backend && python -m pytest tests/test_issue_146_mock_opendota.py tests/test_ingest*.py -q`, then the full suite.
- With `OPENDOTA_BASE_URL` pointing at the mock (`TestClient` transport in tests): release a match, run one ingest pass, and the match and its stats are stored with the expected fantasy points.
- Make a game live, run `_live_poll_once`, and the match is in `live_matches` and shown as provisional by the Twitch panel endpoint.
- Release an unparsed match, ingest it (partial-stat marker), parse it in the mock, run parse retry, and the stats are replaced.
- `ENV=production` with `OPENDOTA_BASE_URL=http://…` fails at import. `DEMO_MODE=true` with the default address skips polling; with a mock address it polls.
- Manual: start the three Compose files, load the mid-season scenario, release two matches and check week 6 points on My Team.
