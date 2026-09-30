"""Stored per-match card points (issue #141).

Each (card, match) pair gets one `card_match_points` row holding the card's final
points for that match:

    card_fantasy_score(match stats, card modifiers, match_count=1)
    + MVP bonus (when the player was that match's MVP)
    × rarity multiplier

The death bonus is therefore floored at 0 per match, the same way the Players tab's
per-match `fantasy_points` are. My Team, the weekly and season leaderboards and the
End Season archive sum these rows; match exclusion and week assignment are applied
when reading, so toggling them needs no rebuild.

Rows are written when an input changes:
- a match is ingested or its stats are replaced (refresh by match),
- an MVP is set or changed (refresh by match),
- a card is drawn or its modifiers are rerolled (refresh by card),
- the weights change (`rebuild_all`, run by the startup check and POST /recalculate).
"""

import hashlib
import json
import logging

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert

from card_utils import _compute_card_points, _load_weights, _mvp_bonus_delta
from models import Card, CardMatchPoints, CardModifier, PlayerMatchStats, ScoringState
from scoring import stat_dict_from_row

logger = logging.getLogger(__name__)

FINGERPRINT_KEY = "card_points_weights_fingerprint"


def weights_fingerprint(weights: dict) -> str:
    """Hash of the sorted weight key/value pairs; independent of key order."""
    pairs = sorted((str(k), None if v is None else float(v)) for k, v in weights.items())
    return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()


def _modifiers(db, card_ids) -> dict[int, dict]:
    q = db.query(CardModifier.card_id, CardModifier.stat_key, CardModifier.bonus_pct)
    if card_ids is not None:
        q = q.filter(CardModifier.card_id.in_(card_ids))
    result: dict[int, dict] = {}
    for card_id, stat_key, bonus_pct in q.all():
        result.setdefault(card_id, {})[stat_key] = bonus_pct
    return result


def _compute(db, card_ids=None, match_ids=None, player_ids=None) -> dict[tuple, dict]:
    """{(card_id, match_id): row dict} for every card and stat row in the scope.
    A None filter means "no restriction"; the filters combine with AND."""
    weights, rarity = _load_weights(db)

    cq = db.query(Card.id, Card.card_type, Card.player_id)
    if card_ids is not None:
        cq = cq.filter(Card.id.in_(card_ids))
    if player_ids is not None:
        cq = cq.filter(Card.player_id.in_(player_ids))
    if match_ids is not None:
        cq = cq.filter(Card.player_id.in_(
            db.query(PlayerMatchStats.player_id).filter(PlayerMatchStats.match_id.in_(match_ids))))
    cards = cq.all()
    if not cards:
        return {}

    sq = db.query(PlayerMatchStats)
    if match_ids is not None:
        sq = sq.filter(PlayerMatchStats.match_id.in_(match_ids))
    if card_ids is not None or player_ids is not None:
        sq = sq.filter(PlayerMatchStats.player_id.in_({c.player_id for c in cards}))
    stats_by_player: dict[int, list] = {}
    for stat in sq.all():
        if stat.match_id is None:
            continue
        stats_by_player.setdefault(stat.player_id, []).append(stat)

    unscoped = card_ids is None and player_ids is None and match_ids is None
    mods_map = _modifiers(db, None if unscoped else [c.id for c in cards])

    # Per-stat-row base values, shared by every card of that player.
    prepared: dict[int, tuple] = {}
    rows: dict[tuple, dict] = {}
    for card_id, card_type, player_id in cards:
        mods = mods_map.get(card_id, {})
        for stat in stats_by_player.get(player_id, ()):
            prep = prepared.get(stat.id)
            if prep is None:
                prep = (stat_dict_from_row(stat),
                        _mvp_bonus_delta(stat, weights) if stat.is_mvp else 0.0)
                prepared[stat.id] = prep
            stat_dict, mvp_bonus = prep
            points = _compute_card_points(stat_dict, card_type, weights, rarity, mods,
                                          mvp_bonus=mvp_bonus, match_count=1)
            key = (card_id, stat.match_id)
            if key in rows:  # duplicate stat rows for one player and match: add them up
                rows[key]["points"] += points
            else:
                rows[key] = {"card_id": card_id, "match_id": stat.match_id,
                             "player_id": player_id, "points": points}
    return rows


def _dialect_insert(db):
    return _pg_insert if db.get_bind().dialect.name == "postgresql" else _sqlite_insert


def refresh_card_points(db, card_ids=None, match_ids=None, player_ids=None) -> int:
    """Bring the stored rows in the given scope up to date with the current stats, cards,
    modifiers, MVP flags and weights: upsert every (card, match) row in the scope and
    delete stored rows in the scope that no longer have a stat row (e.g. replaced or
    removed stats). Does not commit; returns the number of rows written.

    Pass at least one filter; use rebuild_all() to rewrite the whole table."""
    if card_ids is None and match_ids is None and player_ids is None:
        raise ValueError("refresh_card_points needs card_ids, match_ids or player_ids")
    db.flush()
    rows = _compute(db, card_ids=card_ids, match_ids=match_ids, player_ids=player_ids)

    eq = db.query(CardMatchPoints.id, CardMatchPoints.card_id, CardMatchPoints.match_id)
    if card_ids is not None:
        eq = eq.filter(CardMatchPoints.card_id.in_(card_ids))
    if match_ids is not None:
        eq = eq.filter(CardMatchPoints.match_id.in_(match_ids))
    if player_ids is not None:
        eq = eq.filter(CardMatchPoints.player_id.in_(player_ids))
    stale = [row_id for row_id, card_id, match_id in eq.all() if (card_id, match_id) not in rows]
    if stale:
        db.execute(delete(CardMatchPoints).where(CardMatchPoints.id.in_(stale)))

    if rows:
        insert = _dialect_insert(db)
        stmt = insert(CardMatchPoints)
        stmt = stmt.on_conflict_do_update(
            index_elements=[CardMatchPoints.card_id, CardMatchPoints.match_id],
            set_={"points": stmt.excluded.points, "player_id": stmt.excluded.player_id},
        )
        db.execute(stmt, list(rows.values()))
    return len(rows)


def delete_card_points(db, card_ids=None, match_ids=None) -> int:
    """Delete stored rows for deleted cards or matches. Does not commit."""
    stmt = delete(CardMatchPoints)
    if card_ids is not None:
        stmt = stmt.where(CardMatchPoints.card_id.in_(card_ids))
    if match_ids is not None:
        stmt = stmt.where(CardMatchPoints.match_id.in_(match_ids))
    return db.execute(stmt).rowcount


def _current_weights(db) -> dict:
    weights, _ = _load_weights(db)
    return weights


def rebuild_all(db) -> int:
    """Delete and rewrite every card_match_points row, then store the weights
    fingerprint, in one transaction (commits). On failure the transaction is rolled
    back, so the previous rows and fingerprint stay, and the error is logged and
    re-raised. Returns the number of rows written."""
    try:
        db.flush()
        rows = _compute(db)
        fingerprint = weights_fingerprint(_current_weights(db))
        db.execute(delete(CardMatchPoints))
        if rows:
            db.execute(CardMatchPoints.__table__.insert(), list(rows.values()))
        state = db.get(ScoringState, FINGERPRINT_KEY)
        if state is None:
            db.add(ScoringState(key=FINGERPRINT_KEY, value=fingerprint))
        else:
            state.value = fingerprint
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Card points rebuild failed; previous stored points kept")
        raise
    logger.info("Card points rebuilt: %d rows", len(rows))
    return len(rows)


def ensure_card_points_current(db) -> int | None:
    """Startup check: rebuild when card_match_points is empty or the weights differ from
    the ones it was built with. Returns the rebuilt row count, or None when skipped."""
    fingerprint = weights_fingerprint(_current_weights(db))
    state = db.get(ScoringState, FINGERPRINT_KEY)
    has_rows = db.query(CardMatchPoints.id).first() is not None
    if has_rows and state is not None and state.value == fingerprint:
        logger.info("Card points: stored rows match the current weights; no rebuild")
        return None
    reason = "table empty" if not has_rows else "weights changed"
    logger.info("Card points: rebuilding (%s)", reason)
    return rebuild_all(db)
