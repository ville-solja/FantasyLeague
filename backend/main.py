import asyncio
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text
from models import Player, PlayerMatchStats, Card, User, Weight, Team, Week, WeeklyRosterEntry, PromoCode, CodeRedemption
from database import SessionLocal, engine, Base
from ingest import ingest_league
from enrich import run_enrichment
from seed import seed_users, seed_cards, seed_weights
from scoring import fantasy_score
from auth import hash_password, verify_password
from schedule import get_schedule, bust_cache
from weeks import generate_weeks, auto_lock_weeks, get_next_editable_week

ROSTER_LIMIT = 5
TOKEN_NAME     = os.getenv("TOKEN_NAME", "Tokens")
INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))

_ingest_executor = ThreadPoolExecutor(max_workers=1)


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


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    email: str
    password: str


class WeightUpdateBody(BaseModel):
    value: float


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


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        asyncio.get_event_loop().run_in_executor(_ingest_executor, _auto_ingest, _league_ids)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    same_site="lax",
    https_only=False,  # set True behind HTTPS in production
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request) -> dict:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "user_id": user_id,
        "username": request.session.get("username"),
        "is_admin": request.session.get("is_admin", False),
    }


def require_admin(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    user = db.get(User, current_user["user_id"])
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@app.post("/ingest/league/{league_id}")
def ingest_league_endpoint(league_id: int, _: dict = Depends(require_admin)):
    ingest_league(league_id)
    run_enrichment()
    seed_cards(league_id)
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
    data = {"username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0}
    db.close()
    return data


@app.post("/register")
def register(request: Request, body: RegisterBody):
    db = SessionLocal()
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


@app.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    user = db.get(User, current_user["user_id"])
    tokens = user.tokens if user and user.tokens is not None else 0
    db.close()
    return {**current_user, "tokens": tokens}


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
    db = SessionLocal()
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    if (user.tokens or 0) <= 0:
        db.close()
        raise HTTPException(status_code=409, detail="Not enough tokens")

    unclaimed = db.execute(text("""
        SELECT c.id, c.card_type, c.player_id, p.name as player_name, p.avatar_url, t.name as team_name
        FROM cards c
        JOIN players p ON p.id = c.player_id
        LEFT JOIN (
            SELECT player_id, team_id, MAX(match_id) as latest_match
            FROM player_match_stats
            GROUP BY player_id
        ) latest ON latest.player_id = p.id
        LEFT JOIN teams t ON t.id = latest.team_id
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

    db.commit()
    tokens_remaining = user.tokens
    db.close()
    return {
        "id": chosen.id,
        "card_type": chosen.card_type,
        "player_name": chosen.player_name,
        "avatar_url": chosen.avatar_url,
        "team_name": chosen.team_name,
        "is_active": is_active,
        "tokens": tokens_remaining,
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
                   t.name as team_name,
                   COALESCE(SUM(CASE WHEN m.start_time BETWEEN :ws AND :we
                                THEN s.fantasy_points ELSE 0 END), 0) as total_points
            FROM weekly_roster_entries wre
            JOIN cards c ON c.id = wre.card_id
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE wre.week_id = :week_id AND wre.user_id = :user_id
            GROUP BY c.id, c.card_type, p.id, p.name, p.avatar_url, t.name
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
                   t.name as team_name,
                   COALESCE(SUM(CASE WHEN m.start_time BETWEEN :ws AND :we
                                THEN s.fantasy_points ELSE 0 END), 0) as total_points
            FROM cards c
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE c.owner_id = :user_id
            GROUP BY c.id, c.card_type, c.is_active, p.id, p.name, p.avatar_url, t.name
            ORDER BY c.is_active DESC, total_points DESC
        """), {"ws": ws, "we": we, "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active = [c for c in cards if c["is_active"]]
        bench  = [c for c in cards if not c["is_active"]]

    combined = sum(c["total_points"] for c in active)
    user = db.get(User, user_id)
    tokens = user.tokens if user and user.tokens is not None else 0

    # Season points: sum across all locked weekly roster entries
    season_pts_row = db.execute(text("""
        SELECT COALESCE(SUM(s.fantasy_points), 0) as season_points
        FROM weekly_roster_entries wre
        JOIN weeks wk ON wk.id = wre.week_id
        JOIN cards c ON c.id = wre.card_id
        JOIN player_match_stats s ON s.player_id = c.player_id
        JOIN matches m ON m.match_id = s.match_id
        WHERE wre.user_id = :user_id
          AND wk.is_locked = 1
          AND m.start_time BETWEEN wk.start_time AND wk.end_time
    """), {"user_id": user_id}).first()
    season_points = season_pts_row.season_points if season_pts_row else 0

    db.close()
    return {
        "active": active, "bench": bench, "combined_value": combined,
        "tokens": tokens,
        "season_points": season_points,
        "week": {"id": week.id, "label": week.label, "is_locked": week.is_locked,
                 "start_time": week.start_time, "end_time": week.end_time} if week else None,
    }


@app.post("/roster/{card_id}/activate")
def activate_card(card_id: int, current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    user_id = current_user["user_id"]
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

    # Single-player rule: only one card per player may be active
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
    db = SessionLocal()
    user_id = current_user["user_id"]
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


@app.put("/weights/{key}")
def update_weight(key: str, body: WeightUpdateBody, _: dict = Depends(require_admin)):
    db = SessionLocal()
    weight = db.get(Weight, key)
    if not weight:
        db.close()
        raise HTTPException(status_code=404, detail="Weight not found")
    weight.value = body.value
    db.commit()
    db.close()
    return {"key": key, "value": body.value}


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
def grant_tokens(body: GrantTokensBody, _: dict = Depends(require_admin)):
    db = SessionLocal()
    target = db.get(User, body.target_user_id)
    if not target:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount < 1:
        db.close()
        raise HTTPException(status_code=422, detail="Amount must be at least 1")
    target.tokens = (target.tokens or 0) + body.amount
    db.commit()
    new_tokens = target.tokens
    db.close()
    return {"username": target.username, "tokens": new_tokens}


@app.post("/recalculate")
def recalculate(_: dict = Depends(require_admin)):
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
def schedule_refresh(_: dict = Depends(require_admin)):
    db = SessionLocal()
    bust_cache()
    data = get_schedule(db)
    db.close()
    return data


@app.get("/schedule/debug")
def schedule_debug(_: dict = Depends(require_admin)):

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
    db = SessionLocal()
    user_id = current_user["user_id"]
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
    db = SessionLocal()
    user = db.get(User, current_user["user_id"])
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


@app.get("/leaderboard/season")
def season_leaderboard():
    db = SessionLocal()
    results = db.execute(text("""
        SELECT u.id, u.username,
               COALESCE(SUM(s.fantasy_points), 0) as season_points
        FROM users u
        LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id
        LEFT JOIN weeks wk ON wk.id = wre.week_id AND wk.is_locked = 1
        LEFT JOIN cards c ON c.id = wre.card_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        LEFT JOIN matches m ON m.match_id = s.match_id
            AND m.start_time BETWEEN wk.start_time AND wk.end_time
        GROUP BY u.id, u.username
        ORDER BY season_points DESC
    """)).fetchall()
    db.close()
    return [dict(r._mapping) for r in results]


@app.get("/leaderboard/weekly")
def weekly_leaderboard(week_id: int):
    db = SessionLocal()
    week = db.get(Week, week_id)
    if not week:
        db.close()
        raise HTTPException(status_code=404, detail="Week not found")
    results = db.execute(text("""
        SELECT u.id, u.username,
               COALESCE(SUM(s.fantasy_points), 0) as week_points
        FROM users u
        LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id AND wre.week_id = :week_id
        LEFT JOIN cards c ON c.id = wre.card_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        LEFT JOIN matches m ON m.match_id = s.match_id
            AND m.start_time BETWEEN :ws AND :we
        GROUP BY u.id, u.username
        ORDER BY week_points DESC
    """), {"week_id": week_id, "ws": week.start_time, "we": week.end_time}).fetchall()
    db.close()
    return [dict(r._mapping) for r in results]


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
def delete_code(code_id: int, _: dict = Depends(require_admin)):
    db = SessionLocal()
    promo = db.get(PromoCode, code_id)
    if not promo:
        db.close()
        raise HTTPException(status_code=404, detail="Code not found")
    db.delete(promo)
    db.commit()
    db.close()
    return {"status": "ok"}


@app.post("/redeem")
def redeem_code(body: RedeemCodeBody, current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    user_id = current_user["user_id"]
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
    db.commit()
    result = {"tokens": user.tokens, "granted": promo.token_amount}
    db.close()
    return result


@app.get("/config")
def get_config():
    return {"token_name": TOKEN_NAME, "initial_tokens": INITIAL_TOKENS}


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
