from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text

from database import get_db
from deps import require_admin, _audit
from models import League, Match, MatchBan, PlayerMatchStats

router = APIRouter()


# ---------------------------------------------------------------------------
# League Management
# ---------------------------------------------------------------------------

@router.get("/admin/leagues")
def list_leagues(db=Depends(get_db), admin=Depends(require_admin)):
    leagues = db.query(League).all()
    match_counts = {
        r[0]: r[1] for r in
        db.query(Match.league_id, func.count(Match.match_id))
          .group_by(Match.league_id).all()
    }
    return [
        {
            "id": l.id,
            "name": l.name or "(unknown)",
            "is_monitored": l.is_monitored,
            "match_count": match_counts.get(l.id, 0),
        }
        for l in leagues
    ]


@router.post("/admin/leagues/{league_id}/monitor")
def add_monitored_league(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    league = db.get(League, league_id)
    if league and league.is_monitored:
        raise HTTPException(status_code=409, detail="League is already monitored")
    if not league:
        league = League(id=league_id, name="(pending ingest)", is_monitored=True)
        db.add(league)
    else:
        league.is_monitored = True
    _audit(db, "admin_league_add_monitor", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"league_id={league_id}")
    db.commit()
    return {"status": "ok", "league_id": league_id}


@router.delete("/admin/leagues/{league_id}/monitor")
def remove_monitored_league(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    league = db.get(League, league_id)
    if not league or not league.is_monitored:
        raise HTTPException(status_code=404, detail="League is not currently monitored")
    league.is_monitored = False
    _audit(db, "admin_league_remove_monitor", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"league_id={league_id}")
    db.commit()
    return {"status": "ok", "league_id": league_id}


@router.delete("/admin/leagues/{league_id}/data")
def purge_league_data(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    match_ids = [r[0] for r in db.execute(
        text("SELECT match_id FROM matches WHERE league_id = :lid"), {"lid": league_id}
    ).fetchall()]
    deleted_stats = 0
    deleted_bans = 0
    if match_ids:
        deleted_stats = (
            db.query(PlayerMatchStats)
            .filter(PlayerMatchStats.match_id.in_(match_ids))
            .delete(synchronize_session=False)
        )
        deleted_bans = (
            db.query(MatchBan)
            .filter(MatchBan.match_id.in_(match_ids))
            .delete(synchronize_session=False)
        )
    deleted_matches = (
        db.query(Match)
        .filter(Match.league_id == league_id)
        .delete(synchronize_session=False)
    )
    league = db.get(League, league_id)
    if league:
        league.is_monitored = False
    _audit(db, "admin_league_purge", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"league_id={league_id} matches={deleted_matches} stats={deleted_stats}")
    db.commit()
    return {
        "status": "ok",
        "league_id": league_id,
        "deleted_matches": deleted_matches,
        "deleted_stats": deleted_stats,
        "deleted_bans": deleted_bans,
        "note": "Run /recalculate to refresh fantasy scores after purge",
    }
