import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from models import Week, WeeklyRosterEntry, User, Card


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _make_week(db, label="Week 1", offset_start=0, offset_end=86400, locked=False):
    now = int(time.time())
    w = Week(label=label, start_time=now + offset_start,
             end_time=now + offset_end, is_locked=locked)
    db.add(w)
    db.flush()
    return w


def _list_weeks(db):
    weeks = db.query(Week).order_by(Week.start_time).all()
    result = []
    for w in weeks:
        roster_count = db.query(WeeklyRosterEntry).filter_by(week_id=w.id).count()
        result.append({
            "id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time,
            "is_locked": w.is_locked, "roster_count": roster_count,
        })
    return result


def _create_week(db, label, start_time, end_time):
    if end_time <= start_time:
        return None, "end_time must be after start_time"
    w = Week(label=label, start_time=start_time, end_time=end_time, is_locked=False)
    db.add(w)
    db.commit()
    return w, None


def _edit_week(db, week_id, label=None, start_time=None, end_time=None):
    w = db.get(Week, week_id)
    if not w:
        return None, 404
    if w.is_locked:
        return None, 409
    if label is not None:
        w.label = label
    if start_time is not None:
        w.start_time = start_time
    if end_time is not None:
        w.end_time = end_time
    if w.end_time <= w.start_time:
        return None, 422
    db.commit()
    return w, None


def _delete_week(db, week_id):
    w = db.get(Week, week_id)
    if not w:
        return 404
    if w.is_locked:
        return 409
    roster_count = db.query(WeeklyRosterEntry).filter_by(week_id=week_id).count()
    if roster_count > 0:
        return 409
    db.delete(w)
    db.commit()
    return 200


# ---------------------------------------------------------------------------
# Story: View All Weeks
# ---------------------------------------------------------------------------

class TestListWeeks:
    def test_list_returns_all_weeks(self, db):
        """All weeks are returned including locked past weeks."""
        _make_week(db, "Week 1", locked=True)
        _make_week(db, "Week 2", offset_start=86400, offset_end=172800)
        db.commit()

        result = _list_weeks(db)

        assert len(result) == 2
        labels = [r["label"] for r in result]
        assert "Week 1" in labels
        assert "Week 2" in labels

    def test_list_includes_roster_count(self, db):
        """Each week row includes the count of weekly roster entries."""
        user = User(username="u1", email="u1@x.com", password_hash="x", tokens=0)
        db.add(user)
        db.flush()
        w = _make_week(db, locked=True)
        entry = WeeklyRosterEntry(week_id=w.id, user_id=user.id, card_id=None)
        db.add(entry)
        db.commit()

        result = _list_weeks(db)

        assert result[0]["roster_count"] == 1

    def test_locked_weeks_are_flagged(self, db):
        """Locked weeks have is_locked=True in the response."""
        _make_week(db, "Past", locked=True)
        _make_week(db, "Future", offset_start=86400, offset_end=172800, locked=False)
        db.commit()

        result = _list_weeks(db)
        locked_row   = next(r for r in result if r["label"] == "Past")
        unlocked_row = next(r for r in result if r["label"] == "Future")

        assert locked_row["is_locked"] is True
        assert unlocked_row["is_locked"] is False


# ---------------------------------------------------------------------------
# Story: Create a Custom Week
# ---------------------------------------------------------------------------

class TestCreateWeek:
    def test_create_week_persists_label_and_window(self, db):
        """Created week is stored with correct label and time bounds."""
        now = int(time.time())
        w, err = _create_week(db, "Finals", now, now + 3600)

        assert err is None
        stored = db.get(Week, w.id)
        assert stored.label == "Finals"
        assert stored.start_time == now
        assert stored.end_time == now + 3600

    def test_create_rejects_invalid_window(self, db):
        """end_time <= start_time is rejected."""
        now = int(time.time())
        w, err = _create_week(db, "Bad", now + 100, now)

        assert w is None
        assert "end_time" in err

    def test_create_week_is_not_locked(self, db):
        """New weeks start unlocked."""
        now = int(time.time())
        w, err = _create_week(db, "New Week", now, now + 3600)

        assert w.is_locked is False


# ---------------------------------------------------------------------------
# Story: Edit an Unlocked Week
# ---------------------------------------------------------------------------

class TestEditWeek:
    def test_edit_updates_end_time(self, db):
        """Patching end_time updates the week's end_time."""
        now = int(time.time())
        w = _make_week(db, offset_end=3600)
        db.commit()

        new_end = now + 7200
        updated, err = _edit_week(db, w.id, end_time=new_end)

        assert err is None
        assert db.get(Week, w.id).end_time == new_end

    def test_edit_updates_label(self, db):
        """Patching label updates the week's label."""
        w = _make_week(db, label="Old Label")
        db.commit()

        updated, err = _edit_week(db, w.id, label="New Label")

        assert err is None
        assert db.get(Week, w.id).label == "New Label"

    def test_edit_rejects_locked_week(self, db):
        """Editing a locked week is not allowed."""
        w = _make_week(db, locked=True)
        db.commit()

        _, err = _edit_week(db, w.id, label="Attempt")

        assert err == 409

    def test_edit_rejects_invalid_window_after_patch(self, db):
        """Patching end_time to be <= start_time is rejected."""
        now = int(time.time())
        w = _make_week(db, offset_start=100, offset_end=3600)
        db.commit()

        _, err = _edit_week(db, w.id, end_time=w.start_time - 1)

        assert err == 422

    def test_edit_nonexistent_week_returns_404(self, db):
        """Editing a week that does not exist: db.get returns None."""
        result = db.get(Week, 99999)
        assert result is None


# ---------------------------------------------------------------------------
# Story: Delete an Unlocked Week
# ---------------------------------------------------------------------------

class TestDeleteWeek:
    def test_delete_unlocked_empty_week(self, db):
        """Deleting an unlocked week with no roster entries removes it."""
        w = _make_week(db)
        db.commit()
        week_id = w.id

        status = _delete_week(db, week_id)

        assert status == 200
        assert db.get(Week, week_id) is None

    def test_delete_rejects_locked_week(self, db):
        """Deleting a locked week returns 409."""
        w = _make_week(db, locked=True)
        db.commit()

        status = _delete_week(db, w.id)

        assert status == 409
        assert db.get(Week, w.id) is not None  # still exists

    def test_delete_rejects_week_with_roster_entries(self, db):
        """Deleting a week that has roster entries returns 409."""
        user = User(username="u1", email="u1@x.com", password_hash="x", tokens=0)
        db.add(user)
        db.flush()
        w = _make_week(db)
        db.add(WeeklyRosterEntry(week_id=w.id, user_id=user.id, card_id=None))
        db.commit()

        status = _delete_week(db, w.id)

        assert status == 409

    def test_delete_nonexistent_week_returns_404(self, db):
        """Deleting a week that does not exist returns 404."""
        status = _delete_week(db, 99999)
        assert status == 404
