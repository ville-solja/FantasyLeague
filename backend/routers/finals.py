"""Finals predictions (issue #237): the public Div 1 match tree and saving a prediction.
The logic is in finals.py."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

import finals
from database import get_db
from deps import get_current_user, session_user_or_none
from rate_limit import key_by_user_or_ip, limiter

router = APIRouter()

# Tighter than RATE_LIMIT_USER_ACTION: three picks need few saves (finals.MAX_REVISIONS caps the rows).
RATE_LIMIT_FINALS_PREDICTION = "10/minute"

TeamId = Annotated[int, Field(ge=1, le=2**63 - 1)]


class PredictionBody(BaseModel):
    sf1_pick: TeamId
    sf2_pick: TeamId
    final_pick: TeamId


@router.get("/finals")
def get_finals(request: Request, db=Depends(get_db)):
    """The tree, state and lock for everyone (cached briefly); the caller's own
    prediction when logged in."""
    user = session_user_or_none(request, db)
    return finals.cached_public_view(db, user.id if user else None)


def save_prediction(body: PredictionBody, db, current_user: dict):
    own = finals.save_prediction(db, current_user["user_id"], body.sf1_pick, body.sf2_pick,
                                 body.final_pick)
    db.commit()
    return {"prediction": own}


@router.put("/finals/prediction")
@limiter.limit(RATE_LIMIT_FINALS_PREDICTION, key_func=key_by_user_or_ip)
def save_prediction_route(request: Request, body: PredictionBody, db=Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    """Append a revision of the caller's three picks (semi-final 1 and 2, grand final)."""
    return save_prediction(body, db, current_user)
