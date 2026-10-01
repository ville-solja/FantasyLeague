# Plan: Automatic Bench Substitution

## Context
Teams with big rosters rotate players, so a card on a locked roster can score nothing for a week because the player sat out. Players find this frustrating: nobody knows the line-ups in advance, and Kana Cards only sees who played once matches are ingested.

The issue thread settled on the Fantasy Premier League rule. **After the week has ended**, an active card whose player played **0 scored matches** that week is swapped for the **highest bench card whose player did play**. Bench order follows the My Team bench, left to right, which players already arrange with drag and drop (`cards.slot_index`). Scoring already counts matches per week window (`match_count`), so "did not play" is easy to detect.

Two gaps in the current data:
- **The bench isn't saved when a week locks.** `weeks._snapshot_week` writes only active cards to `weekly_roster_entries`. The bench and its order at lock time have to be kept too, or the substitution would use whatever the bench looks like later.
- **There's no record of a substitution.** The readers (My Team, the weekly and season leaderboards, End Season) decide which cards count from `weekly_roster_entries`, so substitutions have to be stored there.

**Assumptions:**
- **Timing.** Substitution runs once per week, `SUBSTITUTION_DELAY_HOURS` (default 24) after the week's `end_time`, so late-ingested and re-parsed matches are in. It runs in the week maintenance loop, before `generate_weekly_summaries`; that order matters only when both fall due in the same tick. Otherwise the Weekly Report opens at week end first, with a "substitutions pending" note, and its "on roster" marks update once substitutions run (product decision, 2026-10-01).
- **"Played"** means at least one match in the week's window (start/end or `week_override_id`) that counts for scoring (`scored_match_sql()`, so excluded matches don't count).
- **Empty slots stay empty.** Fewer than 5 active cards is the player's choice; only non-playing active cards are replaced, as in FPL.
- **The duplicate-player rule still applies.** A bench card of a player who is already counted on the roster for that week is skipped.
- **Corrections.** An admin can re-run a week's substitutions after fixing data (moving a match to another week, excluding a match). A re-run resets and recomputes deterministically, and stored card points (#141) need no change because they are per card per match.
- **Weeks locked before this release** have no bench snapshot, so no substitutions are made for them.

**Decisions confirmed with the product owner (2026-10-01):**
- The 24-hour delay is the default.
- No retroactive substitutions this season. Weeks locked before the release have no bench snapshot and are left as they are.
- Empty roster slots are **not** filled from the bench. Filling them would let late joiners score without setting a roster, and would remove the urgency to set one before the lock. Only cards whose player didn't play are replaced.

Resolves GitHub issue #129.

## User Stories

### Bench Saved at Lock
**User story**
As a player, I want my bench order saved when the week locks so that substitutions follow the order I set.

**Acceptance criteria**
- When a week locks, every card on each user's bench is saved to `weekly_roster_entries` with `is_bench = 1` and `bench_order` taken from the bench order on My Team (`slot_index` ascending with NULL last, then card id), alongside the active cards (`is_bench = 0`)
- Bench cards of deactivated players (`players.is_active = 0`) are not saved
- Saved bench entries don't count towards any points total unless substituted in
- Migration `029_weekly_roster_entries_substitution` adds `is_bench`, `bench_order`, `subbed_in`, `subbed_out` and `subbed_for_entry_id` to `weekly_roster_entries` and `substitutions_at` to `weeks`, all defaulting so existing rows remain active, non-substituted entries

### Automatic Substitution After the Week
**User story**
As a player, I want an active card whose player didn't play to be replaced by my highest bench card whose player did play so that rotation doesn't cost me the week.

**Acceptance criteria**
- `SUBSTITUTION_DELAY_HOURS` (default 24) after a locked week's `end_time`, its substitutions run once for every user
- Active cards are checked in roster slot order. Each one whose player has 0 scored matches in the week's window is marked `subbed_out`
- For each card marked `subbed_out`, the first bench entry (in `bench_order`) that qualifies is marked `subbed_in`: its player played at least one scored match that week, it isn't already subbed in, and its player isn't already counted on that week's roster
- If no bench card qualifies, the slot stays without points, as today
- An active card whose player played is never replaced, however few points it scored
- Each run writes one `weekly_substitutions` audit entry per week with the number of substitutions made
- Running it again for a week with no data changes gives the same result

### Points Count the Substituted Roster
**User story**
As a player, I want my week and season points to use the substituted roster so that the leaderboard reflects the swap.

**Acceptance criteria**
- A roster entry counts for a week when it is active and not `subbed_out`, or when it is `subbed_in`
- My Team for a locked week, the weekly leaderboard, the season leaderboard and End Season (`compute_season_standings`) all use that rule, as do the Weekly Report's "on roster" marks and the admin Week Management roster count (active entries only)
- Before substitution runs for a week, totals are exactly as today

### See What Was Substituted
**User story**
As a player, I want to see which cards were swapped so that a points change isn't a surprise.

**Acceptance criteria**
- My Team for a substituted week shows the subbed-in card on the roster with a "Subbed in for {player}" label, and the subbed-out card on the bench with a "Did not play" label
- `GET /roster/{user_id}?week_id=…` returns `subbed_in` / `subbed_out` per card and a `substitutions_done` flag for the week
- Before substitution has run, a locked week shows "Substitutions are made {N} hours after the week ends" under the roster
- The Weekly Report still opens when the week ends. Until that week's substitutions have run, a revealed week shows "Bench substitutions are made {N} hours after the week ends; roster marks may change.", and its "on roster" marks update once they run (`GET /weekly-summary/{week_id}` returns `substitutions_pending`)
- The How to Play Users subtab explains the rule in one bullet under Roster & Weekly Lock: bench order matters, left first

### Admin Re-Run
**User story**
As an admin, I want to re-run a week's substitutions after correcting match data so that the swaps match the final results.

**Acceptance criteria**
- `POST /admin/weeks/{week_id}/substitutions` (admin only) resets `subbed_in`, `subbed_out` and `subbed_for_entry_id` for that week and runs substitution again, returning the number of substitutions made
- It returns 409 for a week that isn't locked, or whose substitution time hasn't been reached
- It writes an `admin_substitutions_rerun` audit entry
- The admin Week Management table has a "Re-run substitutions" action on locked weeks once `end_time + SUBSTITUTION_DELAY_HOURS` has passed

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `WeeklyRosterEntry`: `is_bench`, `bench_order`, `subbed_in`, `subbed_out`, `subbed_for_entry_id`; `Week.substitutions_at` |
| `backend/migrate.py` | Migration `029_weekly_roster_entries_substitution` (five `weekly_roster_entries` columns plus `weeks.substitutions_at`, `PRAGMA table_info` guarded) |
| `backend/match_scoring.py` | `counted_roster_entry_sql()`, the shared counting condition next to `scored_match_sql()` |
| `backend/weeks.py` | `_snapshot_week` also saves the bench with order; new `run_substitutions(db, week)`, `due_substitutions(db)`, `substitution_delay_hours()`, `substitution_time(week)` |
| `backend/main.py` | Week maintenance loop runs due substitutions before `generate_weekly_summaries`; `SUBSTITUTION_DELAY_HOURS` |
| `backend/routers/admin_demo.py` | Setting the demo clock also runs due substitutions (before summaries) |
| `backend/routers/cards.py` | Locked-week roster uses the counting rule and returns the substitution flags, `subbed_in_for`, `substitutions_done`, `substitution_delay_hours` |
| `backend/routers/leaderboard.py` | Weekly and season readers (totals and card lists) use the counting rule |
| `backend/routers/weekly_summary.py` | Weekly Report "on roster" players use the counting rule |
| `backend/routers/admin_weeks.py` | `POST /admin/weeks/{week_id}/substitutions`; `GET /admin/weeks` `roster_count` counts active entries only, adds `substitutions_at` / `substitutions_due` |
| `frontend/app-roster.js`, `frontend/app-admin-weeks.js`, `frontend/index.html`, `frontend/style.css` | Labels, pending note, locked-week bench, admin action, How to Play bullet |
| `.env.example`, `markdown/features/core/weeks.md`, `markdown/features/core/admin.md`, `markdown/features/reference/commands.md`, `markdown/features/reference/admin-week-management.md`, `markdown/features/reference/demo-mode.md`, `markdown/ui_description/my-team.md`, `markdown/ui_description/admin.md` | Docs |
| `backend/tests/test_issue_129_automatic_bench_substitution.py` | Tests |

### Step 1 — Schema and lock snapshot
Add the columns (`is_bench`, `bench_order`, `subbed_in`, `subbed_out`, `subbed_for_entry_id` on `weekly_roster_entries`; `substitutions_at` on `weeks`) and migration 029. In `_snapshot_week`:
- save active cards as today, with `is_bench=0`, inserted in slot order (so entry id order is the lock-time slot order);
- then save each user's inactive cards whose player is active, ordered by `(slot_index IS NULL, slot_index, id)`, with `is_bench=1` and `bench_order=0..n`.

### Step 2 — Substitution
```python
def run_substitutions(db, week) -> int:
    reset subbed_in/subbed_out for the week
    played = {player_id with >=1 scored match in the week window}
    for each user with entries in the week:
        active = non-bench entries in card slot order
        bench  = bench entries by bench_order
        counted_players = {player of each active entry whose player played}
        for entry in active:
            if entry's player in played: continue
            entry.subbed_out = True
            sub = first bench entry not yet subbed_in whose player is in played
                  and not in counted_players
            if sub: sub.subbed_in = True; sub.subbed_for_entry_id = entry.id
                    counted_players.add(sub's player)
    record week.substitutions_at (or an audit entry) so it runs once
```
`due_substitutions` picks locked weeks where `now >= end_time + delay` and substitutions haven't run. Mark "has run" with a timestamp column on `weeks` (another migration line in 029) rather than inferring it from the audit log.

### Step 3 — Readers
Replace the plain `weekly_roster_entries` join with the counting condition `(wre.is_bench = 0 AND wre.subbed_out = 0) OR wre.subbed_in = 1` in every reader that sums card points per week or season. Use one shared SQL helper (`counted_roster_entry_sql()`) next to `scored_match_sql()` so the rule lives in one place. The same helper also applies to the season leaderboard's DISTINCT (user, card) list and the Weekly Report's "on roster" players; `GET /admin/weeks` `roster_count` counts `is_bench = 0` rows. Setting the demo clock runs due substitutions before the Weekly Report pass, like the maintenance loop.

### Step 4 — UI and admin
- My Team shows the labels and the pending note.
- The admin weeks table gets the re-run action, through `adminFetch` (no re-auth needed, since it isn't destructive).
- Add the How to Play bullet.

### Step 5 — Docs
Update `core/weeks.md` (lock snapshot, the substitution rule, timing), the UI descriptions, `.env.example` and the feature doc.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_129_automatic_bench_substitution.py tests/test_migrate.py tests/test_issue_141_stored_card_points.py -v`, then the full suite.
- A user with active A (played), B (0 matches) and bench C (played), D (played): after the delay, B is subbed out and C subbed in. Week points = A + C.
- Bench C didn't play but D did: D comes in.
- Bench C is the same player as active A (a duplicate): skipped.
- No eligible bench card: B stays out and the total is unchanged.
- Before the delay, totals and My Team equal today's behaviour. After it, the weekly leaderboard, season leaderboard and My Team all agree.
- Moving B's player's match into the week and re-running: no substitution, and B counts again.
- A week locked before migration 029 has no bench rows and no substitutions.
- Migration 029 on a copy of the production database: existing entries stay active and unchanged.
- Manual on test.kana-cards.com: bench a card of a player you know sat out, put a playing card first on the bench, and check the swap the day after the week ends.
