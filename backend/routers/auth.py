import logging
import os
import re as _re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import get_db
from deps import _audit, get_current_user
from models import User, TokenGrantEvent, TokenGrantClaim, Notification, NotificationDismissal
from auth import hash_password, verify_password
from email_utils import send_email

router = APIRouter()

INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email:    str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)


class ForgotPasswordBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)


@router.post("/login")
def login(request: Request, body: LoginBody, db=Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user.must_change_password and user.temp_password_expires_at:
        if int(time.time()) > user.temp_password_expires_at:
            raise HTTPException(
                status_code=401,
                detail="Temporary password has expired. Please request a new password reset.",
            )
    request.session["user_id"]  = user.id
    request.session["username"] = user.username
    request.session["is_admin"] = user.is_admin
    _audit(db, "user_login", actor_id=user.id, actor_username=user.username)
    db.commit()
    return {"username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0}


@router.post("/register")
def register(request: Request, body: RegisterBody, db=Depends(get_db)):
    _e = body.email.strip()
    _at = _e.find("@")
    if _at < 1 or " " in _e or _e.count("@") != 1 or "." not in _e[_at + 2:] or _e.endswith("."):
        raise HTTPException(status_code=422, detail="Invalid email address")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    initial = int(os.getenv("INITIAL_TOKENS", "5"))
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        is_admin=False,
        tokens=initial,
        created_at=int(time.time()),
    )
    db.add(user)
    db.flush()
    _audit(db, "user_register", actor_id=user.id, actor_username=user.username)
    db.commit()
    request.session["user_id"]  = user.id
    request.session["username"] = user.username
    request.session["is_admin"] = user.is_admin
    return {"username": user.username, "is_admin": user.is_admin, "tokens": user.tokens}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


_DUMMY_HASH = hash_password("dummy-timing-equalizer")


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordBody, db=Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not user.email:
        verify_password("dummy-timing-equalizer", _DUMMY_HASH)  # equalize bcrypt timing
        return {"status": "ok"}

    user_email    = user.email
    user_username = user.username
    user_id       = user.id

    temp_password = secrets.token_urlsafe(9)
    ttl_hours = int(os.getenv("TEMP_PASSWORD_TTL_HOURS", "24"))
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    user.temp_password_expires_at = int(time.time()) + ttl_hours * 3600
    _audit(db, "password_reset_requested", actor_id=user_id, actor_username=user_username)

    app_name = os.getenv("APP_NAME", "Kanaliiga Fantasy")
    try:
        send_email(
            to_address=user_email,
            subject=f"[{app_name}] Your temporary password",
            body=(
                f"Hi {user_username},\n\n"
                f"A temporary password has been issued for your account:\n\n"
                f"    {temp_password}\n\n"
                f"Your previous password is no longer valid.\n"
                f"This temporary password expires in {ttl_hours} hour(s). "
                f"Log in and go to your Profile to set a permanent password.\n\n"
                f"If you did not request this reset, contact support immediately.\n"
            ),
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "forgot_password: email send failed for user %s — aborting password change", user_username
        )
        db.rollback()
        raise HTTPException(status_code=503, detail="Failed to send reset email; please try again later")

    db.commit()
    return {"status": "ok"}


@router.post("/claim-events")
def claim_events(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    now = int(time.time())
    active_events = db.query(TokenGrantEvent).filter(
        TokenGrantEvent.start_time <= now,
        TokenGrantEvent.end_time >= now,
    ).all()
    user = db.get(User, current_user["user_id"])
    granted = 0
    for event in active_events:
        already = db.query(TokenGrantClaim).filter_by(event_id=event.id, user_id=user.id).first()
        if already:
            continue
        user.tokens = (user.tokens or 0) + event.amount
        db.add(TokenGrantClaim(event_id=event.id, user_id=user.id, claimed_at=now))
        _audit(db, "token_grant_event_claim", actor_id=user.id, actor_username=user.username,
               detail=f"event={event.id} amount={event.amount}")
        granted += event.amount
    db.commit()
    return {"granted": granted}


@router.get("/notifications")
def get_active_notifications(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    now = int(time.time())
    active = db.query(Notification).filter(
        Notification.start_time <= now,
        Notification.end_time   >= now,
    ).all()
    seen_ids = {r.notification_id for r in
                db.query(NotificationDismissal)
                  .filter(NotificationDismissal.user_id == current_user["user_id"]).all()}
    return [{"id": n.id, "message": n.message} for n in active if n.id not in seen_ids]


@router.post("/notifications/{notification_id}/dismiss")
def dismiss_notification(notification_id: int, db=Depends(get_db),
                         current_user: dict = Depends(get_current_user)):
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    existing = db.query(NotificationDismissal).filter_by(
        notification_id=notification_id, user_id=current_user["user_id"]).first()
    if not existing:
        db.add(NotificationDismissal(notification_id=notification_id,
                                     user_id=current_user["user_id"],
                                     dismissed_at=int(time.time())))
        db.commit()
    return {"ok": True}
