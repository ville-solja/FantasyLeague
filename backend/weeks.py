import logging
import os

from sqlalchemy import text

import clock
from match_scoring import scored_match_sql
from models import AuditLog, Card, Player, User, Week, WeeklyRosterEntry, WeeklySummary

logger = logging.getLogger(__name__)


def substitution_delay_hours() -> float:
    """Hours after a week's end_time before its bench substitutions run (issue #129)."""
    return float(os.getenv("SUBSTITUTION_DELAY_HOURS", "24"))


def substitution_time(week: Week) -> int:
    """Timestamp from which the week's substitutions may run."""
    return int(week.end_time + substitution_delay_hours() * 3600)


def _slot_order(card: Card):
    return (card.slot_index is None, card.slot_index or 0, card.id)


def _snapshot_week(db, week: Week):
    """Snapshot current rosters into WeeklyRosterEntry for this week: active cards
    (is_bench=0, inserted in roster slot order) and the bench of active players
    (is_bench=1, bench_order 0..n in My Team's bench order)."""
    already_snapshotted = {
        r[0] for r in
        db.query(WeeklyRosterEntry.user_id).filter_by(week_id=week.id).all()
    }
    active_cards = (
        db.query(Card)
        .filter(Card.is_active == True, Card.owner_id.isnot(None))  # noqa: E712
        .all()
    )
    bench_cards = (
        db.query(Card)
        .join(Player, Player.id == Card.player_id)
        .filter(Card.is_active == False, Card.owner_id.isnot(None),  # noqa: E712
                Player.is_active == True)  # noqa: E712
        .all()
    )
    for card in sorted(active_cards, key=_slot_order):
        if card.owner_id in already_snapshotted:
            continue
        db.add(WeeklyRosterEntry(week_id=week.id, user_id=card.owner_id, card_id=card.id,
                                 is_bench=False))
    bench_by_user: dict[int, list[Card]] = {}
    for card in bench_cards:
        if card.owner_id in already_snapshotted:
            continue
        bench_by_user.setdefault(card.owner_id, []).append(card)
    for user_id, cards in bench_by_user.items():
        for order, card in enumerate(sorted(cards, key=_slot_order)):
            db.add(WeeklyRosterEntry(week_id=week.id, user_id=user_id, card_id=card.id,
                                     is_bench=True, bench_order=order))


def _players_who_played(db, week: Week) -> set[int]:
    """Players with at least one scored match in the week's window."""
    rows = db.execute(text(f"""
        SELECT DISTINCT s.player_id
        FROM player_match_stats s
        JOIN matches m ON m.match_id = s.match_id AND {scored_match_sql()}
        WHERE m.week_override_id = :week_id
           OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we)
    """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time}).fetchall()
    return {r[0] for r in rows}


def run_substitutions(db, week: Week) -> int:
    """Reset and recompute the week's bench substitutions. Returns the number made.

    Active cards are checked in roster slot order; each whose player played no scored
    match in the week is marked subbed_out, and the first bench card (bench_order)
    whose player played, that isn't already subbed in and whose player isn't already
    counted, is marked subbed_in. A week with no bench rows (locked before bench
    snapshots existed) is left unchanged. Caller commits."""
    entries = (
        db.query(WeeklyRosterEntry)
        .filter(WeeklyRosterEntry.week_id == week.id)
        .order_by(WeeklyRosterEntry.id)
        .all()
    )
    for e in entries:
        e.subbed_in = False
        e.subbed_out = False
        e.subbed_for_entry_id = None

    count = 0
    if any(e.is_bench for e in entries):
        played = _players_who_played(db, week)
        card_ids = {e.card_id for e in entries}
        player_of = {
            cid: pid for cid, pid in
            db.query(Card.id, Card.player_id).filter(Card.id.in_(card_ids)).all()
        } if card_ids else {}
        by_user: dict[int, list[WeeklyRosterEntry]] = {}
        for e in entries:
            by_user.setdefault(e.user_id, []).append(e)
        for user_entries in by_user.values():
            active = [e for e in user_entries if not e.is_bench]
            bench = sorted((e for e in user_entries if e.is_bench),
                           key=lambda e: (e.bench_order is None, e.bench_order or 0, e.id))
            counted = {player_of.get(e.card_id) for e in active
                       if player_of.get(e.card_id) in played}
            for entry in active:
                if player_of.get(entry.card_id) in played:
                    continue
                entry.subbed_out = True
                for sub in bench:
                    pid = player_of.get(sub.card_id)
                    if sub.subbed_in or pid not in played or pid in counted:
                        continue
                    sub.subbed_in = True
                    sub.subbed_for_entry_id = entry.id
                    counted.add(pid)
                    count += 1
                    break

    now = clock.now(db)
    week.substitutions_at = int(now)
    db.add(AuditLog(
        timestamp=int(now),
        actor_id=None,
        actor_username="system",
        action="weekly_substitutions",
        detail=f"week={week.label} id={week.id} substitutions={count}",
    ))
    db.flush()
    logger.info("Bench substitutions for %s: %d", week.label, count)
    return count


def due_substitutions(db) -> int:
    """Run substitutions once for every locked week whose end_time + delay has passed.
    Returns the number of weeks processed."""
    now = clock.now(db)
    delay = int(substitution_delay_hours() * 3600)
    due = (
        db.query(Week)
        .filter(Week.is_locked == True,  # noqa: E712
                Week.substitutions_at.is_(None),
                Week.end_time + delay <= now)
        .order_by(Week.start_time)
        .all()
    )
    for week in due:
        run_substitutions(db, week)
    if due:
        db.commit()
    return len(due)


def auto_lock_weeks(db):
    """Snapshot and lock all weeks whose match window has opened. Idempotent.

    A week is locked as soon as its start_time passes — before any matches
    can contribute points — so users cannot react to results mid-week.
    """
    now = clock.now(db)
    unlocked = (
        db.query(Week)
        .filter(Week.start_time <= now, Week.is_locked == False)  # noqa: E712
        .all()
    )
    for week in unlocked:
        _snapshot_week(db, week)
        week.is_locked = True
        logger.info("Locked %s", week.label)
    if unlocked:
        users = db.query(User).all()
        for u in users:
            u.tokens = (u.tokens or 0) + 1
        week_labels = ", ".join(w.label for w in unlocked)
        db.add(AuditLog(
            timestamp=int(now),
            actor_id=None,
            actor_username="system",
            action="weekly_token_grant",
            detail=f"weeks={week_labels} users={len(users)}",
        ))
        logger.info("Granted 1 token to %d users (weeks: %s)", len(users), week_labels)
        db.commit()  # single commit: snapshot + lock flag + token grants


def generate_weekly_summaries(db):
    """Mark weeks whose scoring window has closed as available in the Weekly
    Report. Idempotent and driven by end_time (same grace-period boundary
    auto_lock_weeks uses), not a fixed calendar schedule — applies uniformly
    to regular weeks and irregular ones (e.g. a compressed finals week).
    """
    now = clock.now(db)
    already = {r[0] for r in db.query(WeeklySummary.week_id).all()}
    query = db.query(Week).filter(Week.end_time <= now)
    if already:
        query = query.filter(~Week.id.in_(already))
    newly_ready = query.all()
    for week in newly_ready:
        db.add(WeeklySummary(week_id=week.id, generated_at=int(now)))
        logger.info("Weekly summary available for %s", week.label)
    if newly_ready:
        db.commit()


def get_current_week(db):
    """Return the Week whose match window contains the current moment, or None.
    If more than one week's range contains it (a legacy overlap predating the
    overlap guard — see plan-issue-84's Story 4), the most recently started wins."""
    now = clock.now(db)
    return (
        db.query(Week)
        .filter(Week.start_time <= now, Week.end_time >= now)
        .order_by(Week.start_time.desc())
        .first()
    )


def get_next_editable_week(db):
    """Return the earliest week that hasn't started yet (roster still editable)."""
    now = clock.now(db)
    return (
        db.query(Week)
        .filter(Week.start_time > now)
        .order_by(Week.start_time)
        .first()
    )
