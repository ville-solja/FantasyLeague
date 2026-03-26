from fastapi import FastAPI
from models import Player, PlayerMatchStats
from database import SessionLocal, engine, Base
from ingest import ingest_league
from enrich import run_enrichment


app = FastAPI()

Base.metadata.create_all(bind=engine)

@app.get("/")
def root():
    return {"status": "running"}

@app.post("/ingest/league/{league_id}")
def ingest_league_endpoint(league_id: int):
    ingest_league(league_id)
    run_enrichment()
    return {"status": "ok", "league_id": league_id}


@app.get("/leaderboard/{division}")
def leaderboard(division: str):
    db = SessionLocal()

    results = db.execute(f"""
        SELECT p.name, p.team, COUNT(s.id) as matches, AVG(s.fantasy_points) as avg_score
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        WHERE p.division = '{division}'
        GROUP BY p.id
        HAVING COUNT(s.id) >= 3
        ORDER BY avg_score DESC
    """)

    data = [dict(r._mapping) for r in results]
    db.close()
    return data

@app.get("/top")
def top_performances():
    db = SessionLocal()

    results = db.execute("""
        SELECT p.name, s.fantasy_points
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        ORDER BY s.fantasy_points DESC
        LIMIT 3
    """)

    data = [dict(r._mapping) for r in results]
    db.close()
    return data