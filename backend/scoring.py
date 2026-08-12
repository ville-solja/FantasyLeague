from __future__ import annotations


# Stats that flow through the standard weight × value loop.
# Deaths is excluded — it uses a clamped pool formula handled separately.
SCORING_STATS = [
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
]


def fantasy_score(p: dict, weights: dict) -> float:
    """Base fantasy score from raw stats and weights (no card modifiers, no rarity)."""
    total = sum(weights.get(key, 0) * p.get(key, 0) for key in SCORING_STATS)
    total += _death_contribution(p.get("deaths", 0), weights)
    return total


def _death_contribution(deaths: float, weights: dict) -> float:
    """Points from the death-survival pool: pool for 0 deaths, minus deduction per death, floored at 0."""
    pool = weights.get("death_pool", 3.0)
    deduction = weights.get("death_deduction", 0.3)
    return max(0.0, pool - deaths * deduction)


def stat_dict_from_row(row) -> dict:
    """Extract the raw stat fields fantasy_score() needs from a PlayerMatchStats-like row.

    Single source of truth for this field list — it was previously copy-pasted
    (with the same fallback-to-0 defaults) in three places: twitch.py's MVP
    bonus helper, ingest.py's post-ingest MVP re-apply step, and admin_ingest.py's
    /recalculate loop. Keeping one copy means a field added to fantasy_score()'s
    inputs only needs updating here.
    """
    return {
        "kills": row.kills or 0, "deaths": row.deaths or 0,
        "gold_per_min": row.gold_per_min or 0, "obs_placed": row.obs_placed or 0,
        "last_hits": row.last_hits or 0, "denies": row.denies or 0,
        "towers_killed": row.towers_killed or 0, "roshan_kills": row.roshan_kills or 0,
        "teamfight_participation": row.teamfight_participation or 0.0,
        "camps_stacked": row.camps_stacked or 0, "rune_pickups": row.rune_pickups or 0,
        "firstblood_claimed": row.firstblood_claimed or 0, "stuns": row.stuns or 0.0,
    }


def apply_mvp_bonus_to_row(row, weights: dict, apply: bool) -> None:
    """Set or clear the MVP bonus + is_mvp flag on a PlayerMatchStats-like row, in place.

    Recomputes the base score from the row's own raw stats (not its current
    fantasy_points), so this is safe to call regardless of what fantasy_points
    currently holds. Caller is responsible for committing.
    """
    base_pts = fantasy_score(stat_dict_from_row(row), weights)
    bonus_pct = weights.get("mvp_bonus_pct", 10.0)
    row.fantasy_points = round(base_pts * (1 + bonus_pct / 100), 4) if apply else round(base_pts, 4)
    row.is_mvp = apply


def card_fantasy_score(stat_sums: dict, weights: dict, card_modifiers: dict) -> float:
    """
    Fantasy points for a specific card, applying per-stat card modifiers.

    stat_sums      — {stat_key: aggregated_value} — should include "deaths"
    weights        — {stat_key: weight}
    card_modifiers — {stat_key: bonus_pct}  e.g. {"kills": 10.0}

    Death modifier amplifies the death-survival reward (always non-negative):
      death_contribution × (1 + bonus_pct / 100)
    """
    total = 0.0
    for stat in SCORING_STATS:
        value = stat_sums.get(stat, 0)
        w = weights.get(stat, 0)
        if w == 0:
            continue
        bonus_pct = card_modifiers.get(stat, 0.0)
        total += w * value * (1 + bonus_pct / 100)

    death_pts = _death_contribution(stat_sums.get("deaths", 0), weights)
    bonus_pct = card_modifiers.get("deaths", 0.0)
    total += death_pts * (1 + bonus_pct / 100)
    return total
