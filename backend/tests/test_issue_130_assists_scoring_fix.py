"""
Failing stubs for Issue #130 / plan-issue-130-assists-scoring-fix.md.

Root cause: `assists` is captured (PlayerMatchStats.assists), ingested from
OpenDota, and displayed on the Players tab — but is absent from
`scoring.SCORING_STATS`, so it contributes zero points to `fantasy_score()`
and `card_fantasy_score()`.

Story 1 ("Include Assists in Fantasy Scoring") acceptance criteria, one
class per criterion:
  1. `assists` added to `SCORING_STATS`, flowing through the weight × value loop
  2. A new `assists` weight added to `DEFAULT_WEIGHTS` (backend/seed.py),
     auto-seeding on next startup for both fresh and already-existing DBs
  3. `card_modifiers`'s DB-level CHECK constraint updated via a new migration
     (mirroring `_m008_card_modifiers_constraint`) to allow `assists`
  4. Card/roster/leaderboard scores (`card_fantasy_score()`) reflect the new
     weight immediately once seeded — no extra step needed
  5. `POST /recalculate` retroactively updates stored
     `player_match_stats.fantasy_points` to include assists

Story 2 ("Public Scoring Explanation Includes Assists") is frontend-only
(`frontend/app-init.js::loadHowToPlay()` + a stories-doc bullet) — it has no
backend test surface and is intentionally skipped here, per this repo's
convention for frontend-only stories.

Each stub below is intentionally unimplemented — its body is exactly
`pytest.fail("not yet implemented")` — so it fails until Stage 2
(the developer) implements the fix described in the plan.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from models import League, Match, Player, PlayerMatchStats, Weight
from scoring import SCORING_STATS, fantasy_score, card_fantasy_score, stat_dict_from_row
from seed import DEFAULT_WEIGHTS, seed_weights
from migrate import run_migrations

# Reuse the existing legacy-schema fixture (pre-008-style tables, including a
# `card_modifiers` table with no CHECK constraint yet) so the migration stubs
# below exercise run_migrations() through the exact same fixture the existing
# card_modifiers-constraint tests use in tests/test_migrate.py.
from tests.test_migrate import legacy_engine  # noqa: F401 — used as a fixture

# Reuse the SessionLocal-patched in-memory DB fixture used by seed_weights()'s
# own tests, so the "already-existing DB" seeding stub matches that file's
# established pattern exactly.
from tests.test_seed import seed_env  # noqa: F401 — used as a fixture


# ---------------------------------------------------------------------------
# AC 1 — assists flows through the standard weight × value loop
# ---------------------------------------------------------------------------

class TestAssistsInScoringLoop:
    def test_assists_present_in_scoring_stats(self):
        """SCORING_STATS must include "assists" so it flows through the same
        weight × value loop as every other captured stat (kills, last_hits, ...).
        """
        assert "assists" in SCORING_STATS

    def test_fantasy_score_assists_contribution_is_nonzero(self):
        """fantasy_score() must multiply a nonzero `assists` value by its weight
        and add it to the total.

        Uses a synthetic weights dict (not the seeded production default, which
        the plan explicitly flags as provisional) so this tests the mechanism,
        not a specific tunable number: e.g. with weights = {"assists": 0.15,
        "death_pool": 0.0, "death_deduction": 0.0}, fantasy_score({"assists": 10},
        weights) should equal pytest.approx(10 * 0.15), and should be strictly
        greater than fantasy_score({"assists": 0}, weights).
        """
        weights = {"assists": 0.15, "death_pool": 0.0, "death_deduction": 0.0}
        with_assists = fantasy_score({"assists": 10}, weights)
        without_assists = fantasy_score({"assists": 0}, weights)
        assert with_assists == pytest.approx(10 * 0.15)
        assert with_assists > without_assists

    def test_card_fantasy_score_assists_contribution_is_nonzero(self):
        """card_fantasy_score() must include "assists" in its per-stat loop over
        SCORING_STATS, including applying any card modifier bonus_pct on
        "assists" — e.g. stat_sums={"assists": 10, "deaths": 0}, weights=
        {"assists": 0.15}, card_modifiers={"assists": 50.0} should score higher
        than the same call with card_modifiers={} (no assists modifier).
        """
        stat_sums = {"assists": 10, "deaths": 0}
        weights = {"assists": 0.15}
        with_modifier = card_fantasy_score(stat_sums, weights, {"assists": 50.0})
        without_modifier = card_fantasy_score(stat_sums, weights, {})
        assert with_modifier > without_modifier


# ---------------------------------------------------------------------------
# AC 2 — DEFAULT_WEIGHTS has an "assists" entry, seeded for fresh AND
# already-existing databases
# ---------------------------------------------------------------------------

class TestAssistsDefaultWeight:
    def test_default_weights_has_assists_entry(self):
        """DEFAULT_WEIGHTS (backend/seed.py) must contain a {"key": "assists", ...}
        entry — required both so seed_weights()'s own `required = set(SCORING_STATS)
        | {...}` validation doesn't raise ValueError at startup, and so the
        weight actually gets seeded.
        """
        entry = next((w for w in DEFAULT_WEIGHTS if w["key"] == "assists"), None)
        assert entry is not None
        assert entry["value"] > 0

    def test_seed_weights_adds_assists_to_already_existing_database(self, seed_env):
        """seed_weights()'s per-key upsert (`db.get(Weight, w["key"])` /
        `existing is None`) must add the "assists" row to a database that
        already has every OTHER default weight seeded but predates this fix
        (i.e. has no "assists" row yet) — without disturbing the existing
        values. Simulates the "already-existing databases" half of the
        acceptance criterion, not just a fresh DB.
        """
        # Simulate a pre-fix database: every default weight already seeded
        # EXCEPT "assists" (which didn't exist as a concept before this fix),
        # with a distinct value on an existing key so we can confirm it's
        # left untouched.
        pre_fix_db = seed_env()
        for w in DEFAULT_WEIGHTS:
            if w["key"] == "assists":
                continue
            value = 999.0 if w["key"] == "kills" else w["value"]
            pre_fix_db.add(Weight(key=w["key"], label=w["label"], value=value))
        pre_fix_db.commit()
        pre_fix_db.close()

        seed_weights()

        post_db = seed_env()
        assists_row = post_db.get(Weight, "assists")
        kills_row = post_db.get(Weight, "kills")
        post_db.close()

        assert assists_row is not None
        expected_assists_value = next(w["value"] for w in DEFAULT_WEIGHTS if w["key"] == "assists")
        assert assists_row.value == pytest.approx(expected_assists_value)
        # Pre-existing values must be left undisturbed by the upsert.
        assert kills_row.value == pytest.approx(999.0)


# ---------------------------------------------------------------------------
# AC 3 — card_modifiers's DB-level CHECK constraint allows "assists"
# ---------------------------------------------------------------------------

class TestCardModifiersConstraintAllowsAssists:
    def test_migration_allows_assists_stat_key(self, legacy_engine):
        """After run_migrations() (which chains through the existing
        _m008_card_modifiers_constraint rebuild and the new migration this plan
        adds), inserting a card_modifiers row with stat_key='assists' must
        succeed without raising sqlalchemy.exc.IntegrityError.
        """
        run_migrations(legacy_engine)
        with legacy_engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO card_modifiers (card_id, stat_key, bonus_pct)"
                " VALUES (1, 'assists', 25.0)"
            ))
            conn.commit()
            row = conn.execute(text(
                "SELECT stat_key FROM card_modifiers WHERE stat_key = 'assists'"
            )).first()
        assert row is not None

    def test_migration_ddl_includes_assists(self, legacy_engine):
        """After run_migrations(), the card_modifiers table's DDL (SELECT sql
        FROM sqlite_master WHERE type='table' AND name='card_modifiers') must
        contain 'assists' in its CHECK constraint's stat_key list.
        """
        run_migrations(legacy_engine)
        with legacy_engine.connect() as conn:
            ddl = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='card_modifiers'"
            )).scalar() or ""
        assert "ck_card_modifiers_stat_key" in ddl
        assert "assists" in ddl

    def test_migration_still_rejects_invalid_stat_key(self, legacy_engine):
        """The rebuilt CHECK constraint must still reject stat keys that were
        never valid (e.g. 'not_a_real_stat') — confirming the migration expands
        the allow-list rather than removing the constraint altogether.
        """
        run_migrations(legacy_engine)
        with pytest.raises(IntegrityError):
            with legacy_engine.connect() as conn:
                conn.execute(text(
                    "INSERT INTO card_modifiers (card_id, stat_key, bonus_pct)"
                    " VALUES (1, 'not_a_real_stat', 10.0)"
                ))
                conn.commit()

    def test_migration_is_idempotent_with_assists(self, legacy_engine):
        """Running run_migrations() twice against the same legacy_engine must not
        raise, and the second run must leave card_modifiers still able to accept
        stat_key='assists' (mirrors the existing
        TestMigrationsAddColumns.test_idempotent_on_legacy_engine /
        TestMigrationsIdempotent pattern, scoped to this new migration).
        """
        run_migrations(legacy_engine)
        run_migrations(legacy_engine)  # second call must not raise

        with legacy_engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO card_modifiers (card_id, stat_key, bonus_pct)"
                " VALUES (1, 'assists', 10.0)"
            ))
            conn.commit()
            row = conn.execute(text(
                "SELECT stat_key FROM card_modifiers WHERE stat_key = 'assists'"
            )).first()
        assert row is not None


# ---------------------------------------------------------------------------
# AC 4 — card/roster/leaderboard scores reflect the new weight immediately
# ---------------------------------------------------------------------------

class TestCardScoringReflectsAssistsImmediately:
    def test_card_fantasy_score_changes_when_assists_weight_changes(self):
        """card_fantasy_score() recomputes live from raw stat sums + current
        weights on every call (no caching/precomputed state) — so calling it
        twice with the same stat_sums (including a nonzero "assists") but two
        different "assists" weight values must produce two different scores,
        with no extra step (e.g. no re-ingest) needed in between.
        """
        stat_sums = {"assists": 10, "deaths": 0}
        score_low_weight = card_fantasy_score(stat_sums, {"assists": 0.1}, {})
        score_high_weight = card_fantasy_score(stat_sums, {"assists": 0.5}, {})
        assert score_low_weight != score_high_weight
        assert score_high_weight > score_low_weight


# ---------------------------------------------------------------------------
# AC 5 — POST /recalculate retroactively updates stored fantasy_points
# ---------------------------------------------------------------------------

class TestRecalculateIncludesAssists:
    def test_recalculate_style_update_increases_stored_points_for_assists(self, db):
        """Mirrors the recalculate endpoint's per-row recompute
        (stat.fantasy_points = fantasy_score(stat_dict_from_row(stat), weights)),
        used by tests/test_recalculate.py's _recalculate() helper.

        Store a PlayerMatchStats row with a nonzero "assists" value and a
        fantasy_points value that reflects the pre-fix state (assists ignored,
        e.g. 0.0). After recomputing via fantasy_score(stat_dict_from_row(stat),
        weights) with a weights dict that includes an "assists" entry, the
        stored fantasy_points must increase to reflect the assists contribution
        — confirming already-ingested matches (not just newly-ingested ones)
        pick up the fix retroactively once POST /recalculate is run.
        """
        league = League(id=1, name="L")
        player = Player(id=1, name="P")
        match = Match(match_id=100, league_id=1)
        db.add_all([league, player, match])
        db.commit()

        # Pre-fix stored state: assists was ignored, so fantasy_points was
        # computed as if assists contributed nothing (0.0 here, for simplicity).
        stat = PlayerMatchStats(
            player_id=1, match_id=100, kills=0, assists=20, deaths=0,
            fantasy_points=0.0, is_mvp=False,
        )
        db.add(stat)
        db.commit()
        pre_fix_points = stat.fantasy_points

        weights = {"assists": 0.15, "death_pool": 0.0, "death_deduction": 0.0}

        # Mirror the recalculate endpoint's per-row recompute.
        stat.fantasy_points = fantasy_score(stat_dict_from_row(stat), weights)
        db.commit()

        assert stat.fantasy_points > pre_fix_points
        assert stat.fantasy_points == pytest.approx(20 * 0.15)
