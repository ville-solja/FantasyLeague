import time
from unittest.mock import patch

import pytest

from models import AuditLog, Card, User, Week, WeeklyRosterEntry
from weeks import auto_lock_weeks

# Fixed reference instant used across auto-lock tests (arbitrary Sunday 23:59:59 UTC)
_ANCHOR = 1578268799  # int(datetime(2020,1,5,23,59,59, tzinfo=timezone.utc).timestamp())


class TestAutoLockWeeks:
    def _make_past_week(self, db, label="Week 1"):
        past = _ANCHOR - 7 * 24 * 3600
        week = Week(label=label, start_time=past, end_time=past + 7 * 24 * 3600 - 1, is_locked=False)
        db.add(week)
        db.commit()
        return week

    def test_locks_past_weeks(self, db):
        week = self._make_past_week(db)
        with patch("clock.time.time", return_value=_ANCHOR):
            auto_lock_weeks(db)

        db.refresh(week)
        assert week.is_locked is True

    def test_does_not_lock_future_weeks(self, db):
        future_start = int(time.time()) + 7 * 24 * 3600
        week = Week(label="Week 99", start_time=future_start,
                    end_time=future_start + 7 * 24 * 3600, is_locked=False)
        db.add(week)
        db.commit()

        auto_lock_weeks(db)

        db.refresh(week)
        assert week.is_locked is False

    def test_idempotent_second_lock(self, db):
        week = self._make_past_week(db)
        user = User(username="u1", email="u1@test.com", password_hash="x", tokens=0)
        db.add(user)
        db.commit()

        with patch("clock.time.time", return_value=_ANCHOR):
            auto_lock_weeks(db)
            auto_lock_weeks(db)

        db.refresh(user)
        # token granted exactly once despite two calls
        assert user.tokens == 1

    def test_grants_token_to_users(self, db):
        self._make_past_week(db)
        user = User(username="u2", email="u2@test.com", password_hash="x", tokens=5)
        db.add(user)
        db.commit()

        with patch("clock.time.time", return_value=_ANCHOR):
            auto_lock_weeks(db)

        db.refresh(user)
        assert user.tokens == 6

    def test_snapshots_active_roster(self, db):
        week = self._make_past_week(db)
        user = User(username="u3", email="u3@test.com", password_hash="x", tokens=0)
        db.add(user)
        db.commit()

        from models import League, Player
        league = League(id=1, name="TestLeague")
        player = Player(id=999, name="TestPlayer")
        db.add_all([league, player])
        db.commit()

        card = Card(player_id=999, owner_id=user.id, card_type="common", league_id=1, is_active=True)
        db.add(card)
        db.commit()

        with patch("clock.time.time", return_value=_ANCHOR):
            auto_lock_weeks(db)

        entries = db.query(WeeklyRosterEntry).filter_by(week_id=week.id, user_id=user.id).all()
        assert len(entries) == 1
        assert entries[0].card_id == card.id
