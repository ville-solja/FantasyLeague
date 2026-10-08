# Plan: Schedule Tournament Visualization

## Context
The Schedule tab shows the season one fantasy week at a time (#156), but nothing shows how the tournament stands: who leads a division, who meets whom in the playoffs, who is through. The fixtures feed (#101) carries only round-robin rows with a week and a division. Playoff series appear only as DB-derived `extra_results` with no bracket position. This plan adds tournament **stages**, which admins set up in the app. Each visible stage becomes a subtab under Schedule.

The first build draws the two formats Kanaliiga uses:
- a round-robin group stage, as a standings table or a team-by-team results grid;
- single-elimination playoffs, as a bracket.

The data model also covers double elimination, GSL groups and Swiss, which later phases draw (stories marked *(not yet implemented)*). A visual canvas of all five formats and the admin editor is at https://claude.ai/artifact/HDsKnJv3MP7H4nrkQUVUGs (private until shared).

Decisions taken with the product owner (2026-10-08):
- **Source:** admins define stages, groups, teams and bracket seeding in the admin portal. This is the first step towards managing the schedule in the app instead of the external sheet. Results still come from ingested matches.
- **Formats:** the model and admin editor cover all five formats; the first build renders round robin and single elimination only.
- **Group view:** both a standings table and a results grid, with standings as the default and a toggle.

Assumptions:
- **Results come from ingested matches:** a stage series' result is resolved from ingested matches between its two teams inside the stage's date window. This uses the same lookup as the Schedule (`resolve_series_result`). An admin can set the winner by hand when matches are missing (a forfeit, an unparsed game).
- **Round-robin pairings are derived:** the pairings come from the group's teams, so admins don't enter 28 series. The week a pairing is played comes from the fixtures feed when it has that pair, and is otherwise left blank.
- **Points are configurable per stage:** the default is series win 3, draw 1, loss 0. Ties break on map difference, then head-to-head, then the admin's group order. Best-of-two draws are normal in the S16 group stage.
- **Season reset:** a season reset deletes all stages, the same as weeks and teams (stage rows reference `teams`).
- **Text stays league-agnostic:** no league name in code or UI; stage and group names are admin data.
- **Hide results:** stage views follow the Schedule's Hide results switch and per-series reveals (`seriesKey`, `kc_schedule_revealed`).
- **No real data on the canvas:** the S16 fixtures feed and kana-cards were not reachable from the planning environment, so it uses lettered sample teams. The test plan seeds S16-shaped data.
- **Frontend approach:** the earlier bracket attempt was scrapped for its hand-written DOM plumbing (`reference/frontend-framework-evaluation.md`). The subtab bar uses the Alpine.js pattern from How to Play. Standings, grid and bracket are built by pure functions from one JSON response, and the bracket is CSS-grid columns of series cards with plain border connectors, no SVG and no per-slot DOM lookups.

Resolves GitHub issue #94.

## User Stories

### Group Stage Standings and Results Grid
**User story**
As a player or viewer, I want a Group stage subtab under Schedule that shows each division's table and every result so that I can see who leads and who still has to play whom.

**Acceptance criteria**
- Schedule has a subtab bar: **Weeks** (the current view, default) and one subtab per stage the admin marked shown, in the admin's order, labelled with the stage's name
- A round-robin stage shows a group chooser (one button per group, e.g. "Div 1", "Div 2") and a **Standings** / **Results grid** toggle; Standings is the default; the choices are kept while the tab stays open
- Standings columns: rank, team, series played, wins, draws, losses, maps won–lost, points, form (last three series as W/D/L boxes with the letter, not colour alone); sorted by points, then map difference, then head-to-head, then the admin's group order
- The top N teams (the stage's advance count) are marked "Playoffs" and a line separates them from the rest
- The results grid shows every team against every other, score from the row team's side; a pairing not played yet shows its week ("W6") when the fixtures feed has it, else a dash; the diagonal is empty
- With Hide results on, scores, form and points of unrevealed series are not rendered, and the table shows teams in the admin's group order with "Hidden" in place of numbers; revealing a series or week on the Weeks subtab reveals it here too
- The table and grid scroll sideways in their own box on a phone-width screen; the page itself does not

### Playoff Bracket
**User story**
As a player or viewer, I want a Playoffs subtab that draws the single-elimination bracket so that I can follow who meets whom and who is through.

**Acceptance criteria**
- A single-elimination stage draws one column per round (e.g. Semifinals, Final), each series as a card with seed, team name and series score; the winner's row is bold with the score in the accent colour
- A slot not decided yet shows where it comes from in italics ("Winner of SF 2"); a slot seeded from a group stage shows the team once that stage has finished, else "Div 1 #1"
- An optional third-place series sits under the final with a dashed outline
- A series' card shows its scheduled time when set, "Upcoming" before it starts, and "Hidden" with a **Reveal** button when Hide results is on and the series is not revealed
- Each series opens its games, as on the Weeks subtab
- With several groups (Div 1, Div 2), a group chooser switches between their brackets

### Set Up Stages in the Admin Portal
**User story**
As an admin, I want to define the season's stages, their format, groups and teams so that the Schedule shows the tournament the way our league runs it.

**Acceptance criteria**
- Admin › Schedule has a **Tournament stages** section listing stages with order, subtab name, format, groups, best-of, a Shown checkbox and a state (Draft, In progress, Finished); **Add stage**, **Edit** and **Delete** (with a confirmation)
- A stage has: name (1–40 characters), format (Round robin, Single elimination, Double elimination, GSL groups, Swiss), date window (start and end), best-of (and final best-of for brackets), shown on Schedule (yes/no), advance count, and for round robin the points for a series win, draw and loss
- Groups: an admin adds groups (name 1–40 characters) and picks teams for each from the season's teams; a team can be in one group per stage
- Single elimination: the admin chooses the bracket size (2, 4, 8 or 16) and seeds each first-round slot either by hand (a team) or from a round-robin stage's final rank ("Div 1 #1"); later slots are filled from earlier series automatically; a third-place series is optional
- An admin can set a series' scheduled time and, when its matches are missing, its winner and score by hand; a hand-set result shows a "Set by admin" note in the admin list only
- Formats not drawn yet (double elimination, GSL, Swiss) can be saved but can't be marked Shown; the checkbox explains "Not shown on Schedule yet"
- Every create, edit and delete writes an audit entry (`stage_created`, `stage_updated`, `stage_deleted`, `stage_series_result_set`); non-admins get 403 on every admin endpoint

### Stage Data Stays Correct
**User story**
As the league operator, I want stage views to follow the ingested results and season resets so that nobody has to keep them in sync by hand.

**Acceptance criteria**
- A new ingested match between two teams of a stage, inside its date window, updates that series' score, the standings and any bracket slot it feeds, on the next Schedule load (the stage response shares the Schedule's cache and is busted with it)
- A series with games outside the stage's window is not counted for that stage
- `POST /admin/season/reset` deletes all stages, groups, teams-in-groups and series
- `GET /schedule/stages` returns only shown stages, no admin-only fields (hand-set markers, audit data), and works for logged-out viewers

### Double Elimination, GSL Groups and Swiss *(not yet implemented)*
**User story**
As a league running other formats, I want the Schedule to draw double-elimination brackets, GSL groups and Swiss rounds so that the tool fits more than one tournament structure.

**Acceptance criteria**
- Double elimination: upper and lower brackets as two rows of round columns plus a grand final; upper-bracket losers drop to the named lower-bracket slot
- GSL groups (4 teams): opening matches, winners match, elimination match and decider; two teams advance
- Swiss: rounds paired by record, pools shown by record ("1–1"), advance and elimination thresholds set per stage (default 2 wins / 2 losses for 8 teams, 3/3 for 16)
- Each is enabled for Shown once drawn; the data model and admin editor from the first build are reused unchanged

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New tables `tournament_stages`, `stage_groups`, `stage_group_teams`, `stage_series` (new tables only: `create_all`, no migration) |
| `backend/stages.py` | New: round-robin pairings and standings, bracket construction and slot resolution, result lookup through `schedule.resolve_series_result`, response builder |
| `backend/routers/admin_stages.py` | New: admin CRUD for stages, groups, teams, seeding and series |
| `backend/routers/admin_ingest.py` | `GET /schedule/stages` beside `GET /schedule`; bust its cache with the schedule cache |
| `backend/routers/admin_season.py` | Season reset deletes stage tables |
| `backend/main.py` | Mount the new router |
| `frontend/index.html` | Schedule subtab bar (Alpine), stage panel container; admin Tournament stages section |
| `frontend/app-schedule-stages.js` | New: pure builders `standingsRows`, `gridRows`, `bracketColumns`, plus `loadScheduleStages` render through `renderIfChanged` |
| `frontend/app-admin-stages.js` | New: admin editor through `adminFetch` |
| `frontend/style.css` | Standings, grid, bracket card and connector styles using the brand tokens |
| `markdown/features/reference/schedule-tournament-visualization.md`, `markdown/ui_description/schedule.md`, `markdown/ui_description/admin.md` | Docs |
| `backend/tests/test_issue_94_schedule_tournament_visualization.py` | Tests, with an S16-shaped fixture (2 groups × 8 teams round robin, best of two; 4-team single elimination per group) |

### Step 1 — Data model
```python
class TournamentStage(Base):
    __tablename__ = "tournament_stages"
    id          = Column(Integer, primary_key=True)
    position    = Column(Integer, nullable=False)          # subtab order
    name        = Column(String, nullable=False)           # subtab label
    format      = Column(String, nullable=False)           # round_robin | single_elim | double_elim | gsl | swiss
    starts_at   = Column(Integer, nullable=True)           # date window for result lookup
    ends_at     = Column(Integer, nullable=True)
    shown       = Column(Boolean, nullable=False, default=False)
    settings    = Column(Text, nullable=False, default="{}")  # JSON: best_of, final_best_of, advance_count,
                                                              # points {win, draw, loss}, third_place, bracket_size, swiss thresholds

class StageGroup(Base):
    __tablename__ = "stage_groups"
    id       = Column(Integer, primary_key=True)
    stage_id = Column(Integer, ForeignKey("tournament_stages.id"), nullable=False)
    position = Column(Integer, nullable=False)
    name     = Column(String, nullable=False)

class StageGroupTeam(Base):
    __tablename__ = "stage_group_teams"
    group_id = Column(Integer, ForeignKey("stage_groups.id"), primary_key=True)
    team_id  = Column(Integer, ForeignKey("teams.id"), primary_key=True)
    position = Column(Integer, nullable=False)              # tie-break / hidden order

class StageSeries(Base):
    __tablename__ = "stage_series"
    id           = Column(Integer, primary_key=True)
    stage_id     = Column(Integer, ForeignKey("tournament_stages.id"), nullable=False)
    group_id     = Column(Integer, ForeignKey("stage_groups.id"), nullable=True)
    bracket      = Column(String, nullable=True)            # upper | lower | grand_final | third_place
    round        = Column(Integer, nullable=False)
    slot         = Column(Integer, nullable=False)
    team1_id     = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team2_id     = Column(Integer, ForeignKey("teams.id"), nullable=True)
    source1      = Column(String, nullable=True)            # "seed:<stage_id>:<group_id>:<rank>" | "winner:<series_id>" | "loser:<series_id>"
    source2      = Column(String, nullable=True)
    scheduled_at = Column(Integer, nullable=True)
    manual_score1 = Column(Integer, nullable=True)          # admin-set result when matches are missing
    manual_score2 = Column(Integer, nullable=True)
```
Round robin stores no series rows: pairings are derived from the group's teams. Bracket formats store one row per series, built when the admin saves the bracket size.

### Step 2 — Stage logic (`backend/stages.py`)
- `round_robin_view(db, stage, group)`:
  - pairings from the group's teams;
  - each pairing's result from `resolve_series_result` within the stage window;
  - its week from the fixtures feed (`get_schedule` weeks) when the pair is listed;
  - standings rows with points and tie-breaks, and the matrix.
- `bracket_view(db, stage, group)`:
  - resolve each series' teams from its sources, in round order;
  - resolve each series' score from matches, else from the manual score;
  - mark the winner when a team reaches `ceil(best_of / 2)` wins, or reaches it at the end of a best-of-two;
  - return columns of series with `seriesKey` values that match the frontend's `seriesKey`.
- `public_stages(db)`: shown stages only, without the manual-result marker. The result is cached in the schedule cache's dict and cleared by `bust_cache()`.

### Step 3 — Endpoints
- `GET /schedule/stages` (public): `{"stages": [{id, name, format, groups: [{id, name, standings | grid | columns}]}]}`.
- `GET /admin/stages`, `POST /admin/stages`, `PUT /admin/stages/{id}`, `DELETE /admin/stages/{id}` (admin, audited).
- `PUT /admin/stages/{id}/groups`: replaces the groups and their teams.
- `PUT /admin/stages/{id}/bracket`: size, third place and first-round seeds; rebuilds the series rows.
- `PUT /admin/stages/{id}/series/{series_id}`: scheduled time, manual score.

Every body is a Pydantic model with `Field` bounds. Names are cleaned with `text_safety.clean_display_text`.

### Step 4 — Schedule subtabs (frontend)
- The subtab bar uses Alpine (`x-data`, `@click`, `x-show`), as How to Play does. **Weeks** wraps the existing `#scheduleContent` area unchanged.
- `app-schedule-stages.js` fetches `/schedule/stages` once per Schedule load and renders the chosen stage with pure builders. It reuses `seriesKey`, `rowState` and the hide and reveal storage from `app-players.js`.
- The group chooser and the Standings / Results grid toggle are buttons with `aria-pressed`. Every name goes through `_escHtml`.
- The bracket is a CSS grid with one column per round, built from `bracketColumns()`. Connectors are border pseudo-elements on each pair; the canvas artboard "Schedule › Playoffs" is the reference.

### Step 5 — Admin editor
An **Admin › Schedule › Tournament stages** section, built with `adminFetch` (`frontend/app-admin-stages.js`):
- the stage list and the edit form, following the canvas artboard "Admin › Tournament stages";
- a team picker from `GET /teams`;
- a seed picker listing round-robin stages and ranks;
- a series list with time and manual score.

Formats not drawn yet show "Not shown on Schedule yet" and keep **Shown** disabled.

### Step 6 — Docs and tests
- Fill in the feature doc and update `ui_description/schedule.md` (subtabs, stage views) and `ui_description/admin.md`.
- Tests:
  - pairing count (n·(n−1)/2);
  - standings order and tie-breaks;
  - the best-of-two draw;
  - bracket slot resolution from winner and loser sources and from group ranks;
  - manual score fallback;
  - the date window excluding outside games;
  - hidden fields absent from the public response;
  - reset deleting the stages;
  - 403 for non-admins;
  - name length bounds;
  - Node-run checks of `standingsRows`, `gridRows` and `bracketColumns`.

## Verification
- `cd backend && python -m pytest tests/test_issue_94_schedule_tournament_visualization.py tests/test_issue_156_schedule_visuals.py tests/test_issue_101_schedule_fixtures_api.py`
- Manual, with S16 data:
  1. Create "Group stage" (round robin, Div 1 and Div 2 with their teams, best of two, top 4 advance) and "Playoffs" (single elimination, size 4 per division, seeds from the group stage ranks, best of three); mark both Shown.
  2. Open Schedule. The subtabs read Weeks, Group stage, Playoffs.
  3. The standings match the played results; the grid shows each pairing once from each side.
  4. With Hide results on, nothing gives a result away; revealing a week on the Weeks subtab reveals those series in the stage views.
  5. After the group stage ends, the bracket shows the seeded teams, and an ingested playoff match fills its series and the next slot.
  6. Check at 360 px width that the table, grid and bracket scroll in their own boxes.
- Season reset clears all stages. No migration is needed (new tables only).
