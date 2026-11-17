import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import obs_overlay
from database import get_db
from rate_limit import RATE_LIMIT_GLOBAL, limiter

router = APIRouter()

_MAX_ID = 2**63 - 1


def _parse_teams(raw: str) -> tuple[int, int]:
    """'<id>,<id>': exactly two different whole numbers in 1..2**63-1, whitespace
    around each allowed. Anything else is a 422."""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 2 or not all(re.fullmatch(r"[0-9]{1,19}", p) for p in parts):
        raise HTTPException(status_code=422, detail="teams must be two team ids: <id>,<id>")
    a, b = int(parts[0]), int(parts[1])
    if not (1 <= a <= _MAX_ID and 1 <= b <= _MAX_ID) or a == b:
        raise HTTPException(status_code=422, detail="teams must be two different team ids")
    return a, b


def obs_last_game(teams: str, db):
    # Issue 246: the OBS pause-screen overlay. Public league data only (no user,
    # card or ownership fields).
    team_a, team_b = _parse_teams(teams)
    data = obs_overlay.last_game(db, team_a, team_b, int(time.time()))
    if data is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return data


# The route carries the global per-IP limit itself: SlowAPIMiddleware's default limit
# never reaches routes added with include_router (newer FastAPI wraps them in
# _IncludedRouter, so the middleware finds no handler and lets the request through).
@router.get("/obs/last-game")
@limiter.limit(RATE_LIMIT_GLOBAL)
def obs_last_game_route(request: Request, teams: str = Query(max_length=64), db=Depends(get_db)):
    return obs_last_game(teams, db)
