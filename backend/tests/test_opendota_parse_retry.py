"""Acceptance-criterion tests for markdown/plans/plan-opendota-parse-retry.md.

Docstrings spell out the exact setup and expected outcome of each test.

Conventions used here:

- Never hit the network. ``ingest.opendota_get_json`` (the ``get_json`` import in
  ``backend/ingest.py``) and the POST helper ``ingest.opendota_post_json`` (the
  ``opendota_client.post_json`` import) are monkeypatched with lambdas returning canned payloads.
- ``retry_unparsed_matches()`` opens its own session like ``ingest_league()`` does, so
  ``ingest.SessionLocal`` is patched with ``monkeypatch.setattr(ingest, "SessionLocal", lambda: db)``
  to route it at the in-memory ``db`` fixture (see the 2026-05-25 lessons-learned entry).
- ``ingest._parse_requested`` (match_id -> last request time) is module-level process state;
  every test that touches ``request_parse()`` resets it (``monkeypatch.setattr(ingest, "_parse_requested", {})``) so
  test order cannot leak "already requested" state between tests.
- ``opendota_client._req_times`` is the rolling RPM window; reset the same way before asserting
  on ``throttle(cost=...)``.
- Endpoint tests call the router function directly and pass every ``Depends(...)`` argument
  explicitly (``admin=_ADMIN``, ``db=db``) — never relying on the ``Depends`` default objects
  (see test_issue_81_season_lifecycle.py for the pattern).
- The endpoint writes its ``parse_retry_triggered`` audit row synchronously through
  ``db=Depends(get_db)`` before spawning the daemon thread; only the re-check itself runs in the
  thread. (An in-memory SQLite session cannot be used from a second thread — SQLAlchemy's
  ``:memory:`` pool is per-thread — so a thread-side audit write via a patched ``SessionLocal``
  is not testable with the shared ``db`` fixture.) The thread releases ``ingest.INGEST_LOCK`` in
  ``finally``; tests patch ``admin_ingest.retry_unparsed_matches`` with a recording stub, wait
  until ``INGEST_LOCK.acquire(blocking=False)`` succeeds, then release it in ``finally`` so a
  failing test does not leave it held for the rest of the session.

A "signature-zero" stat row below means a ``PlayerMatchStats`` row with
``teamfight_participation == 0``, ``stuns == 0`` and ``obs_placed == 0`` — the plan's
detection heuristic for "ingested before OpenDota parsed the replay".
"""

import inspect
import logging
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException
from fastapi.params import Depends as DependsParam

import ingest  # noqa: F401  — module under test; new helpers accessed as ingest.<name>
import opendota_client  # noqa: F401
import scoring
from deps import require_admin
from models import (  # noqa: F401  — registers tables on Base for the db fixture
    AuditLog, League, Match, Player, PlayerMatchStats, Team, TwitchMVP, Weight,
)
from routers import admin_ingest  # noqa: F401

_ADMIN = {"user_id": 1, "username": "admin"}
_NOW = int(time.time())

_PARSED_PAYLOAD_7101 = {
    "version": 21, "duration": 2400, "radiant_win": True,
    "radiant_team_id": 1, "dire_team_id": 2,
    "players": [
        {"account_id": 501, "isRadiant": True, "kills": 3, "obs_placed": 4,
         "teamfight_participation": 0.5, "stuns": 12.5},
        {"account_id": 502, "isRadiant": False, "kills": 1, "obs_placed": 0,
         "teamfight_participation": 0.2, "stuns": 0},
    ],
}


def _seed_match(db, match_id, start_time, rows=None, **match_kwargs):
    """Match + stat rows. Each row dict is merged over a signature-zero default."""
    db.add(Match(match_id=match_id, start_time=start_time, **match_kwargs))
    for row in rows or [{"player_id": 501, "kills": 5}, {"player_id": 502, "kills": 5}]:
        db.add(PlayerMatchStats(**{
            "match_id": match_id, "teamfight_participation": 0.0, "stuns": 0.0,
            "obs_placed": 0, "fantasy_points": 0.0, **row,
        }))
    db.commit()


def _seed_refresh_fixture(db, weights_rows):
    """Shared setup for the refresh tests: weights, teams, players, match 7101 + two
    signature-zero rows (player 501 kills=1 fp=1.0, player 502 kills=0 fp=0.0)."""
    for key, value in weights_rows.items():
        db.add(Weight(key=key, value=value))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    db.add(Player(id=501, name="p501"))
    db.add(Player(id=502, name="p502"))
    db.commit()
    _seed_match(
        db, 7101, _NOW - 3600, duration=1800, radiant_win=False, radiant_team_id=1, dire_team_id=2,
        rows=[{"player_id": 501, "team_id": 1, "kills": 1, "fantasy_points": 1.0},
              {"player_id": 502, "team_id": 2, "kills": 0, "fantasy_points": 0.0}],
    )
    return {w.key: w.value for w in db.query(Weight).all()}


def _rows(db, match_id):
    return db.query(PlayerMatchStats).filter_by(match_id=match_id).order_by(PlayerMatchStats.player_id).all()


def _row_snapshot(row):
    return {c.name: getattr(row, c.name) for c in PlayerMatchStats.__table__.columns}


def _wait_until_lock_free(timeout=5.0):
    """Poll until the background thread has released INGEST_LOCK; the caller now holds it
    and must release it in a finally block."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ingest.INGEST_LOCK.acquire(blocking=False):
            return True
        time.sleep(0.01)
    return False


def _make_recorder(monkeypatch, result):
    """Patch admin_ingest.retry_unparsed_matches with a recorder of (max_age_hours, thread)."""
    calls = []

    def _recorder(max_age_hours):
        calls.append((max_age_hours, threading.current_thread()))
        return result

    monkeypatch.setattr(admin_ingest, "retry_unparsed_matches", _recorder)
    return calls


# ---------------------------------------------------------------------------
# Story 1 — Unparsed Matches Are Re-fetched Until Parsed
# ---------------------------------------------------------------------------

class TestFindUnparsedMatchIds:
    def test_find_unparsed_match_ids_returns_recent_signature_zero_match(self, db):
        """Each poll cycle re-checks every match within the retry window whose stat rows sum to 0 on the three signature stats.

        Setup: one Match(match_id=7001, start_time=_NOW - 3600) with two PlayerMatchStats rows
        that both have teamfight_participation=0, stuns=0, obs_placed=0 (other stats non-zero,
        e.g. kills=5, to prove only the three signature stats are consulted).
        Expected: ingest.find_unparsed_match_ids(db, max_age_hours=48) == [7001].
        """
        _seed_match(db, 7001, _NOW - 3600,
                    rows=[{"player_id": 501, "kills": 5, "deaths": 3, "last_hits": 200},
                          {"player_id": 502, "kills": 5, "gold_per_min": 600}])
        assert ingest.find_unparsed_match_ids(db, max_age_hours=48) == [7001]

    def test_find_unparsed_match_ids_ignores_parsed_match(self, db):
        """A match whose rows carry any parsed-signature data is not treated as unparsed.

        Setup: Match(match_id=7002, start_time=_NOW - 3600) with two stat rows where one row has
        teamfight_participation=0.4 (stuns and obs_placed still 0 on both rows).
        Expected: 7002 is NOT in ingest.find_unparsed_match_ids(db, max_age_hours=48) — a
        non-zero SUM on any one of the three signature stats disqualifies the match.
        """
        _seed_match(db, 7002, _NOW - 3600,
                    rows=[{"player_id": 501, "teamfight_participation": 0.4},
                          {"player_id": 502}])
        assert 7002 not in ingest.find_unparsed_match_ids(db, max_age_hours=48)

    def test_find_unparsed_match_ids_ignores_match_older_than_window(self, db):
        """Matches older than the retry window are never re-fetched, bounding the extra OpenDota traffic.

        Setup: Match(match_id=7003, start_time=_NOW - 72*3600) with signature-zero stat rows, and
        Match(match_id=7004, start_time=_NOW - 3600) with signature-zero stat rows.
        Expected: ingest.find_unparsed_match_ids(db, max_age_hours=48) == [7004]; 7003 is
        excluded purely because start_time < now - 48h even though its rows look unparsed.
        """
        _seed_match(db, 7003, _NOW - 72 * 3600)
        _seed_match(db, 7004, _NOW - 3600)
        assert ingest.find_unparsed_match_ids(db, max_age_hours=48) == [7004]
        # Widening the window proves 7003 was excluded by age alone.
        assert ingest.find_unparsed_match_ids(db, max_age_hours=96) == [7003, 7004]


class TestRefreshMatchStats:
    def test_refresh_match_stats_replaces_rows_and_recomputes_points_when_parsed(self, db, monkeypatch):
        """If GET /matches/{id} now returns a non-null version, existing rows are deleted, re-inserted from the fresh payload, and fantasy_points recomputed with current weights.

        Setup: Weight rows {"kills": 1.0, "obs_placed": 2.0} committed; weights dict built the same
        way ingest_league() does. Match(match_id=7101, start_time=_NOW - 3600, duration=1800,
        radiant_win=False, radiant_team_id=1, dire_team_id=2) plus Team(1), Team(2), Player(501),
        Player(502) and two signature-zero PlayerMatchStats rows (player 501 kills=1
        fantasy_points=1.0, player 502 kills=0 fantasy_points=0.0). Monkeypatch
        ingest.opendota_get_json to return {"version": 21, "duration": 2400, "radiant_win": True,
        "radiant_team_id": 1, "dire_team_id": 2, "players": [
          {"account_id": 501, "isRadiant": True, "kills": 3, "obs_placed": 4,
           "teamfight_participation": 0.5, "stuns": 12.5},
          {"account_id": 502, "isRadiant": False, "kills": 1, "obs_placed": 0,
           "teamfight_participation": 0.2, "stuns": 0}]}.
        Expected: ingest.refresh_match_stats(db, 7101, weights) == "refreshed"; exactly two
        PlayerMatchStats rows remain for match 7101 (old ones gone, no duplicates); player 501's
        row has kills=3, obs_placed=4, teamfight_participation=0.5, stuns=12.5 and
        fantasy_points == scoring.fantasy_score(<that player payload>, weights) (3*1.0 + 4*2.0
        plus the default 3.0 death-survival pool for 0 deaths = 14.0 under these weights); the
        Match row now has duration=2400 and radiant_win=True.
        """
        weights = _seed_refresh_fixture(db, {"kills": 1.0, "obs_placed": 2.0})
        assert [(r.player_id, r.kills) for r in _rows(db, 7101)] == [(501, 1), (502, 0)]
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, **kw: dict(_PARSED_PAYLOAD_7101))

        assert ingest.refresh_match_stats(db, 7101, weights) == "refreshed"

        rows = _rows(db, 7101)
        assert len(rows) == 2, "old rows must be replaced, not duplicated"
        assert [(r.player_id, r.kills) for r in rows] == [(501, 3), (502, 1)]
        r501, r502 = rows
        assert (r501.player_id, r501.kills, r501.obs_placed, r501.teamfight_participation, r501.stuns) == \
            (501, 3, 4, 0.5, 12.5)
        assert r501.team_id == 1 and r502.team_id == 2
        expected_501 = scoring.fantasy_score(_PARSED_PAYLOAD_7101["players"][0], weights)
        assert expected_501 == 14.0
        assert r501.fantasy_points == pytest.approx(expected_501)
        assert r502.fantasy_points == pytest.approx(
            scoring.fantasy_score(_PARSED_PAYLOAD_7101["players"][1], weights))
        match = db.get(Match, 7101)
        assert match.duration == 2400 and match.radiant_win is True

    def test_refresh_match_stats_keeps_confirmed_mvp_flag_and_bonus(self, db, monkeypatch):
        """A previously confirmed Twitch MVP for the refreshed match keeps its is_mvp flag and bonus.

        Setup: as in the parsed-refresh test above, plus Weight("mvp_bonus_pct", 10.0) and a
        TwitchMVP(match_id=7101, player_id=501, channel_id="c1", selected_at=_NOW) row; the
        pre-refresh row for player 501 has is_mvp=True. Monkeypatch ingest.opendota_get_json to
        return the same parsed payload.
        Expected: after ingest.refresh_match_stats(db, 7101, weights) == "refreshed", the new row
        for player 501 has is_mvp=True and fantasy_points == base * 1.10 where base =
        scoring.fantasy_score(player payload, weights) — i.e. scoring.apply_mvp_bonus_to_row was
        re-applied exactly as ingest_match() does. Player 502's row has is_mvp False/None and no
        bonus.
        """
        weights = _seed_refresh_fixture(db, {"kills": 1.0, "obs_placed": 2.0, "mvp_bonus_pct": 10.0})
        db.add(TwitchMVP(match_id=7101, player_id=501, channel_id="c1", selected_at=_NOW))
        pre = db.query(PlayerMatchStats).filter_by(match_id=7101, player_id=501).one()
        pre.is_mvp = True
        db.commit()
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, **kw: dict(_PARSED_PAYLOAD_7101))

        assert ingest.refresh_match_stats(db, 7101, weights) == "refreshed"

        r501, r502 = _rows(db, 7101)
        base = scoring.fantasy_score(_PARSED_PAYLOAD_7101["players"][0], weights)
        assert r501.is_mvp is True
        assert r501.fantasy_points == pytest.approx(round(base * 1.10, 4))
        assert not r502.is_mvp
        assert r502.fantasy_points == pytest.approx(
            scoring.fantasy_score(_PARSED_PAYLOAD_7101["players"][1], weights))

    def test_refresh_match_stats_leaves_rows_untouched_when_still_unparsed(self, db, monkeypatch):
        """If the payload still has version: null, the stored rows are left untouched.

        Setup: Match(match_id=7102, start_time=_NOW - 3600) with two signature-zero stat rows
        (record their primary-key ids and fantasy_points before the call). Monkeypatch
        ingest.opendota_get_json to return {"version": None, "duration": 1800, "players": [
          {"account_id": 501, "isRadiant": True, "kills": 99}, ...]} — a payload whose stats
        differ from the stored rows so any accidental re-insert is detectable.
        Expected: ingest.refresh_match_stats(db, 7102, weights={}) == "unparsed"; the same two
        row ids still exist with identical column values; no row has kills=99.
        """
        _seed_match(db, 7102, _NOW - 3600, duration=1800)
        before = {r.id: _row_snapshot(r) for r in _rows(db, 7102)}
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, **kw: {
            "version": None, "duration": 1800, "players": [
                {"account_id": 501, "isRadiant": True, "kills": 99},
                {"account_id": 502, "isRadiant": False, "kills": 99},
            ]})

        assert ingest.refresh_match_stats(db, 7102, weights={}) == "unparsed"

        db.expire_all()
        after = {r.id: _row_snapshot(r) for r in _rows(db, 7102)}
        assert after == before
        assert all(r["kills"] != 99 for r in after.values())

    def test_refresh_match_stats_returns_unavailable_when_fetch_fails(self, db, monkeypatch):
        """A failed re-fetch leaves the match untouched and eligible for the next cycle.

        Setup: Match(match_id=7103, start_time=_NOW - 3600) with two signature-zero stat rows.
        Monkeypatch ingest.opendota_get_json to return None (what get_json returns after
        exhausting retries or on a non-retryable 4xx).
        Expected: ingest.refresh_match_stats(db, 7103, weights={}) == "unavailable"; both rows
        still exist unchanged; no exception is raised.
        """
        _seed_match(db, 7103, _NOW - 3600)
        before = {r.id: _row_snapshot(r) for r in _rows(db, 7103)}
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, **kw: None)

        assert ingest.refresh_match_stats(db, 7103, weights={}) == "unavailable"

        db.expire_all()
        assert {r.id: _row_snapshot(r) for r in _rows(db, 7103)} == before
        assert ingest.find_unparsed_match_ids(db, max_age_hours=48) == [7103]


class TestRetryUnparsedMatchesResilience:
    def test_retry_unparsed_matches_one_failing_match_does_not_abort_others(self, db, monkeypatch, caplog):
        """A failure on one match is logged and does not abort the cycle or the other matches.

        Setup: monkeypatch ingest.SessionLocal to return db. Seed three recent signature-zero
        matches 7201, 7202, 7203 (each with two stat rows) and empty Weight table. Monkeypatch
        ingest.refresh_match_stats with a function that raises RuntimeError("boom") for
        match_id 7202 and returns "unparsed" for the others; monkeypatch ingest.request_parse
        to a lambda returning False (no POST). Use caplog at WARNING/ERROR level.
        Expected: ingest.retry_unparsed_matches(max_age_hours=48) returns normally with
        summary["checked"] == 3; refresh was invoked for all three ids (7203 is still processed
        after 7202 raised); caplog contains a record mentioning 7202; the RuntimeError never
        propagates.
        """
        monkeypatch.setattr(ingest, "SessionLocal", lambda: db)
        monkeypatch.setattr(ingest, "_parse_requested", {})
        for mid in (7201, 7202, 7203):
            _seed_match(db, mid, _NOW - 3600)
        refreshed = []

        def _refresh(session, match_id, weights):
            refreshed.append(match_id)
            if match_id == 7202:
                raise RuntimeError("boom")
            return "unparsed"

        monkeypatch.setattr(ingest, "refresh_match_stats", _refresh)
        monkeypatch.setattr(ingest, "request_parse", lambda match_id: False)
        caplog.set_level(logging.WARNING)

        summary = ingest.retry_unparsed_matches(max_age_hours=48)

        assert summary["checked"] == 3
        assert refreshed == [7201, 7202, 7203]
        assert any("7202" in rec.getMessage() for rec in caplog.records)
        assert summary["refreshed"] == 0 and summary["requested"] == 0


# ---------------------------------------------------------------------------
# Story 2 — A Parse Is Requested From OpenDota
# ---------------------------------------------------------------------------

def _first_pass_payload(version, **player_extra):
    return {
        "version": version, "duration": 1800, "start_time": _NOW - 600, "radiant_win": True,
        "radiant_team_id": 1, "dire_team_id": 2, "radiant_name": "R", "dire_name": "D",
        "players": [{"account_id": 501, "isRadiant": True, "kills": 2, **player_extra}],
    }


def _post_recorder(monkeypatch, result):
    """Replace ingest.opendota_post_json with a recorder of (url, kwargs)."""
    calls = []

    def _post(url, **kwargs):
        calls.append((url, kwargs))
        return result() if callable(result) else result

    monkeypatch.setattr(ingest, "opendota_post_json", _post)
    return calls


class TestParseRequest:
    def test_ingest_match_requests_parse_when_first_pass_payload_unparsed(self, db, monkeypatch):
        """When first-pass ingest stores a match whose payload has version: null, it immediately submits POST /request/{match_id}.

        Setup: monkeypatch ingest._parse_requested to a fresh set(); monkeypatch
        ingest.opendota_get_json to return {"version": None, "duration": 1800, "start_time":
        _NOW - 600, "radiant_win": True, "radiant_team_id": 1, "dire_team_id": 2,
        "radiant_name": "R", "dire_name": "D", "players": [{"account_id": 501, "isRadiant": True,
        "kills": 2}]}. Replace the POST helper ingest.request_parse depends on (the
        opendota_client.post_json import inside ingest.py) with a recorder that appends the
        called URL and returns {"job": {"jobId": 123}}.
        Expected: after ingest.ingest_match(db, 7301, 999, set(), set(), weights={}), the Match
        and its PlayerMatchStats row are stored exactly as today (first pass unchanged), AND the
        recorder saw exactly one call whose URL == f"{ingest.OPEN_DOTA_URL}/request/7301", AND
        7301 in ingest._parse_requested.
        """
        monkeypatch.setattr(ingest, "_parse_requested", {})
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, **kw: _first_pass_payload(None))
        calls = _post_recorder(monkeypatch, {"job": {"jobId": 123}})

        ingest.ingest_match(db, 7301, 999, set(), set(), weights={})

        match = db.get(Match, 7301)
        assert match is not None and match.radiant_win is True and match.duration == 1800
        rows = _rows(db, 7301)
        assert len(rows) == 1 and rows[0].player_id == 501 and rows[0].kills == 2 and rows[0].team_id == 1
        assert [url for url, _ in calls] == [f"{ingest.OPEN_DOTA_URL}/request/7301"]
        assert 7301 in ingest._parse_requested

    def test_ingest_match_does_not_request_parse_when_payload_already_parsed(self, db, monkeypatch):
        """A first-pass payload with a non-null version must not trigger a parse request.

        Setup: same as the unparsed first-pass test but the payload has "version": 21 and
        "teamfight_participation": 0.3 on the player. Same POST recorder.
        Expected: after ingest.ingest_match(...), the recorder saw zero calls and 7302 is not in
        ingest._parse_requested.
        """
        monkeypatch.setattr(ingest, "_parse_requested", {})
        monkeypatch.setattr(ingest, "opendota_get_json",
                            lambda url, **kw: _first_pass_payload(21, teamfight_participation=0.3))
        calls = _post_recorder(monkeypatch, {"job": {"jobId": 123}})

        ingest.ingest_match(db, 7302, 999, set(), set(), weights={})

        assert db.get(Match, 7302) is not None
        assert _rows(db, 7302)[0].teamfight_participation == pytest.approx(0.3)
        assert calls == []
        assert 7302 not in ingest._parse_requested

    def test_request_parse_posts_once_per_match_within_cooldown(self, monkeypatch):
        """A match is requested at most once per INGEST_PARSE_REREQUEST_HOURS.

        Setup: monkeypatch ingest._parse_requested to {}; replace the POST helper with a
        recorder returning {"job": {"jobId": 42}} and counting calls.
        Expected: ingest.request_parse(7401) is True and the recorder was called once;
        ingest.request_parse(7401) straight after returns False and the call count is still 1;
        ingest.request_parse(7402) triggers a second POST; _parse_requested holds a recent
        timestamp for both 7401 and 7402.
        """
        monkeypatch.setattr(ingest, "_parse_requested", {})
        calls = _post_recorder(monkeypatch, {"job": {"jobId": 42}})

        assert ingest.request_parse(7401) is True
        assert len(calls) == 1
        assert ingest.request_parse(7401) is False
        assert len(calls) == 1
        assert ingest.request_parse(7402) is True
        assert len(calls) == 2
        assert set(ingest._parse_requested) == {7401, 7402}
        assert all(time.time() - ts < 60 for ts in ingest._parse_requested.values())

    def test_request_parse_rerequests_after_cooldown(self, monkeypatch):
        """A match whose last parse request is older than INGEST_PARSE_REREQUEST_HOURS is
        requested again (OpenDota drops a job whose replay download failed, e.g. Valve 5xx).

        Setup: INGEST_PARSE_REREQUEST_HOURS=6; _parse_requested = {7405: now - 7h,
        7406: now - 1h}; POST recorder returning {"job": {"jobId": 7}}.
        Expected: request_parse(7405) is True (one POST, timestamp refreshed);
        request_parse(7406) is False (no POST); the retry loop's _parse_request_due() agrees.
        """
        monkeypatch.setenv("INGEST_PARSE_REREQUEST_HOURS", "6")
        now = time.time()
        monkeypatch.setattr(ingest, "_parse_requested", {7405: now - 7 * 3600, 7406: now - 3600})
        calls = _post_recorder(monkeypatch, {"job": {"jobId": 7}})

        assert ingest._parse_request_due(7405) is True
        assert ingest._parse_request_due(7406) is False
        assert ingest.request_parse(7405) is True
        assert ingest.request_parse(7406) is False
        assert [url for url, _ in calls] == [f"{ingest.OPEN_DOTA_URL}/request/7405"]
        assert ingest._parse_requested[7405] >= now
        assert ingest._parse_requested[7406] == now - 3600

    def test_request_parse_goes_through_client_post_json_with_cost_ten(self, monkeypatch):
        """The request goes through opendota_client with the same api_key/throttle and is counted as 10 requests against the local RPM cap.

        Setup: monkeypatch ingest._parse_requested to set(); replace the POST helper with a
        recorder that captures (url, kwargs) and returns {"job": {"jobId": 1}}.
        Expected: ingest.request_parse(7403) results in exactly one call with
        url == f"{opendota_client.OPEN_DOTA_URL}/request/7403" and kwargs["cost"] == 10.
        Additionally assert opendota_client.post_json exists, is keyword-only after url, and
        accepts timeout/label/cost (inspect.signature) so the helper matches the plan's shape.
        """
        monkeypatch.setattr(ingest, "_parse_requested", {})
        calls = _post_recorder(monkeypatch, {"job": {"jobId": 1}})

        assert ingest.request_parse(7403) is True
        assert len(calls) == 1
        url, kwargs = calls[0]
        assert url == f"{opendota_client.OPEN_DOTA_URL}/request/7403"
        assert kwargs["cost"] == 10

        # The unpatched helper ingest imports must be opendota_client.post_json itself.
        monkeypatch.undo()
        assert ingest.opendota_post_json is opendota_client.post_json
        params = inspect.signature(opendota_client.post_json).parameters
        names = list(params)
        assert names[0] == "url"
        assert all(params[n].kind is inspect.Parameter.KEYWORD_ONLY for n in names[1:])
        assert {"timeout", "label", "cost"} <= set(names[1:])

    def test_throttle_cost_ten_consumes_ten_slots_of_rpm_window(self, monkeypatch):
        """throttle(cost=10) consumes ten slots of the rolling RPM window.

        Setup: monkeypatch opendota_client._req_times to a fresh [] and set env
        OPENDOTA_MAX_RPM=55 (monkeypatch.setenv). Monkeypatch time.sleep in opendota_client to
        raise AssertionError so any blocking wait fails the test loudly.
        Expected: opendota_client.throttle(cost=10) returns without sleeping and
        len(opendota_client._req_times) == 10; a following opendota_client.throttle() (default
        cost=1) makes it 11. Also: with _req_times pre-filled with 50 recent timestamps and
        OPENDOTA_MAX_RPM=55, throttle(cost=10) must attempt to wait (patched sleep is invoked /
        raises) because 50 + 10 > 55 — proving the cost is checked against the cap, not just
        appended after a single-slot check.
        """
        monkeypatch.setenv("OPENDOTA_MAX_RPM", "55")
        monkeypatch.setattr(opendota_client, "_req_times", [])

        def _no_sleep(_s):
            raise AssertionError("throttle tried to sleep")

        monkeypatch.setattr(opendota_client.time, "sleep", _no_sleep)

        opendota_client.throttle(cost=10)
        assert len(opendota_client._req_times) == 10
        opendota_client.throttle()
        assert len(opendota_client._req_times) == 11

        monkeypatch.setattr(opendota_client, "_req_times", [time.time()] * 50)
        with pytest.raises(AssertionError, match="tried to sleep"):
            opendota_client.throttle(cost=10)
        assert len(opendota_client._req_times) == 50

    def test_request_parse_failed_post_logs_warning_and_does_not_raise(self, monkeypatch, caplog):
        """A failed request (non-2xx, timeout) is logged as a warning and does not raise; the match stays eligible for the next cycle.

        Setup: monkeypatch ingest._parse_requested to set(); replace the POST helper with a
        lambda returning None (what post_json returns on non-2xx / timeout). caplog at WARNING.
        Expected: ingest.request_parse(7404) returns False without raising; caplog has a WARNING
        record mentioning 7404; 7404 is NOT in ingest._parse_requested, so a later
        ingest.request_parse(7404) (with the helper now returning {"job": {"jobId": 9}}) POSTs
        again and returns True.
        """
        monkeypatch.setattr(ingest, "_parse_requested", {})
        outcome = {"value": None}
        calls = _post_recorder(monkeypatch, lambda: outcome["value"])
        caplog.set_level(logging.WARNING)

        assert ingest.request_parse(7404) is False
        assert len(calls) == 1
        assert any(rec.levelno == logging.WARNING and "7404" in rec.getMessage() for rec in caplog.records)
        assert 7404 not in ingest._parse_requested

        outcome["value"] = {"job": {"jobId": 9}}
        assert ingest.request_parse(7404) is True
        assert len(calls) == 2
        assert 7404 in ingest._parse_requested

    def test_retry_unparsed_matches_summary_counts(self, db, monkeypatch):
        """The re-check step requests a parse for any still-unparsed match not yet requested this process, and the run reports checked/refreshed/requested/still_unparsed.

        Setup: monkeypatch ingest.SessionLocal to return db and ingest._parse_requested to
        {7503: _NOW} (requested moments ago, still inside the cooldown). Seed four recent signature-zero
        matches 7501..7504 and one recent parsed match 7505 (teamfight_participation=0.5).
        Monkeypatch ingest.refresh_match_stats to return "refreshed" for 7501, "unparsed" for
        7502 and 7503, "unavailable" for 7504. Monkeypatch ingest.request_parse with a recorder
        that returns True and appends the match_id.
        Expected: summary == {"checked": 4, "refreshed": 1, "requested": 2, "still_unparsed": 3}
        — the summary dict is fixed to the plan's four keys, so an "unavailable" match (neither
        parsed nor confirmed unparsed, but still unparsed from the app's point of view) is folded
        into still_unparsed. 7505 is never checked; request_parse was called for 7502 and 7504
        but NOT for 7501 (refreshed) and NOT for 7503 (requested inside the cooldown — the loop
        skips it before calling request_parse, so the recorder never sees it).
        """
        monkeypatch.setattr(ingest, "SessionLocal", lambda: db)
        monkeypatch.setattr(ingest, "_parse_requested", {7503: _NOW})
        for mid in (7501, 7502, 7503, 7504):
            _seed_match(db, mid, _NOW - 3600)
        _seed_match(db, 7505, _NOW - 3600,
                    rows=[{"player_id": 501, "teamfight_participation": 0.5}, {"player_id": 502}])
        outcomes = {7501: "refreshed", 7502: "unparsed", 7503: "unparsed", 7504: "unavailable"}
        checked, requested = [], []

        def _refresh(session, match_id, weights):
            checked.append(match_id)
            return outcomes[match_id]

        def _request(match_id):
            requested.append(match_id)
            return True

        monkeypatch.setattr(ingest, "refresh_match_stats", _refresh)
        monkeypatch.setattr(ingest, "request_parse", _request)

        summary = ingest.retry_unparsed_matches(max_age_hours=48)

        assert summary == {"checked": 4, "refreshed": 1, "requested": 2, "still_unparsed": 3}
        assert checked == [7501, 7502, 7503, 7504]
        assert requested == [7502, 7504]


# ---------------------------------------------------------------------------
# Story 3 — Admin Can Trigger a Backfill On Demand
# ---------------------------------------------------------------------------

_EMPTY_SUMMARY = {"checked": 0, "refreshed": 0, "requested": 0, "still_unparsed": 0}
_RUN_SUMMARY = {"checked": 2, "refreshed": 1, "requested": 1, "still_unparsed": 1}


class TestRetryUnparsedEndpoint:
    def test_retry_unparsed_endpoint_returns_started_and_runs_in_background(self, db, monkeypatch):
        """POST /ingest/retry-unparsed (admin only) runs the re-check in a background thread and returns {"status": "started"} immediately.

        Setup: assert ingest.INGEST_LOCK is not held (acquire(blocking=False) then release).
        Monkeypatch admin_ingest.retry_unparsed_matches with a recorder that captures its
        max_age_hours argument, returns {"checked": 0, "refreshed": 0, "requested": 0,
        "still_unparsed": 0}, and records threading.current_thread() is not the main thread.
        Call the endpoint function admin_ingest.retry_unparsed_endpoint with max_age_hours=None,
        db=db and admin=_ADMIN.
        Expected: return value has "status" == "started" (extra keys such as "max_age_hours" are
        allowed); after waiting until ingest.INGEST_LOCK.acquire(blocking=False) succeeds
        (released in finally), the recorder was called exactly once from a non-main thread, and
        INGEST_LOCK is released again.
        """
        assert ingest.INGEST_LOCK.acquire(blocking=False), "INGEST_LOCK unexpectedly held"
        ingest.INGEST_LOCK.release()
        calls = _make_recorder(monkeypatch, _EMPTY_SUMMARY)

        result = admin_ingest.retry_unparsed_endpoint(max_age_hours=None, db=db, admin=_ADMIN)
        assert result["status"] == "started"

        assert _wait_until_lock_free(), "background thread did not release INGEST_LOCK"
        try:
            assert len(calls) == 1
            assert calls[0][1] is not threading.main_thread()
        finally:
            ingest.INGEST_LOCK.release()
        assert ingest.INGEST_LOCK.acquire(blocking=False)
        ingest.INGEST_LOCK.release()

    def test_retry_unparsed_endpoint_returns_409_when_ingest_lock_held(self, db, monkeypatch):
        """Returns 409 if an ingest is already running, mirroring POST /ingest/league/{league_id}.

        Setup: acquire ingest.INGEST_LOCK in the test (release in finally). Monkeypatch
        admin_ingest.retry_unparsed_matches with a recorder that would fail the test if called.
        Expected: calling the endpoint function with admin=_ADMIN raises fastapi.HTTPException
        with status_code == 409; the recorder was never called; no AuditLog row with action
        "parse_retry_triggered" exists in db.
        """
        assert ingest.INGEST_LOCK.acquire(blocking=False), "INGEST_LOCK unexpectedly held"
        try:
            def _never(max_age_hours):
                raise AssertionError("retry_unparsed_matches must not run while the lock is held")

            monkeypatch.setattr(admin_ingest, "retry_unparsed_matches", _never)
            with pytest.raises(HTTPException) as exc:
                admin_ingest.retry_unparsed_endpoint(max_age_hours=None, db=db, admin=_ADMIN)
            assert exc.value.status_code == 409
            assert db.query(AuditLog).filter_by(action="parse_retry_triggered").count() == 0
        finally:
            ingest.INGEST_LOCK.release()

    def test_retry_unparsed_endpoint_honours_max_age_hours_override(self, db, monkeypatch):
        """An optional max_age_hours query parameter overrides INGEST_PARSE_RETRY_HOURS for that run.

        Setup: monkeypatch.setenv("INGEST_PARSE_RETRY_HOURS", "48") — admin_ingest reads the env
        var at request time via _default_parse_retry_hours(), so no module attribute needs
        patching. Monkeypatch admin_ingest.retry_unparsed_matches with a recorder capturing
        max_age_hours.
        Expected: calling the endpoint with max_age_hours=720, db=db and admin=_ADMIN, then
        waiting for the thread, the recorder received 720; calling again with max_age_hours=None
        (after the lock is free) the recorder received 48 (the env default).
        """
        monkeypatch.setenv("INGEST_PARSE_RETRY_HOURS", "48")
        calls = _make_recorder(monkeypatch, _EMPTY_SUMMARY)

        result = admin_ingest.retry_unparsed_endpoint(max_age_hours=720, db=db, admin=_ADMIN)
        assert result["status"] == "started"
        assert _wait_until_lock_free()
        ingest.INGEST_LOCK.release()
        assert [c[0] for c in calls] == [720]

        result = admin_ingest.retry_unparsed_endpoint(max_age_hours=None, db=db, admin=_ADMIN)
        assert result["status"] == "started"
        assert _wait_until_lock_free()
        ingest.INGEST_LOCK.release()
        assert [c[0] for c in calls] == [720, 48]

    def test_retry_unparsed_endpoint_writes_audit_log_with_window(self, db, monkeypatch):
        """The action is written to the audit log with the window used.

        Setup: monkeypatch admin_ingest.retry_unparsed_matches to return {"checked": 2,
        "refreshed": 1, "requested": 1, "still_unparsed": 1}.
        Expected: after calling the endpoint with max_age_hours=200, db=db and admin=_ADMIN and
        waiting for the background thread, db.query(AuditLog).filter_by(action=
        "parse_retry_triggered") yields exactly one row with actor_id == 1, actor_username ==
        "admin", and "200" in row.detail (detail == "max_age_hours=200").
        """
        _make_recorder(monkeypatch, _RUN_SUMMARY)

        admin_ingest.retry_unparsed_endpoint(max_age_hours=200, db=db, admin=_ADMIN)
        assert _wait_until_lock_free()
        ingest.INGEST_LOCK.release()

        rows = db.query(AuditLog).filter_by(action="parse_retry_triggered").all()
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == 1 and row.actor_username == "admin"
        assert "200" in row.detail and row.detail == "max_age_hours=200"

    def test_retry_unparsed_endpoint_logs_run_summary(self, db, monkeypatch, caplog):
        """The completed run logs how many matches were checked, refreshed, requested and still unparsed.

        Setup: as the audit test, with retry_unparsed_matches returning {"checked": 2,
        "refreshed": 1, "requested": 1, "still_unparsed": 1}; caplog at INFO for logger
        "routers.admin_ingest".
        Expected: after the thread finishes, one INFO record's message contains all four counts
        (assert "checked" and "2", "refreshed" and "1", "requested", "still_unparsed" appear in
        caplog.text).
        """
        _make_recorder(monkeypatch, _RUN_SUMMARY)
        caplog.set_level(logging.INFO, logger="routers.admin_ingest")

        admin_ingest.retry_unparsed_endpoint(max_age_hours=200, db=db, admin=_ADMIN)
        assert _wait_until_lock_free()
        ingest.INGEST_LOCK.release()

        summary_records = [
            rec for rec in caplog.records
            if rec.name == "routers.admin_ingest" and rec.levelno == logging.INFO
            and "still_unparsed" in rec.getMessage()
        ]
        assert len(summary_records) == 1
        msg = summary_records[0].getMessage()
        assert "checked=2" in msg and "refreshed=1" in msg
        assert "requested=1" in msg and "still_unparsed=1" in msg

    def test_retry_unparsed_endpoint_requires_admin_dependency(self):
        """POST /ingest/retry-unparsed is admin only.

        Setup: import inspect and admin_ingest; locate the route function registered for
        path "/ingest/retry-unparsed" with method POST on admin_ingest.router.routes.
        Expected: inspect.signature(fn).parameters has a parameter whose default is a
        fastapi.params.Depends wrapping deps.require_admin (compare `.dependency is
        require_admin`), matching how ingest_league_endpoint is guarded. Also assert the route
        exists at all (fail with a clear message if not found).
        """
        routes = [r for r in admin_ingest.router.routes
                  if getattr(r, "path", None) == "/ingest/retry-unparsed" and "POST" in getattr(r, "methods", set())]
        assert routes, "POST /ingest/retry-unparsed is not registered on admin_ingest.router"
        fn = routes[0].endpoint
        assert fn is admin_ingest.retry_unparsed_endpoint
        guards = [p.default for p in inspect.signature(fn).parameters.values()
                  if isinstance(p.default, DependsParam) and p.default.dependency is require_admin]
        assert len(guards) == 1
