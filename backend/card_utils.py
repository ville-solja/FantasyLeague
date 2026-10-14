import hashlib
import random

from sqlalchemy import bindparam, text

from models import Card, CardModifier, Weight
from scoring import (
    _death_contribution, card_fantasy_score, fantasy_score, stat_dict_from_row, SCORING_STATS,
)


_SCORED_STAT_COLS = list(SCORING_STATS) + ["deaths"]


def _load_weights(db) -> tuple[dict, dict]:
    """Return (weights_dict, rarity_dict) loaded from DB in a single query.

    weights_dict — full {key: value} map, used directly by card_fantasy_score()
    rarity_dict  — {"mod_common": 0.0, "mod_rare": 0.01, ...} multipliers
    """
    all_weights = {w.key: w.value for w in db.query(Weight).all()}
    rarity = {
        "mod_common":    all_weights.get("rarity_common",    0.0) / 100,
        "mod_rare":      all_weights.get("rarity_rare",      1.0) / 100,
        "mod_epic":      all_weights.get("rarity_epic",      2.0) / 100,
        "mod_legendary": all_weights.get("rarity_legendary", 3.0) / 100,
    }
    return all_weights, rarity


def _mvp_bonus_delta(row, weights: dict) -> float:
    """Additive fantasy-point bonus for one MVP-flagged match.

    Mirrors the player-level bonus applied by scoring.apply_mvp_bonus_to_row(): the
    match's own fantasy_score() (deaths included) times mvp_bonus_pct,
    computed on that single match rather than on a card's multi-match
    aggregate, so the bonus only reflects the MVP game itself.
    """
    stats = stat_dict_from_row(row)
    base = fantasy_score(stats, weights)
    bonus_pct = weights.get("mvp_bonus_pct", 10.0)
    return base * bonus_pct / 100


def _compute_card_points(stat_sums: dict, card_type: str, weights: dict, rarity: dict, mods: dict,
                          mvp_bonus: float = 0.0, match_count: int = 1) -> float:
    """Apply card_fantasy_score + rarity multiplier for one card.

    mvp_bonus is the sum of _mvp_bonus_delta() over the MVP-flagged matches in
    stat_sums — added before the rarity multiplier so an MVP bonus scales with
    card rarity the same way every other stat does.
    match_count is the number of games in stat_sums (the death pool scales with it).

    Production callers (card_points.py, issue #141) score one match at a time:
    stat_sums is a single match's stats, mvp_bonus is that match's delta (or 0) and
    match_count is 1, so the death bonus is floored per match. The aggregate
    arguments are kept for API compatibility.
    """
    base = card_fantasy_score(stat_sums, weights, mods, match_count) + mvp_bonus
    rarity_mod = 1 + rarity.get(f"mod_{card_type}", 0)
    return base * rarity_mod


def card_points_breakdown(stats: dict, card_type: str, weights: dict, rarity: dict,
                          mods: dict, mvp_bonus: float = 0.0) -> dict:
    """Exact parts of one game's card points, in display order (issue #152); they sum to
    _compute_card_points(stats, card_type, weights, rarity, mods, mvp_bonus).

    Each part after raw carries the rarity multiplier on its own share, so the parts
    can be shown in the order raw, rarity, modifiers, MVP and still add up."""
    r = rarity.get(f"mod_{card_type}", 0)
    raw = fantasy_score(stats, weights)
    mod_parts = {}
    for stat, pct in mods.items():
        if stat == "deaths":
            base = _death_contribution(stats.get("deaths", 0), weights)
        else:
            base = weights.get(stat, 0) * stats.get(stat, 0)
        mod_parts[stat] = base * pct / 100 * (1 + r)
    return {"raw": raw, "rarity": raw * r, "modifiers": mod_parts,
            "mvp": mvp_bonus * (1 + r), "rarity_pct": r * 100}


def _assign_modifiers(db, card: Card, weights: dict):
    """Randomly assign stat modifiers to a card based on its rarity and configured weights.

    modifier_count_<rarity>  — how many stats get a modifier
    modifier_bonus_pct       — the % bonus each modifier grants
    """
    count_key = f"modifier_count_{card.card_type}"
    count = int(weights.get(count_key, 0))
    if count <= 0:
        return
    bonus_pct = weights.get("modifier_bonus_pct", 10.0)
    chosen = random.sample(_SCORED_STAT_COLS, min(count, len(_SCORED_STAT_COLS)))
    for stat in chosen:
        db.add(CardModifier(card_id=card.id, stat_key=stat, bonus_pct=bonus_pct))


def _card_modifiers_map(db, card_ids: list[int]) -> dict[int, dict]:
    """Return {card_id: {stat_key: bonus_pct}} for a list of card IDs."""
    if not card_ids:
        return {}
    rows = db.query(CardModifier).filter(CardModifier.card_id.in_(card_ids)).all()
    result: dict[int, dict] = {}
    for row in rows:
        result.setdefault(row.card_id, {})[row.stat_key] = row.bonus_pct
    return result


def _card_modifiers_dict_for_image(db, card_id: int) -> dict:
    """Fresh read from DB for PNG generation (avoids any ORM identity-map edge cases)."""
    rows = db.execute(
        text("SELECT stat_key, bonus_pct FROM card_modifiers WHERE card_id = :cid"),
        {"cid": card_id},
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def _format_modifiers(mods: dict) -> list[dict]:
    """Convert {stat_key: bonus_pct} to sorted list for API response."""
    return [{"stat": k, "bonus_pct": v} for k, v in sorted(mods.items())]


def _activate_card_atomic(db, card_id: int, user_id: int, player_id: int, roster_limit: int) -> bool:
    """Atomically activate a card if the user still has room and no duplicate-player
    conflict exists. Returns True if activated, False if any condition failed.

    A single UPDATE...WHERE (not a separate SELECT COUNT then UPDATE) closes the race
    where concurrent requests all read the same pre-activation count and all pass —
    SQLite serializes writers, so the WHERE clause's subqueries and the row mutation
    are evaluated atomically with respect to any other in-flight transaction.
    """
    result = db.execute(text("""
        UPDATE cards
        SET is_active = 1
        WHERE id = :card_id
          AND owner_id = :user_id
          AND is_active = 0
          AND (
              SELECT COUNT(*) FROM cards
              WHERE owner_id = :user_id AND is_active = 1
          ) < :roster_limit
          AND NOT EXISTS (
              SELECT 1 FROM cards c2
              WHERE c2.owner_id = :user_id
                AND c2.player_id = :player_id
                AND c2.is_active = 1
                AND c2.id != :card_id
          )
    """), {"card_id": card_id, "user_id": user_id, "player_id": player_id,
           "roster_limit": roster_limit})
    return result.rowcount > 0


def _swap_roster_atomic(db, bench_card_id: int, active_card_id: int, user_id: int,
                         bench_player_id: int, slot_index) -> bool:
    """Atomically flip bench_card active and active_card inactive, only if bench_card's
    player has no other active card. Returns True if the swap happened; on False the
    caller must roll back (the active card may already be benched).

    The active card is benched first: the partial unique index
    ux_cards_owner_player_active (issue #185) checks each statement, so activating a
    bench card of the same player while the outgoing card is still active would fail."""
    result = db.execute(text("""
        UPDATE cards SET is_active = 0, slot_index = NULL
        WHERE id = :active_card_id AND owner_id = :user_id AND is_active = 1
    """), {"active_card_id": active_card_id, "user_id": user_id})
    if result.rowcount == 0:
        return False
    result = db.execute(text("""
        UPDATE cards
        SET is_active = 1, slot_index = :slot_index
        WHERE id = :bench_card_id
          AND owner_id = :user_id
          AND is_active = 0
          AND NOT EXISTS (
              SELECT 1 FROM cards c2
              WHERE c2.owner_id = :user_id
                AND c2.player_id = :bench_player_id
                AND c2.is_active = 1
                AND c2.id != :active_card_id
          )
    """), {"bench_card_id": bench_card_id, "user_id": user_id,
           "bench_player_id": bench_player_id, "active_card_id": active_card_id,
           "slot_index": slot_index})
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Issue #186: the whole roster layout, versioned and saved in one transaction
# ---------------------------------------------------------------------------

ROSTER_VERSION_CONFLICT = "version"
ROSTER_VERSION_DETAIL = "Your roster changed elsewhere"
ROSTER_DUPLICATE_ID_DETAIL = "A card is listed more than once"
ROSTER_REMOVED_PLAYER_DETAIL = "A removed player can't be on the roster"


class RosterLayoutError(Exception):
    """A refused layout save. conflict is ROSTER_VERSION_CONFLICT for a stale base_version."""

    def __init__(self, status_code: int, detail: str, conflict: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.conflict = conflict


def _slot_order_key(row) -> tuple:
    return (row[2] is None, row[2] or 0, row[0])


def roster_layout(db, user_id: int, roster_limit: int) -> tuple[list, list[int]]:
    """(active, bench) as the My Team page shows the editable week: active is one entry
    per roster slot (card id or None), bench the card ids in order. Cards of removed
    players are left out, as GET /roster leaves them out. An active card without a
    usable slot_index takes the first free slot, as the page places it."""
    rows = db.execute(text("""
        SELECT c.id, c.is_active, c.slot_index FROM cards c
        JOIN players p ON p.id = c.player_id
        WHERE c.owner_id = :user_id AND p.is_active = 1
    """), {"user_id": user_id}).fetchall()
    active_rows = sorted((r for r in rows if r[1]), key=_slot_order_key)
    bench = [r[0] for r in sorted((r for r in rows if not r[1]), key=_slot_order_key)]
    slots: list = [None] * roster_limit
    unplaced = []
    for r in active_rows:
        si = r[2]
        if si is not None and 0 <= si < roster_limit and slots[si] is None:
            slots[si] = r[0]
        else:
            unplaced.append(r[0])
    for cid in unplaced:
        if None not in slots:
            slots.append(cid)
        else:
            slots[slots.index(None)] = cid
    return slots, bench


def layout_version(active: list, bench: list[int]) -> str:
    """SHA-256 of "active:<ids>|bench:<ids>", first 16 hex characters. Active ids are in
    slot order with "-" for an empty slot; trailing empty slots are left out."""
    slots = list(active)
    while slots and slots[-1] is None:
        slots.pop()
    a = ",".join("-" if cid is None else str(int(cid)) for cid in slots)
    b = ",".join(str(int(cid)) for cid in bench)
    return hashlib.sha256(f"active:{a}|bench:{b}".encode()).hexdigest()[:16]


def roster_version(db, user_id: int, roster_limit: int = 5) -> str:
    """Version of the user's stored roster layout (see layout_version)."""
    return layout_version(*roster_layout(db, user_id, roster_limit))


def apply_roster_layout(db, user_id: int, active: list, bench: list[int], base_version: str,
                        roster_limit: int) -> bool:
    """Check and write a whole roster layout in the caller's transaction. Returns True
    when rows were written, False for a layout identical to the stored one. Raises
    RosterLayoutError (nothing written; the caller rolls back) when a check fails.

    The first statement is a no-op UPDATE that takes SQLite's write lock, so the version
    read next can't change before the writes below: of two saves from the same base,
    the second waits here and then sees the first one's version. Every card not listed
    as active is benched (slot_index NULL) before any card is activated, so the
    one-active-card-per-player index (ux_cards_owner_player_active, #185) holds after
    every statement; the listed bench cards then get their order."""
    db.execute(text("UPDATE users SET tokens = tokens WHERE id = :user_id"), {"user_id": user_id})
    if roster_version(db, user_id, roster_limit) != base_version:
        raise RosterLayoutError(409, ROSTER_VERSION_DETAIL, ROSTER_VERSION_CONFLICT)

    active_ids = [cid for cid in active if cid is not None]
    all_ids = active_ids + list(bench)
    if len(set(all_ids)) != len(all_ids):
        raise RosterLayoutError(409, ROSTER_DUPLICATE_ID_DETAIL)
    if len(active) > roster_limit:
        raise RosterLayoutError(409, f"Roster full ({roster_limit} cards max)")

    owned = {}
    if all_ids:
        rows = db.execute(text("""
            SELECT c.id, c.player_id, p.is_active FROM cards c
            JOIN players p ON p.id = c.player_id
            WHERE c.owner_id = :user_id AND c.id IN :ids
        """).bindparams(bindparam("ids", expanding=True)),
            {"user_id": user_id, "ids": all_ids}).fetchall()
        owned = {r[0]: (r[1], bool(r[2])) for r in rows}
    if any(cid not in owned for cid in all_ids):
        raise RosterLayoutError(404, "Card not found")
    active_players = [owned[cid][0] for cid in active_ids]
    if len(set(active_players)) != len(active_players):
        raise RosterLayoutError(409, "A card for this player is already active")
    if any(not owned[cid][1] for cid in active_ids):
        raise RosterLayoutError(409, ROSTER_REMOVED_PLAYER_DETAIL)

    if layout_version(active, bench) == base_version:
        return False

    if active_ids:
        db.execute(text("""
            UPDATE cards SET is_active = 0, slot_index = NULL
            WHERE owner_id = :user_id AND id NOT IN :ids
        """).bindparams(bindparam("ids", expanding=True)), {"user_id": user_id, "ids": active_ids})
    else:
        db.execute(text("UPDATE cards SET is_active = 0, slot_index = NULL "
                        "WHERE owner_id = :user_id"), {"user_id": user_id})
    for slot, cid in enumerate(active):
        if cid is not None:
            db.execute(text("UPDATE cards SET is_active = 1, slot_index = :slot "
                            "WHERE id = :cid AND owner_id = :user_id"),
                       {"slot": slot, "cid": cid, "user_id": user_id})
    for pos, cid in enumerate(bench):
        db.execute(text("UPDATE cards SET is_active = 0, slot_index = :pos "
                        "WHERE id = :cid AND owner_id = :user_id"),
                   {"pos": pos, "cid": cid, "user_id": user_id})
    return True
