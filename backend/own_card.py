"""A league player's own card (issue #188).

A Steam-verified account whose player id is an active player in the pool gets one
common card of that player, once per account and once per league player
(own_player_card_grants: unique user_id, unique player_id). When the account already
owns a card of that player, nothing is created and the grant is recorded as
"already_owned", so draws, which skip owned players, never lead to a duplicate.

grant_own_player_card runs after Link Steam and Steam sign-up (steam_openid.py) and on
GET /me (routers/profile.py) for accounts that qualify but have no grant yet. The
popup that explains the gift reads pending_popup until POST /profile/own-card-grant/seen.
"""
import logging
import time

from sqlalchemy import or_, text

import card_points
from card_utils import _assign_modifiers
from deps import _audit
from models import Card, OwnPlayerCardGrant, Player, User, Weight

logger = logging.getLogger(__name__)

OUTCOME_GRANTED = "granted"
OUTCOME_ALREADY_OWNED = "already_owned"

# Neither the account nor the player may already have a row; ON CONFLICT DO NOTHING
# without a target covers both unique columns, also between simultaneous requests.
_GRANT_SQL = text(
    "INSERT INTO own_player_card_grants (user_id, player_id, card_id, outcome, granted_at) "
    "VALUES (:uid, :pid, NULL, :outcome, :now) ON CONFLICT DO NOTHING")


def is_candidate(user: User | None) -> bool:
    """Steam-verified player id on a full, non-demo account. Self-reported ids (no
    steam_id) never qualify."""
    return bool(user is not None and user.steam_id and user.player_id
                and not user.is_demo and not user.is_soft)


def has_grant_row(db, user: User) -> bool:
    return db.query(OwnPlayerCardGrant.id).filter(
        or_(OwnPlayerCardGrant.user_id == user.id,
            OwnPlayerCardGrant.player_id == user.player_id)).first() is not None


def grant_own_player_card(db, user: User) -> OwnPlayerCardGrant | None:
    """Give the account its own player card when it qualifies; return the new grant
    row, or None when nothing was recorded. Does not commit."""
    if not is_candidate(user):
        return None
    player = db.get(Player, user.player_id)
    if player is None or not player.is_active:
        return None
    if has_grant_row(db, user):
        return None
    owned = db.query(Card.id).filter(Card.owner_id == user.id,
                                     Card.player_id == player.id).first() is not None
    outcome = OUTCOME_ALREADY_OWNED if owned else OUTCOME_GRANTED
    result = db.execute(_GRANT_SQL, {"uid": user.id, "pid": player.id, "outcome": outcome,
                                     "now": int(time.time())})
    if result.rowcount != 1:
        return None
    grant = db.query(OwnPlayerCardGrant).filter(OwnPlayerCardGrant.user_id == user.id).one()
    if outcome == OUTCOME_GRANTED:
        # Imported here: routers.cards pulls in the card routes, which this module's
        # callers (steam_openid, routers.profile) don't otherwise need at import.
        from routers.cards import _activate_new_card
        weights = {w.key: w.value for w in db.query(Weight).all()}
        card = Card(card_type="common", player_id=player.id, owner_id=user.id,
                    league_id=None, is_active=False, generation=1)
        db.add(card)
        db.flush()
        _activate_new_card(db, card, user.id)
        _assign_modifiers(db, card, weights)
        card_points.refresh_card_points(db, card_ids=[card.id])
        grant.card_id = card.id
    _audit(db, "own_player_card_granted", actor_id=user.id, actor_username=user.display_name,
           detail=f"user_id={user.id} player_id={player.id} card_id={grant.card_id} "
                  f"outcome={outcome}")
    return grant


def grant_in_savepoint(db, user: User) -> OwnPlayerCardGrant | None:
    """grant_own_player_card inside a savepoint: a failure rolls back only the grant
    (logged by exception type), so the caller's Steam link, sign-up or page load still
    succeeds. GET /me tries again on the next visit. Does not commit."""
    try:
        with db.begin_nested():
            return grant_own_player_card(db, user)
    except Exception as exc:  # noqa: BLE001 — the grant must never break its caller
        logger.warning("Own player card grant failed for user %s (%s)", user.id,
                       type(exc).__name__)
        return None


def pending_popup(db, user: User) -> dict | None:
    """The grant the player hasn't dismissed yet, for GET /me's own_card_grant."""
    grant = (db.query(OwnPlayerCardGrant)
             .filter(OwnPlayerCardGrant.user_id == user.id,
                     OwnPlayerCardGrant.seen_at.is_(None)).first())
    if grant is None:
        return None
    player = db.get(Player, grant.player_id)
    return {"player_name": player.name if player else None, "card_id": grant.card_id,
            "outcome": grant.outcome}


def mark_seen(db, user_id: int) -> bool:
    """Dismiss the popup. True when a pending grant was marked."""
    result = db.execute(text("UPDATE own_player_card_grants SET seen_at = :now "
                             "WHERE user_id = :uid AND seen_at IS NULL"),
                        {"now": int(time.time()), "uid": user_id})
    return result.rowcount == 1
