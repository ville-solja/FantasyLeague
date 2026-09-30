# Weeks & Leaderboards

The season is divided into weekly windows. Each week defines when roster changes freeze, which matches count toward scoring, and how users rank against each other.

## Week Structure

Weeks are created manually by admins in the Week Management tab (Admin panel) — there is no
automatic week generation. An admin picks a start date and an end date; the backend derives:

| Boundary | Derivation |
|---|---|
| Start (`start_time`) | Start date, 03:00:00 UTC |
| End (`end_time`) | The day **after** the end date, 02:59:59 UTC |

The same 3-hour grace period is applied to both ends (not just the end): it means games starting
late in the evening on the chosen end date and running past midnight still count toward that
week, and — since a normal Monday-start week's `start_time` gets the same offset — a
Monday-to-Sunday week immediately followed by another Monday-start week never overlaps by
default. See `reference/admin-week-management.md`, `reference/week-boundary-formula-fix.md`,
and `reference/season-lifecycle.md`.

The background maintenance thread (runs every 5 minutes by default, configurable via
`WEEK_CHECK_INTERVAL`) only auto-locks weeks whose start time has passed — it never creates
new week rows.

## Week Locking

A week locks automatically once its own admin-set `start_time` has passed (checked by the
background maintenance thread — see Week Structure above; there is no fixed weekday or time-of-day
cadence, since weeks are created manually with arbitrary start dates). Locking is irreversible and
has three effects:

1. **Roster snapshot** — Each user's current active roster (up to 5 cards) is copied into `WeeklyRosterEntry` records. This snapshot is immutable for the rest of the week and is used for all scoring calculations for that week.
2. **Week marked locked** — `weeks.is_locked = true`. The roster for that week can no longer be changed.
3. **Token grant** — Every registered user receives +1 token automatically.

Locking is idempotent: `auto_lock_weeks()` only queries weeks with `is_locked = false`
(`backend/weeks.py`), so a week drops out of that query — and is never touched again — the
moment its lock commits, regardless of the thread's run frequency. `_snapshot_week()` separately
guards against double-snapshotting the same user within a single lock pass via an
already-snapshotted set, but that guard is not what makes re-runs across ticks safe; the
`is_locked` filter is.

## Roster Scoring

Points for a week are sums over the locked snapshot of each card's stored per-match points
(`card_match_points`, see [Stored Card Points](../reference/stored-card-points.md)):

```
For each card in the user's WeeklyRosterEntry for that week:
  for each stored card_match_points row for that card
  whose match counts for this week (week_override_id = week, or no override and
  start_time within [start_time, end_time]) and is not excluded from scoring:
    add its points
```

Each stored row is the card's points for one match: stat weights with card modifiers, plus
the MVP bonus when the player was that match's MVP, times the rarity bonus. The death term
is floored at 0 per match, so a week's value is always the sum of its matches.

Only matches assigned to the week contribute: those played during the week's window, or with a `week_override_id` pointing at it. Matches with a `week_override_id` pointing to a different week do not count. Exclusion and week assignment are applied when reading, so changing them updates totals immediately.

## Leaderboards

### Season Leaderboard (`GET /leaderboard/season`)
Aggregates points from all locked weekly roster entries across the entire season. Each user's score is the sum of their weekly points from all locked weeks combined. Each card chip carries `"scope": "season"` and shows the card's total over every locked week it was rostered in; the frontend labels it as season points.

### Weekly Leaderboard (`GET /leaderboard/weekly?week_id=N`)
Points for a single specified week only, using the snapshot for that week.

### Player Performance Leaderboard (`GET /leaderboard`)
Shows individual Dota players ranked by average fantasy points per match, across all ingested matches in the season. Not tied to user rosters.

### Roster Value Leaderboard (`GET /leaderboard/roster`)
Shows users ranked by the total all-time fantasy points of their currently active cards. Unlike the season leaderboard, this uses the current active roster rather than locked snapshots and is not scoped to any week.

### Top Single-Match Performances (`GET /top`)
Returns the 10 highest individual fantasy point scores from a single match across all ingested data, regardless of week or user roster. Each entry shows the player, their avatar, and the raw `fantasy_points` value for that match. No authentication required. Used by the frontend to surface standout performances on the leaderboard tab.

## Week Override

An admin can manually assign a match to a different week than the one its `start_time` falls in:

```
PUT /matches/{match_id}/week   body: {"week_id": N}
```

Setting `week_id` to `null` clears the override. The automated `POST /admin/sync-match-weeks` endpoint handles bulk assignment based on the schedule sheet.

## `GET /weeks`

Returns all week records sorted by start time:
```json
[
  {
    "id": 1,
    "label": "Week 1",
    "start_time": 1741560000,
    "end_time": 1742163599,
    "is_locked": true
  }
]
```

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `WEEK_CHECK_INTERVAL` | `300` | Seconds between auto-lock maintenance checks |
