import os
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError

import sessions
import soft_accounts
from database import get_db
from deps import (get_current_user, require_admin, require_recent_reauth,
                  require_typed_confirmation, _audit)
from models import AuditLog, Card, PromoCode, CodeRedemption, User, TokenGrantEvent, TokenGrantClaim, TagDefinition, UserTag
from rate_limit import limiter, key_by_user_or_ip

router = APIRouter()

# Per-user limit on promo-code guessing (issue #135). redeem_code stays a plain
# function so direct calls keep working; redeem_code_route carries the
# `request` parameter slowapi needs (same split as routers/cards.py).
RATE_LIMIT_REDEEM = os.getenv("RATE_LIMIT_REDEEM", "5/minute")

GRANT_TOKENS_MAX = 10_000


class GrantTokensBody(BaseModel):
    target_user_id: int
    amount: int = Field(le=GRANT_TOKENS_MAX)


class CreateCodeBody(BaseModel):
    code:            str = Field(min_length=1, max_length=64)
    token_amount:    int
    # Issue #167: optional limits. expires_at is a Unix timestamp.
    expires_at:      int | None = None
    max_redemptions: int | None = Field(default=None, ge=1)


class RedeemCodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=64)


_ACCOUNT_TYPE_FILTERS = {"full", "twitch", "all"}


@router.get("/users")
def list_users(account_type: str = "full", db=Depends(get_db), _: dict = Depends(require_admin)):
    """Admin user list. account_type filters it: "full" (website accounts, the
    default), "twitch" (Twitch viewer soft accounts, issue #157) or "all". The
    Twitch ids themselves are never returned, only whether they are set."""
    if account_type not in _ACCOUNT_TYPE_FILTERS:
        raise HTTPException(status_code=422, detail="account_type must be full, twitch or all")
    query = db.query(User)
    if account_type != "all":
        query = query.filter(User.account_type == account_type)
    users = sorted(query.all(), key=lambda u: (u.username is None, u.username or "", u.id))
    user_ids = [u.id for u in users]
    # Fetch all UserTag rows for these users in one query (avoid N+1)
    user_tags_rows = (
        db.query(UserTag, TagDefinition)
        .join(TagDefinition, TagDefinition.id == UserTag.tag_id)
        .filter(UserTag.user_id.in_(user_ids))
        .all()
    ) if user_ids else []
    tags_by_user: dict = {}
    for ut, td in user_tags_rows:
        tags_by_user.setdefault(ut.user_id, []).append(
            {"id": td.id, "key": td.key, "label": td.label}
        )
    card_counts = dict(
        db.query(Card.owner_id, func.count(Card.id))
        .filter(Card.owner_id.in_(user_ids)).group_by(Card.owner_id).all()
    ) if user_ids else {}
    return [
        {
            "id": u.id,
            "username": u.display_name,
            "account_type": u.account_type or "full",
            "tokens": u.tokens if u.tokens is not None else 0,
            "card_count": card_counts.get(u.id, 0),
            "created_at": u.created_at,
            "last_seen_at": u.last_seen_at,
            "twitch_linked": bool(u.twitch_user_id),
            "twitch_identity_shared": bool(u.twitch_account_id),
            "is_tester": bool(u.is_tester),
            "is_admin": bool(u.is_admin),
            "tags": tags_by_user.get(u.id, []),
        }
        for u in users
    ]


@router.delete("/admin/users/{user_id}", dependencies=[Depends(require_recent_reauth),
                                                       Depends(require_typed_confirmation("delete_user"))])
def delete_twitch_viewer(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    """Delete a Twitch viewer soft account and all its rows (issue #157). Website
    accounts cannot be deleted here."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.account_type != soft_accounts.SOFT:
        raise HTTPException(status_code=409, detail="Only Twitch viewer accounts can be deleted")
    soft_accounts.delete_soft_account(db, user)
    _audit(db, "twitch_soft_account_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"user_id={user_id} reason=admin")
    db.commit()
    return {"deleted": True, "user_id": user_id}


_CLAIM_DETAIL_RE = re.compile(r"user_id=(\d+) verified_user_id=(\d+) player_id=(\d+)")


@router.get("/admin/player-id-claims")
def list_superseded_player_id_claims(db=Depends(get_db), _: dict = Depends(require_admin)):
    """Self-reported player ids cleared because a verified Steam account took the same
    id (issue #150), newest first, read from the player_id_claim_superseded audit rows."""
    rows = (db.query(AuditLog).filter(AuditLog.action == "player_id_claim_superseded")
            .order_by(AuditLog.id.desc()).limit(500).all())
    parsed = []
    for row in rows:
        match = _CLAIM_DETAIL_RE.fullmatch(row.detail or "")
        if match:
            parsed.append((row, int(match.group(1)), int(match.group(2)), int(match.group(3))))
    ids = {uid for _, a, b, _ in parsed for uid in (a, b)}
    names = {u.id: u.display_name for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    return [{"timestamp": row.timestamp, "player_id": pid,
             "superseded_user_id": old, "superseded_username": names.get(old),
             "verified_user_id": new, "verified_username": names.get(new)}
            for row, old, new, pid in parsed]


@router.post("/users/{user_id}/toggle-tester", dependencies=[Depends(require_recent_reauth)])
def toggle_tester(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_tester = not bool(user.is_tester)
    _audit(db, "admin_toggle_tester", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"{user.username} is_tester={user.is_tester}")
    db.commit()
    return {"user_id": user.id, "username": user.username, "is_tester": user.is_tester}


@router.post("/users/{user_id}/toggle-admin", dependencies=[Depends(require_recent_reauth),
                                                            Depends(require_typed_confirmation("toggle_admin"))])
def toggle_admin(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=409, detail="Cannot change your own admin status")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_admin and user.is_demo:
        raise HTTPException(status_code=409, detail="Demo accounts can't be admins")
    if user.is_admin and db.query(User).filter_by(is_admin=True).count() <= 1:
        raise HTTPException(status_code=409, detail="Cannot demote the last remaining admin")
    user.is_admin = not bool(user.is_admin)
    # Privilege change: end the target's sessions so the next login gets a new
    # session ID and the limits of the new role (issue #117).
    sessions.delete_user_sessions(db, user.id)
    _audit(db, "admin_toggle_admin", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"{user.username} is_admin={user.is_admin}")
    db.commit()
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin}


@router.post("/users/{user_id}/force-logout")
def force_logout(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    sessions.delete_user_sessions(db, user.id)
    _audit(db, "admin_force_logout", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"target={user.username} user_id={user.id}")
    db.commit()
    return {"user_id": user.id, "username": user.username}


@router.post("/grant-tokens", dependencies=[Depends(require_recent_reauth),
                                            Depends(require_typed_confirmation("grant_tokens"))])
def grant_tokens(body: GrantTokensBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    target = db.get(User, body.target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount < 1:
        raise HTTPException(status_code=422, detail="Amount must be at least 1")
    target.tokens = (target.tokens or 0) + body.amount
    _audit(db, "admin_grant_tokens", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"target={target.display_name} amount={body.amount}")
    db.commit()
    return {"username": target.username, "tokens": target.tokens}


@router.post("/codes", dependencies=[Depends(require_recent_reauth)])
def create_code(body: CreateCodeBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="Code cannot be empty")
    if body.token_amount < 1:
        raise HTTPException(status_code=422, detail="Token amount must be at least 1")
    if body.expires_at is not None and body.expires_at <= int(time.time()):
        raise HTTPException(status_code=422, detail="Expiry must be in the future")
    if db.query(PromoCode).filter(PromoCode.code == code).first():
        raise HTTPException(status_code=409, detail="Code already exists")
    promo = PromoCode(code=code, token_amount=body.token_amount, created_by_id=admin["user_id"],
                      expires_at=body.expires_at, max_redemptions=body.max_redemptions)
    db.add(promo)
    _audit(db, "admin_code_create", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={code} tokens={body.token_amount} expires_at={body.expires_at} "
                  f"max_redemptions={body.max_redemptions}")
    db.commit()
    return {"id": promo.id, "code": promo.code, "token_amount": promo.token_amount,
            "expires_at": promo.expires_at, "max_redemptions": promo.max_redemptions}


@router.get("/codes")
def list_codes(db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT p.id, p.code, p.token_amount, p.expires_at, p.max_redemptions,
               COUNT(r.id) as redemptions
        FROM promo_codes p
        LEFT JOIN code_redemptions r ON r.code_id = p.id
        GROUP BY p.id, p.code, p.token_amount, p.expires_at, p.max_redemptions
        ORDER BY p.id
    """)).fetchall()
    return [{"id": r.id, "code": r.code, "token_amount": r.token_amount,
             "expires_at": r.expires_at, "max_redemptions": r.max_redemptions,
             "redemptions": r.redemptions} for r in rows]


@router.delete("/codes/{code_id}", dependencies=[Depends(require_recent_reauth)])
def delete_code(code_id: int, db=Depends(get_db), admin: dict = Depends(require_admin)):
    promo = db.get(PromoCode, code_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Code not found")
    _audit(db, "admin_code_delete", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={promo.code}")
    db.delete(promo)
    db.commit()
    return {"status": "ok"}


INVALID_CODE_DETAIL = "Invalid or expired code"


def _code_open(db, promo: PromoCode) -> bool:
    """A code can still be redeemed: not past its expiry and under its redemption cap."""
    if promo.expires_at is not None and promo.expires_at <= int(time.time()):
        return False
    if promo.max_redemptions is not None:
        used = db.query(func.count(CodeRedemption.id)).filter(
            CodeRedemption.code_id == promo.id).scalar() or 0
        if used >= promo.max_redemptions:
            return False
    return True


def redeem_code(body: RedeemCodeBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    code = body.code.strip().upper()
    promo = db.query(PromoCode).filter(PromoCode.code == code).first()
    # One answer for unknown, expired and used-up codes (issue #167), so codes
    # can't be probed. "Already redeemed" stays separate: it is the user's own state.
    if not promo or not _code_open(db, promo):
        raise HTTPException(status_code=404, detail=INVALID_CODE_DETAIL)
    already = db.query(CodeRedemption).filter(
        CodeRedemption.code_id == promo.id,
        CodeRedemption.user_id == user_id,
    ).first()
    if already:
        raise HTTPException(status_code=409, detail="Code already redeemed")
    user.tokens = (user.tokens or 0) + promo.token_amount
    db.add(CodeRedemption(code_id=promo.id, user_id=user_id, redeemed_at=int(time.time())))
    _audit(db, "token_redeem", actor_id=user_id, actor_username=user.username,
           detail=f"code={promo.code} granted={promo.token_amount}")
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent redeems of the same code by the same user both passed
        # the `already` check above — the unique(code_id, user_id) index is
        # the actual guard against double-granting.
        db.rollback()
        raise HTTPException(status_code=409, detail="Code already redeemed")
    return {"tokens": user.tokens, "granted": promo.token_amount}


@router.post("/redeem")
@limiter.limit(RATE_LIMIT_REDEEM, key_func=key_by_user_or_ip)
def redeem_code_route(request: Request, body: RedeemCodeBody, db=Depends(get_db),
                      current_user: dict = Depends(get_current_user)):
    return redeem_code(body, db, current_user)


class TokenGrantEventBody(BaseModel):
    amount:     int = Field(..., ge=1)
    start_time: int
    end_time:   int


@router.get("/admin/token-grant-events")
def list_token_grant_events(db=Depends(get_db), _: dict = Depends(require_admin)):
    events = db.query(TokenGrantEvent).order_by(TokenGrantEvent.start_time.desc()).all()
    claim_counts = {
        row[0]: row[1]
        for row in db.query(TokenGrantClaim.event_id, func.count(TokenGrantClaim.id))
                     .group_by(TokenGrantClaim.event_id).all()
    }
    return [
        {
            "id": ev.id, "amount": ev.amount,
            "start_time": ev.start_time, "end_time": ev.end_time,
            "created_at": ev.created_at, "claim_count": claim_counts.get(ev.id, 0),
        }
        for ev in events
    ]


@router.post("/admin/token-grant-events", dependencies=[Depends(require_recent_reauth)])
def create_token_grant_event(
    body: TokenGrantEventBody,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    if body.end_time <= body.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    ev = TokenGrantEvent(
        amount=body.amount,
        start_time=body.start_time,
        end_time=body.end_time,
        created_by=admin["user_id"],
        created_at=int(time.time()),
    )
    db.add(ev)
    db.flush()
    _audit(db, "admin_token_grant_event_created", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={ev.id} amount={ev.amount} start={ev.start_time} end={ev.end_time}")
    db.commit()
    return {"id": ev.id, "amount": ev.amount, "start_time": ev.start_time, "end_time": ev.end_time}


@router.delete("/admin/token-grant-events/{event_id}", dependencies=[Depends(require_recent_reauth)])
def delete_token_grant_event(
    event_id: int,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    ev = db.get(TokenGrantEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    _audit(db, "admin_token_grant_event_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={ev.id} amount={ev.amount}")
    db.delete(ev)
    db.commit()
    return {"ok": True}
