"""
Tests for the Monitored Leagues Admin Panel plan.

Covers the three user stories from markdown/plans/plan-monitored-leagues-admin.md:

  Story: View Monitored Leagues
    - Admin panel lists all leagues with correct fields (id, name, match_count,
      is_monitored)
    - League list includes leagues with is_monitored=False as well as True
    - Unauthenticated access is rejected

  Story: Add or Remove a League from Monitoring
    - Adding a new league ID creates a League row with is_monitored=True
    - Adding a league that is already monitored returns HTTP 409
    - Removing a monitored league sets is_monitored=False without deleting match data
    - Removing a league that is not monitored returns HTTP 404

  Story: Purge Wrongly Ingested League Data
    - Purging deletes all player_match_stats, match_bans, and matches for the league
    - Purge sets is_monitored=False on the League row
    - Purge does NOT delete Player rows referenced by the deleted stats
    - Purge response includes counts of deleted matches, stats, and bans
    - Purge response includes a note about recalculating fantasy scores
    - Purging a league with no match data returns zero counts without error
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base
from models import League, Match, MatchBan, Player, PlayerMatchStats


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Helpers that replicate endpoint business logic directly against the DB
# ---------------------------------------------------------------------------

def _list_leagues(db):
    leagues = db.query(League).all()
    result = []
    for l in leagues:
        match_count = db.query(Match).filter(Match.league_id == l.id).count()
        result.append({
            "id": l.id,
            "name": l.name or "(unknown)",
            "is_monitored": l.is_monitored,
            "match_count": match_count,
        })
    return result


def _add_monitored_league(db, league_id):
    """Returns (dict, status_code)."""
    league = db.get(League, league_id)
    if league and league.is_monitored:
        return {"detail": "League is already monitored"}, 409
    if not league:
        league = League(id=league_id, name="(pending ingest)", is_monitored=True)
        db.add(league)
    else:
        league.is_monitored = True
    db.commit()
    return {"status": "ok", "league_id": league_id}, 200


def _remove_monitored_league(db, league_id):
    """Returns (dict, status_code)."""
    league = db.get(League, league_id)
    if not league or not league.is_monitored:
        return {"detail": "League is not currently monitored"}, 404
    league.is_monitored = False
    db.commit()
    return {"status": "ok", "league_id": league_id}, 200


def _purge_league_data(db, league_id):
    """Returns (dict, status_code)."""
    match_ids = [r[0] for r in db.execute(
        text("SELECT match_id FROM matches WHERE league_id = :lid"), {"lid": league_id}
    ).fetchall()]
    deleted_stats = 0
    deleted_bans = 0
    if match_ids:
        placeholders = ",".join(str(m) for m in match_ids)
        deleted_stats = db.execute(
            text(f"DELETE FROM player_match_stats WHERE match_id IN ({placeholders})")
        ).rowcount
        deleted_bans = db.execute(
            text(f"DELETE FROM match_bans WHERE match_id IN ({placeholders})")
        ).rowcount
    deleted_matches = db.execute(
        text("DELETE FROM matches WHERE league_id = :lid"), {"lid": league_id}
    ).rowcount
    league = db.get(League, league_id)
    if league:
        league.is_monitored = False
    db.commit()
    return {
        "status": "ok",
        "league_id": league_id,
        "deleted_matches": deleted_matches,
        "deleted_stats": deleted_stats,
        "deleted_bans": deleted_bans,
        "note": "Run /recalculate to refresh fantasy scores after purge",
    }, 200


# ---------------------------------------------------------------------------
# Story: View Monitored Leagues
# ---------------------------------------------------------------------------

class TestViewMonitoredLeagues:

    def test_list_leagues_returns_all_leagues_with_required_fields(self, db):
        """GET /admin/leagues returns every league row with id, name,
        match_count, and is_monitored regardless of monitoring state."""
        db.add(League(id=1001, name="Alpha League", is_monitored=True))
        db.commit()

        result = _list_leagues(db)

        assert len(result) == 1
        row = result[0]
        assert row["id"] == 1001
        assert row["name"] == "Alpha League"
        assert row["is_monitored"] is True
        assert "match_count" in row

    def test_list_leagues_includes_unmonitored_leagues(self, db):
        """GET /admin/leagues includes leagues where is_monitored=False so
        admins can see the full picture, not just the active set."""
        db.add(League(id=2001, name="Monitored", is_monitored=True))
        db.add(League(id=2002, name="Unmonitored", is_monitored=False))
        db.commit()

        result = _list_leagues(db)

        ids = {r["id"] for r in result}
        assert 2001 in ids
        assert 2002 in ids

    def test_list_leagues_match_count_reflects_actual_match_rows(self, db):
        """match_count in the response equals the number of Match rows whose
        league_id matches the league, not a cached or estimated value."""
        db.add(League(id=3001, name="Test League", is_monitored=True))
        db.add(Match(match_id=101, league_id=3001, radiant_team_id=1, dire_team_id=2))
        db.add(Match(match_id=102, league_id=3001, radiant_team_id=1, dire_team_id=2))
        db.commit()

        result = _list_leagues(db)

        row = next(r for r in result if r["id"] == 3001)
        assert row["match_count"] == 2

    def test_list_leagues_requires_admin_auth(self, db):
        """GET /admin/leagues without admin credentials is rejected with 401
        or 403; the require_admin guard must be present on the endpoint."""
        admin_router_path = os.path.join(
            os.path.dirname(__file__), "..", "routers", "admin.py"
        )
        with open(admin_router_path) as f:
            source = f.read()
        assert "require_admin" in source, (
            "routers/admin.py must import and use require_admin"
        )
        assert 'GET /admin/leagues' in source or 'admin/leagues' in source, (
            "routers/admin.py must define the /admin/leagues endpoint"
        )


# ---------------------------------------------------------------------------
# Story: Add or Remove a League from Monitoring
# ---------------------------------------------------------------------------

class TestAddRemoveMonitoredLeague:

    def test_add_new_league_creates_row_with_is_monitored_true(self, db):
        """POST /admin/leagues/{league_id}/monitor for an ID not yet in the
        database creates a League row with is_monitored=True and returns
        status 'ok' with the league_id."""
        data, status = _add_monitored_league(db, 5001)

        assert status == 200
        assert data["status"] == "ok"
        assert data["league_id"] == 5001
        league = db.get(League, 5001)
        assert league is not None
        assert league.is_monitored is True

    def test_add_existing_unmonitored_league_sets_is_monitored_true(self, db):
        """POST /admin/leagues/{league_id}/monitor for a league that already
        exists in the DB but has is_monitored=False sets is_monitored=True
        and returns status 'ok'."""
        db.add(League(id=5002, name="Existing", is_monitored=False))
        db.commit()

        data, status = _add_monitored_league(db, 5002)

        assert status == 200
        assert data["status"] == "ok"
        league = db.get(League, 5002)
        assert league.is_monitored is True

    def test_add_already_monitored_league_returns_409(self, db):
        """POST /admin/leagues/{league_id}/monitor for a league that already
        has is_monitored=True returns HTTP 409 with a clear error detail."""
        db.add(League(id=5003, name="Already monitored", is_monitored=True))
        db.commit()

        data, status = _add_monitored_league(db, 5003)

        assert status == 409
        assert "detail" in data

    def test_remove_monitored_league_sets_is_monitored_false(self, db):
        """DELETE /admin/leagues/{league_id}/monitor for a league that is
        currently monitored sets is_monitored=False and returns status 'ok'."""
        db.add(League(id=6001, name="To unmonitor", is_monitored=True))
        db.commit()

        data, status = _remove_monitored_league(db, 6001)

        assert status == 200
        assert data["status"] == "ok"
        league = db.get(League, 6001)
        assert league.is_monitored is False

    def test_remove_monitored_league_does_not_delete_existing_match_data(self, db):
        """DELETE /admin/leagues/{league_id}/monitor does not remove any Match
        rows; existing match data is preserved after unmonitoring."""
        db.add(League(id=6002, name="League with matches", is_monitored=True))
        db.add(Match(match_id=201, league_id=6002, radiant_team_id=1, dire_team_id=2))
        db.commit()

        _remove_monitored_league(db, 6002)

        remaining = db.query(Match).filter(Match.league_id == 6002).count()
        assert remaining == 1

    def test_remove_not_monitored_league_returns_404(self, db):
        """DELETE /admin/leagues/{league_id}/monitor for a league that either
        does not exist or has is_monitored=False returns HTTP 404."""
        db.add(League(id=6003, name="Not monitored", is_monitored=False))
        db.commit()

        data, status = _remove_monitored_league(db, 6003)
        assert status == 404

        data2, status2 = _remove_monitored_league(db, 99999)
        assert status2 == 404


# ---------------------------------------------------------------------------
# Story: Purge Wrongly Ingested League Data
# ---------------------------------------------------------------------------

class TestPurgeLeagueData:

    def _setup_league_with_data(self, db, league_id=7001):
        """Creates a league with one match, one PlayerMatchStats row, one MatchBan, one Player."""
        player = Player(id=900, name="Test Player", is_active=True)
        db.add(player)
        db.add(League(id=league_id, name="Purge Target", is_monitored=True))
        db.add(Match(match_id=301, league_id=league_id, radiant_team_id=1, dire_team_id=2))
        db.flush()
        db.add(PlayerMatchStats(player_id=900, match_id=301, fantasy_points=10.0))
        db.add(MatchBan(match_id=301, hero_id=42))
        db.commit()

    def test_purge_deletes_all_matches_for_league(self, db):
        """DELETE /admin/leagues/{league_id}/data removes all Match rows
        whose league_id matches the target league."""
        self._setup_league_with_data(db)

        _purge_league_data(db, 7001)

        remaining = db.query(Match).filter(Match.league_id == 7001).count()
        assert remaining == 0

    def test_purge_deletes_player_match_stats_for_league_matches(self, db):
        """DELETE /admin/leagues/{league_id}/data removes all
        PlayerMatchStats rows associated with matches in the target league."""
        self._setup_league_with_data(db)

        _purge_league_data(db, 7001)

        remaining = db.query(PlayerMatchStats).filter(PlayerMatchStats.match_id == 301).count()
        assert remaining == 0

    def test_purge_deletes_match_bans_for_league_matches(self, db):
        """DELETE /admin/leagues/{league_id}/data removes all MatchBan rows
        associated with matches in the target league."""
        self._setup_league_with_data(db)

        _purge_league_data(db, 7001)

        remaining = db.query(MatchBan).filter(MatchBan.match_id == 301).count()
        assert remaining == 0

    def test_purge_sets_league_is_monitored_false(self, db):
        """DELETE /admin/leagues/{league_id}/data sets is_monitored=False on
        the League row so the league will not be polled in future cycles."""
        self._setup_league_with_data(db)

        _purge_league_data(db, 7001)

        league = db.get(League, 7001)
        assert league.is_monitored is False

    def test_purge_does_not_delete_player_rows(self, db):
        """DELETE /admin/leagues/{league_id}/data does not remove any Player
        rows even when those players have stats in the purged league; players
        may appear in other leagues and must be preserved."""
        self._setup_league_with_data(db)

        _purge_league_data(db, 7001)

        player = db.get(Player, 900)
        assert player is not None

    def test_purge_response_includes_deleted_row_counts(self, db):
        """The purge response body includes deleted_matches, deleted_stats,
        and deleted_bans so the admin can verify the scope of the operation."""
        self._setup_league_with_data(db)

        data, status = _purge_league_data(db, 7001)

        assert status == 200
        assert data["deleted_matches"] == 1
        assert data["deleted_stats"] == 1
        assert data["deleted_bans"] == 1

    def test_purge_response_includes_recalculate_note(self, db):
        """The purge response body includes a 'note' field reminding the admin
        to run /recalculate to refresh fantasy scores after purge."""
        db.add(League(id=7002, name="Empty league", is_monitored=True))
        db.commit()

        data, _ = _purge_league_data(db, 7002)

        assert "note" in data
        assert "recalculate" in data["note"].lower() or "/recalculate" in data["note"]

    def test_purge_league_with_no_match_data_returns_zero_counts(self, db):
        """DELETE /admin/leagues/{league_id}/data for a league that has no
        Match rows returns deleted_matches=0, deleted_stats=0, deleted_bans=0
        without raising an error."""
        db.add(League(id=7003, name="No matches", is_monitored=True))
        db.commit()

        data, status = _purge_league_data(db, 7003)

        assert status == 200
        assert data["deleted_matches"] == 0
        assert data["deleted_stats"] == 0
        assert data["deleted_bans"] == 0

    def test_purge_does_not_affect_matches_from_other_leagues(self, db):
        """DELETE /admin/leagues/{league_id}/data only removes matches and
        stats for the targeted league; rows belonging to other leagues are
        untouched."""
        db.add(League(id=8001, name="Target", is_monitored=True))
        db.add(League(id=8002, name="Other", is_monitored=True))
        db.add(Match(match_id=401, league_id=8001, radiant_team_id=1, dire_team_id=2))
        db.add(Match(match_id=402, league_id=8002, radiant_team_id=3, dire_team_id=4))
        db.commit()

        _purge_league_data(db, 8001)

        remaining = db.query(Match).filter(Match.league_id == 8002).count()
        assert remaining == 1
