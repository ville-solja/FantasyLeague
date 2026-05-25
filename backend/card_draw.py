"""
Draw helpers for dynamic card creation.

Extracted from routers/cards.py so they can be imported in tests
without requiring FastAPI to be installed.
"""
import random

from models import Card, Player, Weight


def _roll_rarity(db) -> str:
    labels  = ["common", "rare", "epic", "legendary"]
    wt_keys = ["draw_rate_common", "draw_rate_rare", "draw_rate_epic", "draw_rate_legendary"]
    weights = []
    for k in wt_keys:
        w = db.query(Weight).filter_by(key=k).first()
        weights.append(float(w.value) if w else 1.0)
    return random.choices(labels, weights=weights, k=1)[0]


def _pick_player(db, owner_id: int, rarity: str):
    all_players = db.query(Player).all()
    if not all_players:
        return None
    owned = db.query(Card).filter_by(owner_id=owner_id).all()
    owned_by_player = {}
    for c in owned:
        owned_by_player.setdefault(c.player_id, []).append(c.card_type)

    eligible = [p for p in all_players
                if rarity not in owned_by_player.get(p.id, [])]
    if not eligible:
        eligible = all_players  # relax uniqueness when all players already own this rarity

    weights = [1.0 / (1 + len(owned_by_player.get(p.id, []))) for p in eligible]
    return random.choices(eligible, weights=weights, k=1)[0]
