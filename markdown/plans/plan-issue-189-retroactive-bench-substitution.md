# Plan: Retroactive Bench Substitution

## Context
Bench substitution (#129) only helps weeks locked after it shipped. It needs the bench saved at lock (`weekly_roster_entries.is_bench = 1`), and earlier weeks have no saved bench. On the first deploy, `due_substitutions` gave each of those weeks `substitutions_at` with 0 substitutions. Issue #189 asks for those weeks to get substitutions too. In practice that means Weeks 2–4. Benches are now saved at lock, so this is a **one-off data backfill**, run once by the operator with a script. It adds no feature to the app.

**The hard part:** the app keeps no history of when a card was drawn. `cards` has no acquisition time, and draws write no audit entry. The current collection can't be used as the old bench, because a card drawn in Week 5 would then score for Week 2. The only proof that a user owned a card in a given week is a lock-time snapshot: a card on that user's roster (`is_bench = 0`) in that week or an earlier one.

**Decisions** (agreed with the product owner):
- **Who qualifies for the bench:** for week W, a user's bench is the cards on that user's roster snapshot in any week up to and including W, but not on the roster in W. The card must still be owned by that user, and its player must still be active. Refunded cards (a refund deactivates the player and keeps `owner_id`) and transferred cards don't qualify.
- **Week 1 gets nothing:** it has no earlier week to prove ownership from. The same goes for users who never changed their roster.
- **Bench order:** the order the lock-time snapshot uses (`weeks._slot_order`), current bench cards first, then current roster cards in slot order. The old bench order was never recorded.
- **A script, not an app feature:** `backend/scripts/backfill_bench.py` is run once on the server, with a dry run first.
  - No admin UI, endpoint, schema change, migration or player-facing note.
  - **Undo:** restore the backup taken just before the run.
  - **Rerunning:** it refuses a week that already has bench rows, so a second run changes nothing.
- **What's left alone:** tokens, MVP bonuses and stored card points (`card_match_points`). Leaderboards, My Team and the Weekly Report are computed live, so they change on their next load.

Resolves GitHub issue #189.

## User Stories

### Operator Backfills the Bench for Earlier Weeks
**User story**
As the operator, I want to add bench substitutions to the weeks locked before benches were saved, so that players whose roster cards didn't play get points from their bench as in later weeks.

**Acceptance criteria**
- **Command:** `python scripts/backfill_bench.py --weeks "Week 2,Week 3,Week 4"`, run from `backend/`, for example `docker compose exec <service> python scripts/backfill_bench.py …`. Weeks are given by label or id.
- **Which weeks it processes:** only a week that is locked, past its substitution time (`end_time + SUBSTITUTION_DELAY_HOURS`) and without `is_bench = 1` rows. Any other week is skipped with the reason printed ("Week 5: bench already saved, skipped"), and the other weeks still run.
- **Dry run:** `--dry-run` prints per week:
  - the number of users who get a bench;
  - the number of bench cards and of substitutions;
  - one line per affected user with their username and week points before → after, largest change first.

  It writes nothing to the database.
- **Apply:** without `--dry-run`, each week is handled in its own transaction:
  - insert the bench rows (`is_bench = 1`, `bench_order` 0..n);
  - run `weeks.run_substitutions`;
  - write one `admin_bench_backfill` audit entry (`actor_username=script`, with `id`, `label`, `users`, `bench_cards` and `substitutions` in `detail`).

  It prints the same report as the dry run.
- **Exit code:** 1 when a named week doesn't exist (nothing is processed then) or a week fails (that week is rolled back, the others keep their result), 0 otherwise.
- **After applying:** a second run reports every week as skipped and changes nothing.

### Bench Uses Only Cards the User Provably Had
**User story**
As a player, I want a retroactive bench to use only cards I actually had that week, so that a card drawn later can't score for an earlier week, mine or anyone else's.

**Acceptance criteria**
- **Which cards qualify:** for week W and user U, a card is a bench candidate only when it appears in a `weekly_roster_entries` row with `user_id = U`, `is_bench = 0` and a week whose `start_time` ≤ W's `start_time`.
- **Exclusions:**
  - a card already on U's roster in W is not a candidate;
  - a card no longer owned by U, or whose player is inactive (`players.is_active = 0`), is not a candidate. A refund deactivates the player and leaves `owner_id` as it is, so the inactive-player rule is what excludes refunded cards.
- **Order:** candidates get `bench_order` in the same order the lock-time snapshot uses (`weeks._slot_order`: `slot_index`, empty slots last, then card id), with U's current bench cards first and current roster cards after them in slot order.
- **First week:** a week with no earlier locked week gets no bench cards; the report says "no bench cards to add".
- **Substitution rules:** `run_substitutions` applies its normal rules unchanged: a card whose player played is never replaced, a player is never counted twice, and each bench card fills one slot.
- **After applying:**
  - My Team shows the week's "Subbed in for {player}" and "Did not play" labels as for any later week;
  - the weekly and season leaderboards include the substituted points.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/weeks.py` | `backfill_bench_candidates(db, week)` returns `{user_id: [card_id, …]}` in bench order; `backfill_bench(db, week)` inserts the rows and runs `run_substitutions` |
| `backend/scripts/backfill_bench.py` | CLI: argument parsing, the eligibility checks, the dry run (the week's work rolled back before any commit), the report and the audit entries |
| `backend/tests/test_issue_189_retroactive_bench_substitution.py` | Tests |
| `markdown/features/reference/automatic-bench-substitution.md`, `markdown/features/reference/retroactive-bench-substitution.md` | Docs |

No endpoint, schema change, migration, env var or frontend change.

### Step 1 — Candidates (`weeks.py`)
```python
def backfill_bench_candidates(db, week) -> dict[int, list[int]]:
    """For each user with a roster in `week`: cards on that user's roster snapshot
    in `week` or an earlier one (by start_time), not on the roster in `week`, still
    owned by the user, player active. Ordered as the lock-time snapshot orders a bench
    (_slot_order), current bench cards before current roster cards."""
```
- **Roster snapshots:** one query over `weekly_roster_entries` joined to `weeks` (`start_time <= week.start_time`, `is_bench = 0`).
- **Current cards:** one query over `cards` joined to `players` for ownership and `is_active`; order with `_slot_order`, as `_snapshot_week` orders the bench.

### Step 2 — Apply (`weeks.py`)
`backfill_bench(db, week)`:
- raises `ValueError` when the week has bench rows;
- inserts the rows from the candidates;
- calls `run_substitutions`;
- returns `(users, bench_cards, substitutions)`. The caller commits.

### Step 3 — Script
- **Imports:** `backend/scripts/backfill_bench.py` imports from `backend/`, like the other scripts there, and opens a session from `database`.
- **Per week:** resolve the week by label or id, check eligibility, and read every user's week points before. Then call `backfill_bench` and read the points after, in the same uncommitted transaction.
- **Points:** read with the same counted-entries query the weekly leaderboard uses (`counted_roster_entry_sql()`), so the report matches what players will see.
- **Finish:** a dry run rolls back (`db.rollback()`, one week at a time). An apply adds the audit entry, then commits. A week with no candidates writes nothing.
- **Output:** plain text, one block per week.

### Step 4 — Docs and tests
**Docs:**
- `automatic-bench-substitution.md`: replace the paragraph that says pre-#129 weeks stay unchanged with a short "Retroactive bench (issue #189)" section that links the script doc.
- `retroactive-bench-substitution.md`: the rule, the command, the dry run and undo by backup.

**Tests:**
- **Candidates:**
  - a card first on the roster in a later week is excluded;
  - a refunded card, a card owned by someone else now, and a card of an inactive player are excluded;
  - the order follows the lock-time snapshot order (`_slot_order`), bench cards before roster cards;
  - the first week gets nothing.
- **Apply:**
  - substitutions are made, and the week points change;
  - a week with bench rows raises an error.
- **Script:**
  - a dry run writes nothing (row counts unchanged, no audit entry);
  - an apply writes the rows and the audit entry;
  - a second run skips;
  - an unlocked or not-yet-due week is skipped;
  - an unknown week exits 1.

## Verification
- **Backup:** on the server, `bash scripts/backup-db.sh` first.
- **Dry run:** run with `--dry-run` for "Week 2,Week 3,Week 4", and check the point changes are plausible (spot-check one user's week on My Team against the printed before and after).
- **Apply:** run without `--dry-run`. Weeks 2–4 on My Team show "Subbed in for …" where expected, and the weekly and season leaderboards have changed by the printed amounts.
- **Second run:** reports all three weeks as skipped.
- **Undo, if ever needed:** restore the backup from the first step.
