"""Admin › Settings › Season › Season Finals panel (issue #237): status, tiebreak, pause, close and results.
Thin wrappers; the logic is in finals.py."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import finals
from database import get_db
from deps import _audit, require_admin, require_recent_reauth

router = APIRouter()

TeamId = Annotated[int, Field(ge=1, le=2**63 - 1)]


class TiebreakBody(BaseModel):
    order: list[TeamId] = Field(..., min_length=2, max_length=16)


class ResultBody(BaseModel):
    series: Literal["sf1", "sf2", "final"]
    winner: TeamId


@router.get("/admin/finals")
def get_admin_finals(db=Depends(get_db), _: dict = Depends(require_admin)):
    view = finals.admin_view(db)
    db.commit()
    return view


@router.put("/admin/finals/tiebreak", dependencies=[Depends(require_recent_reauth)])
def put_tiebreak(body: TiebreakBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    b = finals.resolve_tiebreak(db, body.order)
    _audit(db, "admin_finals_tiebreak", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"season_label={b.season_label} order={','.join(map(str, body.order))}")
    db.commit()
    return {"state": finals.bracket_state(db), "seeds": [b.seed1_team_id, b.seed2_team_id,
                                                         b.seed3_team_id, b.seed4_team_id]}


@router.post("/admin/finals/pause")
def post_pause(db=Depends(get_db), admin: dict = Depends(require_admin)):
    b = finals.toggle_pause(db)
    _audit(db, "admin_finals_paused", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"season_label={b.season_label} paused={b.paused}")
    db.commit()
    return {"paused": bool(b.paused)}


@router.post("/admin/finals/close", dependencies=[Depends(require_recent_reauth)])
def post_close(db=Depends(get_db), admin: dict = Depends(require_admin)):
    b = finals.close_now(db)
    _audit(db, "admin_finals_closed", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"season_label={b.season_label} locked_at={b.locked_at} lock_source={b.lock_source}")
    db.commit()
    return {"locked_at": b.locked_at, "lock_source": b.lock_source}


@router.put("/admin/finals/result", dependencies=[Depends(require_recent_reauth)])
def put_result(body: ResultBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    b = finals.set_result(db, body.series, body.winner)
    _audit(db, "admin_finals_result_set", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"season_label={b.season_label} series={body.series} winner={body.winner}")
    db.commit()
    return {"series": body.series, "winner": body.winner,
            "final_winner": b.final_winner, "state": finals.bracket_state(db)}
