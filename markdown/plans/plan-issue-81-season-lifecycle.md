# Plan: Season Lifecycle Management

## Context

Moving between seasons currently requires env var edits, container restarts, and manual DB
surgery — and purging the old season's league data silently destroys the season leaderboard,
because season standings are computed live from match stats. This plan makes the full season
lifecycle admin-driven: an **End Season** action archives final standings before anything is
deleted, a **Season Reset** clears per-season data while retaining user accounts, and week
creation becomes fully manual (date-only inputs) so the auto-generation loop and its
`SEASON_LOCK_START`/`SEASON_END` env vars are retired entirely. League ingestion is already
admin-managed via monitored leagues; the `AUTO_INGEST_LEAGUES` bootstrap env var is retired
at the same time.

Decisions confirmed with the product owner:
- Archive captures **final standings only** (username, points, rank per user)
- Archived seasons are visible in **both** the Leaderboard tab (Past Seasons) and the Profile view
- Week creation becomes **fully manual** — the background generator is removed, auto-lock stays
- `SEASON_LOCK_START` and `SEASON_END` env vars are **retired**

Assumption (flagged for review): Season Reset restores every user's token balance to
`INITIAL_TOKENS`, so each season starts with a fresh economy. Cards are deactivated, not
deleted, preserving historical ownership.

Resolves GitHub issue #81.

---

## User Stories

### End Season Archive
**User story**
As an admin, I want a one-click "End Season" action that archives the final season standings
so that season history survives the data purge that follows.

**Acceptance criteria**
- Admin provides a season label (e.g. "Season 15") and triggers `POST /admin/season/end`
- The current season leaderboard (username, total points, rank) is snapshotted into a
  `season_archive` table
- Tester accounts are excluded from the archive, matching live leaderboard behaviour
- Re-archiving with the same label returns 409 rather than duplicating rows
- The action is logged to the audit log as `admin_season_archived`

---

### Season Reset
**User story**
As an admin, I want a season reset action that clears all per-season data so that the next
season starts from a clean slate without touching user accounts.

**Acceptance criteria**
- `POST /admin/season/reset` deletes: all matches, player match stats, match bans, weeks,
  weekly roster entries, Twitch MVP rows, and Twitch token drop records
- All cards are set inactive; user accounts, tags, and audit logs are retained
- Every user's token balance is reset to `INITIAL_TOKENS`
- Monitored leagues are unmonitored (admin adds the new season's league IDs when ready)
- The endpoint refuses to run (409) if the current season has unarchived locked weeks —
  the admin must run End Season first or pass an explicit `force` flag
- The action is logged as `admin_season_reset` with a summary of deleted row counts

---

### Past Seasons Visibility
**User story**
As a player, I want to see past season results in the leaderboard and my own placements on
my profile so that season achievements are not lost when a new season starts.

**Acceptance criteria**
- `GET /leaderboard/seasons` lists archived season labels with dates
- `GET /leaderboard/seasons/{season_id}` returns the archived standings table
- The Leaderboard tab shows a "Past Seasons" selector when at least one archive exists
- `GET /profile/{user_id}` includes a `past_seasons` array (label, points, rank)
- The Profile view renders past placements (e.g. "Season 15 — 3rd, 1240 pts")

---

### Manual Week Creation with Date-Only Inputs
**User story**
As an admin, I want to create weeks by picking start and end dates only so that week setup is
quick and the end time automatically accounts for matches running past midnight.

**Acceptance criteria**
- The Week Management create/edit forms use date inputs (no time component)
- Backend derives `start_time` as 00:00:00 UTC on the start date
- Backend derives `end_time` as 03:00:00 UTC on the day **after** the end date, so games
  extending past midnight still count toward the week
- Existing validation holds: end must be after start; editing/deleting locked weeks stays blocked
- Weeks are no longer generated automatically — the background loop only auto-locks

---

### Retire Season Env Vars
**User story**
As an operator, I want season boundaries and league selection managed entirely in the admin
UI so that moving between seasons requires no env edits or redeploys.

**Acceptance criteria**
- The week maintenance loop no longer calls `generate_weeks`; `SEASON_LOCK_START` and
  `SEASON_END` parsing is removed
- `AUTO_INGEST_LEAGUES` startup seeding is removed; monitored leagues are managed solely via
  the existing admin endpoints
- `.env.example` and docs no longer list the three retired variables
- Existing deployments with the vars still set start up cleanly (vars are simply ignored)

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New `SeasonArchive` table (new table — no migration entry needed) |
| `backend/routers/admin.py` | `POST /admin/season/end`, `POST /admin/season/reset`; fix `_audit` after-commit bug in `purge_league_data`; date-only week create/edit handling |
| `backend/routers/leaderboard.py` | `GET /leaderboard/seasons`, `GET /leaderboard/seasons/{season_id}`; extract season leaderboard computation into a reusable helper |
| `backend/routers/profile.py` | Add `past_seasons` to `GET /profile/{user_id}` |
| `backend/weeks.py` | Remove `generate_weeks`, `_parse_season_lock_anchor`, `_parse_season_end`; keep `auto_lock_weeks` |
| `backend/main.py` | Remove `generate_weeks` call from maintenance loop; remove `AUTO_INGEST_LEAGUES` seeding |
| `frontend/app-admin.js` | Season lifecycle panel (Settings tab); date-only week form handling |
| `frontend/app-leaderboard.js` | Past Seasons selector and archived table rendering |
| `frontend/app-profile.js` | Past season placements line |
| `frontend/index.html` | Season lifecycle section in Settings tab; week form date inputs; Past Seasons UI |
| `.env.example` | Remove `SEASON_LOCK_START`, `SEASON_END`, `AUTO_INGEST_LEAGUES` |
| `backend/tests/test_weeks.py` | Remove `generate_weeks` tests; keep auto-lock coverage |

### Step 1 — SeasonArchive model

```python
class SeasonArchive(Base):
    __tablename__ = "season_archive"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    season_label = Column(String, nullable=False)
    user_id      = Column(Integer, ForeignKey("users.id"))
    username     = Column(String, nullable=False)   # denormalised: survives renames
    points       = Column(Float, nullable=False)
    rank         = Column(Integer, nullable=False)
    archived_at  = Column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint('season_label', 'user_id'),)
```

New table via `Base.metadata.create_all()` — no `migrate.py` entry required.

### Step 2 — Extract season leaderboard helper

Refactor the body of `season_leaderboard` in `leaderboard.py` into
`compute_season_standings(db) -> list[dict]` so both the live endpoint and the archive
action share one implementation.

### Step 3 — End Season endpoint

`POST /admin/season/end` with body `{"season_label": "Season 15"}`:
1. 409 if any `season_archive` rows already exist with that label
2. Call `compute_season_standings(db)`, rank by points descending
3. Insert one `SeasonArchive` row per user
4. `_audit(...)` **then** `db.commit()`
5. Return `{"season_label", "archived_users": N}`

### Step 4 — Season Reset endpoint

`POST /admin/season/reset` with body `{"force": false}`:
1. If locked weeks exist and no archive was created since the newest locked week — 409
   with hint "Run End Season first or pass force=true"
2. Delete: `player_match_stats`, `match_bans`, `matches`, `weekly_roster_entries`, `weeks`,
   `twitch_mvp`, `twitch_token_drops`
3. `UPDATE cards SET is_active = 0`; `UPDATE users SET tokens = INITIAL_TOKENS`
4. Unmonitor all leagues
5. Audit `admin_season_reset` with per-table counts, then commit
6. Return the counts

### Step 5 — Remove week auto-generation and env seeding

- `weeks.py`: delete `generate_weeks`, `_parse_season_lock_anchor`, `_parse_season_end`
- `main.py`: maintenance loop body becomes auto-lock only; remove `_seed_monitored_leagues`
  call and `AUTO_INGEST_LEAGUES` read (`_seed_monitored_leagues` itself can be deleted)
- Update `test_weeks.py` accordingly

### Step 6 — Date-only week forms

- `POST /admin/weeks` and `PATCH /admin/weeks/{id}` accept `start_date` / `end_date`
  (ISO dates) alongside the existing timestamp fields for backward compatibility
- Derivation: `start_time = start_date 00:00:00 UTC`, `end_time = (end_date + 1 day) 03:00:00 UTC`
- Frontend week forms switch `datetime-local` inputs to `date` inputs

### Step 7 — Past Seasons UI

- Leaderboard tab: fetch `GET /leaderboard/seasons`; when non-empty show a selector that
  loads `GET /leaderboard/seasons/{id}` into the standard leaderboard table layout
- Profile: render `past_seasons` lines under the existing profile info

### Step 8 — Season lifecycle admin panel

In the Settings tab: a "Season" section with the End Season form (label input + button),
the Reset button (with a type-to-confirm popup — destructive action), and a table of
existing archives.

## Verification

- End-to-end: play through archive → reset → create new week → add monitored league →
  verify clean state and archived standings intact
- `POST /admin/season/end` twice with the same label → second returns 409
- `POST /admin/season/reset` without prior archive → 409; with `force=true` → succeeds
- After reset: users retain accounts/tags, tokens equal `INITIAL_TOKENS`, cards inactive,
  no weeks/matches/stats remain, no league is monitored
- Archived standings match the live leaderboard as computed immediately before archiving
- Week created via date inputs: start 00:00 UTC, end 03:00 UTC the day after the chosen end date
- App starts cleanly with `SEASON_LOCK_START`/`SEASON_END`/`AUTO_INGEST_LEAGUES` still present
  in the environment (ignored) and with them absent
- Non-admin requests to all new endpoints return 403
