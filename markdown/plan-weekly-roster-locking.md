# Plan: Weekly Roster Locking

## Context
Currently the roster is time-agnostic: a user's active cards accumulate fantasy points across all matches ever played by those players, retroactively. This removes strategic meaning — there is no incentive to check upcoming matchups and swap cards before a given week's matches.

The fix: introduce a concept of **weeks** (each covering a set of match dates), let users manage their active roster up until a lock deadline, then snapshot that roster. Scoring for a week is the sum of fantasy points earned by locked cards **during that week's matches only**. Users who swap a card before the lock benefit from that decision.

---

## New Database Tables

### `Week` table (`weeks`)
```python
class Week(Base):
    __tablename__ = "weeks"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    label      = Column(String)    # e.g. "Week 1"
    start_time = Column(Integer)   # Unix timestamp — first match of the week
    end_time   = Column(Integer)   # Unix timestamp — last match of the week ends
    lock_time  = Column(Integer)   # Unix timestamp — roster edits blocked after this
    is_locked  = Column(Boolean, default=False)
```
Admin creates weeks manually via admin panel (label + start/end/lock times). Weeks can also be pre-populated from the schedule sheet's existing week structure as a convenience.

### `WeeklyRosterEntry` table (`weekly_roster_entries`)
```python
class WeeklyRosterEntry(Base):
    __tablename__ = "weekly_roster_entries"
    id      = Column(Integer, primary_key=True, autoincrement=True)
    week_id = Column(Integer, ForeignKey("weeks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    card_id = Column(Integer, ForeignKey("cards.id"))
```
Snapshot created when admin calls lock on a week. One row per active card per user. After lock, rows are immutable — the snapshot represents what each user submitted for that week.

---

## Backend Changes

### `backend/models.py`
Add `Week` and `WeeklyRosterEntry` classes (above).

### `backend/main.py`

#### New Pydantic models
```python
class CreateWeekBody(BaseModel):
    label: str
    start_time: int   # Unix
    end_time: int     # Unix
    lock_time: int    # Unix
```

#### New admin routes
- **`POST /weeks`** — Create a week. Returns `{id, label, ...}`.
- **`GET /weeks`** — List all weeks, newest first. Returns `[{id, label, start_time, end_time, lock_time, is_locked}]`.
- **`POST /weeks/{week_id}/lock`** (admin) — Lock the week:
  1. Set `week.is_locked = True`
  2. For each user with ≥1 active card: snapshot their `is_active=True` cards into `WeeklyRosterEntry`
  3. Idempotent: skip users who already have entries for this week

#### Updated roster endpoint
`GET /roster/{user_id}?week_id=X` — If `week_id` is provided, return the locked snapshot for that week (from `WeeklyRosterEntry`) with points filtered to matches within `week.start_time..week.end_time`. If omitted, return current editable roster (existing behaviour, all-time points).

#### Updated leaderboard endpoints
`GET /leaderboard/roster?week_id=X` — When `week_id` is given:
- Join `WeeklyRosterEntry` (for that week) → cards → players → player_match_stats
- Filter `PlayerMatchStats` by joining `Match` and checking `match.start_time BETWEEN week.start_time AND week.end_time`
- Group by user, sum fantasy_points → `weekly_value`

When `week_id` is absent: existing all-time behaviour unchanged.

#### Roster lock enforcement
`POST /roster/{card_id}/activate` and `deactivate`: if the current time is past `lock_time` of the active week (earliest non-locked week whose `lock_time` has passed), reject with `{"error": "Roster locked for current week"}`. The snapshot on `POST /weeks/{id}/lock` is the hard truth.

---

## Frontend Changes

### Admin tab
New "Manage Weeks" panel:
- Table of existing weeks: label, date range, lock time, status (Open / Locked)
- Form: label + start date + end date + lock datetime → "Create Week" button
- Per-row "Lock Week" button (only for unlocked weeks) → calls `POST /weeks/{id}/lock`

### Leaderboard tab
- Add a **week selector** dropdown populated from `GET /weeks` (plus "All time" at top)
- Selecting a week re-fetches `GET /leaderboard/roster?week_id=X` and updates the table
- Default on load: "All time"

### My Team tab
- Add a **week selector** dropdown (same list as leaderboards)
- Selecting a past locked week shows that week's snapshot (read-only)
- "Current (editable)" selection shows live roster (existing behaviour)
- When the current week's lock time has passed and the week hasn't been locked yet, show a banner: "Roster lock pending — admin will snapshot your current active cards"

---

## Critical Files
- `backend/models.py` — add `Week`, `WeeklyRosterEntry`
- `backend/main.py` — migrations, new routes, updated roster/leaderboard queries
- `frontend/index.html` — add Manage Weeks panel, week selector dropdowns
- `frontend/app.js` — `loadWeeks()`, `createWeek()`, `lockWeek()`, update `loadRoster()` and `loadRosterLeaderboard()` with week param

---

## What Does NOT Change
- `PlayerMatchStats.fantasy_points` stays as the per-match base score (no week concept in the stats table)
- All-time roster/leaderboard behaviour is preserved when no `week_id` is given
- The existing `is_active` flag still drives the editable roster; locking just snapshots it
- Schedule sheet week labels can be used as naming reference when admins create weeks, but weeks are created manually — no automatic sync

---

## Verification
1. Admin creates Week 1 with a date range covering a set of past ingested matches
2. Admin locks Week 1 — verify `WeeklyRosterEntry` rows created for each user
3. `GET /leaderboard/roster?week_id=1` returns weekly scores scoped to that week's matches
4. `GET /leaderboard/roster` (no param) returns unchanged all-time scores
5. `GET /roster/{user_id}?week_id=1` returns that user's locked snapshot for Week 1
6. Attempting to activate/deactivate a card after a week's `lock_time` returns an error
