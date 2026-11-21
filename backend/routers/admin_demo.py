import logging
import os
import secrets
import time

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import clock
import demo_snapshots
import scenarios
from auth import check_reserved, hash_password, username_taken
from database import get_db
from deps import require_admin, require_recent_reauth, require_typed_confirmation, _audit
from models import User
from routers.cards import draw_card
from weeks import auto_lock_weeks, due_substitutions, generate_weekly_summaries

router = APIRouter()
logger = logging.getLogger(__name__)


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


class ScenarioBody(BaseModel):
    name: Literal["pre-season", "mid-season", "season-end"]


class SnapshotBody(BaseModel):
    name: str = Field(..., pattern=r"^[A-Za-z0-9-]{1,40}$")


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
    due_substitutions(db)  # synchronous, before summaries — same order as the week maintenance loop
    generate_weekly_summaries(db)  # synchronous, same reason — see auto_lock_weeks above
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
    created = []
    n = 1
    while len(created) < count:
        username = f"demo{n}"
        n += 1
        if username_taken(db, username):
            continue
        check_reserved(username)
        password = secrets.token_urlsafe(9)
        user = User(username=username, email=f"{username}@demo.local",
                    password_hash=hash_password(password),
                    tokens=cards_per_account, is_demo=True)
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


@router.post("/admin/demo/scenario",
             dependencies=[Depends(_require_demo_mode), Depends(require_recent_reauth),
                           Depends(require_typed_confirmation("demo_scenario"))])
def load_demo_scenario(body: ScenarioBody, db=Depends(get_db),
                       admin: dict = Depends(require_admin)):
    """Replace all game data with a named, deterministic season and set the demo clock
    (issue #145). Keeps the caller's account and sessions. Needs a recent re-auth and
    the typed phrase LOAD SCENARIO; 409 without a valid DEMO_ACCOUNT_PASSWORD. The
    response names the accounts and carries scenario-admin's one-time random password
    (`admin_password`), never DEMO_ACCOUNT_PASSWORD."""
    _require_demo_mode()
    return scenarios.load(db, body.name, admin["user_id"])


# Issue #147: named database snapshots. Save and list need admin only; restore
# replaces every row, so it needs a recent re-auth and the typed RESTORE SNAPSHOT.

@router.get("/admin/demo/snapshots")
def list_demo_snapshots(_demo: None = Depends(_require_demo_mode),
                        _: dict = Depends(require_admin)):
    _require_demo_mode()
    return {"snapshots": demo_snapshots.list_all()}


@router.post("/admin/demo/snapshots")
def save_demo_snapshot(body: SnapshotBody, _demo: None = Depends(_require_demo_mode),
                       db=Depends(get_db), admin: dict = Depends(require_admin)):
    _require_demo_mode()
    try:
        demo_snapshots.path_for(body.name)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid snapshot name")
    try:
        info = demo_snapshots.save(body.name)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Demo snapshot save failed for %s", body.name)
        raise HTTPException(status_code=500, detail=f"Saving the snapshot failed ({type(e).__name__})")
    _audit(db, "demo_snapshot_saved", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"name={body.name}")
    db.commit()
    return info


@router.post("/admin/demo/snapshots/{name:path}/restore",
             dependencies=[Depends(_require_demo_mode), Depends(require_recent_reauth),
                           Depends(require_typed_confirmation("demo_snapshot_restore"))])
def restore_demo_snapshot(name: str, db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Replace all data with a saved snapshot. `{name:path}` lets names with "/" reach
    this handler, so they get 422 instead of a routing 404. The caller stays logged in
    and every other session ends; 409 when the snapshot lacks the caller as an admin."""
    _require_demo_mode()
    try:
        demo_snapshots.path_for(name)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid snapshot name")
    db.close()  # return this request's connection before the file is replaced
    try:
        return demo_snapshots.restore(name, admin["user_id"], admin["username"])
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Demo snapshot restore failed for %s", name)
        raise HTTPException(status_code=500, detail=f"Restoring the snapshot failed ({type(e).__name__})")
