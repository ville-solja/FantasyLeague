# Retroactive Bench Substitution

A one-off operator script that adds bench substitutions to weeks locked before benches were saved (#129); in practice Weeks 2–4. It rebuilds each user's bench only from cards that user provably had by that week. Resolves GitHub issue #189; plan: `markdown/plans/plan-issue-189-retroactive-bench-substitution.md`. The substitution rules are in [automatic-bench-substitution.md](automatic-bench-substitution.md).

It adds no endpoint, schema change, migration, env var or UI. Tokens, MVP bonuses and stored card points (`card_match_points`) are left alone; My Team, the leaderboards and the Weekly Report are computed live and show the change on their next load.

---

## How the bench is rebuilt

The app keeps no history of when a card was drawn, so the current collection can't stand in for an old bench. For week W and user U (`weeks.backfill_bench_candidates(db, week)`), a bench candidate:
- was on U's roster snapshot (`weekly_roster_entries`, `is_bench = 0`) in W or a week with an earlier `start_time`;
- isn't on U's roster in W;
- is still owned by U (`cards.owner_id`), and its player is active (`players.is_active = 1`). A refund deactivates the player and keeps `owner_id`, so this rule is what excludes refunded cards.

Only users with a roster in W get a bench. Candidates are ordered as the lock-time snapshot orders a bench (`weeks._slot_order`: `slot_index`, empty slots last, then card id): U's current bench cards first, then cards now on U's roster in slot order. The old bench order was never recorded.

`weeks.backfill_bench(db, week)` raises `ValueError` if the week already has `is_bench = 1` rows. Otherwise it inserts the candidates as `is_bench = 1` rows with `bench_order` 0..n and runs `run_substitutions` with its normal rules, which also writes its own `weekly_substitutions` audit entry and sets `substitutions_at`. It returns `(users, bench_cards, substitutions)`; the caller commits. A week without candidates is left untouched.

The first week, and any user who never changed their roster, gets no bench cards.

## Running it

```
bash scripts/backup-db.sh
cd backend
python scripts/backfill_bench.py --weeks "Week 2,Week 3,Week 4" --dry-run
python scripts/backfill_bench.py --weeks "Week 2,Week 3,Week 4"
```

In Docker: `docker compose exec <service> python scripts/backfill_bench.py …`. Weeks are given by label or id (`"Week 2,3"`); a week named twice runs once.

- **Which weeks run:** a week that is locked, past its substitution time (`end_time + SUBSTITUTION_DELAY_HOURS`) and without bench rows. Any other week prints `<label>: not locked, skipped`, `<label>: substitution time not reached, skipped` or `<label>: bench already saved, skipped`, and the other weeks still run.
- **Report:** per week, `<label>: N users get a bench, N bench cards, N substitutions`, then one line per user whose week points change, `  <username>: before -> after (+delta)`, largest change first. A week without candidates prints `<label>: no bench cards to add`. Points come from `routers.leaderboard.weekly_leaderboard`, which counts entries with `counted_roster_entry_sql()`, so they match the weekly leaderboard (testers and guest accounts are not listed, as on the leaderboard).
- **Dry run:** `--dry-run` prints `Dry run: nothing is written.` and the same report. Each week's work is done in the session and rolled back before any commit, so bench rows, audit log and `substitutions_at` are unchanged.
- **Apply:** each week is its own transaction: bench rows, substitution flags, `substitutions_at`, the `weekly_substitutions` entry and one `admin_bench_backfill` audit entry (`actor_username=script`, detail `id=… label=… users=… bench_cards=… substitutions=…`). A week without candidates writes nothing.
- **Exit code:** 1 when a named week doesn't exist (nothing is processed then) or a week fails (`<label>: failed (…), rolled back`; weeks already applied keep their result); 0 otherwise, including when weeks are skipped.
- **Second run:** every applied week now has bench rows, so it is skipped and nothing changes.
- **Undo:** restore the backup taken first.

## Code and tests

- `backend/weeks.py`: `backfill_bench_candidates`, `backfill_bench`.
- `backend/scripts/backfill_bench.py`: `main(argv=None) -> int` (argument parsing, eligibility, report, audit entries); it opens its session from `database.SessionLocal`.
- `backend/tests/test_issue_189_retroactive_bench_substitution.py`.
