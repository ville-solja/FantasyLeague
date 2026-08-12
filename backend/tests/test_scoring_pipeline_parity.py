"""Cross-pipeline parity guardrail — systems-architect technical-debt review,
"Recommended next steps" item 2.

Player-level scoring (scoring.fantasy_score() + scoring.apply_mvp_bonus_to_row(),
written to PlayerMatchStats.fantasy_points) and card-level scoring
(card_utils.card_fantasy_score()/_compute_card_points(), recomputed from raw
per-stat aggregates via _build_roster_response()/leaderboard queries) are two
structurally independent pipelines. They can't simply be merged: the
death-survival term is a clamped, non-linear formula
(max(0, pool - deaths*deduction)), so summing per-match contributions is not
the same as computing it on aggregated deaths across a card's whole scoring
window — see markdown/features/reference/mvp-fantasy-bonus.md.

For the one case where they must always agree exactly — a card backed by a
single match, common rarity (0% bonus), no card modifiers, so the aggregate
degenerates to that one match's own numbers — this test locks in that the two
pipelines stay in sync. It is not a general parity guarantee: multi-match
cards are expected to differ (see test_mvp_card_scoring_parity.py's death-pool
regression case), and any new player-level-only bonus needs its own extension
here. What it buys is turning the specific bug fixed this session (MVP bonus
computed at the player level but never reaching card/roster/leaderboard
totals) into a fast, obvious CI failure if it ever regresses, instead of a
silent divergence discovered sessions later.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from models import Card, Match, Player, PlayerMatchStats, Team, User, Week, WeeklyRosterEntry, Weight
from routers.cards import _build_roster_response
from scoring import apply_mvp_bonus_to_row

_WEIGHTS = {
    "kills": 0.3,
    "gold_per_min": 0.002,
    "death_pool": 3.0,
    "death_deduction": 0.3,
    "mvp_bonus_pct": 10.0,
}


def _seed_single_match_card(db, is_mvp: bool) -> PlayerMatchStats:
    db.add(User(id=1, username="alice", email="alice@test.com", password_hash="x", tokens=0))
    db.add(Player(id=101, name="P1"))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    # card_type="common" -> rarity_common weight is unset, defaults to 0% in
    # _load_weights(), so the card-level rarity multiplier is exactly 1.0.
    db.add(Card(id=1, player_id=101, owner_id=1, card_type="common", is_active=True, slot_index=0))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=999999, is_locked=True))
    db.add(WeeklyRosterEntry(week_id=1, user_id=1, card_id=1))
    db.add(Match(match_id=7001, radiant_team_id=1, dire_team_id=2, start_time=500, radiant_win=True))
    stat = PlayerMatchStats(player_id=101, match_id=7001, team_id=1, kills=7, deaths=3)
    db.add(stat)
    for key, value in _WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    db.commit()

    apply_mvp_bonus_to_row(stat, _WEIGHTS, apply=is_mvp)
    db.commit()
    return stat


class TestSingleMatchCardMatchesPlayerLevelExactly:
    def test_parity_without_mvp(self, db):
        stat = _seed_single_match_card(db, is_mvp=False)

        result = _build_roster_response(db, user_id=1, week_id=1)

        assert result["season_points"] == pytest.approx(stat.fantasy_points)
        assert result["active"][0]["total_points"] == pytest.approx(stat.fantasy_points)

    def test_parity_with_mvp_bonus(self, db):
        stat = _seed_single_match_card(db, is_mvp=True)
        assert stat.is_mvp is True  # sanity: the fixture actually set it

        result = _build_roster_response(db, user_id=1, week_id=1)

        assert result["season_points"] == pytest.approx(stat.fantasy_points)
        assert result["active"][0]["total_points"] == pytest.approx(stat.fantasy_points)
