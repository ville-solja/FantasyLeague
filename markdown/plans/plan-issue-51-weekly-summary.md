# Plan: Weekly Summary Report

## Context
After a week's scoring window closes, users have no dedicated way to review what actually
happened — which matches were played, who the MVPs were, and how many points their roster
earned — without piecing it together from the leaderboard and My Team tab. This plan adds a
"Weekly report" popup, similar in spirit to the Battle Report popup in the Dota 2 client: a
button in the corner of the UI that opens a per-week tabbed view, initially showing only
matches/teams/VOD links, with a "Reveal results" button that permanently unlocks the full
breakdown (players, MVP highlight, points earned) for that user and that week.

The originating issue proposed generating the summary on a fixed "every Monday at 06:00" cron.
That was overridden in review: this codebase's weeks are admin-defined and do not always
align to calendar weeks (e.g. a compressed finals week), and week boundaries already carry a
grace period past midnight for matches to finish (see `backend/routers/admin_weeks.py`'s
`_derive_week_times`, which sets `end_time` to `end_date + 1 day @ 03:00 UTC`). So summary
generation is instead driven by each `Week`'s own `end_time` passing, using the same
background check that already runs `auto_lock_weeks` (`backend/weeks.py`,
`_week_maintenance_loop` in `backend/main.py`) — this way irregular weeks and the existing
grace period are handled uniformly with no separate schedule to keep in sync.

*Resolves GitHub issue #51.*

## User Stories

### View the Weekly Report
**User story**
As a user, I want to open a "Weekly report" button and see a tab per finished week showing
that week's matches, so I can review the tournament results at a glance.

**Acceptance criteria**
- A "Weekly report" button is shown in a fixed corner of the UI, visible whenever the user is
  logged in
- Clicking it opens a popup with one tab per week that has a generated summary, labeled by
  week number/label, defaulting to the most recent week's tab
- Weeks with no generated summary yet do not appear as tabs — tabs are populated as the
  season progresses, not shown in advance
- Each week's tab shows its matches grouped by series (matches between the same two teams
  clustered together), each match's two team names and logos, and a VOD link where one has
  been set — with the winning team visually highlighted
- Before the user has revealed that week's results, no player names, points, or MVP
  information are shown — only the fields above

### Reveal Full Match Results
**User story**
As a user, I want to click "Reveal results" on a week's tab to see the full player-level
breakdown, so that I control when I see the outcome instead of it being shown immediately.

**Acceptance criteria**
- Each not-yet-revealed week tab shows a "Reveal results" button
- Clicking it permanently reveals, for that week: every player in each match grouped under
  their team, the match's MVP player with a highlighted portrait, and a points-earned number
  under each player's portrait
- The points-earned number is shown in a neutral/grey color for players not on the viewing
  user's roster that week, and in an accent color for players who were on it
- Reveal state is per-user and per-week: one user revealing a week does not reveal it for any
  other user, and revealing one week does not reveal any other week
- Reopening the popup later (same session or after logging back in) shows previously revealed
  weeks already revealed, without needing to click "Reveal results" again

### New Report Highlight
**User story**
As a user, I want a visual cue on the Weekly report button when a new week's report becomes
available, so I notice it without having to check manually.

**Acceptance criteria**
- The Weekly report button shows a highlight/badge once a new week's summary has been
  generated and the current user has not yet opened the report popup since then
- Opening the report popup clears the highlight, regardless of whether the user reveals any
  week's results while it's open
- The highlight reappears the next time a further week's summary is generated, following the
  same per-user "not opened since" rule

### Automatic Weekly Summary Generation
**User story**
As the system, I want to mark a week's summary as available as soon as that week's scoring
window has actually closed, so reports reflect complete results regardless of whether a week
maps to a calendar week.

**Acceptance criteria**
- A week becomes available in the Weekly Report once `now >= week.end_time` — the same
  boundary (including its grace period) used by `auto_lock_weeks` — not a fixed calendar
  schedule
- The check runs from the existing week-maintenance background loop, so it applies uniformly
  to regular weeks and irregular ones (e.g. a finals week with a short window)
- Re-running the check after a week is already marked available does not re-trigger or
  duplicate anything (idempotent, matching the existing `auto_lock_weeks` pattern)
- A week with zero matches still becomes available (shown as an empty-state tab) rather than
  never appearing in the report

### Admin: Attach VOD Links to Matches
**User story**
As an admin, I want to attach a caster's VOD link to a match after the fact, so viewers can
find the recording from the Weekly Report.

**Acceptance criteria**
- Admin can set, edit, or clear a VOD URL on any match from the existing admin match tooling
- An invalid (non-URL) value is rejected with a clear error; clearing is always allowed
- Once set, the VOD link appears next to that match in the Weekly Report for every user,
  including weeks whose summary was generated before the link was added
- Clearing the VOD URL removes the link from the report without affecting anything else in
  that week's summary

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | Add `vod_url` column to `Match`; add `WeeklySummary` (readiness marker), `WeeklySummaryReveal`, `WeeklySummarySeen` models |
| `backend/migrate.py` | Add a numbered migration for `Match.vod_url` (new column on an existing table — required per this repo's schema-migration rule) |
| `backend/weeks.py` | Add `generate_weekly_summaries(db)`, following the same idempotent, `end_time`-driven shape as `auto_lock_weeks` |
| `backend/main.py` | Call `generate_weekly_summaries(db)` from `_week_maintenance_loop` alongside `auto_lock_weeks(db)` |
| `backend/routers/admin_matches.py` | Add `PATCH /admin/matches/{match_id}/vod` |
| New: `backend/routers/weekly_summary.py` | `GET /weekly-summary` (list + unseen flag), `GET /weekly-summary/{week_id}` (content, reveal-gated), `POST /weekly-summary/{week_id}/reveal`, `POST /weekly-summary/seen` |
| `backend/main.py` | Mount the new `weekly_summary` router |
| New: `frontend/app-weekly-summary.js` | Fetch/open/reveal logic for the popup, following the existing `app-*.js` per-concern split |
| `frontend/index.html` | Weekly report button + popup modal (tabs, series-grouped match rows, Reveal button) |
| `frontend/app-globals.js` / `frontend/app-init.js` | Check for an unseen summary on login/init, same place `checkNotifications()`/`claimTokenEvents()` are called |
| `frontend/app-admin.js` + admin matches table markup | VOD URL input next to each match row |

### Step 1 — Models

Add to `backend/models.py`:

```python
class WeeklySummary(Base):
    """Marks a week as ready to appear in the Weekly Report. Content itself is
    computed live from Match/PlayerMatchStats/Team, the same way the weekly
    leaderboard and card scoring already do — this table only gates visibility
    and drives the "new report" highlight."""
    __tablename__ = "weekly_summaries"

    week_id      = Column(Integer, ForeignKey("weeks.id"), primary_key=True)
    generated_at = Column(Integer)  # Unix timestamp


class WeeklySummaryReveal(Base):
    __tablename__ = "weekly_summary_reveals"
    __table_args__ = (UniqueConstraint("week_id", "user_id",
                                       name="uq_weekly_summary_reveal_week_user"),)

    id          = Column(Integer, primary_key=True, autoincrement=True)
    week_id     = Column(Integer, ForeignKey("weeks.id"))
    user_id     = Column(Integer, ForeignKey("users.id"))
    revealed_at = Column(Integer)  # Unix timestamp


class WeeklySummarySeen(Base):
    """One row per user: the most recent week_id they've opened the report
    popup for. Used only to gate the highlight badge on the report button."""
    __tablename__ = "weekly_summary_seen"

    user_id        = Column(Integer, ForeignKey("users.id"), primary_key=True)
    last_seen_week_id = Column(Integer, ForeignKey("weeks.id"), nullable=True)
```

Add to `Match`:
```python
vod_url = Column(String, nullable=True)
```

`WeeklySummary`/`WeeklySummaryReveal`/`WeeklySummarySeen` are new tables, so per this repo's
CLAUDE.md rule they need no migration entry. `Match.vod_url` is a new column on an existing
table and **does** need one — add it to `backend/migrate.py` in the same edit session,
guarded by the existing `PRAGMA table_info` check pattern.

### Step 2 — Generation logic

In `backend/weeks.py`, mirroring `auto_lock_weeks`:

```python
def generate_weekly_summaries(db):
    """Mark weeks whose scoring window has closed as available in the Weekly
    Report. Idempotent — driven by end_time, not a fixed calendar schedule, so
    it applies uniformly to regular and irregular (e.g. finals) weeks."""
    now = clock.now(db)
    already = {r[0] for r in db.query(WeeklySummary.week_id).all()}
    newly_ready = (
        db.query(Week)
        .filter(Week.end_time <= now, ~Week.id.in_(already))
        .all()
    )
    for week in newly_ready:
        db.add(WeeklySummary(week_id=week.id, generated_at=int(now)))
        logger.info("Weekly summary available for %s", week.label)
    if newly_ready:
        db.commit()
```

Call it from `_week_maintenance_loop` in `backend/main.py` right after `auto_lock_weeks(db)`,
inside the same `try`/`finally` session block.

### Step 3 — Content query

Reuse the week/match association already established by the weekly leaderboard and card
scoring queries (`backend/routers/leaderboard.py`, `backend/routers/cards.py`):

```sql
m.week_override_id = :week_id
OR (m.week_override_id IS NULL AND m.start_time BETWEEN :week_start AND :week_end)
```

For a given week, join `Match` → `Team` (both sides) → `PlayerMatchStats` → `Player`, and
`Match.vod_url` for the VOD link. `PlayerMatchStats.is_mvp` already flags the per-match MVP
(set via `_apply_mvp_bonus` in `backend/twitch.py`), so no new MVP tracking is needed. Group
matches into series client- or server-side using the same same-two-teams/gap clustering idea
`backend/schedule.py` already uses to derive series from completed matches.

### Step 4 — Endpoints

New `backend/routers/weekly_summary.py`:
- `GET /weekly-summary` (auth required) — list of `WeeklySummary` weeks with label, whether
  the current user has revealed each, and whether the current user has an unseen new report
  (compare latest `WeeklySummary.week_id` against `WeeklySummarySeen.last_seen_week_id`)
- `GET /weekly-summary/{week_id}` (auth required) — always returns matches/teams/VOD links;
  additionally returns players/points/MVP only if a `WeeklySummaryReveal` row exists for
  `(week_id, current_user)`
- `POST /weekly-summary/{week_id}/reveal` (auth required) — creates the `WeeklySummaryReveal`
  row if absent (idempotent), then returns the same full content `GET .../{week_id}` would
- `POST /weekly-summary/seen` (auth required) — upserts `WeeklySummarySeen.last_seen_week_id`
  to the current latest `WeeklySummary.week_id`, clearing the highlight

`backend/routers/admin_matches.py`:
- `PATCH /admin/matches/{match_id}/vod` (admin required) — body `{vod_url: str | null}`,
  validated as a well-formed URL when non-null; 404 if the match doesn't exist

### Step 5 — Frontend

`frontend/index.html`: a fixed-position "Weekly report" button (badge span for the highlight)
and a modal with a tab strip (one button per available week) and a content area — series
header, per-match team/VOD rows, and either a "Reveal results" button or the full per-player
breakdown depending on reveal state.

New `frontend/app-weekly-summary.js`: `loadWeeklySummaryList()`, `openWeeklySummary(weekId)`,
`revealWeeklySummary(weekId)`, `markWeeklySummarySeen()` — fetch/render functions following
the existing `app-*.js` conventions (plain `fetch`, `render*` DOM updates, no framework).

Call `loadWeeklySummaryList()` (to decide the highlight badge) alongside
`checkNotifications()`/`claimTokenEvents()` in `login()`/`init()` in `frontend/app-auth.js`
or `frontend/app-init.js` (match whichever already owns that call site).

`frontend/app-admin.js` + the admin match table markup: add a VOD URL input (or inline edit)
per match row, calling the new `PATCH /admin/matches/{match_id}/vod` endpoint.

---

## Verification
- Create a week whose `end_time` is a few minutes in the future (or use Demo Mode's clock
  override); wait for the maintenance loop to run — the week appears in `GET /weekly-summary`
  without any fixed-schedule trigger firing
- `GET /weekly-summary/{week_id}` before reveal returns matches/teams/VOD only, no players or
  points; after `POST .../reveal` it returns the full breakdown
- Reveal as user A; confirm user B's `GET /weekly-summary/{week_id}` for the same week is
  still unrevealed
- Set a `vod_url` via `PATCH /admin/matches/{id}/vod` on a match belonging to an
  already-generated week — confirm it now appears in that week's report for all users
- Clear the `vod_url` — confirm the link disappears without touching player/points data
- Confirm the highlight badge appears after a new week is generated, clears after
  `POST /weekly-summary/seen`, and reappears once the next week's summary is generated
- Create a week with zero matches assigned to it — confirm it still appears as an empty-state
  tab rather than being omitted
- Attempt to set an obviously malformed `vod_url` (e.g. `"not a url"`) — 422 returned
