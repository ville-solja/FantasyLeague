import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, text

from database import get_db
from deps import get_current_user, require_admin, _audit
from models import PromoCode, CodeRedemption, User, TokenGrantEvent, TokenGrantClaim, TagDefinition, UserTag

router = APIRouter()


class GrantTokensBody(BaseModel):
    target_user_id: int
    amount: int


class CreateCodeBody(BaseModel):
    code:         str = Field(min_length=1, max_length=64)
    token_amount: int


class RedeemCodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=64)


@router.get("/users")
def list_users(db=Depends(get_db), _: dict = Depends(require_admin)):
    users = db.query(User).order_by(User.username).all()
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
    return [
        {
            "id": u.id,
            "username": u.username,
            "tokens": u.tokens if u.tokens is not None else 0,
            "is_tester": bool(u.is_tester),
            "is_admin": bool(u.is_admin),
            "tags": tags_by_user.get(u.id, []),
        }
        for u in users
    ]


@router.post("/users/{user_id}/toggle-tester")
def toggle_tester(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_tester = not bool(user.is_tester)
    _audit(db, "admin_toggle_tester", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"{user.username} is_tester={user.is_tester}")
    db.commit()
    return {"user_id": user.id, "username": user.username, "is_tester": user.is_tester}


@router.post("/users/{user_id}/toggle-admin")
def toggle_admin(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=409, detail="Cannot change your own admin status")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_admin and db.query(User).filter_by(is_admin=True).count() <= 1:
        raise HTTPException(status_code=409, detail="Cannot demote the last remaining admin")
    user.is_admin = not bool(user.is_admin)
    _audit(db, "admin_toggle_admin", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"{user.username} is_admin={user.is_admin}")
    db.commit()
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin}


@router.post("/grant-tokens")
def grant_tokens(body: GrantTokensBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    target = db.get(User, body.target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount < 1:
        raise HTTPException(status_code=422, detail="Amount must be at least 1")
    target.tokens = (target.tokens or 0) + body.amount
    _audit(db, "admin_grant_tokens", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"target={target.username} amount={body.amount}")
    db.commit()
    return {"username": target.username, "tokens": target.tokens}


@router.post("/codes")
def create_code(body: CreateCodeBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="Code cannot be empty")
    if body.token_amount < 1:
        raise HTTPException(status_code=422, detail="Token amount must be at least 1")
    if db.query(PromoCode).filter(PromoCode.code == code).first():
        raise HTTPException(status_code=409, detail="Code already exists")
    promo = PromoCode(code=code, token_amount=body.token_amount, created_by_id=admin["user_id"])
    db.add(promo)
    _audit(db, "admin_code_create", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={code} tokens={body.token_amount}")
    db.commit()
    return {"id": promo.id, "code": promo.code, "token_amount": promo.token_amount}


@router.get("/codes")
def list_codes(db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT p.id, p.code, p.token_amount, COUNT(r.id) as redemptions
        FROM promo_codes p
        LEFT JOIN code_redemptions r ON r.code_id = p.id
        GROUP BY p.id, p.code, p.token_amount
        ORDER BY p.id
    """)).fetchall()
    return [{"id": r.id, "code": r.code, "token_amount": r.token_amount,
             "redemptions": r.redemptions} for r in rows]


@router.delete("/codes/{code_id}")
def delete_code(code_id: int, db=Depends(get_db), admin: dict = Depends(require_admin)):
    promo = db.get(PromoCode, code_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Code not found")
    _audit(db, "admin_code_delete", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={promo.code}")
    db.delete(promo)
    db.commit()
    return {"status": "ok"}


@router.post("/redeem")
def redeem_code(body: RedeemCodeBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    code = body.code.strip().upper()
    promo = db.query(PromoCode).filter(PromoCode.code == code).first()
    if not promo:
        raise HTTPException(status_code=404, detail="Invalid code")
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
    db.commit()
    return {"tokens": user.tokens, "granted": promo.token_amount}


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


@router.post("/admin/token-grant-events")
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


@router.delete("/admin/token-grant-events/{event_id}")
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
