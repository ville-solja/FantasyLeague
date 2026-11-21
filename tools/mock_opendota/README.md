# Mock OpenDota

A local stand-in for OpenDota and Steam's `GetLiveLeagueGames` (issue #146), so the app's real ingest, live poll and parse retry run against scripted matches. Dev and test servers only: it is never in the app image, and Compose publishes it on `127.0.0.1:8090` only, because the control endpoints have no authentication.

The full walkthrough is in [testing-tooling.md](../../markdown/features/reference/testing-tooling.md#mock-opendota).

## Start

```
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.mock.yml up
```

`docker-compose.mock.yml` starts the mock and points the app at it: `OPENDOTA_BASE_URL=http://mock_opendota:8090`, `STEAM_LIVE_URL=http://mock_opendota:8090/IDOTA2Match_570/GetLiveLeagueGames/v1/` and `STEAM_API_KEY=mock`. Polling runs there also with `DEMO_MODE=true`.

Never point an app that holds real API keys (`OPENDOTA_API_KEY`, `STEAM_API_KEY`) at the mock: the app sends them as query parameters to whatever address is set. The mock runs with `--no-access-log` so uvicorn doesn't log those query strings; keep the flag when you run it yourself.

Without Docker, from this folder (the backend's dependencies installed):

```
uvicorn app:create_app --factory --port 8090 --no-access-log
```

The mock finds the backend through `MOCK_BACKEND_DIR` (the Dockerfile sets `/backend`); unset, it tries `/backend` and then `../../backend` from this folder. Without `DATABASE_URL` set, it uses an in-memory SQLite (`sqlite://`), so it never creates a database file.

## Script

By default the script is the mid-season scenario's unplayed weeks 6–10 (40 matches) in league `990001`, with the scenario's team, player and match ids, so released matches score against the scenario's rosters. Load the `mid-season` scenario in the app first.

`MOCK_SEED=<integer>` gives a standalone league instead (id `990100 + seed % 900`, "Mock League <seed>") with its own teams, players and match ids. Monitor that league in Admin › Settings › Season › League Management. A value that is not an integer stops the mock at startup.

Matches keep their scripted start times (weeks of 2026), and are released in start-time order.

## Control calls

```
# Release the next scripted match (parsed); it appears in /leagues/{id}/matchIds
curl -X POST localhost:8090/_control/next-match

# Release it unparsed (no "version", only the stats OpenDota has before a parse)
curl -X POST localhost:8090/_control/next-match -H 'Content-Type: application/json' -d '{"unparsed": true}'

# Make the next unreleased game live for 10 minutes (Steam's live list)
curl -X POST localhost:8090/_control/live -H 'Content-Type: application/json' -d '{"minutes": 10}'

# Turn a released unparsed match into a parsed one
curl -X POST localhost:8090/_control/parse/8000000044

# Start the script over (nothing released, live or parsed)
curl -X POST localhost:8090/_control/reset

# Released, live (with ends_at), unparsed, parse requests and remaining count
curl localhost:8090/_control/state
```

| Call | Answers |
|---|---|
| `POST /_control/next-match` | `{"match_id", "parsed", "start_time", "remaining"}`; 409 when the script is exhausted |
| `POST /_control/live` | `{"match_id", "ends_at"}`; 422 unless `minutes` is an integer from 1 to 1440; 409 when no match is left |
| `POST /_control/parse/{id}` | `{"match_id", "parsed": true}`; 404 for an unknown or unreleased match, 409 when already parsed |
| `POST /_control/reset` | `{"reset": true, "remaining"}` |
| `GET /_control/state` | `{"league_id", "league_name", "released", "live", "unparsed", "parse_requests", "remaining", "scripted"}` |

A live game stays live until its minutes run out; release it with `next-match` to have it ingested.

## Paths the app calls

| Path | Shape |
|---|---|
| `GET /leagues/{id}` | `{"leagueid", "name", "tier"}`; 404 for another league |
| `GET /leagues/{id}/matchIds` | Released match ids |
| `GET /matches/{id}` | OpenDota's match fields as `ingest.py` reads them; 404 until released |
| `POST /request/{id}` | `{"job": {"jobId"}}` (recorded in `parse_requests`) |
| `GET /constants/heroes` | Heroes 1–120 by id, with `localized_name` |
| `GET /players/{id}` | `{"profile": {"personaname", …}}` for scripted players; 404 otherwise. `/players/{id}/heroes` and `/matches` answer `[]` |
| `GET /IDOTA2Match_570/GetLiveLeagueGames/v1/?key=…` | `{"result": {"games": [...]}}`, every other player without a name; 403 without a key. The key is never echoed in a response, and the access log is off |
