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

1. `backend/season_generator.py`'s `generate(seed, *, weeks, teams, players_per_team, games_per_team_week, users, cards_per_user, roster_size, start, …)` returns plain dicts: teams, players, weeks, matches (with `radiant_name`, `dire_name`, `parse_status`, `series_id`, per-player stats with `hero_id` and `is_mvp`) and users with cards and modifiers. It imports only `scoring.SCORING_STATS` and `card_utils._SCORED_STAT_COLS`; note that `card_utils` imports `models`, so the mock's container needs the backend package on its path. `scripts/bench_leaderboards.py` writes the same output, with the same draws as before, so its counts and totals are unchanged.
2. The loader inserts the league, teams, players, unlocked weeks, the accounts (`scenario-admin` as admin and `scenario1`–`scenario5`, all `is_demo` with `@demo.local` emails). The players' password is `DEMO_ACCOUNT_PASSWORD`; `scenario-admin` gets a new random password (`secrets.token_urlsafe`) on every load, returned once in the response and never logged or audited, so a tester given a player login doesn't also have the admin login and their cards. Only active cards get a `slot_index`. If the caller's username matches a scenario account name, the caller's row plays that account.
3. For each week to lock it changes `scenario5`'s roster from week 2 on (one active card swapped for a bench card), sets the clock to the week's start, runs `auto_lock_weeks`, `due_substitutions` and `generate_weekly_summaries` (the `POST /admin/demo/clock` sequence), and inserts the week's matches with `fantasy_points` including the MVP bonus. The player on `scenario1`'s first card plays no game in week 3, which gives the substitution.
4. It sets the final clock, runs the jobs again, rebuilds stored card points (`card_points.rebuild_all`), writes the `demo_scenario_loaded` audit entry (`name=… users=… matches=…`) and empties the season caches after the commit.

The week jobs commit as they go, so the loader turns the session's commits into flushes for the duration of the load. The load is one transaction: an error anywhere rolls back the wipe too.

## Mock OpenDota *(planned, #146)*

`tools/mock_opendota/` serves the OpenDota paths the app uses, plus Steam's `GetLiveLeagueGames`, where live games have come from since #161. By default it serves the mid-season scenario's unplayed weeks in league 990001. The app points at it with `OPENDOTA_BASE_URL` and `STEAM_LIVE_URL`. Its control endpoints can:

- release the next match;
- make a game live;
- mark a match parsed.

That covers ingest, live polling, parse retry and early MVP selection end to end. To start it:

```
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.mock.yml up
```

Demo Mode skips polling only while `OPENDOTA_BASE_URL` is the real API, so polling runs against the mock.

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
| `OPENDOTA_BASE_URL` *(planned, #146)* | `https://api.opendota.com/api` | OpenDota API address; point it at the mock in dev. Must be https with `ENV=production` |
| `STEAM_LIVE_URL` *(planned, #146)* | Steam's `GetLiveLeagueGames` address | Live-games address; point it at the mock in dev. Must be https with `ENV=production` |
| `DEMO_ACCOUNT_PASSWORD` | *(empty)* | Password for the scenario player accounts (`scenario1`–`scenario5`; `scenario-admin` gets its own one-time password); the loader answers 409 when it is unset, shorter than 6 characters or over 72 bytes |
| `MOCK_SEED` *(planned, #146)* | *(empty)* | Mock only: a standalone scripted league instead of the mid-season scenario's |

`ENV=production` refuses `DEMO_MODE=true` at startup (`[SECURITY]` `RuntimeError` from `main.py`). Test server setup (`test.kana-cards.com`): `DEMO_MODE=true`, `DEMO_ACCOUNT_PASSWORD` set, `ENV` unset.

---

*This document is a stub created at feature planning time. Season scenarios (#145) are filled in; the mock and snapshot sections are still planned.*
