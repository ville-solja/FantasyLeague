import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import get_db
from deps import require_admin, _audit
from models import Match, Player, PlayerMatchStats, Team, TwitchMVP, Weight
from twitch import _apply_mvp_bonus

router = APIRouter()


# ---------------------------------------------------------------------------
# Match table + Admin MVP selection
# ---------------------------------------------------------------------------

class AdminMVPRequest(BaseModel):
    player_id: int


class MatchVodBody(BaseModel):
    vod_url: str | None = Field(None, max_length=500)


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
            "vod_url": m.vod_url,
        })
    return result


@router.get("/admin/matches/{match_id}/players")
def match_players(match_id: int, db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = (
        db.query(Player, PlayerMatchStats.team_id, Team.name)
        .join(PlayerMatchStats, PlayerMatchStats.player_id == Player.id)
        .outerjoin(Team, Team.id == PlayerMatchStats.team_id)
        .filter(PlayerMatchStats.match_id == match_id)
        .all()
    )
    return [
        {"id": p.id, "name": p.name, "team_id": team_id, "team_name": team_name}
        for p, team_id, team_name in rows
    ]


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
    old_player_id = existing.player_id if existing else None
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

    weights = {w.key: w.value for w in db.query(Weight).all()}
    if old_player_id and old_player_id != body.player_id:
        _apply_mvp_bonus(db, old_player_id, match_id, apply=False, weights=weights)
    _apply_mvp_bonus(db, body.player_id, match_id, apply=True, weights=weights)

    _audit(db, "admin_set_mvp", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match {match_id} → player {body.player_id} ({player.name})")
    db.commit()
    return {"match_id": match_id, "player_id": body.player_id, "player_name": player.name}


@router.patch("/admin/matches/{match_id}/vod")
def set_match_vod(
    match_id: int,
    body: MatchVodBody,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    match = db.query(Match).filter(Match.match_id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    vod_url = body.vod_url.strip() if body.vod_url else None
    if vod_url and not (vod_url.startswith("http://") or vod_url.startswith("https://")):
        raise HTTPException(status_code=422, detail="vod_url must be a valid http(s) URL")

    match.vod_url = vod_url
    _audit(db, "admin_match_vod_set", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match {match_id} vod_url={vod_url}")
    db.commit()
    return {"match_id": match_id, "vod_url": match.vod_url}
