import random

from sqlalchemy import text

from models import Card, CardModifier, Weight
from scoring import card_fantasy_score, fantasy_score, SCORING_STATS


_SCORED_STAT_COLS = list(SCORING_STATS) + ["deaths"]


def _load_weights(db) -> tuple[dict, dict]:
    """Return (weights_dict, rarity_dict) loaded from DB in a single query.

    weights_dict — full {key: value} map, used directly by card_fantasy_score()
    rarity_dict  — {"mod_common": 0.0, "mod_rare": 0.01, ...} multipliers
    """
    all_weights = {w.key: w.value for w in db.query(Weight).all()}
    rarity = {
        "mod_common":    all_weights.get("rarity_common",    0.0) / 100,
        "mod_rare":      all_weights.get("rarity_rare",      1.0) / 100,
        "mod_epic":      all_weights.get("rarity_epic",      2.0) / 100,
        "mod_legendary": all_weights.get("rarity_legendary", 3.0) / 100,
    }
    return all_weights, rarity


def _stat_sums_from_row(row) -> dict:
    """Extract scored stat values (SCORING_STATS + deaths) from a SQLAlchemy Row or dict."""
    if hasattr(row, "_mapping"):
        return {stat: row._mapping.get(stat, 0) or 0 for stat in _SCORED_STAT_COLS}
    return {stat: getattr(row, stat, 0) or 0 for stat in _SCORED_STAT_COLS}


def _mvp_bonus_delta(row, weights: dict) -> float:
    """Additive fantasy-point bonus for one MVP-flagged match.

    Mirrors the player-level bonus applied by scoring.apply_mvp_bonus_to_row(): the
    match's own fantasy_score() (deaths included) times mvp_bonus_pct,
    computed on that single match rather than on a card's multi-match
    aggregate. The death-survival term is a clamped, non-linear formula
    (max(0, pool - deaths*deduction)), so summing per-match contributions is
    not the same as computing it on aggregated deaths — keeping this
    per-match and adding the result as a flat bonus avoids distorting that
    term for every card, which is what a naive per-match SQL restructure
    would otherwise do.
    """
    stats = _stat_sums_from_row(row)
    base = fantasy_score(stats, weights)
    bonus_pct = weights.get("mvp_bonus_pct", 10.0)
    return base * bonus_pct / 100


def _compute_card_points(stat_sums: dict, card_type: str, weights: dict, rarity: dict, mods: dict,
                          mvp_bonus: float = 0.0) -> float:
    """Apply card_fantasy_score + rarity multiplier for one card.

    mvp_bonus is the sum of _mvp_bonus_delta() across any MVP-flagged matches
    in the card's scoring window — added before the rarity multiplier so an
    MVP bonus scales with card rarity the same way every other stat does.
    """
    base = card_fantasy_score(stat_sums, weights, mods) + mvp_bonus
    rarity_mod = 1 + rarity.get(f"mod_{card_type}", 0)
    return base * rarity_mod


def _assign_modifiers(db, card: Card, weights: dict):
    """Randomly assign stat modifiers to a card based on its rarity and configured weights.

    modifier_count_<rarity>  — how many stats get a modifier
    modifier_bonus_pct       — the % bonus each modifier grants
    """
    count_key = f"modifier_count_{card.card_type}"
    count = int(weights.get(count_key, 0))
    if count <= 0:
        return
    bonus_pct = weights.get("modifier_bonus_pct", 10.0)
    chosen = random.sample(_SCORED_STAT_COLS, min(count, len(_SCORED_STAT_COLS)))
    for stat in chosen:
        db.add(CardModifier(card_id=card.id, stat_key=stat, bonus_pct=bonus_pct))


def _card_modifiers_map(db, card_ids: list[int]) -> dict[int, dict]:
    """Return {card_id: {stat_key: bonus_pct}} for a list of card IDs."""
    if not card_ids:
        return {}
    rows = db.query(CardModifier).filter(CardModifier.card_id.in_(card_ids)).all()
    result: dict[int, dict] = {}
    for row in rows:
        result.setdefault(row.card_id, {})[row.stat_key] = row.bonus_pct
    return result


def _card_modifiers_dict_for_image(db, card_id: int) -> dict:
    """Fresh read from DB for PNG generation (avoids any ORM identity-map edge cases)."""
    rows = db.execute(
        text("SELECT stat_key, bonus_pct FROM card_modifiers WHERE card_id = :cid"),
        {"cid": card_id},
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def _format_modifiers(mods: dict) -> list[dict]:
    """Convert {stat_key: bonus_pct} to sorted list for API response."""
    return [{"stat": k, "bonus_pct": v} for k, v in sorted(mods.items())]
