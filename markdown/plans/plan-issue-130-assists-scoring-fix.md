# Plan: Assists Scoring Fix

## Context
Issue #130 reports that a player ("Jiri," account id `119940691`) who played two matches — one
as MVP — scored far lower than his KDA suggested. The two specific matches cited
(`9003643194`, `9003545905`) aren't present in the local dev DB snapshot used to investigate
this, so they couldn't be checked directly. However, a root cause was found and confirmed
directly in the current codebase that fully explains the reported symptom:

**`assists` is captured and stored (`PlayerMatchStats.assists`, `backend/models.py:40`),
ingested from OpenDota (`assists=p.get("assists", 0)`, `backend/ingest.py:197`), and even
displayed on the Players tab match history (`backend/routers/players.py:49`) — but it is
completely absent from `SCORING_STATS` in `backend/scoring.py`, so it contributes exactly zero
points to `fantasy_score()`.** Every *other* raw stat this app captures flows through the
weight × value loop (`scoring.py`'s own comment: "Stats that flow through the standard weight ×
value loop"); assists appears to have simply been left out. Jiri's other already-ingested
matches (found while investigating) show exactly the pattern this omission predicts — matches
with very high assist counts (26, 42, 19) score no higher, and sometimes lower, than matches
with far fewer assists but similar kills/deaths, since assists never factor in at all. This is
consistent with, though not proof positive for, the two specific matches reported.

Fixing this touches more than `scoring.py` alone, found while tracing every place
`SCORING_STATS` is referenced:
- `card_modifiers`'s DB-level `CHECK` constraint (`backend/models.py:88`, most recently
  rebuilt by migration `008_card_modifiers_constraint`) hardcodes the list of valid `stat_key`
  values at the SQL level for *existing* databases — it does not update automatically just
  because the Python-side `SCORING_STATS` list changes, since `card_modifiers`' constraint was
  baked into the table DDL when the table was created. Without a new migration rebuilding it
  the same way migration 008 did, a card modifier roll that randomly picks "assists" (now
  possible via `card_utils.py`'s `_SCORED_STAT_COLS = list(SCORING_STATS) + ["deaths"]`) would
  fail with an `IntegrityError` on every affected deployment that predates this fix.
- `frontend/app-init.js`'s `loadHowToPlay()` hardcodes its own `statsKeys`/`statsLabels`
  mirror of `SCORING_STATS` for the public scoring-explanation table — this needs the same
  addition or the public table stays silently incomplete. The Admin Weights tab
  (`frontend/app-admin-ingest.js::loadWeights()`) is unaffected — it renders whatever
  `GET /weights` returns dynamically, so a new weight appears there automatically once seeded.
- `backend/seed.py::seed_weights()` already validates its own `DEFAULT_WEIGHTS` list against
  `set(SCORING_STATS) | {...}` at startup and raises `ValueError` if a required key is missing
  — so forgetting to add the new weight entry would be caught immediately at the next startup,
  not silently shipped.

The exact default weight value for `assists` is a scoring-balance decision, not something to
guess at definitively — this plan proposes `0.15` (half of `kills`' `0.3`) as a reasonable
starting point, explicitly flagged as provisional and tunable via the existing admin Weights
panel like every other stat. *Resolves GitHub issue #130.*

## User Stories

### Include Assists in Fantasy Scoring
**User story**
As a league participant, I want assists to actually contribute to my fantasy score — matching
what's already captured, ingested, and shown to me — so that a strong assist-heavy performance
is reflected in my points instead of silently contributing nothing.

**Acceptance criteria**
- `assists` is added to `SCORING_STATS` in `backend/scoring.py`, flowing through the same
  weight × value loop as every other captured stat
- A new `assists` weight is added to `DEFAULT_WEIGHTS` in `backend/seed.py` (provisional
  default `0.15`), so it auto-seeds on next startup for both fresh and already-existing
  databases via `seed_weights()`'s existing idempotent upsert logic
- `card_modifiers`'s DB-level `CHECK` constraint is updated via a new migration (rebuilding
  the table the same way migration `008_card_modifiers_constraint` did) to allow `assists` as
  a valid `stat_key`, so card modifier rolls that land on it don't fail
- Card, roster, and leaderboard scores (`card_fantasy_score()`/`_compute_card_points()`, which
  recompute live from raw stat sums + current weights on every read) reflect the new weight
  immediately after the weight is seeded, with no extra step needed
- Running `POST /recalculate` after the fix retroactively updates every already-ingested
  match's stored `player_match_stats.fantasy_points` (used by the Players tab match history
  and `/top`) to include assists, not just newly-ingested matches going forward

### Public Scoring Explanation Includes Assists
**User story**
As a player, I want the public "How to Play" scoring table to list Assists alongside every
other scored stat, so I understand what actually earns me points without needing to guess.

**Acceptance criteria**
- `frontend/app-init.js::loadHowToPlay()`'s `statsKeys`/`statsLabels` include `assists` /
  `"Assists"`, so the rendered table shows its current weight value the same way every other
  stat already does
- `markdown/stories/team-tokens-scoring.md`'s "Score Active Cards" story's stat list is updated
  to include `assists`, so the documented formula matches the implemented one

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/scoring.py` | Add `"assists"` to `SCORING_STATS` |
| `backend/seed.py` | Add `{"key": "assists", "label": "Assists", "value": 0.15}` to `DEFAULT_WEIGHTS` |
| `backend/migrate.py` | New migration rebuilding `card_modifiers`'s `CHECK` constraint to include `assists`, following migration 008's exact pattern |
| `frontend/app-init.js` | Add `assists`/`"Assists"` to `loadHowToPlay()`'s `statsKeys`/`statsLabels` |
| `markdown/stories/team-tokens-scoring.md` | Update "Score Active Cards"'s stat list bullet |
| `markdown/features/reference/assists-scoring-fix.md` | New reference doc (stub created by product-planner) |

No change needed: `card_utils.py` (`_SCORED_STAT_COLS` already derives from `SCORING_STATS`
dynamically), `models.py`'s Python-side `_VALID_STAT_KEYS` (same reason — only the *existing*
database's already-baked constraint needs the migration), `frontend/app-admin-ingest.js` (renders
`GET /weights` dynamically).

### Step 1 — Add `assists` to the scoring loop
```python
SCORING_STATS = [
    "kills",
    "assists",
    "last_hits",
    ...
]
```

### Step 2 — Seed the new weight
Add to `DEFAULT_WEIGHTS` in `backend/seed.py`, near `kills`:
```python
{"key": "assists", "label": "Assists", "value": 0.15},
```

### Step 3 — Migration for the `card_modifiers` CHECK constraint
Add `_m025_card_modifiers_assists(conn)` to `backend/migrate.py`, mirroring
`_m008_card_modifiers_constraint`'s table-rebuild exactly (check current DDL for `'assists'`,
rebuild `card_modifiers_new` with the expanded `CHECK` list including `'assists'`, copy rows,
drop/rename), and register it in `MIGRATIONS`.

### Step 4 — Public scoring table
In `frontend/app-init.js::loadHowToPlay()`, add `'assists'` to `statsKeys` and
`assists: 'Assists'` to `statsLabels`.

### Step 5 — Update the stories doc
In `markdown/stories/team-tokens-scoring.md`'s "Score Active Cards" story, add `assists` to
the listed stat set.

### Step 6 — Fill in the feature doc stub
Update `markdown/features/reference/assists-scoring-fix.md` with the final weight value chosen
(if different from the provisional `0.15`) and confirmation the migration ran cleanly.

---

## Verification
- `cd backend && python -m pytest tests/ -v` — existing scoring tests must stay green;
  `backend/tests/test_migrate.py::TestSchemaCoverage::test_all_model_columns_present_after_migration`
  and the card-modifiers-constraint tests specifically need to pass with the new migration
- New tests: `fantasy_score()` with a synthetic stat dict including nonzero `assists` produces
  a higher score than the same dict with `assists=0`, using the seeded weight; a card modifier
  roll can land on `"assists"` without raising `IntegrityError` post-migration; the migration
  itself is idempotent (safe to run twice) and correctly rebuilds an existing `card_modifiers`
  table that has the old (pre-assists) constraint
- Manually verify against the two matches reported in issue #130 once available: ingest (or
  re-ingest) league data covering `9003643194`/`9003545905`, run `POST /recalculate`, and
  confirm Jiri's `fantasy_points` for those matches increases to reflect his assists — this is
  the actual confirmation that the fix resolves the reported complaint, since the root cause
  here is a strong, well-evidenced hypothesis rather than something verified against the exact
  matches cited
- Confirm the "How to Play" tab and Admin Weights tab both show "Assists" with the same value
  after a fresh startup
