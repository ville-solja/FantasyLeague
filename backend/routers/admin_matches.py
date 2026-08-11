import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db
from deps import require_admin, _audit
from models import Match, Player, PlayerMatchStats, Team, TwitchMVP

router = APIRouter()


# ---------------------------------------------------------------------------
# Match table + Admin MVP selection
# ---------------------------------------------------------------------------

class AdminMVPRequest(BaseModel):
    player_id: int


@router.get("/admin/matches")
def list_matches(db=Depends(get_db), _: dict = Depends(require_admin)):
    matches = db.query(Match).order_by(Match.start_time.desc()).all()
    match_ids = [m.match_id for m in matches]

    mvps_by_match = {
        mv.match_id: mv
        for mv in db.query(TwitchMVP).filter(TwitchMVP.match_id.in_(match_ids)).all()
    } if match_ids else {}

    mvp_player_ids = {mv.player_id for mv in mvps_by_match.values()}
    players_by_id = {
        p.id: p for p in db.query(Player).filter(Player.id.in_(mvp_player_ids)).all()
    } if mvp_player_ids else {}

    team_ids = {tid for m in matches for tid in (m.radiant_team_id, m.dire_team_id) if tid}
    teams_by_id = {
        t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()
    } if team_ids else {}

    result = []
    for m in matches:
        mvp = mvps_by_match.get(m.match_id)
        mvp_player = players_by_id.get(mvp.player_id) if mvp else None
        radiant = teams_by_id.get(m.radiant_team_id) if m.radiant_team_id else None
        dire = teams_by_id.get(m.dire_team_id) if m.dire_team_id else None
        result.append({
            "match_id": m.match_id,
            "league_id": m.league_id,
            "radiant_team_id": m.radiant_team_id,
            "dire_team_id": m.dire_team_id,
            "team1": radiant.name if radiant else None,
            "team2": dire.name if dire else None,
            "start_time": m.start_time,
            "mvp_player_name": mvp_player.name if mvp_player else None,
            "mvp_player_id": mvp.player_id if mvp else None,
        })
    return result


@router.get("/admin/matches/{match_id}/players")
def match_players(match_id: int, db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = (
        db.query(Player)
        .join(PlayerMatchStats, PlayerMatchStats.player_id == Player.id)
        .filter(PlayerMatchStats.match_id == match_id)
        .all()
    )
    return [{"id": p.id, "name": p.name} for p in rows]


@router.post("/admin/matches/{match_id}/mvp")
def admin_set_mvp(
    match_id: int,
    body: AdminMVPRequest,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    match = db.query(Match).filter(Match.match_id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    player = db.query(Player).filter(Player.id == body.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    existing = db.query(TwitchMVP).filter(TwitchMVP.match_id == match_id).first()
    if existing:
        existing.player_id = body.player_id
        existing.channel_id = "admin"
        existing.selected_at = int(time.time())
    else:
        db.add(TwitchMVP(
            match_id=match_id,
            player_id=body.player_id,
            channel_id="admin",
            selected_at=int(time.time()),
        ))

    _audit(db, "admin_set_mvp", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match {match_id} → player {body.player_id} ({player.name})")
    db.commit()
    return {"match_id": match_id, "player_id": body.player_id, "player_name": player.name}
