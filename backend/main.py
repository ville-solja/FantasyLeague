import random
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from models import Player, PlayerMatchStats, Card, User, Weight
from database import SessionLocal, engine, Base
from ingest import ingest_league
from enrich import run_enrichment
from seed import seed_users, seed_cards, seed_weights
from scoring import fantasy_score


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_users()
    seed_weights()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
def root():
    return {"status": "running"}


@app.post("/ingest/league/{league_id}")
def ingest_league_endpoint(league_id: int):
    ingest_league(league_id)
    run_enrichment()
    seed_cards()
    return {"status": "ok", "league_id": league_id}


@app.get("/users")
def get_users():
    db = SessionLocal()
    users = db.query(User).all()
    data = [{"id": u.id, "username": u.username, "is_admin": u.is_admin} for u in users]
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
def draw_card(user_id: int):
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
    card.owner_id = user_id
    db.commit()
    db.close()
    return {"id": chosen.id, "card_type": chosen.card_type, "player_name": chosen.player_name}


@app.get("/roster/{user_id}")
def get_roster(user_id: int):
    db = SessionLocal()
    results = db.execute(text("""
        SELECT c.id, c.card_type, p.name as player_name,
               COALESCE(SUM(s.fantasy_points), 0) as total_points
        FROM cards c
        JOIN players p ON p.id = c.player_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        WHERE c.owner_id = :user_id
        GROUP BY c.id, c.card_type, p.name
        ORDER BY total_points DESC
    """), {"user_id": user_id}).fetchall()
    db.close()
    return [dict(r._mapping) for r in results]


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


@app.get("/weights")
def get_weights():
    db = SessionLocal()
    weights = db.query(Weight).order_by(Weight.key).all()
    data = [{"key": w.key, "label": w.label, "value": w.value} for w in weights]
    db.close()
    return data


@app.put("/weights/{key}")
def update_weight(key: str, value: float):
    db = SessionLocal()
    weight = db.get(Weight, key)
    if not weight:
        db.close()
        raise HTTPException(status_code=404, detail="Weight not found")
    weight.value = value
    db.commit()
    db.close()
    return {"key": key, "value": value}


@app.post("/recalculate")
def recalculate():
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


app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")
