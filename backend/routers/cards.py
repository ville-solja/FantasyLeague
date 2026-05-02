import io
import os
import random
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import text

from card_utils import (
    _SCORED_STAT_COLS, _load_weights, _compute_card_points,
    _assign_modifiers, _card_modifiers_map, _card_modifiers_dict_for_image, _format_modifiers,
)
from database import get_db
from deps import get_current_user, _audit
from models import Card, User, Week, Weight
from weeks import get_next_editable_week

router = APIRouter()

ROSTER_LIMIT = int(os.getenv("ROSTER_LIMIT", "5"))

_LATEST_TEAM_SUBQUERY = """
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
"""


def _build_roster_response(db, user_id: int, week_id: int | None) -> dict:
    """Compute roster data for a user, scoped to the given week (or next editable week)."""
    week = db.get(Week, week_id) if week_id is not None else get_next_editable_week(db)
    now = int(time.time())

    def _week_stat_case(col):
        return (
            f"COALESCE(SUM(CASE WHEN (m.week_override_id = :week_id OR "
            f"(m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we)) "
            f"THEN s.{col} ELSE 0 END), 0) as {col}"
        )
    stat_cols = ",\n                   ".join(_week_stat_case(col) for col in _SCORED_STAT_COLS)

    week_match_count = (
        "COUNT(DISTINCT CASE WHEN (m.week_override_id = :week_id OR "
        "(m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we)) "
        "THEN m.match_id END) as match_count"
    )

    if week and week.is_locked:
        results = db.execute(text(f"""
            SELECT c.id, c.card_type, 1 as is_active,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.name as team_name, t.logo_url as team_logo_url,
                   {week_match_count},
                   {stat_cols}
            FROM weekly_roster_entries wre
            JOIN cards c ON c.id = wre.card_id
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE wre.week_id = :week_id AND wre.user_id = :user_id
            GROUP BY c.id, c.card_type, p.id, p.name, p.avatar_url, t.name, t.logo_url
        """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time,
               "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active, bench = cards, []
    else:
        ws = week.start_time if week else 0
        we = week.end_time if week else now
        results = db.execute(text(f"""
            SELECT c.id, c.card_type, c.is_active,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.name as team_name, t.logo_url as team_logo_url,
                   {week_match_count},
                   {stat_cols}
            FROM cards c
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE c.owner_id = :user_id
            GROUP BY c.id, c.card_type, c.is_active, p.id, p.name, p.avatar_url, t.name, t.logo_url
            ORDER BY c.is_active DESC
        """), {"ws": ws, "we": we, "week_id": week.id if week else -1, "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active = [c for c in cards if c["is_active"]]
        bench  = [c for c in cards if not c["is_active"]]

    card_ids = [c["id"] for c in cards]
    modifiers_map = _card_modifiers_map(db, card_ids)
    weights, rarity = _load_weights(db)

    for c in cards:
        mods = modifiers_map.get(c["id"], {})
        c["modifiers"] = _format_modifiers(mods)
        if c.get("match_count", 1) == 0:
            c["total_points"] = 0.0
            continue
        stat_sums = {stat: c.get(stat, 0) or 0 for stat in _SCORED_STAT_COLS}
        c["total_points"] = _compute_card_points(stat_sums, c["card_type"], weights, rarity, mods)

    active.sort(key=lambda c: c["total_points"], reverse=True)
    bench.sort(key=lambda c: c["total_points"], reverse=True)

    user = db.get(User, user_id)
    tokens = user.tokens if user and user.tokens is not None else 0

    season_pts_rows = db.execute(text("""
        SELECT c.id as card_id, c.card_type,
               COALESCE(SUM(s.deaths), 0)                    as deaths,
               COALESCE(SUM(s.kills), 0)                     as kills,
               COALESCE(SUM(s.last_hits), 0)                 as last_hits,
               COALESCE(SUM(s.denies), 0)                    as denies,
               COALESCE(SUM(s.gold_per_min), 0)              as gold_per_min,
               COALESCE(SUM(s.obs_placed), 0)                as obs_placed,
               COALESCE(SUM(s.towers_killed), 0)             as towers_killed,
               COALESCE(SUM(s.roshan_kills), 0)              as roshan_kills,
               COALESCE(SUM(s.teamfight_participation), 0)   as teamfight_participation,
               COALESCE(SUM(s.camps_stacked), 0)             as camps_stacked,
               COALESCE(SUM(s.rune_pickups), 0)              as rune_pickups,
               COALESCE(SUM(s.firstblood_claimed), 0)        as firstblood_claimed,
               COALESCE(SUM(s.stuns), 0)                     as stuns
        FROM weekly_roster_entries wre
        JOIN weeks wk ON wk.id = wre.week_id
        JOIN cards c ON c.id = wre.card_id
        JOIN player_match_stats s ON s.player_id = c.player_id
        JOIN matches m ON m.match_id = s.match_id
        WHERE wre.user_id = :user_id
          AND wk.is_locked = 1
          AND (m.week_override_id = wk.id OR (m.week_override_id IS NULL AND m.start_time BETWEEN wk.start_time AND wk.end_time))
        GROUP BY c.id, c.card_type
    """), {"user_id": user_id}).fetchall()

    from card_utils import _stat_sums_from_row
    season_card_ids = [r.card_id for r in season_pts_rows]
    season_mods = _card_modifiers_map(db, season_card_ids)
    season_points = sum(
        _compute_card_points(_stat_sums_from_row(row), row.card_type, weights, rarity,
                             season_mods.get(row.card_id, {}))
        for row in season_pts_rows
    )

    return {
        "active": active, "bench": bench,
        "combined_value": sum(c["total_points"] for c in active),
        "tokens": tokens,
        "season_points": season_points,
        "week": {"id": week.id, "label": week.label, "is_locked": week.is_locked,
                 "start_time": week.start_time, "end_time": week.end_time} if week else None,
    }


@router.get("/deck")
def get_deck(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT c.card_type, COUNT(*) as count
        FROM cards c
        WHERE c.owner_id IS NULL
        GROUP BY c.card_type
    """)).fetchall()
    return {r.card_type: r.count for r in results}


@router.post("/draw")
def draw_card(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (user.tokens or 0) <= 0:
        raise HTTPException(status_code=409, detail="Not enough tokens")

    unclaimed = db.execute(text("""
        SELECT c.id, c.card_type, c.player_id, p.name as player_name, p.avatar_url,
               t.name as team_name, t.id as team_id, t.logo_url as team_logo_url
        FROM cards c
        JOIN players p ON p.id = c.player_id
""" + _LATEST_TEAM_SUBQUERY + """
        WHERE c.owner_id IS NULL
    """)).fetchall()

    if not unclaimed:
        raise HTTPException(status_code=404, detail="No cards left in deck")

    owned_player_ids = {r[0] for r in db.execute(
        text("SELECT c.player_id FROM cards c WHERE c.owner_id = :uid"), {"uid": user_id}
    ).fetchall()}
    available = [c for c in unclaimed if c.player_id not in owned_player_ids]
    if not available:
        available = list(unclaimed)

    chosen = random.choice(available)
    card = db.get(Card, chosen.id)
    card.owner_id = user_id
    user.tokens = (user.tokens or 0) - 1

    active_count = db.query(Card).filter(
        Card.owner_id == user_id, Card.is_active == True
    ).count()
    is_active = active_count < ROSTER_LIMIT
    card.is_active = is_active

    weights = {w.key: w.value for w in db.query(Weight).all()}
    _assign_modifiers(db, card, weights)

    _audit(db, "token_draw", actor_id=user_id, actor_username=user.username,
           detail=f"card_id={chosen.id} player={chosen.player_name} rarity={chosen.card_type}")
    db.commit()
    tokens_remaining = user.tokens

    mods = _card_modifiers_map(db, [card.id]).get(card.id, {})
    return {
        "id": chosen.id,
        "card_type": chosen.card_type,
        "player_id": chosen.player_id,
        "player_name": chosen.player_name,
        "avatar_url": chosen.avatar_url,
        "team_name": chosen.team_name,
        "team_logo_url": chosen.team_logo_url,
        "is_active": is_active,
        "tokens": tokens_remaining,
        "modifiers": _format_modifiers(mods),
    }


@router.get("/weeks")
def get_weeks(db=Depends(get_db)):
    weeks = db.query(Week).order_by(Week.start_time).all()
    return [{"id": w.id, "label": w.label, "start_time": w.start_time,
             "end_time": w.end_time, "is_locked": w.is_locked} for w in weeks]


@router.get("/cards/{card_id}")
def get_card(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    from models import Player
    user_id = current_user["user_id"]
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")
    player = db.get(Player, card.player_id)
    team_row = db.execute(text("""
        SELECT t.name, t.logo_url
        FROM player_match_stats s
        JOIN teams t ON t.id = s.team_id
        WHERE s.player_id = :pid
        ORDER BY s.match_id DESC LIMIT 1
    """), {"pid": card.player_id}).first()
    mods = _card_modifiers_map(db, [card_id]).get(card_id, {})
    return {
        "id": card.id,
        "card_type": card.card_type,
        "player_name": player.name if player else None,
        "avatar_url": player.avatar_url if player else None,
        "team_name": team_row.name if team_row else None,
        "team_logo_url": team_row.logo_url if team_row else None,
        "modifiers": _format_modifiers(mods),
    }


@router.get("/cards/{card_id}/image")
def get_card_image(card_id: int, db=Depends(get_db)):
    from image import generate_card_image, PIL_AVAILABLE
    if not PIL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Image generation unavailable (Pillow not installed)")
    result = db.execute(text("""
        SELECT c.card_type, p.name as player_name, p.avatar_url,
               t.name as team_name, t.logo_url as team_logo_url
        FROM cards c
        JOIN players p ON p.id = c.player_id
""" + _LATEST_TEAM_SUBQUERY + """
        WHERE c.id = :card_id
    """), {"card_id": card_id}).first()
    if not result:
        raise HTTPException(status_code=404, detail="Card not found")
    mods: dict = _card_modifiers_dict_for_image(db, card_id)
    img = generate_card_image(
        card_type=result.card_type,
        player_name=result.player_name,
        avatar_url=result.avatar_url,
        team_name=result.team_name,
        team_logo_url=result.team_logo_url,
        card_modifiers=mods,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=5)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@router.post("/roster/{card_id}/reroll")
def reroll_modifiers(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (user.tokens or 0) <= 0:
        raise HTTPException(status_code=409, detail="Not enough tokens")
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")

    db.execute(text("DELETE FROM card_modifiers WHERE card_id = :cid"), {"cid": card_id})
    db.flush()

    weights = {w.key: w.value for w in db.query(Weight).all()}
    _assign_modifiers(db, card, weights)

    user.tokens = (user.tokens or 0) - 1
    _audit(db, "reroll_modifiers", actor_id=user_id, actor_username=user.username,
           detail=f"card_id={card_id} rarity={card.card_type}")
    db.commit()
    tokens_remaining = user.tokens

    mods = _card_modifiers_map(db, [card_id]).get(card_id, {})
    return {
        "modifiers": _format_modifiers(mods),
        "tokens": tokens_remaining,
    }


@router.post("/roster/{card_id}/activate")
def activate_card(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")
    if card.is_active:
        raise HTTPException(status_code=409, detail="Card already active")

    active_count = db.query(Card).filter(
        Card.owner_id == user_id, Card.is_active == True
    ).count()
    if active_count >= ROSTER_LIMIT:
        raise HTTPException(status_code=409, detail=f"Roster full ({ROSTER_LIMIT} cards max)")

    duplicate = db.query(Card).filter(
        Card.owner_id == user_id,
        Card.player_id == card.player_id,
        Card.is_active == True,
        Card.id != card_id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="A card for this player is already active")

    card.is_active = True
    db.commit()
    return {"status": "ok", "card_id": card_id}


@router.post("/roster/{card_id}/deactivate")
def deactivate_card(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")
    card.is_active = False
    db.commit()
    return {"status": "ok", "card_id": card_id}


@router.get("/roster/{user_id}")
def get_roster(user_id: int, week_id: int = None, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    if user_id != current_user["user_id"] and not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Cannot view another user's roster")
    return _build_roster_response(db, user_id, week_id)
