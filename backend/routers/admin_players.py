from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, text

from database import get_db
from deps import require_admin, _audit
from models import Card, Player, User
from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json

router = APIRouter()


# ---------------------------------------------------------------------------
# Player Pool Management
# ---------------------------------------------------------------------------

class AddPlayerBody(BaseModel):
    player_id: int


class BulkAddPlayersBody(BaseModel):
    player_ids: str = Field(..., min_length=1, max_length=2000)  # CSV string


class RemovePlayersBody(BaseModel):
    player_ids: List[int]


@router.get("/admin/players")
def list_players(db=Depends(get_db), _=Depends(require_admin)):
    # Same name/avatar/team identity as GET /players (public Players tab) — team
    # is each player's most recent match's team, not a static assignment.
    rows = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url, p.is_active,
               t.id as team_id, t.name as team_name
        FROM players p
        LEFT JOIN (
            SELECT s2.player_id, s2.team_id
            FROM player_match_stats s2
            INNER JOIN (
                SELECT player_id, MAX(match_id) as max_match
                FROM player_match_stats
                GROUP BY player_id
            ) mx ON mx.player_id = s2.player_id AND mx.max_match = s2.match_id
        ) latest ON latest.player_id = p.id
        LEFT JOIN teams t ON t.id = latest.team_id
        ORDER BY p.name
    """)).fetchall()
    card_counts = {
        r[0]: r[1] for r in
        db.query(Card.player_id, func.count(Card.id))
          .filter(Card.is_active == True)
          .group_by(Card.player_id).all()
    }
    return [
        {
            "id": r.id, "name": r.name, "avatar_url": r.avatar_url,
            "team_id": r.team_id, "team_name": r.team_name,
            "is_active": r.is_active,
            "active_card_count": card_counts.get(r.id, 0),
        }
        for r in rows
    ]


@router.post("/admin/players")
def add_player(body: AddPlayerBody, db=Depends(get_db), admin=Depends(require_admin)):
    existing = db.get(Player, body.player_id)
    if existing and existing.is_active:
        raise HTTPException(status_code=409, detail="Player already exists in pool")
    result = opendota_get_json(f"{OPEN_DOTA_URL}/players/{body.player_id}",
                               label=f"player {body.player_id}")
    if not result or not result.get("profile"):
        raise HTTPException(status_code=422, detail="Player not found on OpenDota")
    data = result["profile"]
    if existing:
        existing.is_active = True
        existing.name = data.get("personaname", str(body.player_id))
        existing.avatar_url = data.get("avatarfull", "")
        p = existing
    else:
        p = Player(
            id=body.player_id,
            name=data.get("personaname", str(body.player_id)),
            avatar_url=data.get("avatarfull", ""),
            is_active=True,
        )
        db.add(p)
    _audit(db, "admin_player_added", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"player_id={body.player_id}")
    db.commit()
    return {"id": p.id, "name": p.name}


@router.post("/admin/players/bulk")
def bulk_add_players(body: BulkAddPlayersBody, db=Depends(get_db),
                     admin=Depends(require_admin)):
    raw_ids = [s.strip() for s in body.player_ids.split(",") if s.strip()]
    added, skipped = [], []
    for raw in raw_ids:
        try:
            pid = int(raw)
        except ValueError:
            skipped.append({"id": raw, "reason": "not an integer"})
            continue
        if db.get(Player, pid):
            skipped.append({"id": pid, "reason": "already exists"})
            continue
        result = opendota_get_json(f"{OPEN_DOTA_URL}/players/{pid}", label=f"player {pid}")
        if not result or not result.get("profile"):
            skipped.append({"id": pid, "reason": "not found on OpenDota"})
            continue
        data = result["profile"]
        db.add(Player(
            id=pid,
            name=data.get("personaname", str(pid)),
            avatar_url=data.get("avatarfull", ""),
            is_active=True,
        ))
        added.append(pid)
    if added:
        _audit(db, "admin_player_bulk_added", actor_id=admin["user_id"],
               actor_username=admin["username"], detail=f"added={len(added)}")
    db.commit()
    return {"added": len(added), "skipped": skipped}


@router.post("/admin/players/remove")
def remove_players(body: RemovePlayersBody, db=Depends(get_db),
                   admin=Depends(require_admin)):
    for pid in body.player_ids:
        player = db.get(Player, pid)
        if not player or not player.is_active:
            continue
        player.is_active = False
        cards = db.query(Card).filter(Card.player_id == pid).all()
        refund_totals: dict = {}
        for card in cards:
            card.is_active = False
            refund_totals[card.owner_id] = refund_totals.get(card.owner_id, 0) + 1
        for user_id, token_count in refund_totals.items():
            user = db.get(User, user_id)
            if user:
                user.tokens = (user.tokens or 0) + token_count
                _audit(db, "admin_player_refund_issued", actor_id=admin["user_id"],
                       actor_username=admin["username"],
                       detail=f"player_id={pid} user_id={user_id} tokens={token_count}")
        _audit(db, "admin_player_removed", actor_id=admin["user_id"],
               actor_username=admin["username"], detail=f"player_id={pid}")
    db.commit()
    return {"ok": True}
