# Architecture Maturity Review

Two read-only operator tools that size the current architecture (one process, one SQLite file) against a season's real load, and the review written from their numbers. Issue #251. Plan: `markdown/plans/plan-issue-251-architecture-maturity-review.md`.

Neither tool changes production behaviour. Neither is run by the app; both are run by hand from the repo root.

---

## Usage report

```
python3 scripts/usage_report.py --db <path to a database backup> [--json]
```

Prints a season's usage from a database file. It opens the file with SQLite's `mode=ro`, so it writes nothing. Point it at a backup (`bash scripts/backup-db.sh`, or a download from the admin panel), not at the file a running server writes to.

| Section | What it counts | Source |
|---|---|---|
| **Accounts** | Website accounts, Twitch soft accounts, accounts with a card, accounts with a roster in each week | `users.account_type`, `cards`, `weekly_roster_entries` |
| **Activity** | Draws and logins per week, the busiest hour and the busiest minute of the season | `audit_logs` (`token_draw`, `token_booster_draw`, `user_login`), bucketed by `weeks.start_time` / `end_time` |
| **Twitch** | Channels, MVPs set, token drops, the largest presence pool | `twitch_mvp`, `twitch_token_drops`, and `pool_size=` in the `twitch_token_drop` audit details |
| **Data** | Rows per table, file size, growth per week | every table; `os.path.getsize` |

Limits of the numbers:

- **Roster saves are not counted.** Roster changes write no audit row, so the report says "not recorded" instead of 0. Rosters per week come from the weekly snapshots.
- **Peaks are audited actions, not requests.** The busiest hour and minute count audit rows (draws, logins, admin actions). Page loads and leaderboard reads are not in the database; the reverse proxy's access log is the source for those.
- **The largest presence pool is seen only at token drops,** because `twitch_presence` holds just the current heartbeats.
- **Privacy:** the output holds counts only: no usernames, emails or ids.

## Load test

```
python3 scripts/load_test.py --base-url http://localhost:8251 --users 20 --seconds 30
python3 scripts/load_test.py --base-url http://localhost:8251 --ramp --users 50 --step 50 --max-users 400 [--json]
```

Drives a local instance with virtual users. Each registers a marked account (`loadtest-…`), logs in, and loops over a weighted mix of the calls the website and the Twitch panel make: season and weekly leaderboards, roster, schedule, players and the panel as reads, a card draw and a roster save as writes. It reports requests per second, error rate, and p50, p95 and p99 latency per endpoint.

- **`--ramp`** raises the user count by `--step` up to `--max-users`, runs each level for `--seconds`, and stops at the first level whose p95 is over 1 second or whose error rate is over 1%. That level is the limit.
- **It writes accounts and cards,** so the target must run on a throwaway copy of the database. It refuses a base URL that is not `localhost`, `127.0.0.1` or `::1` unless `--allow-remote` is given. Never point it at production.
- **`--think`** is the mean pause between one user's calls (default 1 second), so N users make about N requests per second until the server slows down.

### Starting the target instance

Rate limits have no off switch: they are settings read at import, and all virtual users share one IP. Start the target with them raised, on a copy of the database:

```
cd backend
DATABASE_URL=sqlite:////absolute/path/to/copy.db \
DEBUG=true TWITCH_LOCAL_DEV=true BACKGROUND_TASKS_ENABLED=false INITIAL_TOKENS=100000 \
RATE_LIMIT_GLOBAL=10000000/minute RATE_LIMIT_REGISTER=10000000/minute RATE_LIMIT_LOGIN=10000000/minute \
RATE_LIMIT_CARD_ACTION=10000000/minute RATE_LIMIT_CARD_ACTION_IP=10000000/minute \
RATE_LIMIT_ROSTER_MUTATION=10000000/minute RATE_LIMIT_TWITCH_ACTION=10000000/minute \
RATE_LIMIT_TWITCH_JOIN_IP=10000000/minute \
python3 -m uvicorn main:app --host 127.0.0.1 --port 8251
```

| Setting | Why |
|---|---|
| `RATE_LIMIT_GLOBAL`, `RATE_LIMIT_REGISTER`, `RATE_LIMIT_LOGIN`, `RATE_LIMIT_CARD_ACTION`, `RATE_LIMIT_CARD_ACTION_IP`, `RATE_LIMIT_ROSTER_MUTATION`, `RATE_LIMIT_TWITCH_ACTION`, `RATE_LIMIT_TWITCH_JOIN_IP` | The limits a single-IP test runs into. The script cannot read them, so its report only states that it assumes they were raised; requests refused with 429 are shown in the `refused` column |
| `INITIAL_TOKENS` | High, so the draws don't run out of tokens |
| `TWITCH_LOCAL_DEV=true` | The panel route accepts the test token (`--twitch-token`) |
| `BACKGROUND_TASKS_ENABLED=false` | No ingest or enrichment calls to outside services during the test |

Make the copy with SQLite's backup (`sqlite3 backup.db ".backup copy.db"`), not `cp` of a live file.

### Reading the result

The limit depends on the machine and the size of the database, so compare runs only on the same hardware and data. On a development machine (12 cores) with a development database of 25 accounts, the ramp served 150 users at about 90 requests per second with p95 under 1 second and passed the limit at 200 users. That figure checks the tool; it is not the production headroom.

## Review

`markdown/research/architecture-maturity-review.md` will hold the measured load of season 16, the target load for season 17 (3× the measured peak), the headroom, a verdict per area and a ranked list of off-season improvements with their GitHub issues.

**Status:** not written yet. It needs the usage report from a production backup of season 16, and the ramp run on a copy of that backup.
