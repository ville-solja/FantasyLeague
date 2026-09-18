"""Tests for plan-issue-125-roster-limit-race-fix.

Covers the two user stories in markdown/plans/plan-issue-125-roster-limit-race-fix.md:

1. Atomic Roster Activation Limit Enforcement (`activate_card` in
   backend/routers/cards.py, backed by a new `_activate_card_atomic()` helper
   in backend/card_utils.py).
2. Atomic Duplicate-Player Guard on Roster Swap (`swap_roster` in
   backend/routers/cards.py, backed by a new `_swap_roster_atomic()` helper
   in backend/card_utils.py).

--- Note on concurrency-test mechanics ---
The `db` fixture below uses `create_engine("sqlite:///:memory:")` without
`StaticPool`, so each new connection off that engine gets its OWN private
in-memory database — it is NOT shared across threads/connections. The two
concurrency tests below use a separate `file_db_sessionmaker` fixture: a real
on-disk temp-file SQLite database (via `tmp_path`), with each concurrent
"request" running in its own thread using its own `Session` bound to that
same file (via `concurrent.futures.ThreadPoolExecutor`), each thread calling
the real router function end-to-end. Only a shared on-disk file + real
threads surfaces the race the plan describes (~40 active cards observed in
production off a single stale count).
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database import Base
from models import Card, Player, User


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def file_db_sessionmaker(tmp_path):
    """A shared on-disk SQLite DB + sessionmaker for tests that need to exercise
    a real race across threads. Each caller should open its own Session from
    this factory rather than sharing one Session across threads (SQLAlchemy
    Sessions are not thread-safe)."""
    db_path = tmp_path / "race.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    yield SessionFactory
    engine.dispose()


def _make_user(db, tokens=10, username="tester", email="t@t.com"):
    u = User(username=username, email=email, password_hash="x", tokens=tokens)
    db.add(u)
    db.flush()
    return u


def _make_player(db, player_id=10, name="PlayerOne"):
    p = Player(id=player_id, name=name)
    db.add(p)
    db.flush()
    return p


def _make_card(db, owner_id, player_id, is_active=False, card_type="common", slot_index=None):
    c = Card(owner_id=owner_id, player_id=player_id, card_type=card_type,
              league_id=None, is_active=is_active, generation=1, slot_index=slot_index)
    db.add(c)
    db.flush()
    return c


# ---------------------------------------------------------------------------
# Story: Atomic Roster Activation Limit Enforcement
# ---------------------------------------------------------------------------

class TestAtomicRosterActivationLimitEnforcement:

    def test_concurrent_activate_requests_never_exceed_roster_limit(self, file_db_sessionmaker):
        """Firing many concurrent POST /roster/{card_id}/activate requests for the
        same user against distinct bench cards must never result in more than
        ROSTER_LIMIT active cards, regardless of how many requests race.
        """
        from routers.cards import activate_card, ROSTER_LIMIT

        SessionFactory = file_db_sessionmaker
        setup = SessionFactory()
        user = _make_user(setup)
        num_bench = ROSTER_LIMIT + 10
        card_ids = []
        for i in range(num_bench):
            player = _make_player(setup, player_id=1000 + i, name=f"Bench{i}")
            card = _make_card(setup, user.id, player.id, is_active=False)
            card_ids.append(card.id)
        setup.commit()
        user_id = user.id
        setup.close()

        def _activate(card_id):
            session = SessionFactory()
            try:
                activate_card(card_id, session, {"user_id": user_id})
                return True
            except HTTPException:
                return False
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=num_bench) as pool:
            results = list(pool.map(_activate, card_ids))

        verify = SessionFactory()
        try:
            active_count = verify.query(Card).filter(
                Card.owner_id == user_id, Card.is_active == True  # noqa: E712
            ).count()
        finally:
            verify.close()

        assert active_count <= ROSTER_LIMIT
        assert active_count == ROSTER_LIMIT  # more bench cards than room were seeded
        assert sum(1 for r in results if r) == active_count

    def test_single_activate_request_succeeds_when_under_limit(self, db):
        """A single, sequential activate request on a bench card succeeds (200
        equivalent / no exception) and sets is_active=True when the user is
        under ROSTER_LIMIT."""
        from routers.cards import activate_card

        user = _make_user(db)
        player = _make_player(db)
        card = _make_card(db, user.id, player.id, is_active=False)

        result = activate_card(card.id, db, {"user_id": user.id})

        db.refresh(card)
        assert card.is_active is True
        assert result == {"status": "ok", "card_id": card.id}

    def test_single_activate_request_returns_404_for_missing_card(self, db):
        """Activating a card_id that does not exist raises HTTPException 404."""
        from routers.cards import activate_card

        user = _make_user(db)

        with pytest.raises(HTTPException) as exc_info:
            activate_card(999999, db, {"user_id": user.id})
        assert exc_info.value.status_code == 404

    def test_single_activate_request_returns_404_for_foreign_card(self, db):
        """Activating a card owned by a different user raises HTTPException 404."""
        from routers.cards import activate_card

        owner = _make_user(db, username="owner", email="owner@t.com")
        other = _make_user(db, username="other", email="other@t.com")
        player = _make_player(db)
        card = _make_card(db, owner.id, player.id, is_active=False)

        with pytest.raises(HTTPException) as exc_info:
            activate_card(card.id, db, {"user_id": other.id})
        assert exc_info.value.status_code == 404

    def test_single_activate_request_returns_409_when_already_active(self, db):
        """Activating a card that is already active raises HTTPException 409
        with detail 'Card already active'."""
        from routers.cards import activate_card

        user = _make_user(db)
        player = _make_player(db)
        card = _make_card(db, user.id, player.id, is_active=True)

        with pytest.raises(HTTPException) as exc_info:
            activate_card(card.id, db, {"user_id": user.id})
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "Card already active"

    def test_single_activate_request_returns_409_when_roster_full(self, db):
        """Activating a bench card when the user already has ROSTER_LIMIT active
        cards raises HTTPException 409 with detail 'Roster full ({N} cards
        max)'."""
        from routers.cards import activate_card, ROSTER_LIMIT

        user = _make_user(db)
        for i in range(ROSTER_LIMIT):
            p = _make_player(db, player_id=100 + i, name=f"Active{i}")
            _make_card(db, user.id, p.id, is_active=True)
        bench_player = _make_player(db, player_id=200, name="Bench")
        bench_card = _make_card(db, user.id, bench_player.id, is_active=False)

        with pytest.raises(HTTPException) as exc_info:
            activate_card(bench_card.id, db, {"user_id": user.id})
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == f"Roster full ({ROSTER_LIMIT} cards max)"

    def test_single_activate_request_returns_409_for_duplicate_player(self, db):
        """Activating a bench card whose player already has another active card
        for the same user raises HTTPException 409 with detail 'A card for this
        player is already active'."""
        from routers.cards import activate_card

        user = _make_user(db)
        player = _make_player(db)
        _make_card(db, user.id, player.id, is_active=True)
        bench_card = _make_card(db, user.id, player.id, is_active=False)

        with pytest.raises(HTTPException) as exc_info:
            activate_card(bench_card.id, db, {"user_id": user.id})
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "A card for this player is already active"

    def test_activate_success_response_shape_unchanged(self, db):
        """A successful activation still returns exactly
        {"status": "ok", "card_id": <id>} — the atomic-helper rewrite must not
        change the response shape."""
        from routers.cards import activate_card

        user = _make_user(db)
        player = _make_player(db)
        card = _make_card(db, user.id, player.id, is_active=False)

        result = activate_card(card.id, db, {"user_id": user.id})

        assert result == {"status": "ok", "card_id": card.id}
        assert set(result.keys()) == {"status", "card_id"}


# ---------------------------------------------------------------------------
# Story: Atomic Duplicate-Player Guard on Roster Swap
# ---------------------------------------------------------------------------

class TestAtomicDuplicatePlayerGuardOnRosterSwap:

    def test_concurrent_swap_requests_never_result_in_duplicate_active_player(self, file_db_sessionmaker):
        """Firing concurrent POST /roster/swap requests that could both pass a
        naive read-then-write duplicate-player check (two bench cards for the
        same player racing to fill one active slot) must never result in two
        active cards for that player.
        """
        from routers.cards import swap_roster, SwapRequest

        SessionFactory = file_db_sessionmaker
        setup = SessionFactory()
        user = _make_user(setup)
        other_player = _make_player(setup, player_id=2000, name="ActivePlayer")
        shared_player = _make_player(setup, player_id=2001, name="SharedPlayer")
        active_card = _make_card(setup, user.id, other_player.id, is_active=True, slot_index=0)
        bench1 = _make_card(setup, user.id, shared_player.id, is_active=False)
        bench2 = _make_card(setup, user.id, shared_player.id, is_active=False)
        setup.commit()
        user_id = user.id
        active_card_id = active_card.id
        shared_player_id = shared_player.id
        bench_ids = [bench1.id, bench2.id]
        setup.close()

        def _swap(bench_card_id):
            session = SessionFactory()
            try:
                swap_roster(
                    SwapRequest(bench_card_id=bench_card_id, active_card_id=active_card_id, slot_index=0),
                    {"user_id": user_id}, session,
                )
                return True
            except HTTPException:
                return False
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(_swap, bench_ids))

        verify = SessionFactory()
        try:
            active_for_player = verify.query(Card).filter(
                Card.owner_id == user_id,
                Card.player_id == shared_player_id,
                Card.is_active == True,  # noqa: E712
            ).count()
        finally:
            verify.close()

        assert active_for_player == 1
        assert sum(1 for r in results if r) == 1

    def test_single_swap_request_returns_404_for_missing_bench_card(self, db):
        """Swapping with a bench_card_id that doesn't exist (or isn't owned by
        the user, or isn't actually benched) raises HTTPException 404."""
        from routers.cards import swap_roster, SwapRequest

        user = _make_user(db)
        player = _make_player(db)
        active_card = _make_card(db, user.id, player.id, is_active=True)

        with pytest.raises(HTTPException) as exc_info:
            swap_roster(
                SwapRequest(bench_card_id=999999, active_card_id=active_card.id, slot_index=0),
                {"user_id": user.id}, db,
            )
        assert exc_info.value.status_code == 404

    def test_single_swap_request_returns_404_for_missing_active_card(self, db):
        """Swapping with an active_card_id that doesn't exist (or isn't owned by
        the user, or isn't actually active) raises HTTPException 404."""
        from routers.cards import swap_roster, SwapRequest

        user = _make_user(db)
        player = _make_player(db)
        bench_card = _make_card(db, user.id, player.id, is_active=False)

        with pytest.raises(HTTPException) as exc_info:
            swap_roster(
                SwapRequest(bench_card_id=bench_card.id, active_card_id=999999, slot_index=0),
                {"user_id": user.id}, db,
            )
        assert exc_info.value.status_code == 404

    def test_single_swap_request_returns_409_for_duplicate_player(self, db):
        """Swapping in a bench card whose player already has another active card
        (other than the one being swapped out) raises HTTPException 409 with
        detail 'A card for this player is already active', and leaves both
        cards' is_active state unchanged."""
        from routers.cards import swap_roster, SwapRequest

        user = _make_user(db)
        shared_player = _make_player(db, player_id=10, name="Shared")
        other_player = _make_player(db, player_id=20, name="Other")
        active_card = _make_card(db, user.id, other_player.id, is_active=True, slot_index=0)
        other_active = _make_card(db, user.id, shared_player.id, is_active=True, slot_index=1)
        bench_card = _make_card(db, user.id, shared_player.id, is_active=False)

        with pytest.raises(HTTPException) as exc_info:
            swap_roster(
                SwapRequest(bench_card_id=bench_card.id, active_card_id=active_card.id, slot_index=0),
                {"user_id": user.id}, db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "A card for this player is already active"

        db.refresh(active_card)
        db.refresh(bench_card)
        db.refresh(other_active)
        assert active_card.is_active is True
        assert bench_card.is_active is False
        assert other_active.is_active is True

    def test_single_swap_request_flips_bench_and_active_with_slot_index(self, db):
        """A single, sequential valid swap request deactivates the active card
        (slot_index cleared to None), activates the bench card with the
        requested slot_index, and returns {"ok": True} — unchanged from
        current behavior."""
        from routers.cards import swap_roster, SwapRequest

        user = _make_user(db)
        p1 = _make_player(db, player_id=10, name="P1")
        p2 = _make_player(db, player_id=20, name="P2")
        active_card = _make_card(db, user.id, p1.id, is_active=True, slot_index=3)
        bench_card = _make_card(db, user.id, p2.id, is_active=False)

        result = swap_roster(
            SwapRequest(bench_card_id=bench_card.id, active_card_id=active_card.id, slot_index=3),
            {"user_id": user.id}, db,
        )

        assert result == {"ok": True}
        db.refresh(active_card)
        db.refresh(bench_card)
        assert active_card.is_active is False
        assert active_card.slot_index is None
        assert bench_card.is_active is True
        assert bench_card.slot_index == 3
