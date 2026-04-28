import io
import json
import logging
import os
import random
import re as _re
import secrets
import threading
import time
import warnings
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text
from models import Player, PlayerMatchStats, Match, Card, CardModifier, User, Weight, Team, Week, PromoCode, CodeRedemption, AuditLog, PlayerProfile
from twitch import router as twitch_router
from database import SessionLocal, engine, Base, DATABASE_URL, get_db
from migrate import run_migrations
from ingest import ingest_league
from enrich import run_enrichment, run_profile_enrichment
from seed import seed_users, seed_cards, seed_weights
from scoring import fantasy_score, card_fantasy_score, SCORING_STATS
from auth import hash_password, verify_password
from email_utils import send_email
from schedule import get_schedule, bust_cache, SCHEDULE_SHEET_URL
from weeks import generate_weeks, auto_lock_weeks, get_next_editable_week
from image import generate_card_image, PIL_AVAILABLE, _ASSETS_DIR
from toornament import sync_toornament_results

logger = logging.getLogger(__name__)

ROSTER_LIMIT   = int(os.getenv("ROSTER_LIMIT", "5"))
TOKEN_NAME     = os.getenv("TOKEN_NAME", "Tokens")
INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))
_APP_VERSION   = os.getenv("APP_VERSION", "APP_VERSION")
_APP_RELEASE   = os.getenv("APP_RELEASE", "")

_WEEK_CHECK_INTERVAL       = int(os.getenv("WEEK_CHECK_INTERVAL",       "300"))
_INGEST_POLL_INTERVAL      = int(os.getenv("INGEST_POLL_INTERVAL",      "900"))
_ENRICHMENT_INTERVAL       = int(os.getenv("ENRICHMENT_CHECK_INTERVAL", "300"))
_ENRICHMENT_BATCH_SIZE     = int(os.getenv("ENRICHMENT_BATCH_SIZE",     "3"))


def _week_maintenance_loop():
    """Background thread: periodically generate new weeks and lock past ones."""
    while True:
        try:
            db = SessionLocal()
            try:
                generate_weeks(db)
                auto_lock_weeks(db)
            finally:
                db.close()
        except Exception:
            logger.exception("Week maintenance error")
        time.sleep(_WEEK_CHECK_INTERVAL)


def _profile_enrichment_loop():
    """Background thread: periodically enrich player profiles with hero stats and AI bios."""
    while True:
        try:
            result = run_profile_enrichment(batch_size=_ENRICHMENT_BATCH_SIZE)
            if result["enriched"] or result["errors"]:
                logger.info("Profile enrichment: %s", result)
        except Exception:
            logger.exception("Profile enrichment loop error")
        time.sleep(_ENRICHMENT_INTERVAL)


def _auto_ingest(league_ids: list[int]):
    for league_id in league_ids:
        try:
            logger.info("Auto-ingest: league %d starting", league_id)
            ingest_league(league_id)
            run_enrichment()
            seed_cards(league_id)
            logger.info("Auto-ingest: league %d done", league_id)
        except Exception:
            logger.exception("Auto-ingest: league %d failed", league_id)


def _run_toornament_sync():
    try:
        db = SessionLocal()
        try:
            result = sync_toornament_results(db)
        finally:
            db.close()
        logger.info("Toornament sync: %s", result)
    except Exception:
        logger.exception("Toornament sync error")


def _ingest_poll_loop(league_ids: list[int]):
    """Background thread: periodically ingest new matches then sync to toornament."""
    while True:
        try:
            _auto_ingest(league_ids)
            _run_toornament_sync()
        except Exception:
            logger.exception("Unexpected error in ingest poll loop")
        time.sleep(_INGEST_POLL_INTERVAL)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email:    str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)


class GrantTokensBody(BaseModel):
    target_user_id: int
    amount: int


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password:     str = Field(min_length=6, max_length=128)


class CreateCodeBody(BaseModel):
    code:         str = Field(min_length=1, max_length=64)
    token_amount: int


class RedeemCodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class UpdateUsernameBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class UpdatePlayerIdBody(BaseModel):
    player_id: int | None = None


class ForgotPasswordBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class MatchWeekBody(BaseModel):
    week_id: int | None = None


class SimulateBody(BaseModel):
    kills: float | None = None
<<<<<<< HEAD
    assists: float | None = None
    deaths: float | None = None
    gold_per_min: float | None = None
    obs_placed: float | None = None
    sen_placed: float | None = None
    tower_damage: float | None = None
=======
    last_hits: float | None = None
    denies: float | None = None
    gold_per_min: float | None = None
    obs_placed: float | None = None
    towers_killed: float | None = None
    roshan_kills: float | None = None
    teamfight_participation: float | None = None
    camps_stacked: float | None = None
    rune_pickups: float | None = None
    firstblood_claimed: float | None = None
    stuns: float | None = None
    death_pool: float | None = None
    death_deduction: float | None = None
>>>>>>> 25cc59e (Initial commit)


def get_current_user(request: Request) -> dict:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user_id, "username": request.session.get("username"),
            "is_admin": request.session.get("is_admin", False)}


def require_admin(current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def _audit(db, action: str, actor_id=None, actor_username=None, detail=None):
    db.add(AuditLog(
        timestamp=int(time.time()),
        actor_id=actor_id,
        actor_username=actor_username,
        action=action,
        detail=detail,
    ))
    # Caller is responsible for committing


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


<<<<<<< HEAD
def _stat_sums_from_row(row) -> dict:
    """Extract SCORING_STATS values from a SQLAlchemy Row or dict."""
    if hasattr(row, "_mapping"):
        return {stat: row._mapping.get(stat, 0) or 0 for stat in SCORING_STATS}
    return {stat: getattr(row, stat, 0) or 0 for stat in SCORING_STATS}
=======
_SCORED_STAT_COLS = list(SCORING_STATS) + ["deaths"]


def _stat_sums_from_row(row) -> dict:
    """Extract scored stat values (SCORING_STATS + deaths) from a SQLAlchemy Row or dict."""
    if hasattr(row, "_mapping"):
        return {stat: row._mapping.get(stat, 0) or 0 for stat in _SCORED_STAT_COLS}
    return {stat: getattr(row, stat, 0) or 0 for stat in _SCORED_STAT_COLS}
>>>>>>> 25cc59e (Initial commit)


def _compute_card_points(stat_sums: dict, card_type: str, weights: dict, rarity: dict, mods: dict) -> float:
    """Apply card_fantasy_score + rarity multiplier for one card."""
    base = card_fantasy_score(stat_sums, weights, mods)
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
    # Pick `count` distinct stats to boost (capped at number of available stats)
<<<<<<< HEAD
    chosen = random.sample(SCORING_STATS, min(count, len(SCORING_STATS)))
=======
    chosen = random.sample(_SCORED_STAT_COLS, min(count, len(_SCORED_STAT_COLS)))
>>>>>>> 25cc59e (Initial commit)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    logger.info("DB: %s", DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    seed_users()
    seed_weights()
    _leagues_env = os.getenv("AUTO_INGEST_LEAGUES", "19368,19369")
    _league_ids = [int(x.strip()) for x in _leagues_env.split(",") if x.strip().isdigit()]
    if _league_ids:
        threading.Thread(target=_ingest_poll_loop, args=(_league_ids,), daemon=True).start()
        logger.info("Ingest poll thread started (interval=%ds)", _INGEST_POLL_INTERVAL)
    threading.Thread(target=_week_maintenance_loop, daemon=True).start()
    logger.info("Week maintenance thread started (interval=%ds)", _WEEK_CHECK_INTERVAL)
    threading.Thread(target=_profile_enrichment_loop, daemon=True).start()
    logger.info("Profile enrichment thread started (interval=%ds)", _ENRICHMENT_INTERVAL)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
_secret_key = os.environ.get("SECRET_KEY", "")
_is_dev = os.getenv("TWITCH_LOCAL_DEV") == "true" or os.getenv("DEBUG", "").lower() == "true"
if not _secret_key:
    if not _is_dev:
        raise RuntimeError(
            "[SECURITY] SECRET_KEY is not set. Set SECRET_KEY in your environment. "
            "To bypass this check in local dev, set DEBUG=true or TWITCH_LOCAL_DEV=true."
        )
    warnings.warn(
        "[SECURITY] SECRET_KEY not set — using insecure default. Only acceptable in local dev.",
        stacklevel=1,
    )
    _secret_key = "dev-secret-change-me"
_https_only = os.getenv("HTTPS_ONLY", "false").lower() == "true"
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key,
    same_site="lax",
    https_only=_https_only,
)
# Twitch extension iframes are served from *.ext-twitch.tv — a different origin.
# All /twitch/* endpoints authenticate via JWT (not cookies), so allow_origins="*"
# is safe: cross-origin requests cannot carry session cookies, so regular
# session-protected endpoints are unaffected.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(twitch_router)


@app.post("/ingest/league/{league_id}")
def ingest_league_endpoint(league_id: int, db=Depends(get_db), admin: dict = Depends(require_admin)):
    ingest_league(league_id)
    run_enrichment()
    seed_cards(league_id)
    _audit(db, "admin_ingest", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"league_id={league_id}")
    db.commit()
    return {"status": "ok", "league_id": league_id}


@app.post("/login")
def login(request: Request, body: LoginBody, db=Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session["user_id"]  = user.id
    request.session["username"] = user.username
    request.session["is_admin"] = user.is_admin
    _audit(db, "user_login", actor_id=user.id, actor_username=user.username)
    db.commit()
    return {"username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0}


@app.post("/register")
def register(request: Request, body: RegisterBody, db=Depends(get_db)):
    if not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', body.email.strip()):
        raise HTTPException(status_code=422, detail="Invalid email address")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        is_admin=False,
        tokens=INITIAL_TOKENS,
        created_at=int(time.time()),
    )
    db.add(user)
    db.flush()  # populate user.id before audit
    _audit(db, "user_register", actor_id=user.id, actor_username=user.username)
    db.commit()
    request.session["user_id"]  = user.id
    request.session["username"] = user.username
    request.session["is_admin"] = user.is_admin
    return {"username": user.username, "is_admin": user.is_admin, "tokens": user.tokens}


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@app.post("/forgot-password")
def forgot_password(body: ForgotPasswordBody, db=Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not user.email:
        # Return 200 regardless to avoid username enumeration
        return {"status": "ok"}

    # Capture values before any session state changes to avoid DetachedInstanceError
    user_email    = user.email
    user_username = user.username
    user_id       = user.id

    temp_password = secrets.token_urlsafe(9)  # ~12 printable chars
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    _audit(db, "password_reset_requested", actor_id=user_id, actor_username=user_username)
    db.commit()

    app_name = os.getenv("APP_NAME", "Kanaliiga Fantasy")
    send_email(
        to_address=user_email,
        subject=f"[{app_name}] Your temporary password",
        body=(
            f"Hi {user_username},\n\n"
            f"A temporary password has been issued for your account:\n\n"
            f"    {temp_password}\n\n"
            f"Log in and go to your Profile to set a new password.\n"
            f"This temporary password will stop working once you change it.\n\n"
            f"If you did not request this, your account is still safe — "
            f"the password was not changed until you log in and update it.\n"
        ),
    )
    return {"status": "ok"}


@app.get("/me")
def me(request: Request, db=Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0,
            "must_change_password": bool(user.must_change_password)}


@app.get("/deck")
def get_deck(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT c.card_type, COUNT(*) as count
        FROM cards c
        WHERE c.owner_id IS NULL
        GROUP BY c.card_type
    """)).fetchall()
    return {r.card_type: r.count for r in results}


@app.post("/draw")
def draw_card(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (user.tokens or 0) <= 0:
        raise HTTPException(status_code=409, detail="Not enough tokens")

    unclaimed = db.execute(text("""
        SELECT c.id, c.card_type, c.player_id, p.name as player_name, p.avatar_url,
               t.name as team_name, t.id as team_id, t.logo_url as team_logo_url
        FROM cards c
        JOIN players p ON p.id = c.player_id
""" + _LATEST_TEAM_SUBQUERY + """
        WHERE c.owner_id IS NULL
    """)).fetchall()

    if not unclaimed:
        raise HTTPException(status_code=404, detail="No cards left in deck")

    # Prefer players the user does not yet own a card for
    owned_player_ids = {r[0] for r in db.execute(
        text("SELECT c.player_id FROM cards c WHERE c.owner_id = :uid"), {"uid": user_id}
    ).fetchall()}
    available = [c for c in unclaimed if c.player_id not in owned_player_ids]
    if not available:
        available = list(unclaimed)  # fallback: user owns all players, allow duplicates

    chosen = random.choice(available)
    card = db.get(Card, chosen.id)
    card.owner_id = user_id
    user.tokens = (user.tokens or 0) - 1

    active_count = db.query(Card).filter(
        Card.owner_id == user_id, Card.is_active == True
    ).count()
    is_active = active_count < ROSTER_LIMIT
    card.is_active = is_active

    # Assign stat modifiers based on rarity config
    weights = {w.key: w.value for w in db.query(Weight).all()}
    _assign_modifiers(db, card, weights)

    _audit(db, "token_draw", actor_id=user_id, actor_username=user.username,
           detail=f"card_id={chosen.id} player={chosen.player_name} rarity={chosen.card_type}")
    db.commit()
    tokens_remaining = user.tokens

    # Load modifiers after commit so IDs are populated
    mods = _card_modifiers_map(db, [card.id]).get(card.id, {})
    return {
        "id": chosen.id,
        "card_type": chosen.card_type,
        "player_id": chosen.player_id,
        "player_name": chosen.player_name,
        "avatar_url": chosen.avatar_url,
        "team_name": chosen.team_name,
        "team_logo_url": chosen.team_logo_url,
        "is_active": is_active,
        "tokens": tokens_remaining,
        "modifiers": _format_modifiers(mods),
    }


@app.get("/weeks")
def get_weeks(db=Depends(get_db)):
    weeks = db.query(Week).order_by(Week.start_time).all()
    return [{"id": w.id, "label": w.label, "start_time": w.start_time,
             "end_time": w.end_time, "is_locked": w.is_locked} for w in weeks]


_LATEST_TEAM_SUBQUERY = """
    LEFT JOIN (
        SELECT s2.player_id, s2.team_id
        FROM player_match_stats s2
        INNER JOIN (
            SELECT player_id, MAX(match_id) as max_match
            FROM player_match_stats
            GROUP BY player_id
        ) mx ON mx.player_id = s2.player_id AND mx.max_match = s2.match_id
    ) latest ON latest.player_id = p.id
    LEFT JOIN teams t ON t.id = latest.team_id
"""


def _build_roster_response(db, user_id: int, week_id: int | None) -> dict:
    """Compute roster data for a user, scoped to the given week (or next editable week)."""
    week = db.get(Week, week_id) if week_id is not None else get_next_editable_week(db)
    now = int(time.time())

    def _week_stat_case(col):
        return (
            f"COALESCE(SUM(CASE WHEN (m.week_override_id = :week_id OR "
            f"(m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we)) "
            f"THEN s.{col} ELSE 0 END), 0) as {col}"
        )
<<<<<<< HEAD
    stat_cols = ",\n                   ".join(_week_stat_case(col) for col in SCORING_STATS)
=======
    stat_cols = ",\n                   ".join(_week_stat_case(col) for col in _SCORED_STAT_COLS)
>>>>>>> 25cc59e (Initial commit)

    if week and week.is_locked:
        results = db.execute(text(f"""
            SELECT c.id, c.card_type, 1 as is_active,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.name as team_name, t.logo_url as team_logo_url,
                   {stat_cols}
            FROM weekly_roster_entries wre
            JOIN cards c ON c.id = wre.card_id
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE wre.week_id = :week_id AND wre.user_id = :user_id
            GROUP BY c.id, c.card_type, p.id, p.name, p.avatar_url, t.name, t.logo_url
        """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time,
               "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active, bench = cards, []
    else:
        ws = week.start_time if week else 0
        we = week.end_time if week else now
        results = db.execute(text(f"""
            SELECT c.id, c.card_type, c.is_active,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.name as team_name, t.logo_url as team_logo_url,
                   {stat_cols}
            FROM cards c
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE c.owner_id = :user_id
            GROUP BY c.id, c.card_type, c.is_active, p.id, p.name, p.avatar_url, t.name, t.logo_url
            ORDER BY c.is_active DESC
        """), {"ws": ws, "we": we, "week_id": week.id if week else -1, "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active = [c for c in cards if c["is_active"]]
        bench  = [c for c in cards if not c["is_active"]]

    card_ids = [c["id"] for c in cards]
    modifiers_map = _card_modifiers_map(db, card_ids)
    weights, rarity = _load_weights(db)

    for c in cards:
        mods = modifiers_map.get(c["id"], {})
        c["modifiers"] = _format_modifiers(mods)
<<<<<<< HEAD
        stat_sums = {stat: c.get(stat, 0) or 0 for stat in SCORING_STATS}
=======
        stat_sums = {stat: c.get(stat, 0) or 0 for stat in _SCORED_STAT_COLS}
>>>>>>> 25cc59e (Initial commit)
        c["total_points"] = _compute_card_points(stat_sums, c["card_type"], weights, rarity, mods)

    active.sort(key=lambda c: c["total_points"], reverse=True)
    bench.sort(key=lambda c: c["total_points"], reverse=True)

    user = db.get(User, user_id)
    tokens = user.tokens if user and user.tokens is not None else 0

    season_pts_rows = db.execute(text("""
        SELECT c.id as card_id, c.card_type,
<<<<<<< HEAD
               COALESCE(SUM(s.kills), 0)        as kills,
               COALESCE(SUM(s.assists), 0)      as assists,
               COALESCE(SUM(s.deaths), 0)       as deaths,
               COALESCE(SUM(s.gold_per_min), 0) as gold_per_min,
               COALESCE(SUM(s.obs_placed), 0)   as obs_placed,
               COALESCE(SUM(s.sen_placed), 0)   as sen_placed,
               COALESCE(SUM(s.tower_damage), 0) as tower_damage
=======
               COALESCE(SUM(s.deaths), 0)                    as deaths,
               COALESCE(SUM(s.kills), 0)                     as kills,
               COALESCE(SUM(s.last_hits), 0)                 as last_hits,
               COALESCE(SUM(s.denies), 0)                    as denies,
               COALESCE(SUM(s.gold_per_min), 0)              as gold_per_min,
               COALESCE(SUM(s.obs_placed), 0)                as obs_placed,
               COALESCE(SUM(s.towers_killed), 0)             as towers_killed,
               COALESCE(SUM(s.roshan_kills), 0)              as roshan_kills,
               COALESCE(SUM(s.teamfight_participation), 0)   as teamfight_participation,
               COALESCE(SUM(s.camps_stacked), 0)             as camps_stacked,
               COALESCE(SUM(s.rune_pickups), 0)              as rune_pickups,
               COALESCE(SUM(s.firstblood_claimed), 0)        as firstblood_claimed,
               COALESCE(SUM(s.stuns), 0)                     as stuns
>>>>>>> 25cc59e (Initial commit)
        FROM weekly_roster_entries wre
        JOIN weeks wk ON wk.id = wre.week_id
        JOIN cards c ON c.id = wre.card_id
        JOIN player_match_stats s ON s.player_id = c.player_id
        JOIN matches m ON m.match_id = s.match_id
        WHERE wre.user_id = :user_id
          AND wk.is_locked = 1
          AND (m.week_override_id = wk.id OR (m.week_override_id IS NULL AND m.start_time BETWEEN wk.start_time AND wk.end_time))
        GROUP BY c.id, c.card_type
    """), {"user_id": user_id}).fetchall()

    season_card_ids = [r.card_id for r in season_pts_rows]
    season_mods = _card_modifiers_map(db, season_card_ids)
    season_points = sum(
        _compute_card_points(_stat_sums_from_row(row), row.card_type, weights, rarity,
                             season_mods.get(row.card_id, {}))
        for row in season_pts_rows
    )

    return {
        "active": active, "bench": bench,
        "combined_value": sum(c["total_points"] for c in active),
        "tokens": tokens,
        "season_points": season_points,
        "week": {"id": week.id, "label": week.label, "is_locked": week.is_locked,
                 "start_time": week.start_time, "end_time": week.end_time} if week else None,
    }


@app.get("/roster/{user_id}")
def get_roster(user_id: int, week_id: int = None, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    if user_id != current_user["user_id"] and not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Cannot view another user's roster")
    return _build_roster_response(db, user_id, week_id)


@app.get("/cards/{card_id}")
def get_card(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")
    player = db.get(Player, card.player_id)
    # Resolve latest team for this player
    team_row = db.execute(text("""
        SELECT t.name, t.logo_url
        FROM player_match_stats s
        JOIN teams t ON t.id = s.team_id
        WHERE s.player_id = :pid
        ORDER BY s.match_id DESC LIMIT 1
    """), {"pid": card.player_id}).first()
    mods = _card_modifiers_map(db, [card_id]).get(card_id, {})
    return {
        "id": card.id,
        "card_type": card.card_type,
        "player_name": player.name if player else None,
        "avatar_url": player.avatar_url if player else None,
        "team_name": team_row.name if team_row else None,
        "team_logo_url": team_row.logo_url if team_row else None,
        "modifiers": _format_modifiers(mods),
    }


@app.get("/cards/{card_id}/image")
def get_card_image(card_id: int, db=Depends(get_db)):
    """Generate and return a PNG image for this card."""
    if not PIL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Image generation unavailable (Pillow not installed)")
    result = db.execute(text("""
        SELECT c.card_type, p.name as player_name, p.avatar_url,
               t.name as team_name, t.logo_url as team_logo_url
        FROM cards c
        JOIN players p ON p.id = c.player_id
""" + _LATEST_TEAM_SUBQUERY + """
        WHERE c.id = :card_id
    """), {"card_id": card_id}).first()
    if not result:
        raise HTTPException(status_code=404, detail="Card not found")
    mods: dict = _card_modifiers_dict_for_image(db, card_id)
    img = generate_card_image(
        card_type=result.card_type,
        player_name=result.player_name,
        avatar_url=result.avatar_url,
        team_name=result.team_name,
        team_logo_url=result.team_logo_url,
        card_modifiers=mods,
    )
    buf = io.BytesIO()
    # Faster encode for interactive /draw reveal (size vs latency tradeoff)
    img.save(buf, format="PNG", optimize=False, compress_level=5)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.post("/roster/{card_id}/reroll")
def reroll_modifiers(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (user.tokens or 0) <= 0:
        raise HTTPException(status_code=409, detail="Not enough tokens")
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")

    # Raw DELETE avoids ORM bulk-delete session sync quirks (SA 2.x)
    db.execute(text("DELETE FROM card_modifiers WHERE card_id = :cid"), {"cid": card_id})
    db.flush()

    # Assign new modifiers using same logic as draw
    weights = {w.key: w.value for w in db.query(Weight).all()}
    _assign_modifiers(db, card, weights)

    user.tokens = (user.tokens or 0) - 1
    _audit(db, "reroll_modifiers", actor_id=user_id, actor_username=user.username,
           detail=f"card_id={card_id} rarity={card.card_type}")
    db.commit()
    tokens_remaining = user.tokens

    mods = _card_modifiers_map(db, [card_id]).get(card_id, {})
    return {
        "modifiers": _format_modifiers(mods),
        "tokens": tokens_remaining,
    }


@app.post("/roster/{card_id}/activate")
def activate_card(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")
    if card.is_active:
        raise HTTPException(status_code=409, detail="Card already active")

    active_count = db.query(Card).filter(
        Card.owner_id == user_id, Card.is_active == True
    ).count()
    if active_count >= ROSTER_LIMIT:
        raise HTTPException(status_code=409, detail=f"Roster full ({ROSTER_LIMIT} cards max)")

    duplicate = db.query(Card).filter(
        Card.owner_id == user_id,
        Card.player_id == card.player_id,
        Card.is_active == True,
        Card.id != card_id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="A card for this player is already active")

    card.is_active = True
    db.commit()
    return {"status": "ok", "card_id": card_id}


@app.post("/roster/{card_id}/deactivate")
def deactivate_card(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")
    card.is_active = False
    db.commit()
    return {"status": "ok", "card_id": card_id}


@app.get("/players")
def list_players(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url,
               t.name as team_name, t.id as team_id,
               COUNT(s.id) as matches,
               COALESCE(AVG(s.fantasy_points), 0) as avg_points,
               COALESCE(SUM(s.fantasy_points), 0) as total_points
        FROM players p
        LEFT JOIN player_match_stats s ON s.player_id = p.id
        LEFT JOIN (
            SELECT s2.player_id, s2.team_id
            FROM player_match_stats s2
            INNER JOIN (
                SELECT player_id, MAX(match_id) as max_match
                FROM player_match_stats
                GROUP BY player_id
            ) mx ON mx.player_id = s2.player_id AND mx.max_match = s2.match_id
        ) latest ON latest.player_id = p.id
        LEFT JOIN teams t ON t.id = latest.team_id
        GROUP BY p.id, p.name, p.avatar_url, t.name, t.id
        ORDER BY total_points DESC
    """)).fetchall()
    return [dict(r._mapping) for r in results]


@app.get("/players/{player_id}")
def get_player(player_id: int, db=Depends(get_db)):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    stats = db.execute(text("""
        SELECT s.match_id, m.start_time, s.fantasy_points,
<<<<<<< HEAD
               s.kills, s.assists, s.deaths, s.gold_per_min,
               s.obs_placed, s.sen_placed, s.tower_damage,
=======
               s.kills, s.assists, s.deaths, s.gold_per_min, s.obs_placed,
               s.last_hits, s.denies, s.towers_killed, s.roshan_kills,
               s.teamfight_participation, s.camps_stacked, s.rune_pickups,
               s.firstblood_claimed, s.stuns,
>>>>>>> 25cc59e (Initial commit)
               t.id as team_id, t.name as team_name
        FROM player_match_stats s
        LEFT JOIN matches m ON m.match_id = s.match_id
        LEFT JOIN teams t ON t.id = s.team_id
        WHERE s.player_id = :player_id
        ORDER BY COALESCE(m.start_time, 0) DESC
    """), {"player_id": player_id}).fetchall()

    history = [dict(r._mapping) for r in stats]
    matches = len(history)
    total_points = sum(r["fantasy_points"] for r in history)
    avg_points = total_points / matches if matches else 0
    best = max(history, key=lambda r: r["fantasy_points"], default=None)

    team_name = history[0]["team_name"] if history else None
    team_id = history[0]["team_id"] if history else None

    return {
        "id": player.id,
        "name": player.name,
        "avatar_url": player.avatar_url,
        "team_name": team_name,
        "team_id": team_id,
        "matches": matches,
        "avg_points": avg_points,
        "total_points": total_points,
        "best_match": {
            "match_id": best["match_id"],
            "fantasy_points": best["fantasy_points"],
            "start_time": best["start_time"],
        } if best else None,
        "match_history": history,
    }


@app.get("/players/{player_id}/profile")
def get_player_profile(player_id: int, db=Depends(get_db)):
    profile = db.get(PlayerProfile, player_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    facts = json.loads(profile.facts_json) if profile.facts_json else None
    return {
        "player_id":        player_id,
        "facts":            facts,
        "bio_text":         profile.bio_text,
        "facts_fetched_at": profile.facts_fetched_at,
        "bio_generated_at": profile.bio_generated_at,
    }


@app.post("/admin/enrich-profiles")
def admin_enrich_profiles(db=Depends(get_db), admin: dict = Depends(require_admin)):
    result = run_profile_enrichment()
    _audit(db, "admin_enrich_profiles", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"enriched={result['enriched']} skipped={result['skipped']} errors={result['errors']}")
    db.commit()
    return result


class TopUpCardsBody(BaseModel):
    league_id: int


@app.post("/admin/top-up-cards")
def top_up_cards(body: TopUpCardsBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Add one full card batch (1L/2E/4R/8C per player) as a new generation to the unowned pool."""
    from sqlalchemy import func
    max_gen = db.query(func.max(Card.generation)).filter(
        Card.league_id == body.league_id
    ).scalar() or 1
    next_gen = max_gen + 1
    seed_cards(body.league_id, generation=next_gen)
    _audit(db, "admin_top_up_cards", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"league_id={body.league_id} generation={next_gen}")
    db.commit()
    return {"league_id": body.league_id, "generation_added": next_gen}


@app.get("/teams")
def list_teams(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT t.id, t.name,
               COUNT(DISTINCT s.match_id) as matches,
               COUNT(DISTINCT s.player_id) as player_count
        FROM teams t
        LEFT JOIN player_match_stats s ON s.team_id = t.id
        GROUP BY t.id, t.name
        ORDER BY matches DESC, t.name
    """)).fetchall()
    return [dict(r._mapping) for r in results]


@app.get("/teams/{team_id}")
def get_team(team_id: int, db=Depends(get_db)):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    players = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url,
               COUNT(s.id) as matches,
               COALESCE(AVG(s.fantasy_points), 0) as avg_points,
               COALESCE(SUM(s.fantasy_points), 0) as total_points
        FROM players p
        JOIN player_match_stats s ON s.player_id = p.id AND s.team_id = :team_id
        GROUP BY p.id, p.name, p.avatar_url
        ORDER BY total_points DESC
    """), {"team_id": team_id}).fetchall()

    match_count = db.execute(text("""
        SELECT COUNT(DISTINCT match_id) as cnt FROM player_match_stats WHERE team_id = :team_id
    """), {"team_id": team_id}).scalar()

    return {
        "id": team.id,
        "name": team.name,
        "matches": match_count or 0,
        "players": [dict(r._mapping) for r in players],
    }


@app.get("/top")
def top_performances(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url, s.fantasy_points
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        ORDER BY s.fantasy_points DESC
        LIMIT 10
    """)).fetchall()
    return [dict(r._mapping) for r in results]


@app.get("/leaderboard")
def leaderboard(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url, COUNT(s.id) as matches, AVG(s.fantasy_points) as avg_points
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        GROUP BY p.id, p.name, p.avatar_url
        ORDER BY avg_points DESC
    """)).fetchall()
    return [dict(r._mapping) for r in results]


@app.get("/leaderboard/roster")
def roster_leaderboard(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT u.username,
               COALESCE(owned.total, 0) as total_cards,
               COALESCE(SUM(pts.total), 0) as roster_value
        FROM users u
        LEFT JOIN (
            SELECT owner_id, COUNT(*) as total
            FROM cards
            GROUP BY owner_id
        ) owned ON owned.owner_id = u.id
        LEFT JOIN cards c ON c.owner_id = u.id AND c.is_active = true
        LEFT JOIN (
            SELECT player_id, SUM(fantasy_points) as total
            FROM player_match_stats
            GROUP BY player_id
        ) pts ON pts.player_id = c.player_id
        WHERE u.is_tester = 0
        GROUP BY u.id, u.username, owned.total
        ORDER BY roster_value DESC
    """)).fetchall()
    return [dict(r._mapping) for r in results]


@app.get("/weights")
def get_weights(db=Depends(get_db)):
    weights = db.query(Weight).order_by(Weight.key).all()
    return [{"key": w.key, "label": w.label, "value": w.value} for w in weights]


_SIMULATE_DOCS = {
    "endpoint": "POST /simulate/{match_id}",
    "description": (
        "Simulate fantasy point scores for all players in a given match using custom "
<<<<<<< HEAD
        "per-stat weights. Any stat weight not provided falls back to the current "
        "season default stored in the database. No authentication required."
=======
        "per-stat weights. Any weight not provided falls back to the current season "
        "default stored in the database. No authentication required."
>>>>>>> 25cc59e (Initial commit)
    ),
    "path_parameters": {
        "match_id": "integer — OpenDota match ID that has been ingested into the system",
    },
    "request_body": {
        "content_type": "application/json",
        "fields": {
<<<<<<< HEAD
            "kills":        "float | omit  — points per kill (default from DB)",
            "assists":      "float | omit  — points per assist (default from DB)",
            "deaths":       "float | omit  — points per death, typically negative (default from DB)",
            "gold_per_min": "float | omit  — points per GPM (default from DB)",
            "obs_placed":   "float | omit  — points per observer ward placed (default from DB)",
            "sen_placed":   "float | omit  — points per sentry ward placed (default from DB)",
            "tower_damage": "float | omit  — points per tower damage dealt (default from DB)",
        },
        "example": {
            "kills": 2.0,
            "deaths": -1.5,
            "gold_per_min": 0.05,
=======
            "kills":                    "float | omit — points per kill (default from DB)",
            "last_hits":                "float | omit — points per last hit (default from DB)",
            "denies":                   "float | omit — points per deny (default from DB)",
            "gold_per_min":             "float | omit — points per GPM (default from DB)",
            "obs_placed":               "float | omit — points per observer ward placed (default from DB)",
            "towers_killed":            "float | omit — points per tower destroyed (default from DB)",
            "roshan_kills":             "float | omit — points per Roshan kill (default from DB)",
            "teamfight_participation":  "float | omit — points for 100% teamfight participation (default from DB)",
            "camps_stacked":            "float | omit — points per camp stacked (default from DB)",
            "rune_pickups":             "float | omit — points per rune picked up (default from DB)",
            "firstblood_claimed":       "float | omit — points for claiming first blood (default from DB)",
            "stuns":                    "float | omit — points per second of stuns applied (default from DB)",
            "death_pool":               "float | omit — base points awarded for 0 deaths (default from DB)",
            "death_deduction":          "float | omit — points deducted per death (default from DB)",
        },
        "example": {
            "kills": 0.5,
            "death_pool": 5.0,
            "death_deduction": 0.5,
>>>>>>> 25cc59e (Initial commit)
        },
    },
    "response": {
        "match_id": "integer — the queried match ID",
        "weights_used": "object — the full weight map applied (merged DB defaults + overrides)",
        "players": [
            {
                "player_id": "integer",
                "player_name": "string",
                "team_name": "string | null",
                "fantasy_points": "float — score under the provided weights",
                "stats": {
                    "kills": "integer",
<<<<<<< HEAD
                    "assists": "integer",
                    "deaths": "integer",
                    "gold_per_min": "float",
                    "obs_placed": "integer",
                    "sen_placed": "integer",
                    "tower_damage": "integer",
=======
                    "deaths": "integer",
                    "last_hits": "integer",
                    "denies": "integer",
                    "gold_per_min": "float",
                    "obs_placed": "integer",
                    "towers_killed": "integer",
                    "roshan_kills": "integer",
                    "teamfight_participation": "float",
                    "camps_stacked": "integer",
                    "rune_pickups": "integer",
                    "firstblood_claimed": "integer",
                    "stuns": "float",
>>>>>>> 25cc59e (Initial commit)
                },
            }
        ],
    },
    "errors": {
        "404": "Match not found — match_id has not been ingested",
        "422": "Validation error — non-numeric weight value supplied",
    },
}


@app.get("/simulate")
def simulate_docs():
    """Human- and machine-readable documentation for the weight simulation endpoint."""
    return _SIMULATE_DOCS


@app.post("/simulate/{match_id}")
def simulate_match(match_id: int, db=Depends(get_db), body: SimulateBody = None):
    """Return fantasy scores for every player in a match under custom weights.

    Any weight not supplied in the request body falls back to the current DB default.
    No authentication required so statisticians can call this without an account.
    """
    if body is None:
        body = SimulateBody()

    # Verify match exists
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

<<<<<<< HEAD
    # Load DB weights and apply overrides for scoring stats only
    db_weights = {w.key: w.value for w in db.query(Weight).all()}
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    weights_used = {stat: overrides.get(stat, db_weights.get(stat, 0.0)) for stat in SCORING_STATS}
=======
    # Load DB weights and apply overrides for all scoring weight keys
    db_weights = {w.key: w.value for w in db.query(Weight).all()}
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    all_weight_keys = list(SCORING_STATS) + ["death_pool", "death_deduction"]
    weights_used = {k: overrides.get(k, db_weights.get(k, 0.0)) for k in all_weight_keys}
>>>>>>> 25cc59e (Initial commit)

    # Fetch all player stats for this match with player and team names
    rows = db.execute(text("""
        SELECT s.player_id, p.name as player_name,
               t.name as team_name,
<<<<<<< HEAD
               s.kills, s.assists, s.deaths,
               s.gold_per_min, s.obs_placed, s.sen_placed, s.tower_damage
=======
               s.kills, s.deaths, s.gold_per_min, s.obs_placed,
               s.last_hits, s.denies, s.towers_killed, s.roshan_kills,
               s.teamfight_participation, s.camps_stacked, s.rune_pickups,
               s.firstblood_claimed, s.stuns
>>>>>>> 25cc59e (Initial commit)
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        LEFT JOIN teams t ON t.id = s.team_id
        WHERE s.match_id = :match_id
    """), {"match_id": match_id}).fetchall()

    players = []
    for r in rows:
        stats = {
            "kills": r.kills or 0,
<<<<<<< HEAD
            "assists": r.assists or 0,
            "deaths": r.deaths or 0,
            "gold_per_min": r.gold_per_min or 0,
            "obs_placed": r.obs_placed or 0,
            "sen_placed": r.sen_placed or 0,
            "tower_damage": r.tower_damage or 0,
=======
            "deaths": r.deaths or 0,
            "gold_per_min": r.gold_per_min or 0,
            "obs_placed": r.obs_placed or 0,
            "last_hits": r.last_hits or 0,
            "denies": r.denies or 0,
            "towers_killed": r.towers_killed or 0,
            "roshan_kills": r.roshan_kills or 0,
            "teamfight_participation": r.teamfight_participation or 0.0,
            "camps_stacked": r.camps_stacked or 0,
            "rune_pickups": r.rune_pickups or 0,
            "firstblood_claimed": r.firstblood_claimed or 0,
            "stuns": r.stuns or 0.0,
>>>>>>> 25cc59e (Initial commit)
        }
        players.append({
            "player_id": r.player_id,
            "player_name": r.player_name,
            "team_name": r.team_name,
            "fantasy_points": round(fantasy_score(stats, weights_used), 2),
            "stats": stats,
        })

    players.sort(key=lambda p: p["fantasy_points"], reverse=True)

    return {
        "match_id": match_id,
        "weights_used": weights_used,
        "players": players,
    }


@app.get("/users")
def list_users(db=Depends(get_db), _: dict = Depends(require_admin)):
    users = db.query(User).order_by(User.username).all()
    return [{"id": u.id, "username": u.username, "tokens": u.tokens if u.tokens is not None else 0,
             "is_tester": bool(u.is_tester)}
            for u in users]


@app.post("/users/{user_id}/toggle-tester")
def toggle_tester(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_tester = not bool(user.is_tester)
    _audit(db, "admin_toggle_tester", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"{user.username} is_tester={user.is_tester}")
    db.commit()
    return {"user_id": user.id, "username": user.username, "is_tester": user.is_tester}


@app.post("/grant-tokens")
def grant_tokens(body: GrantTokensBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    target = db.get(User, body.target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount < 1:
        raise HTTPException(status_code=422, detail="Amount must be at least 1")
    target.tokens = (target.tokens or 0) + body.amount
    _audit(db, "admin_grant_tokens", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"target={target.username} amount={body.amount}")
    db.commit()
    return {"username": target.username, "tokens": target.tokens}


@app.post("/recalculate")
def recalculate(db=Depends(get_db), admin: dict = Depends(require_admin)):
    weights = {w.key: w.value for w in db.query(Weight).all()}
    stats = db.query(PlayerMatchStats).all()
    for stat in stats:
        p = {
<<<<<<< HEAD
            "kills": stat.kills,
            "assists": stat.assists,
            "deaths": stat.deaths,
            "gold_per_min": stat.gold_per_min,
            "obs_placed": stat.obs_placed,
            "sen_placed": stat.sen_placed,
            "tower_damage": stat.tower_damage,
=======
            "kills": stat.kills or 0,
            "deaths": stat.deaths or 0,
            "gold_per_min": stat.gold_per_min or 0,
            "obs_placed": stat.obs_placed or 0,
            "last_hits": stat.last_hits or 0,
            "denies": stat.denies or 0,
            "towers_killed": stat.towers_killed or 0,
            "roshan_kills": stat.roshan_kills or 0,
            "teamfight_participation": stat.teamfight_participation or 0.0,
            "camps_stacked": stat.camps_stacked or 0,
            "rune_pickups": stat.rune_pickups or 0,
            "firstblood_claimed": stat.firstblood_claimed or 0,
            "stuns": stat.stuns or 0.0,
>>>>>>> 25cc59e (Initial commit)
        }
        stat.fantasy_points = fantasy_score(p, weights)
    _audit(db, "admin_recalculate", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"records={len(stats)}")
    db.commit()
    return {"status": "ok", "recalculated": len(stats)}


@app.get("/schedule")
def schedule_endpoint(db=Depends(get_db)):
    return get_schedule(db)


@app.post("/schedule/refresh")
def schedule_refresh(db=Depends(get_db), admin: dict = Depends(require_admin)):
    bust_cache()
    _audit(db, "admin_schedule_refresh", actor_id=admin["user_id"], actor_username=admin["username"])
    db.commit()
    return get_schedule(db)


@app.get("/schedule/debug")
def schedule_debug(_: dict = Depends(require_admin)):
    url = os.getenv("SCHEDULE_SHEET_URL", SCHEDULE_SHEET_URL)
    result = {"url_set": bool(url), "url_prefix": url[:60] + "..." if len(url) > 60 else url}

    if not url:
        result["error"] = "SCHEDULE_SHEET_URL is not set"
        return result

    try:
        import requests as req
        res = req.get(url, timeout=15, allow_redirects=True)
        result["status_code"] = res.status_code
        result["content_type"] = res.headers.get("content-type", "")
        result["response_length"] = len(res.text)
        result["first_200_chars"] = res.text[:200]
    except Exception as e:
        result["error"] = str(e)

    return result


@app.put("/matches/{match_id}/week")
def set_match_week(match_id: int, body: MatchWeekBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Manually override which fantasy week a match counts for.
    Set week_id to null to clear the override and revert to time-based assignment."""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if body.week_id is not None:
        week = db.get(Week, body.week_id)
        if not week:
            raise HTTPException(status_code=404, detail="Week not found")
    old_override = match.week_override_id
    match.week_override_id = body.week_id
    _audit(db, "admin_set_match_week", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match_id={match_id} old_override={old_override} new_override={body.week_id}")
    db.commit()
    return {"match_id": match_id, "week_override_id": body.week_id}


@app.post("/admin/sync-match-weeks")
def sync_match_weeks(db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Auto-assign week_override_id on matches whose actual play date differs from their
    scheduled week in the Google Sheet. Matches already in the correct week get their
    override cleared (set to NULL). Uses ±3-day proximity to the series scheduled date
    to disambiguate when two teams play each other more than once in a season."""
    # Build week lookup: normalised label -> Week
    db_weeks = db.query(Week).all()
    week_by_label = {w.label.lower().strip(): w for w in db_weeks}

    schedule_data = get_schedule(db)

    changes = []
    errors = []

    for sheet_week in schedule_data.get("weeks", []):
        week_label = (sheet_week.get("label") or "").lower().strip()
        target_week = week_by_label.get(week_label)
        if not target_week:
            errors.append(f"No DB week found for sheet label '{sheet_week.get('label')}'")
            continue

        for series in sheet_week["div1"] + sheet_week["div2"]:
            team1_id = series.get("team1_id")
            team2_id = series.get("team2_id")
            if not team1_id or not team2_id:
                continue

            # Convert scheduled series date to Unix timestamp for proximity matching
            series_ts = None
            dt_iso = series.get("datetime_iso")
            if dt_iso:
                try:
                    from datetime import datetime
                    series_ts = int(datetime.fromisoformat(dt_iso).timestamp())
                except (ValueError, OSError):
                    pass

            rows = db.execute(text("""
                SELECT match_id, start_time, week_override_id FROM matches
                WHERE (radiant_team_id = :a AND dire_team_id = :b)
                   OR (radiant_team_id = :b AND dire_team_id = :a)
            """), {"a": team1_id, "b": team2_id}).fetchall()

            for row in rows:
                # If we have a scheduled date, skip matches more than 3 days away —
                # they belong to a different series between the same two teams.
                if series_ts and row.start_time:
                    if abs(row.start_time - series_ts) > 3 * 86400:
                        continue

                in_target_by_time = (
                    row.start_time is not None
                    and target_week.start_time <= row.start_time <= target_week.end_time
                )
                # Correct state: no override needed when time already lands in target week
                new_override = None if in_target_by_time else target_week.id

                # Skip if already in desired state
                if new_override == row.week_override_id:
                    continue

                match_obj = db.get(Match, row.match_id)
                old = match_obj.week_override_id
                match_obj.week_override_id = new_override
                changes.append({
                    "match_id": row.match_id,
                    "old_override": old,
                    "new_override": new_override,
                    "target_week": target_week.label,
                    "teams": f"{series.get('team1')} vs {series.get('team2')}",
                })

    if changes:
        _audit(db, "admin_sync_match_weeks", actor_id=admin["user_id"], actor_username=admin["username"],
               detail=f"changes={len(changes)}")
        db.commit()

    return {"changes": changes, "errors": errors}


@app.post("/admin/sync-toornament")
def admin_sync_toornament(db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Push current series results to toornament.com. Idempotent — safe to call repeatedly."""
    result = sync_toornament_results(db)
    _audit(db, "admin_sync_toornament", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"pushed={result['pushed']} skipped={result['skipped']} errors={len(result['errors'])}")
    db.commit()
    return result


@app.get("/profile/{user_id}")
def get_profile(user_id: int, db=Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    result = {"id": user.id, "username": user.username, "player_id": user.player_id,
              "player_name": None, "player_avatar_url": None,
              "twitch_linked": bool(user.twitch_user_id)}
    if user.player_id:
        player = db.get(Player, user.player_id)
        if player:
            result["player_name"] = player.name
            result["player_avatar_url"] = player.avatar_url
    return result


@app.put("/profile/username")
def update_username(body: UpdateUsernameBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="Username cannot be empty")
    existing = db.query(User).filter(User.username == username, User.id != user_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")
    user.username = username
    db.commit()
    return {"username": username}


@app.put("/profile/player-id")
def update_player_id(body: UpdatePlayerIdBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.player_id = body.player_id
    db.commit()
    result = {"player_id": body.player_id, "player_name": None, "player_avatar_url": None}
    if body.player_id:
        player = db.get(Player, body.player_id)
        if player:
            result["player_name"] = player.name
            result["player_avatar_url"] = player.avatar_url
    return result


def _leaderboard_rows(db, rows) -> list[dict]:
    """Compute leaderboard totals using per-stat card_fantasy_score().

    rows must have: user_id, username, card_id, card_type, player_name,
<<<<<<< HEAD
                    kills, assists, deaths, gold_per_min, obs_placed, sen_placed, tower_damage
=======
                    deaths, kills, last_hits, denies, gold_per_min, obs_placed,
                    towers_killed, roshan_kills, teamfight_participation,
                    camps_stacked, rune_pickups, firstblood_claimed, stuns
>>>>>>> 25cc59e (Initial commit)
    """
    weights, rarity = _load_weights(db)
    card_ids = list({r.card_id for r in rows if r.card_id})
    mods_map = _card_modifiers_map(db, card_ids)

    totals: dict[int, float] = {}
    usernames: dict[int, str] = {}
    cards_by_user: dict[int, list] = {}

    for r in rows:
        uid = r.user_id
        usernames[uid] = r.username
        totals.setdefault(uid, 0.0)
        cards_by_user.setdefault(uid, [])
        if not r.card_id:
            continue
        stat_sums = _stat_sums_from_row(r)
        mods = mods_map.get(r.card_id, {})
        card_pts = _compute_card_points(stat_sums, r.card_type, weights, rarity, mods)
        totals[uid] += card_pts
        cards_by_user[uid].append({
            "card_id": r.card_id,
            "card_type": r.card_type,
            "player_name": getattr(r, "player_name", None) or "",
            "points": round(card_pts, 2),
        })

    return sorted(
        [{"id": uid, "username": usernames[uid], "points": round(totals[uid], 2),
          "cards": sorted(cards_by_user.get(uid, []), key=lambda c: c["points"], reverse=True)}
         for uid in totals],
        key=lambda x: x["points"], reverse=True,
    )


@app.get("/leaderboard/season")
def season_leaderboard(db=Depends(get_db)):
    rows = db.execute(text("""
        SELECT u.id as user_id, u.username,
               c.id as card_id, c.card_type,
               p.name as player_name,
<<<<<<< HEAD
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.kills        ELSE 0 END), 0) as kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.assists      ELSE 0 END), 0) as assists,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.deaths       ELSE 0 END), 0) as deaths,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.gold_per_min ELSE 0 END), 0) as gold_per_min,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.obs_placed   ELSE 0 END), 0) as obs_placed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.sen_placed   ELSE 0 END), 0) as sen_placed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.tower_damage ELSE 0 END), 0) as tower_damage
=======
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.deaths                  ELSE 0 END), 0) as deaths,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.kills                   ELSE 0 END), 0) as kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.last_hits               ELSE 0 END), 0) as last_hits,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.denies                  ELSE 0 END), 0) as denies,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.gold_per_min            ELSE 0 END), 0) as gold_per_min,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.obs_placed              ELSE 0 END), 0) as obs_placed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.towers_killed           ELSE 0 END), 0) as towers_killed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.roshan_kills            ELSE 0 END), 0) as roshan_kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.teamfight_participation ELSE 0 END), 0) as teamfight_participation,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.camps_stacked           ELSE 0 END), 0) as camps_stacked,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.rune_pickups            ELSE 0 END), 0) as rune_pickups,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.firstblood_claimed      ELSE 0 END), 0) as firstblood_claimed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.stuns                   ELSE 0 END), 0) as stuns
>>>>>>> 25cc59e (Initial commit)
        FROM users u
        LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id
        LEFT JOIN weeks wk ON wk.id = wre.week_id AND wk.is_locked = 1
        LEFT JOIN cards c ON c.id = wre.card_id
        LEFT JOIN players p ON p.id = c.player_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        LEFT JOIN matches m ON m.match_id = s.match_id
            AND (m.week_override_id = wk.id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN wk.start_time AND wk.end_time))
        WHERE u.is_tester = 0
        GROUP BY u.id, u.username, c.id, c.card_type, p.name
    """)).fetchall()
    result = _leaderboard_rows(db, rows)
    return [{"id": r["id"], "username": r["username"], "season_points": r["points"],
             "cards": r["cards"]} for r in result]


@app.get("/leaderboard/weekly")
def weekly_leaderboard(week_id: int, db=Depends(get_db)):
    week = db.get(Week, week_id)
    if not week:
        raise HTTPException(status_code=404, detail="Week not found")
    rows = db.execute(text("""
        SELECT u.id as user_id, u.username,
               c.id as card_id, c.card_type,
               p.name as player_name,
<<<<<<< HEAD
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.kills        ELSE 0 END), 0) as kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.assists      ELSE 0 END), 0) as assists,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.deaths       ELSE 0 END), 0) as deaths,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.gold_per_min ELSE 0 END), 0) as gold_per_min,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.obs_placed   ELSE 0 END), 0) as obs_placed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.sen_placed   ELSE 0 END), 0) as sen_placed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.tower_damage ELSE 0 END), 0) as tower_damage
=======
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.deaths                  ELSE 0 END), 0) as deaths,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.kills                   ELSE 0 END), 0) as kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.last_hits               ELSE 0 END), 0) as last_hits,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.denies                  ELSE 0 END), 0) as denies,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.gold_per_min            ELSE 0 END), 0) as gold_per_min,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.obs_placed              ELSE 0 END), 0) as obs_placed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.towers_killed           ELSE 0 END), 0) as towers_killed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.roshan_kills            ELSE 0 END), 0) as roshan_kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.teamfight_participation ELSE 0 END), 0) as teamfight_participation,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.camps_stacked           ELSE 0 END), 0) as camps_stacked,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.rune_pickups            ELSE 0 END), 0) as rune_pickups,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.firstblood_claimed      ELSE 0 END), 0) as firstblood_claimed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.stuns                   ELSE 0 END), 0) as stuns
>>>>>>> 25cc59e (Initial commit)
        FROM users u
        LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id AND wre.week_id = :week_id
        LEFT JOIN cards c ON c.id = wre.card_id
        LEFT JOIN players p ON p.id = c.player_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        LEFT JOIN matches m ON m.match_id = s.match_id
            AND (m.week_override_id = :week_id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
        WHERE u.is_tester = 0
        GROUP BY u.id, u.username, c.id, c.card_type, p.name
    """), {"week_id": week_id, "ws": week.start_time, "we": week.end_time}).fetchall()
    result = _leaderboard_rows(db, rows)
    return [{"id": r["id"], "username": r["username"], "week_points": r["points"],
             "cards": r["cards"]} for r in result]


@app.put("/profile/password")
def change_password(body: ChangePasswordBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user = db.get(User, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=422, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    return {"status": "ok"}


@app.post("/codes")
def create_code(body: CreateCodeBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="Code cannot be empty")
    if body.token_amount < 1:
        raise HTTPException(status_code=422, detail="Token amount must be at least 1")
    if db.query(PromoCode).filter(PromoCode.code == code).first():
        raise HTTPException(status_code=409, detail="Code already exists")
    promo = PromoCode(code=code, token_amount=body.token_amount, created_by_id=admin["user_id"])
    db.add(promo)
    _audit(db, "admin_code_create", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={code} tokens={body.token_amount}")
    db.commit()
    return {"id": promo.id, "code": promo.code, "token_amount": promo.token_amount}


@app.get("/codes")
def list_codes(db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT p.id, p.code, p.token_amount, COUNT(r.id) as redemptions
        FROM promo_codes p
        LEFT JOIN code_redemptions r ON r.code_id = p.id
        GROUP BY p.id, p.code, p.token_amount
        ORDER BY p.id
    """)).fetchall()
    return [{"id": r.id, "code": r.code, "token_amount": r.token_amount,
             "redemptions": r.redemptions} for r in rows]


@app.delete("/codes/{code_id}")
def delete_code(code_id: int, db=Depends(get_db), admin: dict = Depends(require_admin)):
    promo = db.get(PromoCode, code_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Code not found")
    _audit(db, "admin_code_delete", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={promo.code}")
    db.delete(promo)
    db.commit()
    return {"status": "ok"}


@app.post("/redeem")
def redeem_code(body: RedeemCodeBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    code = body.code.strip().upper()
    promo = db.query(PromoCode).filter(PromoCode.code == code).first()
    if not promo:
        raise HTTPException(status_code=404, detail="Invalid code")
    already = db.query(CodeRedemption).filter(
        CodeRedemption.code_id == promo.id,
        CodeRedemption.user_id == user_id,
    ).first()
    if already:
        raise HTTPException(status_code=409, detail="Code already redeemed")
    user.tokens = (user.tokens or 0) + promo.token_amount
    db.add(CodeRedemption(code_id=promo.id, user_id=user_id, redeemed_at=int(time.time())))
    _audit(db, "token_redeem", actor_id=user_id, actor_username=user.username,
           detail=f"code={promo.code} granted={promo.token_amount}")
    db.commit()
    return {"tokens": user.tokens, "granted": promo.token_amount}


@app.get("/audit-logs")
def get_audit_logs(db=Depends(get_db), limit: int = 200, _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT id, timestamp, actor_username, action, detail
        FROM audit_logs
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    return [dict(r._mapping) for r in rows]


@app.get("/config")
def get_config():
    return {"token_name": TOKEN_NAME, "initial_tokens": INITIAL_TOKENS, "app_version": _APP_VERSION, "app_release": _APP_RELEASE}


@app.get("/health")
def health():
    return {"status": "ok"}


_FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if not os.path.isdir(_FRONTEND_DIR):
    _FRONTEND_DIR = "frontend"  # docker image copies to /app/frontend

_TWITCH_EXT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "twitch-extension"))
if not os.path.isdir(_TWITCH_EXT_DIR):
    _TWITCH_EXT_DIR = "twitch-extension"
if os.path.isdir(_TWITCH_EXT_DIR):
    app.mount("/twitch-ext", StaticFiles(directory=_TWITCH_EXT_DIR), name="twitch-extension")

if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
