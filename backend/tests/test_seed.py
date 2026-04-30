import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Card, League, Match, Player, PlayerMatchStats, Weight
from scoring import SCORING_STATS
from seed import CARD_SCHEMA, DEFAULT_WEIGHTS, seed_cards, seed_weights


@pytest.fixture
def seed_env():
    """In-memory DB with seed.SessionLocal patched to use it."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with patch("seed.SessionLocal", side_effect=Session):
        yield Session


# ---------------------------------------------------------------------------
# DEFAULT_WEIGHTS completeness
# ---------------------------------------------------------------------------

class TestDefaultWeights:
    def test_all_scoring_stats_have_entries(self):
        keys = {w["key"] for w in DEFAULT_WEIGHTS}
        for stat in SCORING_STATS:
            assert stat in keys, f"DEFAULT_WEIGHTS missing entry for stat '{stat}'"

    def test_death_formula_keys_present(self):
        keys = {w["key"] for w in DEFAULT_WEIGHTS}
        assert "death_pool" in keys
        assert "death_deduction" in keys

    def test_rarity_bonus_keys_present(self):
        keys = {w["key"] for w in DEFAULT_WEIGHTS}
        for r in ("rarity_common", "rarity_rare", "rarity_epic", "rarity_legendary"):
            assert r in keys, f"DEFAULT_WEIGHTS missing '{r}'"

    def test_modifier_count_keys_present(self):
        keys = {w["key"] for w in DEFAULT_WEIGHTS}
        for r in ("modifier_count_common", "modifier_count_rare",
                  "modifier_count_epic", "modifier_count_legendary"):
            assert r in keys, f"DEFAULT_WEIGHTS missing '{r}'"

    def test_modifier_bonus_pct_present(self):
        assert any(w["key"] == "modifier_bonus_pct" for w in DEFAULT_WEIGHTS)

    def test_mvp_bonus_pct_present(self):
        assert any(w["key"] == "mvp_bonus_pct" for w in DEFAULT_WEIGHTS)

    def test_no_duplicate_keys(self):
        keys = [w["key"] for w in DEFAULT_WEIGHTS]
        assert len(keys) == len(set(keys))

    def test_all_entries_have_required_fields(self):
        for w in DEFAULT_WEIGHTS:
            assert "key" in w, f"Entry missing 'key': {w}"
            assert "label" in w, f"Entry missing 'label': {w}"
            assert "value" in w, f"Entry missing 'value': {w}"

    def test_default_death_pool(self):
        by_key = {w["key"]: w["value"] for w in DEFAULT_WEIGHTS}
        assert by_key["death_pool"] == 3.0

    def test_default_death_deduction(self):
        by_key = {w["key"]: w["value"] for w in DEFAULT_WEIGHTS}
        assert by_key["death_deduction"] == 0.3

    def test_rarity_common_bonus_is_zero(self):
        by_key = {w["key"]: w["value"] for w in DEFAULT_WEIGHTS}
        assert by_key["rarity_common"] == 0.0

    def test_rarity_bonuses_ascending(self):
        by_key = {w["key"]: w["value"] for w in DEFAULT_WEIGHTS}
        assert (
            by_key["rarity_common"]
            < by_key["rarity_rare"]
            < by_key["rarity_epic"]
            < by_key["rarity_legendary"]
        )

    def test_common_modifier_count_is_zero(self):
        by_key = {w["key"]: w["value"] for w in DEFAULT_WEIGHTS}
        assert by_key["modifier_count_common"] == 0.0

    def test_modifier_counts_ascending(self):
        by_key = {w["key"]: w["value"] for w in DEFAULT_WEIGHTS}
        assert (
            by_key["modifier_count_rare"]
            <= by_key["modifier_count_epic"]
            <= by_key["modifier_count_legendary"]
        )

    def test_all_values_are_numeric(self):
        for w in DEFAULT_WEIGHTS:
            assert isinstance(w["value"], (int, float)), \
                f"Weight '{w['key']}' has non-numeric value: {w['value']!r}"


# ---------------------------------------------------------------------------
# seed_weights() DB behaviour
# ---------------------------------------------------------------------------

class TestSeedWeights:
    def test_seeds_all_default_keys(self, seed_env):
        seed_weights()
        db = seed_env()
        keys = {w.key for w in db.query(Weight).all()}
        db.close()
        assert {w["key"] for w in DEFAULT_WEIGHTS} == keys

    def test_seeds_correct_values(self, seed_env):
        seed_weights()
        db = seed_env()
        by_key = {w.key: w.value for w in db.query(Weight).all()}
        db.close()
        for w in DEFAULT_WEIGHTS:
            assert by_key[w["key"]] == pytest.approx(w["value"])

    def test_idempotent_does_not_create_duplicates(self, seed_env):
        seed_weights()
        first_count = seed_env().query(Weight).count()
        seed_weights()
        second_count = seed_env().query(Weight).count()
        assert first_count == second_count

    def test_weights_json_override_applies_to_target_key(self, seed_env):
        with patch.dict(os.environ, {"WEIGHTS_JSON": '{"kills": 99.0}'}):
            seed_weights()
        db = seed_env()
        row = db.get(Weight, "kills")
        db.close()
        assert row.value == 99.0

    def test_weights_json_override_leaves_other_keys_at_default(self, seed_env):
        with patch.dict(os.environ, {"WEIGHTS_JSON": '{"kills": 99.0}'}):
            seed_weights()
        db = seed_env()
        row = db.get(Weight, "death_pool")
        db.close()
        expected = next(w["value"] for w in DEFAULT_WEIGHTS if w["key"] == "death_pool")
        assert row.value == pytest.approx(expected)

    def test_invalid_weights_json_seeds_defaults_without_crash(self, seed_env):
        with patch.dict(os.environ, {"WEIGHTS_JSON": "not-valid-json"}):
            seed_weights()  # must not raise
        db = seed_env()
        count = db.query(Weight).count()
        db.close()
        assert count == len(DEFAULT_WEIGHTS)

    def test_empty_weights_json_seeds_defaults(self, seed_env):
        with patch.dict(os.environ, {"WEIGHTS_JSON": ""}):
            seed_weights()
        db = seed_env()
        by_key = {w.key: w.value for w in db.query(Weight).all()}
        db.close()
        for w in DEFAULT_WEIGHTS:
            assert by_key[w["key"]] == pytest.approx(w["value"])


# ---------------------------------------------------------------------------
# seed_cards() DB behaviour
# ---------------------------------------------------------------------------

class TestSeedCards:
    def _add_match_data(self, Session, league_id=42):
        db = Session()
        db.add(League(id=league_id, name="Test League"))
        db.add(Player(id=1001, name="PlayerA"))
        db.add(Player(id=1002, name="PlayerB"))
        match = Match(match_id=9001, league_id=league_id)
        db.add(match)
        db.add(PlayerMatchStats(player_id=1001, match_id=9001, fantasy_points=10.0))
        db.add(PlayerMatchStats(player_id=1002, match_id=9001, fantasy_points=8.0))
        db.commit()
        db.close()

    def test_creates_correct_total_cards(self, seed_env):
        self._add_match_data(seed_env)
        seed_cards(league_id=42)
        db = seed_env()
        total = db.query(Card).count()
        db.close()
        cards_per_player = sum(qty for _, qty in CARD_SCHEMA)
        assert total == 2 * cards_per_player  # 2 players × 15 cards each

    def test_card_schema_distribution(self, seed_env):
        self._add_match_data(seed_env)
        seed_cards(league_id=42)
        db = seed_env()
        for card_type, qty_per_player in CARD_SCHEMA:
            count = db.query(Card).filter(Card.card_type == card_type).count()
            assert count == 2 * qty_per_player, \
                f"Expected {2 * qty_per_player} {card_type} cards, got {count}"
        db.close()

    def test_all_seeded_cards_are_unowned(self, seed_env):
        self._add_match_data(seed_env)
        seed_cards(league_id=42)
        db = seed_env()
        owned = db.query(Card).filter(Card.owner_id.isnot(None)).count()
        db.close()
        assert owned == 0

    def test_idempotent_same_generation(self, seed_env):
        self._add_match_data(seed_env)
        seed_cards(league_id=42, generation=1)
        first_count = seed_env().query(Card).count()
        seed_cards(league_id=42, generation=1)
        second_count = seed_env().query(Card).count()
        assert first_count == second_count

    def test_different_generation_adds_cards(self, seed_env):
        self._add_match_data(seed_env)
        seed_cards(league_id=42, generation=1)
        first_count = seed_env().query(Card).count()
        seed_cards(league_id=42, generation=2)
        second_count = seed_env().query(Card).count()
        assert second_count == first_count * 2

    def test_cards_assigned_to_correct_league(self, seed_env):
        self._add_match_data(seed_env)
        seed_cards(league_id=42)
        db = seed_env()
        wrong_league = db.query(Card).filter(Card.league_id != 42).count()
        db.close()
        assert wrong_league == 0
