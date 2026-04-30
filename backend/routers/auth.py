import os
import re as _re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import get_db
from deps import _audit
from models import User
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
    request.session["user_id"]  = user.id
    request.session["username"] = user.username
    request.session["is_admin"] = user.is_admin
    _audit(db, "user_login", actor_id=user.id, actor_username=user.username)
    db.commit()
    return {"username": user.username, "is_admin": user.is_admin,
            "tokens": user.tokens if user.tokens is not None else 0}


@router.post("/register")
def register(request: Request, body: RegisterBody, db=Depends(get_db)):
    if not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', body.email.strip()):
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


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordBody, db=Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not user.email:
        return {"status": "ok"}

    user_email    = user.email
    user_username = user.username
    user_id       = user.id

    temp_password = secrets.token_urlsafe(9)
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    _audit(db, "password_reset_requested", actor_id=user_id, actor_username=user_username)
    db.commit()

    app_name = os.getenv("APP_NAME", "Kanaliiga Fantasy")
    send_email(
        to_address=user_email,
        subject=f"[{app_name}] Your temporary password",
        body=(
            f"Hi {user_username},\n\n"
            f"A temporary password has been issued for your account:\n\n"
            f"    {temp_password}\n\n"
            f"Log in and go to your Profile to set a new password.\n"
            f"This temporary password will stop working once you change it.\n\n"
            f"If you did not request this, your account is still safe — "
            f"the password was not changed until you log in and update it.\n"
        ),
    )
    return {"status": "ok"}
