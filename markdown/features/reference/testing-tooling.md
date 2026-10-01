# Testing Tooling

Tools for testing on dev and test servers: load a realistic season state in one action, drive ingest from a local mock OpenDota, and save or restore the test database. All of it is behind `DEMO_MODE` and refused in production.

---

## Season scenarios *(planned)*

`POST /admin/demo/scenario` with `pre-season`, `mid-season` or `season-end` replaces the game data with a deterministic, synthetic season and sets the demo clock. Mid-season has 5 scored weeks, rosters with benches, MVPs, a bench substitution, and one unparsed and one excluded match. Scenario accounts use `DEMO_ACCOUNT_PASSWORD`.

## Mock OpenDota *(planned)*

`tools/mock_opendota/` serves the OpenDota endpoints the app uses, from the same scripted season. The app points at it with `OPENDOTA_BASE_URL`. Control endpoints release the next match, make a game live, or mark a match parsed, so ingest, live polling, parse retry and early MVP selection can be tested end to end. Start it with the `mock` Compose profile.

## Snapshots *(planned)*

Save the test database under a name and restore it later (SQLite online backup, `data/demo-snapshots/`). Restore requires the admin password re-entry.

## Endpoints

### `POST /admin/demo/scenario` *(planned)*
### `GET /admin/demo/snapshots` *(planned)*
### `POST /admin/demo/snapshots` *(planned)*
### `POST /admin/demo/snapshots/{name}/restore` *(planned)*

All are admin only, and return 404 unless `DEMO_MODE=true`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `OPENDOTA_BASE_URL` | `https://api.opendota.com/api` | OpenDota API address; point it at the mock in dev. Must be https with `ENV=production` |
| `DEMO_ACCOUNT_PASSWORD` | *(empty)* | Password for scenario accounts; the scenario loader refuses to run without it |

`ENV=production` refuses `DEMO_MODE=true` at startup.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
