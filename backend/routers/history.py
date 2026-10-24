"""Public season history and accolade data (issues #50, #53).

GET /history/seasons serves the History tab; GET /accolades serves the accolade pips
on every card and list, and the tag pips on cards (issue #217). Neither carries user
ids, and GET /accolades carries no usernames: a fantasy win and a user's tags show on a
player only through that user's current verified link.
"""
from fastapi import APIRouter, Depends

import accolades
from database import get_db

router = APIRouter()


@router.get("/history/seasons")
def history_seasons(db=Depends(get_db)):
    """One entry per season, newest first (champion teams, the four awards with ties,
    the played count), and the hall of fame (players ranked by titles; played is not
    a title)."""
    return accolades.history(db, accolades.current_season_label(db))


@router.get("/accolades")
def get_accolades(db=Depends(get_db)):
    """{current_season, players: {player_id: [accolade, ...]}, tags: {player_id:
    [{key, label}, ...]}}. players covers every player with an accolade or a scored
    match this season; each accolade: kind, division, season, season_short, team_name,
    value, match_id. tags covers players with a verified linked user who has tags or
    is an admin (accolades.tags_by_player)."""
    current = accolades.current_season_label(db)
    per_player = accolades.accolades_for(db, current=current)
    return {"current_season": current, "current_season_short": accolades.short_season(current),
            "players": {str(pid): lst for pid, lst in per_player.items()},
            "tags": {str(pid): lst for pid, lst in accolades.tags_by_player(db).items()}}
