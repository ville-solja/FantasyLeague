<<<<<<< HEAD
# Stats that contribute to fantasy points and can carry card modifiers.
SCORING_STATS = [
    "kills", "assists", "deaths",
    "gold_per_min", "obs_placed", "sen_placed", "tower_damage",
]


def fantasy_score(p, weights):
    """Base fantasy score from raw stats and weights (no card modifiers, no rarity)."""
    return sum(weights.get(key, 0) * p.get(key, 0) for key in SCORING_STATS)
=======
# Stats that flow through the standard weight × value loop.
# Deaths is excluded — it uses a clamped pool formula handled separately.
SCORING_STATS = [
    "kills",
    "last_hits", "denies",
    "gold_per_min",
    "obs_placed",
    "towers_killed", "roshan_kills",
    "teamfight_participation",
    "camps_stacked", "rune_pickups",
    "firstblood_claimed", "stuns",
]


def _death_contribution(deaths: float, weights: dict) -> float:
    """Points from the death-survival pool: 3 pts for 0 deaths, -0.3 per death, floor 0."""
    pool = weights.get("death_pool", 3.0)
    deduction = weights.get("death_deduction", 0.3)
    return max(0.0, pool - deaths * deduction)


def fantasy_score(p, weights):
    """Base fantasy score from raw stats and weights (no card modifiers, no rarity)."""
    total = sum(weights.get(key, 0) * p.get(key, 0) for key in SCORING_STATS)
    total += _death_contribution(p.get("deaths", 0), weights)
    return total
>>>>>>> 25cc59e (Initial commit)


def card_fantasy_score(stat_sums: dict, weights: dict, card_modifiers: dict) -> float:
    """
    Fantasy points for a specific card, applying per-stat card modifiers.

<<<<<<< HEAD
    stat_sums      — {stat_key: aggregated_value}
    weights        — {stat_key: weight}  (positive = reward, negative = penalty)
    card_modifiers — {stat_key: bonus_pct}  e.g. {"kills": 10.0}

    Modifier semantics (always a benefit to the owner):
      positive-weight stats (kills, assists, GPM, wards, tower_dmg):
        contribution *= (1 + bonus_pct / 100)   — earn more points
      negative-weight stats (deaths):
        contribution *= (1 - bonus_pct / 100)   — soften the penalty
=======
    stat_sums      — {stat_key: aggregated_value} — must include "deaths"
    weights        — {stat_key: weight}
    card_modifiers — {stat_key: bonus_pct}  e.g. {"kills": 10.0}

    Death modifier amplifies the death-survival reward (always non-negative):
      death_contribution × (1 + bonus_pct / 100)
>>>>>>> 25cc59e (Initial commit)
    """
    total = 0.0
    for stat in SCORING_STATS:
        value = stat_sums.get(stat, 0)
        w = weights.get(stat, 0)
        if w == 0:
            continue
        bonus_pct = card_modifiers.get(stat, 0.0)
<<<<<<< HEAD
        factor = (1 + bonus_pct / 100) if w > 0 else (1 - bonus_pct / 100)
        total += w * value * factor
=======
        total += w * value * (1 + bonus_pct / 100)

    death_pts = _death_contribution(stat_sums.get("deaths", 0), weights)
    bonus_pct = card_modifiers.get("deaths", 0.0)
    total += death_pts * (1 + bonus_pct / 100)

>>>>>>> 25cc59e (Initial commit)
    return total
