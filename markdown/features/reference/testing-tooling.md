# Testing Tooling

Tools for testing on dev and test servers:

- load a realistic season state in one action;
- drive ingest from a local mock OpenDota;
- save and restore the test database.

All of it is behind `DEMO_MODE` and refused in production. Plans: `plan-issue-145-season-scenarios.md`, `plan-issue-146-mock-opendota.md` and `plan-issue-147-demo-snapshots.md`.

---

## Season scenarios

`POST /admin/demo/scenario` with `pre-season`, `mid-season` or `season-end` replaces the game data with a deterministic, synthetic season and sets the demo clock. The admin Demo Mode panel has a scenario picker with an in-page confirmation where the admin types `LOAD SCENARIO` (the issue #150 rule for destructive admin actions); the request goes through `adminFetch`, so it asks for the password when the re-auth is not recent.

| Scenario | Seed | Weeks locked | Data |
|---|---|---|---|
| `pre-season` | 145001 | 0 of 10 | No matches; accounts with starter tokens (`INITIAL_TOKENS`) and 3 cards each |
| `mid-season` | 145002 | 5 of 10 | Week 6 open; 10–15 cards per account with benches, MVPs on 4 of 5 matches, a bench substitution in week 3, one unparsed and one excluded match in week 4 |
| `season-end` | 145003 | 10 of 10 | Every week scored and reported, no season archive, so End Season can run |

All three have 8 teams ("Scenario Team A" to "H") of 5 generated players, two-game series, and the monitored league `990001` (`scenarios.SCENARIO_LEAGUE_ID`, shared with the mock). Week 1 starts Monday 2026-01-05 00:00 UTC; each week's match window is Monday to Friday, so the weekend leaves room for the 24-hour substitution delay. The final clock is 12 hours before the next week's lock: for mid-season, Sunday before week 6, with weeks 1–5 locked, substituted and reported and week 6 still editable.

### What is kept

`backend/scenarios.py` lists the tables. A load keeps `scenarios.KEPT_TABLES` (`weights`, `scoring_state`, `tag_definitions`, `audit_logs`, `demo_clock`) and the caller's own `users` and `user_sessions` rows, so the caller stays logged in. It runs `season_reset.clear()` and then deletes every table in `scenarios.EXTRA_DELETED_TABLES`, which is every other table, season history and other accounts included, so scenario data never mixes with real data. A test checks that each model table is in exactly one of `season_reset.CLEARED_TABLES`, `KEPT_TABLES` and `EXTRA_DELETED_TABLES`. An empty `weights` table gets the default weights.

### How it is built

1. `backend/season_generator.py`'s `generate(seed, *, weeks, teams, players_per_team, games_per_team_week, users, cards_per_user, roster_size, start, …)` returns plain dicts: teams, players, weeks, matches (with `radiant_name`, `dire_name`, `parse_status`, `series_id`, per-player stats with `hero_id` and `is_mvp`) and users with cards and modifiers. It imports only `scoring.SCORING_STATS` and `card_utils._SCORED_STAT_COLS`; note that `card_utils` imports `models`, so the mock's container mounts the backend and installs its dependencies. `scripts/bench_leaderboards.py` writes the same output, with the same draws as before, so its counts and totals are unchanged.
2. The loader inserts the league, teams, players, unlocked weeks, the accounts (`scenario-admin` as admin and `scenario1`–`scenario5`, all `is_demo` with `@demo.local` emails). The players' password is `DEMO_ACCOUNT_PASSWORD`; `scenario-admin` gets a new random password (`secrets.token_urlsafe`) on every load, returned once in the response and never logged or audited, so a tester given a player login doesn't also have the admin login and their cards. Only active cards get a `slot_index`. If the caller's username matches a scenario account name, the caller's row plays that account.
3. For each week to lock it changes `scenario5`'s roster from week 2 on (one active card swapped for a bench card), sets the clock to the week's start, runs `auto_lock_weeks`, `due_substitutions` and `generate_weekly_summaries` (the `POST /admin/demo/clock` sequence), and inserts the week's matches with `fantasy_points` including the MVP bonus. The player on `scenario1`'s first card plays no game in week 3, which gives the substitution.
4. It sets the final clock, runs the jobs again, rebuilds stored card points (`card_points.rebuild_all`), writes the `demo_scenario_loaded` audit entry (`name=… users=… matches=…`) and empties the season caches after the commit.

The week jobs commit as they go, so the loader turns the session's commits into flushes for the duration of the load. The load is one transaction: an error anywhere rolls back the wipe too.

## Mock OpenDota

`tools/mock_opendota/` is a local stand-in for OpenDota and for Steam's `GetLiveLeagueGames`, where live games have come from since #161. The app's real polling code runs against it, end to end: ingest, live polling, parse retry and early MVP selection. Its control endpoints release the next match, make a game live and mark a match parsed. Control calls with `curl` and the response shapes are in [tools/mock_opendota/README.md](../../../tools/mock_opendota/README.md).

The mock is a dev tool. It is never in the app image (the root `.dockerignore` excludes `tools/`), and Compose publishes it on `127.0.0.1:8090` only, because the control endpoints have no authentication. It runs with `--no-access-log`, so the query-string keys the app sends are not logged. Never point an app that holds real `OPENDOTA_API_KEY` or `STEAM_API_KEY` values at it.

### Walkthrough

1. Start the app with the mock:

   ```
   docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.mock.yml up
   ```

   `docker-compose.mock.yml` adds the `mock_opendota` service and sets the backend's `OPENDOTA_BASE_URL=http://mock_opendota:8090`, `STEAM_LIVE_URL=http://mock_opendota:8090/IDOTA2Match_570/GetLiveLeagueGames/v1/` and `STEAM_API_KEY=mock`. It also sets short poll intervals (`INGEST_POLL_INTERVAL=30`, `LIVE_POLL_INTERVAL=15`), a wide `INGEST_PARSE_RETRY_HOURS` and an empty `DOTABUFF_LEAGUE_LOGO_PAGES` (no logo scraping); details below.
2. With `DEMO_MODE=true` and `DEMO_ACCOUNT_PASSWORD` set, load the `mid-season` scenario (Admin › Settings › Maintenance › Demo Mode). League 990001 is then monitored in Admin › Settings › Season › League Management. Without the scenario, add league 990001 there and mark it monitored.
3. Release a match: `curl -X POST localhost:8090/_control/next-match`. The next ingest pass, within `INGEST_POLL_INTERVAL` (30 s here) or at once with **Ingest Now** on the league's row in League Management, stores it with its stats and points.
4. Make a game live: `curl -X POST localhost:8090/_control/live -H 'Content-Type: application/json' -d '{"minutes": 10}'`. The live poll stores it in `live_matches`, and the Twitch panel shows it as provisional for early MVP selection.
5. Parse retry: release a match with `-d '{"unparsed": true}'`, which gives Partial stats. Parse it with `curl -X POST localhost:8090/_control/parse/<id>`, and the next parse-retry pass (or **Retry parse** in Admin › Matches) replaces the stats.
6. Release two matches and check week 6 points on My Team. `curl -X POST localhost:8090/_control/reset` starts the script over; matches the app already stored stay stored.

### Script

By default the script is the mid-season scenario's unplayed weeks 6–10: 40 matches in league `990001`. It is built with `season_generator.generate()` and the same seed and parameters as `scenarios.load("mid-season")`, so the teams, players and match ids are the scenario's, and released matches score against the scenario's rosters. Matches are released in start-time order and keep their scripted start times, so they fall into scenario weeks 6–10.

`MOCK_SEED=<integer>` gives a standalone league instead (id `990100 + seed % 900`) with its own team, player and match ids. A value that is not an integer stops the mock at startup.

Match JSON uses OpenDota's fields as `ingest.py` reads them. An unparsed match has no `version` and only `season_generator.UNPARSED_STATS`, as OpenDota sends before a replay parse, so ingest stores it as `unparsed` and asks for a parse (`POST /request/{id}`, recorded in `/_control/state`). The Steam response follows `steam_live.parse_live_league_games`; every other player has no name, as Steam often sends. Without a key the Steam path answers 403, and it never echoes the key.

The mock imports `backend/season_generator.py` and `backend/scenarios.py` from a read-only `./backend:/backend:ro` mount. They import the backend's models, so the mock image installs the backend's hash-locked `requirements.lock`, and `DATABASE_URL=sqlite://` keeps `database` on an in-memory SQLite, so the mock never creates a database file.

### Polling and the clock

- **Demo Mode.** It skips the ingest and live poll threads only while `OPENDOTA_BASE_URL` is the real API (`opendota_client.is_default_base_url()`, which compares the hostname, so `http://`, an uppercase host or a port still count as the real API). Other jobs, such as profile enrichment and the hero constants warm-up, still call the address that is set. With the mock address, both run. The live thread also needs a non-default `STEAM_LIVE_URL` (`steam_live.is_default_url()`, also by hostname), so a demo server never calls the real Steam API; otherwise start-up logs "Live poll thread skipped (DEMO_MODE=true with the default STEAM_LIVE_URL)". Start-up logs which rule applied: "Demo Mode with the default OpenDota address: match polling is off" or "Demo Mode with a non-default OpenDota address (mock): match polling runs".
- **Parse retry.** It uses the real clock, and scripted matches are dated 2026. The mock Compose file therefore sets `INGEST_PARSE_RETRY_HOURS=87600`, so these matches are re-checked and not marked unparseable at once.
- **Production.** With `ENV=production`, startup refuses a non-https `OPENDOTA_BASE_URL` or `STEAM_LIVE_URL` (`[SECURITY]` `RuntimeError` naming the variable; only the scheme is printed, never the address).

## Snapshots *(planned, #147)*

Saving writes the database under a name in `data/demo-snapshots/` with SQLite's online backup. Restoring copies a snapshot back while the app runs. After it:

- the schema is migrated;
- stored card points are rebuilt and the caches emptied;
- the restoring admin stays logged in and every other session ends.

Restore requires the admin password re-entry. It refuses (409) when the snapshot has no admin account with the caller's id.

## Endpoints

### `POST /admin/demo/scenario`
Body `{"name": "pre-season" | "mid-season" | "season-end"}` (422 otherwise). Requires a recent re-auth (403 `reauth_required`) and `confirm` equal to `LOAD SCENARIO` in the body or query, any case (400 `confirmation_required`, `deps.CONFIRM_PHRASES["demo_scenario"]`). The checks run in that order, after the Demo Mode check (404). Returns 409 when `DEMO_ACCOUNT_PASSWORD` is unset or breaks the registration password rules (at least 6 characters, at most 72 bytes); the message names the variable, never its value. Answers `{"scenario", "override_timestamp", "effective_now", "accounts": [usernames], "counts": {accounts, teams, players, weeks, locked_weeks, matches, stat_rows, cards, roster_entries, substitutions}, "admin_password"}`. `admin_password` is scenario-admin's one-time password (`null` when the caller is scenario-admin and keeps their own); the response never contains `DEMO_ACCOUNT_PASSWORD`.
### `GET /admin/demo/snapshots` *(planned)*
### `POST /admin/demo/snapshots` *(planned)*
Body `{"name"}`, matching `^[A-Za-z0-9-]{1,40}$`. Returns 409 when the name exists.
### `POST /admin/demo/snapshots/{name}/restore` *(planned)*
Requires a recent re-auth. Returns 422 for an invalid name (including `../x` and `a/b`).

All are admin only, and return 404 unless `DEMO_MODE=true`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `OPENDOTA_BASE_URL` | `https://api.opendota.com/api` | OpenDota API address, read at startup (a trailing `/` is dropped); point it at the mock in dev. Must be https with `ENV=production`. Demo Mode polls only when its host is not `api.opendota.com`. `OPENDOTA_API_KEY` is sent as a query parameter to this address: only point it at a trusted host |
| `STEAM_LIVE_URL` | `https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/` | Live-games address; point it at the mock in dev. Must be https with `ENV=production`. `STEAM_API_KEY` is sent as a query parameter to this address: only point it at a trusted host |
| `DEMO_ACCOUNT_PASSWORD` | *(empty)* | Password for the scenario player accounts (`scenario1`–`scenario5`; `scenario-admin` gets its own one-time password); the loader answers 409 when it is unset, shorter than 6 characters or over 72 bytes |
| `MOCK_SEED` | *(empty)* | Mock only: an integer gives a standalone scripted league (id `990100 + seed % 900`) instead of the mid-season scenario's weeks 6–10; anything else stops the mock |

`ENV=production` refuses `DEMO_MODE=true` at startup (`[SECURITY]` `RuntimeError` from `main.py`). Test server setup (`test.kana-cards.com`): `DEMO_MODE=true`, `DEMO_ACCOUNT_PASSWORD` set, `ENV` unset.

---

*This document is a stub created at feature planning time. Season scenarios (#145) and the mock OpenDota (#146) are filled in; the snapshot section is still planned.*
