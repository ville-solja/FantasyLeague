from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import get_db
from deps import get_current_user
from models import Player, User
from auth import hash_password, verify_password

router = APIRouter()


class UpdateUsernameBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class UpdatePlayerIdBody(BaseModel):
    player_id: int | None = None


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password:     str = Field(min_length=6, max_length=128)


@router.get("/me")
def me(request: Request, db=Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0,
            "must_change_password": bool(user.must_change_password)}


@router.get("/profile/{user_id}")
def get_profile(user_id: int, db=Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    result = {"id": user.id, "username": user.username, "player_id": user.player_id,
              "player_name": None, "player_avatar_url": None,
              "twitch_linked": bool(user.twitch_user_id)}
    if user.player_id:
        player = db.get(Player, user.player_id)
        if player:
            result["player_name"] = player.name
            result["player_avatar_url"] = player.avatar_url
    return result


@router.put("/profile/username")
def update_username(body: UpdateUsernameBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="Username cannot be empty")
    existing = db.query(User).filter(User.username == username, User.id != user_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")
    user.username = username
    db.commit()
    return {"username": username}


@router.put("/profile/player-id")
def update_player_id(body: UpdatePlayerIdBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.player_id = body.player_id
    db.commit()
    result = {"player_id": body.player_id, "player_name": None, "player_avatar_url": None}
    if body.player_id:
        player = db.get(Player, body.player_id)
        if player:
            result["player_name"] = player.name
            result["player_avatar_url"] = player.avatar_url
    return result


@router.put("/profile/password")
def change_password(body: ChangePasswordBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user = db.get(User, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=422, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    return {"status": "ok"}
