from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

import sessions
from database import get_db
from deps import _audit, get_current_user
from models import PasswordResetToken, Player, SeasonArchive, User, UserTag, TagDefinition
from scoring import display_points
from auth import (check_password_bytes, check_username, hash_password, username_policy_error,
                  verify_password)
from routers.auth import send_password_changed_notice

router = APIRouter()


class UpdateUsernameBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)

    _username_chars = field_validator("username")(check_username)


class UpdatePlayerIdBody(BaseModel):
    player_id: int | None = None


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password:     str = Field(min_length=6, max_length=128)

    # Only the new password is capped; the current one may predate the cap.
    _password_bytes = field_validator("new_password")(check_password_bytes)


@router.get("/me")
def me(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user = db.get(User, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0,
            "must_change_password": bool(user.must_change_password)}


@router.get("/profile/{user_id}")
def get_profile(user_id: int, db=Depends(get_db),
                 current_user: dict = Depends(get_current_user)):
    user = db.get(User, user_id)
    # Twitch viewer soft accounts (issue #157) have no public profile.
    if not user or user.account_type == "twitch":
        raise HTTPException(status_code=404, detail="User not found")
    # Issue #169: the linked player id is self-reported, so another user's profile
    # shows only the in-game name, marked self-reported: no Steam-identifying id and
    # no avatar to borrow. The owner and admins see everything.
    full_view = current_user["user_id"] == user.id or bool(current_user.get("is_admin"))
    result = {"id": user.id, "username": user.username,
              "player_id": user.player_id if full_view else None,
              "player_name": None, "player_avatar_url": None,
              "player_self_reported": bool(user.player_id),
              "is_admin": bool(user.is_admin),
              "twitch_linked": bool(user.twitch_user_id)}
    if user.player_id:
        player = db.get(Player, user.player_id)
        if player:
            result["player_name"] = player.name
            if full_view:
                result["player_avatar_url"] = player.avatar_url
    tag_rows = (
        db.query(UserTag, TagDefinition)
        .join(TagDefinition, TagDefinition.id == UserTag.tag_id)
        .filter(UserTag.user_id == user.id)
        .all()
    )
    result["tags"] = [{"key": td.key, "label": td.label} for _, td in tag_rows]
    past_rows = (
        db.query(SeasonArchive)
        .filter(SeasonArchive.user_id == user.id)
        .order_by(SeasonArchive.archived_at.desc(), SeasonArchive.id.desc())
        .all()
    )
    result["past_seasons"] = [{"season_label": r.season_label,
                               "points": display_points(r.points), "rank": r.rank}
                              for r in past_rows]
    return result


@router.put("/profile/username")
def update_username(body: UpdateUsernameBody, db=Depends(get_db),
                    current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="Username cannot be empty")
    if username != user.username:
        policy_error = username_policy_error(db, username, exclude_user_id=user_id)
        if policy_error:
            raise HTTPException(status_code=policy_error[0], detail=policy_error[1])
    old_username = user.username
    user.username = username
    if old_username != username:
        _audit(db, "username_changed", actor_id=user.id, actor_username=username,
               detail=f"old={old_username} new={username}")
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
def change_password(request: Request, body: ChangePasswordBody, db=Depends(get_db),
                    current_user: dict = Depends(get_current_user)):
    user = db.get(User, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=422, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.temp_password_expires_at = None
    # A password change supersedes any reset link still sitting in the inbox.
    db.query(PasswordResetToken).filter_by(user_id=user.id).delete()
    # Log out every other session, and give the requester's session a new ID.
    current = sessions.current_row(request, db)
    sessions.delete_user_sessions(db, user.id, keep_id=current.id if current else None)
    sessions.start_session(request, db, user)
    db.commit()
    send_password_changed_notice(user)
    return {"status": "ok"}
