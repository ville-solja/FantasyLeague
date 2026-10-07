import io
import os
import random
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from card_draw import _roll_rarity, _pick_player, _pick_player_from_team
import card_points
from card_utils import (
    _assign_modifiers, _card_modifiers_map, _card_modifiers_dict_for_image, _format_modifiers,
    _activate_card_atomic, _swap_roster_atomic,
)
from database import get_db, spend_tokens
from match_scoring import counted_roster_entry_sql, scored_match_sql
from deps import get_current_user, is_admin_fresh, session_user_or_none, _audit
from logo_hosts import safe_logo_url
from models import Card, Player, PlayerMatchStats, Team, User, Week, Weight
from rate_limit import limiter, key_by_user_or_ip
from scoring import display_points
from weeks import get_next_editable_week, substitution_delay_hours

router = APIRouter()

ROSTER_LIMIT = int(os.getenv("ROSTER_LIMIT", "5"))

# Per-user limit on roster activate/deactivate/swap/reorder (issue #124). Keyed by
# session user_id (falls back to source IP if somehow unauthenticated — see
# key_by_user_or_ip in rate_limit.py). These four routes are split into a plain,
# undecorated business-logic function (activate_card, deactivate_card,
# reorder_roster, swap_roster — same signature as before, still directly
# importable/callable by tests, e.g. backend/tests/test_issue_125_roster_limit_race_fix.py
# and backend/tests/test_issue_40_my_team_drag_and_drop.py which call them as plain
# Python functions with positional args) and a thin `*_route` wrapper that FastAPI
# actually registers, carrying the new `request: Request` parameter slowapi's
# @limiter.limit(...) decorator requires. Adding `request` directly to the business
# functions would have shifted those tests' existing positional arguments into the
# wrong parameters.
RATE_LIMIT_ROSTER_MUTATION = os.getenv("RATE_LIMIT_ROSTER_MUTATION", "30/minute")

# Per-IP limit on the public, render-per-call card image endpoint (issue #135).
RATE_LIMIT_CARD_IMAGE = os.getenv("RATE_LIMIT_CARD_IMAGE", "60/minute")


class ReorderRequest(BaseModel):
    card_ids: list[int] = Field(max_length=500)  # ordered list; positions assigned by index. The frontend sends the whole bench, and bench size is unlimited, so this bounds abuse without breaking large collections
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


_WEEK_WINDOW_SQL = ("(m.week_override_id = :week_id OR "
                    "(m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))")


def _slot_key(c: dict):
    return (c.get("slot_index") is None, c.get("slot_index") or 0, c["id"])


def _build_roster_response(db, user_id: int, week_id: int | None) -> dict:
    """Compute roster data for a user, scoped to the given week (or next editable week).

    Card points are sums of stored per-match rows (card_match_points, issue #141) over
    the scored matches in the week window; nothing is recalculated here."""
    week = db.get(Week, week_id) if week_id is not None else get_next_editable_week(db)
    now = int(time.time())

    week_sums = (
        f"COUNT(m.match_id) as match_count, "
        f"COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN cmp.points END), 0) as total_points"
    )
    week_join = f"""
            LEFT JOIN card_match_points cmp ON cmp.card_id = c.id
            LEFT JOIN matches m ON m.match_id = cmp.match_id AND {scored_match_sql()}
                AND {_WEEK_WINDOW_SQL}"""

    if week and week.is_locked:
        # Snapshot rows (issue #129): counted entries are the roster, the rest (saved
        # bench and subbed-out cards) the bench.
        results = db.execute(text(f"""
            SELECT c.id, c.card_type,
                   CASE WHEN {counted_roster_entry_sql()} THEN 1 ELSE 0 END as is_active,
                   c.slot_index,
                   wre.id as entry_id, wre.bench_order, wre.subbed_for_entry_id,
                   COALESCE(wre.subbed_in, 0) as subbed_in,
                   COALESCE(wre.subbed_out, 0) as subbed_out,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.id as team_id, t.name as team_name, t.logo_url as team_logo_url,
                   {week_sums}
            FROM weekly_roster_entries wre
            JOIN cards c ON c.id = wre.card_id
            JOIN players p ON p.id = c.player_id
            {week_join}
            {_LATEST_TEAM_SUBQUERY}
            WHERE wre.week_id = :week_id AND wre.user_id = :user_id
            GROUP BY wre.id, c.id, c.card_type, c.slot_index, p.id, p.name, p.avatar_url, t.id, t.name, t.logo_url
        """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time,
               "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        by_entry = {c["entry_id"]: c for c in cards}
        replaced_of = {}
        for c in cards:
            c["subbed_in"] = bool(c["subbed_in"])
            c["subbed_out"] = bool(c["subbed_out"])
            replaced = by_entry.get(c.pop("subbed_for_entry_id")) if c["subbed_in"] else None
            c["subbed_in_for"] = replaced["player_name"] if replaced else None
            if replaced:
                replaced_of[c["entry_id"]] = replaced
                c["slot_index"] = replaced["slot_index"]  # shown in the replaced card's slot
        active = [c for c in cards if c["is_active"]]
        bench  = [c for c in cards if not c["is_active"]]
        # A subbed-in card takes the slot of the card it replaced; subbed-out cards
        # lead the bench, then the saved bench in its lock-time order.
        active.sort(key=lambda c: (_slot_key(c)[:2], c["entry_id"] not in replaced_of, c["id"]))
        bench.sort(key=lambda c: (not c["subbed_out"], c["bench_order"] is None,
                                  c["bench_order"] or 0, c["entry_id"]))
        for c in cards:
            del c["entry_id"], c["bench_order"]
    else:
        ws = week.start_time if week else 0
        we = week.end_time if week else now
        results = db.execute(text(f"""
            SELECT c.id, c.card_type, c.is_active, c.slot_index,
                   p.id as player_id, p.name as player_name, p.avatar_url,
                   t.id as team_id, t.name as team_name, t.logo_url as team_logo_url,
                   {week_sums}
            FROM cards c
            JOIN players p ON p.id = c.player_id
            {week_join}
            {_LATEST_TEAM_SUBQUERY}
            WHERE c.owner_id = :user_id AND p.is_active = 1
            GROUP BY c.id, c.card_type, c.is_active, c.slot_index, p.id, p.name, p.avatar_url, t.id, t.name, t.logo_url
            ORDER BY c.is_active DESC
        """), {"ws": ws, "we": we, "week_id": week.id if week else -1, "user_id": user_id}).fetchall()
        cards = [dict(r._mapping) for r in results]
        for c in cards:
            c["subbed_in"] = c["subbed_out"] = False
            c["subbed_in_for"] = None
        active = [c for c in cards if c["is_active"]]
        bench  = [c for c in cards if not c["is_active"]]
        active.sort(key=_slot_key)
        bench.sort(key=_slot_key)

    # Week total from exact card sums, then every value rounded once (issue #149).
    combined_value = sum(float(c["total_points"] or 0.0) for c in active)
    modifiers_map = _card_modifiers_map(db, [c["id"] for c in cards])
    for c in cards:
        c["modifiers"] = _format_modifiers(modifiers_map.get(c["id"], {}))
        c["total_points"] = display_points(c["total_points"])
        c["team_logo_url"] = safe_logo_url(c["team_logo_url"])

    user = db.get(User, user_id)
    tokens = user.tokens if user and user.tokens is not None else 0

    season_points = db.execute(text(f"""
        SELECT COALESCE(SUM(cmp.points), 0)
        FROM weekly_roster_entries wre
        JOIN weeks wk ON wk.id = wre.week_id AND wk.is_locked = 1
        JOIN card_match_points cmp ON cmp.card_id = wre.card_id
        JOIN matches m ON m.match_id = cmp.match_id AND {scored_match_sql()}
            AND (m.week_override_id = wk.id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN wk.start_time AND wk.end_time))
        WHERE wre.user_id = :user_id AND {counted_roster_entry_sql()}
    """), {"user_id": user_id}).scalar() or 0.0

    return {
        "active": active, "bench": bench,
        "combined_value": display_points(combined_value),
        "tokens": tokens,
        "season_points": display_points(season_points),
        "week": {"id": week.id, "label": week.label, "is_locked": week.is_locked,
                 "start_time": week.start_time, "end_time": week.end_time,
                 "substitutions_done": week.substitutions_at is not None} if week else None,
        "substitutions_done": bool(week and week.substitutions_at is not None),
        "substitution_delay_hours": substitution_delay_hours(),
    }


def collection_for_user(db, user_id: int) -> list[dict]:
    """Every card the user owns with player, team, rarity, modifiers, roster state and
    season points (the card's stored points over all scored matches), rarest first,
    then by player name. Used by the Twitch panel's GET /twitch/me (issue #157)."""
    rows = db.execute(text(f"""
        SELECT c.id, c.card_type, c.is_active, c.slot_index,
               p.id as player_id, p.name as player_name, p.avatar_url,
               t.id as team_id, t.name as team_name, t.logo_url as team_logo_url,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN cmp.points END), 0) as season_points
        FROM cards c
        JOIN players p ON p.id = c.player_id
        LEFT JOIN card_match_points cmp ON cmp.card_id = c.id
        LEFT JOIN matches m ON m.match_id = cmp.match_id AND {scored_match_sql()}
        {_LATEST_TEAM_SUBQUERY}
        WHERE c.owner_id = :user_id
        GROUP BY c.id, c.card_type, c.is_active, c.slot_index, p.id, p.name, p.avatar_url,
                 t.id, t.name, t.logo_url
    """), {"user_id": user_id}).fetchall()
    cards = [dict(r._mapping) for r in rows]
    modifiers_map = _card_modifiers_map(db, [c["id"] for c in cards])
    rank = {"legendary": 0, "epic": 1, "rare": 2, "common": 3}
    for c in cards:
        c["is_active"] = bool(c["is_active"])
        c["season_points"] = display_points(c["season_points"])
        c["team_logo_url"] = safe_logo_url(c["team_logo_url"])
        c["modifiers"] = _format_modifiers(modifiers_map.get(c["id"], {}))
    cards.sort(key=lambda c: (rank.get(c["card_type"], 4), (c["player_name"] or "").lower(), c["id"]))
    return cards


@router.get("/deck")
def get_deck(request: Request, db=Depends(get_db)):
    rarities = ["common", "rare", "epic", "legendary"]
    all_players = db.query(Player).all()
    all_combos = {(p.id, r) for p in all_players for r in rarities}

    session_user = session_user_or_none(request, db)
    user_id = session_user.id if session_user else None
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
    card_points.refresh_card_points(db, card_ids=[card.id])

    team_row = db.execute(text("""
        SELECT t.name, t.logo_url
        FROM player_match_stats s
        JOIN teams t ON t.id = s.team_id
        WHERE s.player_id = :pid
        ORDER BY s.match_id DESC LIMIT 1
    """), {"pid": player.id}).first()

    if not spend_tokens(db, user_id, 1):
        db.rollback()
        raise HTTPException(status_code=409, detail="Not enough tokens")
    db.refresh(user)
    _audit(db, "token_draw", actor_id=user_id, actor_username=user.display_name,
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
        "team_logo_url": safe_logo_url(team_row.logo_url) if team_row else None,
        "is_active": is_active,
        "tokens": tokens_remaining,
        "modifiers": _format_modifiers(mods),
    }


@router.get("/deck/booster")
def get_booster_deck(request: Request, db=Depends(get_db)):
    """Return per-team drawable card counts for the requesting user."""
    session_user = session_user_or_none(request, db)
    return booster_deck_for_user(db, session_user.id if session_user else None)


def booster_deck_for_user(db, user_id: int | None) -> list[dict]:
    """Teams with players who have match data and how many of those players `user_id`
    does not own yet (all of them when user_id is None). Shared by GET /deck/booster
    and the Twitch panel's GET /twitch/teams (issue #157)."""
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
            "logo_url": safe_logo_url(team.logo_url),
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
    card_points.refresh_card_points(db, card_ids=[card.id])

    team_row = db.execute(text("""
        SELECT t.name, t.logo_url FROM player_match_stats s
        JOIN teams t ON t.id = s.team_id
        WHERE s.player_id = :pid ORDER BY s.match_id DESC LIMIT 1
    """), {"pid": player.id}).first()

    if not spend_tokens(db, user_id, cost):
        db.rollback()
        raise HTTPException(status_code=409, detail="Not enough tokens")
    db.refresh(user)
    _audit(db, "token_booster_draw", actor_id=user_id, actor_username=user.display_name,
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
        "team_logo_url": safe_logo_url(team_row.logo_url if team_row else team.logo_url),
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
        "team_logo_url": safe_logo_url(team_row.logo_url) if team_row else None,
        "modifiers": _format_modifiers(mods),
    }


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


@router.get("/cards/{card_id}/image")
@limiter.limit(RATE_LIMIT_CARD_IMAGE)
def get_card_image_route(request: Request, card_id: int, db=Depends(get_db)):
    return get_card_image(card_id, db)


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
    card_points.refresh_card_points(db, card_ids=[card_id])

    if not spend_tokens(db, user_id, 1):
        db.rollback()
        raise HTTPException(status_code=409, detail="Not enough tokens")
    db.refresh(user)
    _audit(db, "reroll_modifiers", actor_id=user_id, actor_username=user.display_name,
           detail=f"card_id={card_id} rarity={card.card_type}")
    db.commit()
    tokens_remaining = user.tokens

    mods = _card_modifiers_map(db, [card_id]).get(card_id, {})
    return {
        "modifiers": _format_modifiers(mods),
        "tokens": tokens_remaining,
    }


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

    if not _activate_card_atomic(db, card_id, user_id, card.player_id, ROSTER_LIMIT):
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Roster full ({ROSTER_LIMIT} cards max)")
    db.commit()
    return {"status": "ok", "card_id": card_id}


@router.post("/roster/{card_id}/activate")
@limiter.limit(RATE_LIMIT_ROSTER_MUTATION, key_func=key_by_user_or_ip)
def activate_card_route(request: Request, card_id: int, db=Depends(get_db),
                         current_user: dict = Depends(get_current_user)):
    return activate_card(card_id, db, current_user)


def deactivate_card(card_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    card = db.get(Card, card_id)
    if not card or card.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Card not found")
    card.is_active = False
    db.commit()
    return {"status": "ok", "card_id": card_id}


@router.post("/roster/{card_id}/deactivate")
@limiter.limit(RATE_LIMIT_ROSTER_MUTATION, key_func=key_by_user_or_ip)
def deactivate_card_route(request: Request, card_id: int, db=Depends(get_db),
                           current_user: dict = Depends(get_current_user)):
    return deactivate_card(card_id, db, current_user)


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


@router.post("/roster/reorder")
@limiter.limit(RATE_LIMIT_ROSTER_MUTATION, key_func=key_by_user_or_ip)
def reorder_roster_route(request: Request, body: ReorderRequest,
                          user=Depends(get_current_user), db=Depends(get_db)):
    return reorder_roster(body, user, db)


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

    if not _swap_roster_atomic(db, body.bench_card_id, body.active_card_id, user_id,
                                bench_card.player_id, body.slot_index):
        db.rollback()
        raise HTTPException(status_code=409, detail="A card for this player is already active")
    db.commit()
    return {"ok": True}


@router.post("/roster/swap")
@limiter.limit(RATE_LIMIT_ROSTER_MUTATION, key_func=key_by_user_or_ip)
def swap_roster_route(request: Request, body: SwapRequest,
                       user=Depends(get_current_user), db=Depends(get_db)):
    return swap_roster(body, user, db)


@router.get("/roster/{user_id}")
def get_roster(user_id: int, week_id: int = None, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    if user_id != current_user["user_id"] and not is_admin_fresh(db, current_user["user_id"]):
        raise HTTPException(status_code=403, detail="Cannot view another user's roster")
    return _build_roster_response(db, user_id, week_id)
