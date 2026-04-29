import pytest
from scoring import SCORING_STATS, fantasy_score, card_fantasy_score

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
}


class TestFantasyScore:
    def test_basic_calculation(self):
        stats = {
            "kills": 5, "deaths": 2, "last_hits": 200, "denies": 10,
            "gold_per_min": 600, "obs_placed": 3, "towers_killed": 1,
            "roshan_kills": 0, "teamfight_participation": 0.6,
            "camps_stacked": 2, "rune_pickups": 4, "firstblood_claimed": 0,
            "stuns": 10.0,
        }
        expected = (
            5 * 0.3
            + 200 * 0.003
            + 10 * 0.0003
            + 600 * 0.002
            + 3 * 0.5
            + 1 * 1.0
            + 0 * 1.0
            + 0.6 * 3.0
            + 2 * 0.5
            + 4 * 0.25
            + 0 * 4.0
            + 10.0 * 0.05
            + max(0.0, 3.0 - 2 * 0.3)  # death contribution
        )
        assert fantasy_score(stats, WEIGHTS) == pytest.approx(expected)

    def test_zero_deaths_awards_full_pool(self):
        score = fantasy_score({"deaths": 0}, WEIGHTS)
        assert score == pytest.approx(3.0)

    def test_ten_deaths_awards_zero(self):
        score = fantasy_score({"deaths": 10}, WEIGHTS)
        assert score == pytest.approx(0.0)

    def test_excess_deaths_floored_at_zero(self):
        score_ten = fantasy_score({"deaths": 10}, WEIGHTS)
        score_twenty = fantasy_score({"deaths": 20}, WEIGHTS)
        assert score_ten == pytest.approx(score_twenty)
        assert score_twenty == pytest.approx(0.0)

    def test_more_deaths_reduce_score(self):
        few = fantasy_score({"deaths": 1}, WEIGHTS)
        many = fantasy_score({"deaths": 5}, WEIGHTS)
        assert many < few

    def test_missing_stats_default_to_zero_deaths(self):
        # No stats supplied → only death_pool contributes (0 deaths = 3.0 pts)
        assert fantasy_score({}, WEIGHTS) == pytest.approx(3.0)

    def test_missing_weight_key_ignored(self):
        stats = {"kills": 5}
        weights = {"kills": 0.3, "death_pool": 3.0, "death_deduction": 0.3}
        assert fantasy_score(stats, weights) == pytest.approx(5 * 0.3 + 3.0)

    def test_scoring_stats_excludes_deaths(self):
        assert "deaths" not in SCORING_STATS

    def test_scoring_stats_has_twelve_entries(self):
        assert len(SCORING_STATS) == 12

    def test_firstblood_scores_correctly(self):
        score = fantasy_score({"firstblood_claimed": 1, "deaths": 0}, WEIGHTS)
        assert score == pytest.approx(4.0 + 3.0)

    def test_teamfight_participation_full(self):
        score = fantasy_score({"teamfight_participation": 1.0, "deaths": 0}, WEIGHTS)
        assert score == pytest.approx(3.0 + 3.0)


class TestCardFantasyScore:
    def test_no_modifiers_matches_base(self):
        stats = {"kills": 5, "deaths": 2, "gold_per_min": 500}
        base = fantasy_score(stats, WEIGHTS)
        assert card_fantasy_score(stats, WEIGHTS, {}) == pytest.approx(base)

    def test_positive_stat_modifier_increases_score(self):
        stats = {"kills": 10, "deaths": 0}
        no_mod = card_fantasy_score(stats, WEIGHTS, {})
        with_mod = card_fantasy_score(stats, WEIGHTS, {"kills": 10.0})
        assert with_mod > no_mod
        kill_contribution = 10 * 0.3
        assert with_mod == pytest.approx(no_mod + kill_contribution * 0.10)

    def test_death_modifier_amplifies_survival_bonus(self):
        stats = {"deaths": 0}
        no_mod = card_fantasy_score(stats, WEIGHTS, {})    # 3.0
        with_mod = card_fantasy_score(stats, WEIGHTS, {"deaths": 20.0})  # 3.0 * 1.20
        assert with_mod > no_mod
        assert with_mod == pytest.approx(3.0 * 1.20)

    def test_death_modifier_useless_at_max_deaths(self):
        stats = {"deaths": 10}
        no_mod = card_fantasy_score(stats, WEIGHTS, {})
        with_mod = card_fantasy_score(stats, WEIGHTS, {"deaths": 50.0})
        assert no_mod == pytest.approx(0.0)
        assert with_mod == pytest.approx(0.0)

    def test_zero_weight_stat_skipped(self):
        stats = {"kills": 10, "deaths": 0}
        weights_no_kills = {**WEIGHTS, "kills": 0}
        result = card_fantasy_score(stats, weights_no_kills, {"kills": 50.0})
        assert result == pytest.approx(card_fantasy_score({"deaths": 0}, WEIGHTS, {}))

    def test_all_modifiers_increase_score(self):
        stats = {k: 5 for k in SCORING_STATS}
        stats["deaths"] = 2
        base = card_fantasy_score(stats, WEIGHTS, {})
        modifiers = {k: 10.0 for k in SCORING_STATS}
        modifiers["deaths"] = 10.0
        boosted = card_fantasy_score(stats, WEIGHTS, modifiers)
        assert boosted > base
