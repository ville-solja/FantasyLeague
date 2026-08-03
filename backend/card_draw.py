"""
Draw helpers for dynamic card creation.

Extracted from routers/cards.py so they can be imported in tests
without requiring FastAPI to be installed.
"""
import random

from sqlalchemy import func

from models import Card, Player, PlayerMatchStats


def _roll_rarity(weights: dict) -> str:
    """Roll a rarity from the draw_rate_* weights.

    Takes the already-loaded {key: value} weights dict (see card_utils._load_weights
    or the equivalent inline fetch at each call site) instead of querying the DB
    itself, so callers that already have weights loaded don't pay for 4 extra
    single-row queries per draw.
    """
    labels  = ["common", "rare", "epic", "legendary"]
    wt_keys = ["draw_rate_common", "draw_rate_rare", "draw_rate_epic", "draw_rate_legendary"]
    weight_values = [float(weights.get(k, 1.0)) for k in wt_keys]
    return random.choices(labels, weights=weight_values, k=1)[0]


def _pick_player(db, owner_id: int, rarity: str):
    """Pick a player for a standard draw.

    Duplicate prevention is player-level: the user will not receive a player they already
    own (at any rarity) until they own every active player, at which point any player
    becomes eligible again.
    """
    all_players = db.query(Player).all()
    if not all_players:
        return None

    owned_player_ids = {
        r[0] for r in
        db.query(Card.player_id).filter_by(owner_id=owner_id).all()
    }

    eligible = [p for p in all_players if p.id not in owned_player_ids]
    if not eligible:
        eligible = all_players

    owned_counts = {
        r[0]: r[1] for r in
        db.query(Card.player_id, func.count(Card.id))
          .filter_by(owner_id=owner_id)
          .group_by(Card.player_id).all()
    }
    max_count = max(owned_counts.values(), default=0)
    weights = [max_count - owned_counts.get(p.id, 0) + 1 for p in eligible]
    return random.choices(eligible, weights=weights, k=1)[0]


def _pick_player_from_team(db, owner_id: int, rarity: str, team_id: int):
    """Pick a player from a specific team for a booster draw.

    Duplicate prevention is player-level only (rarity is ignored): the user will not
    receive a player they already own from this team until they own every player on the
    team, at which point any player becomes eligible again.

    Returns the chosen Player, or None if the team has no players at all.
    """
    team_player_ids = [
        r[0] for r in
        db.query(PlayerMatchStats.player_id)
          .filter(PlayerMatchStats.team_id == team_id)
          .distinct().all()
    ]
    if not team_player_ids:
        return None

    owned_player_ids = {
        r[0] for r in
        db.query(Card.player_id).filter(
            Card.owner_id == owner_id,
            Card.player_id.in_(team_player_ids),
        ).all()
    }

    eligible = [pid for pid in team_player_ids if pid not in owned_player_ids]
    if not eligible:
        # All team players owned — allow any player
        eligible = team_player_ids

    owned_counts = {
        r[0]: r[1] for r in
        db.query(Card.player_id, func.count(Card.id))
          .filter(Card.owner_id == owner_id, Card.player_id.in_(eligible))
          .group_by(Card.player_id).all()
    }
    max_count = max(owned_counts.values(), default=0)
    weights = [max_count - owned_counts.get(pid, 0) + 1 for pid in eligible]
    chosen_id = random.choices(eligible, weights=weights, k=1)[0]
    return db.get(Player, chosen_id)
