# Assists Scoring Fix

Fixes a scoring bug where `assists` — already captured, ingested, and displayed — contributed
zero points to fantasy scoring because it was never included in the weight × value loop.

*(see `markdown/plans/plan-issue-130-assists-scoring-fix.md`, resolves GitHub issue #130)*

---

## The bug

`PlayerMatchStats.assists` is stored (`backend/models.py`), ingested from OpenDota
(`backend/ingest.py`), and shown on the Players tab match history (`backend/routers/players.py`)
— but `backend/scoring.py`'s `SCORING_STATS` list, which every other captured stat flows
through, never included it. A player's assists were visible everywhere except in their actual
score. Reported (issue #130) as a player's fantasy points looking "awfully low" relative to
their KDA despite an MVP-worthy performance.

## Fix

1. **`assists` added to `SCORING_STATS`** (`backend/scoring.py`) — flows through
   `fantasy_score()`/`card_fantasy_score()` exactly like every other stat.
2. **New `assists` weight seeded** (`backend/seed.py`'s `DEFAULT_WEIGHTS`, default value `0.15`,
   half of `kills`' `0.3`) — auto-seeds on next startup via the existing idempotent upsert in
   `seed_weights()`, no manual step needed on already-deployed instances. Admin-tunable via the
   Weights panel like every other stat.
3. **`card_modifiers`'s DB-level `CHECK` constraint updated** via migration
   `025_card_modifiers_assists` (`backend/migrate.py`) — the constraint is baked into the table
   DDL at creation time on existing databases and does not update itself just because
   `SCORING_STATS` changed in Python; without this, a card modifier roll landing on "assists"
   would fail with an `IntegrityError`. Rebuilt the same table-rebuild way migration
   `008_card_modifiers_constraint` originally built it, widening the `CHECK` list to include
   `'assists'`.
4. **Public "How to Play" scoring table updated** (`frontend/app-init.js::loadHowToPlay()`) —
   its `statsKeys`/`statsLabels` are a separate hardcoded mirror of `SCORING_STATS`, not derived
   from it; the Admin Weights tab needed no change since it renders `GET /weights` dynamically.

## What this does *not* retroactively fix on its own

Card/roster/leaderboard scores recompute live from raw stat sums on every read, so they reflect
the new weight immediately once seeded. The *stored* `player_match_stats.fantasy_points` column
(used by the Players tab match history and `/top`) does not update itself — an admin needs to
run `POST /recalculate` once after this ships to retroactively apply the new weight to
already-ingested matches.

## Root cause confidence

The two specific matches reported in issue #130 (`9003643194`, `9003545905`) were not present
in the local dev DB used to investigate this, so the fix could not be verified against them
directly. The root cause is corroborated by the same reported player's *other* already-ingested
matches, which show no correlation between assist count and fantasy points — consistent with,
but not conclusive proof of, the exact complaint. Verifying against the two cited matches once
ingested is called out explicitly in the plan's Verification section.
