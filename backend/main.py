import asyncio
import io
import os
import random
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text
from models import Player, PlayerMatchStats, Match, Card, CardModifier, User, Weight, Team, Week, WeeklyRosterEntry, PromoCode, CodeRedemption, AuditLog, ToornamentSyncLog
from database import SessionLocal, engine, Base, DATABASE_URL
from ingest import ingest_league
from dotabuff_league_logos import resolve_local_team_logo_path
from enrich import run_enrichment
from seed import seed_users, seed_cards, seed_weights
from scoring import fantasy_score, card_fantasy_score, SCORING_STATS
from auth import hash_password, verify_password
from email_utils import send_email
from schedule import get_schedule, bust_cache
from weeks import generate_weeks, auto_lock_weeks, get_next_editable_week
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

ROSTER_LIMIT = 5
TOKEN_NAME     = os.getenv("TOKEN_NAME", "Tokens")
INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))

# ---------------------------------------------------------------------------
# CARD IMAGE GENERATION
# ---------------------------------------------------------------------------

def _resolve_assets_dir() -> str:
    here = os.path.dirname(__file__)
    repo_root = os.path.normpath(os.path.join(here, ".."))

    template_files = [
        "Card_Template_Common.png",
        "Card_Template_Rare.png",
        "Card_Template_Epic.png",
        "Card_Template_Legendary.png",
    ]

    candidates = [
        os.path.join(here, "Assets"),
        os.path.join(here, "assets"),
        os.path.join(repo_root, "Assets"),
        os.path.join(repo_root, "assets"),
        "Assets",
        "assets",
        "/app/Assets",
        "/app/assets",
    ]
    for c in candidates:
        if not os.path.isdir(c):
            continue
        if all(os.path.exists(os.path.join(c, f)) for f in template_files):
            return c
    return "assets"


_ASSETS_DIR = _resolve_assets_dir()

_CARD_TEMPLATES = {
    "common":    "Card_Template_Common.png",
    "rare":      "Card_Template_Rare.png",
    "epic":      "Card_Template_Epic.png",
    "legendary": "Card_Template_Legendary.png",
}

# Layout positions discovered by pixel analysis of the 597×845 templates
_BIG_CIRCLE    = (298, 375, 175)   # (cx, cy, radius) — player avatar
_SMALL_CIRCLE  = (444, 258,  52)   # (cx, cy, radius) — team logo
# Name plates: PNG pixel coords for /cards/{id}/image only (reveal modal no longer duplicates name/team under the art on draw).
_PLAYER_NAME_Y = 90
_TEAM_NAME_Y   = 155
_CARD_SIZE     = (597, 845)
# Stat modifiers — bottom band of the template (below portrait)
_MODIFIERS_START_Y = 620
_MODIFIER_LINE_GAP = 50
_MODIFIER_MAX_WIDTH = 500
# Epic/Legendary templates’ cutouts/plates sit slightly higher than common/rare — nudge content down.
_CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY = 8

# Human-readable stat names (must match frontend roster copy / SCORING_STATS)
_STAT_LABELS_CARD = {
    "kills": "Kills",
    "assists": "Assists",
    "deaths": "Deaths",
    "gold_per_min": "GPM",
    "obs_placed": "Observer wards",
    "sen_placed": "Sentry wards",
    "tower_damage": "Tower damage",
}

_FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _get_font(size: int):
    if not PIL_AVAILABLE:
        return None
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _fetch_team_logo_image(team_logo_url: str | None, diameter: int):
    """Team badge from DB `logo_url` (HTTP)."""
    u = _normalize_image_url(team_logo_url)
    return _fetch_pil_image(u, diameter) if u else None


def _load_team_logo_for_card(team_name: str | None, team_logo_url: str | None, diameter: int):
    """Prefer PNG under {assets}/dotabuff_league_logos/ (ingest), else HTTP logo_url."""
    logo_dir = os.path.join(_ASSETS_DIR, "dotabuff_league_logos")
    path = resolve_local_team_logo_path(logo_dir, team_name)
    if path and PIL_AVAILABLE:
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((diameter, diameter), Image.LANCZOS)
            return img
        except Exception:
            pass
    return _fetch_team_logo_image(team_logo_url, diameter)


def _normalize_image_url(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    u = str(url).strip()
    if u.startswith("//"):
        u = "https:" + u
    return u


def _fetch_pil_image(url: str, diameter: int):
    """Download an image, resize to diameter×diameter, return RGBA PIL Image or None."""
    url = _normalize_image_url(url)
    if not url or not PIL_AVAILABLE:
        return None
    try:
        import requests as _req
        headers = {
            "User-Agent": "FantasyLeagueCardBot/1.0 (+https://github.com/)",
            "Accept": "image/*,*/*;q=0.8",
        }
        r = _req.get(url, timeout=10, headers=headers)
        if r.status_code != 200:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        img = img.resize((diameter, diameter), Image.LANCZOS)
        return img
    except Exception:
        return None


def _circle_crop(img):
    """Apply a circular alpha mask to a square PIL RGBA image."""
    sz = img.size[0]
    mask = Image.new("L", (sz, sz), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, sz, sz), fill=255)
    result = img.copy()
    result.putalpha(mask)
    return result


def _draw_centered_text(draw, text: str, cx: int, cy: int, font, fill,
                        shadow=(0, 0, 0, 160)):
    """Draw text centred at (cx, cy) with a configurable drop shadow."""
    try:
        draw.text((cx + 2, cy + 2), text, font=font, fill=shadow, anchor="mm")
        draw.text((cx, cy), text, font=font, fill=fill, anchor="mm")
        return
    except (TypeError, ValueError):
        pass
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = cx - w // 2, cy - h // 2
    draw.text((x + 2, y + 2), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _truncate_centered_line(draw, text: str, font, max_w: int) -> str:
    t = text
    if hasattr(draw, "textlength"):
        while len(t) > 3 and draw.textlength(t, font=font) > max_w:
            t = t[:-1]
    return t


def _modifier_lines_from_map(mods: dict) -> list[str]:
    if not mods:
        return []
    lines: list[str] = []
    for stat_key, bonus in sorted(mods.items()):
        label = _STAT_LABELS_CARD.get(stat_key, stat_key.replace("_", " ")).upper()
        pct = int(bonus) if float(bonus).is_integer() else bonus
        lines.append(f"{label} +{pct}%")
    return lines


def _draw_card_modifiers(draw, mods: dict, y_offset: int = 0):
    """Stack modifier lines in the empty lower area of the card template."""
    lines = _modifier_lines_from_map(mods)
    if not lines:
        return
    font = _get_font(30)
    fill = (200, 230, 210, 255)
    shadow = (15, 18, 20, 220)
    cy = _MODIFIERS_START_Y + y_offset
    for line in lines:
        t = _truncate_centered_line(draw, line, font, _MODIFIER_MAX_WIDTH)
        _draw_centered_text(draw, t, _CARD_SIZE[0] // 2, cy, font, fill, shadow=shadow)
        cy += _MODIFIER_LINE_GAP


def generate_card_image(
    card_type: str,
    player_name: str | None,
    avatar_url: str | None,
    team_name: str | None,
    team_logo_url: str | None,
    card_modifiers: dict | None = None,
):
    """Composite a player card PNG and return a PIL Image."""
    ct = (card_type or "common").lower()
    template_file = _CARD_TEMPLATES.get(ct, _CARD_TEMPLATES["common"])
    template = Image.open(os.path.join(_ASSETS_DIR, template_file)).convert("RGBA")

    y_off = _CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY if ct in ("epic", "legendary") else 0

    # Dark base matching the card's background colour
    base = Image.new("RGBA", _CARD_SIZE, (35, 37, 40, 255))

    # ── Player avatar (big circle) ──────────────────────────────────────────
    cx, cy, r = _BIG_CIRCLE
    cy += y_off
    avatar = _fetch_pil_image(avatar_url, r * 2)
    if avatar:
        base.paste(_circle_crop(avatar), (cx - r, cy - r), _circle_crop(avatar))

    # ── Team logo (small circle) ────────────────────────────────────────────
    scx, scy, sr = _SMALL_CIRCLE
    scy += y_off
    logo = _load_team_logo_for_card(team_name, team_logo_url, sr * 2)
    if logo:
        base.paste(_circle_crop(logo), (scx - sr, scy - sr), _circle_crop(logo))

    # ── Composite frame on top ──────────────────────────────────────────────
    base.alpha_composite(template)

    # ── Text ────────────────────────────────────────────────────────────────
    draw = ImageDraw.Draw(base)

    # Player name — big plate (bright silver bg → dark text, light shadow)
    name_font = _get_font(32)
    name = (player_name or "Unknown").upper()
    if hasattr(draw, "textlength"):
        while len(name) > 1 and draw.textlength(name, font=name_font) > 480:
            name = name[:-1]
    _draw_centered_text(draw, name, _CARD_SIZE[0] // 2, _PLAYER_NAME_Y + y_off,
                        name_font, (35, 35, 35, 255), shadow=(200, 200, 200, 100))

    # Team name — use same shadow as player; _draw_centered_text default is dark (0,0,0,160).
    team_font = _get_font(22)
    team = (team_name or "").upper()
    if team:
        _draw_centered_text(draw, team, _CARD_SIZE[0] // 2, _TEAM_NAME_Y + y_off,
                            team_font, (35, 35, 35, 255), shadow=(200, 200, 200, 100))

    _draw_card_modifiers(draw, card_modifiers or {}, y_offset=y_off)

    return base



_ingest_executor = ThreadPoolExecutor(max_workers=1)
_WEEK_CHECK_INTERVAL  = int(os.getenv("WEEK_CHECK_INTERVAL",  "300"))   # seconds, default 5 min
_INGEST_POLL_INTERVAL = int(os.getenv("INGEST_POLL_INTERVAL", "900"))   # seconds, default 15 min


def _week_maintenance_loop():
    """Background thread: periodically generate new weeks and lock past ones."""
    while True:
        time.sleep(_WEEK_CHECK_INTERVAL)
        try:
            db = SessionLocal()
            generate_weeks(db)
            auto_lock_weeks(db)
            db.close()
        except Exception as e:
            print(f"[WEEKS] Maintenance error: {e}")


def _auto_ingest(league_ids: list[int]):
    for league_id in league_ids:
        try:
            print(f"[AUTO-INGEST] League {league_id} starting")
            ingest_league(league_id)
            run_enrichment()
            seed_cards(league_id)
            print(f"[AUTO-INGEST] League {league_id} done")
        except Exception as e:
            print(f"[AUTO-INGEST] League {league_id} failed: {e}")


def _run_toornament_sync():
    try:
        from toornament import sync_toornament_results
        db = SessionLocal()
        result = sync_toornament_results(db)
        db.close()
        print(f"[TOORNAMENT] Sync: {result}")
    except Exception as e:
        print(f"[TOORNAMENT] Sync error: {e}")


def _ingest_poll_loop(league_ids: list[int]):
    """Background thread: periodically ingest new matches then sync to toornament."""
    while True:
        _auto_ingest(league_ids)
        _run_toornament_sync()
        time.sleep(_INGEST_POLL_INTERVAL)


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    email: str
    password: str



class GrantTokensBody(BaseModel):
    target_user_id: int
    amount: int


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


class CreateCodeBody(BaseModel):
    code: str
    token_amount: int


class RedeemCodeBody(BaseModel):
    code: str


class UpdateUsernameBody(BaseModel):
    username: str


class UpdatePlayerIdBody(BaseModel):
    player_id: int | None = None


class ForgotPasswordBody(BaseModel):
    username: str


class MatchWeekBody(BaseModel):
    week_id: int | None = None


class SimulateBody(BaseModel):
    kills: float | None = None
    assists: float | None = None
    deaths: float | None = None
    gold_per_min: float | None = None
    obs_placed: float | None = None
    sen_placed: float | None = None
    tower_damage: float | None = None


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


def _rarity_params(db) -> dict:
    """Return rarity modifier params for SQL CASE expressions.

    Values are stored as percentages (e.g. 3.0 = 3%).
    Returns them divided by 100 so they can be used as: fantasy_points * (1 + param).
    """
    weights = {w.key: w.value for w in db.query(Weight).all()}
    return {
        "mod_common":    weights.get("rarity_common",    0.0) / 100,
        "mod_rare":      weights.get("rarity_rare",      1.0) / 100,
        "mod_epic":      weights.get("rarity_epic",      2.0) / 100,
        "mod_legendary": weights.get("rarity_legendary", 3.0) / 100,
    }


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
    chosen = random.sample(SCORING_STATS, min(count, len(SCORING_STATS)))
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
    print(f"[DB] {DATABASE_URL}")
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(players)")).fetchall()]
        if "avatar_url" not in cols:
            conn.execute(text("ALTER TABLE players ADD COLUMN avatar_url TEXT"))
            conn.commit()
        match_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(matches)")).fetchall()]
        if "start_time" not in match_cols:
            conn.execute(text("ALTER TABLE matches ADD COLUMN start_time INTEGER"))
            conn.commit()
        if "radiant_win" not in match_cols:
            conn.execute(text("ALTER TABLE matches ADD COLUMN radiant_win BOOLEAN"))
            conn.commit()
        if "week_override_id" not in match_cols:
            conn.execute(text("ALTER TABLE matches ADD COLUMN week_override_id INTEGER REFERENCES weeks(id)"))
            conn.commit()
        user_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
        if "tokens" not in user_cols:
            # Seed from draw_limit if it exists, otherwise default to INITIAL_TOKENS
            if "draw_limit" in user_cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN tokens INTEGER DEFAULT {INITIAL_TOKENS}"))
                conn.execute(text("UPDATE users SET tokens = COALESCE(draw_limit, 7)"))
            else:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN tokens INTEGER DEFAULT {INITIAL_TOKENS}"))
            conn.commit()
        if "created_at" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN created_at INTEGER"))
            conn.commit()
        if "player_id" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN player_id INTEGER"))
            conn.commit()
        if "must_change_password" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0"))
            conn.commit()
        team_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(teams)")).fetchall()]
        if "logo_url" not in team_cols:
            conn.execute(text("ALTER TABLE teams ADD COLUMN logo_url TEXT"))
            conn.commit()
    seed_users()
    seed_weights()
    # Migrate: if the old epoch-0 Week 1 exists, the week structure is wrong.
    # Wipe weeks + snapshots and regenerate with the corrected boundaries.
    with engine.connect() as _mc:
        _old = _mc.execute(text("SELECT id FROM weeks WHERE start_time = 0 LIMIT 1")).first()
        if _old:
            _mc.execute(text("DELETE FROM weekly_roster_entries"))
            _mc.execute(text("DELETE FROM weeks"))
            _mc.commit()
            print("[MIGRATION] Reset weeks to corrected structure (lock-before-matches)")
    _db = SessionLocal()
    generate_weeks(_db)
    auto_lock_weeks(_db)
    _db.close()
    _leagues_env = os.getenv("AUTO_INGEST_LEAGUES", "19368,19369")
    _league_ids = [int(x.strip()) for x in _leagues_env.split(",") if x.strip().isdigit()]
    if _league_ids:
        threading.Thread(target=_ingest_poll_loop, args=(_league_ids,), daemon=True).start()
        print(f"[INGEST] Poll thread started (interval={_INGEST_POLL_INTERVAL}s)")
    t = threading.Thread(target=_week_maintenance_loop, daemon=True)
    t.start()
    print(f"[WEEKS] Maintenance thread started (interval={_WEEK_CHECK_INTERVAL}s)")
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    same_site="lax",
    https_only=False,
)


@app.post("/ingest/league/{league_id}")
def ingest_league_endpoint(league_id: int, admin: dict = Depends(require_admin)):
    ingest_league(league_id)
    run_enrichment()
    seed_cards(league_id)
    db = SessionLocal()
    _audit(db, "admin_ingest", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"league_id={league_id}")
    db.commit()
    db.close()
    return {"status": "ok", "league_id": league_id}


@app.post("/login")
def login(request: Request, body: LoginBody):
    db = SessionLocal()
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        db.close()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session["user_id"]  = user.id
    request.session["username"] = user.username
    request.session["is_admin"] = user.is_admin
    _audit(db, "user_login", actor_id=user.id, actor_username=user.username)
    db.commit()
    data = {"username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0}
    db.close()
    return data


@app.post("/register")
def register(request: Request, body: RegisterBody):
    import re as _re
    db = SessionLocal()
    if not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', body.email.strip()):
        db.close()
        raise HTTPException(status_code=422, detail="Invalid email address")
    if db.query(User).filter(User.username == body.username).first():
        db.close()
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == body.email).first():
        db.close()
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
    data = {"username": user.username, "is_admin": user.is_admin, "tokens": user.tokens}
    db.close()
    return data


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@app.post("/forgot-password")
def forgot_password(body: ForgotPasswordBody):
    db = SessionLocal()
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not user.email:
        db.close()
        # Return 200 regardless to avoid username enumeration
        return {"status": "ok"}

    # Capture values before closing the session to avoid DetachedInstanceError
    user_email    = user.email
    user_username = user.username
    user_id       = user.id

    temp_password = secrets.token_urlsafe(9)  # ~12 printable chars
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    _audit(db, "password_reset_requested", actor_id=user_id, actor_username=user_username)
    db.commit()
    db.close()

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
def me(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    user = db.get(User, user_id)
    db.close()
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0,
            "must_change_password": bool(user.must_change_password)}


@app.get("/deck")
def get_deck():
    db = SessionLocal()
    results = db.execute(text("""
        SELECT c.card_type, COUNT(*) as count
        FROM cards c
        WHERE c.owner_id IS NULL
        GROUP BY c.card_type
    """)).fetchall()
    db.close()
    return {r.card_type: r.count for r in results}


@app.post("/draw")
def draw_card(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    db = SessionLocal()
    user = db.get(User, user_id)
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    if (user.tokens or 0) <= 0:
        db.close()
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
        db.close()
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
    db.close()
    return {
        "id": chosen.id,
        "card_type": chosen.card_type,
        "player_name": chosen.player_name,
        "avatar_url": chosen.avatar_url,
        "team_name": chosen.team_name,
        "team_logo_url": chosen.team_logo_url,
        "is_active": is_active,
        "tokens": tokens_remaining,
        "modifiers": _format_modifiers(mods),
    }


@app.get("/weeks")
def get_weeks():
    db = SessionLocal()
    weeks = db.query(Week).order_by(Week.start_time).all()
    data = [{"id": w.id, "label": w.label, "start_time": w.start_time,
             "end_time": w.end_time, "is_locked": w.is_locked} for w in weeks]
    db.close()
    return data


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


@app.get("/roster/{user_id}")
def get_roster(user_id: int, week_id: int = None):
    db = SessionLocal()

    # Determine which week to scope points to
    if week_id is not None:
        week = db.get(Week, week_id)
    else:
        # Default: the next upcoming (editable) week — roster being prepared,
        # no matches yet so points = 0 until the week starts.
        week = get_next_editable_week(db)

    now = int(time.time())

    if week and week.is_locked:
        # Locked week: return the immutable snapshot with week-scoped points
        results = db.execute(text(f"""
            SELECT c.id, c.card_type, 1 as is_active,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.name as team_name, t.logo_url as team_logo_url,
                   COALESCE(SUM(CASE WHEN (m.week_override_id = :week_id OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
                                THEN s.fantasy_points ELSE 0 END), 0) as total_points
            FROM weekly_roster_entries wre
            JOIN cards c ON c.id = wre.card_id
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE wre.week_id = :week_id AND wre.user_id = :user_id
            GROUP BY c.id, c.card_type, p.id, p.name, p.avatar_url, t.name, t.logo_url
            ORDER BY total_points DESC
        """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time,
               "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active = cards
        bench = []
    else:
        # Current/active week: editable roster, points scoped to this week only
        ws = week.start_time if week else 0
        we = week.end_time if week else now
        results = db.execute(text(f"""
            SELECT c.id, c.card_type, c.is_active,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.name as team_name, t.logo_url as team_logo_url,
                   COALESCE(SUM(CASE WHEN (m.week_override_id = :week_id OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
                                THEN s.fantasy_points ELSE 0 END), 0) as total_points
            FROM cards c
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE c.owner_id = :user_id
            GROUP BY c.id, c.card_type, c.is_active, p.id, p.name, p.avatar_url, t.name, t.logo_url
            ORDER BY c.is_active DESC, total_points DESC
        """), {"ws": ws, "we": we, "week_id": week.id if week else -1, "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active = [c for c in cards if c["is_active"]]
        bench  = [c for c in cards if not c["is_active"]]

    # Load modifiers for all cards in this roster
    card_ids = [c["id"] for c in cards]
    modifiers_map = _card_modifiers_map(db, card_ids)

    rarity = _rarity_params(db)
    for c in cards:
        mods = modifiers_map.get(c["id"], {})
        c["modifiers"] = _format_modifiers(mods)
        # Card modifier bonus: average % across all modifiers on this card
        # applied on top of the base score (which uses raw fantasy_points from DB)
        avg_mod_bonus = sum(mods.values()) / len(mods) if mods else 0.0
        rarity_mod = 1 + rarity.get(f"mod_{c['card_type']}", 0)
        card_mod = 1 + avg_mod_bonus / 100
        c["total_points"] = c["total_points"] * rarity_mod * card_mod

    combined = sum(c["total_points"] for c in active)
    user = db.get(User, user_id)
    tokens = user.tokens if user and user.tokens is not None else 0

    # Season points: per card so both rarity and card modifiers can be applied
    season_pts_rows = db.execute(text("""
        SELECT c.id as card_id, c.card_type,
               COALESCE(SUM(s.fantasy_points), 0) as raw_points
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
    season_points = 0.0
    for row in season_pts_rows:
        mods = season_mods.get(row.card_id, {})
        avg_mod_bonus = sum(mods.values()) / len(mods) if mods else 0.0
        rarity_mod = 1 + rarity.get(f"mod_{row.card_type}", 0)
        card_mod = 1 + avg_mod_bonus / 100
        season_points += row.raw_points * rarity_mod * card_mod

    db.close()
    return {
        "active": active, "bench": bench, "combined_value": combined,
        "tokens": tokens,
        "season_points": season_points,
        "week": {"id": week.id, "label": week.label, "is_locked": week.is_locked,
                 "start_time": week.start_time, "end_time": week.end_time} if week else None,
    }


@app.get("/cards/{card_id}")
def get_card(card_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    db = SessionLocal()
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        db.close()
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
    db.close()
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
def get_card_image(card_id: int):
    """Generate and return a PNG image for this card."""
    if not PIL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Image generation unavailable (Pillow not installed)")
    db = SessionLocal()
    result = db.execute(text("""
        SELECT c.card_type, p.name as player_name, p.avatar_url,
               t.name as team_name, t.logo_url as team_logo_url
        FROM cards c
        JOIN players p ON p.id = c.player_id
""" + _LATEST_TEAM_SUBQUERY + """
        WHERE c.id = :card_id
    """), {"card_id": card_id}).first()
    mods: dict = _card_modifiers_dict_for_image(db, card_id) if result else {}
    db.close()
    if not result:
        raise HTTPException(status_code=404, detail="Card not found")
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
def reroll_modifiers(card_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    db = SessionLocal()
    user = db.get(User, user_id)
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    if (user.tokens or 0) <= 0:
        db.close()
        raise HTTPException(status_code=409, detail="Not enough tokens")
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        db.close()
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
    db.close()
    return {
        "modifiers": _format_modifiers(mods),
        "tokens": tokens_remaining,
    }


@app.post("/roster/{card_id}/activate")
def activate_card(card_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    db = SessionLocal()
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        db.close()
        raise HTTPException(status_code=404, detail="Card not found")
    if card.is_active:
        db.close()
        raise HTTPException(status_code=409, detail="Card already active")

    active_count = db.query(Card).filter(
        Card.owner_id == user_id, Card.is_active == True
    ).count()
    if active_count >= ROSTER_LIMIT:
        db.close()
        raise HTTPException(status_code=409, detail=f"Roster full ({ROSTER_LIMIT} cards max)")

    duplicate = db.query(Card).filter(
        Card.owner_id == user_id,
        Card.player_id == card.player_id,
        Card.is_active == True,
        Card.id != card_id,
    ).first()
    if duplicate:
        db.close()
        raise HTTPException(status_code=409, detail="A card for this player is already active")

    card.is_active = True
    db.commit()
    db.close()
    return {"status": "ok", "card_id": card_id}


@app.post("/roster/{card_id}/deactivate")
def deactivate_card(card_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    db = SessionLocal()
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        db.close()
        raise HTTPException(status_code=404, detail="Card not found")
    card.is_active = False
    db.commit()
    db.close()
    return {"status": "ok", "card_id": card_id}


@app.get("/players")
def list_players():
    db = SessionLocal()
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
    db.close()
    return [dict(r._mapping) for r in results]


@app.get("/players/{player_id}")
def get_player(player_id: int):
    db = SessionLocal()
    player = db.get(Player, player_id)
    if not player:
        db.close()
        raise HTTPException(status_code=404, detail="Player not found")

    stats = db.execute(text("""
        SELECT s.match_id, m.start_time, s.fantasy_points,
               s.kills, s.assists, s.deaths, s.gold_per_min,
               s.obs_placed, s.sen_placed, s.tower_damage,
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

    db.close()
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


@app.get("/teams")
def list_teams():
    db = SessionLocal()
    results = db.execute(text("""
        SELECT t.id, t.name,
               COUNT(DISTINCT s.match_id) as matches,
               COUNT(DISTINCT s.player_id) as player_count
        FROM teams t
        LEFT JOIN player_match_stats s ON s.team_id = t.id
        GROUP BY t.id, t.name
        ORDER BY matches DESC, t.name
    """)).fetchall()
    db.close()
    return [dict(r._mapping) for r in results]


@app.get("/teams/{team_id}")
def get_team(team_id: int):
    db = SessionLocal()
    team = db.get(Team, team_id)
    if not team:
        db.close()
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

    db.close()
    return {
        "id": team.id,
        "name": team.name,
        "matches": match_count or 0,
        "players": [dict(r._mapping) for r in players],
    }


@app.get("/top")
def top_performances():
    db = SessionLocal()
    results = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url, s.fantasy_points
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        ORDER BY s.fantasy_points DESC
        LIMIT 10
    """)).fetchall()
    db.close()
    return [dict(r._mapping) for r in results]


@app.get("/leaderboard")
def leaderboard():
    db = SessionLocal()
    results = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url, COUNT(s.id) as matches, AVG(s.fantasy_points) as avg_points
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        GROUP BY p.id, p.name, p.avatar_url
        ORDER BY avg_points DESC
    """)).fetchall()
    db.close()
    return [dict(r._mapping) for r in results]


@app.get("/leaderboard/roster")
def roster_leaderboard():
    db = SessionLocal()
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
        GROUP BY u.id, u.username, owned.total
        ORDER BY roster_value DESC
    """)).fetchall()
    db.close()
    return [dict(r._mapping) for r in results]


@app.get("/weights")
def get_weights():
    db = SessionLocal()
    weights = db.query(Weight).order_by(Weight.key).all()
    data = [{"key": w.key, "label": w.label, "value": w.value} for w in weights]
    db.close()
    return data



_SIMULATE_DOCS = {
    "endpoint": "POST /simulate/{match_id}",
    "description": (
        "Simulate fantasy point scores for all players in a given match using custom "
        "per-stat weights. Any stat weight not provided falls back to the current "
        "season default stored in the database. No authentication required."
    ),
    "path_parameters": {
        "match_id": "integer — OpenDota match ID that has been ingested into the system",
    },
    "request_body": {
        "content_type": "application/json",
        "fields": {
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
                    "assists": "integer",
                    "deaths": "integer",
                    "gold_per_min": "float",
                    "obs_placed": "integer",
                    "sen_placed": "integer",
                    "tower_damage": "integer",
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
    """12.2 — Human- and machine-readable documentation for the weight simulation endpoint."""
    return _SIMULATE_DOCS


@app.post("/simulate/{match_id}")
def simulate_match(match_id: int, body: SimulateBody = None):
    """12.1 — Return fantasy scores for every player in a match under custom weights.

    Any weight not supplied in the request body falls back to the current DB default.
    No authentication required so statisticians can call this without an account.
    """
    if body is None:
        body = SimulateBody()

    db = SessionLocal()

    # Verify match exists
    match = db.get(Match, match_id)
    if not match:
        db.close()
        raise HTTPException(status_code=404, detail="Match not found")

    # Load DB weights and apply overrides for scoring stats only
    db_weights = {w.key: w.value for w in db.query(Weight).all()}
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    weights_used = {stat: overrides.get(stat, db_weights.get(stat, 0.0)) for stat in SCORING_STATS}

    # Fetch all player stats for this match with player and team names
    rows = db.execute(text("""
        SELECT s.player_id, p.name as player_name,
               t.name as team_name,
               s.kills, s.assists, s.deaths,
               s.gold_per_min, s.obs_placed, s.sen_placed, s.tower_damage
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        LEFT JOIN teams t ON t.id = s.team_id
        WHERE s.match_id = :match_id
    """), {"match_id": match_id}).fetchall()
    db.close()

    players = []
    for r in rows:
        stats = {
            "kills": r.kills or 0,
            "assists": r.assists or 0,
            "deaths": r.deaths or 0,
            "gold_per_min": r.gold_per_min or 0,
            "obs_placed": r.obs_placed or 0,
            "sen_placed": r.sen_placed or 0,
            "tower_damage": r.tower_damage or 0,
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
def list_users(_: dict = Depends(require_admin)):
    db = SessionLocal()
    users = db.query(User).order_by(User.username).all()
    result = []
    for u in users:
        result.append({
            "id": u.id,
            "username": u.username,
            "tokens": u.tokens if u.tokens is not None else 0,
        })
    db.close()
    return result


@app.post("/grant-tokens")
def grant_tokens(body: GrantTokensBody, admin: dict = Depends(require_admin)):
    db = SessionLocal()
    target = db.get(User, body.target_user_id)
    if not target:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount < 1:
        db.close()
        raise HTTPException(status_code=422, detail="Amount must be at least 1")
    target.tokens = (target.tokens or 0) + body.amount
    _audit(db, "admin_grant_tokens", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"target={target.username} amount={body.amount}")
    db.commit()
    new_tokens = target.tokens
    db.close()
    return {"username": target.username, "tokens": new_tokens}


@app.post("/recalculate")
def recalculate(admin: dict = Depends(require_admin)):
    db = SessionLocal()
    weights = {w.key: w.value for w in db.query(Weight).all()}
    stats = db.query(PlayerMatchStats).all()
    for stat in stats:
        p = {
            "kills": stat.kills,
            "assists": stat.assists,
            "deaths": stat.deaths,
            "gold_per_min": stat.gold_per_min,
            "obs_placed": stat.obs_placed,
            "sen_placed": stat.sen_placed,
            "tower_damage": stat.tower_damage,
        }
        stat.fantasy_points = fantasy_score(p, weights)
    _audit(db, "admin_recalculate", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"records={len(stats)}")
    db.commit()
    count = len(stats)
    db.close()
    return {"status": "ok", "recalculated": count}


@app.get("/schedule")
def schedule_endpoint():
    db = SessionLocal()
    data = get_schedule(db)
    db.close()
    return data


@app.post("/schedule/refresh")
def schedule_refresh(admin: dict = Depends(require_admin)):
    db = SessionLocal()
    bust_cache()
    _audit(db, "admin_schedule_refresh", actor_id=admin["user_id"], actor_username=admin["username"])
    db.commit()
    data = get_schedule(db)
    db.close()
    return data


@app.get("/schedule/debug")
def schedule_debug(_: dict = Depends(require_admin)):
    db = SessionLocal()
    db.close()
    db.close()

    from schedule import SCHEDULE_SHEET_URL as _DEFAULT_SCHEDULE_URL
    url = os.getenv("SCHEDULE_SHEET_URL", _DEFAULT_SCHEDULE_URL)
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
def set_match_week(match_id: int, body: MatchWeekBody, admin: dict = Depends(require_admin)):
    """Manually override which fantasy week a match counts for.
    Set week_id to null to clear the override and revert to time-based assignment."""
    db = SessionLocal()
    match = db.get(Match, match_id)
    if not match:
        db.close()
        raise HTTPException(status_code=404, detail="Match not found")
    if body.week_id is not None:
        week = db.get(Week, body.week_id)
        if not week:
            db.close()
            raise HTTPException(status_code=404, detail="Week not found")
    old_override = match.week_override_id
    match.week_override_id = body.week_id
    _audit(db, "admin_set_match_week", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match_id={match_id} old_override={old_override} new_override={body.week_id}")
    db.commit()
    db.close()
    return {"match_id": match_id, "week_override_id": body.week_id}


@app.post("/admin/sync-match-weeks")
def sync_match_weeks(admin: dict = Depends(require_admin)):
    """Auto-assign week_override_id on matches whose actual play date differs from their
    scheduled week in the Google Sheet. Matches already in the correct week get their
    override cleared (set to NULL). Uses ±3-day proximity to the series scheduled date
    to disambiguate when two teams play each other more than once in a season."""
    from schedule import get_schedule

    db = SessionLocal()

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

    db.close()
    return {"changes": changes, "errors": errors}


@app.post("/admin/sync-toornament")
def admin_sync_toornament(admin: dict = Depends(require_admin)):
    """Push current series results to toornament.com. Idempotent — safe to call repeatedly."""
    from toornament import sync_toornament_results
    db = SessionLocal()
    result = sync_toornament_results(db)
    _audit(db, "admin_sync_toornament", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"pushed={result['pushed']} skipped={result['skipped']} errors={len(result['errors'])}")
    db.commit()
    db.close()
    return result


@app.get("/profile/{user_id}")
def get_profile(user_id: int):
    db = SessionLocal()
    user = db.get(User, user_id)
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    result = {"id": user.id, "username": user.username, "player_id": user.player_id,
              "player_name": None, "player_avatar_url": None}
    if user.player_id:
        player = db.get(Player, user.player_id)
        if player:
            result["player_name"] = player.name
            result["player_avatar_url"] = player.avatar_url
    db.close()
    return result


@app.put("/profile/username")
def update_username(body: UpdateUsernameBody, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    db = SessionLocal()
    user = db.get(User, user_id)
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    username = body.username.strip()
    if not username:
        db.close()
        raise HTTPException(status_code=422, detail="Username cannot be empty")
    existing = db.query(User).filter(User.username == username, User.id != user_id).first()
    if existing:
        db.close()
        raise HTTPException(status_code=409, detail="Username already taken")
    user.username = username
    db.commit()
    db.close()
    return {"username": username}


@app.put("/profile/player-id")
def update_player_id(body: UpdatePlayerIdBody, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    db = SessionLocal()
    user = db.get(User, user_id)
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    user.player_id = body.player_id
    db.commit()
    result = {"player_id": body.player_id, "player_name": None, "player_avatar_url": None}
    if body.player_id:
        player = db.get(Player, body.player_id)
        if player:
            result["player_name"] = player.name
            result["player_avatar_url"] = player.avatar_url
    db.close()
    return result


def _leaderboard_rows(db, rows) -> list[dict]:
    """Apply rarity + card modifier multipliers to raw leaderboard rows.

    rows must have: user_id, username, card_id, card_type, raw_points
    """
    rarity = _rarity_params(db)
    card_ids = list({r.card_id for r in rows if r.card_id})
    mods_map = _card_modifiers_map(db, card_ids)

    totals: dict[int, float] = {}
    usernames: dict[int, str] = {}
    for r in rows:
        uid = r.user_id
        usernames[uid] = r.username
        if not r.card_id or not r.raw_points:
            totals.setdefault(uid, 0.0)
            continue
        mods = mods_map.get(r.card_id, {})
        avg_mod_bonus = sum(mods.values()) / len(mods) if mods else 0.0
        rarity_mod = 1 + rarity.get(f"mod_{r.card_type}", 0)
        card_mod = 1 + avg_mod_bonus / 100
        totals[uid] = totals.get(uid, 0.0) + r.raw_points * rarity_mod * card_mod

    return sorted(
        [{"id": uid, "username": usernames[uid], "points": round(totals[uid], 2)}
         for uid in totals],
        key=lambda x: x["points"], reverse=True,
    )


@app.get("/leaderboard/season")
def season_leaderboard():
    db = SessionLocal()
    rows = db.execute(text("""
        SELECT u.id as user_id, u.username,
               c.id as card_id, c.card_type,
               COALESCE(SUM(s.fantasy_points), 0) as raw_points
        FROM users u
        LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id
        LEFT JOIN weeks wk ON wk.id = wre.week_id AND wk.is_locked = 1
        LEFT JOIN cards c ON c.id = wre.card_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        LEFT JOIN matches m ON m.match_id = s.match_id
            AND m.start_time BETWEEN wk.start_time AND wk.end_time
        GROUP BY u.id, u.username, c.id, c.card_type
    """)).fetchall()
    result = _leaderboard_rows(db, rows)
    db.close()
    return [{"id": r["id"], "username": r["username"], "season_points": r["points"]} for r in result]


@app.get("/leaderboard/weekly")
def weekly_leaderboard(week_id: int):
    db = SessionLocal()
    week = db.get(Week, week_id)
    if not week:
        db.close()
        raise HTTPException(status_code=404, detail="Week not found")
    rows = db.execute(text("""
        SELECT u.id as user_id, u.username,
               c.id as card_id, c.card_type,
               COALESCE(SUM(s.fantasy_points), 0) as raw_points
        FROM users u
        LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id AND wre.week_id = :week_id
        LEFT JOIN cards c ON c.id = wre.card_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        LEFT JOIN matches m ON m.match_id = s.match_id
            AND m.start_time BETWEEN :ws AND :we
        GROUP BY u.id, u.username, c.id, c.card_type
    """), {"week_id": week_id, "ws": week.start_time, "we": week.end_time}).fetchall()
    result = _leaderboard_rows(db, rows)
    db.close()
    return [{"id": r["id"], "username": r["username"], "week_points": r["points"]} for r in result]


@app.put("/profile/password")
def change_password(body: ChangePasswordBody, current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    user = db.get(User, current_user["user_id"])
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, user.password_hash):
        db.close()
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < 6:
        db.close()
        raise HTTPException(status_code=422, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    db.close()
    return {"status": "ok"}


@app.post("/codes")
def create_code(body: CreateCodeBody, admin: dict = Depends(require_admin)):
    db = SessionLocal()
    code = body.code.strip().upper()
    if not code:
        db.close()
        raise HTTPException(status_code=422, detail="Code cannot be empty")
    if body.token_amount < 1:
        db.close()
        raise HTTPException(status_code=422, detail="Token amount must be at least 1")
    if db.query(PromoCode).filter(PromoCode.code == code).first():
        db.close()
        raise HTTPException(status_code=409, detail="Code already exists")
    promo = PromoCode(code=code, token_amount=body.token_amount, created_by_id=admin["user_id"])
    db.add(promo)
    _audit(db, "admin_code_create", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={code} tokens={body.token_amount}")
    db.commit()
    result = {"id": promo.id, "code": promo.code, "token_amount": promo.token_amount}
    db.close()
    return result


@app.get("/codes")
def list_codes(_: dict = Depends(require_admin)):
    db = SessionLocal()
    codes = db.query(PromoCode).all()
    result = []
    for c in codes:
        redemptions = db.query(CodeRedemption).filter(CodeRedemption.code_id == c.id).count()
        result.append({"id": c.id, "code": c.code, "token_amount": c.token_amount,
                       "redemptions": redemptions})
    db.close()
    return result


@app.delete("/codes/{code_id}")
def delete_code(code_id: int, admin: dict = Depends(require_admin)):
    db = SessionLocal()
    promo = db.get(PromoCode, code_id)
    if not promo:
        db.close()
        raise HTTPException(status_code=404, detail="Code not found")
    _audit(db, "admin_code_delete", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={promo.code}")
    db.delete(promo)
    db.commit()
    db.close()
    return {"status": "ok"}


@app.post("/redeem")
def redeem_code(body: RedeemCodeBody, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    db = SessionLocal()
    user = db.get(User, user_id)
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    code = body.code.strip().upper()
    promo = db.query(PromoCode).filter(PromoCode.code == code).first()
    if not promo:
        db.close()
        raise HTTPException(status_code=404, detail="Invalid code")
    already = db.query(CodeRedemption).filter(
        CodeRedemption.code_id == promo.id,
        CodeRedemption.user_id == user_id,
    ).first()
    if already:
        db.close()
        raise HTTPException(status_code=409, detail="Code already redeemed")
    user.tokens = (user.tokens or 0) + promo.token_amount
    db.add(CodeRedemption(code_id=promo.id, user_id=user_id, redeemed_at=int(time.time())))
    _audit(db, "token_redeem", actor_id=user_id, actor_username=user.username,
           detail=f"code={promo.code} granted={promo.token_amount}")
    db.commit()
    result = {"tokens": user.tokens, "granted": promo.token_amount}
    db.close()
    return result


@app.get("/audit-logs")
def get_audit_logs(limit: int = 200, _: dict = Depends(require_admin)):
    db = SessionLocal()
    rows = db.execute(text("""
        SELECT id, timestamp, actor_username, action, detail
        FROM audit_logs
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    db.close()
    return [dict(r._mapping) for r in rows]


@app.get("/config")
def get_config():
    return {"token_name": TOKEN_NAME, "initial_tokens": INITIAL_TOKENS}


_FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if not os.path.isdir(_FRONTEND_DIR):
    _FRONTEND_DIR = "frontend"  # docker image copies to /app/frontend

app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
