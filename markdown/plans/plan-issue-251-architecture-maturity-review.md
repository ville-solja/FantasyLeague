# Plan: Architecture Maturity Review

## Context
Issue #251: "Now with statistics on expected user load analyze the current structure and should there warranted improvements over the offseason." Season 16 has ended, so there is now a full season of real usage to size the system against. This plan produces a written review with measured numbers and a short, ranked list of off-season improvements. It builds two small tools to get the numbers. It changes no production behaviour.

**What is known today (2026-11-16):**
- **Structure:** one FastAPI process, one SQLite file, in-memory rate limits and caches, background loops in the same process (ingest poll, week maintenance, profile enrichment), one Docker container behind a reverse proxy. The single-process rule is documented ([Dependency Locking and Release Gating](../features/reference/dependency-locking.md), from the 2026-10-31 architecture review).
- **Size, from public endpoints:** 72 accounts on the season leaderboard and 85 players in season 16.
- **Not known yet:** the real request peaks (match nights, week locks, Twitch drops), soft-account and Twitch panel numbers, database growth per season, and how far the current setup is from its limit.
- **Existing tooling:** `scripts/bench_leaderboards.py` with a stored baseline, and `/systems-architect` for the structural review.

**Decisions** (change them in review if needed):
- **Measure first.** A usage report from the database gives the season's real load. A load test on a copy gives the headroom. The review judges the structure against both.
- **Target load:** season 17 is sized at 3× season 16's measured peak, and the review also states the load at which the current setup breaks. Change the factor in review if the expected growth differs.
- **Output is a document and issues.** The review lands in `markdown/research/`, and each warranted improvement becomes a GitHub issue. No refactor is done under this issue.
- **Read-only tools.** Both scripts only read; the load test runs against a local copy, never production.
- **No new runtime dependency.** The load test uses the standard library and `requests`, which is already a dependency.

Resolves GitHub issue #251.

## User Stories

### See the Season's Real Load
**User story**
As the operator, I want a report of season 16's usage from the database, so that the architecture is judged against real numbers.

**Acceptance criteria**
- **Run:** `python scripts/usage_report.py --db <path>` reads a database file (a backup works) and prints a report; `--json` writes the same numbers as JSON. It writes nothing to the database.
- **Accounts:** website accounts, Twitch soft accounts, accounts with at least one card, and accounts with a roster in each week.
- **Activity:** per week, the number of draws (`token_draw`, `token_booster_draw`) and logins (`user_login`) found in `audit_logs`, and the busiest hour and busiest minute of the season with their action counts. Roster saves write no audit row, so the report says they are not recorded instead of showing 0; rosters per week come from `weekly_roster_entries`.
- **Twitch:** channels, MVPs set, token drops and the largest presence pool (from `pool_size=` in the `twitch_token_drop` audit details, since `twitch_presence` holds only current heartbeats).
- **Data:** row counts of the largest tables and the database file size, with growth per week.
- **Privacy:** only counts; no usernames, emails or ids in the output.

### Know the Headroom
**User story**
As the operator, I want a repeatable load test of the hot endpoints, so that I know how far the current setup is from its limit.

**Acceptance criteria**
- **Run:** `python scripts/load_test.py --base-url http://localhost:8000 --users N --seconds S` drives a local instance with a mix of the hot read endpoints (leaderboards, roster, schedule, players, Twitch panel) and writes (draw, roster save) with test users it registers itself.
- **Refuses production:** it stops unless the base URL is localhost or `--allow-remote` is given.
- **Reports:** requests per second, error rate, and p50, p95 and p99 latency per endpoint; `--json` for the same numbers.
- **Steps:** a `--ramp` mode raises the users step by step and reports the level at which p95 passes 1 second or errors pass 1%.

### A Ranked List of Off-Season Improvements
**User story**
As the maintainer, I want a review that says which parts of the architecture are fine, which need work before season 17 and which can wait, so that the off-season goes to what matters.

**Acceptance criteria**
- **Document:** `markdown/research/architecture-maturity-review.md` holds the measured load, the target load and the headroom found.
- **Verdict per area:** process model and the single-process rule, SQLite (write contention, backups, size), background jobs, external services (OpenDota, Steam, Twitch, Toornament), caching and rate limits, deployment and recovery, observability, frontend delivery, and test and release tooling. Each gets "fine at target load", "fix before season 17" or "watch", with the evidence.
- **Ranked:** improvements are listed by risk and effort, each with the load at which it becomes necessary.
- **Issues:** each "fix before season 17" item has a GitHub issue, linked from the document.
- **Indexed:** the document is listed in `markdown/features/README.md`'s research row and the plan index.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `scripts/usage_report.py` | New: read-only usage numbers from a database file |
| `scripts/load_test.py` | New: local load test with a ramp mode |
| `backend/tests/test_issue_251_architecture_maturity_review.py` | Tests for the two scripts |
| `markdown/research/architecture-maturity-review.md` | The review (written after the numbers exist) |
| `markdown/features/reference/architecture-maturity-review.md` | Short pointer doc: how to run the tools, where the review is |

No migration, no env var, no production code change.

### Step 1 — Usage report
Open the database read-only (`sqlite3` URI with `mode=ro`). Derive activity from `audit_logs` (draws and logins; roster saves aren't audited), `weekly_roster_entries`, `cards`, `users.account_type`, `twitch_mvp`, `twitch_token_drops` and `twitch_presence`. Bucket audit timestamps by hour and minute for the peaks. Print counts only.

### Step 2 — Load test
Threads with `requests.Session`; each virtual user registers, logs in and loops over a weighted mix of calls. Read the endpoint list from the frontend's real calls so the mix is honest. Rate limits are in-memory and per user or IP, so run the target instance with the limits raised for the test. There is no on/off switch: the limits are the `RATE_LIMIT_*` settings read at import, so the pointer doc names the ones to raise, and the report says the limits were raised.

### Step 3 — Measure
Run the usage report on the latest production backup. Run the load test on a copy of it, on hardware comparable to production if possible, with `--ramp`. Record both outputs in the review.

### Step 4 — Review
Run `/systems-architect` and fold its findings into the document, judged against the measured and target load. Open one issue per "fix before season 17" item.

### Step 5 — Tests
- **Usage report:** on a seeded database the counts are right; the output has no username, email or id; the database is unchanged afterwards.
- **Load test:** refuses a non-local URL without `--allow-remote`; against a stub server it reports per-endpoint counts and percentiles; the ramp stops at the threshold.

## Verification
- The usage report on a production backup matches known numbers (72 accounts on the season leaderboard).
- The load test's ramp finds a clear limit on a local copy, and the same run twice gives similar numbers.
- The review names each area's verdict with evidence, and its issues exist.
- Manual: the operator supplies the production backup and, if available, the reverse proxy's request counts for a match night, to check the audit-log peaks against real traffic.
