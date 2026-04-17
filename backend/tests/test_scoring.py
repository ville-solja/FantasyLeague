import pytest
from scoring import SCORING_STATS, fantasy_score, card_fantasy_score

WEIGHTS = {
    "kills": 3.0,
    "assists": 1.5,
    "deaths": -1.0,
    "gold_per_min": 0.01,
    "obs_placed": 0.5,
    "sen_placed": 0.25,
    "tower_damage": 0.001,
}


class TestFantasyScore:
    def test_basic_calculation(self):
        stats = {"kills": 5, "assists": 3, "deaths": 2, "gold_per_min": 600,
                 "obs_placed": 2, "sen_placed": 1, "tower_damage": 2000}
        expected = (5*3.0) + (3*1.5) + (2*-1.0) + (600*0.01) + (2*0.5) + (1*0.25) + (2000*0.001)
        assert fantasy_score(stats, WEIGHTS) == pytest.approx(expected)

    def test_missing_stats_default_to_zero(self):
        assert fantasy_score({}, WEIGHTS) == 0.0

    def test_missing_weight_key_ignored(self):
        stats = {"kills": 5}
        weights = {"kills": 3.0}
        assert fantasy_score(stats, weights) == pytest.approx(15.0)

    def test_deaths_are_penalised(self):
        no_deaths = fantasy_score({"kills": 5, "deaths": 0}, WEIGHTS)
        with_deaths = fantasy_score({"kills": 5, "deaths": 3}, WEIGHTS)
        assert with_deaths < no_deaths

    def test_scoring_stats_constant_has_seven_entries(self):
        assert len(SCORING_STATS) == 7


class TestCardFantasyScore:
    def test_no_modifiers_matches_base(self):
        stats = {"kills": 5, "assists": 3, "deaths": 2}
        base = fantasy_score(stats, WEIGHTS)
        assert card_fantasy_score(stats, WEIGHTS, {}) == pytest.approx(base)

    def test_positive_stat_modifier_increases_score(self):
        stats = {"kills": 10}
        no_mod = card_fantasy_score(stats, WEIGHTS, {})
        with_mod = card_fantasy_score(stats, WEIGHTS, {"kills": 10.0})
        assert with_mod > no_mod
        assert with_mod == pytest.approx(no_mod * 1.10)

    def test_death_modifier_reduces_penalty(self):
        # deaths have negative weight; a modifier should soften the penalty
        stats = {"deaths": 5}
        no_mod = card_fantasy_score(stats, WEIGHTS, {})       # -5.0
        with_mod = card_fantasy_score(stats, WEIGHTS, {"deaths": 20.0})  # factor = 1 - 0.20 = 0.80
        assert with_mod > no_mod
        assert with_mod == pytest.approx(no_mod * 0.80)

    def test_zero_weight_stat_skipped(self):
        stats = {"kills": 10}
        weights_no_kills = dict(WEIGHTS)
        weights_no_kills["kills"] = 0
        result = card_fantasy_score(stats, weights_no_kills, {"kills": 50.0})
        assert result == pytest.approx(0.0)

    def test_all_modifiers_positive(self):
        stats = {k: 10 for k in SCORING_STATS}
        base = card_fantasy_score(stats, WEIGHTS, {})
        modifiers = {k: 10.0 for k in SCORING_STATS}
        boosted = card_fantasy_score(stats, WEIGHTS, modifiers)
        # kills/assists/gpm/wards/tower_damage are rewarded more; deaths penalty softened
        # net effect on total should be larger magnitude (less negative or more positive)
        assert boosted != pytest.approx(base)
