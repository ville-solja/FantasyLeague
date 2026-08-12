"""Regression test: MVP bonus must reach card, roster, and leaderboard totals, not just
player_match_stats.fantasy_points. Previously card_fantasy_score()/_compute_card_points()
(backend/card_utils.py, backend/scoring.py) recomputed card totals from raw per-stat SUM
columns aggregated across every match in a scoring window, with no is_mvp awareness at all —
a confirmed MVP's bonus was visible on their own profile and the player-performance
leaderboard, but invisible in every card-based total (My Team roster value, weekly
leaderboard, season leaderboard, and the End Season archive that shares
compute_season_standings()).

The fix (card_utils._mvp_bonus_delta() / _mvp_bonus_map()) adds the bonus as a flat,
additive term computed from each MVP match's own fantasy_score() (not the card's
aggregate), because the death-survival term (max(0, death_pool - deaths*death_deduction))
is a clamped, non-linear formula: summing per-match death contributions is not the same as
computing the formula on the aggregated death count. These tests lock in both halves of
that behavior — the MVP bonus reaching every card-based total, and the existing aggregate
death-term math staying untouched for the rest of a card's stats.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from models import Card, Match, Player, PlayerMatchStats, Team, User, Week, WeeklyRosterEntry, Weight
from routers.cards import _build_roster_response
from routers.leaderboard import compute_season_standings, weekly_leaderboard

_WEIGHTS = {
    "kills": 0.3,
    "death_pool": 3.0,
    "death_deduction": 0.3,
    "mvp_bonus_pct": 10.0,
}


def _seed(db):
    db.add(User(id=1, username="alice", email="alice@test.com", password_hash="x", tokens=0))
    db.add(Player(id=101, name="P1"))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    db.add(Card(id=1, player_id=101, owner_id=1, card_type="common", is_active=True, slot_index=0))
    week = Week(id=1, label="Week 1", start_time=0, end_time=999999, is_locked=True)
    db.add(week)
    db.add(WeeklyRosterEntry(week_id=1, user_id=1, card_id=1))

    # MVP match: kills=5, deaths=2 -> base = 5*0.3 + max(0, 3-2*0.3) = 1.5 + 2.4 = 3.9
    # mvp bonus delta = 3.9 * 10% = 0.39
    db.add(Match(match_id=5001, radiant_team_id=1, dire_team_id=2, start_time=500, radiant_win=True))
    db.add(PlayerMatchStats(player_id=101, match_id=5001, team_id=1, fantasy_points=4.29,
                             kills=5, deaths=2, is_mvp=True))

    # Non-MVP match in the same window: kills=0, deaths=5. Aggregated with the MVP match,
    # total deaths=7 -> aggregate death term = max(0, 3-7*0.3) = 0.9, NOT
    # max(0,3-2*.3) + max(0,3-5*.3) = 2.4+1.5 = 3.9 (what a naive per-match-then-sum
    # restructure would produce). This is the regression guard for the death-pool claim.
    db.add(Match(match_id=5002, radiant_team_id=1, dire_team_id=2, start_time=600, radiant_win=True))
    db.add(PlayerMatchStats(player_id=101, match_id=5002, team_id=1, fantasy_points=1.5,
                             kills=0, deaths=5, is_mvp=False))

    for key, value in _WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    db.commit()
    return week


# aggregate stat_sums across both matches: kills=5, deaths=7
# base = 5*0.3 + max(0, 3 - 7*0.3) = 1.5 + 0.9 = 2.4
# + mvp bonus delta (from match 5001 alone) = 0.39
# rarity_mod = 1 (no rarity_common weight configured -> defaults to 0%)
_EXPECTED_CARD_TOTAL = pytest.approx(2.79, abs=1e-6)


class TestRosterSeasonPointsIncludesMvpBonus:
    def test_season_points_reflects_mvp_bonus_and_aggregate_death_term(self, db):
        _seed(db)

        result = _build_roster_response(db, user_id=1, week_id=1)

        assert result["season_points"] == _EXPECTED_CARD_TOTAL

    def test_active_card_total_points_reflects_mvp_bonus(self, db):
        _seed(db)

        result = _build_roster_response(db, user_id=1, week_id=1)

        assert len(result["active"]) == 1
        assert result["active"][0]["total_points"] == _EXPECTED_CARD_TOTAL


class TestSeasonLeaderboardIncludesMvpBonus:
    def test_compute_season_standings_reflects_mvp_bonus(self, db):
        _seed(db)

        standings = compute_season_standings(db)

        assert len(standings) == 1
        assert standings[0]["points"] == pytest.approx(2.79, abs=1e-2)
        assert standings[0]["cards"][0]["points"] == pytest.approx(2.79, abs=1e-2)


class TestWeeklyLeaderboardIncludesMvpBonus:
    def test_weekly_leaderboard_reflects_mvp_bonus(self, db):
        _seed(db)

        result = weekly_leaderboard(week_id=1, db=db)

        assert len(result) == 1
        assert result[0]["week_points"] == pytest.approx(2.79, abs=1e-2)


class TestNoMvpMatchesLeavesCardUnaffected:
    def test_card_with_no_mvp_matches_gets_zero_bonus(self, db):
        week = _seed(db)
        # Clear the MVP flag entirely -> bonus should vanish, aggregate math unaffected.
        row = db.query(PlayerMatchStats).filter_by(match_id=5001).first()
        row.is_mvp = False
        db.commit()

        result = _build_roster_response(db, user_id=1, week_id=1)

        # base only: 5*0.3 + max(0, 3-7*0.3) = 1.5 + 0.9 = 2.4, no +0.39
        assert result["season_points"] == pytest.approx(2.4, abs=1e-6)
