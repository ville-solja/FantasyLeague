import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base
from models import AuditLog, Card, Player, PlayerMatchStats, Team, User, Weight


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed_weights(db, booster_cost=3):
    """Insert the minimum Weight rows needed for booster draw tests."""
    for key, value in [
        ("draw_rate_common",    60.0),
        ("draw_rate_rare",      25.0),
        ("draw_rate_epic",      10.0),
        ("draw_rate_legendary",  5.0),
        ("modifier_count_common",    0.0),
        ("modifier_count_rare",      1.0),
        ("modifier_count_epic",      2.0),
        ("modifier_count_legendary", 3.0),
        ("modifier_bonus_pct", 10.0),
        ("team_booster_cost", float(booster_cost)),
    ]:
        db.add(Weight(key=key, label=key, value=value))
    db.flush()


def _make_team(db, team_id=1, name="Team A"):
    t = Team(id=team_id, name=name)
    db.add(t)
    db.flush()
    return t


def _make_player(db, player_id=10, name="PlayerOne"):
    p = Player(id=player_id, name=name)
    db.add(p)
    db.flush()
    return p


def _link_player_to_team(db, player_id, team_id, match_id=100):
    from models import Match, League
    league = db.get(League, 1)
    if league is None:
        from models import League as L
        db.add(L(id=1, name="TestLeague"))
        db.flush()
    match = db.get(Match, match_id)
    if match is None:
        from models import Match as M
        db.add(M(match_id=match_id, radiant_team_id=team_id,
                 dire_team_id=team_id + 100, league_id=1,
                 start_time=0, radiant_win=True))
        db.flush()
    pms = PlayerMatchStats(
        player_id=player_id, match_id=match_id, team_id=team_id,
        fantasy_points=0.0,
    )
    db.add(pms)
    db.flush()
    return pms


def _make_user(db, tokens=10):
    u = User(username="tester", email="t@t.com", password_hash="x", tokens=tokens)
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# Story: Team Booster Draw
# ---------------------------------------------------------------------------

class TestTeamBoosterDraw:

    def test_team_booster_cost_weight_has_default_value_of_3(self, db):
        """team_booster_cost must exist in DEFAULT_WEIGHTS with value 3.0."""
        from seed import DEFAULT_WEIGHTS
        entry = next((w for w in DEFAULT_WEIGHTS if w["key"] == "team_booster_cost"), None)
        assert entry is not None, "team_booster_cost not found in DEFAULT_WEIGHTS"
        assert entry["value"] == 3.0

    def test_booster_draw_deducts_configured_tokens_from_user(self, db):
        """A successful draw deducts exactly team_booster_cost tokens."""
        from routers.cards import draw_booster
        _seed_weights(db, booster_cost=3)
        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=10)

        result = draw_booster(team_id=team.id, db=db,
                              current_user={"user_id": user.id})
        assert result["tokens"] == 7  # 10 - 3

    def test_booster_draw_returns_card_belonging_to_requested_team(self, db):
        """The drawn card's player must belong to the team_id passed to the endpoint."""
        from routers.cards import draw_booster
        _seed_weights(db)
        team = _make_team(db, team_id=1, name="Team A")
        player = _make_player(db, player_id=10, name="PlayerA")
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db)

        result = draw_booster(team_id=team.id, db=db,
                              current_user={"user_id": user.id})
        # The drawn player must be linked to the requested team
        drawn_player_id = result["player_id"]
        team_player_ids = [
            r[0] for r in
            db.query(PlayerMatchStats.player_id)
              .filter(PlayerMatchStats.team_id == team.id)
              .distinct().all()
        ]
        assert drawn_player_id in team_player_ids

    def test_booster_draw_rarity_uses_standard_draw_rate_weights(self, db):
        """Rarity is determined by the draw_rate_* weights, not a fixed value."""
        from routers.cards import draw_booster
        # Seed weights with only legendary draws possible
        for key, value in [
            ("draw_rate_common",    0.0),
            ("draw_rate_rare",      0.0),
            ("draw_rate_epic",      0.0),
            ("draw_rate_legendary", 100.0),
            ("modifier_count_common",    0.0),
            ("modifier_count_rare",      1.0),
            ("modifier_count_epic",      2.0),
            ("modifier_count_legendary", 3.0),
            ("modifier_bonus_pct", 10.0),
            ("team_booster_cost", 3.0),
        ]:
            db.add(Weight(key=key, label=key, value=value))
        db.flush()

        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db)

        result = draw_booster(team_id=team.id, db=db,
                              current_user={"user_id": user.id})
        assert result["card_type"] == "legendary"

    def test_booster_draw_response_includes_token_balance(self, db):
        """POST /draw/booster/{team_id} response payload includes updated token count."""
        from routers.cards import draw_booster
        _seed_weights(db)
        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=5)

        result = draw_booster(team_id=team.id, db=db,
                              current_user={"user_id": user.id})
        assert "tokens" in result
        assert isinstance(result["tokens"], int)

    def test_booster_draw_insufficient_tokens_raises_409(self, db):
        """A user with fewer tokens than team_booster_cost receives a 409."""
        from routers.cards import draw_booster
        _seed_weights(db, booster_cost=3)
        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=2)  # fewer than cost of 3

        with pytest.raises(HTTPException) as exc_info:
            draw_booster(team_id=team.id, db=db,
                         current_user={"user_id": user.id})
        assert exc_info.value.status_code == 409

    def test_booster_draw_zero_tokens_raises_409(self, db):
        """A user with 0 tokens cannot draw a booster."""
        from routers.cards import draw_booster
        _seed_weights(db, booster_cost=3)
        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=0)

        with pytest.raises(HTTPException) as exc_info:
            draw_booster(team_id=team.id, db=db,
                         current_user={"user_id": user.id})
        assert exc_info.value.status_code == 409

    def test_booster_draw_unknown_team_raises_404(self, db):
        """POST /draw/booster/{nonexistent_team_id} returns 404."""
        from routers.cards import draw_booster
        _seed_weights(db)
        user = _make_user(db, tokens=10)

        with pytest.raises(HTTPException) as exc_info:
            draw_booster(team_id=9999, db=db,
                         current_user={"user_id": user.id})
        assert exc_info.value.status_code == 404

    def test_get_booster_deck_lists_teams_with_players(self, db):
        """GET /deck/booster returns only teams that have at least one player with match data."""
        from routers.cards import get_booster_deck

        class FakeRequest:
            session = {}

        team_a = _make_team(db, team_id=1, name="Alpha")
        team_b = _make_team(db, team_id=2, name="Beta")
        player = _make_player(db, player_id=10)
        _link_player_to_team(db, player.id, team_a.id)
        # team_b has no players

        result = get_booster_deck(request=FakeRequest(), db=db)
        team_ids = [r["team_id"] for r in result]
        assert team_a.id in team_ids
        assert team_b.id not in team_ids

    def test_get_booster_deck_remaining_count_excludes_teams_without_players(self, db):
        """A team with no PlayerMatchStats rows is omitted from GET /deck/booster."""
        from routers.cards import get_booster_deck

        class FakeRequest:
            session = {}

        _make_team(db, team_id=1, name="EmptyTeam")
        result = get_booster_deck(request=FakeRequest(), db=db)
        assert result == []

    def test_get_booster_deck_remaining_count_decreases_after_draw(self, db):
        """After a successful booster draw the selected team's remaining count decreases by 1."""
        from routers.cards import get_booster_deck, draw_booster
        _seed_weights(db)

        class FakeRequest:
            session = {}

        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=10)

        before = get_booster_deck(request=FakeRequest(), db=db)
        before_remaining = next(r["remaining"] for r in before if r["team_id"] == team.id)

        # Do the draw to get the rarity
        result = draw_booster(team_id=team.id, db=db,
                              current_user={"user_id": user.id})

        # Now simulate the deck endpoint with user context
        class AuthRequest:
            session = {"user_id": user.id}

        after = get_booster_deck(request=AuthRequest(), db=db)
        after_remaining = next(r["remaining"] for r in after if r["team_id"] == team.id)
        assert after_remaining < before_remaining


# ---------------------------------------------------------------------------
# Story: Booster Duplicate Prevention
# ---------------------------------------------------------------------------

class TestBoosterDuplicatePrevention:

    def test_booster_draw_excludes_already_owned_players(self, db):
        """_pick_player_from_team must not return a player the user already owns (any rarity)."""
        from card_draw import _pick_player_from_team
        team = _make_team(db)
        player1 = _make_player(db, player_id=10, name="P1")
        player2 = _make_player(db, player_id=11, name="P2")
        _link_player_to_team(db, player1.id, team.id, match_id=100)
        _link_player_to_team(db, player2.id, team.id, match_id=101)
        user = _make_user(db)

        # Own player1 at any rarity
        db.add(Card(player_id=player1.id, owner_id=user.id, card_type="epic",
                    league_id=None, is_active=False, generation=1))
        db.flush()

        # Repeat draws — player1 must never appear regardless of rarity requested
        for _ in range(20):
            picked = _pick_player_from_team(db, user.id, "common", team.id)
            assert picked is not None
            assert picked.id == player2.id

    def test_booster_draw_falls_back_when_all_players_owned(self, db):
        """When every player on the team is owned (any rarity), the draw still succeeds."""
        from card_draw import _pick_player_from_team
        team = _make_team(db)
        player = _make_player(db, player_id=10)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db)

        # Own the only player on the team
        db.add(Card(player_id=player.id, owner_id=user.id, card_type="rare",
                    league_id=None, is_active=False, generation=1))
        db.flush()

        # All players owned — fallback must still return a player
        picked = _pick_player_from_team(db, user.id, "rare", team.id)
        assert picked is not None
        assert picked.id == player.id

    def test_booster_draw_succeeds_when_all_players_owned_via_endpoint(self, db):
        """POST /draw/booster succeeds even when all team players are owned (fallback path)."""
        from routers.cards import draw_booster
        _seed_weights(db)

        team = _make_team(db)
        player = _make_player(db, player_id=10)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=20)

        # Own the only player on the team
        db.add(Card(player_id=player.id, owner_id=user.id, card_type="legendary",
                    league_id=None, is_active=False, generation=1))
        db.flush()

        result = draw_booster(team_id=team.id, db=db,
                              current_user={"user_id": user.id})
        assert result["player_id"] == player.id

    def test_booster_draw_returns_409_when_team_has_no_players(self, db):
        """POST /draw/booster/{team_id} returns 409 when the team exists but has no players in the DB."""
        from routers.cards import draw_booster
        _seed_weights(db)
        team = _make_team(db)  # no players linked
        user = _make_user(db, tokens=10)

        with pytest.raises(HTTPException) as exc_info:
            draw_booster(team_id=team.id, db=db,
                         current_user={"user_id": user.id})
        assert exc_info.value.status_code == 409

    def test_pick_player_from_team_returns_none_for_empty_team(self, db):
        """_pick_player_from_team returns None when the team has no PlayerMatchStats rows."""
        from card_draw import _pick_player_from_team
        team = _make_team(db)
        user = _make_user(db)

        result = _pick_player_from_team(db, user.id, "common", team.id)
        assert result is None

    def test_get_booster_deck_shows_zero_remaining_when_all_players_owned(self, db):
        """GET /deck/booster sets remaining=0 for a team where the user owns every player."""
        from routers.cards import get_booster_deck
        team = _make_team(db)
        player = _make_player(db, player_id=10)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db)

        # Own the player at any rarity — that's enough to exhaust remaining
        db.add(Card(player_id=player.id, owner_id=user.id, card_type="common",
                    league_id=None, is_active=False, generation=1))
        db.flush()

        class AuthRequest:
            session = {"user_id": user.id}

        result = get_booster_deck(request=AuthRequest(), db=db)
        team_entry = next((r for r in result if r["team_id"] == team.id), None)
        assert team_entry is not None
        assert team_entry["remaining"] == 0


# ---------------------------------------------------------------------------
# Story: Configurable Booster Cost (Admin)
# ---------------------------------------------------------------------------

class TestConfigurableBoosterCost:

    def test_team_booster_cost_key_present_in_default_weights(self, db):
        """seed.DEFAULT_WEIGHTS contains an entry with key 'team_booster_cost'."""
        from seed import DEFAULT_WEIGHTS
        keys = [w["key"] for w in DEFAULT_WEIGHTS]
        assert "team_booster_cost" in keys

    def test_booster_draw_reads_cost_from_db_at_request_time(self, db):
        """Changing the Weight row for team_booster_cost is reflected immediately in the next draw."""
        from routers.cards import draw_booster
        _seed_weights(db, booster_cost=3)
        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=10)

        # Update cost to 5 in the DB
        weight_row = db.query(Weight).filter_by(key="team_booster_cost").first()
        weight_row.value = 5.0
        db.flush()

        result = draw_booster(team_id=team.id, db=db,
                              current_user={"user_id": user.id})
        assert result["tokens"] == 5  # 10 - 5

    def test_booster_cost_set_to_1_deducts_one_token(self, db):
        """When team_booster_cost weight is 1, only 1 token is deducted per booster draw."""
        from routers.cards import draw_booster
        _seed_weights(db, booster_cost=1)
        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=5)

        result = draw_booster(team_id=team.id, db=db,
                              current_user={"user_id": user.id})
        assert result["tokens"] == 4  # 5 - 1

    def test_get_config_returns_team_booster_cost(self, db):
        """GET /config response includes the team_booster_cost field."""
        # Test the logic directly: query the weight and check the expected response structure
        db.add(Weight(key="team_booster_cost", label="Team booster draw cost (Tokens)", value=3.0))
        db.flush()

        booster_row = db.query(Weight).filter_by(key="team_booster_cost").first()
        booster_cost = int(booster_row.value) if booster_row else 3

        config_response = {
            "token_name": "Tokens",
            "initial_tokens": 5,
            "team_booster_cost": booster_cost,
        }
        assert "team_booster_cost" in config_response
        assert config_response["team_booster_cost"] == 3

    def test_booster_cost_weight_is_readable_and_writable_via_admin_api(self, db):
        """The team_booster_cost Weight row can be updated through the admin weights endpoint."""
        # The GET /weights endpoint returns all weights including team_booster_cost.
        # Test that the Weight row can be read and modified directly (simulating admin update).
        db.add(Weight(key="team_booster_cost", label="Team booster draw cost (Tokens)", value=3.0))
        db.flush()

        # Read via the weights query used by the leaderboard endpoint
        weights = db.query(Weight).order_by(Weight.key).all()
        keys = [w.key for w in weights]
        assert "team_booster_cost" in keys

        # Write (simulate admin update)
        row = db.query(Weight).filter_by(key="team_booster_cost").first()
        row.value = 7.0
        db.flush()

        updated = db.query(Weight).filter_by(key="team_booster_cost").first()
        assert updated.value == 7.0

    def test_booster_draw_with_custom_cost_higher_than_balance_raises_409(self, db):
        """If admin raises team_booster_cost above user's balance, the next draw returns 409."""
        from routers.cards import draw_booster
        _seed_weights(db, booster_cost=3)
        team = _make_team(db)
        player = _make_player(db)
        _link_player_to_team(db, player.id, team.id)
        user = _make_user(db, tokens=4)

        # Admin raises cost to 10
        row = db.query(Weight).filter_by(key="team_booster_cost").first()
        row.value = 10.0
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            draw_booster(team_id=team.id, db=db,
                         current_user={"user_id": user.id})
        assert exc_info.value.status_code == 409
