import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import pytest
from sqlalchemy.exc import IntegrityError

from models import (
    Card, CardModifier, CodeRedemption, League, Match, Player,
    PlayerMatchStats, PromoCode, User, Weight,
)


# ---------------------------------------------------------------------------
# PlayerMatchStats defaults and is_mvp
# ---------------------------------------------------------------------------

class TestPlayerMatchStats:
    def _make_prereqs(self, db):
        league = League(id=1, name="L")
        player = Player(id=1, name="P")
        match = Match(match_id=100, league_id=1)
        db.add_all([league, player, match])
        db.commit()

    def test_is_mvp_defaults_to_false(self, db):
        self._make_prereqs(db)
        stat = PlayerMatchStats(player_id=1, match_id=100, fantasy_points=10.0)
        db.add(stat)
        db.commit()
        db.refresh(stat)
        assert stat.is_mvp is False

    def test_is_mvp_can_be_set_true(self, db):
        self._make_prereqs(db)
        stat = PlayerMatchStats(player_id=1, match_id=100, fantasy_points=10.0, is_mvp=True)
        db.add(stat)
        db.commit()
        db.refresh(stat)
        assert stat.is_mvp is True

    def test_expanded_stat_defaults_to_zero(self, db):
        self._make_prereqs(db)
        stat = PlayerMatchStats(player_id=1, match_id=100, fantasy_points=5.0)
        db.add(stat)
        db.commit()
        db.refresh(stat)
        for col in ("kills", "deaths", "last_hits", "denies", "towers_killed",
                    "roshan_kills", "camps_stacked", "rune_pickups", "firstblood_claimed"):
            assert getattr(stat, col) == 0, f"{col} should default to 0"

    def test_float_stat_defaults_to_zero(self, db):
        self._make_prereqs(db)
        stat = PlayerMatchStats(player_id=1, match_id=100, fantasy_points=5.0)
        db.add(stat)
        db.commit()
        db.refresh(stat)
        assert stat.teamfight_participation == pytest.approx(0.0)
        assert stat.stuns == pytest.approx(0.0)

    def test_fantasy_points_stored_with_precision(self, db):
        self._make_prereqs(db)
        stat = PlayerMatchStats(player_id=1, match_id=100, fantasy_points=12.3456)
        db.add(stat)
        db.commit()
        db.refresh(stat)
        assert stat.fantasy_points == pytest.approx(12.3456)


# ---------------------------------------------------------------------------
# CardModifier stat_key constraint
# ---------------------------------------------------------------------------

class TestCardModifier:
    def _make_card(self, db):
        league = League(id=1, name="L")
        player = Player(id=1, name="P")
        db.add_all([league, player])
        db.commit()
        card = Card(player_id=1, card_type="rare", league_id=1)
        db.add(card)
        db.commit()
        return card

    def test_valid_stat_key_accepted(self, db):
        card = self._make_card(db)
        mod = CardModifier(card_id=card.id, stat_key="kills", bonus_pct=10.0)
        db.add(mod)
        db.commit()
        db.refresh(mod)
        assert mod.stat_key == "kills"
        assert mod.bonus_pct == pytest.approx(10.0)

    def test_deaths_modifier_accepted(self, db):
        card = self._make_card(db)
        mod = CardModifier(card_id=card.id, stat_key="deaths", bonus_pct=20.0)
        db.add(mod)
        db.commit()
        db.refresh(mod)
        assert mod.stat_key == "deaths"

    def test_multiple_modifiers_on_same_card(self, db):
        card = self._make_card(db)
        db.add(CardModifier(card_id=card.id, stat_key="kills", bonus_pct=10.0))
        db.add(CardModifier(card_id=card.id, stat_key="gold_per_min", bonus_pct=10.0))
        db.commit()
        mods = db.query(CardModifier).filter_by(card_id=card.id).all()
        assert len(mods) == 2


# ---------------------------------------------------------------------------
# PromoCode and CodeRedemption
# ---------------------------------------------------------------------------

class TestPromoCodeRedemption:
    def _make_users(self, db):
        admin = User(id=1, username="admin", email="a@test.com",
                     password_hash="x", is_admin=True, tokens=0)
        user1 = User(id=2, username="u1", email="u1@test.com",
                     password_hash="x", tokens=5)
        user2 = User(id=3, username="u2", email="u2@test.com",
                     password_hash="x", tokens=3)
        db.add_all([admin, user1, user2])
        db.commit()
        return admin, user1, user2

    def test_promo_code_created(self, db):
        admin, _, _ = self._make_users(db)
        code = PromoCode(code="SAVE10", token_amount=10, created_by_id=admin.id)
        db.add(code)
        db.commit()
        db.refresh(code)
        assert code.code == "SAVE10"
        assert code.token_amount == 10

    def test_redeem_adds_tokens(self, db):
        admin, user1, _ = self._make_users(db)
        code = PromoCode(code="SAVE5", token_amount=5, created_by_id=admin.id)
        db.add(code)
        db.commit()

        user1.tokens += code.token_amount
        db.add(CodeRedemption(code_id=code.id, user_id=user1.id,
                               redeemed_at=int(time.time())))
        db.commit()

        db.refresh(user1)
        assert user1.tokens == 10

    def test_redemption_is_recorded(self, db):
        admin, user1, _ = self._make_users(db)
        code = PromoCode(code="ONCE", token_amount=3, created_by_id=admin.id)
        db.add(code)
        db.commit()

        db.add(CodeRedemption(code_id=code.id, user_id=user1.id,
                               redeemed_at=int(time.time())))
        db.commit()

        redemptions = db.query(CodeRedemption).filter_by(
            code_id=code.id, user_id=user1.id
        ).all()
        assert len(redemptions) == 1

    def test_two_users_can_redeem_same_code(self, db):
        admin, user1, user2 = self._make_users(db)
        code = PromoCode(code="MULTI", token_amount=2, created_by_id=admin.id)
        db.add(code)
        db.commit()

        db.add(CodeRedemption(code_id=code.id, user_id=user1.id,
                               redeemed_at=int(time.time())))
        db.add(CodeRedemption(code_id=code.id, user_id=user2.id,
                               redeemed_at=int(time.time())))
        db.commit()

        assert db.query(CodeRedemption).filter_by(code_id=code.id).count() == 2

    def test_duplicate_redemption_detectable(self, db):
        admin, user1, _ = self._make_users(db)
        code = PromoCode(code="ONCE2", token_amount=5, created_by_id=admin.id)
        db.add(code)
        db.commit()

        db.add(CodeRedemption(code_id=code.id, user_id=user1.id,
                               redeemed_at=int(time.time())))
        db.commit()

        already = db.query(CodeRedemption).filter_by(
            code_id=code.id, user_id=user1.id
        ).first()
        assert already is not None  # guard used by redemption endpoint


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

class TestUserModel:
    def test_default_is_admin_false(self, db):
        user = User(username="newuser", email="n@test.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.is_admin is False

    def test_default_is_tester_false(self, db):
        user = User(username="tester", email="t@test.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.is_tester is False

    def test_must_change_password_defaults_false(self, db):
        user = User(username="u", email="u@test.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.must_change_password is False

    def test_unique_username_enforced(self, db):
        db.add(User(username="dup", email="a@test.com", password_hash="x"))
        db.commit()
        db.add(User(username="dup", email="b@test.com", password_hash="x"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_unique_email_enforced(self, db):
        db.add(User(username="u1x", email="same@test.com", password_hash="x"))
        db.commit()
        db.rollback()
        db.add(User(username="u1x2", email="same@test.com", password_hash="x"))
        with pytest.raises(IntegrityError):
            db.commit()
