import json
import os
from database import SessionLocal
from models import User, Card, Weight

SEED_DIR = os.path.join(os.path.dirname(__file__), "seed")


def seed_users():
    db = SessionLocal()
    with open(os.path.join(SEED_DIR, "users.json")) as f:
        users = json.load(f)

    for u in users:
        if not db.get(User, u["id"]):
            db.add(User(id=u["id"], username=u["username"], email=u["email"], is_admin=u.get("is_admin", False)))
            print(f"[SEED] User {u['username']}")

    db.commit()
    db.close()


def seed_cards():
    db = SessionLocal()
    with open(os.path.join(SEED_DIR, "cards.json")) as f:
        cards = json.load(f)

    for c in cards:
        if not db.get(Card, c["id"]):
            db.add(Card(
                id=c["id"],
                player_id=c["player_id"],
                owner_id=c["owner_id"],
                card_type=c["card_type"],
                league_id=c["league_id"],
            ))
            print(f"[SEED] Card {c['id']} ({c['card_type']}) -> player {c['player_id']}")

    db.commit()
    db.close()


DEFAULT_WEIGHTS = [
    {"key": "kills",        "label": "Kills",                  "value": 3.0},
    {"key": "assists",      "label": "Assists",                "value": 2.0},
    {"key": "deaths",       "label": "Deaths",                 "value": -1.0},
    {"key": "gold_per_min", "label": "Gold per minute",        "value": 0.02},
    {"key": "obs_placed",   "label": "Observer wards placed",  "value": 1.0},
    {"key": "sen_placed",   "label": "Sentry wards placed",    "value": 1.5},
    {"key": "tower_damage", "label": "Tower damage",           "value": 0.002},
]


def seed_weights():
    db = SessionLocal()
    for w in DEFAULT_WEIGHTS:
        if not db.get(Weight, w["key"]):
            db.add(Weight(key=w["key"], label=w["label"], value=w["value"]))
            print(f"[SEED] Weight {w['key']} = {w['value']}")
    db.commit()
    db.close()
