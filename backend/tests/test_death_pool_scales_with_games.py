"""The death-survival pool must scale with the number of games aggregated into a card's
scoring window. Previously card_fantasy_score() applied a single death_pool to the SUM of
deaths across every match in the window, so a two-game card had the same 3.0-point ceiling
as a one-game card and lost all survival credit at 10 total deaths — a normal 5-deaths-per-game
line — while every other stat scaled linearly with games played.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from models import Card, Match, Player, PlayerMatchStats, Team, User, Week, WeeklyRosterEntry, Weight
from routers.cards import _build_roster_response
from routers.leaderboard import weekly_leaderboard
from scoring import card_fantasy_score, fantasy_score

WEIGHTS = {"kills": 0.3, "death_pool": 3.0, "death_deduction": 0.3}


class TestCardFantasyScoreMatchCount:
    def test_default_match_count_is_single_game(self):
        assert card_fantasy_score({"deaths": 0}, WEIGHTS, {}) == pytest.approx(3.0)
        assert card_fantasy_score({"deaths": 10}, WEIGHTS, {}) == pytest.approx(0.0)

    def test_pool_scales_with_games(self):
        assert card_fantasy_score({"deaths": 0}, WEIGHTS, {}, match_count=2) == pytest.approx(6.0)
        assert card_fantasy_score({"deaths": 0}, WEIGHTS, {}, match_count=3) == pytest.approx(9.0)

    def test_two_normal_games_keep_survival_credit(self):
        # 5 deaths in each of two games used to zero out (3 - 10*0.3); now 6 - 3 = 3.0
        assert card_fantasy_score({"deaths": 10}, WEIGHTS, {}, match_count=2) == pytest.approx(3.0)

    def test_floor_moves_with_games(self):
        assert card_fantasy_score({"deaths": 20}, WEIGHTS, {}, match_count=2) == pytest.approx(0.0)
        assert card_fantasy_score({"deaths": 40}, WEIGHTS, {}, match_count=2) == pytest.approx(0.0)

    def test_matches_per_game_sum_when_no_game_floors_out(self):
        games = [{"kills": 4, "deaths": 3}, {"kills": 1, "deaths": 6}]
        per_game = sum(fantasy_score(g, WEIGHTS) for g in games)
        agg = {"kills": 5, "deaths": 9}
        assert card_fantasy_score(agg, WEIGHTS, {}, match_count=len(games)) == pytest.approx(per_game)

    def test_death_modifier_applies_to_scaled_pool(self):
        plain = card_fantasy_score({"deaths": 4}, WEIGHTS, {}, match_count=2)          # 6 - 1.2 = 4.8
        boosted = card_fantasy_score({"deaths": 4}, WEIGHTS, {"deaths": 25.0}, match_count=2)
        assert boosted == pytest.approx(plain * 1.25)

    def test_zero_match_count_treated_as_one(self):
        assert card_fantasy_score({"deaths": 0}, WEIGHTS, {}, match_count=0) == pytest.approx(3.0)


def _seed_two_game_card(db):
    db.add(User(id=1, username="alice", email="alice@test.com", password_hash="x", tokens=0))
    db.add(Player(id=101, name="P1"))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    db.add(Card(id=1, player_id=101, owner_id=1, card_type="common", is_active=True, slot_index=0))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=999999, is_locked=True))
    db.add(WeeklyRosterEntry(week_id=1, user_id=1, card_id=1))
    for mid, start, kills, deaths in ((9001, 500, 4, 5), (9002, 600, 2, 5)):
        db.add(Match(match_id=mid, radiant_team_id=1, dire_team_id=2, start_time=start, radiant_win=True))
        db.add(PlayerMatchStats(player_id=101, match_id=mid, team_id=1, kills=kills, deaths=deaths))
    for key, value in WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    db.commit()


# kills 6*0.3 = 1.8; deaths 10 over 2 games -> max(0, 6 - 3) = 3.0; total 4.8
_EXPECTED = pytest.approx(4.8, abs=1e-6)


class TestAggregatesUseMatchCount:
    def test_roster_week_and_season_totals(self, db):
        _seed_two_game_card(db)
        result = _build_roster_response(db, user_id=1, week_id=1)
        assert result["active"][0]["match_count"] == 2
        assert result["active"][0]["total_points"] == _EXPECTED
        assert result["season_points"] == _EXPECTED

    def test_weekly_leaderboard(self, db):
        _seed_two_game_card(db)
        result = weekly_leaderboard(week_id=1, db=db)
        assert result[0]["week_points"] == pytest.approx(4.8, abs=1e-2)
