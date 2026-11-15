"""OpenDota failures are visible and Add match fails fast (2026-11-10 report).

Game 3 of a PV-1 vs HOLISA series (match 9083653843, league 20163) never reached the
database, and Admin › Add match stayed on "Loading…". Both fit OpenDota rate-limiting
or failing the server's calls:
- ingest_league read a failed league match list as "0 matches" and logged no error;
- Add match fetched with the background retries (five tries, 10-160 s back-off), so
  the admin's request could hang for minutes, and a failed fetch was reported as
  "no player data, use a replay import".

Covered here: the OpenDota client's in-memory health record, the per-league ingest
status (a failed list, games listed but not stored and why), GET /admin/opendota-status,
Add match's short retries and its 503 when OpenDota didn't answer, and the frontend's
timeout and status panel.
"""
import inspect
import os
import re

import pytest
from fastapi import HTTPException

import ingest as ingest_module
import opendota_client

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class _Res:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    opendota_client.reset_health()
    ingest_module.reset_league_statuses()
    monkeypatch.setattr(opendota_client.time, "sleep", lambda s: None)
    yield
    opendota_client.reset_health()
    ingest_module.reset_league_statuses()


def _answers(monkeypatch, *responses):
    """opendota_client.get answers with these, in order (the last one repeats)."""
    seq = list(responses)

    def _get(url, **kw):
        r = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(opendota_client, "get", _get)


# ---------------------------------------------------------------------------
# Health record
# ---------------------------------------------------------------------------

class TestOpendotaHealth:
    def test_rate_limit_until_give_up_reads_as_rate_limited_now(self, monkeypatch):
        _answers(monkeypatch, _Res(429))
        assert opendota_client.get_json("u", retries=3, label="league 20163 matchIds") is None
        h = opendota_client.health_snapshot()
        assert h["rate_limited_now"] is True and h["failing_now"] is True
        assert h["problems_24h"]["rate_limited"] == 3 and h["problems_24h"]["gave_up"] == 1
        assert h["last_problem"]["kind"] == "gave_up"
        assert h["last_problem"]["label"] == "league 20163 matchIds"

    def test_success_after_problem_clears_now_flags(self, monkeypatch):
        _answers(monkeypatch, _Res(429), _Res(200, [1, 2]))
        assert opendota_client.get_json("u", retries=3) == [1, 2]
        h = opendota_client.health_snapshot()
        assert h["last_ok_at"] is not None
        assert h["rate_limited_now"] is False and h["failing_now"] is False
        assert h["problems_24h"]["rate_limited"] == 1  # still counted for the day

    def test_404_is_an_answer_not_a_problem(self, monkeypatch):
        _answers(monkeypatch, _Res(404))
        assert opendota_client.get_json("u") is None
        h = opendota_client.health_snapshot()
        assert h["last_problem"] is None and sum(h["problems_24h"].values()) == 0

    def test_server_error_and_network_are_recorded(self, monkeypatch):
        import requests
        _answers(monkeypatch, _Res(503), requests.exceptions.Timeout(), _Res(200, {}))
        opendota_client.get_json("u", retries=3)
        counts = opendota_client.health_snapshot()["problems_24h"]
        assert counts["server_error"] == 1 and counts["network"] == 1

    def test_old_problems_leave_the_24h_counts(self, monkeypatch):
        _answers(monkeypatch, _Res(429), _Res(200, {}))
        opendota_client.get_json("u", retries=2)
        later = opendota_client.time.time() + opendota_client.HEALTH_WINDOW_SECONDS + 5
        assert opendota_client.health_snapshot(now=later)["problems_24h"]["rate_limited"] == 0

    def test_api_key_flag_never_exposes_the_key(self, monkeypatch):
        monkeypatch.setenv("OPENDOTA_API_KEY", "secret-value-123")
        h = opendota_client.health_snapshot()
        assert h["api_key_set"] is True
        assert "secret-value-123" not in repr(h)


# ---------------------------------------------------------------------------
# League ingest status
# ---------------------------------------------------------------------------

def _ingest_env(db, monkeypatch, listed, outcomes):
    """ingest_league against `db` with a fake match list and per-id ingest outcomes:
    "stored" adds a Match row, None is a failed fetch, "too_short", or an Exception."""
    from models import Match
    monkeypatch.setattr(ingest_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(ingest_module, "get_league_info", lambda lid: {"name": "Kanaliiga Season 16 Lower"})
    monkeypatch.setattr(ingest_module, "get_league_matches", lambda lid: listed)
    monkeypatch.setattr(ingest_module, "ensure_dotabuff_league_logos", lambda: None)
    db.close = lambda: None  # ingest_league closes its session; keep the test's open

    def _ingest_match(db_, match_id, league_id, *a, **k):
        out = outcomes.get(match_id, "stored")
        if isinstance(out, Exception):
            db_.add(Match(match_id=1, league_id=league_id))  # duplicate key: poisons the session
            db_.flush()
        if out == "stored":
            db_.add(Match(match_id=match_id, league_id=league_id, start_time=1))
            db_.commit()
        return out
    monkeypatch.setattr(ingest_module, "ingest_match", _ingest_match)


class TestLeagueIngestStatus:
    def test_failed_match_list_is_recorded_not_read_as_empty(self, db, monkeypatch, caplog):
        _ingest_env(db, monkeypatch, None, {})
        with caplog.at_level("WARNING"):
            ingest_module.ingest_league(20163)
        st = ingest_module.league_statuses()[20163]
        assert st["list_failed_at"] and "listed_at" not in st
        assert "match list unavailable" in caplog.text

    def test_error_object_instead_of_list_counts_as_failed(self, db, monkeypatch):
        _ingest_env(db, monkeypatch, {"error": "rate limit exceeded"}, {})
        ingest_module.ingest_league(20163)
        assert ingest_module.league_statuses()[20163]["list_failed_at"]

    def test_listed_games_not_stored_are_named_with_a_reason(self, db, monkeypatch):
        from models import Match
        db.add(Match(match_id=1, league_id=20163, start_time=1))
        db.commit()
        listed = [1, 9083489431, 9083653843, 9000000001]
        _ingest_env(db, monkeypatch, listed, {9083653843: None, 9000000001: "too_short"})
        ingest_module.ingest_league(20163)
        st = ingest_module.league_statuses()[20163]
        assert st["listed"] == 4 and st["listed_at"]
        assert st["not_stored"] == [
            {"match_id": 9083653843, "reason": "fetch_failed"},
            {"match_id": 9000000001, "reason": "too_short"},
        ]

    def test_a_failing_game_does_not_block_the_next_one(self, db, monkeypatch):
        from models import Match
        db.add(Match(match_id=1, league_id=20163, start_time=1))
        db.commit()
        _ingest_env(db, monkeypatch, [1, 501, 502], {501: RuntimeError("boom")})
        ingest_module.ingest_league(20163)
        assert db.get(Match, 502) is not None  # the session was rolled back after 501
        reasons = {m["match_id"]: m["reason"] for m in ingest_module.league_statuses()[20163]["not_stored"]}
        assert reasons == {501: "error"}

    def test_later_success_keeps_the_last_failure_time_for_comparison(self, db, monkeypatch):
        _ingest_env(db, monkeypatch, None, {})
        ingest_module.ingest_league(20163)
        _ingest_env(db, monkeypatch, [], {})
        ingest_module.ingest_league(20163)
        st = ingest_module.league_statuses()[20163]
        assert st["listed_at"] >= st["list_failed_at"] and st["not_stored"] == []


# ---------------------------------------------------------------------------
# GET /admin/opendota-status
# ---------------------------------------------------------------------------

class TestAdminOpendotaStatus:
    def test_route_requires_admin(self):
        from deps import require_admin
        from routers import admin_leagues
        sig = inspect.signature(admin_leagues.opendota_status)
        assert sig.parameters["admin"].default.dependency is require_admin

    def test_lists_monitored_leagues_with_their_check(self, db, monkeypatch):
        from models import League
        from routers import admin_leagues
        db.add_all([League(id=20163, name="Kanaliiga Season 16 Lower", is_monitored=True),
                    League(id=7, name="Old", is_monitored=False)])
        db.commit()
        ingest_module._set_league_status(20163, listed_at=100, listed=36,
                                         not_stored=[{"match_id": 9083653843, "reason": "fetch_failed"}])
        _answers(monkeypatch, _Res(429))
        opendota_client.get_json("u", retries=1)
        out = admin_leagues.opendota_status(db=db, admin={"user_id": 1})
        assert [l["id"] for l in out["leagues"]] == [20163]
        assert out["leagues"][0]["not_stored"] == [{"match_id": 9083653843, "reason": "fetch_failed"}]
        assert out["opendota"]["rate_limited_now"] is True

    def test_unchecked_league_has_empty_fields(self, db):
        from models import League
        from routers import admin_leagues
        db.add(League(id=20163, name="L", is_monitored=True))
        db.commit()
        lg = admin_leagues.opendota_status(db=db, admin={})["leagues"][0]
        assert lg["listed_at"] is None and lg["list_failed_at"] is None and lg["not_stored"] == []


# ---------------------------------------------------------------------------
# Add match: short retries, and "OpenDota didn't answer" instead of "no player data"
# ---------------------------------------------------------------------------

class TestAddMatchFailsFast:
    def _body(self, mid=9083653843):
        import manual_match
        return manual_match.ManualMatchBody(match_id=mid)

    def test_fetch_uses_short_interactive_retries(self, db, monkeypatch):
        import manual_match
        seen = {}

        def _get(url, **kw):
            seen.update(kw)
            return None
        monkeypatch.setattr(ingest_module, "opendota_get_json", _get)
        with pytest.raises(HTTPException):
            manual_match.preview(db, self._body())
        assert seen["retries"] <= 2 and seen["timeout"] <= 15 and seen["base_backoff"] <= 5

    def test_rate_limited_fetch_answers_503_naming_the_rate_limit(self, db, monkeypatch):
        import manual_match

        def _get(url, **kw):
            opendota_client._record("rate_limited", "match (add match)", 429)
            opendota_client._record("gave_up", "match (add match)")
            return None
        monkeypatch.setattr(ingest_module, "opendota_get_json", _get)
        with pytest.raises(HTTPException) as exc:
            manual_match.preview(db, self._body())
        assert exc.value.status_code == 503
        assert "rate-limiting" in exc.value.detail
        assert "replay" not in exc.value.detail

    def test_timeout_answers_503_without_rate_limit_wording(self, db, monkeypatch):
        import manual_match

        def _get(url, **kw):
            opendota_client._record("network", "match (add match)")
            opendota_client._record("gave_up", "match (add match)")
            return None
        monkeypatch.setattr(ingest_module, "opendota_get_json", _get)
        with pytest.raises(HTTPException) as exc:
            manual_match.preview(db, self._body())
        assert exc.value.status_code == 503 and "didn't answer" in exc.value.detail

    def test_not_found_keeps_the_replay_hint(self, db, monkeypatch):
        import manual_match
        monkeypatch.setattr(ingest_module, "opendota_get_json", lambda url, **kw: None)
        with pytest.raises(HTTPException) as exc:
            manual_match.preview(db, self._body())
        assert exc.value.status_code == 422 and "Use a replay import instead" in exc.value.detail

    def test_old_problem_does_not_turn_not_found_into_503(self, db, monkeypatch):
        import manual_match
        opendota_client._record("rate_limited", "earlier", 429)
        monkeypatch.setattr(opendota_client.time, "time", lambda: 10**10)  # much later
        monkeypatch.setattr(manual_match.time, "time", lambda: 10**10)
        monkeypatch.setattr(ingest_module, "opendota_get_json", lambda url, **kw: None)
        with pytest.raises(HTTPException) as exc:
            manual_match.preview(db, self._body())
        assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

def _src(name):
    with open(os.path.join(REPO, "frontend", name), encoding="utf-8") as f:
        return f.read()


class TestFrontend:
    def test_add_match_requests_time_out_with_a_clear_message(self):
        js = _src("app-admin-matches.js")
        assert re.search(r"_ADD_MATCH_TIMEOUT_MS\s*=\s*60000", js)
        assert js.count("signal: _addMatchSignal()") == 2  # preview and store
        assert "League Management shows its status" in js
        assert "setStatus('addMatchStatus', _addMatchError(e), false)" in js

    def test_league_management_shows_opendota_status_and_not_stored(self):
        js = _src("app-admin-leagues.js")
        assert "/admin/opendota-status" in js
        assert "<th>Last check</th><th>Not stored</th>" in js
        assert "https://www.opendota.com/matches/${id}" in js
        # every server string in the panel is escaped
        assert "_escHtml(last.label" in js and "_escHtml(_NOT_STORED_TEXT[m.reason] || m.reason)" in js
