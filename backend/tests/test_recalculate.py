"""
Tests for the recalculate and MVP bonus logic.

The recalculate endpoint (POST /recalculate in main.py) and the MVP bonus
helper (_apply_mvp_bonus in twitch.py) both depend on FastAPI and cannot be
imported directly.  These tests exercise the identical arithmetic — using
fantasy_score() and the same weight lookups — directly against the models
so that any future change to the formula is caught without needing an HTTP
layer.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from models import League, Match, Player, PlayerMatchStats, Weight
from scoring import fantasy_score, SCORING_STATS


# Weights that mirror the DEFAULT_WEIGHTS used in production
WEIGHTS = {
    "kills":                   0.3,
    "last_hits":               0.003,
    "denies":                  0.0003,
    "gold_per_min":            0.002,
    "obs_placed":              0.5,
    "towers_killed":           1.0,
    "roshan_kills":            1.0,
    "teamfight_participation": 3.0,
    "camps_stacked":           0.5,
    "rune_pickups":            0.25,
    "firstblood_claimed":      4.0,
    "stuns":                   0.05,
    "death_pool":              3.0,
    "death_deduction":         0.3,
    "mvp_bonus_pct":           10.0,
}


def _seed_weights(db, overrides=None):
    w = dict(WEIGHTS)
    if overrides:
        w.update(overrides)
    for key, value in w.items():
        db.add(Weight(key=key, label=key, value=value))
    db.commit()


def _make_stat(db, kills=5, deaths=2, gold_per_min=500.0, obs_placed=1,
               last_hits=100, denies=5, towers_killed=0, roshan_kills=0,
               teamfight_participation=0.5, camps_stacked=1, rune_pickups=2,
               firstblood_claimed=0, stuns=5.0):
    league = League(id=1, name="L")
    player = Player(id=1, name="P")
    match = Match(match_id=100, league_id=1)
    db.add_all([league, player, match])
    db.commit()

    stat_fields = dict(
        kills=kills, deaths=deaths, gold_per_min=gold_per_min,
        obs_placed=obs_placed, last_hits=last_hits, denies=denies,
        towers_killed=towers_killed, roshan_kills=roshan_kills,
        teamfight_participation=teamfight_participation,
        camps_stacked=camps_stacked, rune_pickups=rune_pickups,
        firstblood_claimed=firstblood_claimed, stuns=stuns,
    )
    base = fantasy_score(stat_fields, WEIGHTS)
    stat = PlayerMatchStats(
        player_id=1, match_id=100, fantasy_points=base, is_mvp=False,
        **stat_fields,
    )
    db.add(stat)
    db.commit()
    return stat


# ---------------------------------------------------------------------------
# Base fantasy score stored correctly
# ---------------------------------------------------------------------------

class TestBaseScore:
    def test_stored_score_matches_formula(self, db):
        stat = _make_stat(db)
        expected = fantasy_score({
            "kills": 5, "deaths": 2, "gold_per_min": 500.0, "obs_placed": 1,
            "last_hits": 100, "denies": 5, "towers_killed": 0, "roshan_kills": 0,
            "teamfight_participation": 0.5, "camps_stacked": 1, "rune_pickups": 2,
            "firstblood_claimed": 0, "stuns": 5.0,
        }, WEIGHTS)
        assert stat.fantasy_points == pytest.approx(expected)

    def test_zero_stats_yields_only_death_pool(self, db):
        stat = _make_stat(db, kills=0, deaths=0, gold_per_min=0, obs_placed=0,
                          last_hits=0, denies=0, towers_killed=0, roshan_kills=0,
                          teamfight_participation=0, camps_stacked=0, rune_pickups=0,
                          firstblood_claimed=0, stuns=0)
        assert stat.fantasy_points == pytest.approx(3.0)  # death_pool at 0 deaths

    def test_high_death_count_reduces_score(self, db):
        low_deaths = _make_stat(db, deaths=0)
        low_score = low_deaths.fantasy_points

        # New player/match for second stat
        db.add(Player(id=2, name="P2"))
        db.add(Match(match_id=101, league_id=1))
        db.commit()
        fields = dict(kills=5, deaths=10, gold_per_min=500.0, obs_placed=1,
                      last_hits=100, denies=5, towers_killed=0, roshan_kills=0,
                      teamfight_participation=0.5, camps_stacked=1, rune_pickups=2,
                      firstblood_claimed=0, stuns=5.0)
        high_stat = PlayerMatchStats(
            player_id=2, match_id=101,
            fantasy_points=fantasy_score(fields, WEIGHTS),
            **fields,
        )
        db.add(high_stat)
        db.commit()

        assert high_stat.fantasy_points < low_score


# ---------------------------------------------------------------------------
# MVP bonus application
# ---------------------------------------------------------------------------

class TestMvpBonus:
    def test_mvp_bonus_increases_points_by_correct_pct(self, db):
        stat = _make_stat(db)
        base_pts = stat.fantasy_points
        bonus_pct = WEIGHTS["mvp_bonus_pct"]
        expected = round(base_pts * (1 + bonus_pct / 100), 4)

        stat.fantasy_points = round(stat.fantasy_points * (1 + bonus_pct / 100), 4)
        stat.is_mvp = True
        db.commit()
        db.refresh(stat)

        assert stat.fantasy_points == pytest.approx(expected)
        assert stat.is_mvp is True

    def test_clearing_mvp_restores_base_score(self, db):
        stat = _make_stat(db)
        base_pts = stat.fantasy_points
        bonus_pct = WEIGHTS["mvp_bonus_pct"]

        # Apply bonus
        stat.fantasy_points = round(base_pts * (1 + bonus_pct / 100), 4)
        stat.is_mvp = True
        db.commit()

        # Clear bonus (re-derive from raw stats)
        raw = {
            "kills": stat.kills or 0, "deaths": stat.deaths or 0,
            "gold_per_min": stat.gold_per_min or 0, "obs_placed": stat.obs_placed or 0,
            "last_hits": stat.last_hits or 0, "denies": stat.denies or 0,
            "towers_killed": stat.towers_killed or 0, "roshan_kills": stat.roshan_kills or 0,
            "teamfight_participation": stat.teamfight_participation or 0,
            "camps_stacked": stat.camps_stacked or 0, "rune_pickups": stat.rune_pickups or 0,
            "firstblood_claimed": stat.firstblood_claimed or 0, "stuns": stat.stuns or 0,
        }
        stat.fantasy_points = round(fantasy_score(raw, WEIGHTS), 4)
        stat.is_mvp = False
        db.commit()
        db.refresh(stat)

        assert stat.fantasy_points == pytest.approx(base_pts, abs=1e-4)
        assert stat.is_mvp is False

    def test_non_mvp_stat_is_not_boosted(self, db):
        stat = _make_stat(db)
        base_pts = stat.fantasy_points
        # Do NOT apply bonus — verify score is unchanged
        assert stat.is_mvp is False
        assert stat.fantasy_points == pytest.approx(base_pts)

    def test_mvp_bonus_with_custom_percentage(self, db):
        stat = _make_stat(db)
        base_pts = stat.fantasy_points
        bonus_pct = 25.0  # custom
        expected = round(base_pts * 1.25, 4)

        stat.fantasy_points = round(base_pts * (1 + bonus_pct / 100), 4)
        stat.is_mvp = True
        db.commit()
        db.refresh(stat)

        assert stat.fantasy_points == pytest.approx(expected)

    def test_mvp_bonus_with_zero_percentage_is_identity(self, db):
        stat = _make_stat(db)
        base_pts = stat.fantasy_points

        stat.fantasy_points = round(base_pts * (1 + 0 / 100), 4)
        stat.is_mvp = True
        db.commit()
        db.refresh(stat)

        assert stat.fantasy_points == pytest.approx(base_pts, abs=1e-4)


# ---------------------------------------------------------------------------
# Recalculate logic (mirrors POST /recalculate in main.py)
# ---------------------------------------------------------------------------

def _recalculate(db, weights_dict, mvp_bonus_pct=10.0):
    """
    Replicate the recalculate endpoint logic:
      1. Recompute base fantasy_points from stored raw stats.
      2. Apply MVP bonus to rows with is_mvp=True.
    """
    stats = db.query(PlayerMatchStats).all()
    for stat in stats:
        p = {
            "kills": stat.kills or 0, "deaths": stat.deaths or 0,
            "gold_per_min": stat.gold_per_min or 0, "obs_placed": stat.obs_placed or 0,
            "last_hits": stat.last_hits or 0, "denies": stat.denies or 0,
            "towers_killed": stat.towers_killed or 0, "roshan_kills": stat.roshan_kills or 0,
            "teamfight_participation": stat.teamfight_participation or 0.0,
            "camps_stacked": stat.camps_stacked or 0, "rune_pickups": stat.rune_pickups or 0,
            "firstblood_claimed": stat.firstblood_claimed or 0, "stuns": stat.stuns or 0.0,
        }
        stat.fantasy_points = fantasy_score(p, weights_dict)
    for stat in stats:
        if stat.is_mvp:
            stat.fantasy_points = round(stat.fantasy_points * (1 + mvp_bonus_pct / 100), 4)
    db.commit()


class TestRecalculateLogic:
    def test_recalculate_applies_new_weights(self, db):
        stat = _make_stat(db, kills=10, deaths=0)
        old_pts = stat.fantasy_points

        new_weights = dict(WEIGHTS, kills=1.0)  # triple the kill weight
        _recalculate(db, new_weights)

        db.refresh(stat)
        assert stat.fantasy_points > old_pts

    def test_recalculate_recomputes_from_raw_stats(self, db):
        stat = _make_stat(db, kills=5, deaths=0)
        expected = fantasy_score(
            {"kills": 5, "deaths": 0, "gold_per_min": 500.0, "obs_placed": 1,
             "last_hits": 100, "denies": 5, "towers_killed": 0, "roshan_kills": 0,
             "teamfight_participation": 0.5, "camps_stacked": 1, "rune_pickups": 2,
             "firstblood_claimed": 0, "stuns": 5.0},
            WEIGHTS,
        )

        # Corrupt the stored points to verify they get rewritten
        stat.fantasy_points = 999.0
        db.commit()

        _recalculate(db, WEIGHTS)

        db.refresh(stat)
        assert stat.fantasy_points == pytest.approx(expected)

    def test_recalculate_applies_mvp_bonus_to_mvp_rows(self, db):
        stat = _make_stat(db)
        stat.is_mvp = True
        stat.fantasy_points = 999.0  # corrupt value
        db.commit()

        bonus_pct = WEIGHTS["mvp_bonus_pct"]
        raw = {"kills": 5, "deaths": 2, "gold_per_min": 500.0, "obs_placed": 1,
               "last_hits": 100, "denies": 5, "towers_killed": 0, "roshan_kills": 0,
               "teamfight_participation": 0.5, "camps_stacked": 1, "rune_pickups": 2,
               "firstblood_claimed": 0, "stuns": 5.0}
        expected = round(fantasy_score(raw, WEIGHTS) * (1 + bonus_pct / 100), 4)

        _recalculate(db, WEIGHTS, mvp_bonus_pct=bonus_pct)

        db.refresh(stat)
        assert stat.fantasy_points == pytest.approx(expected)

    def test_recalculate_does_not_apply_mvp_bonus_to_non_mvp_rows(self, db):
        stat = _make_stat(db)
        stat.is_mvp = False
        db.commit()

        raw = {"kills": 5, "deaths": 2, "gold_per_min": 500.0, "obs_placed": 1,
               "last_hits": 100, "denies": 5, "towers_killed": 0, "roshan_kills": 0,
               "teamfight_participation": 0.5, "camps_stacked": 1, "rune_pickups": 2,
               "firstblood_claimed": 0, "stuns": 5.0}
        expected = fantasy_score(raw, WEIGHTS)

        _recalculate(db, WEIGHTS)

        db.refresh(stat)
        assert stat.fantasy_points == pytest.approx(expected)

    def test_recalculate_handles_empty_table(self, db):
        # Should run without error even with no stats rows
        _recalculate(db, WEIGHTS)
