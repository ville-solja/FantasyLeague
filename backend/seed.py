import json
import logging
import os
import re
import time
from sqlalchemy.exc import IntegrityError
from database import SessionLocal

logger = logging.getLogger(__name__)
from models import User, Weight, TagDefinition
from auth import hash_password, username_taken
import login_mode
from scoring import SCORING_STATS

SEED_DIR = os.path.join(os.path.dirname(__file__), "seed")

def seed_users():
    db = SessionLocal()
    try:
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
    finally:
        db.close()


def seed_admin_from_env():
    """Create admin user(s) from env vars at startup if not already present.

    Reads SEED_ADMIN_USERNAME, SEED_ADMIN_EMAIL, and SEED_ADMIN_PASSWORD for
    admin #1 (unsuffixed — fully backward compatible with single-admin
    deployments). Additional admins can be configured with numbered
    suffixes: SEED_ADMIN_USERNAME_2/_EMAIL_2/_PASSWORD_2, then _3, _4, ...
    For each numbered set, all three values must be set and non-empty;
    seeding stops at the first suffix where the set is incomplete or absent
    — there is no need to declare a total admin count anywhere.

    For each set, creates an admin user unless a user with that username
    already exists (in which case it is skipped). Safe to call multiple
    times (idempotent).

    Skipped with one warning when LOGIN_METHOD=steam_signup (issue #150): these
    would be password accounts, and that mode creates accounts only through Steam.
    """
    if login_mode.current() == login_mode.STEAM_SIGNUP:
        if os.environ.get("SEED_ADMIN_USERNAME", "").strip():
            logger.warning("Admin seed: SEED_ADMIN_USERNAME (and numbered sets) ignored because "
                           "LOGIN_METHOD=steam_signup creates accounts only through Steam; "
                           "name admins with SEED_ADMIN_STEAM_IDS")
        return
    db = SessionLocal()
    try:
        i = 1
        while True:
            suffix = "" if i == 1 else f"_{i}"
            username = os.environ.get(f"SEED_ADMIN_USERNAME{suffix}", "").strip()
            email    = os.environ.get(f"SEED_ADMIN_EMAIL{suffix}",    "").strip()
            password = os.environ.get(f"SEED_ADMIN_PASSWORD{suffix}", "").strip()

            if not (username and email and password):
                break  # env vars absent or incomplete — stop seeding here

            # Case-insensitive like every other name check (issue #169); env seeding
            # skips the reserved-word check so an operator can name an admin "admin".
            if not username_taken(db, username):
                db.add(User(
                    username=username,
                    email=email,
                    password_hash=hash_password(password),
                    is_admin=True,
                    is_tester=False,
                ))
                try:
                    db.commit()
                    logger.info("Admin seed: created admin account %s", username)
                except IntegrityError:
                    db.rollback()
                    logger.error(
                        "Admin seed: cannot create %s — email %s is already in use by another account. "
                        "Set SEED_ADMIN_EMAIL%s to an unused address.",
                        username, email, suffix,
                    )
            else:
                logger.debug("Admin account %s already exists, skipping", username)

            i += 1
    finally:
        db.close()


_STEAM64_RE = re.compile(r"[0-9]{17}")


def seed_admin_steam_ids(environ=os.environ) -> set[str]:
    """Steam64 ids from SEED_ADMIN_STEAM_IDS (comma-separated, issue #150). A verified
    Steam sign-in, sign-up or link with a listed id makes the account an admin
    (never a demo account). An entry that is not exactly 17 digits is logged by
    position and skipped. Read on every call; removing an id never demotes anyone."""
    ids = set()
    raw = environ.get("SEED_ADMIN_STEAM_IDS", "")
    for position, entry in enumerate(raw.split(","), start=1):
        entry = entry.strip()
        if not entry:
            continue
        if _STEAM64_RE.fullmatch(entry):
            ids.add(entry)
        else:
            logger.warning("SEED_ADMIN_STEAM_IDS entry %d is not a 17-digit Steam64 id; skipped",
                           position)
    return ids


DEFAULT_WEIGHTS = [
    # --- Scoring stat weights ---
    {"key": "kills",                    "label": "Kills",                          "value": 0.3},
    {"key": "assists",                  "label": "Assists",                        "value": 0.15},
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
    {"key": "mvp_bonus_pct",            "label": "MVP bonus (%)",                  "value": 10.0},
    # --- Draw rate weights — relative probability of each rarity on draw ---
    {"key": "draw_rate_common",     "label": "Draw rate: Common (%)",     "value": 60.0},
    {"key": "draw_rate_rare",       "label": "Draw rate: Rare (%)",       "value": 25.0},
    {"key": "draw_rate_epic",       "label": "Draw rate: Epic (%)",       "value": 10.0},
    {"key": "draw_rate_legendary",  "label": "Draw rate: Legendary (%)",  "value": 5.0},
    # --- Team draw cost ---
    {"key": "team_booster_cost", "label": "Team draw cost (Tokens)", "value": 3.0},
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
        if existing is not None and existing.label != w["label"]:
            existing.label = w["label"]
    db.commit()
    db.close()


_INITIAL_TAGS = [
    {"key": "caster",        "label": "Caster"},
    {"key": "season_winner", "label": "Season Winner"},
]


def seed_tags():
    """Seed initial tag definitions if they do not already exist."""
    db = SessionLocal()
    try:
        for t in _INITIAL_TAGS:
            if not db.query(TagDefinition).filter_by(key=t["key"]).first():
                db.add(TagDefinition(key=t["key"], label=t["label"],
                                     created_at=int(time.time())))
        db.commit()
    finally:
        db.close()


