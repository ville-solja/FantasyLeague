import logging

import clock
from models import AuditLog, Card, User, Week, WeeklyRosterEntry, WeeklySummary

logger = logging.getLogger(__name__)


def _snapshot_week(db, week: Week):
    """Snapshot current active rosters into WeeklyRosterEntry for this week."""
    already_snapshotted = {
        r[0] for r in
        db.query(WeeklyRosterEntry.user_id).filter_by(week_id=week.id).all()
    }
    active_cards = (
        db.query(Card)
        .filter(Card.is_active == True, Card.owner_id.isnot(None))  # noqa: E712
        .all()
    )
    for card in active_cards:
        if card.owner_id in already_snapshotted:
            continue
        db.add(WeeklyRosterEntry(week_id=week.id, user_id=card.owner_id, card_id=card.id))


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
    """Return the Week whose match window contains the current moment, or None."""
    now = clock.now(db)
    return (
        db.query(Week)
        .filter(Week.start_time <= now, Week.end_time >= now)
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
