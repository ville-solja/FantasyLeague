"""
Failing test stubs for plan-issue-146-mock-opendota.md (resolves GitHub issue #146).

A local stand-in for OpenDota and Steam's GetLiveLeagueGames (`tools/mock_opendota/`)
that the app's real polling code ingests from. `OPENDOTA_BASE_URL` and `STEAM_LIVE_URL`
replace the hard-coded addresses; Demo Mode skips polling only with the real OpenDota
address; `ENV=production` refuses non-https addresses. The plan has one user story with
six acceptance criteria: one class per criterion (happy path plus the primary failure
path), then classes for the testable Verification bullets.

Developer notes
---------------

  What exists today (verified 2026-11-18)
    - `opendota_client.OPEN_DOTA_URL` is a literal at line ~87. `ingest.py` and
      `enrich.py` import it by name (`from opendota_client import OPEN_DOTA_URL`), so a
      test that changes the base must patch `ingest.OPEN_DOTA_URL` / `enrich.OPEN_DOTA_URL`
      too, or check the env setting in a subprocess (preferred for "read at import":
      never `importlib.reload(opendota_client)` in-process, it leaks into other tests
      under xdist workers).
    - `steam_live._URL` is a literal; `steam_live.STEAM_API_KEY` is read at import
      (patch the attribute, see test_issue_161_mvp_selection_delays.py).
    - The only other `api.opendota.com` literal is `backend/scripts/test_match_team_logos.py`
      (a manual script). The literal-scan test covers app modules (`backend/*.py`,
      `backend/routers/*.py`); decide whether the script reads `OPEN_DOTA_URL` too and
      widen the scan if so.
    - `main._start_background_threads` (main.py ~line 470) checks `if _DEMO_MODE:`; the
      new rule is `_DEMO_MODE and opendota_client.is_default_base_url()`.
    - Production guards live in the `if os.getenv("ENV", "").lower() == "production":`
      block at main.py ~line 575.

  Importing the mock app (tools/mock_opendota/app.py, not written yet)
    - Load it by file path under a unique module name so it can't collide with any
      other `app` module:
          _MOCK_DIR = os.path.join(_ROOT, "tools", "mock_opendota")
          spec = importlib.util.spec_from_file_location("mock_opendota_app",
                                                        os.path.join(_MOCK_DIR, "app.py"))
      `backend/` is already on sys.path (below), so the mock's
      `import season_generator` / `import scenarios` resolves the same way it does from
      the `/backend:ro` mount in Compose (the mock should insert `/backend` or
      `../../backend` on sys.path itself when it isn't importable).
    - Give the mock a factory, e.g. `create_app(seed: int | None = None)`, that builds a
      fresh in-memory state per call; tests call it per test (no module-level state
      shared between tests or xdist workers). `MOCK_SEED` is read by the factory when
      `seed` is None. Wrap it with `fastapi.testclient.TestClient`.

  Routing the app's HTTP at the mock (no real network)
    - Patch `opendota_client.requests.get` / `requests.post` and
      `steam_live.requests.get` with a small adapter that strips the configured base
      (`opendota_client.OPEN_DOTA_URL`, `steam_live._URL` minus its path) and forwards
      path + params to the mock's TestClient, returning its response (it has
      `status_code` and `.json()`, which is all the callers read). Fail the test on any
      URL that doesn't start with a mock base. Put this in a `_route_to_mock(monkeypatch,
      client, base="http://mock:8090")` helper and use a mock base, not the default, so
      the transport also proves the setting is honoured.
    - Zero the OpenDota throttle and backoff: `monkeypatch.setattr(opendota_client,
      "_req_times", [])`, and patch `opendota_client.time.sleep` to a no-op; reset
      `ingest._parse_requested` to `{}` (see test_opendota_parse_retry.py).
    - `ingest_league()` and `retry_unparsed_matches()` open their own session: patch
      `ingest.SessionLocal` with `lambda: db` (test_opendota_parse_retry.py docstring).
      Patch `enrich.run_enrichment` / `main.run_enrichment` to a no-op unless a test needs
      it, so the ingest pass makes only the calls under test.
    - `_live_poll_once`: patch `main._get_monitored_league_ids` to
      `lambda: [scenarios.SCENARIO_LEAGUE_ID]`, `steam_live.STEAM_API_KEY` to "mock",
      and route `store_live_matches`'s session at `db` (`ingest.SessionLocal`).
    - Twitch panel: call `twitch.current_matches(payload=dict(_BROADCASTER), db=db)`
      like test_issue_139_early_mvp_selection.py (`_BROADCASTER` and its channel
      approval setup are there); the live game's entry has `"provisional": True`.
    - Expected points: compare stored `PlayerMatchStats.fantasy_points` against
      `scoring` applied to the mock's own match JSON with the seeded weights (seed them
      the way test_opendota_parse_retry.py does), never against hand-typed numbers.
    - Scenario rosters: the default script must equal the mid-season scenario's
      unplayed weeks, i.e. `season_generator.generate(seed=SCENARIOS["mid-season"]
      ["seed"], **scenarios._SEASON, ...)` weeks 6..10 in league
      `scenarios.SCENARIO_LEAGUE_ID` (990001). Build the expectation from the generator
      rather than copying ids.

  Startup guards (subprocess import of main)
    - Copy `_run_import_main(tmp_path, env)` from test_issue_136_security_audit_3.py
      (pops ENV/DEBUG/TWITCH_LOCAL_DEV/SECRET_KEY, sets a tmp DATABASE_URL and
      HTTPS_ONLY=true) and its `_LONG_SECRET`. Expect returncode != 0, "RuntimeError",
      "[SECURITY]" and the variable name in stderr.

  Polling rule
    - Call `main._start_background_threads()` with `main.threading.Thread` patched to a
      recorder (record `target`, don't start), `main._DEMO_MODE` patched, and
      `opendota_client.OPEN_DOTA_URL` patched (default vs "http://mock:8090");
      `steam_live.STEAM_API_KEY` set so the live thread is eligible. Assert on the
      recorded targets (`main._ingest_poll_loop`, `main._live_poll_loop`) and on the log
      line with `caplog`.

  Files read as text: `docker-compose.mock.yml`, `tools/mock_opendota/README.md`,
  `Dockerfile`, `.env.example`, `markdown/features/reference/testing-tooling.md`.
  Parse the Compose file with `yaml.safe_load` if PyYAML is installed, otherwise regex.
"""

import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

import enrich
import ingest
import models  # noqa: F401  — registers every table for the db fixture
import opendota_client
import player_lookup
import scenarios
import scoring
import season_generator
import steam_live
from models import League, LiveMatch, Match, PlayerMatchStats, Weight

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ROOT = os.path.dirname(_BACKEND_DIR)
_MOCK_DIR = os.path.join(_ROOT, "tools", "mock_opendota")
_MOCK_BASE = "http://mock:8090"
_STEAM_PATH = "/IDOTA2Match_570/GetLiveLeagueGames/v1/"
_LEAGUE = scenarios.SCENARIO_LEAGUE_ID
_LONG_SECRET = "x" * 40
_BROADCASTER = {"channel_id": "test_channel", "role": "broadcaster", "opaque_user_id": "Utest"}
# Wide enough to re-check scripted matches dated in 2026 against the real clock.
_RETRY_HOURS = 87600
_ADDRESS_VARS = ("OPENDOTA_BASE_URL", "STEAM_LIVE_URL", "STEAM_API_KEY", "DEMO_MODE")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_module():
    name = "mock_opendota_app"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_MOCK_DIR, "app.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _client(seed=None, now=None, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.delenv("MOCK_SEED", raising=False)
    return TestClient(_mock_module().create_app(seed=seed, now=now))


def _release(client, unparsed=False):
    res = client.post("/_control/next-match", json={"unparsed": unparsed})
    assert res.status_code == 200, res.text
    return res.json()["match_id"]


def _expected_script(seed=None):
    """The mid-season scenario's unplayed weeks, built from the generator itself."""
    spec = dict(scenarios.SCENARIOS["mid-season"])
    s, locked = spec.pop("seed"), spec.pop("locked_weeks")
    season = season_generator.generate(s, users=len(scenarios.ACCOUNT_NAMES),
                                       **scenarios._SEASON, **spec)
    return season, locked


def _route_to_mock(monkeypatch, client, base=_MOCK_BASE):
    """Send the app's requests.get/post to the mock's TestClient. Returns (calls, stray):
    every (method, url) requested, and the URLs outside the mock base (which also raise)."""
    calls, stray = [], []

    def _send(method, url, params=None, **_kw):
        calls.append((method, url))
        if not url.startswith(base + "/"):
            stray.append(url)
            raise AssertionError(f"request outside the mock: {url}")
        return client.request(method, url[len(base):], params=params or None)

    monkeypatch.setattr(opendota_client.requests, "get", lambda url, **kw: _send("GET", url, **kw))
    monkeypatch.setattr(opendota_client.requests, "post", lambda url, **kw: _send("POST", url, **kw))
    return calls, stray


def _use_mock_base(monkeypatch, base=_MOCK_BASE):
    """Point every module's copy of OPEN_DOTA_URL, and steam_live._URL, at the mock."""
    for mod in list(sys.modules.values()):
        try:
            value = getattr(mod, "OPEN_DOTA_URL", None)
        except Exception:
            continue
        if value == opendota_client.DEFAULT_OPEN_DOTA_URL:
            monkeypatch.setattr(mod, "OPEN_DOTA_URL", base)
    monkeypatch.setattr(steam_live, "_URL", base + _STEAM_PATH)


def _wire(monkeypatch, db, client):
    """The mock as the app's OpenDota and Steam, the test db as every session, no throttle."""
    _use_mock_base(monkeypatch)
    calls, stray = _route_to_mock(monkeypatch, client)
    monkeypatch.setattr(opendota_client, "_req_times", [])
    monkeypatch.setattr(opendota_client, "throttle", lambda cost=1: None)
    monkeypatch.setattr(ingest, "_parse_requested", {})
    monkeypatch.setattr(ingest, "_league_status", {})
    monkeypatch.setattr(ingest, "SessionLocal", lambda: db)
    monkeypatch.setattr(ingest, "ensure_dotabuff_league_logos", lambda: None)
    monkeypatch.setattr(enrich, "SessionLocal", lambda: db)
    return calls, stray


def _seed_weights(db):
    from seed import DEFAULT_WEIGHTS
    for w in DEFAULT_WEIGHTS:
        db.add(Weight(key=w["key"], label=w["label"], value=w["value"]))
    db.add(League(id=_LEAGUE, name=scenarios.SCENARIO_LEAGUE_NAME, is_monitored=True))
    db.commit()
    return {w.key: w.value for w in db.query(Weight).all()}


def _expected_points(match_json, weights):
    return {p["account_id"]: scoring.fantasy_score(
        {**p, "courier_kills": int(p.get("courier_kills") or 0)}, weights)
        for p in match_json["players"]}


def _stored_points(db, match_id):
    db.expire_all()
    return {r.player_id: r.fantasy_points
            for r in db.query(PlayerMatchStats).filter_by(match_id=match_id).all()}


def _subprocess(code, env_overrides):
    env = {k: v for k, v in os.environ.items() if k not in _ADDRESS_VARS}
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR, env=env,
                          capture_output=True, text=True, timeout=120)


def _run_import_main(tmp_path, env_overrides):
    """`import main` in a subprocess (as test_issue_136_security_audit_3.py)."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("ENV", "DEBUG", "TWITCH_LOCAL_DEV", "SECRET_KEY", "AUTO_INGEST_LEAGUES")
        + _ADDRESS_VARS
    }
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'fantasy.db'}"
    env["HTTPS_ONLY"] = "true"
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _fake_threading(started):
    class _FakeThread:
        def __init__(self, target=None, daemon=None, **kwargs):
            self.target = target

        def start(self):
            started.append(self.target)
    return SimpleNamespace(Thread=_FakeThread)


def _start_threads(monkeypatch, demo, base, steam_url=None, key="mock"):
    import main
    started = []
    monkeypatch.setattr(main, "_DEMO_MODE", demo)
    monkeypatch.setattr(opendota_client, "OPEN_DOTA_URL", base)
    monkeypatch.setattr(steam_live, "_URL", steam_url or steam_live.DEFAULT_URL)
    monkeypatch.setattr(steam_live, "STEAM_API_KEY", key)
    monkeypatch.setattr(main, "threading", _fake_threading(started))
    main._start_background_threads()
    return main, started


# ---------------------------------------------------------------------------
# AC 1 — OPENDOTA_BASE_URL and STEAM_LIVE_URL replace the hard-coded addresses
# ---------------------------------------------------------------------------

_PRINT_BASE = ("import json, opendota_client; "
               "print(json.dumps([opendota_client.OPEN_DOTA_URL, opendota_client.is_default_base_url()]))")


class TestConfigurableAddresses:

    def test_opendota_base_url_defaults_to_real_api(self, tmp_path):
        """Without OPENDOTA_BASE_URL, opendota_client.OPEN_DOTA_URL is https://api.opendota.com/api and is_default_base_url() is True (subprocess import)."""
        res = _subprocess(_PRINT_BASE, {})
        assert res.returncode == 0, res.stderr
        assert json.loads(res.stdout) == ["https://api.opendota.com/api", True]

    def test_opendota_base_url_env_overrides_and_strips_trailing_slash(self, tmp_path):
        """OPENDOTA_BASE_URL=http://mock:8090/ gives OPEN_DOTA_URL == 'http://mock:8090' and is_default_base_url() False (subprocess import)."""
        res = _subprocess(_PRINT_BASE, {"OPENDOTA_BASE_URL": "http://mock:8090/"})
        assert res.returncode == 0, res.stderr
        assert json.loads(res.stdout) == ["http://mock:8090", False]

    def test_steam_live_url_defaults_to_get_live_league_games(self, tmp_path):
        """Without STEAM_LIVE_URL, steam_live._URL is Steam's https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/ (subprocess import)."""
        res = _subprocess("import steam_live; print(steam_live._URL); print(steam_live.is_default_url())", {})
        assert res.returncode == 0, res.stderr
        assert res.stdout.split() == [
            "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/", "True"]

    def test_steam_live_url_env_overrides(self, tmp_path):
        """STEAM_LIVE_URL=http://mock:8090/IDOTA2Match_570/GetLiveLeagueGames/v1/ is the address get_live_league_games requests (subprocess + recorder)."""
        code = (
            "import steam_live\n"
            "seen = []\n"
            "class R:\n"
            "    status_code = 200\n"
            "    def json(self): return {'result': {'games': []}}\n"
            "steam_live.requests.get = lambda url, **kw: seen.append(url) or R()\n"
            "print(steam_live.get_live_league_games([1]))\n"
            "print(seen[0])\n"
        )
        url = _MOCK_BASE + _STEAM_PATH
        res = _subprocess(code, {"STEAM_LIVE_URL": url, "STEAM_API_KEY": "mock"})
        assert res.returncode == 0, res.stderr
        assert res.stdout.split() == ["[]", url]

    def test_every_opendota_call_uses_configured_base(self, db, monkeypatch):
        """With the base patched to the mock address, an ingest pass, a parse request, enrichment and player lookup request only URLs under that base; a URL under api.opendota.com fails the transport."""
        client = _client(monkeypatch=monkeypatch)
        calls, stray = _wire(monkeypatch, db, client)
        _seed_weights(db)
        mid = _release(client, unparsed=True)

        ingest.ingest_league(_LEAGUE)
        monkeypatch.setattr(ingest, "_parse_requested", {})
        assert ingest.request_parse(mid) is True
        db.query(models.Player).update({"avatar_url": None})
        db.commit()
        assert enrich.enrich_players() == 10
        assert enrich._fetch_hero_name_map()[1] == "Mock Hero 1"
        player_lookup.clear_lookup_cache()
        try:
            found, name, _, _ = player_lookup.opendota_lookup(1001)
        finally:
            player_lookup.clear_lookup_cache()
        assert found and name

        paths = {url[len(_MOCK_BASE):].split("?")[0] for _, url in calls}
        assert {f"/leagues/{_LEAGUE}", f"/leagues/{_LEAGUE}/matchIds", f"/matches/{mid}",
                f"/request/{mid}", "/constants/heroes", "/players/1001"} <= paths
        assert stray == []
        assert all(url.startswith(_MOCK_BASE + "/") for _, url in calls)

        with pytest.raises(AssertionError):
            opendota_client.requests.get("https://api.opendota.com/api/heroes")
        assert stray == ["https://api.opendota.com/api/heroes"]

    @pytest.mark.parametrize("url", [
        "https://api.opendota.com/api", "http://api.opendota.com/api",
        "https://API.OpenDota.com/api", "https://api.opendota.com:443/api",
        "https://api.opendota.com", "https://api.opendota.com./api/",
    ])
    def test_real_opendota_spellings_count_as_default(self, monkeypatch, url):
        """Security review: any spelling of the real OpenDota host (scheme, case, port, path) counts as the default, so Demo Mode never polls the real API."""
        monkeypatch.setattr(opendota_client, "OPEN_DOTA_URL", url)
        assert opendota_client.is_default_base_url() is True

    @pytest.mark.parametrize("url", [
        "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/",
        "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1",
        "http://API.SteamPowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/",
        "https://api.steampowered.com:443/IDOTA2Match_570/GetLiveLeagueGames/v1/",
    ])
    def test_real_steam_spellings_count_as_default(self, monkeypatch, url):
        """Security review: any spelling of Steam's host counts as the default STEAM_LIVE_URL."""
        monkeypatch.setattr(steam_live, "_URL", url)
        assert steam_live.is_default_url() is True

    @pytest.mark.parametrize("url", [_MOCK_BASE, "http://mock_opendota:8090",
                                     "https://opendota.example.org/api", "http://127.0.0.1:8090"])
    def test_other_hosts_are_not_default(self, monkeypatch, url):
        """A mock or any other host is not the default, for both settings."""
        monkeypatch.setattr(opendota_client, "OPEN_DOTA_URL", url)
        monkeypatch.setattr(steam_live, "_URL", url + _STEAM_PATH)
        assert opendota_client.is_default_base_url() is False
        assert steam_live.is_default_url() is False

    def test_demo_mode_with_real_host_spelling_skips_polling(self, monkeypatch):
        """DEMO_MODE=true with http://API.opendota.com:443/api starts neither poll thread."""
        main, started = _start_threads(monkeypatch, True, "http://API.opendota.com:443/api",
                                       steam_url=_MOCK_BASE + _STEAM_PATH)
        assert main._ingest_poll_loop not in started and main._live_poll_loop not in started
        main, started = _start_threads(monkeypatch, True, _MOCK_BASE,
                                       steam_url="https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1")
        assert main._ingest_poll_loop in started and main._live_poll_loop not in started

    def test_no_opendota_literal_outside_opendota_client(self):
        """No backend app module (backend/*.py, backend/routers/*.py) other than opendota_client.py contains the literal 'api.opendota.com'."""
        offenders = []
        for folder in ("", "routers", "scripts"):
            path = os.path.join(_BACKEND_DIR, folder)
            for name in sorted(os.listdir(path)):
                if not name.endswith(".py") or (folder == "" and name == "opendota_client.py"):
                    continue
                with open(os.path.join(path, name), encoding="utf-8") as f:
                    if re.search(r"api\.opendota\.com", f.read()):
                        offenders.append(os.path.join(folder, name))
        assert offenders == []


# ---------------------------------------------------------------------------
# AC 2 — The mock serves the paths the app calls, in the shapes the app reads
# ---------------------------------------------------------------------------

class TestMockServesAppPaths:

    def test_mock_app_importable_without_network(self, monkeypatch):
        """tools/mock_opendota/app.py loads by file path and create_app() builds a FastAPI app with in-memory state (no outbound calls)."""
        from fastapi import FastAPI

        def _no_network(*a, **k):
            raise AssertionError("the mock made an outbound call")
        monkeypatch.setattr(opendota_client.requests, "get", _no_network)
        monkeypatch.setattr(opendota_client.requests, "post", _no_network)
        monkeypatch.delenv("MOCK_SEED", raising=False)
        mock = _mock_module()
        app_a, app_b = mock.create_app(), mock.create_app()
        assert isinstance(app_a, FastAPI)
        assert app_a.state.mock is not app_b.state.mock
        TestClient(app_a).post("/_control/next-match")
        assert TestClient(app_b).get("/_control/state").json()["released"] == []

    def test_mock_league_info_returns_league_name(self, monkeypatch):
        """GET /leagues/990001 answers 200 with a dict that has 'leagueid' and 'name' as ingest.get_league_info reads them."""
        client = _client(monkeypatch=monkeypatch)
        res = client.get(f"/leagues/{_LEAGUE}")
        assert res.status_code == 200
        assert res.json()["leagueid"] == _LEAGUE
        assert res.json()["name"] == scenarios.SCENARIO_LEAGUE_NAME
        assert client.get("/leagues/12345").status_code == 404

    def test_mock_match_ids_lists_only_released_matches(self, monkeypatch):
        """GET /leagues/990001/matchIds is empty before any release and lists exactly the released match ids after POST /_control/next-match."""
        client = _client(monkeypatch=monkeypatch)
        assert client.get(f"/leagues/{_LEAGUE}/matchIds").json() == []
        first, second = _release(client), _release(client)
        assert client.get(f"/leagues/{_LEAGUE}/matchIds").json() == [first, second]

    def test_mock_match_detail_has_ingest_fields(self, monkeypatch):
        """GET /matches/{id} of a released match has match_id, start_time, duration, radiant_win, radiant/dire team ids and names, picks_bans and 10 players with account_id, isRadiant, player_slot, hero_id, personaname and every scored stat."""
        client = _client(monkeypatch=monkeypatch)
        mid = _release(client)
        res = client.get(f"/matches/{mid}")
        assert res.status_code == 200
        data = res.json()
        for key in ("match_id", "start_time", "duration", "radiant_win", "radiant_team_id",
                    "dire_team_id", "radiant_name", "dire_name", "picks_bans"):
            assert key in data, key
        assert data["match_id"] == mid
        assert data["duration"] >= ingest.MIN_MATCH_SECONDS
        assert any(not pb["is_pick"] for pb in data["picks_bans"])
        assert len(data["players"]) == 10
        for p in data["players"]:
            for key in ("account_id", "isRadiant", "player_slot", "hero_id", "personaname",
                        "deaths", *scoring.SCORING_STATS):
                assert key in p, key
        radiant = [p for p in data["players"] if p["isRadiant"]]
        assert sorted(p["player_slot"] for p in radiant) == [0, 1, 2, 3, 4]
        assert ingest._is_unparsed(data) is False

    def test_mock_unreleased_match_returns_404(self, monkeypatch):
        """GET /matches/{id} of a scripted but unreleased match, or an unknown id, answers 404 like OpenDota."""
        client = _client(monkeypatch=monkeypatch)
        scripted = _mock_module().build_script()["matches"][0]["match_id"]
        assert client.get(f"/matches/{scripted}").status_code == 404
        assert client.get("/matches/123").status_code == 404

    def test_mock_unparsed_match_omits_parsed_only_stats(self, monkeypatch):
        """A match released unparsed omits the parsed-only stats (everything outside season_generator.UNPARSED_STATS), so ingest._is_unparsed(data) is True."""
        client = _client(monkeypatch=monkeypatch)
        mid = _release(client, unparsed=True)
        data = client.get(f"/matches/{mid}").json()
        assert ingest._is_unparsed(data) is True
        parsed_only = set(scoring.SCORING_STATS) - set(season_generator.UNPARSED_STATS)
        for p in data["players"]:
            assert not parsed_only & set(p), parsed_only & set(p)
            for key in season_generator.UNPARSED_STATS:
                assert key in p

    def test_mock_request_parse_answers_like_opendota_job(self, monkeypatch):
        """POST /request/{id} answers 200 with an OpenDota-style job body ({'job': {'jobId': ...}}) that ingest.request_parse accepts."""
        client = _client(monkeypatch=monkeypatch)
        mid = _release(client, unparsed=True)
        res = client.post(f"/request/{mid}")
        assert res.status_code == 200
        assert isinstance(res.json()["job"]["jobId"], int)

        monkeypatch.setattr(opendota_client, "OPEN_DOTA_URL", _MOCK_BASE)
        monkeypatch.setattr(ingest, "OPEN_DOTA_URL", _MOCK_BASE)
        _route_to_mock(monkeypatch, client)
        monkeypatch.setattr(opendota_client, "throttle", lambda cost=1: None)
        monkeypatch.setattr(ingest, "_parse_requested", {})
        assert ingest.request_parse(mid) is True
        assert client.get("/_control/state").json()["parse_requests"] == [mid, mid]

    def test_mock_constants_heroes_and_players(self, monkeypatch):
        """GET /constants/heroes returns a hero-id-keyed dict with localized_name; GET /players/{id} returns a profile with personaname for scripted players and 404 for unknown ids."""
        client = _client(monkeypatch=monkeypatch)
        heroes = client.get("/constants/heroes").json()
        assert heroes["1"]["id"] == 1 and heroes["1"]["localized_name"]
        season, _ = _expected_script()
        player = season["players"][0]
        res = client.get(f"/players/{player['id']}")
        assert res.status_code == 200
        assert res.json()["profile"]["personaname"] == player["name"]
        assert client.get("/players/42").status_code == 404

    def test_mock_steam_live_response_parses(self, monkeypatch):
        """GET /IDOTA2Match_570/GetLiveLeagueGames/v1/?key=mock with a live game returns {'result': {'games': [...]}} that steam_live.parse_live_league_games turns into one game, including players without names."""
        client = _client(monkeypatch=monkeypatch)
        live = client.post("/_control/live", json={"minutes": 10}).json()
        res = client.get(_STEAM_PATH, params={"key": "mock"})
        assert res.status_code == 200
        assert "mock" not in res.text.replace("Mock", "")  # the key is never echoed
        games = steam_live.parse_live_league_games(res.json(), [_LEAGUE])
        assert len(games) == 1
        game = games[0]
        assert game["match_id"] == live["match_id"] and game["league_id"] == _LEAGUE
        assert game["team_id_radiant"] and game["team_id_dire"]
        assert len(game["players"]) == 10
        assert any(p["name"] is None for p in game["players"])
        assert any(p["name"] for p in game["players"])

    def test_mock_steam_live_without_key_is_refused(self, monkeypatch):
        """GET /IDOTA2Match_570/GetLiveLeagueGames/v1/ without a key answers 403 like Steam, and steam_live.get_live_league_games returns None."""
        client = _client(monkeypatch=monkeypatch)
        client.post("/_control/live", json={"minutes": 10})
        assert client.get(_STEAM_PATH).status_code == 403
        assert client.get(_STEAM_PATH, params={"key": ""}).status_code == 403

        monkeypatch.setattr(steam_live, "_URL", _MOCK_BASE + _STEAM_PATH)
        _route_to_mock(monkeypatch, client)
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "")
        assert steam_live.get_live_league_games([_LEAGUE]) is None
        # A request that reaches the mock without a usable key gets the 403 -> None.
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "mock")
        monkeypatch.setattr(opendota_client.requests, "get",
                            lambda url, params=None, **kw: client.get(url[len(_MOCK_BASE):]))
        assert steam_live.get_live_league_games([_LEAGUE]) is None


# ---------------------------------------------------------------------------
# AC 3 — Control endpoints
# ---------------------------------------------------------------------------

class TestControlEndpoints:

    def test_control_next_match_releases_next_scripted_match(self, monkeypatch):
        """POST /_control/next-match releases the scripted matches in start_time order and returns the released match id; repeated calls release the next ones."""
        client = _client(monkeypatch=monkeypatch)
        script = _mock_module().build_script()["matches"]
        ordered = [m["match_id"] for m in sorted(script, key=lambda m: (m["start_time"], m["match_id"]))]
        released = [_release(client) for _ in range(3)]
        assert released == ordered[:3]
        assert client.get("/_control/state").json()["remaining"] == len(script) - 3

    def test_control_next_match_when_script_exhausted(self, monkeypatch):
        """POST /_control/next-match after the last scripted match answers 409 (nothing left) and releases nothing."""
        client = _client(monkeypatch=monkeypatch)
        total = client.get("/_control/state").json()["scripted"]
        for _ in range(total):
            _release(client)
        res = client.post("/_control/next-match")
        assert res.status_code == 409
        state = client.get("/_control/state").json()
        assert len(state["released"]) == total and state["remaining"] == 0

    def test_control_live_makes_next_game_live_for_n_minutes(self, monkeypatch):
        """POST /_control/live {'minutes': 10} puts the next scripted game in the Steam live response; after the mock's clock passes 10 minutes it is no longer live."""
        clock = [1_800_000_000.0]
        client = _client(now=lambda: clock[0], monkeypatch=monkeypatch)
        first = _mock_module().build_script()["matches"][0]["match_id"]
        res = client.post("/_control/live", json={"minutes": 10})
        assert res.status_code == 200
        assert res.json() == {"match_id": first, "ends_at": int(clock[0]) + 600}
        games = client.get(_STEAM_PATH, params={"key": "k"}).json()["result"]["games"]
        assert [g["match_id"] for g in games] == [first]
        clock[0] += 599
        assert len(client.get(_STEAM_PATH, params={"key": "k"}).json()["result"]["games"]) == 1
        clock[0] += 2
        assert client.get(_STEAM_PATH, params={"key": "k"}).json()["result"]["games"] == []
        assert client.get("/_control/state").json()["live"] == []

    def test_control_live_rejects_invalid_minutes(self, monkeypatch):
        """POST /_control/live with a missing, zero, negative or non-integer 'minutes' answers 422 and no game goes live."""
        client = _client(monkeypatch=monkeypatch)
        for body in ({}, {"minutes": 0}, {"minutes": -5}, {"minutes": 1.5}, {"minutes": "10"},
                     {"minutes": True}, {"minutes": None}):
            assert client.post("/_control/live", json=body).status_code == 422, body
        assert client.post("/_control/live").status_code == 422
        assert client.get("/_control/state").json()["live"] == []

    def test_control_parse_turns_unparsed_match_into_parsed(self, monkeypatch):
        """POST /_control/parse/{id} on a released unparsed match makes GET /matches/{id} include the parsed-only stats."""
        client = _client(monkeypatch=monkeypatch)
        mid = _release(client, unparsed=True)
        assert ingest._is_unparsed(client.get(f"/matches/{mid}").json())
        res = client.post(f"/_control/parse/{mid}")
        assert res.status_code == 200
        data = client.get(f"/matches/{mid}").json()
        assert not ingest._is_unparsed(data)
        for p in data["players"]:
            assert set(scoring.SCORING_STATS) <= set(p)
        assert client.get("/_control/state").json()["unparsed"] == []

    def test_control_parse_unknown_or_parsed_match(self, monkeypatch):
        """POST /_control/parse/{id} for an unknown, unreleased or already parsed match answers 404 (or 409 for already parsed) and changes nothing."""
        client = _client(monkeypatch=monkeypatch)
        unreleased = _mock_module().build_script()["matches"][-1]["match_id"]
        parsed = _release(client)
        unparsed = _release(client, unparsed=True)
        before = client.get("/_control/state").json()
        assert client.post("/_control/parse/123").status_code == 404
        assert client.post(f"/_control/parse/{unreleased}").status_code == 404
        assert client.post(f"/_control/parse/{parsed}").status_code == 409
        assert client.get("/_control/state").json() == before
        assert before["unparsed"] == [unparsed]

    def test_control_reset_restores_initial_script(self, monkeypatch):
        """POST /_control/reset after releases, a live game and a parse empties released/live/parsed so matchIds is empty and next-match starts from the first match again."""
        client = _client(monkeypatch=monkeypatch)
        first = _release(client)
        mid = _release(client, unparsed=True)
        client.post(f"/_control/parse/{mid}")
        client.post("/_control/live", json={"minutes": 5})
        assert client.post("/_control/reset").status_code == 200
        state = client.get("/_control/state").json()
        assert state["released"] == [] and state["live"] == [] and state["unparsed"] == []
        assert state["remaining"] == state["scripted"]
        assert client.get(f"/leagues/{_LEAGUE}/matchIds").json() == []
        assert _release(client) == first

    def test_control_state_lists_released_live_and_unparsed(self, monkeypatch):
        """GET /_control/state lists released, live (with ends_at) and unparsed match ids, plus the remaining scripted count."""
        clock = [1_800_000_000.0]
        client = _client(now=lambda: clock[0], monkeypatch=monkeypatch)
        parsed = _release(client)
        unparsed = _release(client, unparsed=True)
        live = client.post("/_control/live", json={"minutes": 3}).json()
        state = client.get("/_control/state").json()
        assert state["league_id"] == _LEAGUE
        assert state["released"] == [parsed, unparsed]
        assert state["unparsed"] == [unparsed]
        assert state["live"] == [{"match_id": live["match_id"], "ends_at": int(clock[0]) + 180}]
        assert state["remaining"] == state["scripted"] - 2


# ---------------------------------------------------------------------------
# AC 4 — Default script is the mid-season scenario's unplayed weeks; MOCK_SEED
# ---------------------------------------------------------------------------

class TestScript:

    def test_default_script_is_mid_season_unplayed_weeks_in_scenario_league(self, monkeypatch):
        """Without MOCK_SEED the script is the mid-season scenario's weeks 6-10, league 990001, with the same team ids, player ids and match ids season_generator produces for SCENARIOS['mid-season']."""
        monkeypatch.delenv("MOCK_SEED", raising=False)
        script = _mock_module().build_script()
        season, locked = _expected_script()
        assert locked == 5
        expected = [m for m in season["matches"] if m["week"] > locked]
        assert {m["week"] for m in expected} == {6, 7, 8, 9, 10}
        assert script["league_id"] == _LEAGUE == 990001
        assert sorted(m["match_id"] for m in script["matches"]) == sorted(m["match_id"] for m in expected)
        by_id = {m["match_id"]: m for m in expected}
        for m in script["matches"]:
            exp = by_id[m["match_id"]]
            assert (m["radiant_team_id"], m["dire_team_id"]) == (exp["radiant_team_id"], exp["dire_team_id"])
            assert [s["player_id"] for s in m["stats"]] == [s["player_id"] for s in exp["stats"]]
        assert set(script["teams"]) == {t["id"] for t in season["teams"]}
        assert set(script["players"]) == {p["id"] for p in season["players"]}
        # The app's default (create_app with MOCK_SEED unset) serves this league.
        assert _client(monkeypatch=monkeypatch).get(f"/leagues/{_LEAGUE}").status_code == 200

    def test_default_script_excludes_played_weeks(self, monkeypatch):
        """No scripted match falls in mid-season weeks 1-5 (those the scenario loader already stores), so a released match never collides with a stored one."""
        script = _mock_module().build_script()
        season, locked = _expected_script()
        stored = {m["match_id"] for m in season["matches"] if m["week"] <= locked}
        assert stored and not stored & {m["match_id"] for m in script["matches"]}
        assert all(m["week"] > locked for m in script["matches"])
        week6_start = season["weeks"][locked]["start_time"]
        assert min(m["start_time"] for m in script["matches"]) >= week6_start

    def test_mock_seed_gives_standalone_league_with_own_teams(self, monkeypatch):
        """MOCK_SEED=7 gives a league id other than 990001 with its own teams and players; the same seed gives the same script twice."""
        monkeypatch.setenv("MOCK_SEED", "7")
        client = TestClient(_mock_module().create_app())
        league_id = client.get("/_control/state").json()["league_id"]
        assert league_id != _LEAGUE
        assert client.get(f"/leagues/{league_id}").json()["leagueid"] == league_id
        mock = _mock_module()
        a, b = mock.build_script(7), mock.build_script(7)
        assert a == b
        default = mock.build_script()
        assert not set(a["teams"]) & set(default["teams"])
        assert not set(a["players"]) & set(default["players"])
        assert not {m["match_id"] for m in a["matches"]} & {m["match_id"] for m in default["matches"]}
        assert mock.build_script(8)["matches"] != a["matches"]

    def test_mock_seed_invalid_value_rejected(self, monkeypatch):
        """MOCK_SEED=abc makes create_app() raise a clear error instead of falling back silently."""
        monkeypatch.setenv("MOCK_SEED", "abc")
        with pytest.raises(ValueError, match="MOCK_SEED must be an integer"):
            _mock_module().create_app()


# ---------------------------------------------------------------------------
# AC 5 — Compose: the mock file starts the app with both addresses at the mock
# ---------------------------------------------------------------------------

def _compose_service(src, name):
    """The indented block of one top-level service in a Compose file."""
    m = re.search(rf"^  {name}:\n((?:    .*\n|\s*\n)*)", src, re.M)
    assert m, name
    return m.group(1)


class TestComposeMock:

    def test_compose_mock_publishes_on_localhost_only(self):
        """docker-compose.mock.yml publishes the mock_opendota service only as 127.0.0.1:8090:..., never on 0.0.0.0 or a bare port."""
        src = _read("docker-compose.mock.yml")
        mock = _compose_service(src, "mock_opendota")
        ports = re.findall(r"^\s*-\s*\"?([^\"\n]+)\"?\s*$", mock.split("ports:", 1)[1], re.M)
        assert ports == ["127.0.0.1:8090:8090"]
        assert "0.0.0.0" not in src.split("services:", 1)[1].replace("--host 0.0.0.0", "")
        backend = _compose_service(src, "backend")
        assert "ports:" not in backend

    def test_compose_mock_points_backend_at_mock(self):
        """docker-compose.mock.yml sets the backend's OPENDOTA_BASE_URL and STEAM_LIVE_URL to the mock service and STEAM_API_KEY=mock, and mounts ./backend:/backend:ro into the mock."""
        src = _read("docker-compose.mock.yml")
        backend = _compose_service(src, "backend")
        assert re.search(r"-\s*OPENDOTA_BASE_URL=http://mock_opendota:8090\s*$", backend, re.M)
        assert re.search(r"-\s*STEAM_LIVE_URL=http://mock_opendota:8090/IDOTA2Match_570/GetLiveLeagueGames/v1/\s*$",
                         backend, re.M)
        assert re.search(r"-\s*STEAM_API_KEY=mock\s*$", backend, re.M)
        mock = _compose_service(src, "mock_opendota")
        assert re.search(r"-\s*\./backend:/backend:ro\s*$", mock, re.M)
        assert "tools/mock_opendota/Dockerfile" in mock

    def test_mock_runs_without_access_log(self):
        """Security review: the mock's CMD and the README's local command pass --no-access-log, so uvicorn never logs the ?key= / ?api_key= query strings; the README warns against real keys."""
        dockerfile = _read("tools", "mock_opendota", "Dockerfile")
        cmd = [l for l in dockerfile.splitlines() if l.startswith("CMD")]
        assert len(cmd) == 1 and '"--no-access-log"' in cmd[0]
        readme = _read("tools", "mock_opendota", "README.md")
        commands = [l for l in readme.splitlines() if l.startswith("uvicorn ")]
        assert commands and all("--no-access-log" in l for l in commands)
        assert "Never point an app that holds real API keys" in readme

    def test_mock_not_in_production_image(self):
        """The root Dockerfile copies no tools/ path, and docker-compose.yml has no mock_opendota service."""
        dockerfile = _read("Dockerfile")
        copies = [l for l in dockerfile.splitlines() if l.strip().upper().startswith(("COPY", "ADD"))]
        assert copies and not any("tools" in l for l in copies)
        ignored = [l.strip() for l in _read(".dockerignore").splitlines()]
        assert "tools/" in ignored
        assert "mock_opendota" not in _read("docker-compose.yml")
        assert "mock_opendota" not in _read("docker-compose.dev.yml")

    def test_mock_docs_list_control_calls(self):
        """tools/mock_opendota/README.md has curl examples for next-match, live, parse, reset and state; testing-tooling.md has a 'Mock OpenDota' walkthrough; .env.example documents OPENDOTA_BASE_URL and STEAM_LIVE_URL."""
        readme = _read("tools", "mock_opendota", "README.md")
        for call in ("_control/next-match", "_control/live", "_control/parse/", "_control/reset",
                     "_control/state"):
            assert re.search(rf"^curl .*{re.escape(call)}", readme, re.M), call
        doc = _read("markdown", "features", "reference", "testing-tooling.md")
        section = doc.split("## Mock OpenDota", 1)[1].split("\n## ", 1)[0]
        assert "(planned, #146)" not in doc
        for step in ("docker-compose.mock.yml", "990001", "next-match", "Admin"):
            assert step in section, step
        env = _read(".env.example")
        assert re.search(r"^# OPENDOTA_BASE_URL=https://api\.opendota\.com/api$", env, re.M)
        assert re.search(r"^# STEAM_LIVE_URL=https://api\.steampowered\.com/IDOTA2Match_570/GetLiveLeagueGames/v1/$",
                         env, re.M)


# ---------------------------------------------------------------------------
# AC 5 (cont.) — Polling rule: Demo Mode skips polling only with the real address
# ---------------------------------------------------------------------------

class TestPollingRule:

    def test_demo_mode_with_default_address_skips_polling(self, monkeypatch, caplog):
        """DEMO_MODE=true with the default OpenDota address starts neither _ingest_poll_loop nor _live_poll_loop and logs that Demo Mode skipped them."""
        caplog.set_level(logging.INFO, logger="main")
        main, started = _start_threads(monkeypatch, True, opendota_client.DEFAULT_OPEN_DOTA_URL,
                                       steam_url=_MOCK_BASE + _STEAM_PATH)
        assert main._ingest_poll_loop not in started
        assert main._live_poll_loop not in started
        assert main._week_maintenance_loop in started
        assert "Demo Mode with the default OpenDota address: match polling is off" in caplog.text
        assert "Ingest poll thread skipped (DEMO_MODE=true)" in caplog.text

    def test_demo_mode_with_mock_address_polls(self, monkeypatch, caplog):
        """DEMO_MODE=true with OPEN_DOTA_URL=http://mock:8090 and STEAM_API_KEY set starts both _ingest_poll_loop and _live_poll_loop and logs that the mock address applied."""
        caplog.set_level(logging.INFO, logger="main")
        main, started = _start_threads(monkeypatch, True, _MOCK_BASE,
                                       steam_url=_MOCK_BASE + _STEAM_PATH)
        assert started.count(main._ingest_poll_loop) == 1
        assert started.count(main._live_poll_loop) == 1
        assert "non-default OpenDota address (mock): match polling runs" in caplog.text

        # The live check never goes to the real Steam address in Demo Mode.
        main, started = _start_threads(monkeypatch, True, _MOCK_BASE)
        assert main._ingest_poll_loop in started
        assert main._live_poll_loop not in started

    def test_non_demo_mode_polls_with_either_address(self, monkeypatch):
        """DEMO_MODE off starts the ingest thread with the default address and with a mock address (unchanged behaviour)."""
        for base in (opendota_client.DEFAULT_OPEN_DOTA_URL, _MOCK_BASE):
            main, started = _start_threads(monkeypatch, False, base)
            assert started.count(main._ingest_poll_loop) == 1, base
            assert started.count(main._live_poll_loop) == 1, base


# ---------------------------------------------------------------------------
# AC 6 — ENV=production refuses non-https addresses
# ---------------------------------------------------------------------------

class TestProductionGuard:

    def test_production_startup_fails_with_http_opendota_base_url(self, tmp_path):
        """ENV=production with OPENDOTA_BASE_URL=http://mock:8090 fails at import with a RuntimeError naming OPENDOTA_BASE_URL and [SECURITY] (subprocess)."""
        res = _run_import_main(tmp_path, {"ENV": "production", "SECRET_KEY": _LONG_SECRET,
                                          "OPENDOTA_BASE_URL": "http://user:CREDSECRET@mock:8090"})
        assert res.returncode != 0
        assert "RuntimeError" in res.stderr and "[SECURITY]" in res.stderr
        assert "OPENDOTA_BASE_URL" in res.stderr
        assert "CREDSECRET" not in res.stderr and "mock:8090" not in res.stderr

    def test_production_startup_fails_with_http_steam_live_url(self, tmp_path):
        """ENV=production with STEAM_LIVE_URL=http://mock:8090/IDOTA2Match_570/GetLiveLeagueGames/v1/ fails at import with a RuntimeError naming STEAM_LIVE_URL and [SECURITY] (subprocess)."""
        res = _run_import_main(tmp_path, {"ENV": "production", "SECRET_KEY": _LONG_SECRET,
                                          "STEAM_LIVE_URL": _MOCK_BASE + _STEAM_PATH})
        assert res.returncode != 0
        assert "RuntimeError" in res.stderr and "[SECURITY]" in res.stderr
        assert "STEAM_LIVE_URL" in res.stderr

    def test_production_startup_succeeds_with_https_addresses(self, tmp_path):
        """ENV=production with the defaults, or with https:// values for both settings, imports main successfully (subprocess)."""
        res = _run_import_main(tmp_path, {"ENV": "production", "SECRET_KEY": _LONG_SECRET})
        assert res.returncode == 0, res.stderr
        res = _run_import_main(tmp_path, {
            "ENV": "production", "SECRET_KEY": _LONG_SECRET,
            "OPENDOTA_BASE_URL": "https://opendota.example.org/api",
            "STEAM_LIVE_URL": "https://steam.example.org/IDOTA2Match_570/GetLiveLeagueGames/v1/"})
        assert res.returncode == 0, res.stderr

    def test_non_production_allows_http_mock_addresses(self, tmp_path):
        """Without ENV=production (DEBUG=true), http:// mock addresses for both settings import main successfully (subprocess)."""
        res = _run_import_main(tmp_path, {"DEBUG": "true", "OPENDOTA_BASE_URL": _MOCK_BASE,
                                          "STEAM_LIVE_URL": _MOCK_BASE + _STEAM_PATH})
        assert res.returncode == 0, res.stderr


# ---------------------------------------------------------------------------
# Verification — ingest, live poll and parse retry against the mock app
# ---------------------------------------------------------------------------

def _live_poll(monkeypatch, db):
    import main
    monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: [_LEAGUE])
    monkeypatch.setattr(steam_live, "STEAM_API_KEY", "mock")
    monkeypatch.setattr(steam_live, "live_checked_at", None)
    main._live_poll_once()


class TestIngestAgainstMock:

    def test_ingest_league_against_mock_stores_released_match_with_expected_points(self, db, monkeypatch):
        """Release one match in the mock, run ingest_league(990001) through the TestClient transport: the Match and its 10 PlayerMatchStats rows are stored with fantasy_points equal to scoring applied to the mock's match JSON."""
        client = _client(monkeypatch=monkeypatch)
        _, stray = _wire(monkeypatch, db, client)
        weights = _seed_weights(db)
        mid = _release(client)

        ingest.ingest_league(_LEAGUE)

        match = db.get(Match, mid)
        assert match is not None and match.league_id == _LEAGUE
        assert match.parse_status == "parsed"
        payload = client.get(f"/matches/{mid}").json()
        assert (match.radiant_team_id, match.dire_team_id) == (payload["radiant_team_id"], payload["dire_team_id"])
        stored = _stored_points(db, mid)
        assert len(stored) == 10
        expected = _expected_points(payload, weights)
        assert stored == pytest.approx(expected)
        assert any(v > 0 for v in stored.values())
        assert stray == []

    def test_ingest_league_against_mock_ignores_unreleased_matches(self, db, monkeypatch):
        """With nothing released, an ingest pass stores no Match rows and requests no /matches/{id}."""
        client = _client(monkeypatch=monkeypatch)
        calls, stray = _wire(monkeypatch, db, client)
        _seed_weights(db)

        ingest.ingest_league(_LEAGUE)

        assert db.query(Match).count() == 0
        assert not [u for _, u in calls if "/matches/" in u]
        assert any(u.endswith(f"/leagues/{_LEAGUE}/matchIds") for _, u in calls)
        assert stray == []

    def test_live_poll_once_against_mock_stores_live_match(self, db, monkeypatch):
        """POST /_control/live {'minutes': 10}, then main._live_poll_once(): the game is a LiveMatch row in league 990001 with its team ids and players."""
        client = _client(monkeypatch=monkeypatch)
        _, stray = _wire(monkeypatch, db, client)
        _seed_weights(db)
        live = client.post("/_control/live", json={"minutes": 10}).json()
        scripted = _mock_module().build_script()["matches"][0]

        _live_poll(monkeypatch, db)

        db.expire_all()
        row = db.get(LiveMatch, live["match_id"])
        assert row is not None and row.league_id == _LEAGUE and row.ended_at is None
        assert (row.radiant_team_id, row.dire_team_id) == (scripted["radiant_team_id"], scripted["dire_team_id"])
        players = json.loads(row.players_json)
        assert {p["account_id"] for p in players} == {s["player_id"] for s in scripted["stats"]}
        assert {p["side"] for p in players} == {"radiant", "dire"}
        assert steam_live.live_checked_at is not None
        assert stray == []

    def test_twitch_panel_shows_mock_live_game_as_provisional(self, db, monkeypatch):
        """After the live poll above, twitch.current_matches lists that game with provisional=True and its players."""
        import twitch
        monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
        client = _client(monkeypatch=monkeypatch)
        _wire(monkeypatch, db, client)
        _seed_weights(db)
        live = client.post("/_control/live", json={"minutes": 10}).json()
        _live_poll(monkeypatch, db)

        result = twitch.current_matches(payload=dict(_BROADCASTER), db=db)

        matches = {m["match_id"]: m for s in result["series"] for m in s["matches"]}
        entry = matches[live["match_id"]]
        assert entry["provisional"] is True and entry["live"] is True
        scripted = _mock_module().build_script()["matches"][0]
        assert {p["player_id"] for p in entry["players"]} == {s["player_id"] for s in scripted["stats"]}

    def test_live_poll_once_with_no_live_game_stores_nothing(self, db, monkeypatch):
        """With no game made live, main._live_poll_once() stores no LiveMatch row (and a game whose minutes ran out is no longer returned)."""
        clock = [time.time()]
        client = _client(now=lambda: clock[0], monkeypatch=monkeypatch)
        _wire(monkeypatch, db, client)
        _seed_weights(db)

        _live_poll(monkeypatch, db)
        assert db.query(LiveMatch).count() == 0

        client.post("/_control/live", json={"minutes": 1})
        clock[0] += 61
        _live_poll(monkeypatch, db)
        db.expire_all()
        assert db.query(LiveMatch).count() == 0

    def test_parse_retry_against_mock_replaces_partial_stats(self, db, monkeypatch):
        """Release an unparsed match, ingest it (parse_status 'unparsed', partial-stat marker), POST /_control/parse/{id}, run retry_unparsed_matches: stats are replaced with the parsed values and parse_status is 'parsed'."""
        client = _client(monkeypatch=monkeypatch)
        _, stray = _wire(monkeypatch, db, client)
        weights = _seed_weights(db)
        mid = _release(client, unparsed=True)

        ingest.ingest_league(_LEAGUE)
        assert db.get(Match, mid).parse_status == "unparsed"
        assert ingest.find_unparsed_match_ids(db, _RETRY_HOURS) == [mid]
        partial = _stored_points(db, mid)
        assert partial == pytest.approx(_expected_points(client.get(f"/matches/{mid}").json(), weights))

        assert client.post(f"/_control/parse/{mid}").status_code == 200
        summary = ingest.retry_unparsed_matches(_RETRY_HOURS)

        assert summary["refreshed"] == 1
        db.expire_all()
        assert db.get(Match, mid).parse_status == "parsed"
        parsed_json = client.get(f"/matches/{mid}").json()
        assert _stored_points(db, mid) == pytest.approx(_expected_points(parsed_json, weights))
        assert _stored_points(db, mid) != pytest.approx(partial)
        assert ingest.find_unparsed_match_ids(db, _RETRY_HOURS) == []
        assert stray == []

    def test_parse_retry_before_mock_parse_keeps_partial_stats(self, db, monkeypatch):
        """Running retry_unparsed_matches before the mock parses the match keeps the partial stats and parse_status 'unparsed', and sends POST /request/{id} to the mock."""
        client = _client(monkeypatch=monkeypatch)
        _wire(monkeypatch, db, client)
        _seed_weights(db)
        mid = _release(client, unparsed=True)
        ingest.ingest_league(_LEAGUE)
        partial = _stored_points(db, mid)
        requests_before = client.get("/_control/state").json()["parse_requests"]
        assert requests_before == [mid]  # first-pass ingest asked for the parse
        monkeypatch.setattr(ingest, "_parse_requested", {})

        summary = ingest.retry_unparsed_matches(_RETRY_HOURS)

        assert summary["refreshed"] == 0 and summary["still_unparsed"] == 1
        assert summary["requested"] == 1
        db.expire_all()
        assert db.get(Match, mid).parse_status == "unparsed"
        assert _stored_points(db, mid) == pytest.approx(partial)
        assert client.get("/_control/state").json()["parse_requests"] == [mid, mid]
