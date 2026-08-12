import io
import os
import random
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text

from card_draw import _roll_rarity, _pick_player, _pick_player_from_team
from card_utils import (
    _SCORED_STAT_COLS, _load_weights, _compute_card_points, _mvp_bonus_delta,
    _assign_modifiers, _card_modifiers_map, _card_modifiers_dict_for_image, _format_modifiers,
)
from database import get_db
from deps import get_current_user, _audit
from models import Card, Player, PlayerMatchStats, Team, User, Week, Weight
from weeks import get_next_editable_week

router = APIRouter()

ROSTER_LIMIT = int(os.getenv("ROSTER_LIMIT", "5"))


class ReorderRequest(BaseModel):
    card_ids: list[int]           # ordered list; positions assigned by index
    slot_indexes: list[int] | None = None  # explicit positions; overrides sequential when provided


class SwapRequest(BaseModel):
    bench_card_id: int   # card moving from bench → active
    active_card_id: int  # card moving from active → bench
    slot_index: int      # the active slot the bench card should occupy


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


def _mvp_bonus_map(mvp_rows, weights: dict) -> dict[int, float]:
    """{card_id: summed _mvp_bonus_delta()} across a set of raw, un-aggregated
    is_mvp=1 match rows (one row per MVP match, not per card)."""
    result: dict[int, float] = {}
    for row in mvp_rows:
        result[row.card_id] = result.get(row.card_id, 0.0) + _mvp_bonus_delta(row, weights)
    return result


def _build_roster_response(db, user_id: int, week_id: int | None) -> dict:
    """Compute roster data for a user, scoped to the given week (or next editable week)."""
    week = db.get(Week, week_id) if week_id is not None else get_next_editable_week(db)
    now = int(time.time())
    weights, rarity = _load_weights(db)
    mvp_stat_cols = ", ".join(f"s.{col}" for col in _SCORED_STAT_COLS)

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
            SELECT c.id, c.card_type, 1 as is_active, c.slot_index,
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
            GROUP BY c.id, c.card_type, c.slot_index, p.id, p.name, p.avatar_url, t.name, t.logo_url
        """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time,
               "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active, bench = cards, []
        mvp_rows = db.execute(text(f"""
            SELECT c.id as card_id, {mvp_stat_cols}
            FROM weekly_roster_entries wre
            JOIN cards c ON c.id = wre.card_id
            JOIN player_match_stats s ON s.player_id = c.player_id
            JOIN matches m ON m.match_id = s.match_id
            WHERE wre.week_id = :week_id AND wre.user_id = :user_id AND s.is_mvp = 1
              AND (m.week_override_id = :week_id OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
        """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time,
               "user_id": user_id}).fetchall()
    else:
        ws = week.start_time if week else 0
        we = week.end_time if week else now
        results = db.execute(text(f"""
            SELECT c.id, c.card_type, c.is_active, c.slot_index,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.name as team_name, t.logo_url as team_logo_url,
                   {week_match_count},
                   {stat_cols}
            FROM cards c
            JOIN players p ON p.id = c.player_id
            LEFT JOIN player_match_stats s ON s.player_id = c.player_id
            LEFT JOIN matches m ON m.match_id = s.match_id
            {_LATEST_TEAM_SUBQUERY}
            WHERE c.owner_id = :user_id AND p.is_active = 1
            GROUP BY c.id, c.card_type, c.is_active, c.slot_index, p.id, p.name, p.avatar_url, t.name, t.logo_url
            ORDER BY c.is_active DESC
        """), {"ws": ws, "we": we, "week_id": week.id if week else -1, "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        active = [c for c in cards if c["is_active"]]
        bench  = [c for c in cards if not c["is_active"]]
        mvp_rows = db.execute(text(f"""
            SELECT c.id as card_id, {mvp_stat_cols}
            FROM cards c
            JOIN players p ON p.id = c.player_id
            JOIN player_match_stats s ON s.player_id = c.player_id
            JOIN matches m ON m.match_id = s.match_id
            WHERE c.owner_id = :user_id AND p.is_active = 1 AND s.is_mvp = 1
              AND (m.week_override_id = :week_id OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
        """), {"ws": ws, "we": we, "week_id": week.id if week else -1, "user_id": user_id}).fetchall()

    card_ids = [c["id"] for c in cards]
    modifiers_map = _card_modifiers_map(db, card_ids)
    mvp_bonus_map = _mvp_bonus_map(mvp_rows, weights)

    for c in cards:
        mods = modifiers_map.get(c["id"], {})
        c["modifiers"] = _format_modifiers(mods)
        if c.get("match_count", 1) == 0:
            c["total_points"] = 0.0
            continue
        stat_sums = {stat: c.get(stat, 0) or 0 for stat in _SCORED_STAT_COLS}
        c["total_points"] = _compute_card_points(stat_sums, c["card_type"], weights, rarity, mods,
                                                   mvp_bonus_map.get(c["id"], 0.0))

    active.sort(key=lambda c: (c.get("slot_index") is None, c.get("slot_index") or 0, c["id"]))
    bench.sort(key=lambda c: (c.get("slot_index") is None, c.get("slot_index") or 0, c["id"]))

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

    season_mvp_rows = db.execute(text(f"""
        SELECT c.id as card_id, {mvp_stat_cols}
        FROM weekly_roster_entries wre
        JOIN weeks wk ON wk.id = wre.week_id
        JOIN cards c ON c.id = wre.card_id
        JOIN player_match_stats s ON s.player_id = c.player_id
        JOIN matches m ON m.match_id = s.match_id
        WHERE wre.user_id = :user_id
          AND wk.is_locked = 1
          AND s.is_mvp = 1
          AND (m.week_override_id = wk.id OR (m.week_override_id IS NULL AND m.start_time BETWEEN wk.start_time AND wk.end_time))
    """), {"user_id": user_id}).fetchall()
    season_mvp_bonus_map = _mvp_bonus_map(season_mvp_rows, weights)

    from card_utils import _stat_sums_from_row
    season_card_ids = [r.card_id for r in season_pts_rows]
    season_mods = _card_modifiers_map(db, season_card_ids)
    season_points = sum(
        _compute_card_points(_stat_sums_from_row(row), row.card_type, weights, rarity,
                             season_mods.get(row.card_id, {}),
                             season_mvp_bonus_map.get(row.card_id, 0.0))
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
def get_deck(request: Request, db=Depends(get_db)):
    rarities = ["common", "rare", "epic", "legendary"]
    all_players = db.query(Player).all()
    all_combos = {(p.id, r) for p in all_players for r in rarities}

    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if user_id:
        owned_combos = {
            (c.player_id, c.card_type)
            for c in db.query(Card).filter_by(owner_id=user_id).all()
        }
        available = all_combos - owned_combos
    else:
        available = all_combos

    return {r: sum(1 for _, rr in available if rr == r) for r in rarities}


@router.post("/draw")
def draw_card(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (user.tokens or 0) <= 0:
        raise HTTPException(status_code=409, detail="Not enough tokens")

    weights = {w.key: w.value for w in db.query(Weight).all()}
    rarity = _roll_rarity(weights)
    player = _pick_player(db, user_id, rarity)
    if player is None:
        raise HTTPException(status_code=409, detail="No players available to draw")

    card = Card(
        card_type=rarity,
        player_id=player.id,
        owner_id=user_id,
        league_id=None,
        is_active=False,
        generation=1,
    )
    db.add(card)
    db.flush()

    active_count = db.query(Card).filter(
        Card.owner_id == user_id, Card.is_active == True
    ).count()
    is_active = active_count < ROSTER_LIMIT
    card.is_active = is_active

    _assign_modifiers(db, card, weights)

    team_row = db.execute(text("""
        SELECT t.name, t.logo_url
        FROM player_match_stats s
        JOIN teams t ON t.id = s.team_id
        WHERE s.player_id = :pid
        ORDER BY s.match_id DESC LIMIT 1
    """), {"pid": player.id}).first()

    user.tokens = (user.tokens or 0) - 1
    _audit(db, "token_draw", actor_id=user_id, actor_username=user.username,
           detail=f"card_id={card.id} player={player.name} rarity={rarity}")
    db.commit()
    tokens_remaining = user.tokens

    mods = _card_modifiers_map(db, [card.id]).get(card.id, {})
    return {
        "id": card.id,
        "card_type": card.card_type,
        "player_id": player.id,
        "player_name": player.name,
        "avatar_url": player.avatar_url,
        "team_name": team_row.name if team_row else None,
        "team_logo_url": team_row.logo_url if team_row else None,
        "is_active": is_active,
        "tokens": tokens_remaining,
        "modifiers": _format_modifiers(mods),
    }


@router.get("/deck/booster")
def get_booster_deck(request: Request, db=Depends(get_db)):
    """Return per-team drawable card counts for the requesting user."""
    user_id = request.session.get("user_id") if hasattr(request, "session") else None

    teams = db.query(Team).all()

    # Pre-fetch all (team_id, player_id) pairs in a single query
    pms_rows = (
        db.query(PlayerMatchStats.team_id, PlayerMatchStats.player_id)
          .distinct()
          .all()
    )
    # Build a dict: team_id -> set of player_ids
    team_players: dict[int, set[int]] = {}
    for team_id, player_id in pms_rows:
        team_players.setdefault(team_id, set()).add(player_id)

    # Pre-fetch all player_ids that have players in any team with stats
    all_player_ids = {pid for pids in team_players.values() for pid in pids}

    # Pre-fetch owned player IDs for the authenticated user in a single query
    owned_player_ids: set[int] = set()
    if user_id and all_player_ids:
        owned_player_ids = {
            r[0] for r in
            db.query(Card.player_id).filter(
                Card.owner_id == user_id,
                Card.player_id.in_(all_player_ids),
            ).all()
        }

    result = []
    for team in teams:
        player_ids = team_players.get(team.id)
        if not player_ids:
            continue
        if user_id:
            remaining = len(player_ids - owned_player_ids)
        else:
            remaining = len(player_ids)
        result.append({
            "team_id": team.id,
            "team_name": team.name,
            "logo_url": team.logo_url,
            "remaining": remaining,
        })
    result.sort(key=lambda t: (t["remaining"] == 0, t["team_name"] or ""))
    return result


@router.post("/draw/booster/{team_id}")
def draw_booster(team_id: int, db=Depends(get_db),
                 current_user: dict = Depends(get_current_user)):
    """Draw a card guaranteed to be from the specified team's player roster."""
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    weights_map = {w.key: w.value for w in db.query(Weight).all()}
    cost = int(weights_map.get("team_booster_cost", 3))

    if (user.tokens or 0) < cost:
        raise HTTPException(status_code=409, detail="Not enough tokens")

    rarity = _roll_rarity(weights_map)
    player = _pick_player_from_team(db, user_id, rarity, team_id)
    if player is None:
        raise HTTPException(status_code=409,
                            detail="No players available for this team")

    card = Card(card_type=rarity, player_id=player.id, owner_id=user_id,
                league_id=None, is_active=False, generation=1)
    db.add(card)
    db.flush()

    active_count = db.query(Card).filter(
        Card.owner_id == user_id, Card.is_active == True
    ).count()
    card.is_active = active_count < ROSTER_LIMIT

    _assign_modifiers(db, card, weights_map)

    team_row = db.execute(text("""
        SELECT t.name, t.logo_url FROM player_match_stats s
        JOIN teams t ON t.id = s.team_id
        WHERE s.player_id = :pid ORDER BY s.match_id DESC LIMIT 1
    """), {"pid": player.id}).first()

    user.tokens = (user.tokens or 0) - cost
    _audit(db, "token_booster_draw", actor_id=user_id, actor_username=user.username,
           detail=f"card_id={card.id} player={player.name} rarity={rarity} "
                  f"team_id={team_id} cost={cost}")
    db.commit()

    mods = _card_modifiers_map(db, [card.id]).get(card.id, {})
    return {
        "id": card.id,
        "card_type": card.card_type,
        "player_id": player.id,
        "player_name": player.name,
        "avatar_url": player.avatar_url,
        "team_name": team_row.name if team_row else team.name,
        "team_logo_url": team_row.logo_url if team_row else team.logo_url,
        "is_active": card.is_active,
        "tokens": user.tokens,
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
    from models import UserTag, TagDefinition
    if not PIL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Image generation unavailable (Pillow not installed)")
    result = db.execute(text("""
        SELECT c.card_type, p.name as player_name, p.avatar_url,
               p.id as player_id,
               t.name as team_name, t.logo_url as team_logo_url
        FROM cards c
        JOIN players p ON p.id = c.player_id
""" + _LATEST_TEAM_SUBQUERY + """
        WHERE c.id = :card_id
    """), {"card_id": card_id}).first()
    if not result:
        raise HTTPException(status_code=404, detail="Card not found")
    mods: dict = _card_modifiers_dict_for_image(db, card_id)
    # Resolve tag keys for the player's linked user (if any)
    tag_keys: list = []
    linked_user = db.execute(text(
        "SELECT id FROM users WHERE player_id = :pid LIMIT 1"
    ), {"pid": result.player_id}).first()
    if linked_user:
        ut_rows = (
            db.query(UserTag, TagDefinition)
            .join(TagDefinition, TagDefinition.id == UserTag.tag_id)
            .filter(UserTag.user_id == linked_user.id)
            .all()
        )
        tag_keys = [td.key for _, td in ut_rows]
    img = generate_card_image(
        card_type=result.card_type,
        player_name=result.player_name,
        avatar_url=result.avatar_url,
        team_name=result.team_name,
        team_logo_url=result.team_logo_url,
        card_modifiers=mods,
        tag_keys=tag_keys,
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
    if card.card_type == "common":
        raise HTTPException(status_code=400, detail="Common cards cannot be rerolled")

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


@router.post("/roster/reorder")
def reorder_roster(body: ReorderRequest, user=Depends(get_current_user), db=Depends(get_db)):
    """Assign slot_index to each card in the ordered list. Zone (active/bench) is
    determined by each card's current is_active state; the caller should only mix
    cards from the same zone in a single call."""
    user_id = user["user_id"]
    use_explicit = body.slot_indexes and len(body.slot_indexes) == len(body.card_ids)
    for i, card_id in enumerate(body.card_ids):
        card = db.query(Card).filter_by(id=card_id, owner_id=user_id).first()
        if card:
            card.slot_index = body.slot_indexes[i] if use_explicit else i
    db.commit()
    return {"ok": True}


@router.post("/roster/swap")
def swap_roster(body: SwapRequest, user=Depends(get_current_user), db=Depends(get_db)):
    """Atomically move a bench card to the active roster and an active card to the
    bench. Applies the duplicate-player guard before committing."""
    user_id = user["user_id"]
    bench_card = db.query(Card).filter_by(id=body.bench_card_id, owner_id=user_id, is_active=False).first()
    active_card = db.query(Card).filter_by(id=body.active_card_id, owner_id=user_id, is_active=True).first()
    if not bench_card or not active_card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Duplicate-player guard: bench card's player must not already be active elsewhere
    duplicate = db.query(Card).filter(
        Card.owner_id == user_id,
        Card.player_id == bench_card.player_id,
        Card.is_active == True,
        Card.id != active_card.id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="A card for this player is already active")

    active_card.is_active = False
    active_card.slot_index = None
    bench_card.is_active = True
    bench_card.slot_index = body.slot_index
    db.commit()
    return {"ok": True}


@router.get("/roster/{user_id}")
def get_roster(user_id: int, week_id: int = None, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    if user_id != current_user["user_id"] and not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Cannot view another user's roster")
    return _build_roster_response(db, user_id, week_id)
