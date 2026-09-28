import logging
import os
import re as _re
import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from database import get_db
from deps import _audit, get_current_user
from models import (User, TokenGrantEvent, TokenGrantClaim, Notification,
                    NotificationDismissal, PasswordResetToken)
from auth import check_email, check_password_bytes, check_username, hash_password, verify_password
from email_utils import email_configured, send_email
from rate_limit import limiter, key_by_user_or_ip

router = APIRouter()

INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))

RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "5/minute")
RATE_LIMIT_REGISTER = os.getenv("RATE_LIMIT_REGISTER", "5/minute")
RATE_LIMIT_FORGOT_PASSWORD = os.getenv("RATE_LIMIT_FORGOT_PASSWORD", "3/minute")
RATE_LIMIT_RESET_PASSWORD = os.getenv("RATE_LIMIT_RESET_PASSWORD", "10/minute")

# Per-username failed-login lockout, independent of source IP — catches an
# attacker rotating IPs against one account, which the per-IP RATE_LIMIT_LOGIN
# limiter alone would not. In-memory only (same reasoning as the slowapi
# limiter itself: single-process deployment, no shared-state backend needed;
# lockout state resetting on restart is an acceptable tradeoff).
_LOGIN_LOCKOUT_THRESHOLD = int(os.getenv("LOGIN_LOCKOUT_THRESHOLD", "10"))
_LOGIN_LOCKOUT_WINDOW_SECONDS = int(os.getenv("LOGIN_LOCKOUT_WINDOW_SECONDS", "300"))
_LOGIN_LOCKOUT_MESSAGE = "Too many failed login attempts. Please try again later."
_failed_login_attempts: dict[str, list[float]] = defaultdict(list)


def _is_locked_out(username: str) -> bool:
    now = time.time()
    attempts = _failed_login_attempts[username]
    attempts[:] = [t for t in attempts if now - t < _LOGIN_LOCKOUT_WINDOW_SECONDS]
    return len(attempts) >= _LOGIN_LOCKOUT_THRESHOLD


def _record_failed_login(username: str):
    _failed_login_attempts[username].append(time.time())


def _clear_failed_logins(username: str):
    _failed_login_attempts.pop(username, None)


# Per-username cooldown on POST /forgot-password, independent of source IP —
# closes the remaining gap left by RATE_LIMIT_FORGOT_PASSWORD (per-IP, issue
# #121): an attacker spread across multiple IPs, or simply waiting out the
# per-IP window, could otherwise still repeatedly trigger reset emails
# against one specific account. Unlike the login lockout (a threshold over a
# window), this is a simple cooldown: at most one reset email per account per
# FORGOT_PASSWORD_COOLDOWN_SECONDS. In-memory only, same reasoning as the
# lockout state above.
FORGOT_PASSWORD_COOLDOWN_SECONDS = int(os.getenv("FORGOT_PASSWORD_COOLDOWN_SECONDS", "300"))
_last_forgot_password_request: dict[str, float] = {}


def _forgot_password_in_cooldown(username: str) -> bool:
    last = _last_forgot_password_request.get(username)
    return last is not None and (time.time() - last) < FORGOT_PASSWORD_COOLDOWN_SECONDS


def _record_forgot_password_request(username: str):
    _last_forgot_password_request[username] = time.time()


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    # No 72-byte cap here: accounts created before the cap may have longer
    # passwords, and bcrypt 4.x truncates identically at hash and verify time.
    password: str = Field(min_length=1, max_length=128)


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email:    str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)

    _password_bytes = field_validator("password")(check_password_bytes)
    _email_shape = field_validator("email")(check_email)
    _username_chars = field_validator("username")(check_username)


class ForgotPasswordBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class ResetPasswordBody(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)

    _password_bytes = field_validator("new_password")(check_password_bytes)


@router.post("/login")
@limiter.limit(RATE_LIMIT_LOGIN)
def login(request: Request, body: LoginBody, db=Depends(get_db)):
    # Check the per-username lockout first, before touching the DB or bcrypt
    # at all — same fast-exit spirit as the /forgot-password timing
    # equalization below. The message is identical whether or not the
    # username exists in the DB (the lockout counter itself is keyed by the
    # submitted username string, existing or not), so this never reveals
    # username existence.
    if _is_locked_out(body.username):
        raise HTTPException(status_code=429, detail=_LOGIN_LOCKOUT_MESSAGE)
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        _record_failed_login(body.username)
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
    _clear_failed_logins(user.username)
    _audit(db, "user_login", actor_id=user.id, actor_username=user.username)
    db.commit()
    return {"username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0}


@router.post("/register")
@limiter.limit(RATE_LIMIT_REGISTER)
def register(request: Request, body: RegisterBody, db=Depends(get_db)):
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
@limiter.limit(RATE_LIMIT_FORGOT_PASSWORD)
def forgot_password(request: Request, body: ForgotPasswordBody, db=Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not user.email:
        verify_password("dummy-timing-equalizer", _DUMMY_HASH)  # equalize bcrypt timing
        return {"status": "ok"}

    if _forgot_password_in_cooldown(body.username):
        # Same shape as the nonexistent-username fast-exit above — a
        # cooldown-suppressed request must be indistinguishable from it, so
        # the cooldown never becomes a new username-enumeration side channel.
        verify_password("dummy-timing-equalizer", _DUMMY_HASH)  # equalize bcrypt timing
        return {"status": "ok"}

    # Record before attempting the send — a slow SMTP send must not let a rapid
    # retry bypass the cooldown. A failed send clears it again below.
    _record_forgot_password_request(body.username)

    user_email    = user.email
    user_username = user.username
    user_id       = user.id

    # Invalidate any prior unused token for this account before issuing a new one —
    # only one live reset token per user at a time (mirrors TwitchLinkCode's
    # invalidate-on-regenerate pattern in twitch.py's generate_link_code()).
    db.query(PasswordResetToken).filter_by(user_id=user_id).delete()
    token = secrets.token_urlsafe(32)
    ttl_hours = int(os.getenv("PASSWORD_RESET_TOKEN_TTL_HOURS", "1"))
    db.add(PasswordResetToken(token=token, user_id=user_id,
                              expires_at=int(time.time()) + ttl_hours * 3600))
    _audit(db, "password_reset_requested", actor_id=user_id, actor_username=user_username)

    app_name = os.getenv("APP_NAME", "Kana Cards")
    base_url = os.getenv("APP_BASE_URL", "").rstrip("/")
    link_block = f"    {base_url}/?reset_token={token}\n\n" if base_url else ""
    send_failed = False
    try:
        sent = send_email(
            to_address=user_email,
            subject=f"[{app_name}] Password reset requested",
            body=(
                f"Hi {user_username},\n\n"
                f"A password reset was requested for your account.\n\n"
                f"{link_block}"
                f"    Reset code: {token}\n\n"
                f"Enter this code on the login screen's 'Reset password' form if you don't use "
                f"the link above. This code expires in {ttl_hours} hour(s).\n\n"
                f"Your current password has not been changed and remains valid — nothing happens "
                f"to your account until you complete this step. If you did not request this, you "
                f"can safely ignore this email.\n"
            ),
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "forgot_password: email send raised for user %s", user_username
        )
        send_failed = True
    else:
        # False without SMTP_HOST is the local-dev fallback: send_email() has
        # already logged a warning, and the token is kept as before.
        send_failed = not sent and email_configured()
    if send_failed:
        # The send raised, or a configured send failed. Roll back the new token
        # (the prior token's delete is undone too) and the cooldown stamp so
        # the user can retry right away.
        logging.getLogger(__name__).error(
            "forgot_password: email send failed for user %s — aborting", user_username
        )
        db.rollback()
        _last_forgot_password_request.pop(body.username, None)
        raise HTTPException(status_code=503, detail="Failed to send reset email; please try again later")

    db.commit()
    return {"status": "ok"}


@router.post("/reset-password")
@limiter.limit(RATE_LIMIT_RESET_PASSWORD)
def reset_password(request: Request, body: ResetPasswordBody, db=Depends(get_db)):
    token_row = db.get(PasswordResetToken, body.token)
    if not token_row or token_row.expires_at < int(time.time()):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user = db.get(User, token_row.user_id)
    if not user:
        db.delete(token_row)
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user.password_hash = hash_password(body.new_password)
    # Cleanup: clear any legacy pre-fix temp-password state (matches what
    # PUT /profile/password already does), since this reset supersedes it.
    user.must_change_password = False
    user.temp_password_expires_at = None
    db.delete(token_row)
    _audit(db, "password_reset_completed", actor_id=user.id, actor_username=user.username)
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
