import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from database import get_db
from deps import require_admin
from enrich import run_profile_enrichment
from models import Player, PlayerProfile

router = APIRouter()


@router.get("/players")
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


@router.get("/players/{player_id}")
def get_player(player_id: int, db=Depends(get_db)):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    stats = db.execute(text("""
        SELECT s.match_id, m.start_time, s.fantasy_points, s.is_mvp,
               s.kills, s.assists, s.deaths, s.gold_per_min, s.obs_placed,
               s.last_hits, s.denies, s.towers_killed, s.roshan_kills,
               s.teamfight_participation, s.camps_stacked, s.rune_pickups,
               s.firstblood_claimed, s.stuns,
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


@router.get("/players/{player_id}/profile")
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


@router.get("/teams")
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


@router.get("/teams/{team_id}")
def get_team(team_id: int, db=Depends(get_db)):
    from models import Team
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
