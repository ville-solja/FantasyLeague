"""Team Finder (issue #220): browsing the listings, the captain's own listing, the id
lookup and "Not on this team". The logic is in team_signup.py."""
from typing import Annotated, Union

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address

import player_lookup
import team_signup
from database import get_db
from deps import _audit, get_current_user, session_user_or_none
from models import User
from rate_limit import key_by_user_or_ip, limiter

router = APIRouter()

RATE_LIMIT_TEAM_SIGNUP_SAVE = "10/minute"
RATE_LIMIT_TEAM_SIGNUP_LOOKUP = "30/minute"
RATE_LIMIT_TEAM_SIGNUP_VIEW = "60/minute"

# A typed id: digits (a 32-bit Dota id or a Steam64 id) as a string or a number.
TypedId = Union[Annotated[int, Field(ge=1, le=2**63 - 1)], Annotated[str, Field(min_length=1, max_length=20)]]
Role = Annotated[int, Field(ge=1, le=5)]


class ListingBody(BaseModel):
    team_name: str = Field(..., max_length=200)
    players: list[TypedId] = Field(default_factory=list, max_length=team_signup.MAX_PLAYERS + 1)
    open_roles: list[Role] = Field(default_factory=list, max_length=5)
    note: str = Field("", max_length=2000)
    contact: str = Field(..., max_length=500)
    is_full: bool = False


def optional_user(request: Request, db=Depends(get_db)):
    """The logged-in website User, or None (contacts and the own listing need a login)."""
    return session_user_or_none(request, db)


def _user_row(db, current_user: dict) -> User:
    user = db.get(User, current_user["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_team_signup(db, viewer):
    return team_signup.public_view(db, viewer)


@router.get("/team-signup")
@limiter.limit(RATE_LIMIT_TEAM_SIGNUP_VIEW, key_func=get_remote_address)
def get_team_signup_route(request: Request, db=Depends(get_db), viewer=Depends(optional_user)):
    """The open period, its listings (contacts only when logged in) and the caller's own."""
    return get_team_signup(db, viewer)


def lookup(ids: str, db, current_user: dict):
    if not team_signup.is_open(db):
        raise HTTPException(status_code=409, detail="Signup is closed")
    id_list = player_lookup.parse_ids(ids, max_ids=team_signup.MAX_PLAYERS + 1)
    return player_lookup.describe(db, id_list, user_key=current_user["user_id"])


@router.get("/team-signup/lookup")
@limiter.limit(RATE_LIMIT_TEAM_SIGNUP_LOOKUP, key_func=key_by_user_or_ip)
def lookup_route(request: Request, ids: str = Query("", max_length=200), db=Depends(get_db),
                 current_user: dict = Depends(get_current_user)):
    """Names and medals for typed ids (Dota or Steam64, converted), in typed order, while
    a period is open. OpenDota calls are capped per user and in total and never wait."""
    return lookup(ids, db, current_user)


def save_mine(body: ListingBody, db, current_user: dict):
    user = _user_row(db, current_user)
    team_signup.save_listing(db, user, team_name=body.team_name, players=body.players,
                             open_roles=body.open_roles, note=body.note, contact=body.contact,
                             is_full=body.is_full)
    db.commit()
    return team_signup.public_view(db, user)["mine"]


@router.put("/team-signup/mine")
@limiter.limit(RATE_LIMIT_TEAM_SIGNUP_SAVE, key_func=key_by_user_or_ip)
def save_mine_route(request: Request, body: ListingBody, db=Depends(get_db),
                    current_user: dict = Depends(get_current_user)):
    """Create or update the caller's listing in the open period."""
    return save_mine(body, db, current_user)


def delete_mine(db, current_user: dict):
    team_signup.delete_listing(db, _user_row(db, current_user))
    db.commit()
    return {"ok": True}


@router.delete("/team-signup/mine")
@limiter.limit(RATE_LIMIT_TEAM_SIGNUP_SAVE, key_func=key_by_user_or_ip)
def delete_mine_route(request: Request, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Delete the caller's listing, its players and its contact at once."""
    return delete_mine(db, current_user)


def not_on_team(signup_id: int, db, current_user: dict):
    user = _user_row(db, current_user)
    signup, period, account_id = team_signup.not_on_team(db, user, signup_id)
    _audit(db, "team_signup_not_on_team", actor_id=user.id, actor_username=user.username,
           detail=f"period={period.label if period else ''} signup_id={signup.id} account_id={account_id}")
    db.commit()
    return {"ok": True}


@router.post("/team-signup/{signup_id}/not-on-team")
@limiter.limit(RATE_LIMIT_TEAM_SIGNUP_SAVE, key_func=key_by_user_or_ip)
def not_on_team_route(request: Request, signup_id: Annotated[int, Path(ge=1, le=2**63 - 1)],
                      db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Remove the caller's Steam-verified player from another captain's listing."""
    return not_on_team(signup_id, db, current_user)
