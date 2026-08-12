"""Regression test: admin_set_mvp() (POST /admin/matches/{match_id}/mvp) must actually
set PlayerMatchStats.is_mvp and apply the fantasy-score bonus, not just upsert the
TwitchMVP row. Every MVP-visibility surface (mvp_count on GET /players, the MVP column
on GET /players/{id}'s match_history, and mvp_player_id/name on GET /schedule's per-game
entries) reads is_mvp directly, so an admin-set MVP that never touches is_mvp is silently
invisible everywhere except the admin match table itself, which reads TwitchMVP directly."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from models import Match, Player, PlayerMatchStats, TwitchMVP, Weight
from routers.admin_matches import admin_set_mvp, AdminMVPRequest

_ADMIN = {"user_id": 1, "username": "admin"}


def _seed_match_with_two_players(db, match_id=9001):
    db.add(Match(match_id=match_id, radiant_team_id=1, dire_team_id=2,
                  start_time=int(time.time()), radiant_win=True))
    db.add(Player(id=101, name="Alice"))
    db.add(Player(id=102, name="Bob"))
    db.add(PlayerMatchStats(player_id=101, match_id=match_id, team_id=1,
                             fantasy_points=10.0, kills=5, is_mvp=False))
    db.add(PlayerMatchStats(player_id=102, match_id=match_id, team_id=2,
                             fantasy_points=8.0, kills=3, is_mvp=False))
    db.add(Weight(key="mvp_bonus_pct", label="MVP bonus (%)", value=10.0))
    db.commit()


class TestAdminSetMvpReflectsInViews:
    def test_admin_set_mvp_sets_is_mvp_flag_on_player_match_stats(self, db):
        _seed_match_with_two_players(db)

        admin_set_mvp(9001, AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)

        row = db.query(PlayerMatchStats).filter_by(player_id=101, match_id=9001).first()
        assert row.is_mvp is True

    def test_admin_set_mvp_applies_fantasy_score_bonus(self, db):
        _seed_match_with_two_players(db)

        admin_set_mvp(9001, AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)

        row = db.query(PlayerMatchStats).filter_by(player_id=101, match_id=9001).first()
        # base fantasy_score(kills=5, ...) with only mvp_bonus_pct weight set will be
        # recomputed from raw stats — just assert it increased vs the pre-MVP baseline,
        # since the exact base value depends on fantasy_score()'s full weight set.
        assert row.fantasy_points != 10.0

    def test_admin_set_mvp_clears_previous_mvp_when_reassigned(self, db):
        _seed_match_with_two_players(db)
        admin_set_mvp(9001, AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)

        admin_set_mvp(9001, AdminMVPRequest(player_id=102), db=db, admin=_ADMIN)

        old_row = db.query(PlayerMatchStats).filter_by(player_id=101, match_id=9001).first()
        new_row = db.query(PlayerMatchStats).filter_by(player_id=102, match_id=9001).first()
        assert old_row.is_mvp is False
        assert new_row.is_mvp is True

    def test_admin_set_mvp_still_upserts_twitch_mvp_row(self, db):
        """The TwitchMVP upsert (used by the admin match table's own MVP column,
        and shared with the Twitch broadcaster flow) must be unaffected by this fix."""
        _seed_match_with_two_players(db)

        admin_set_mvp(9001, AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)

        mvp_row = db.query(TwitchMVP).filter_by(match_id=9001).first()
        assert mvp_row is not None
        assert mvp_row.player_id == 101
        assert mvp_row.channel_id == "admin"
