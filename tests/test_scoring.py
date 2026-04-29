from scoring import fantasy_score, card_fantasy_score, SCORING_STATS

WEIGHTS = {
    "kills": 0.3,
    "last_hits": 0.003,
    "denies": 0.0003,
    "gold_per_min": 0.002,
    "obs_placed": 0.5,
    "towers_killed": 1.0,
    "roshan_kills": 1.0,
    "teamfight_participation": 3.0,
    "camps_stacked": 0.5,
    "rune_pickups": 0.25,
    "firstblood_claimed": 4.0,
    "stuns": 0.05,
    "death_pool": 3.0,
    "death_deduction": 0.3,
}


def test_fantasy_score_basic():
    stats = {
        "kills": 5,
        "deaths": 2,
        "last_hits": 200,
        "denies": 10,
        "gold_per_min": 600,
        "obs_placed": 3,
        "towers_killed": 1,
        "roshan_kills": 0,
        "teamfight_participation": 0.6,
        "camps_stacked": 2,
        "rune_pickups": 4,
        "firstblood_claimed": 0,
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
        + max(0.0, 3.0 - 2 * 0.3)
    )
    assert abs(fantasy_score(stats, WEIGHTS) - expected) < 1e-9


def test_fantasy_score_empty_stats():
    # No stats supplied → only death_pool contributes (0 deaths = 3.0 pts)
    assert abs(fantasy_score({}, WEIGHTS) - 3.0) < 1e-9


def test_fantasy_score_partial_stats():
    score = fantasy_score({"kills": 10, "deaths": 0}, {"kills": 0.3, "death_pool": 3.0, "death_deduction": 0.3})
    assert abs(score - (10 * 0.3 + 3.0)) < 1e-9


def test_fantasy_score_missing_weight_contributes_zero():
    score = fantasy_score({"kills": 100}, {"death_pool": 0.0, "death_deduction": 0.3})
    assert abs(score - 0.0) < 1e-9


def test_card_fantasy_score_no_modifiers_matches_base():
    stats = {"kills": 10, "deaths": 2, "gold_per_min": 500}
    assert abs(card_fantasy_score(stats, WEIGHTS, {}) - fantasy_score(stats, WEIGHTS)) < 1e-9


def test_card_fantasy_score_positive_weight_modifier():
    # 20% bonus on kills (positive weight) — contribution multiplied by 1.2
    stats = {"kills": 10, "deaths": 0}
    score = card_fantasy_score(stats, WEIGHTS, {"kills": 20})
    expected = (10 * 0.3 * 1.2) + 3.0
    assert abs(score - expected) < 1e-9


def test_card_fantasy_score_negative_weight_modifier():
    # 20% bonus on deaths amplifies the survival bonus (pool component)
    stats = {"deaths": 0}
    score = card_fantasy_score(stats, WEIGHTS, {"deaths": 20})
    assert abs(score - 3.0 * 1.2) < 1e-9


def test_card_fantasy_score_zero_weight_stat_skipped():
    score = card_fantasy_score({"kills": 100, "deaths": 0}, {"kills": 0, "death_pool": 3.0, "death_deduction": 0.3}, {"kills": 50})
    assert abs(score - 3.0) < 1e-9


def test_scoring_stats_contains_expected_keys():
    for key in (
        "kills",
        "last_hits",
        "denies",
        "gold_per_min",
        "obs_placed",
        "towers_killed",
        "roshan_kills",
        "teamfight_participation",
        "camps_stacked",
        "rune_pickups",
        "firstblood_claimed",
        "stuns",
    ):
        assert key in SCORING_STATS
    assert "deaths" not in SCORING_STATS
