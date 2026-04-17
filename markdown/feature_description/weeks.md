# Weeks & Leaderboards

The season is divided into weekly windows. Each week defines when roster changes freeze, which matches count toward scoring, and how users rank against each other.

## Week Structure

Weeks are anchored to the date set in `SEASON_LOCK_START` (ISO date string, must be a Sunday). Each week:

| Boundary | Time |
|---|---|
| Lock (roster freezes) | Sunday 23:59:59 UTC |
| Match window opens | Monday 00:00:00 UTC |
| Match window closes | Following Sunday 23:59:59 UTC |

Week rows are generated automatically, always keeping at least 4 weeks ahead of the current date. New weeks are added by the week maintenance background thread (runs every 5 minutes by default, configurable via `WEEK_CHECK_INTERVAL`).

## Week Locking

A week locks automatically when its match window opens (Monday 00:00 UTC). Locking is irreversible and has three effects:

1. **Roster snapshot** — Each user's current active roster (up to 5 cards) is copied into `WeeklyRosterEntry` records. This snapshot is immutable for the rest of the week and is used for all scoring calculations for that week.
2. **Week marked locked** — `weeks.is_locked = true`. The roster for that week can no longer be changed.
3. **Token grant** — Every registered user receives +1 token automatically.

Locking is idempotent: if the maintenance thread runs multiple times after a week's start time, the second run skips weeks that already have snapshots.

## Roster Scoring

Points for a week are calculated from the locked snapshot:

```
For each card in the user's WeeklyRosterEntry for that week:
  sum the fantasy_points of all player_match_stats
  where the match start_time falls within the week's [start_time, end_time]
  apply rarity bonus and card modifier bonuses
```

Only matches played during the week's window contribute. Matches outside the window (including those with a `week_override_id` pointing to a different week) do not count.

## Leaderboards

### Season Leaderboard (`GET /leaderboard/season`)
Aggregates points from all locked weekly roster entries across the entire season. Each user's score is the sum of their weekly points from all locked weeks combined.

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
| `SEASON_LOCK_START` | `2026-03-08` | First Sunday lock anchor date |
| `WEEK_CHECK_INTERVAL` | `300` | Seconds between maintenance checks |
