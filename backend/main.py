import os
import random
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from models import Player, PlayerMatchStats, Card, User, Weight
from database import SessionLocal, engine, Base
from ingest import ingest_league
from enrich import run_enrichment
from seed import seed_users, seed_cards, seed_weights
from scoring import fantasy_score
from auth import hash_password, verify_password
from schedule import get_schedule, bust_cache

ROSTER_LIMIT = 5


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    email: str
    password: str


class DrawBody(BaseModel):
    user_id: int


class RosterActionBody(BaseModel):
    user_id: int


class WeightUpdateBody(BaseModel):
    value: float


class AdminBody(BaseModel):
    user_id: int


class GrantDrawsBody(BaseModel):
    user_id: int        # admin
    target_user_id: int
    amount: int


def require_admin(user_id: int, db):
    user = db.get(User, user_id)
    if not user or not user.is_admin:
        db.close()
        raise HTTPException(status_code=403, detail="Admin access required")


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
        if "draw_limit" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN draw_limit INTEGER DEFAULT 7"))
            conn.commit()
    seed_users()
    seed_weights()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.post("/ingest/league/{league_id}")
def ingest_league_endpoint(league_id: int, body: AdminBody):
    db = SessionLocal()
    require_admin(body.user_id, db)
    db.close()
    ingest_league(league_id)
    run_enrichment()
    seed_cards(league_id)
    return {"status": "ok", "league_id": league_id}


@app.post("/login")
def login(body: LoginBody):
    db = SessionLocal()
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        db.close()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    data = {"id": user.id, "username": user.username, "is_admin": user.is_admin}
    db.close()
    return data


@app.post("/register")
def register(body: RegisterBody):
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
    )
    db.add(user)
    db.commit()
    data = {"id": user.id, "username": user.username, "is_admin": user.is_admin}
    db.close()
    return data


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
def draw_card(body: DrawBody):
    db = SessionLocal()
    user = db.get(User, body.user_id)
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    draws_used = db.query(Card).filter(Card.owner_id == body.user_id).count()
    draw_limit = user.draw_limit if user.draw_limit is not None else 7
    if draws_used >= draw_limit:
        db.close()
        raise HTTPException(status_code=409, detail=f"Draw limit reached ({draws_used}/{draw_limit})")

    unclaimed = db.execute(text("""
        SELECT c.id, c.card_type, p.name as player_name, p.avatar_url, t.name as team_name
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

    chosen = random.choice(unclaimed)
    card = db.get(Card, chosen.id)
    card.owner_id = body.user_id

    active_count = db.query(Card).filter(
        Card.owner_id == body.user_id, Card.is_active == True
    ).count()
    is_active = active_count < ROSTER_LIMIT
    card.is_active = is_active

    db.commit()
    db.close()
    return {
        "id": chosen.id,
        "card_type": chosen.card_type,
        "player_name": chosen.player_name,
        "avatar_url": chosen.avatar_url,
        "team_name": chosen.team_name,
        "is_active": is_active,
    }


@app.get("/roster/{user_id}")
def get_roster(user_id: int):
    db = SessionLocal()
    results = db.execute(text("""
        SELECT c.id, c.card_type, c.is_active, p.name as player_name, p.avatar_url,
               COALESCE(SUM(s.fantasy_points), 0) as total_points
        FROM cards c
        JOIN players p ON p.id = c.player_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        WHERE c.owner_id = :user_id
        GROUP BY c.id, c.card_type, c.is_active, p.name, p.avatar_url
        ORDER BY c.is_active DESC, total_points DESC
    """), {"user_id": user_id}).fetchall()

    cards = [dict(r._mapping) for r in results]
    active = [c for c in cards if c["is_active"]]
    bench  = [c for c in cards if not c["is_active"]]
    combined = sum(c["total_points"] for c in active)

    user = db.get(User, user_id)
    draws_used  = len(cards)
    draw_limit  = user.draw_limit if user and user.draw_limit is not None else 7

    db.close()
    return {"active": active, "bench": bench, "combined_value": combined,
            "draws_used": draws_used, "draw_limit": draw_limit}


@app.post("/roster/{card_id}/activate")
def activate_card(card_id: int, body: RosterActionBody):
    db = SessionLocal()
    card = db.get(Card, card_id)
    if not card or card.owner_id != body.user_id:
        db.close()
        raise HTTPException(status_code=404, detail="Card not found")
    if card.is_active:
        db.close()
        raise HTTPException(status_code=409, detail="Card already active")

    active_count = db.query(Card).filter(
        Card.owner_id == body.user_id, Card.is_active == True
    ).count()
    if active_count >= ROSTER_LIMIT:
        db.close()
        raise HTTPException(status_code=409, detail=f"Roster full ({ROSTER_LIMIT} cards max)")

    card.is_active = True
    db.commit()
    db.close()
    return {"status": "ok", "card_id": card_id}


@app.post("/roster/{card_id}/deactivate")
def deactivate_card(card_id: int, body: RosterActionBody):
    db = SessionLocal()
    card = db.get(Card, card_id)
    if not card or card.owner_id != body.user_id:
        db.close()
        raise HTTPException(status_code=404, detail="Card not found")
    card.is_active = False
    db.commit()
    db.close()
    return {"status": "ok", "card_id": card_id}


@app.get("/top")
def top_performances():
    db = SessionLocal()
    results = db.execute(text("""
        SELECT p.name, p.avatar_url, s.fantasy_points
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
        SELECT p.name, p.avatar_url, COUNT(s.id) as matches, AVG(s.fantasy_points) as avg_points
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
def update_weight(key: str, body: WeightUpdateBody):
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
def list_users(user_id: int):
    db = SessionLocal()
    require_admin(user_id, db)
    users = db.query(User).order_by(User.username).all()
    result = []
    for u in users:
        draws_used = db.query(Card).filter(Card.owner_id == u.id).count()
        result.append({
            "id": u.id,
            "username": u.username,
            "draws_used": draws_used,
            "draw_limit": u.draw_limit if u.draw_limit is not None else 7,
        })
    db.close()
    return result


@app.post("/grant-draws")
def grant_draws(body: GrantDrawsBody):
    db = SessionLocal()
    require_admin(body.user_id, db)
    target = db.get(User, body.target_user_id)
    if not target:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount < 1:
        db.close()
        raise HTTPException(status_code=422, detail="Amount must be at least 1")
    target.draw_limit = (target.draw_limit or 7) + body.amount
    db.commit()
    new_limit = target.draw_limit
    db.close()
    return {"username": target.username, "draw_limit": new_limit}


@app.post("/recalculate")
def recalculate(body: AdminBody):
    db = SessionLocal()
    require_admin(body.user_id, db)
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
def schedule_refresh(body: AdminBody):
    db = SessionLocal()
    require_admin(body.user_id, db)
    bust_cache()
    data = get_schedule(db)
    db.close()
    return data


@app.get("/schedule/debug")
def schedule_debug(user_id: int):
    db = SessionLocal()
    require_admin(user_id, db)
    db.close()

    url = os.getenv("SCHEDULE_SHEET_URL", "")
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


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
