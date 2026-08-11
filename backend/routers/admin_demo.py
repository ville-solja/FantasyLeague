import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import clock
from auth import hash_password
from database import get_db
from deps import require_admin, _audit
from models import User
from routers.cards import draw_card
from weeks import auto_lock_weeks

router = APIRouter()


# ---------------------------------------------------------------------------
# Demo Mode — env-gated. Structurally invisible (404, not 403) whenever
# DEMO_MODE is not explicitly "true", regardless of caller identity, so its
# existence is never revealed in a production deployment.
# ---------------------------------------------------------------------------

class DemoClockBody(BaseModel):
    timestamp: int


class SeedDemoAccountsBody(BaseModel):
    count:             int | None = Field(None, ge=1, le=100)
    cards_per_account: int | None = Field(None, ge=0, le=50)


def _require_demo_mode():
    if os.getenv("DEMO_MODE", "").lower() != "true":
        raise HTTPException(status_code=404)


@router.get("/admin/demo/clock")
def get_demo_clock(db=Depends(get_db), _demo: None = Depends(_require_demo_mode),
                   _: dict = Depends(require_admin)):
    # Also called imperatively (not just via Depends) because this codebase's
    # test suite invokes endpoint functions directly, bypassing FastAPI's
    # dependency resolution — a bare Depends() default never fires there.
    _require_demo_mode()
    override = clock.get_override(db)
    return {"override_timestamp": override, "effective_now": clock.now(db)}


@router.post("/admin/demo/clock")
def set_demo_clock(body: DemoClockBody, db=Depends(get_db),
                   _demo: None = Depends(_require_demo_mode),
                   admin: dict = Depends(require_admin)):
    _require_demo_mode()
    clock.set_override(db, body.timestamp)
    auto_lock_weeks(db)  # synchronous — make the lock transition observable immediately
    _audit(db, "admin_demo_clock_set", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"timestamp={body.timestamp}")
    db.commit()
    return {"override_timestamp": body.timestamp, "effective_now": clock.now(db)}


@router.delete("/admin/demo/clock")
def clear_demo_clock(db=Depends(get_db), _demo: None = Depends(_require_demo_mode),
                     admin: dict = Depends(require_admin)):
    _require_demo_mode()
    clock.clear_override(db)
    _audit(db, "admin_demo_clock_cleared", actor_id=admin["user_id"],
           actor_username=admin["username"], detail="")
    db.commit()
    return {"override_timestamp": None}


@router.post("/admin/demo/seed-accounts")
def seed_demo_accounts(body: SeedDemoAccountsBody, db=Depends(get_db),
                       _demo: None = Depends(_require_demo_mode),
                       admin: dict = Depends(require_admin)):
    """Create disposable demo1, demo2, ... accounts pre-loaded with random cards.

    Reuses draw_card from routers/cards.py directly (a plain Python function
    call, not an HTTP round-trip) — it already handles rarity rolls, player
    selection, modifier assignment, and roster auto-activation up to
    ROSTER_LIMIT. Granting cards_per_account tokens up front lets the loop
    call the real draw path unmodified.

    _require_demo_mode is declared as a dependency ahead of require_admin so a
    real HTTP request resolves it first: a non-admin caller gets 404 (mode
    disabled), not 403, when DEMO_MODE is off — the endpoint's existence stays
    hidden. It is also called imperatively below because this codebase's test
    suite invokes endpoint functions directly, bypassing FastAPI's dependency
    resolution entirely; a bare Depends() default would never fire there.
    """
    _require_demo_mode()
    count = body.count or 5
    cards_per_account = body.cards_per_account if body.cards_per_account is not None else 3
    existing = {u.username for u in db.query(User).filter(User.username.like("demo%")).all()}
    created = []
    n = 1
    while len(created) < count:
        username = f"demo{n}"
        n += 1
        if username in existing:
            continue
        password = secrets.token_urlsafe(9)
        user = User(username=username, email=f"{username}@demo.local",
                    password_hash=hash_password(password),
                    tokens=cards_per_account)
        db.add(user)
        db.flush()
        fake_current_user = {"user_id": user.id, "username": username, "is_admin": False}
        for _ in range(cards_per_account):
            try:
                draw_card(db=db, current_user=fake_current_user)
            except HTTPException:
                # No players available to draw (empty pool) or out of tokens —
                # the account is still created; it just ends up with fewer cards.
                break
        created.append({"username": username, "password": password})
    _audit(db, "admin_demo_accounts_seeded", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"created={len(created)}")
    db.commit()
    return {"accounts": created}
