"""
Tests for plan-issue-161-mvp-selection-delays.md (resolves GitHub issue #161).

Live games now come from Steam's `IDOTA2Match_570/GetLiveLeagueGames` (new
module `steam_live`, key `STEAM_API_KEY`), checked by a dedicated
`main._live_poll_loop` thread every `LIVE_POLL_INTERVAL` seconds. OpenDota's
`/live` and `ingest.get_live_matches()` are removed. Per-match timings go in a
new `match_timings` table (model `MatchTiming`, created by `create_all`, no
migration). The Twitch panel gets `live_checked_at` / `live_source_configured`
and a freshness line with a Refresh button. One stub per acceptance criterion,
plus the primary failure path for each story.

Developer notes
---------------

  Steam fixture (STAND-IN, replace with a real capture)
    - `backend/tests/fixtures/steam_live_league_games.json` is a STAND-IN built
      from Steam's documented shape, NOT a real response: plan Step 1 (curl
      during a live Kanaliiga game) has not happened yet. When it does, replace
      the file with a trimmed real capture (ids kept, key removed) and re-check
      field names, `players[].team` values and whether `league_id=` filters on
      the server. Drop the top-level `_stand_in` marker key at the same time.
    - Shape: `result.games[]` with `match_id`, `league_id`,
      `radiant_team{team_id, team_name}`, `dire_team{...}`,
      `players[]{account_id, name, hero_id, team}`.
    - Contents: game 8200000001 (league 20162, both teams known, plus a player
      with no account_id, a caster team=2 and a spectator team=4, all to be
      skipped); game 8200000002 (league 20163, radiant team_id 0 and
      team_name "" -> NULL); game 8200000003 (league 99999, unmonitored ->
      dropped). Monitored ids in examples: 20162, 20163.
    - `store_live_matches()` keeps its contract, and today it reads the
      OpenDota-style keys `team_id_radiant`, `team_id_dire`,
      `team_name_radiant`, `team_name_dire` and `players[].team` (0/1). The
      Steam normaliser must emit those keys (or store_live_matches must be
      taught the new ones without changing its signature); pin whichever the
      implementation picks in the normalisation test.

  No network
    - Never hit Steam. Patch `steam_live.requests.get` with a recorder returning
      a fake response (`.status_code`, `.json()`, `.raise_for_status()`), or
      raising `requests.Timeout` / `requests.ConnectionError`. Assert it was
      called exactly once, with `timeout=10`, and patch `time.sleep` with a
      recorder to prove there are no backoff sleeps.
    - For main-level tests patch `main.steam_live.get_live_league_games` (or
      however main imports it) instead of requests.
    - `STEAM_API_KEY` is read at import time in `steam_live`: patch the module
      attribute (`monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")`)
      rather than the env var. Same for `main._LIVE_POLL_INTERVAL`. For the
      "default is 60" check, read the source or reload steam_live only, never
      main.
    - Key-leak checks: use a distinctive key like "SECRETKEY161" and assert it
      appears in no `caplog.text`, no stored row, and no response body.

  Poll loops (`main._live_poll_once`, `main._live_poll_loop`, `main._ingest_poll_loop`)
    - Follow test_issue_109_opendota_query_prioritization.py and
      test_issue_139_early_mvp_selection.py: plain `import main` inside the
      test (do NOT reload main; conftest sets BACKGROUND_TASKS_ENABLED=false
      and DEBUG=true), an `_OneShotEvent` as `main._stop_event`, and
      monkeypatch `_get_monitored_league_ids`, `_auto_ingest`,
      `_run_toornament_sync`, `_has_active_week`. Patch `main.SessionLocal`
      to return the conftest `db` where the loop reads `live_matches`.
    - Reset `main._live_checked_at` with monkeypatch in every test that reads it.

  Storage / timings (`ingest.store_live_matches`, `ingest.ingest_match`, `record_timing`)
    - Call directly with `db=db, now=...`. Import `MatchTiming` from `models`
      INSIDE each test (it does not exist yet; a module-level import would
      break collection of every stub). `_seed_live`, `_seed_match`,
      `_match_payload`, `_call_set_mvp`, `_current` and the `twitch_env`
      fixture body in test_issue_139_early_mvp_selection.py are the
      precedents; import underscore helpers with
      `from tests.test_issue_139_early_mvp_selection import _seed_live, ...`
      (see lessons-learned 2026-10-03) and copy the `twitch_env` fixture.

  Admin (`routers.admin_matches.list_matches`)
    - Call the router function directly with `db=db, _={}`.

  Frontend (`frontend/app-admin-matches.js`, `twitch-extension/live_config.js` / `.html`)
    - No JS runtime required: static source checks (precedent: the
      `_read_js` / `_function_source` helpers in test_issue_139). Optionally
      run under Node against a fake DOM as test_issue_156 does, returning
      early when Node is missing (keep the #85 count exact).

Existing tests that must migrate to the Steam source
----------------------------------------------------
  test_issue_109_opendota_query_prioritization.py
    - test_get_live_matches_falls_back_to_empty_list_when_opendota_call_fails
      (calls ingest.get_live_matches; becomes a steam_live returns-None test
      or is deleted as covered here)
    - test_ingest_poll_loop_selects_live_match_interval_when_league_live
      (patches main.get_live_matches / main.store_live_matches; must seed a
      fresh unended LiveMatch row instead)
    - test_ingest_poll_loop_falls_back_to_normal_interval_selection_when_live_check_fails
      (raises from main.get_live_matches; ingest loop no longer makes a live call)
    - module docstring describes GET /live per poll cycle
  test_issue_139_early_mvp_selection.py
    - module docstring (OpenDota /live fixture, get_live_matches)
    - _run_poll_loop_once helper (patches main.get_live_matches /
      main.store_live_matches); used by
      test_ingest_poll_loop_uses_live_match_interval_after_game_ends_without_stats,
      test_ingest_poll_loop_falls_back_after_post_match_fast_poll_window,
      test_ingest_poll_loop_intervals_unchanged_without_live_or_recent_matches
    - test_store_live_matches_skips_unmonitored_leagues_and_players_without_account_id
      (asserts on ingest.get_live_matches() at the end)
    - test_ingest_poll_loop_stores_live_matches_each_cycle (the ingest loop
      must no longer store live matches; move to _live_poll_once)
    - _LIVE_PAYLOAD is OpenDota-shaped; store_live_matches tests can keep it
      only if store_live_matches still accepts those keys.
  test_issue_156_schedule_visuals.py seeds LiveMatch directly and reads
    schedule.get_live_pairs; it should be unaffected.
  test_issue_85_split_admin_router.py
    - bump the full-suite pass/skip baseline for this plan's new tests.
"""

import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest
import requests

# Registers every existing table on Base before the conftest db fixture runs
# create_all. Import MatchTiming inside tests (it does not exist yet).
import models  # noqa: F401

from tests.test_issue_139_early_mvp_selection import (
    _LIVE_PAYLOAD,
    _MONITORED_LEAGUE,
    _OneShotEvent,
    _add_mvp_weight,
    _call_set_mvp,
    _current,
    _function_source,
    _match_payload,
    _seed_live,
    _seed_match,
)

_FIXTURE = "tests/fixtures/steam_live_league_games.json"  # stand-in, see docstring
_MONITORED = [20162, 20163]

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND, ".."))
_ADMIN_MATCHES_JS = os.path.join(_REPO_ROOT, "frontend", "app-admin-matches.js")
_INDEX_HTML = os.path.join(_REPO_ROOT, "frontend", "index.html")
_LIVE_CONFIG_JS = os.path.join(_REPO_ROOT, "twitch-extension", "live_config.js")
_LIVE_CONFIG_HTML = os.path.join(_REPO_ROOT, "twitch-extension", "live_config.html")
_SECRET = "SECRETKEY161"
_WARNING_TEXT = "Live games not checked recently — your match will appear once its stats are in"


# ===========================================================================
# Shared helpers
# ===========================================================================

def _fixture():
    with open(os.path.join(_BACKEND, _FIXTURE), encoding="utf-8") as f:
        return json.load(f)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url")


def _patch_steam(monkeypatch, outcome, key="TESTKEY"):
    """Patch steam_live's key and requests.get; returns the list of recorded calls.
    `outcome` is a _FakeResponse or an exception instance to raise."""
    import steam_live
    calls = []
    monkeypatch.setattr(steam_live, "STEAM_API_KEY", key)

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    monkeypatch.setattr(steam_live.requests, "get", _get)
    return calls


def _games_by_id(entries):
    return {e["match_id"]: e for e in entries}


def _parsed_fixture():
    import steam_live
    return steam_live.parse_live_league_games(_fixture(), _MONITORED)


@pytest.fixture
def twitch_env(monkeypatch):
    """No real Twitch calls: PubSub/chat short-circuit under TWITCH_LOCAL_DEV."""
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)


def _fake_threading(started):
    class _FakeThread:
        def __init__(self, target=None, daemon=None, **kwargs):
            self.target = target

        def start(self):
            started.append(self.target)
    return SimpleNamespace(Thread=_FakeThread)


class _TwoShotEvent:
    """Stand-in for main._stop_event that allows two loop iterations."""

    def __init__(self):
        self.wait_calls = []

    def is_set(self):
        return len(self.wait_calls) >= 2

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)


def _run_ingest_loop_once(monkeypatch, db, active_week=False):
    import main
    auto_ingest_calls = []
    monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: [_MONITORED_LEAGUE])
    monkeypatch.setattr(main, "_auto_ingest", lambda league_ids, live: auto_ingest_calls.append((league_ids, live)))
    monkeypatch.setattr(main, "_run_toornament_sync", lambda: None)
    monkeypatch.setattr(main, "_has_active_week", lambda: active_week)
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    event = _OneShotEvent()
    monkeypatch.setattr(main, "_stop_event", event)
    main._ingest_poll_loop()
    return auto_ingest_calls, event.wait_calls


def _node():
    return shutil.which("node")


def _run_node(script):
    out = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout)


def _timing_cells(calls):
    """Runs the admin _timingCell(at, start) for each pair under Node; None without Node."""
    if not _node():
        return None
    fn = _function_source(_read(_ADMIN_MATCHES_JS), "_timingCell")
    script = (
        "function _escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')"
        ".replace(/>/g,'&gt;').replace(/\"/g,'&quot;');}\n"
        + fn
        + "\nconsole.log(JSON.stringify(" + json.dumps(calls) + ".map(function(c){return _timingCell(c[0], c[1]);})));"
    )
    return _run_node(script)


_LIVE_CONFIG_HARNESS = r"""
function mk(id) {
  var cls = new Set();
  return {
    id: id, innerHTML: "", textContent: "", disabled: false, className: "", listeners: {},
    classList: {
      toggle: function(c, on) { if (on === undefined) on = !cls.has(c); if (on) cls.add(c); else cls.delete(c); },
      add: function(c) { cls.add(c); }, remove: function(c) { cls.delete(c); },
      contains: function(c) { return cls.has(c); }
    },
    addEventListener: function(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    appendChild: function() {}
  };
}
var els = {};
function el(id) { return els[id] || (els[id] = mk(id)); }
var document = { createElement: function() { return mk(""); }, querySelectorAll: function() { return []; } };
var requests = 0;
var nextResponse = null;
function ebsGet(path) { requests++; return nextResponse(); }
function ebsPost() { return Promise.reject(new Error("no")); }
function showBanner() {}
function _escHtml(s) { return String(s); }
function failReasonSuffix() { return ""; }
function init() {}
%(src)s
function tick() { return new Promise(function(r) { setTimeout(r, 5); }); }
function line() { return { text: el("live-freshness").textContent, warn: el("live-freshness").classList.contains("warn") }; }
(async function() {
  var out = {};
  %(steps)s
  console.log(JSON.stringify(out));
})().catch(function(e) { console.error(e && e.stack || e); process.exit(1); });
"""


def _run_live_config(steps):
    """Runs live_config.js under Node with a fake DOM and EBS; None without Node."""
    if not _node():
        return None
    return _run_node(_LIVE_CONFIG_HARNESS % {"src": _read(_LIVE_CONFIG_JS), "steps": steps})


# ===========================================================================
# Story: Live Games Come From Steam
# ===========================================================================

class TestLiveGamesComeFromSteam:

    def test_get_live_league_games_calls_steam_once_and_keeps_monitored_leagues(self, monkeypatch):
        """AC: with STEAM_API_KEY set, each check calls GetLiveLeagueGames once and keeps only games whose league_id is monitored (20162, 20163 kept; 99999 dropped)."""
        import steam_live
        calls = _patch_steam(monkeypatch, _FakeResponse(200, _fixture()))

        games = steam_live.get_live_league_games(_MONITORED)

        assert len(calls) == 1
        url, kwargs = calls[0]
        assert url == "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/"
        assert kwargs["params"]["key"] == "TESTKEY"
        assert sorted(g["match_id"] for g in games) == [8200000001, 8200000002]
        assert {g["league_id"] for g in games} == {20162, 20163}

    def test_get_live_league_games_normalises_team_ids_and_names(self, monkeypatch):
        """AC: each game is normalised to the store_live_matches() entry shape: match_id, league_id, team ids (0/missing -> None), team names ("" -> None)."""
        import steam_live
        _patch_steam(monkeypatch, _FakeResponse(200, _fixture()))

        games = _games_by_id(steam_live.get_live_league_games(_MONITORED))

        # The normaliser emits the keys store_live_matches() has always read.
        assert set(games[8200000001]) == {
            "match_id", "league_id", "team_id_radiant", "team_id_dire",
            "team_name_radiant", "team_name_dire", "players",
        }
        first = games[8200000001]
        assert (first["league_id"], first["team_id_radiant"], first["team_id_dire"]) == (20162, 9100001, 9100002)
        assert (first["team_name_radiant"], first["team_name_dire"]) == ("Radiant Wolves", "Dire Bears")
        second = games[8200000002]
        assert second["team_id_radiant"] is None
        assert second["team_name_radiant"] is None
        assert (second["team_id_dire"], second["team_name_dire"]) == (9100004, "Pickup Beta")

        # A missing team object is treated like an empty one.
        game = dict(_fixture()["result"]["games"][0])
        del game["dire_team"]
        entry = steam_live.parse_live_league_games({"result": {"games": [game]}}, _MONITORED)[0]
        assert (entry["team_id_dire"], entry["team_name_dire"]) == (None, None)

    def test_get_live_league_games_normalises_players_account_id_name_team(self, monkeypatch):
        """AC: players carry account_id, name and team (0 radiant, 1 dire)."""
        import steam_live
        _patch_steam(monkeypatch, _FakeResponse(200, _fixture()))

        players = _games_by_id(steam_live.get_live_league_games(_MONITORED))[8200000001]["players"]

        assert players[0] == {"account_id": 1000, "name": "P1000", "team": 0}
        assert {p["account_id"] for p in players if p["team"] == 0} == {1000, 1001, 1002, 1003, 1004}
        assert {p["account_id"] for p in players if p["team"] == 1} == {1010, 1011, 1012, 1013}

    def test_get_live_league_games_skips_casters_spectators_and_players_without_account_id(self, monkeypatch):
        """AC: players with team other than 0/1 (casters team=2, spectators team=4) and players without account_id are skipped."""
        import steam_live
        _patch_steam(monkeypatch, _FakeResponse(200, _fixture()))

        games = _games_by_id(steam_live.get_live_league_games(_MONITORED))
        players = games[8200000001]["players"]

        assert len(players) == 9
        ids = {p["account_id"] for p in players}
        assert 1900 not in ids and 1901 not in ids
        assert all(p["account_id"] for p in players)
        assert "NoAccount" not in {p["name"] for p in players}
        assert {p["team"] for p in players} == {0, 1}
        assert len(games[8200000002]["players"]) == 10

    def test_store_live_matches_accepts_normalised_steam_entries(self, db, monkeypatch):
        """AC: store_live_matches keeps its contract; normalised Steam entries produce LiveMatch rows with NULL team ids/names where missing and radiant/dire player sides."""
        import ingest
        from models import LiveMatch

        ingest.store_live_matches(_parsed_fixture(), _MONITORED, db=db, now=1000)

        rows = {r.match_id: r for r in db.query(LiveMatch).all()}
        assert set(rows) == {8200000001, 8200000002}
        first = rows[8200000001]
        assert (first.league_id, first.radiant_team_id, first.dire_team_id) == (20162, 9100001, 9100002)
        assert (first.radiant_name, first.dire_name) == ("Radiant Wolves", "Dire Bears")
        players = json.loads(first.players_json)
        assert players[0] == {"account_id": 1000, "name": "P1000", "side": "radiant"}
        assert {p["account_id"] for p in players if p["side"] == "dire"} == {1010, 1011, 1012, 1013}
        assert len(players) == 9
        second = rows[8200000002]
        assert (second.radiant_team_id, second.radiant_name) == (None, None)
        assert (second.dire_team_id, second.dire_name) == (9100004, "Pickup Beta")

    def test_get_live_matches_removed_and_opendota_live_not_called_anywhere(self):
        """AC: OpenDota's /live is no longer called anywhere; ingest.get_live_matches does not exist and main does not import or call it."""
        import ingest
        import main

        assert not hasattr(ingest, "get_live_matches")
        assert not hasattr(main, "get_live_matches")
        assert "get_live_matches" not in _read(os.path.join(_BACKEND, "main.py"))

        offenders = []
        for root, _dirs, files in os.walk(_BACKEND):
            if os.sep + "tests" in root or "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                src = _read(os.path.join(root, name))
                if re.search(r"OPEN_DOTA_URL\}?/live\b|api\.opendota\.com/api/live\b|get_live_matches", src):
                    offenders.append(name)
        assert offenders == []

    def test_get_live_league_games_request_error_log_omits_steam_key(self, monkeypatch, caplog):
        """AC: request errors are logged with the key removed from the URL (status or exception class only); the key never appears in caplog."""
        import steam_live
        url = f"https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/?key={_SECRET}"

        with caplog.at_level(logging.DEBUG):
            _patch_steam(monkeypatch, requests.ConnectionError(f"Max retries exceeded with url: {url}"), key=_SECRET)
            assert steam_live.get_live_league_games(_MONITORED) is None
            _patch_steam(monkeypatch, requests.Timeout(f"Read timed out. (url: {url})"), key=_SECRET)
            assert steam_live.get_live_league_games(_MONITORED) is None
            _patch_steam(monkeypatch, _FakeResponse(403, {"error": url}), key=_SECRET)
            assert steam_live.get_live_league_games(_MONITORED) is None
            _patch_steam(monkeypatch, _FakeResponse(200, json_error=ValueError(url)), key=_SECRET)
            assert steam_live.get_live_league_games(_MONITORED) is None

        assert _SECRET not in caplog.text
        assert "ConnectionError" in caplog.text
        assert "Timeout" in caplog.text
        assert "403" in caplog.text

    def test_steam_key_never_stored_or_returned(self, db, monkeypatch):
        """AC: the Steam key is never stored (no LiveMatch/MatchTiming field) nor returned by GET /twitch/matches/current or GET /admin/matches."""
        import ingest
        import main
        import steam_live
        from models import LiveMatch, MatchTiming
        from routers import admin_matches
        monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
        monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)

        _patch_steam(monkeypatch, _FakeResponse(200, _fixture()), key=_SECRET)
        monkeypatch.setattr(steam_live, "live_checked_at", None)
        monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: list(_MONITORED))
        monkeypatch.setattr(ingest, "SessionLocal", lambda: db)
        _seed_match(db, 9001, 11, 12, int(time.time()) - 600, player_ids=(500, 510))

        main._live_poll_once()

        db.expire_all()
        stored = []
        for model in (LiveMatch, MatchTiming):
            for row in db.query(model).all():
                stored += [str(getattr(row, c.name)) for c in model.__table__.columns]
        assert stored and not any(_SECRET in v for v in stored)
        assert _SECRET not in json.dumps(_current(db))
        assert _SECRET not in json.dumps(admin_matches.list_matches(db=db, _={}))

    def test_env_example_documents_steam_api_key_and_live_poll_interval(self):
        """AC: .env.example has a commented STEAM_API_KEY= (noting the Steam login #150 reuses it) and LIVE_POLL_INTERVAL=60."""
        src = _read(os.path.join(_REPO_ROOT, ".env.example"))

        assert re.search(r"^# STEAM_API_KEY=$", src, re.M)
        assert not re.search(r"^STEAM_API_KEY=", src, re.M)
        block = src[:src.index("# STEAM_API_KEY=")].rsplit("\n\n", 1)[-1]
        assert "#150" in block
        assert re.search(r"^# LIVE_POLL_INTERVAL=60$", src, re.M)

    def test_live_poll_once_without_steam_api_key_makes_no_request(self, monkeypatch):
        """Failure path: with STEAM_API_KEY unset, no live check runs (no Steam request, _live_checked_at stays None)."""
        import main
        import steam_live
        calls = _patch_steam(monkeypatch, _FakeResponse(200, _fixture()), key="")
        monkeypatch.setattr(steam_live, "live_checked_at", None)
        monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: list(_MONITORED))
        monkeypatch.setattr(main, "store_live_matches", lambda *a, **k: pytest.fail("nothing to store"))

        main._live_poll_once()

        assert calls == []
        assert steam_live.live_checked_at is None
        # The Steam function itself also refuses to call without a key.
        assert steam_live.get_live_league_games(_MONITORED) is None
        assert calls == []

    def test_startup_logs_missing_steam_api_key_warning_once(self, monkeypatch, caplog):
        """Failure path: with STEAM_API_KEY unset, a warning is logged once at start-up (not on every tick)."""
        import main
        import steam_live
        started = []
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "")
        monkeypatch.setattr(main, "_DEMO_MODE", False)
        monkeypatch.setattr(main, "threading", _fake_threading(started))
        monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: list(_MONITORED))

        with caplog.at_level(logging.INFO, logger="main"):
            main._start_background_threads()
            main._live_poll_once()
            main._live_poll_once()

        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno == logging.WARNING and "STEAM_API_KEY" in r.getMessage()]
        assert len(warnings) == 1, warnings
        assert main._live_poll_loop not in started

    def test_current_matches_reports_live_source_not_configured_without_key(self, db, monkeypatch, twitch_env):
        """Failure path: with STEAM_API_KEY unset, GET /twitch/matches/current reports live_source_configured: false."""
        import steam_live
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "")
        monkeypatch.setattr(steam_live, "live_checked_at", None)

        assert _current(db)["live_source_configured"] is False
        _seed_live(db, _LIVE_PAYLOAD[0])
        result = _current(db)
        assert result["series"]
        assert result["live_source_configured"] is False


# ===========================================================================
# Story: Live Matches Appear in the MVP Picker Within a Minute
# ===========================================================================

class TestLiveMatchesAppearWithinAMinute:

    def test_live_poll_loop_calls_live_poll_once_and_waits_live_poll_interval(self, monkeypatch):
        """AC: _live_poll_loop runs _live_poll_once each tick and waits LIVE_POLL_INTERVAL seconds between ticks."""
        import main
        ticks = []
        monkeypatch.setattr(main, "_live_poll_once", lambda: ticks.append(1))
        monkeypatch.setattr(main, "_LIVE_POLL_INTERVAL", 7)
        event = _TwoShotEvent()
        monkeypatch.setattr(main, "_stop_event", event)

        main._live_poll_loop()

        assert len(ticks) == 2
        assert event.wait_calls == [7, 7]

    def test_live_poll_interval_defaults_to_60_seconds(self):
        """AC: LIVE_POLL_INTERVAL defaults to 60."""
        import main
        src = _read(os.path.join(_BACKEND, "main.py"))
        assert re.search(r'_LIVE_POLL_INTERVAL\s*=\s*int\(os\.getenv\("LIVE_POLL_INTERVAL",\s*"60"\)\)', src)
        if "LIVE_POLL_INTERVAL" not in os.environ:
            assert main._LIVE_POLL_INTERVAL == 60

    def test_live_poll_loop_never_waits_on_ingest_enrichment_or_toornament(self):
        """AC: the live thread never waits on ingest, enrichment, parse retries or the Toornament sync (no INGEST_LOCK, _auto_ingest, run_enrichment, retry_unparsed_matches or _run_toornament_sync in _live_poll_loop/_live_poll_once)."""
        import main
        src = inspect.getsource(main._live_poll_loop) + inspect.getsource(main._live_poll_once)
        for name in ("INGEST_LOCK", "_auto_ingest", "ingest_league", "run_enrichment",
                     "retry_unparsed_matches", "_run_toornament_sync"):
            assert name not in src, name

    def test_live_poll_once_stores_games_and_sets_live_checked_at(self, db, monkeypatch):
        """AC: _live_poll_once (key set, leagues monitored) stores the games via store_live_matches and sets _live_checked_at to now."""
        import ingest
        import main
        import steam_live
        from models import LiveMatch, MatchTiming
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")
        monkeypatch.setattr(steam_live, "live_checked_at", None)
        monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: list(_MONITORED))
        monkeypatch.setattr(main.steam_live, "get_live_league_games", lambda league_ids: _parsed_fixture())
        monkeypatch.setattr(ingest, "SessionLocal", lambda: db)

        before = int(time.time())
        main._live_poll_once()
        after = int(time.time())

        db.expire_all()
        assert {r.match_id for r in db.query(LiveMatch).all()} == {8200000001, 8200000002}
        assert before <= steam_live.live_checked_at <= after
        timing = db.get(MatchTiming, 8200000001)
        assert before <= timing.live_first_seen_at <= after

    def test_live_poll_once_skips_when_no_league_monitored(self, monkeypatch):
        """AC: the live check runs only when at least one league is monitored; with none, no Steam request is made."""
        import main
        import steam_live
        calls = _patch_steam(monkeypatch, _FakeResponse(200, _fixture()))
        monkeypatch.setattr(steam_live, "live_checked_at", None)
        monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: [])

        main._live_poll_once()

        assert calls == []
        assert steam_live.live_checked_at is None

    def test_get_live_league_games_single_request_10s_timeout_no_retries(self, monkeypatch):
        """AC: each check makes one Steam request with timeout=10, no retries and no backoff sleeps."""
        import steam_live
        sleeps = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

        calls = _patch_steam(monkeypatch, requests.Timeout("timed out"))
        assert steam_live.get_live_league_games(_MONITORED) is None
        assert len(calls) == 1
        assert calls[0][1]["timeout"] == 10

        calls = _patch_steam(monkeypatch, _FakeResponse(503, None))
        assert steam_live.get_live_league_games(_MONITORED) is None
        assert len(calls) == 1

        calls = _patch_steam(monkeypatch, _FakeResponse(200, _fixture()))
        assert steam_live.get_live_league_games(_MONITORED)
        assert len(calls) == 1
        assert calls[0][1]["timeout"] == 10
        assert sleeps == []

    def test_get_live_league_games_returns_none_on_timeout_or_error_status(self, monkeypatch):
        """AC: a failed check (timeout, connection error, non-200 status, bad JSON) returns None without raising."""
        import steam_live
        for outcome in (
            requests.Timeout("t"),
            requests.ConnectionError("c"),
            RuntimeError("unexpected"),
            _FakeResponse(500, None),
            _FakeResponse(429, None),
            _FakeResponse(200, json_error=ValueError("bad json")),
            _FakeResponse(200, {"result": {"status": 200}}),
            _FakeResponse(200, ["not", "a", "dict"]),
        ):
            _patch_steam(monkeypatch, outcome)
            assert steam_live.get_live_league_games(_MONITORED) is None, outcome

        # An empty but well-formed list is a successful check, not a failure.
        _patch_steam(monkeypatch, _FakeResponse(200, {"result": {"games": []}}))
        assert steam_live.get_live_league_games(_MONITORED) == []

    def test_live_poll_loop_logs_failure_and_retries_next_tick(self, monkeypatch, caplog):
        """AC: a failed check is logged and retried on the next tick; an exception in _live_poll_once does not end the loop."""
        import main
        ticks = []

        def _once():
            ticks.append(1)
            if len(ticks) == 1:
                raise RuntimeError("simulated live check failure")
        monkeypatch.setattr(main, "_live_poll_once", _once)
        event = _TwoShotEvent()
        monkeypatch.setattr(main, "_stop_event", event)

        with caplog.at_level(logging.ERROR, logger="main"):
            main._live_poll_loop()

        assert len(ticks) == 2
        assert event.wait_calls == [main._LIVE_POLL_INTERVAL, main._LIVE_POLL_INTERVAL]
        assert any("Live poll failed" in r.getMessage() for r in caplog.records)

    def test_ingest_poll_loop_makes_no_live_calls(self, db, monkeypatch):
        """AC: _ingest_poll_loop makes no live calls (does not call steam_live or store_live_matches)."""
        import main
        src = inspect.getsource(main._ingest_poll_loop)
        assert "store_live_matches" not in src
        assert "steam_live" not in src

        monkeypatch.setattr(main.steam_live, "get_live_league_games",
                            lambda league_ids: pytest.fail("the ingest loop must not check Steam"))
        monkeypatch.setattr(main, "store_live_matches",
                            lambda *a, **k: pytest.fail("the ingest loop must not store live matches"))

        calls, waits = _run_ingest_loop_once(monkeypatch, db)

        assert calls == [([_MONITORED_LEAGUE], set())]
        assert waits == [main._INGEST_POLL_INTERVAL]

    def test_ingest_poll_loop_uses_live_interval_for_fresh_unended_live_match(self, db, monkeypatch):
        """AC: a live_matches row with ended_at NULL seen in the last 15 minutes counts as live: the loop picks the live-match interval and passes the league to _auto_ingest so enrichment is skipped."""
        import main
        now = int(time.time())
        _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 14 * 60)

        calls, waits = _run_ingest_loop_once(monkeypatch, db)

        assert calls == [([_MONITORED_LEAGUE], {_MONITORED_LEAGUE})]
        assert waits == [main._INGEST_LIVE_MATCH_POLL_INTERVAL]

    def test_ingest_poll_loop_ignores_live_match_last_seen_over_15_minutes_ago(self, db, monkeypatch):
        """AC: an unended row last seen more than 15 minutes ago does not count as live (normal interval, enrichment not skipped)."""
        import main
        now = int(time.time())
        _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 16 * 60)

        calls, waits = _run_ingest_loop_once(monkeypatch, db)

        assert calls == [([_MONITORED_LEAGUE], set())]
        assert waits == [main._INGEST_POLL_INTERVAL]

    def test_live_thread_not_started_in_demo_mode(self, monkeypatch):
        """AC: in DEMO_MODE the live thread does not start, as for the ingest thread."""
        import main
        import steam_live
        started = []
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")
        monkeypatch.setattr(main, "_DEMO_MODE", True)
        monkeypatch.setattr(main, "threading", _fake_threading(started))

        main._start_background_threads()

        assert main._live_poll_loop not in started
        assert main._ingest_poll_loop not in started
        assert main._week_maintenance_loop in started

    def test_live_thread_not_started_without_steam_api_key(self, monkeypatch):
        """AC: the live thread starts only when STEAM_API_KEY is set."""
        import main
        import steam_live
        monkeypatch.setattr(main, "_DEMO_MODE", False)

        started = []
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "")
        monkeypatch.setattr(main, "threading", _fake_threading(started))
        main._start_background_threads()
        assert main._live_poll_loop not in started
        assert main._ingest_poll_loop in started

        started = []
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")
        monkeypatch.setattr(main, "threading", _fake_threading(started))
        main._start_background_threads()
        assert started.count(main._live_poll_loop) == 1

    def test_live_poll_once_steam_failure_leaves_live_matches_unchanged(self, db, monkeypatch):
        """Failure path: when Steam fails (get_live_league_games returns None) live_matches rows are unchanged, ended_at is not set, and _live_checked_at is not updated."""
        import ingest
        import main
        import steam_live
        from models import LiveMatch
        now = int(time.time())
        _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 300)
        columns = [c.name for c in LiveMatch.__table__.columns]
        before = {c: getattr(db.get(LiveMatch, 8100000001), c) for c in columns}

        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")
        monkeypatch.setattr(steam_live, "live_checked_at", 1234)
        monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: [_MONITORED_LEAGUE])
        _patch_steam(monkeypatch, _FakeResponse(502, None))
        monkeypatch.setattr(ingest, "SessionLocal", lambda: db)

        main._live_poll_once()

        db.expire_all()
        row = db.get(LiveMatch, 8100000001)
        assert {c: getattr(row, c) for c in columns} == before
        assert row.ended_at is None
        assert steam_live.live_checked_at == 1234


# ===========================================================================
# Story: See Where the Delay Comes From
# ===========================================================================

class TestSeeWhereTheDelayComesFrom:

    def test_match_timings_table_created_by_create_all(self, db):
        """AC: MatchTiming (match_timings: match_id PK, live_first_seen_at, ingested_at, mvp_confirmed_at, mvp_provisional) exists via create_all with no migration."""
        from sqlalchemy import inspect as sa_inspect
        from models import MatchTiming

        assert MatchTiming.__tablename__ == "match_timings"
        insp = sa_inspect(db.get_bind())
        assert "match_timings" in insp.get_table_names()
        cols = {c["name"] for c in insp.get_columns("match_timings")}
        assert cols == {"match_id", "live_first_seen_at", "ingested_at", "mvp_confirmed_at", "mvp_provisional"}
        assert insp.get_pk_constraint("match_timings")["constrained_columns"] == ["match_id"]
        assert "match_timings" not in _read(os.path.join(_BACKEND, "migrate.py"))

    def test_record_timing_sets_only_null_fields(self, db):
        """AC: record_timing(db, match_id, **fields) sets each field only while it is empty."""
        import ingest
        from models import MatchTiming

        ingest.record_timing(db, 42, live_first_seen_at=100)
        db.commit()
        ingest.record_timing(db, 42, live_first_seen_at=200, ingested_at=300)
        db.commit()
        ingest.record_timing(db, 42, ingested_at=400, mvp_confirmed_at=500, mvp_provisional=False)
        db.commit()
        ingest.record_timing(db, 42, mvp_confirmed_at=600, mvp_provisional=True)
        db.commit()

        db.expire_all()
        row = db.get(MatchTiming, 42)
        assert (row.live_first_seen_at, row.ingested_at, row.mvp_confirmed_at) == (100, 300, 500)
        assert row.mvp_provisional is False
        assert db.query(MatchTiming).count() == 1

    def test_store_live_matches_writes_live_first_seen_at_once(self, db):
        """AC: live_first_seen_at is set on first sight by the live check and not changed by later sightings."""
        import ingest
        from models import MatchTiming

        ingest.store_live_matches(_LIVE_PAYLOAD, [_MONITORED_LEAGUE], db=db, now=1000)
        ingest.store_live_matches(_LIVE_PAYLOAD, [_MONITORED_LEAGUE], db=db, now=2000)

        db.expire_all()
        assert db.get(MatchTiming, 8100000001).live_first_seen_at == 1000
        assert db.get(MatchTiming, 8100000002).live_first_seen_at == 1000
        assert db.get(MatchTiming, 8100000003) is None  # unmonitored league
        assert db.get(MatchTiming, 8100000001).ingested_at is None

    def test_ingest_match_writes_ingested_at(self, db, monkeypatch):
        """AC: ingest_match() sets match_timings.ingested_at when stats are written."""
        import ingest
        from models import MatchTiming, PlayerMatchStats, Weight
        _add_mvp_weight(db)
        now = int(time.time())
        ingest.store_live_matches([_LIVE_PAYLOAD[0]], [_MONITORED_LEAGUE], db=db, now=now - 2400)
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, label=None: _match_payload(now - 2400))
        monkeypatch.setattr(ingest, "request_parse", lambda match_id: True)
        weights = {w.key: w.value for w in db.query(Weight).all()}

        before = int(time.time())
        ingest.ingest_match(db, 8100000001, _MONITORED_LEAGUE, set(), set(), weights)
        after = int(time.time())

        db.expire_all()
        assert db.query(PlayerMatchStats).filter_by(match_id=8100000001).count() == 2
        timing = db.get(MatchTiming, 8100000001)
        assert before <= timing.ingested_at <= after
        assert timing.live_first_seen_at == now - 2400

    def test_set_mvp_on_provisional_match_writes_mvp_confirmed_at_and_provisional_true(self, db, monkeypatch, twitch_env):
        """AC: POST /twitch/mvp on a match confirmed before ingest sets mvp_confirmed_at and mvp_provisional=true."""
        from models import MatchTiming
        _seed_live(db, _LIVE_PAYLOAD[0])

        before = int(time.time())
        _call_set_mvp(db, 8100000001, 500)
        after = int(time.time())

        db.expire_all()
        timing = db.get(MatchTiming, 8100000001)
        assert before <= timing.mvp_confirmed_at <= after
        assert timing.mvp_provisional is True

    def test_set_mvp_on_ingested_match_records_provisional_false(self, db, monkeypatch, twitch_env):
        """AC: POST /twitch/mvp on an already-ingested match sets mvp_provisional=false."""
        from models import MatchTiming
        _add_mvp_weight(db)
        _seed_match(db, 9001, 11, 12, int(time.time()) - 600, player_ids=(500, 510))

        _call_set_mvp(db, 9001, 500)

        db.expire_all()
        timing = db.get(MatchTiming, 9001)
        assert timing.mvp_confirmed_at is not None
        assert timing.mvp_provisional is False

    def test_set_mvp_reselect_keeps_first_mvp_confirmed_at(self, db, monkeypatch, twitch_env):
        """AC: mvp_confirmed_at is the first confirmation; re-selecting the MVP later does not move it."""
        from models import MatchTiming
        _seed_live(db, _LIVE_PAYLOAD[0])
        _call_set_mvp(db, 8100000001, 500)
        db.query(MatchTiming).filter_by(match_id=8100000001).update({MatchTiming.mvp_confirmed_at: 12345})
        db.commit()

        _call_set_mvp(db, 8100000001, 501)

        db.expire_all()
        timing = db.get(MatchTiming, 8100000001)
        assert timing.mvp_confirmed_at == 12345
        assert timing.mvp_provisional is True

    def test_admin_matches_includes_timing_fields(self, db):
        """AC: GET /admin/matches includes live_first_seen_at, ingested_at and mvp_confirmed_at for each match."""
        from models import MatchTiming
        from routers import admin_matches
        _seed_match(db, 9001, 11, 12, 1000, player_ids=(500,))
        _seed_match(db, 9002, 13, 14, 2000, player_ids=(600,))
        db.add(MatchTiming(match_id=9001, live_first_seen_at=1120, ingested_at=4480,
                           mvp_confirmed_at=3000, mvp_provisional=True))
        db.commit()

        rows = {r["match_id"]: r for r in admin_matches.list_matches(db=db, _={})}

        assert (rows[9001]["live_first_seen_at"], rows[9001]["ingested_at"], rows[9001]["mvp_confirmed_at"]) == \
            (1120, 4480, 3000)
        for key in ("live_first_seen_at", "ingested_at", "mvp_confirmed_at"):
            assert key in rows[9002]

    def test_admin_matches_js_renders_timing_columns_as_minutes_after_start(self):
        """AC: the admin Matches table shows "Live seen", "Stats in", "MVP picked" as "+N min" after start_time, with the exact time in the title attribute."""
        html = _read(_INDEX_HTML)
        head = re.search(r'<table id="admin-matches-table">\s*<thead><tr>(.*?)</tr></thead>', html).group(1)
        headers = re.findall(r"<th>(.*?)</th>", head)
        assert headers[headers.index("Start Time") + 1:headers.index("Start Time") + 4] == \
            ["Live seen", "Stats in", "MVP picked"]
        assert f'colspan="{len(headers)}"' in html[html.index('id="adminMatchesBody"') - 30:][:200]

        js = _read(_ADMIN_MATCHES_JS)
        render = _function_source(js, "renderAdminMatches")
        assert render.index("m.live_first_seen_at") < render.index("m.ingested_at") < render.index("m.mvp_confirmed_at")
        assert f"colspan='{len(headers)}'" in render
        cell = _function_source(js, "_timingCell")
        assert "title=" in cell and "_escHtml(" in cell

        out = _timing_cells([[1000 + 120, 1000], [1000 + 58 * 60, 1000], [1000 + 89, 1000], [1000 - 120, 1000]])
        if out is None:
            return
        assert ">+2 min</td>" in out[0]
        assert ">+58 min</td>" in out[1]
        assert ">+1 min</td>" in out[2]
        assert ">−2 min</td>" in out[3]
        assert all('title="' in c for c in out)

    def test_admin_matches_never_seen_live_has_null_live_first_seen_at(self, db):
        """Failure path: a match never seen live returns live_first_seen_at null from GET /admin/matches."""
        import ingest
        from routers import admin_matches
        _seed_match(db, 9001, 11, 12, 1000, player_ids=(500,))
        ingest.record_timing(db, 9001, ingested_at=4000)
        db.commit()

        row = admin_matches.list_matches(db=db, _={})[0]

        assert row["live_first_seen_at"] is None
        assert row["ingested_at"] == 4000
        assert row["mvp_confirmed_at"] is None

    def test_admin_matches_js_shows_dash_for_unknown_timing(self):
        """Failure path: an unknown timing (never seen live) renders as "—" under "Live seen"."""
        cell = _function_source(_read(_ADMIN_MATCHES_JS), "_timingCell")
        assert "—" in cell

        out = _timing_cells([[None, 1000], [0, 1000], [2000, None]])
        if out is None:
            return
        assert out[0] == '<td style="font-size:0.8rem;">—</td>'
        assert out[1] == out[0]
        assert ">—</td>" in out[2] and "min" not in out[2]


# ===========================================================================
# Story: Casters Can See How Fresh the Match List Is
# ===========================================================================

class TestCastersSeeMatchListFreshness:

    def test_current_matches_includes_live_checked_at_and_live_source_configured(self, db, monkeypatch, twitch_env):
        """AC: GET /twitch/matches/current returns live_checked_at (Unix time of last successful check) and live_source_configured (true when STEAM_API_KEY is set)."""
        import steam_live
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")
        monkeypatch.setattr(steam_live, "live_checked_at", 1790000000)

        empty = _current(db)
        assert empty["series"] == []
        assert (empty["live_checked_at"], empty["live_source_configured"]) == (1790000000, True)

        _seed_live(db, _LIVE_PAYLOAD[0])
        result = _current(db)
        assert result["series"]
        assert (result["live_checked_at"], result["live_source_configured"]) == (1790000000, True)

    def test_current_matches_live_checked_at_null_before_first_check(self, db, monkeypatch, twitch_env):
        """AC: live_checked_at is null when no live check has succeeded since start-up."""
        import steam_live
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")
        monkeypatch.setattr(steam_live, "live_checked_at", None)
        _seed_live(db, _LIVE_PAYLOAD[0])

        result = _current(db)

        assert result["live_checked_at"] is None
        assert json.loads(json.dumps(result))["live_checked_at"] is None

    def test_live_config_js_shows_checked_ago_line_and_refresh_button(self):
        """AC: the series list shows "Live games checked N s ago" / "N min ago" and a Refresh button that calls loadSeries() again."""
        html = _read(_LIVE_CONFIG_HTML)
        step1 = html[html.index('id="mvp-step-1"'):html.index('id="mvp-step-2"')]
        assert 'id="live-freshness"' in step1
        assert re.search(r'<button[^>]*id="btn-refresh-series"[^>]*>Refresh</button>', step1)
        js = _read(_LIVE_CONFIG_JS)
        assert 'el("btn-refresh-series").addEventListener("click", loadSeries);' in js
        assert "Live games checked " in js

        steps = """
        var now = Math.floor(Date.now() / 1000);
        nextResponse = function() { return Promise.resolve({series: [], live_checked_at: now - 30, live_source_configured: true}); };
        loadSeries(); await tick();
        out.seconds = line();
        nextResponse = function() { return Promise.resolve({series: [], live_checked_at: now - 150, live_source_configured: true}); };
        el("btn-refresh-series").listeners.click[0](); await tick();
        out.minutes = line();
        out.requests = requests;
        out.fn = [liveFreshness({live_checked_at: 1000, live_source_configured: true}, 1030),
                  liveFreshness({live_checked_at: 1000, live_source_configured: true}, 1000 + 299)];
        """
        out = _run_live_config(steps)
        if out is None:
            return
        assert out["seconds"]["text"] in ("Live games checked 30 s ago", "Live games checked 31 s ago")
        assert out["seconds"]["warn"] is False
        assert out["minutes"]["text"] == "Live games checked 2 min ago"
        assert out["requests"] == 2
        assert out["fn"][0] == {"text": "Live games checked 30 s ago", "warn": False}
        assert out["fn"][1] == {"text": "Live games checked 4 min ago", "warn": False}

    def test_live_config_js_warns_when_stale_null_or_not_configured(self):
        """AC: when live_checked_at is over 5 minutes old or null, or the source is not configured, the line reads "Live games not checked recently — your match will appear once its stats are in" in the warning colour."""
        html = _read(_LIVE_CONFIG_HTML)
        assert re.search(r"\.freshness\.warn\s*\{\s*color:\s*#d29922;", html)
        js = _read(_LIVE_CONFIG_JS)
        assert _WARNING_TEXT in js

        steps = """
        out.cases = [
          liveFreshness({live_checked_at: 1000, live_source_configured: true}, 1000 + 301),
          liveFreshness({live_checked_at: null, live_source_configured: true}, 2000),
          liveFreshness({live_checked_at: 1990, live_source_configured: false}, 2000),
          liveFreshness({}, 2000)
        ];
        nextResponse = function() { return Promise.resolve({series: [], live_checked_at: null, live_source_configured: true}); };
        loadSeries(); await tick();
        out.rendered = line();
        """
        out = _run_live_config(steps)
        if out is None:
            return
        for case in out["cases"]:
            assert case == {"text": _WARNING_TEXT, "warn": True}
        assert out["rendered"] == {"text": _WARNING_TEXT, "warn": True}

    def test_live_config_js_refresh_button_stays_usable_after_request_error(self):
        """Failure path: if the request fails the panel shows its existing error state and the Refresh button stays usable."""
        html = _read(_LIVE_CONFIG_HTML)
        step1 = html[html.index('id="mvp-step-1"'):html.index('id="mvp-step-2"')]
        # The button is static markup outside #series-list, which the error state replaces.
        assert step1.index('id="btn-refresh-series"') < step1.index('id="series-list"')
        load = _function_source(_read(_LIVE_CONFIG_JS), "loadSeries")
        assert "Failed to load matches." in load
        assert re.search(r"\.finally\(function\(\)\s*\{\s*refreshBtn\.disabled = false;", load)

        steps = """
        nextResponse = function() { return Promise.reject(new Error("network")); };
        loadSeries();
        out.disabledWhileLoading = el("btn-refresh-series").disabled;
        await tick();
        out.list = el("series-list").innerHTML;
        out.disabledAfter = el("btn-refresh-series").disabled;
        nextResponse = function() { return Promise.resolve({series: [], live_checked_at: Math.floor(Date.now() / 1000), live_source_configured: true}); };
        el("btn-refresh-series").listeners.click[0](); await tick();
        out.requests = requests;
        out.listAfterRetry = el("series-list").innerHTML;
        """
        out = _run_live_config(steps)
        if out is None:
            return
        assert out["disabledWhileLoading"] is True
        assert "Failed to load matches." in out["list"]
        assert out["disabledAfter"] is False
        assert out["requests"] == 2
        assert "No recent matches found" in out["listAfterRetry"]


class TestApiKeysStayOutOfDebugLogs:
    """Security review follow-up: with DEBUG=true the root logger runs at DEBUG, and
    urllib3's connectionpool DEBUG line logs the full request URL, query string (and
    so STEAM_API_KEY / OPENDOTA_API_KEY) included."""

    def test_urllib3_debug_lines_disabled_even_when_root_logs_debug(self, caplog):
        """Importing main pins the urllib3 logger at INFO, so its request-URL DEBUG line never reaches the logs, even with the root logger at DEBUG."""
        import logging
        import main  # noqa: F401  (the import sets the level)

        root = logging.getLogger()
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            pool = logging.getLogger("urllib3.connectionpool")
            assert pool.getEffectiveLevel() >= logging.INFO
            assert not pool.isEnabledFor(logging.DEBUG)
            with caplog.at_level(logging.DEBUG):
                pool.debug('https://api.steampowered.com:443 "GET /x?key=SECRETKEY HTTP/1.1" 200 None')
            assert "SECRETKEY" not in caplog.text
        finally:
            root.setLevel(old)
