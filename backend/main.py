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


def require_admin(user_id: int, db):
    user = db.get(User, user_id)
    if not user or not user.is_admin:
        db.close()
        raise HTTPException(status_code=403, detail="Admin access required")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
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
    seed_cards()
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
    unclaimed = db.execute(text("""
        SELECT c.id, c.card_type, p.name as player_name
        FROM cards c
        JOIN players p ON p.id = c.player_id
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
        "is_active": is_active,
    }


@app.get("/roster/{user_id}")
def get_roster(user_id: int):
    db = SessionLocal()
    results = db.execute(text("""
        SELECT c.id, c.card_type, c.is_active, p.name as player_name,
               COALESCE(SUM(s.fantasy_points), 0) as total_points
        FROM cards c
        JOIN players p ON p.id = c.player_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        WHERE c.owner_id = :user_id
        GROUP BY c.id, c.card_type, c.is_active, p.name
        ORDER BY c.is_active DESC, total_points DESC
    """), {"user_id": user_id}).fetchall()

    cards = [dict(r._mapping) for r in results]
    active = [c for c in cards if c["is_active"]]
    bench  = [c for c in cards if not c["is_active"]]
    combined = sum(c["total_points"] for c in active)

    db.close()
    return {"active": active, "bench": bench, "combined_value": combined}


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
        SELECT p.name, s.fantasy_points
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
        SELECT p.name, COUNT(s.id) as matches, AVG(s.fantasy_points) as avg_points
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        GROUP BY p.id, p.name
        ORDER BY avg_points DESC
    """)).fetchall()
    db.close()
    return [dict(r._mapping) for r in results]


@app.get("/leaderboard/roster")
def roster_leaderboard():
    db = SessionLocal()
    results = db.execute(text("""
        SELECT u.username,
               COUNT(c.id) as active_cards,
               COALESCE(SUM(pts.total), 0) as roster_value
        FROM users u
        LEFT JOIN cards c ON c.owner_id = u.id AND c.is_active = true
        LEFT JOIN (
            SELECT player_id, SUM(fantasy_points) as total
            FROM player_match_stats
            GROUP BY player_id
        ) pts ON pts.player_id = c.player_id
        GROUP BY u.id, u.username
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


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
