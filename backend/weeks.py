import datetime
import os
import time

from models import Card, User, Week, WeeklyRosterEntry

_SECS_PER_WEEK = 7 * 24 * 3600


def _parse_season_lock_anchor() -> int:
    """Return Unix timestamp for SEASON_LOCK_START 23:59:59 UTC.

    This is the first Sunday lock. Week 1's match window opens immediately
    after (Monday 00:00:00 UTC) and runs through the following Sunday 23:59:59.
    """
    start_str = os.getenv("SEASON_LOCK_START", "2026-03-08")
    d = datetime.datetime.strptime(start_str, "%Y-%m-%d")
    anchor = datetime.datetime(d.year, d.month, d.day, 23, 59, 59,
                               tzinfo=datetime.timezone.utc)
    return int(anchor.timestamp())


def generate_weeks(db):
    """Insert missing Week rows from SEASON_LOCK_START through 4 Sundays ahead.

    Week N covers the match window that opens after the Nth lock:
      start = anchor + (N-1)*7d + 1s   (Monday 00:00:00 UTC)
      end   = anchor + N*7d             (Sunday 23:59:59 UTC)

    The roster for Week N is locked when start_time passes.
    """
    anchor = _parse_season_lock_anchor()
    now = int(time.time())
    future_limit = now + 4 * _SECS_PER_WEEK

    existing_starts = {w.start_time for w in db.query(Week).all()}

    week_num = 1
    while True:
        start = anchor + (week_num - 1) * _SECS_PER_WEEK + 1
        end   = anchor +  week_num      * _SECS_PER_WEEK

        if start > future_limit:
            break

        if start not in existing_starts:
            db.add(Week(label=f"Week {week_num}", start_time=start, end_time=end,
                        is_locked=False))
            print(f"[WEEKS] Generated Week {week_num} ({start}–{end})")

        week_num += 1
        if end > future_limit:
            break

    db.commit()


def _snapshot_week(db, week: Week):
    """Snapshot current active rosters into WeeklyRosterEntry for this week."""
    users = db.query(User).all()
    for user in users:
        existing = db.query(WeeklyRosterEntry).filter_by(
            week_id=week.id, user_id=user.id
        ).first()
        if existing:
            continue
        active_cards = db.query(Card).filter_by(owner_id=user.id, is_active=True).all()
        for card in active_cards:
            db.add(WeeklyRosterEntry(week_id=week.id, user_id=user.id, card_id=card.id))


def auto_lock_weeks(db):
    """Snapshot and lock all weeks whose match window has opened. Idempotent.

    A week is locked as soon as its start_time passes — before any matches
    can contribute points — so users cannot react to results mid-week.
    """
    now = int(time.time())
    unlocked = (
        db.query(Week)
        .filter(Week.start_time <= now, Week.is_locked == False)  # noqa: E712
        .all()
    )
    for week in unlocked:
        _snapshot_week(db, week)
        week.is_locked = True
        print(f"[WEEKS] Locked {week.label}")
    if unlocked:
        db.commit()


def get_current_week(db):
    """Return the Week whose match window contains the current moment, or None."""
    now = int(time.time())
    return (
        db.query(Week)
        .filter(Week.start_time <= now, Week.end_time >= now)
        .first()
    )


def get_next_editable_week(db):
    """Return the earliest week that hasn't started yet (roster still editable)."""
    now = int(time.time())
    return (
        db.query(Week)
        .filter(Week.start_time > now)
        .order_by(Week.start_time)
        .first()
    )
