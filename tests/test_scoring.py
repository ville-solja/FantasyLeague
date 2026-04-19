from scoring import fantasy_score, card_fantasy_score, SCORING_STATS

WEIGHTS = {
    "kills": 0.3,
    "assists": 0.15,
    "deaths": -0.3,
    "gold_per_min": 0.003,
    "obs_placed": 0.5,
    "sen_placed": 0.5,
    "tower_damage": 0.0001,
}


def test_fantasy_score_basic():
    stats = {
        "kills": 5, "assists": 3, "deaths": 2,
        "gold_per_min": 600, "obs_placed": 2, "sen_placed": 1, "tower_damage": 2000,
    }
    expected = (
        5 * 0.3 + 3 * 0.15 + 2 * (-0.3)
        + 600 * 0.003 + 2 * 0.5 + 1 * 0.5 + 2000 * 0.0001
    )
    assert abs(fantasy_score(stats, WEIGHTS) - expected) < 1e-9


def test_fantasy_score_empty_stats():
    assert fantasy_score({}, WEIGHTS) == 0.0


def test_fantasy_score_partial_stats():
    score = fantasy_score({"kills": 10}, {"kills": 0.3})
    assert abs(score - 3.0) < 1e-9


def test_fantasy_score_missing_weight_contributes_zero():
    score = fantasy_score({"kills": 100}, {})
    assert score == 0.0


def test_card_fantasy_score_no_modifiers_matches_base():
    stats = {"kills": 10, "assists": 5, "deaths": 2}
    assert abs(card_fantasy_score(stats, WEIGHTS, {}) - fantasy_score(stats, WEIGHTS)) < 1e-9


def test_card_fantasy_score_positive_weight_modifier():
    # 20% bonus on kills (positive weight) — contribution multiplied by 1.2
    stats = {"kills": 10}
    score = card_fantasy_score(stats, WEIGHTS, {"kills": 20})
    assert abs(score - 10 * 0.3 * 1.2) < 1e-9


def test_card_fantasy_score_negative_weight_modifier():
    # 20% bonus on deaths (negative weight) — penalty softened by factor 0.8
    stats = {"deaths": 5}
    score = card_fantasy_score(stats, WEIGHTS, {"deaths": 20})
    assert abs(score - 5 * (-0.3) * (1 - 0.20)) < 1e-9


def test_card_fantasy_score_zero_weight_stat_skipped():
    score = card_fantasy_score({"kills": 100}, {"kills": 0}, {"kills": 50})
    assert score == 0.0


def test_scoring_stats_contains_expected_keys():
    for key in ("kills", "assists", "deaths", "gold_per_min", "obs_placed", "sen_placed", "tower_damage"):
        assert key in SCORING_STATS
