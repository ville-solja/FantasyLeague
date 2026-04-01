# Stats that contribute to fantasy points and can carry card modifiers.
SCORING_STATS = [
    "kills", "assists", "deaths",
    "gold_per_min", "obs_placed", "sen_placed", "tower_damage",
]


def fantasy_score(p, weights):
    """Base fantasy score from raw stats and weights (no card modifiers, no rarity)."""
    return sum(weights.get(key, 0) * p.get(key, 0) for key in SCORING_STATS)


def card_fantasy_score(stat_sums: dict, weights: dict, card_modifiers: dict) -> float:
    """
    Fantasy points for a specific card, applying per-stat card modifiers.

    stat_sums      — {stat_key: aggregated_value}
    weights        — {stat_key: weight}  (positive = reward, negative = penalty)
    card_modifiers — {stat_key: bonus_pct}  e.g. {"kills": 10.0}

    Modifier semantics (always a benefit to the owner):
      positive-weight stats (kills, assists, GPM, wards, tower_dmg):
        contribution *= (1 + bonus_pct / 100)   — earn more points
      negative-weight stats (deaths):
        contribution *= (1 - bonus_pct / 100)   — soften the penalty
    """
    total = 0.0
    for stat in SCORING_STATS:
        value = stat_sums.get(stat, 0)
        w = weights.get(stat, 0)
        if w == 0:
            continue
        bonus_pct = card_modifiers.get(stat, 0.0)
        factor = (1 + bonus_pct / 100) if w > 0 else (1 - bonus_pct / 100)
        total += w * value * factor
    return total
