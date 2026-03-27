# Plan: Weekly Roster Locking

## Context

Currently the roster is time-agnostic: a user's active cards accumulate fantasy points across all matches ever played by those players, retroactively. This removes strategic meaning — there is no incentive to swap cards before a given week's matches.

The fix: introduce **weekly locks**. Each week ends on Sunday at midnight. At that moment the server snapshots every user's active roster. Points for that week are the sum of fantasy points earned by the snapshotted cards **during that week's matches only**. Users who make smart swaps before Sunday benefit from that decision.

### Season state as of 2026-03-27

- **Week 1** ended 2026-03-08 (Sunday) — **already passed, needs retroactive snapshot**
- **Week 2** ended 2026-03-15 — **already passed**
- **Week 3** ended 2026-03-22 — **already passed**
- **Week 4** ends 2026-03-29 — **in progress, editable until Sunday midnight**

Weeks 1–3 will be retroactively locked using each user's current active roster as the snapshot (the feature didn't exist before, so all users are on equal footing).

---

## Week Generation

Weeks are **auto-generated** from a configurable season start date. No admin action required.

### `SEASON_LOCK_START` env var

Default: `2026-03-08` (the first Sunday lock date, ISO format).

On startup the server generates all weeks from this anchor:
- **Week 1** start = Unix epoch 0 (captures all pre-season matches), end = `SEASON_LOCK_START` 23:59:59 UTC
- **Week 2** start = `SEASON_LOCK_START + 1 day` 00:00:00 UTC, end = `SEASON_LOCK_START + 7 days` 23:59:59 UTC
- **Week N** continues in 7-day increments, always ending on Sunday 23:59:59 UTC
- Generation extends **4 Sundays into the future** so upcoming weeks always exist

Weeks are inserted into the DB on startup if they don't already exist (idempotent). Labels are auto-assigned: "Week 1", "Week 2", etc.

Changing leagues (different seasons) means setting `SEASON_LOCK_START` to the new season's first Sunday.

---

## Auto-Locking

No admin lock button. The server locks weeks automatically.

### When auto-lock fires
1. **On startup** — scan all weeks where `end_time < now` and `is_locked = False`, lock each one
2. **On `POST /roster/{card_id}/activate` or `/deactivate`** — check if the editable roster is already past its lock time before allowing the change

### What locking does
For each unlocked week whose `end_time` has passed:
1. Set `week.is_locked = True`
2. For each user who has at least one card: snapshot their current `is_active = True` cards into `WeeklyRosterEntry`
3. Idempotent: skip users who already have entries for this week (safe to call multiple times)

### Retroactive locking (weeks 1–3)
These weeks will be locked on first startup after the feature is deployed. Their snapshots will reflect each user's active roster at deployment time. This is the fairest option since the feature didn't exist during those weeks.

---

## Schema

### `Week` table

```python
class Week(Base):
    __tablename__ = "weeks"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    label      = Column(String)    # "Week 1", "Week 2", ...
    start_time = Column(Integer)   # Unix timestamp — Monday 00:00 UTC (week 1 = 0)
    end_time   = Column(Integer)   # Unix timestamp — Sunday 23:59:59 UTC
    is_locked  = Column(Boolean, default=False)
```

No `lock_time` field — lock time is always `end_time`. The separation between "when does the week end" and "when does the roster lock" was unnecessary complexity; they are the same event.

### `WeeklyRosterEntry` table

```python
class WeeklyRosterEntry(Base):
    __tablename__ = "weekly_roster_entries"
    id      = Column(Integer, primary_key=True, autoincrement=True)
    week_id = Column(Integer, ForeignKey("weeks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    card_id = Column(Integer, ForeignKey("cards.id"))
```

One row per active card per user per week. Immutable after snapshot.

---

## Backend Changes

### `backend/models.py`
Add `Week` and `WeeklyRosterEntry`.

### `backend/main.py`

#### Week generation and auto-lock helpers

```python
def generate_weeks(db):
    """Insert missing Week rows from SEASON_LOCK_START through 4 Sundays ahead."""
    anchor = ...  # parse SEASON_LOCK_START env var as date, convert to Unix Sunday 23:59:59 UTC
    # Week 1: (0, anchor)
    # Week N: (anchor + (N-2)*7 days, anchor + (N-1)*7 days)
    # Insert until end_time > now + 4 weeks

def auto_lock_weeks(db):
    """Snapshot and lock all elapsed unlocked weeks."""
    now = int(time.time())
    unlocked = db.query(Week).filter(Week.end_time < now, Week.is_locked == False).all()
    for week in unlocked:
        _snapshot_week(db, week)
        week.is_locked = True
    db.commit()

def _snapshot_week(db, week):
    """Snapshot current active rosters into WeeklyRosterEntry for this week."""
    users = db.query(User).all()
    for user in users:
        existing = db.query(WeeklyRosterEntry).filter_by(week_id=week.id, user_id=user.id).first()
        if existing:
            continue
        active_cards = db.query(Card).filter_by(owner_id=user.id, is_active=True).all()
        for card in active_cards:
            db.add(WeeklyRosterEntry(week_id=week.id, user_id=user.id, card_id=card.id))
```

Both called in `lifespan` after seeding:
```python
generate_weeks(db)
auto_lock_weeks(db)
```

#### `GET /weeks` — public
Returns all weeks ordered by start_time, with lock status.
```json
[{"id": 1, "label": "Week 1", "start_time": 0, "end_time": 1741471199, "is_locked": true}, ...]
```

#### `GET /roster/{user_id}?week_id=X`

If `week_id` is provided:
- If the week is locked: return cards from `WeeklyRosterEntry` for that week, with `fantasy_points` filtered to `Match.start_time BETWEEN week.start_time AND week.end_time`
- If the week is not locked (current week): return current `is_active` cards with points earned since `week.start_time`

If `week_id` is omitted: return current editable roster with all-time points (existing behaviour preserved).

#### `GET /leaderboard/roster?week_id=X`

When `week_id` is given:
```sql
SELECT u.username,
       COUNT(wre.card_id) as locked_cards,
       COALESCE(SUM(pms.fantasy_points), 0) as week_value
FROM users u
LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id AND wre.week_id = :week_id
LEFT JOIN cards c ON c.id = wre.card_id
LEFT JOIN player_match_stats pms ON pms.player_id = c.player_id
LEFT JOIN matches m ON m.match_id = pms.match_id
    AND m.start_time BETWEEN :week_start AND :week_end
GROUP BY u.id, u.username
ORDER BY week_value DESC
```

When omitted: existing all-time query unchanged.

#### Roster lock enforcement

On `POST /roster/{card_id}/activate` and `/deactivate`:
```python
# Call auto_lock_weeks first to catch any newly elapsed weeks
auto_lock_weeks(db)
# Then check if there is currently no editable week (all weeks are locked)
# This would mean it's between Sunday midnight and the server generating next week —
# a window so small it's acceptable to allow edits and catch it on next request
```

---

## Frontend Changes

### My Team tab

Replace the static roster view with a week-aware view:

**Week selector dropdown** (populated from `GET /weeks`):
- All locked weeks: "Week 1 ✓", "Week 2 ✓", ...
- Current in-progress week: "Week N (live)"
- Selecting any option loads `GET /roster/{user_id}?week_id=N`

**Locked week view** (read-only):
- Table shows the snapshotted cards with that week's points
- No Bench/Activate buttons
- Banner: "Roster locked — Week N snapshot"

**Current week view** (editable until Sunday):
- Same table with Bench/Activate controls
- Shows points earned so far this week (since week start)
- Countdown or label: "Locks Sunday midnight"
- After Sunday passes (auto-locked): switches to read-only snapshot view automatically

**Editable roster** (always accessible):
- The current `is_active` roster is always the roster being prepared for the next lock
- When viewing a past locked week, the active roster panel is still shown below with a note: "Your roster for the upcoming week (Week N+1)"
- This allows users to review a past week and still manage future cards

### Leaderboard tab

**Week selector dropdown** (same `GET /weeks` source, shared fetch):
- "All time" (default) — existing behaviour
- "Week N ✓" (locked weeks)
- "Week N (live)" (current week, in-progress scores)

Selecting a week re-fetches `GET /leaderboard/roster?week_id=N`.

---

## Point Accumulation — What Changes

| View | Points shown | Source |
|---|---|---|
| All-time leaderboard (no week_id) | Sum of all fantasy_points ever for active cards | Existing behaviour, unchanged |
| Weekly leaderboard (week_id=N) | Sum of fantasy_points for locked roster, filtered to that week's matches | New |
| My Roster all-time (no week_id) | Sum of all fantasy_points for each active card | Existing, unchanged |
| My Roster weekly (week_id=N) | Sum of fantasy_points for that week's snapshot, filtered to week's matches | New |

The per-match `fantasy_points` stored on `PlayerMatchStats` never changes — it is always the raw match score. Weekly scoping is applied at query time using the `Match.start_time` filter.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SEASON_LOCK_START` | `2026-03-08` | ISO date of the first Sunday lock. Determines all week boundaries. Change for a new season. |

---

## What Does NOT Change
- `PlayerMatchStats.fantasy_points` — still a per-match raw score, never weekly
- The `is_active` flag on `Card` — still drives the editable roster
- All-time leaderboard and all-time roster when no `week_id` is given
- Admin cannot manually create or delete weeks — generation is fully automatic

---

## Critical Files
- `backend/models.py` — add `Week`, `WeeklyRosterEntry`
- `backend/main.py` — `generate_weeks()`, `auto_lock_weeks()`, `_snapshot_week()`; `GET /weeks`; update `GET /roster` and `GET /leaderboard/roster` with week_id param; enforce lock on activate/deactivate
- `frontend/index.html` — week selector in My Team and Leaderboard tabs
- `frontend/app.js` — `loadWeeks()`, week-aware `loadRoster()` and `loadRosterLeaderboard()`
- `.env.example` — document `SEASON_LOCK_START`

---

## Verification
1. On startup with no data, weeks 1–4 (and 4 future) are auto-generated in the DB
2. Weeks 1–3 are immediately auto-locked, creating `WeeklyRosterEntry` rows for all users with active cards
3. `GET /leaderboard/roster?week_id=1` returns scores scoped to week 1's match dates
4. `GET /leaderboard/roster` (no param) returns unchanged all-time scores
5. Week 4 is not yet locked; activate/deactivate still works
6. After 2026-03-29 23:59:59 passes: next startup or roster operation auto-locks week 4
7. Week selector in UI shows correct read-only vs editable state per week
