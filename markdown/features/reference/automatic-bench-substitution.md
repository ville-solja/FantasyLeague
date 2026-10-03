# Automatic Bench Substitution

After a week ends, any active card whose player didn't play is replaced by the player's highest bench card whose player did, following the Fantasy Premier League rule. Resolves GitHub issue #129; plan: `markdown/plans/plan-issue-129-automatic-bench-substitution.md`.

---

## How it works

1. **At lock** (`weeks._snapshot_week`): the active roster is saved to `weekly_roster_entries` with `is_bench = 0`, inserted in roster slot order (`slot_index`, then card id). The bench is saved with `is_bench = 1` and `bench_order` 0..n in its My Team order (left first: `slot_index IS NULL`, `slot_index`, card id). Bench cards of deactivated players (`players.is_active = 0`) and unowned cards are left out.
2. **`SUBSTITUTION_DELAY_HOURS` after the week ends** (`weeks.due_substitutions`, called by the week maintenance loop after `auto_lock_weeks` and before `generate_weekly_summaries`; the order matters only when both fall due in the same tick): every locked week with `end_time + delay <= now` and no `weeks.substitutions_at` runs `weeks.run_substitutions(db, week)` once.
3. **`run_substitutions`** first resets `subbed_in`, `subbed_out` and `subbed_for_entry_id` for the week. "Played" means at least one match in the week's window (start/end, or `week_override_id`) that passes `scored_match_sql()`. For each user, active entries are checked in snapshot (slot) order. An entry whose player didn't play is marked `subbed_out`; the first bench entry by `bench_order` whose player played, that isn't already subbed in and whose player isn't already counted on the roster, is marked `subbed_in` with `subbed_for_entry_id` pointing at the replaced entry. It sets `weeks.substitutions_at`, writes one `weekly_substitutions` audit entry and returns the number of substitutions.
4. **Counting:** an entry counts when `(is_bench = 0 AND subbed_out = 0) OR subbed_in = 1`. The condition lives in `match_scoring.counted_roster_entry_sql()` and is used by My Team (`routers/cards.py`, week points and season points), the weekly and season leaderboards and End Season (`routers/leaderboard.py`, including the card chip lists), and the Weekly Report's "on roster" marks (`routers/weekly_summary.py`). `GET /admin/weeks` `roster_count` counts active entries (`is_bench = 0`) only.
5. If no bench card qualifies, the slot scores nothing, as before. Cards whose player played are never replaced, however few points they scored. Empty roster slots are never filled from the bench.

Stored card points (`card_match_points`, issue #141) are per card per match, so substitution and re-runs never touch them; only the set of counted entries changes.

Weeks locked before this feature have no saved bench rows. `run_substitutions` leaves such a week unchanged (no `subbed_out` marks either) and only records `substitutions_at`. On the first deploy, `due_substitutions` therefore processes every such past locked week once: it sets `substitutions_at` and writes a `weekly_substitutions` audit entry with `substitutions=0`, without changing any flags. The same happens for a week in which no user had a bench.

Active cards are saved at lock whatever their player's status, so an active card of a deactivated player is saved as active and subbed out by the normal rule when its player played no scored match.

**Weekly Report.** The report opens when the week ends, which is normally before substitutions run. Until they run (`weeks.substitutions_at` is null), `GET /weekly-summary/{week_id}` returns `substitutions_pending: true` and the revealed report shows the note "Bench substitutions are made {N} hours after the week ends; roster marks may change." Its "on roster" marks use the counted entries, so they update once substitutions have run. The maintenance loop calls `due_substitutions` before `generate_weekly_summaries`, which matters only when both fall due in the same tick.

Demo Mode: `POST /admin/demo/clock` runs `due_substitutions` synchronously after `auto_lock_weeks` and before `generate_weekly_summaries`.

## Schema

Migration `029_weekly_roster_entries_substitution` (`backend/migrate.py`):

| Table | Column | Type | Default |
|---|---|---|---|
| `weekly_roster_entries` | `is_bench` | BOOLEAN NOT NULL | 0 |
| `weekly_roster_entries` | `bench_order` | INTEGER | NULL |
| `weekly_roster_entries` | `subbed_in` | BOOLEAN NOT NULL | 0 |
| `weekly_roster_entries` | `subbed_out` | BOOLEAN NOT NULL | 0 |
| `weekly_roster_entries` | `subbed_for_entry_id` | INTEGER | NULL (on a subbed-in entry: the subbed-out entry it replaced) |
| `weeks` | `substitutions_at` | INTEGER | NULL (when substitutions last ran) |

Existing rows read as active, non-substituted entries.

## Endpoints

### `POST /admin/weeks/{week_id}/substitutions`
Admin only (`require_admin`); no re-auth, since the result is deterministic from the snapshot and match data. Resets and re-runs the week's substitutions after data corrections (moving a match to another week, excluding a match). Returns `{"week_id", "substitutions", "substitutions_at"}`. 404 for an unknown week; 409 when the week isn't locked or `end_time + SUBSTITUTION_DELAY_HOURS` hasn't been reached. Writes `weekly_substitutions` and `admin_substitutions_rerun` audit entries.

### `GET /roster/{user_id}?week_id=…` (extended)
Every card carries `subbed_in`, `subbed_out` and `subbed_in_for` (the replaced card's player name, or null). For a locked week, `active` holds the counted entries (a subbed-in card takes the replaced card's `slot_index`) and `bench` the rest (subbed-out cards first, then the saved bench by `bench_order`). The response adds `substitutions_done` (also inside `week`) and `substitution_delay_hours`.

### `GET /weekly-summary/{week_id}` (extended)
Adds `substitutions_pending` (true while `weeks.substitutions_at` is null), `substitutions_at` (unix seconds or null) and `substitution_delay_hours`. Players' `on_roster` uses `counted_roster_entry_sql()`. The same fields come back from `POST /weekly-summary/{week_id}/reveal`.

### `GET /admin/weeks` (extended)
Each row adds `substitutions_at` and `substitutions_due` (locked and past the substitution time); the admin table shows **Re-run substitutions** on due weeks.

## UI

- My Team: "Subbed in for {player}" on the subbed-in card, "Did not play" on the subbed-out card (on the locked week's bench), and "Substitutions are made {N} hours after the week ends" under a locked week's roster until substitutions have run. See `markdown/ui_description/my-team.md`.
- Weekly Report: "Bench substitutions are made {N} hours after the week ends; roster marks may change." in the My roster column header of a revealed week until substitutions have run. See `markdown/features/core/weekly-summary.md`.
- Admin, Week Management: **Re-run substitutions** button. See `markdown/ui_description/admin.md`.
- How to Play, Users subtab, Roster & Weekly Lock: one bullet explaining the rule and that the leftmost bench card comes in first.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SUBSTITUTION_DELAY_HOURS` | `24` | Hours after a week's end before substitutions run, so late matches are ingested first. Read at call time. |
