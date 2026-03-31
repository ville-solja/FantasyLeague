import json
import os
from database import SessionLocal
from models import User, Card, Weight, PlayerMatchStats, Match
from auth import hash_password
from weeks import generate_weeks, auto_lock_weeks

SEED_DIR = os.path.join(os.path.dirname(__file__), "seed")

CARD_SCHEMA = [
    ("legendary", 1),
    ("epic",      2),
    ("rare",      4),
    ("common",    8),
]


def seed_users():
    db = SessionLocal()
    with open(os.path.join(SEED_DIR, "users.json")) as f:
        users = json.load(f)

    for u in users:
        if not db.get(User, u["id"]):
            db.add(User(
                id=u["id"],
                username=u["username"],
                email=u["email"],
                password_hash=hash_password(u["password"]),
                is_admin=u.get("is_admin", False),
            ))
            print(f"[SEED] User {u['username']}")

    db.commit()
    db.close()


def seed_cards(league_id: int):
    db = SessionLocal()

    player_ids = (
        db.query(PlayerMatchStats.player_id)
        .join(Match, Match.match_id == PlayerMatchStats.match_id)
        .filter(Match.league_id == league_id)
        .distinct()
        .all()
    )
    player_ids = [r[0] for r in player_ids]

    count = 0
    for player_id in player_ids:
        already_seeded = db.query(Card).filter(
            Card.player_id == player_id,
            Card.league_id == league_id,
        ).count()
        if already_seeded:
            continue
        for card_type, quantity in CARD_SCHEMA:
            for _ in range(quantity):
                db.add(Card(
                    player_id=player_id,
                    owner_id=None,
                    card_type=card_type,
                    league_id=league_id,
                ))
                count += 1

    db.commit()
    db.close()
    print(f"[SEED] {count} cards generated for league {league_id} across {len(player_ids)} players")


DEFAULT_WEIGHTS = [
    {"key": "kills",             "label": "Kills",                        "value": 3.0},
    {"key": "assists",           "label": "Assists",                      "value": 2.0},
    {"key": "deaths",            "label": "Deaths",                       "value": -1.0},
    {"key": "gold_per_min",      "label": "Gold per minute",              "value": 0.02},
    {"key": "obs_placed",        "label": "Observer wards placed",        "value": 1.0},
    {"key": "sen_placed",        "label": "Sentry wards placed",          "value": 1.5},
    {"key": "tower_damage",      "label": "Tower damage",                 "value": 0.002},
    {"key": "rarity_common",     "label": "Rarity bonus — Common (%)",    "value": 0.0},
    {"key": "rarity_rare",       "label": "Rarity bonus — Rare (%)",      "value": 1.0},
    {"key": "rarity_epic",       "label": "Rarity bonus — Epic (%)",      "value": 2.0},
    {"key": "rarity_legendary",  "label": "Rarity bonus — Legendary (%)", "value": 3.0},
]


def seed_weights():
    db = SessionLocal()
    for w in DEFAULT_WEIGHTS:
        if not db.get(Weight, w["key"]):
            db.add(Weight(key=w["key"], label=w["label"], value=w["value"]))
            print(f"[SEED] Weight {w['key']} = {w['value']}")
    db.commit()
    db.close()


def seed_weeks():
    """Generate week rows and retroactively lock past weeks.

    Safe to call multiple times (idempotent). Past weeks are snapshotted using
    each user's current active roster, which is the fairest option when the
    feature didn't exist during those weeks. Run this after cards are seeded so
    the snapshots capture real active rosters.
    """
    db = SessionLocal()
    generate_weeks(db)
    auto_lock_weeks(db)
    db.close()
