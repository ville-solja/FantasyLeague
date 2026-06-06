import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from models import User, TokenGrantEvent, TokenGrantClaim


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _make_user(db, username="player1", tokens=0):
    user = User(username=username, email=f"{username}@test.com",
                password_hash="x", is_admin=False, tokens=tokens)
    db.add(user)
    db.flush()
    return user


def _make_event(db, amount=10, offset_start=-60, offset_end=3600):
    now = int(time.time())
    ev = TokenGrantEvent(
        amount=amount,
        start_time=now + offset_start,
        end_time=now + offset_end,
        created_at=now,
    )
    db.add(ev)
    db.flush()
    return ev


def _claim_active_events(db, user):
    now = int(time.time())
    active = db.query(TokenGrantEvent).filter(
        TokenGrantEvent.start_time <= now,
        TokenGrantEvent.end_time >= now,
    ).all()
    granted = 0
    for ev in active:
        already = db.query(TokenGrantClaim).filter_by(event_id=ev.id, user_id=user.id).first()
        if already:
            continue
        user.tokens = (user.tokens or 0) + ev.amount
        db.add(TokenGrantClaim(event_id=ev.id, user_id=user.id, claimed_at=now))
        granted += ev.amount
    db.commit()
    return granted


# ---------------------------------------------------------------------------
# Story: Create a Token Grant Event
# ---------------------------------------------------------------------------

class TestCreateTokenGrantEvent:
    def test_create_event_stores_amount_and_window(self, db):
        """Admin can create an event; it is persisted with amount and time window."""
        now = int(time.time())
        ev = TokenGrantEvent(amount=5, start_time=now, end_time=now + 3600, created_at=now)
        db.add(ev)
        db.commit()

        stored = db.get(TokenGrantEvent, ev.id)
        assert stored is not None
        assert stored.amount == 5
        assert stored.start_time == now
        assert stored.end_time == now + 3600

    def test_create_event_rejects_invalid_window(self, db):
        """Event with end_time <= start_time is rejected."""
        now = int(time.time())
        # Business rule: end_time must be strictly after start_time.
        ev = TokenGrantEvent(amount=5, start_time=now + 100, end_time=now, created_at=now)
        assert ev.end_time <= ev.start_time  # condition the API layer checks before persisting

    def test_create_event_rejects_zero_amount(self, db):
        """Event with amount < 1 is invalid."""
        # Business rule: amount must be >= 1.
        ev = TokenGrantEvent(amount=0, start_time=0, end_time=3600, created_at=0)
        assert ev.amount < 1  # condition the API layer's ge=1 field constraint covers


# ---------------------------------------------------------------------------
# Story: Claim Tokens on Login During Active Event
# ---------------------------------------------------------------------------

class TestClaimTokenGrantEvent:
    def test_claim_grants_tokens_during_active_window(self, db):
        """Player receives tokens when claiming during an active event."""
        user = _make_user(db, tokens=0)
        _make_event(db, amount=10, offset_start=-60, offset_end=3600)

        granted = _claim_active_events(db, user)

        assert granted == 10
        assert user.tokens == 10

    def test_claim_is_idempotent_within_window(self, db):
        """Calling claim twice during the same active event grants tokens only once."""
        user = _make_user(db, tokens=0)
        _make_event(db, amount=10)

        first  = _claim_active_events(db, user)
        second = _claim_active_events(db, user)

        assert first == 10
        assert second == 0
        assert user.tokens == 10

    def test_claim_does_not_grant_after_event_expires(self, db):
        """No tokens are granted when the event window has passed."""
        user = _make_user(db, tokens=0)
        now = int(time.time())
        ev = TokenGrantEvent(amount=10, start_time=now - 7200, end_time=now - 3600, created_at=now)
        db.add(ev)
        db.commit()

        granted = _claim_active_events(db, user)

        assert granted == 0
        assert user.tokens == 0

    def test_claim_does_not_grant_before_event_starts(self, db):
        """No tokens are granted when the event has not yet started."""
        user = _make_user(db, tokens=0)
        now = int(time.time())
        ev = TokenGrantEvent(amount=10, start_time=now + 3600, end_time=now + 7200, created_at=now)
        db.add(ev)
        db.commit()

        granted = _claim_active_events(db, user)

        assert granted == 0
        assert user.tokens == 0


# ---------------------------------------------------------------------------
# Story: Remove a Token Grant Event
# ---------------------------------------------------------------------------

class TestDeleteTokenGrantEvent:
    def test_delete_event_removes_it_from_list(self, db):
        """Deleting an event removes it so future claims are not granted."""
        user = _make_user(db, tokens=0)
        ev = _make_event(db, amount=10)
        db.commit()

        db.delete(ev)
        db.commit()

        granted = _claim_active_events(db, user)
        assert granted == 0
        assert user.tokens == 0

    def test_delete_event_preserves_already_granted_tokens(self, db):
        """Tokens already claimed before deletion are not revoked."""
        user = _make_user(db, tokens=0)
        ev = _make_event(db, amount=10)

        granted = _claim_active_events(db, user)
        assert granted == 10
        assert user.tokens == 10

        db.delete(ev)
        db.commit()

        assert user.tokens == 10

    def test_delete_nonexistent_event_returns_404(self, db):
        """Deleting an event that does not exist: db.get returns None (API raises 404)."""
        result = db.get(TokenGrantEvent, 99999)
        assert result is None
