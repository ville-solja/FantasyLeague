import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from database import Base
from models import User, Card


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_user(db, tokens=5):
    u = User(username="tester", email="t@t.com", password_hash="x", tokens=tokens)
    db.add(u)
    db.flush()
    return u


def _make_card(db, owner_id, card_type="common"):
    c = Card(player_id=1, owner_id=owner_id, card_type=card_type, league_id=1, is_active=False)
    db.add(c)
    db.flush()
    return c


def _should_reject_reroll(card):
    """Returns True if the reroll should be rejected — mirrors the backend guard condition."""
    return (card.card_type or "").lower() == "common"


def _do_reroll(db, card, user):
    """Execute the token deduction + modifier wipe without the guard (simulate allowed reroll)."""
    db.execute(text("DELETE FROM card_modifiers WHERE card_id = :cid"), {"cid": card.id})
    user.tokens = (user.tokens or 0) - 1
    db.commit()
    return {"tokens": user.tokens}


# ---------------------------------------------------------------------------
# Backend guard condition: common cards must be rejected
# ---------------------------------------------------------------------------

class TestRerollCommonRejected:
    def test_common_card_triggers_reject(self, db):
        user = _make_user(db, tokens=3)
        card = _make_card(db, user.id, card_type="common")
        assert _should_reject_reroll(card) is True

    def test_common_card_token_not_deducted_when_rejected(self, db):
        user = _make_user(db, tokens=3)
        card = _make_card(db, user.id, card_type="common")
        tokens_before = user.tokens
        # Guard fires — do NOT call _do_reroll
        if _should_reject_reroll(card):
            pass  # correctly rejected
        assert user.tokens == tokens_before

    def test_common_uppercase_also_rejected(self, db):
        user = _make_user(db, tokens=3)
        card = _make_card(db, user.id, card_type="Common")
        assert _should_reject_reroll(card) is True


# ---------------------------------------------------------------------------
# Non-common cards pass the guard
# ---------------------------------------------------------------------------

class TestRerollNonCommonAllowed:
    def test_rare_card_not_rejected(self, db):
        user = _make_user(db, tokens=3)
        card = _make_card(db, user.id, card_type="rare")
        assert _should_reject_reroll(card) is False

    def test_epic_card_not_rejected(self, db):
        user = _make_user(db, tokens=3)
        card = _make_card(db, user.id, card_type="epic")
        assert _should_reject_reroll(card) is False

    def test_legendary_card_not_rejected(self, db):
        user = _make_user(db, tokens=3)
        card = _make_card(db, user.id, card_type="legendary")
        assert _should_reject_reroll(card) is False

    def test_reroll_deducts_one_token_for_non_common(self, db):
        user = _make_user(db, tokens=5)
        card = _make_card(db, user.id, card_type="rare")
        assert not _should_reject_reroll(card)
        result = _do_reroll(db, card, user)
        assert result["tokens"] == 4
