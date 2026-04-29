import json
import logging
import os
from database import SessionLocal

logger = logging.getLogger(__name__)
from models import User, Card, Weight, PlayerMatchStats, Match
from auth import hash_password
from weeks import generate_weeks, auto_lock_weeks
from scoring import SCORING_STATS

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
                is_tester=u.get("is_tester", False),
            ))
            logger.info("Seeded user %s", u["username"])

    db.commit()
    db.close()


def seed_cards(league_id: int, generation: int = 1):
    db = SessionLocal()

    player_ids = (
        db.query(PlayerMatchStats.player_id)
        .join(Match, Match.match_id == PlayerMatchStats.match_id)
        .filter(Match.league_id == league_id)
        .distinct()
        .all()
    )
    player_ids = [r[0] for r in player_ids]

    already_seeded = {
        r[0] for r in
        db.query(Card.player_id).filter(
            Card.league_id == league_id,
            Card.generation == generation,
        ).distinct().all()
    }

    count = 0
    for player_id in player_ids:
        if player_id in already_seeded:
            continue
        for card_type, quantity in CARD_SCHEMA:
            for _ in range(quantity):
                db.add(Card(
                    player_id=player_id,
                    owner_id=None,
                    card_type=card_type,
                    league_id=league_id,
                    generation=generation,
                ))
                count += 1

    db.commit()
    db.close()
    logger.info("Seeded %d cards (gen %d) for league %d across %d players",
                count, generation, league_id, len(player_ids))


DEFAULT_WEIGHTS = [
    # --- Scoring stat weights ---
    {"key": "kills",                    "label": "Kills",                          "value": 0.3},
    {"key": "last_hits",                "label": "Last hits",                      "value": 0.003},
    {"key": "denies",                   "label": "Denies",                         "value": 0.0003},
    {"key": "gold_per_min",             "label": "Gold per minute",                "value": 0.002},
    {"key": "obs_placed",               "label": "Observer wards placed",          "value": 0.5},
    {"key": "towers_killed",            "label": "Towers destroyed",               "value": 1.0},
    {"key": "roshan_kills",             "label": "Roshan kills",                   "value": 1.0},
    {"key": "teamfight_participation",  "label": "Participation (100% = 1.0)",     "value": 3.0},
    {"key": "camps_stacked",            "label": "Camps stacked",                  "value": 0.5},
    {"key": "rune_pickups",             "label": "Runes picked up",                "value": 0.25},
    {"key": "firstblood_claimed",       "label": "First blood",                    "value": 4.0},
    {"key": "stuns",                    "label": "Stuns (seconds)",                "value": 0.05},
    {"key": "death_pool",               "label": "Deaths — pool (0 deaths)",        "value": 3.0},
    {"key": "death_deduction",          "label": "Deaths — deduction per death",    "value": 0.3},
    # --- Rarity bonuses — flat % multiplier on a card's total score ---
    {"key": "rarity_common",     "label": "Rarity bonus — Common (%)",          "value": 0.0},
    {"key": "rarity_rare",       "label": "Rarity bonus — Rare (%)",            "value": 1.0},
    {"key": "rarity_epic",       "label": "Rarity bonus — Epic (%)",            "value": 2.0},
    {"key": "rarity_legendary",  "label": "Rarity bonus — Legendary (%)",       "value": 3.0},
    # --- Card modifiers — number of stat modifiers granted per rarity at draw time ---
    {"key": "modifier_count_common",    "label": "Modifiers — Common (count)",     "value": 0.0},
    {"key": "modifier_count_rare",      "label": "Modifiers — Rare (count)",       "value": 1.0},
    {"key": "modifier_count_epic",      "label": "Modifiers — Epic (count)",       "value": 2.0},
    {"key": "modifier_count_legendary", "label": "Modifiers — Legendary (count)",  "value": 3.0},
    # --- Bonus % applied by each modifier ---
    {"key": "modifier_bonus_pct",       "label": "Modifier bonus (%)",             "value": 10.0},
]


def seed_weights():
    """Seed weights from DEFAULT_WEIGHTS, then apply any WEIGHTS_JSON overrides.

    WEIGHTS_JSON is a JSON object mapping weight keys to float values, e.g.:
        WEIGHTS_JSON={"kills": 3.0, "deaths": -1.5}
    Only keys present in the env var are overridden; the rest keep their defaults.
    Values are upserted so env var changes take effect on restart.
    """
    env_overrides: dict = {}
    raw = os.getenv("WEIGHTS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            env_overrides = {k: float(v) for k, v in parsed.items()}
            logger.info("WEIGHTS_JSON overrides: %s", list(env_overrides.keys()))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Could not parse WEIGHTS_JSON — %s", e)

    required = set(SCORING_STATS) | {"death_pool", "death_deduction",
                                     "rarity_common", "rarity_rare", "rarity_epic", "rarity_legendary",
                                     "modifier_count_common", "modifier_count_rare", "modifier_count_epic", "modifier_count_legendary",
                                     "modifier_bonus_pct"}
    present = {w["key"] for w in DEFAULT_WEIGHTS}
    missing = sorted(required - present)
    if missing:
        raise ValueError(f"DEFAULT_WEIGHTS missing required keys: {missing}")

    db = SessionLocal()
    for w in DEFAULT_WEIGHTS:
        existing = db.get(Weight, w["key"])
        target_value = env_overrides.get(w["key"], w["value"])
        if existing is None:
            db.add(Weight(key=w["key"], label=w["label"], value=target_value))
            logger.info("Weight %s = %s", w["key"], target_value)
        elif w["key"] in env_overrides and existing.value != target_value:
            logger.info("Weight %s overridden by env: %s → %s", w["key"], existing.value, target_value)
            existing.value = target_value
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
