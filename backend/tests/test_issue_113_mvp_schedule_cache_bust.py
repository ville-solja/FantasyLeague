"""
Failing test stubs for plan-issue-113-mvp-schedule-cache-bust.md (resolves
GitHub issue #113).

Issue #113 reports a "huge delay" before a newly-set match MVP shows up on
the Schedule tab. Root cause: `GET /schedule` (`backend/schedule.py::get_schedule`)
caches its response in-process for up to `CACHE_TTL` (3600s) in the
module-level `schedule._cache` dict. Both MVP-setting endpoints —
`POST /admin/matches/{match_id}/mvp` (`admin_set_mvp()` in
`backend/routers/admin_matches.py`) and `POST /twitch/mvp` (`set_mvp()` in
`backend/twitch.py`) — already correctly update `PlayerMatchStats.is_mvp` via
the shared `_apply_mvp_bonus()` helper, but neither calls
`schedule.bust_cache()` after committing, unlike `POST /schedule/refresh` and
the ingest pipeline, which already do. The fix adds a `bust_cache()` call to
both endpoints right after their `db.commit()`, so the next `GET /schedule`
call recomputes fresh data instead of serving the stale cached response.

Every stub below is a `pytest.fail("not yet implemented")` placeholder. Both
MVP-setting endpoint functions are called directly (bypassing FastAPI's
dependency injection, same pattern as `test_admin_mvp_reflects_in_views.py`),
with `schedule._cache` inspected/reset directly (module-level dict, no TTL
mocking needed) to assert cache invalidation without waiting on
`schedule.CACHE_TTL`.

Covers the single user story from
markdown/plans/plan-issue-113-mvp-schedule-cache-bust.md:

  Story: MVP Selection Immediately Reflects on the Schedule Tab
    - `POST /admin/matches/{match_id}/mvp` busts the schedule cache after
      successfully setting the MVP, so the next `GET /schedule` call
      recomputes fresh data instead of serving a stale cached response
    - `POST /twitch/mvp` (the streamer-facing MVP flow) does the same
    - A `GET /schedule` call made immediately after either endpoint succeeds
      shows the new MVP on the corresponding game row, with no waiting period
    - Setting/changing the MVP for a match that isn't part of any
      currently-cached schedule response doesn't error — busting an
      already-clear cache is a no-op, matching `bust_cache()`'s existing
      behaviour used elsewhere (`POST /schedule/refresh`)
    - No change to how the MVP itself is selected, stored, or scored — this
      only fixes how promptly the Schedule tab's read-side cache reflects it
    - (failure path) An MVP-set attempt that fails validation (unknown
      player_id) must not bust an otherwise-still-warm cache, since
      `bust_cache()` is only reached after a successful commit

Run with: cd backend && python -m pytest tests/test_issue_113_mvp_schedule_cache_bust.py -v
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from models import Match, Player, PlayerMatchStats, Team, Weight
from routers.admin_matches import admin_set_mvp, AdminMVPRequest
from twitch import MVPBody, set_mvp
import schedule

_ADMIN = {"user_id": 1, "username": "admin"}
_BROADCASTER_PAYLOAD = {"channel_id": "test_channel", "role": "broadcaster", "opaque_user_id": "Utest"}


@pytest.fixture(autouse=True)
def _reset_schedule_cache():
    """schedule._cache is a module-level dict — reset it around every test in
    this file so cache state never leaks into/out of other test modules that
    also exercise schedule.py (e.g. test_mvp_visibility.py)."""
    schedule.bust_cache()
    yield
    schedule.bust_cache()


def _seed_match_with_two_players(db, match_id=9001, team1_id=1, team2_id=2):
    db.add(Team(id=team1_id, name="TeamA"))
    db.add(Team(id=team2_id, name="TeamB"))
    db.add(Match(match_id=match_id, radiant_team_id=team1_id, dire_team_id=team2_id,
                  start_time=int(time.time()), radiant_win=True))
    db.add(Player(id=101, name="Alice"))
    db.add(Player(id=102, name="Bob"))
    db.add(PlayerMatchStats(player_id=101, match_id=match_id, team_id=team1_id,
                             fantasy_points=10.0, kills=5, is_mvp=False))
    db.add(PlayerMatchStats(player_id=102, match_id=match_id, team_id=team2_id,
                             fantasy_points=8.0, kills=3, is_mvp=False))
    db.add(Weight(key="mvp_bonus_pct", label="MVP bonus (%)", value=10.0))
    db.commit()


def _find_game_by_match_id(schedule_data, match_id):
    """Search a get_schedule() response's extra_results for the games[] entry
    matching match_id (our unscheduled-results path is the one exercised here,
    since no SCHEDULE_SHEET_URL/SCHEDULE_FIXTURES_URL sheet data is seeded)."""
    for series in schedule_data["extra_results"]:
        for game in series["series_result"]["games"]:
            if game["match_id"] == match_id:
                return game
    return None


# ---------------------------------------------------------------------------
# Story: MVP Selection Immediately Reflects on the Schedule Tab
# ---------------------------------------------------------------------------

class TestMvpSelectionImmediatelyReflectsOnScheduleTab:

    def test_admin_set_mvp_busts_schedule_cache(self, db):
        """POST /admin/matches/{match_id}/mvp (admin_set_mvp()) calls
        schedule.bust_cache() after successfully committing the MVP change,
        clearing schedule._cache so the next GET /schedule recomputes fresh
        data instead of serving the pre-MVP cached response."""
        _seed_match_with_two_players(db)
        schedule._cache["data"] = {"weeks": [], "extra_results": []}
        schedule._cache["fetched_at"] = datetime.now()

        admin_set_mvp(9001, AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)

        assert schedule._cache["data"] is None
        assert schedule._cache["fetched_at"] is None

    def test_twitch_set_mvp_busts_schedule_cache(self, db):
        """POST /twitch/mvp (set_mvp() in backend/twitch.py) calls
        schedule.bust_cache() after successfully committing the MVP change,
        the same as the admin-set path."""
        _seed_match_with_two_players(db)
        schedule._cache["data"] = {"weeks": [], "extra_results": []}
        schedule._cache["fetched_at"] = datetime.now()

        set_mvp(MVPBody(match_id=9001, player_id=101), payload=_BROADCASTER_PAYLOAD, db=db)

        assert schedule._cache["data"] is None
        assert schedule._cache["fetched_at"] is None

    def test_get_schedule_reflects_new_mvp_immediately_after_admin_set(self, db, monkeypatch):
        """A GET /schedule call (schedule.get_schedule()) made immediately
        after POST /admin/matches/{match_id}/mvp succeeds shows the new MVP
        on the corresponding game row (via _build_games()'s mvp_player_id/
        mvp_player_name), with no waiting period and without needing
        POST /schedule/refresh or the CACHE_TTL to elapse."""
        monkeypatch.setattr(schedule, "SCHEDULE_SHEET_URL", "")
        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "")
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        _seed_match_with_two_players(db)

        before = schedule.get_schedule(db)
        game_before = _find_game_by_match_id(before, 9001)
        assert game_before is not None
        assert game_before["mvp_player_id"] is None

        admin_set_mvp(9001, AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)

        after = schedule.get_schedule(db)
        game_after = _find_game_by_match_id(after, 9001)
        assert game_after is not None
        assert game_after["mvp_player_id"] == 101
        assert game_after["mvp_player_name"] == "Alice"

    def test_get_schedule_reflects_new_mvp_immediately_after_twitch_set(self, db, monkeypatch):
        """A GET /schedule call made immediately after POST /twitch/mvp
        succeeds shows the new MVP on the corresponding game row, with no
        waiting period — the streamer-facing MVP flow mirrors the admin
        flow's immediate cache invalidation."""
        monkeypatch.setattr(schedule, "SCHEDULE_SHEET_URL", "")
        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "")
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        _seed_match_with_two_players(db)

        before = schedule.get_schedule(db)
        game_before = _find_game_by_match_id(before, 9001)
        assert game_before is not None
        assert game_before["mvp_player_id"] is None

        set_mvp(MVPBody(match_id=9001, player_id=102), payload=_BROADCASTER_PAYLOAD, db=db)

        after = schedule.get_schedule(db)
        game_after = _find_game_by_match_id(after, 9001)
        assert game_after is not None
        assert game_after["mvp_player_id"] == 102
        assert game_after["mvp_player_name"] == "Bob"

    def test_admin_set_mvp_noop_when_schedule_cache_already_empty(self, db):
        """Setting/changing the MVP for a match when schedule._cache is
        already empty/unset (e.g. never warmed, or already expired) does not
        raise — bust_cache() is a plain dict-clear, safe to call
        unconditionally even when there's nothing cached to clear."""
        _seed_match_with_two_players(db)
        assert schedule._cache["data"] is None
        assert schedule._cache["fetched_at"] is None

        result = admin_set_mvp(9001, AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)

        assert result["player_id"] == 101
        assert schedule._cache["data"] is None
        assert schedule._cache["fetched_at"] is None

    def test_admin_set_mvp_still_sets_is_mvp_and_fantasy_bonus_unchanged(self, db):
        """This plan only touches cache invalidation, not scoring: after this
        fix, admin_set_mvp() still sets PlayerMatchStats.is_mvp on the chosen
        player and still applies the fantasy-score MVP bonus via
        _apply_mvp_bonus(), exactly as before the cache-bust call was added."""
        _seed_match_with_two_players(db)

        admin_set_mvp(9001, AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)

        row = db.query(PlayerMatchStats).filter_by(player_id=101, match_id=9001).first()
        assert row.is_mvp is True
        assert row.fantasy_points != 10.0

    def test_admin_set_mvp_unknown_player_404_does_not_bust_cache(self, db):
        """(failure path) admin_set_mvp() with a player_id that doesn't exist
        raises HTTPException(404) before reaching db.commit(), so
        schedule.bust_cache() is never called — a still-warm schedule cache
        from before the failed request remains untouched."""
        _seed_match_with_two_players(db)
        schedule._cache["data"] = {"weeks": [], "extra_results": []}
        schedule._cache["fetched_at"] = datetime.now()

        with pytest.raises(HTTPException) as exc_info:
            admin_set_mvp(9001, AdminMVPRequest(player_id=99999), db=db, admin=_ADMIN)
        assert exc_info.value.status_code == 404

        assert schedule._cache["data"] is not None
        assert schedule._cache["fetched_at"] is not None
