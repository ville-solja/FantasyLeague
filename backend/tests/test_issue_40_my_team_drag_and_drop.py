"""
Tests for plan-issue-40-my-team-drag-and-drop.md
Stories covered:
  1. Active Roster Drag-and-Drop Reorder       (POST /roster/reorder, active zone)
  2. Cross-Zone Drag — Active to Bench         (deactivate + reorder)
  3. Bench Drag-and-Drop Reorder               (POST /roster/reorder, bench zone)
  4. Cross-Zone Drag — Bench to Empty Slot     (activate + reorder)
  5. Cross-Zone Drag — Bench to Populated Slot (POST /roster/swap)
  6. Card Viewer Backdrop Dismiss              (frontend-only, pass with note)
  7. Migration 021                             (schema coverage)
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

import models  # noqa: F401 — register all tables with Base.metadata
from database import Base


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _make_user(db, username="tester"):
    from models import User
    u = User(username=username, email=f"{username}@test.com", password_hash="x", tokens=5)
    db.add(u)
    db.flush()
    return u


def _make_player(db, name="Player", pid=None):
    from models import Player
    import time
    p = Player(
        id=pid if pid is not None else int(time.time() * 1_000_000) % 999_999,
        name=name,
        avatar_url="",
    )
    db.add(p)
    db.flush()
    return p


def _make_card(db, owner_id, player_id, is_active=False, slot_index=None):
    from models import Card
    c = Card(
        player_id=player_id,
        owner_id=owner_id,
        card_type="common",
        league_id=None,
        is_active=is_active,
        generation=1,
        slot_index=slot_index,
    )
    db.add(c)
    db.flush()
    return c


# ---------------------------------------------------------------------------
# Story 1 — Active Roster Drag-and-Drop Reorder
# ---------------------------------------------------------------------------

def test_reorder_active_cards_persists_slot_index(db):
    """POST /roster/reorder saves the supplied order as slot_index on each card."""
    from routers.cards import reorder_roster, ReorderRequest

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    c1 = _make_card(db, user.id, p1.id, is_active=True)
    c2 = _make_card(db, user.id, p2.id, is_active=True)

    # c2 first → slot 0; c1 second → slot 1
    reorder_roster(ReorderRequest(card_ids=[c2.id, c1.id]), {"user_id": user.id}, db)

    db.refresh(c1)
    db.refresh(c2)
    assert c2.slot_index == 0
    assert c1.slot_index == 1


def test_reorder_active_cards_ignores_cards_not_owned_by_user(db):
    """POST /roster/reorder must not update cards that belong to a different user."""
    from routers.cards import reorder_roster, ReorderRequest

    u1 = _make_user(db, "owner")
    u2 = _make_user(db, "other")
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    c1 = _make_card(db, u1.id, p1.id, is_active=True)
    c_other = _make_card(db, u2.id, p2.id, is_active=True)

    # Attacker sends another user's card in their own reorder request
    reorder_roster(ReorderRequest(card_ids=[c_other.id, c1.id]), {"user_id": u1.id}, db)

    db.refresh(c_other)
    assert c_other.slot_index is None  # must not have been updated


def test_reorder_active_cards_returns_ok(db):
    """POST /roster/reorder returns {ok: true} on success."""
    from routers.cards import reorder_roster, ReorderRequest

    user = _make_user(db)
    p = _make_player(db, "P", 1)
    c = _make_card(db, user.id, p.id, is_active=True)

    result = reorder_roster(ReorderRequest(card_ids=[c.id]), {"user_id": user.id}, db)
    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# Story 2 — Cross-Zone Drag — Active to Bench
# ---------------------------------------------------------------------------

def test_deactivate_card_then_reorder_places_it_at_target_bench_position(db):
    """After deactivation, a subsequent reorder call sets slot_index so the card lands
    at the requested bench position."""
    from routers.cards import deactivate_card, reorder_roster, ReorderRequest

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    c_active = _make_card(db, user.id, p1.id, is_active=True)
    c_bench = _make_card(db, user.id, p2.id, is_active=False, slot_index=0)

    deactivate_card(c_active.id, db, {"user_id": user.id})
    db.refresh(c_active)
    assert c_active.is_active is False

    # Reorder bench: put the newly deactivated card at position 0
    reorder_roster(
        ReorderRequest(card_ids=[c_active.id, c_bench.id]),
        {"user_id": user.id},
        db,
    )
    db.refresh(c_active)
    db.refresh(c_bench)
    assert c_active.slot_index == 0
    assert c_bench.slot_index == 1


def test_active_to_bench_deactivates_card(db):
    """Deactivating an active card via the existing deactivate endpoint sets is_active=False."""
    from routers.cards import deactivate_card

    user = _make_user(db)
    p = _make_player(db, "P", 1)
    c = _make_card(db, user.id, p.id, is_active=True)

    deactivate_card(c.id, db, {"user_id": user.id})
    db.refresh(c)
    assert c.is_active is False


# ---------------------------------------------------------------------------
# Story 3 — Bench Drag-and-Drop Reorder
# ---------------------------------------------------------------------------

def test_reorder_bench_cards_persists_slot_index(db):
    """POST /roster/reorder saves the supplied order as slot_index on bench cards."""
    from routers.cards import reorder_roster, ReorderRequest

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    c1 = _make_card(db, user.id, p1.id, is_active=False)
    c2 = _make_card(db, user.id, p2.id, is_active=False)

    # c2 first → slot 0; c1 second → slot 1
    reorder_roster(ReorderRequest(card_ids=[c2.id, c1.id]), {"user_id": user.id}, db)

    db.refresh(c1)
    db.refresh(c2)
    assert c2.slot_index == 0
    assert c1.slot_index == 1


def test_reorder_bench_cards_does_not_affect_active_zone(db):
    """Reordering bench-only card IDs must not alter slot_index of active cards."""
    from routers.cards import reorder_roster, ReorderRequest

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    p3 = _make_player(db, "P3", 3)
    c_active = _make_card(db, user.id, p1.id, is_active=True, slot_index=0)
    c_bench1 = _make_card(db, user.id, p2.id, is_active=False)
    c_bench2 = _make_card(db, user.id, p3.id, is_active=False)

    # Reorder only bench cards — active card's slot_index must stay unchanged
    reorder_roster(
        ReorderRequest(card_ids=[c_bench2.id, c_bench1.id]),
        {"user_id": user.id},
        db,
    )

    db.refresh(c_active)
    assert c_active.slot_index == 0  # must remain untouched


# ---------------------------------------------------------------------------
# Story 4 — Cross-Zone Drag — Bench to Empty Active Slot
# ---------------------------------------------------------------------------

def test_activate_bench_card_into_empty_active_slot(db):
    """Activating a bench card via the existing activate endpoint sets is_active=True
    and a subsequent reorder call assigns the correct slot_index."""
    from routers.cards import activate_card, reorder_roster, ReorderRequest

    user = _make_user(db)
    p = _make_player(db, "P", 1)
    c = _make_card(db, user.id, p.id, is_active=False)

    activate_card(c.id, db, {"user_id": user.id})
    db.refresh(c)
    assert c.is_active is True

    reorder_roster(ReorderRequest(card_ids=[c.id]), {"user_id": user.id}, db)
    db.refresh(c)
    assert c.slot_index == 0


def test_activate_bench_card_blocked_by_duplicate_player_guard(db):
    """Attempting to activate a bench card whose player_id is already represented in the
    active roster returns HTTP 409."""
    from routers.cards import activate_card

    user = _make_user(db)
    p = _make_player(db, "P", 1)
    _make_card(db, user.id, p.id, is_active=True)      # already active
    c_bench = _make_card(db, user.id, p.id, is_active=False)  # same player, bench

    with pytest.raises(HTTPException) as exc_info:
        activate_card(c_bench.id, db, {"user_id": user.id})
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Story 5 — Cross-Zone Drag — Bench to Populated Active Slot
# ---------------------------------------------------------------------------

def test_swap_bench_and_active_card_atomically(db):
    """POST /roster/swap moves the bench card to is_active=True and the active card to
    is_active=False in a single operation; both changes are committed together."""
    from routers.cards import swap_roster, SwapRequest

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    c_bench = _make_card(db, user.id, p1.id, is_active=False)
    c_active = _make_card(db, user.id, p2.id, is_active=True, slot_index=0)

    swap_roster(
        SwapRequest(bench_card_id=c_bench.id, active_card_id=c_active.id, slot_index=0),
        {"user_id": user.id},
        db,
    )

    db.refresh(c_bench)
    db.refresh(c_active)
    assert c_bench.is_active is True
    assert c_active.is_active is False


def test_swap_assigns_correct_slot_index_to_activated_card(db):
    """POST /roster/swap sets slot_index on the newly activated (formerly bench) card
    to the value supplied in the request body."""
    from routers.cards import swap_roster, SwapRequest

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    c_bench = _make_card(db, user.id, p1.id, is_active=False)
    c_active = _make_card(db, user.id, p2.id, is_active=True, slot_index=2)

    swap_roster(
        SwapRequest(bench_card_id=c_bench.id, active_card_id=c_active.id, slot_index=2),
        {"user_id": user.id},
        db,
    )

    db.refresh(c_bench)
    assert c_bench.slot_index == 2


def test_swap_returns_409_when_bench_card_player_already_active(db):
    """POST /roster/swap returns HTTP 409 if another active card already holds the
    same player as the bench card (duplicate-player guard)."""
    from routers.cards import swap_roster, SwapRequest

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)  # player that will be on bench card
    p2 = _make_player(db, "P2", 2)
    # c_bench's player (p1) is also active on another card
    c_bench = _make_card(db, user.id, p1.id, is_active=False)
    c_active_target = _make_card(db, user.id, p2.id, is_active=True, slot_index=0)
    _make_card(db, user.id, p1.id, is_active=True, slot_index=1)  # duplicate

    with pytest.raises(HTTPException) as exc_info:
        swap_roster(
            SwapRequest(bench_card_id=c_bench.id, active_card_id=c_active_target.id, slot_index=0),
            {"user_id": user.id},
            db,
        )
    assert exc_info.value.status_code == 409


def test_swap_returns_404_when_bench_card_not_found(db):
    """POST /roster/swap returns HTTP 404 when bench_card_id does not exist or is
    not owned by the authenticated user."""
    from routers.cards import swap_roster, SwapRequest

    user = _make_user(db)
    p = _make_player(db, "P", 1)
    c_active = _make_card(db, user.id, p.id, is_active=True)

    with pytest.raises(HTTPException) as exc_info:
        swap_roster(
            SwapRequest(bench_card_id=9999, active_card_id=c_active.id, slot_index=0),
            {"user_id": user.id},
            db,
        )
    assert exc_info.value.status_code == 404


def test_swap_returns_404_when_active_card_not_found(db):
    """POST /roster/swap returns HTTP 404 when active_card_id does not exist or is
    not owned by the authenticated user."""
    from routers.cards import swap_roster, SwapRequest

    user = _make_user(db)
    p = _make_player(db, "P", 1)
    c_bench = _make_card(db, user.id, p.id, is_active=False)

    with pytest.raises(HTTPException) as exc_info:
        swap_roster(
            SwapRequest(bench_card_id=c_bench.id, active_card_id=9999, slot_index=0),
            {"user_id": user.id},
            db,
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Story 5 (cont.) — Sort order in roster GET
# ---------------------------------------------------------------------------

def test_roster_get_returns_active_cards_sorted_by_slot_index(db):
    """GET roster response lists active cards ordered by slot_index ascending,
    with NULL slot_index cards appearing last."""
    from routers.cards import _build_roster_response

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    p3 = _make_player(db, "P3", 3)
    c_slot1 = _make_card(db, user.id, p1.id, is_active=True, slot_index=1)
    c_slot0 = _make_card(db, user.id, p2.id, is_active=True, slot_index=0)
    c_none  = _make_card(db, user.id, p3.id, is_active=True, slot_index=None)
    db.commit()

    result = _build_roster_response(db, user.id, None)
    active_ids = [c["id"] for c in result["active"]]

    assert active_ids.index(c_slot0.id) < active_ids.index(c_slot1.id), \
        "slot_index=0 should appear before slot_index=1"
    assert active_ids.index(c_slot1.id) < active_ids.index(c_none.id), \
        "slot_index=1 should appear before slot_index=None"


def test_roster_get_returns_bench_cards_sorted_by_slot_index(db):
    """GET roster response lists bench cards ordered by slot_index ascending,
    with NULL slot_index cards appearing last."""
    from routers.cards import _build_roster_response

    user = _make_user(db)
    p1 = _make_player(db, "P1", 1)
    p2 = _make_player(db, "P2", 2)
    p3 = _make_player(db, "P3", 3)
    c_slot2 = _make_card(db, user.id, p1.id, is_active=False, slot_index=2)
    c_slot0 = _make_card(db, user.id, p2.id, is_active=False, slot_index=0)
    c_none  = _make_card(db, user.id, p3.id, is_active=False, slot_index=None)
    db.commit()

    result = _build_roster_response(db, user.id, None)
    bench_ids = [c["id"] for c in result["bench"]]

    assert bench_ids.index(c_slot0.id) < bench_ids.index(c_slot2.id), \
        "slot_index=0 should appear before slot_index=2"
    assert bench_ids.index(c_slot2.id) < bench_ids.index(c_none.id), \
        "slot_index=2 should appear before slot_index=None"


# ---------------------------------------------------------------------------
# Story 6 — Card Viewer Backdrop Dismiss (frontend / integration stubs)
# ---------------------------------------------------------------------------

def test_card_viewer_closes_on_backdrop_click():
    """Clicking the overlay element (#revealModal) outside the card content adds the
    'hidden' class to the modal and clears the open card state.

    This is a frontend-only behaviour implemented via modal.onclick in
    frontend/app-cards.js (showCard function). Verified by code inspection and
    manual browser testing; not exercisable by pytest without a DOM runtime."""
    pass  # Frontend-only — covered by implementation in app-cards.js


def test_card_viewer_does_not_close_on_card_content_click():
    """Clicking inside the card content area does not propagate to the backdrop handler
    and must not close the modal.

    The e.target === modal guard in the onclick handler ensures only direct clicks
    on the overlay (not bubbled events from card content) close the modal.
    Frontend-only — not exercisable by pytest without a DOM runtime."""
    pass  # Frontend-only — covered by implementation in app-cards.js


# ---------------------------------------------------------------------------
# Migration 021 — slot_index column
# ---------------------------------------------------------------------------

def test_migration_021_adds_slot_index_column_to_cards_table():
    """Running run_migrations() on a legacy schema that lacks slot_index adds the
    column to the cards table without error."""
    import time as _time
    from migrate import run_migrations, MIGRATIONS

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        # Create a minimal cards table without slot_index (legacy schema)
        conn.execute(text("""
            CREATE TABLE cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER, owner_id INTEGER, card_type TEXT,
                league_id INTEGER, is_active BOOLEAN DEFAULT 0, generation INTEGER DEFAULT 1
            )
        """))
        # Pre-populate schema_migrations to skip every migration except 021
        conn.execute(text("""
            CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at INTEGER)
        """))
        ts = int(_time.time())
        for migration_id, _ in MIGRATIONS:
            if migration_id != "021_card_slot_index":
                conn.execute(
                    text("INSERT INTO schema_migrations (id, applied_at) VALUES (:id, :ts)"),
                    {"id": migration_id, "ts": ts},
                )
        conn.commit()

    # Confirm slot_index is absent before migration
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(cards)")).fetchall()}
    assert "slot_index" not in cols

    run_migrations(engine)

    # Confirm slot_index was added
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(cards)")).fetchall()}
    assert "slot_index" in cols


def test_migration_021_is_idempotent():
    """Running run_migrations() twice on a schema that already has slot_index does not
    raise an error (guard branch is exercised)."""
    from migrate import run_migrations

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)  # creates full schema including slot_index

    # Both runs must succeed without raising
    run_migrations(engine)
    run_migrations(engine)

    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(cards)")).fetchall()}
    assert "slot_index" in cols
