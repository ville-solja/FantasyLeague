# Architecture Maturity Review

Issue #251, written 2026-11-17 after season 16. Plan: `markdown/plans/plan-issue-251-architecture-maturity-review.md`. Tools: [Architecture Maturity Review](../features/reference/architecture-maturity-review.md).

**Question:** is the current structure (one FastAPI process, one SQLite file, one container) enough for season 17, and what should the off-season be spent on?

**Answer:** yes. The measured headroom is about four times the season 17 target. One thing should be fixed before season 17: the backups live on the same disk as the database. Twitch is the part to watch, because its load grows with stream viewers, not with players.

---

## Measured load

Season 16, from the operator (2026-11-17) and the server's own backup list:

| Measure | Season 16 |
|---|---|
| Accounts on the season leaderboard | 72 |
| Players in the season | 85 |
| Streamers who asked for MVP approval | 5 |
| Twitch token drops | 0 (the extension was not approved, so no channel ran it) |
| Twitch soft accounts | 0 (same reason: Join is only in the extension) |
| Database file | 10.8 MB on 2026-11-17 |
| Database growth | 10.0 MB on 2026-11-04 to 10.8 MB on 2026-11-17: about 60 KB a day |
| Request peaks (match nights, week locks) | Not measured. The operator judges them not a concern |

The production database was not copied for this review. `scripts/usage_report.py` was checked on the development database instead, so the figures below test the tool, not season 16:

```
Accounts
  Website accounts:           25
  Twitch soft accounts:       0
Activity (from audit_logs)
  Roster saves:               not recorded (roster saves write no audit row)
  Busiest hour:               49 actions, starting 2026-08-19 06:00 UTC
  Busiest minute:             40 actions, starting 2026-09-18 07:06 UTC
Data
  File size:                  2568192 bytes
```

Run it on a production backup to replace the "not measured" rows: `python3 scripts/usage_report.py --db <backup file> --json` prints counts only.

## Target load

Season 17 is sized at **3× season 16's peak**. Season 16's request peak was not measured, so the peak is taken as its upper bound: every one of the 72 accounts active at the same time. The target is therefore **216 players active at once**.

A real player reads a leaderboard, the roster or the schedule about once every 10 seconds, so 216 players make about **22 requests a second**. The load test's virtual users are harder on the server: each sends a request about every second without pause.

Twitch is sized apart, because it scales with viewers. If the extension is approved, an open MVP vote on a channel with 300 viewers adds about **20 requests a second** (each open panel re-reads the vote every 15 seconds).

## Headroom

`scripts/load_test.py --ramp` against a local instance on a copy of the development database (12-core development machine; rate limits raised; 10 seconds per level; the mix is leaderboards, roster, schedule, players, the Twitch panel, card draws and roster saves):

```
   users    req/s err rate    p50 ms    p95 ms    p99 ms
      50    47.36      0.0       6.4      16.7      28.8
     100    91.02      0.0      11.1     122.1     376.4
     150    90.53      0.0     415.8     825.5    1106.2
     200    17.72   0.9123   10010.1   10010.9   10011.5
Limit: 200 users (p95 > 1 s).
```

- **Capacity:** about **90 requests a second** with p95 under 1 second. One process saturates there: going from 100 to 150 users adds no throughput, only waiting.
- **Against the target:** 22 requests a second from players is about a quarter of that capacity. A busy vote on a 300-viewer channel on top (20 requests a second) still leaves about half free.
- **Writes:** draws and roster saves were 15% of the requests, with no errors and no database lock timeouts below the limit.
- **Caveat:** production hardware is likely smaller than the development machine, and its database is about four times larger. Run the ramp once on a production-sized machine with a copy of a production backup before relying on the exact number.

## Verdict per area

| Area | Verdict | Evidence |
|---|---|---|
| Process model and the single-process rule | fine at target load | One uvicorn process; `_single_process_guard` refuses `WEB_CONCURRENCY` above 1, because the rate limits, caches, ingest lock and background threads assume one process. The process serves about 90 requests a second, four times the target. |
| SQLite (write contention, backups, size) | watch | Write contention: WAL mode with a 10-second busy timeout, and writes are rare (draws, roster saves, ingest); the load test's writes saw no lock errors. Size: 10.8 MB, growing about 60 KB a day, so a season adds a few MB. Backups: daily, kept 14 days, but on the same disk as the database (see deployment and recovery). |
| Background jobs | fine at target load | Ingest polling (every 15 minutes by default), live-game checks, week maintenance, profile enrichment and backups run as threads in the same process. Their work depends on the number of league matches, not players, so season 17's growth doesn't change it. |
| External services | watch | OpenDota: ingest with parse retries, and its last success and last problem are shown in Admin. Steam: sign-in and the live-game list (`STEAM_API_KEY`). Toornament: the schedule, cached. Twitch: no drops in season 16 because the extension was not approved; once it is, panel load grows with each channel's viewers, which no season 16 figure measures. |
| Caching and rate limits | watch | Rate limits and caches are in memory in the one process, which is right for one process. `GET /twitch/panel` is one shared body cached for 30 seconds. `GET /twitch/mvp-poll` is built per viewer and not cached; the MVP Vote panel re-read an open vote every 5 seconds, changed in this review to the full extension's 15 seconds. |
| Deployment and recovery | fix before season 17 | Issue [#254](https://github.com/ville-solja/FantasyLeague/issues/254). One container with `restart: unless-stopped` and a health check on `/health` that queries the database. Backups are written daily to `data/` on the same host and kept 14 days; a copy off the server exists only when an admin downloads one. Losing that disk or host loses the database and every backup together. |
| Observability | watch | Logs go to stdout; `/health` checks the database; Admin shows the Twitch status, OpenDota health and the audit log. There are no request counts or alerts, so this season's peaks are unknown. The reverse proxy's access log is the cheapest source if they are ever needed. |
| Frontend delivery | fine at target load | Static files are served by the same process with no build step; scripts are sent no-cache so a deploy reaches players at once. The pages are small and the load test's 90 requests a second include API calls only. |
| Test and release tooling | fine at target load | CI runs the backend suite (about 4,400 tests), Playwright UI tests and CodeQL on every PR; dependencies are hash-locked; images are published from CI; `scripts/backup-db.sh` runs before each deploy. |

## Ranked improvements

| # | Improvement | Risk | Effort | Needed at |
|---|---|---|---|---|
| 1 | Copy the daily backup off the server (another host or object storage), and test a restore from it ([#254](https://github.com/ville-solja/FantasyLeague/issues/254)) | High | Small | Now, at any load: 1 disk failure loses all 72 accounts' data |
| 2 | Before approving the extension for large channels, load-test `GET /twitch/mvp-poll` and `GET /twitch/panel` with many viewers, and cache the shared part of the poll view if needed | Medium | Small | About 300 viewers on one channel during a vote (20 requests a second) |
| 3 | Count requests per minute from the reverse proxy's access log on match nights | Low | Small | When players pass about 150 at once (half the measured limit) |
| 4 | Leave one process: shared rate-limit store, job runner and PostgreSQL | Low | Large | Above about 150 players active at once on production hardware (the measured limit), which is not expected in season 17 |

Item 1 is the only one to do before season 17. Items 2 and 3 are cheap and depend on the Twitch review and on growth. Item 4 is listed so the threshold is known; it is not recommended now.
