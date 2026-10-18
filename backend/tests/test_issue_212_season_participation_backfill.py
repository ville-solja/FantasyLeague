"""
Tests for plan-issue-212-season-participation-backfill.md (resolves GitHub issue #212).

Past seasons' participation (Season 4 onward) is backfilled from a checked-in league
file in one command, and the seasons count says it starts at Season 4.

  Story 1: Past Seasons' Participation Is Backfilled in One Run
  Story 2: Counts Say Where They Start

Approach notes (for the developer filling these in):

- OpenDota is ALWAYS mocked. Reuse the `_backfill()` / `_run_backfill()` pattern from
  test_issue_50_season_winners_and_holo_cards.py: load backend/scripts/backfill_played.py
  with importlib, monkeypatch `ingest.get_league_matches`, `ingest.get_league_info`,
  `mod.fetch_match` and `mod.fetch_leagues`, point `cache_path` at `tmp_path`, pass
  `sleep=list.append` and `out=list.append`. For `--all`, point the script at a small
  test league file (a `tmp_path` JSON, or monkeypatch the module's league-file path)
  so tests don't depend on the real ids, and pin `accolades.current_season_label` with
  monkeypatch to choose the live season.
- Exit code 2 and the "Budget used: resume to continue from Season N" message come from
  the `run`/`main` entry point the developer adds for `--all` / `--max-calls`.
- The league-file test reads the real backend/scripts/kanaliiga_leagues.json.
- Note: test_issue_50's `test_backfill_played_requires_season_and_league_args` asserts
  backfill_played.py holds no 4+ digit numbers, so league ids (12481 ...) must live
  only in the JSON file.
- GET /players returns a list, so `seasons_counted_from` is a field on each row (the
  list shape must not change: other tests and the frontend iterate it).
- Story 2 frontend checks are source-reading (frontend/app-players.js and
  frontend/index.html, `_read`/`_fe` as in test_issue_50). The hover-text check may
  use a Node harness on `_playerSeasonsCellHtml` (`_node()` from test_issue_50; skip
  when Node is missing) to confirm the text is built from the one value.

Run with: cd backend && python -m pytest tests/test_issue_212_season_participation_backfill.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib.util
import json
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import accolades
import models  # noqa: F401  (registers every table for the db fixture)
from database import Base, get_db
from models import AuditLog, Player, SeasonAccolade

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_SCRIPT = os.path.join(_ROOT, "backend", "scripts", "backfill_played.py")
_REAL_LEAGUE_FILE = os.path.join(_ROOT, "backend", "scripts", "kanaliiga_leagues.json")


@pytest.fixture
def db():
    """In-memory database on one shared connection, so a TestClient's request thread
    sees the same data (overrides conftest's `db`)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _fe(name):
    return _read("frontend", name)


def _fn_source(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start) + 2]


def _node():
    return shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)


def _run_node(script):
    node = _node()
    if not node:
        pytest.skip("node not available")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _mod():
    spec = importlib.util.spec_from_file_location("backfill_played_212", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A small league file: Season 4 (one league), Season 5 (two, plus an empty one listed
# but never fetched), Season 6 (the live season unless a test says otherwise).
_FILE = {
    "seasons": [
        {"season": 4, "leagues": [101], "note": "unnumbered"},
        {"season": 5, "leagues": [201, 202], "empty_leagues": [203], "note": "203 has no matches"},
        {"season": 6, "leagues": [301], "note": "live"},
    ],
    "unused_leagues": [{"league": 401, "note": "no matches"}],
}
_LEAGUE_MAP = {101: [1001, 1002], 201: [2001], 202: [2002], 301: [3001]}
_MATCHES = {
    1001: {"players": [{"account_id": 10, "personaname": "ten"}, {"account_id": 11, "personaname": "eleven"}]},
    1002: {"players": [{"account_id": 10, "personaname": "ten"}, {"account_id": 12, "personaname": "twelve"}]},
    2001: {"players": [{"account_id": 10, "personaname": "ten"}, {"account_id": 13, "personaname": "thirteen"}]},
    2002: {"players": [{"account_id": 14, "personaname": "fourteen"}, {"account_id": None}]},
    3001: {"players": [{"account_id": 15, "personaname": "fifteen"}]},
}


def _league_file(tmp_path, data=None, name="leagues.json"):
    path = tmp_path / name
    path.write_text(json.dumps(_FILE if data is None else data))
    return str(path)


def _mock(mod, monkeypatch, matches=None, league_map=None, league_names=None, league_list=None,
          live="Season 6"):
    """Mocks every OpenDota call; returns the lists the mocks record."""
    import ingest
    rec = SimpleNamespace(fetched=[], infos=[], lists=[], match_lists=[])
    matches = _MATCHES if matches is None else matches
    league_map = _LEAGUE_MAP if league_map is None else league_map
    league_names = league_names or {}
    monkeypatch.setattr(ingest, "get_league_matches",
                        lambda lid: (rec.match_lists.append(lid), league_map.get(lid))[1])
    monkeypatch.setattr(ingest, "get_league_info",
                        lambda lid: (rec.infos.append(lid),
                                     {"name": league_names[lid]} if lid in league_names else None)[1])
    monkeypatch.setattr(mod, "fetch_match", lambda mid: (rec.fetched.append(mid), matches.get(mid))[1])
    monkeypatch.setattr(mod, "fetch_leagues", lambda: (rec.lists.append(1), league_list)[1])
    monkeypatch.setattr(accolades, "current_season_label", lambda db: live)
    return rec


def _all(db, tmp_path, monkeypatch, dry_run=False, max_calls=None, league_file=None, **mock):
    """Runs backfill_played.run_all (--all) with OpenDota mocked."""
    mod = _mod()
    rec = _mock(mod, monkeypatch, **mock)
    out, sleeps = [], []
    rec.code = mod.run_all(db, dry_run, cache_path=str(tmp_path / "cache.json"), pause=0.5,
                           sleep=sleeps.append, out=out.append,
                           league_file=league_file or _league_file(tmp_path), max_calls=max_calls)
    rec.out = "\n".join(out)
    rec.lines = out
    return rec


def _one(db, tmp_path, monkeypatch, season, leagues=(), dry_run=False, league_file=None, **mock):
    """Runs backfill_played.run (--season / --league) with OpenDota mocked."""
    mod = _mod()
    rec = _mock(mod, monkeypatch, **mock)
    out = []
    rec.code = mod.run(db, season, list(leagues), dry_run, cache_path=str(tmp_path / "cache.json"),
                       pause=0.5, sleep=lambda s: None, out=out.append,
                       league_file=league_file, max_calls=None)
    rec.out = "\n".join(out)
    return rec


def _rows(db, **filters):
    db.expire_all()
    return db.query(SeasonAccolade).filter_by(**filters).all()


def _played(db, label):
    return sorted(r.player_account_id for r in _rows(db, kind="played", season_label=label))


def _audits(db):
    db.expire_all()
    return [a.detail for a in
            db.query(AuditLog).filter_by(action="admin_accolade_added").order_by(AuditLog.id)]


def _main_exits(argv):
    mod = _mod()
    with pytest.raises(SystemExit) as exc:
        mod.main(argv)
    return exc.value.code


# ===========================================================================
# Story 1: Past Seasons' Participation Is Backfilled in One Run
# ===========================================================================

# --- League file ---

def test_league_file_lists_seasons_4_to_16_valid():
    """kanaliiga_leagues.json lists seasons 4-16, ascending, each league an int, all ids unique."""
    seasons = _mod().load_league_file(_REAL_LEAGUE_FILE)
    assert list(seasons) == list(range(4, 17))
    data = json.loads(_read("backend", "scripts", "kanaliiga_leagues.json"))
    numbers = [e["season"] for e in data["seasons"]]
    assert numbers == sorted(numbers)
    ids = [lid for e in data["seasons"] for lid in e["leagues"] + e.get("empty_leagues", [])]
    ids += [u["league"] for u in data.get("unused_leagues", [])]
    assert all(type(x) is int for x in ids)
    assert len(ids) == len(set(ids))


def test_league_file_season_4_is_12481_and_notes_cover_empty_leagues():
    """S4 maps to the unnumbered league 12481; notes exist for 15753, 17813 and 17814 (no matches)."""
    data = json.loads(_read("backend", "scripts", "kanaliiga_leagues.json"))
    by_season = {e["season"]: e for e in data["seasons"]}
    assert by_season[4]["leagues"] == [12481] and by_season[4]["note"]
    assert by_season[10]["empty_leagues"] == [15753] and "no matches" in by_season[10]["note"]
    assert by_season[13]["empty_leagues"] == [17813] and "no matches" in by_season[13]["note"]
    unused = {u["league"]: u["note"] for u in data["unused_leagues"]}
    assert "no matches" in unused[17814]
    # Empty leagues stay listed but are never fetched.
    loaded = _mod().load_league_file(_REAL_LEAGUE_FILE)
    assert loaded[10] == [15715] and loaded[13] == [17812]


def test_league_file_invalid_rejected(tmp_path):
    """A league file with duplicate ids, non-int ids or descending seasons is rejected by the loader; nothing written."""
    mod = _mod()
    bad = [
        {"seasons": [{"season": 4, "leagues": [101]}, {"season": 5, "leagues": [101]}]},  # duplicate
        {"seasons": [{"season": 4, "leagues": [101]}], "unused_leagues": [{"league": 101}]},  # duplicate
        {"seasons": [{"season": 4, "leagues": ["101"]}]},  # not an int
        {"seasons": [{"season": 4, "leagues": [True]}]},  # a bool is not an id
        {"seasons": [{"season": 5, "leagues": [201]}, {"season": 4, "leagues": [101]}]},  # descending
        {"seasons": [{"season": 4, "leagues": []}]},  # no league
        {"seasons": []},
    ]
    for i, data in enumerate(bad):
        with pytest.raises(mod.LeagueFileError):
            mod.load_league_file(_league_file(tmp_path, data, f"bad{i}.json"))
    with pytest.raises(mod.LeagueFileError):
        mod.load_league_file(str(tmp_path / "missing.json"))


# --- --all ---

def test_backfill_all_skips_live_season_and_runs_oldest_first(db, tmp_path, monkeypatch):
    """--all runs every listed season except accolades.current_season_label, oldest first."""
    r = _all(db, tmp_path, monkeypatch)
    assert r.code == 0
    assert r.match_lists == [101, 201, 202]  # Season 6 (live) not fetched; empty league 203 neither
    assert 3001 not in r.fetched
    assert "Skipping Season 6: it is the live season." in r.out
    assert r.out.index("Season 4: 2 matches") < r.out.index("Season 5: 2 matches")
    assert _played(db, "Season 4") == [10, 11, 12]
    assert _played(db, "Season 5") == [10, 13, 14]
    assert _played(db, "Season 6") == []
    # With Season 5 live instead, Season 6 runs and Season 5 is skipped.
    (tmp_path / "other").mkdir()
    other = _all(db, tmp_path / "other", monkeypatch, dry_run=True, live="Season 5")
    assert other.match_lists == [101, 301]


def test_backfill_all_uses_same_per_season_code_as_season(db, tmp_path, monkeypatch):
    """--all writes the same played rows for a season as --season does (shared per-season code)."""
    league_file = _league_file(tmp_path)
    _all(db, tmp_path, monkeypatch, league_file=league_file)
    from_all = {(r.player_account_id, r.player_name, r.source) for r in _rows(db, season_label="Season 5")}
    db.query(SeasonAccolade).delete()
    db.commit()
    (tmp_path / "one").mkdir()
    r = _one(db, tmp_path / "one", monkeypatch, "Season 5", league_file=league_file)
    assert r.code == 0
    assert r.match_lists == [201, 202] and r.lists == []  # from the file, no name discovery
    from_season = {(x.player_account_id, x.player_name, x.source) for x in _rows(db, season_label="Season 5")}
    assert from_all and from_season == from_all
    assert "Season 5: 2 matches, 3 players, 3 new rows" in r.out


def test_backfill_all_writes_one_audit_entry_per_season(db, tmp_path, monkeypatch):
    """Each season run by --all writes its own admin_accolade_added entry 'played=N source=backfill'."""
    _all(db, tmp_path, monkeypatch)
    assert _audits(db) == ["season_label=Season 4 played=3 source=backfill",
                           "season_label=Season 5 played=3 source=backfill"]
    db.expire_all()
    assert {a.actor_username for a in db.query(AuditLog).all()} == {"script"}


def test_backfill_all_dry_run_writes_nothing(db, tmp_path, monkeypatch):
    """--dry-run --all writes no season_accolades rows and no audit entries."""
    r = _all(db, tmp_path, monkeypatch, dry_run=True)
    assert r.code == 0 and "Dry run" in r.out
    assert "Season 4: 2 matches, 3 players, 3 new rows" in r.out
    assert _rows(db) == [] and _audits(db) == []


def test_backfill_all_rerun_adds_nothing(db, tmp_path, monkeypatch):
    """A second --all run adds no rows (ON CONFLICT DO NOTHING) and reports 0 new rows."""
    _all(db, tmp_path, monkeypatch)
    again = _all(db, tmp_path, monkeypatch)
    assert again.code == 0
    assert "Season 4: 2 matches, 3 players, 0 new rows" in again.out
    assert "Season 5: 2 matches, 3 players, 0 new rows" in again.out
    assert again.fetched == []  # every match comes from the cache
    assert len(_rows(db, kind="played")) == 6


def test_backfill_all_and_season_together_rejected():
    """--all combined with --season or --league is a usage error (non-zero exit), nothing written."""
    for argv in (["--all", "--season", "Season 5"], ["--all", "--league", "7"],
                 ["--all", "--season", "Season 5", "--league", "7"]):
        assert _main_exits(argv) != 0


# --- --max-calls ---

def test_backfill_max_calls_defaults_to_900(monkeypatch):
    """--max-calls defaults to 900 OpenDota calls per run."""
    mod = _mod()
    assert mod.DEFAULT_MAX_CALLS == 900
    seen = {}

    class _Db:
        def close(self):
            pass

    monkeypatch.setattr(mod.database, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(mod, "run_all", lambda db, dry_run, *a, **kw: (seen.update(kw, mode="all"), 0)[1])
    monkeypatch.setattr(mod, "run", lambda db, season, leagues, dry_run, *a, **kw: (seen.update(kw, mode="one"), 0)[1])
    assert mod.main(["--all", "--dry-run"]) == 0
    assert seen["mode"] == "all" and seen["max_calls"] == 900
    assert mod.main(["--season", "Season 5"]) == 0
    assert seen["mode"] == "one" and seen["max_calls"] == 900
    assert seen["league_file"] == mod.LEAGUE_FILE


def test_backfill_max_calls_stops_cleanly_exit_2_with_resume_message(db, tmp_path, monkeypatch):
    """When the budget is used, the run stops after the current match, exits 2 and prints 'Budget used: resume to continue from Season N'."""
    # Season 4 takes 3 calls (match list + 2 matches); the 4th is Season 5's first match list.
    r = _all(db, tmp_path, monkeypatch, max_calls=4)
    assert r.code == 2
    assert "Budget used: resume to continue from Season 5" in r.out
    assert r.match_lists == [101, 201] and r.fetched == [1001, 1002]  # no call past the budget


def test_backfill_max_calls_keeps_cache_and_records_finished_seasons(db, tmp_path, monkeypatch):
    """A budget stop keeps the cache and records rows (and audit) for the seasons it finished."""
    r = _all(db, tmp_path, monkeypatch, max_calls=4)
    assert r.code == 2
    cache = json.loads((tmp_path / "cache.json").read_text())
    assert set(cache["matches"]) == {"1001", "1002"}
    assert _played(db, "Season 4") == [10, 11, 12]
    assert _played(db, "Season 5") == []  # unfinished: recorded by the resumed run
    assert _audits(db) == ["season_label=Season 4 played=3 source=backfill"]


def test_backfill_max_calls_resume_spends_no_calls_on_cached_matches(db, tmp_path, monkeypatch):
    """A resumed run fetches no cached match and continues from the season it stopped in."""
    _all(db, tmp_path, monkeypatch, max_calls=4)
    resumed = _all(db, tmp_path, monkeypatch)
    assert resumed.code == 0
    assert resumed.fetched == [2001, 2002]  # Season 4's matches come from the cache
    assert _played(db, "Season 5") == [10, 13, 14]
    assert "Season 4: 2 matches, 3 players, 0 new rows" in resumed.out
    assert _audits(db)[-1] == "season_label=Season 5 played=3 source=backfill"


def test_backfill_max_calls_rejects_non_positive():
    """--max-calls 0 or a negative value is a usage error (non-zero exit)."""
    for value in ("0", "-5"):
        assert _main_exits(["--all", "--max-calls", value]) != 0
        assert _main_exits(["--season", "Season 5", "--max-calls", value]) != 0


# --- Unreadable matches ---

def test_backfill_unreadable_match_counted_rows_still_written(db, tmp_path, monkeypatch):
    """A match that can't be fetched is counted as unreadable; the season's rows for read matches are still written."""
    matches = {k: v for k, v in _MATCHES.items() if k != 2001}
    r = _all(db, tmp_path, monkeypatch, matches=matches)
    assert r.code == 0
    assert ("Season 5: 1 matches, 1 players, 1 new rows, 1 anonymous slots skipped, "
            "0 already recorded, 1 unreadable matches") in r.lines
    assert "1 matches could not be read; run again to retry them." in r.out
    assert _played(db, "Season 5") == [14]


def test_backfill_unreadable_match_retried_next_run(db, tmp_path, monkeypatch):
    """An unreadable match isn't cached, so the next run fetches it again and records its players."""
    matches = {k: v for k, v in _MATCHES.items() if k != 2001}
    _all(db, tmp_path, monkeypatch, matches=matches)
    assert "2001" not in json.loads((tmp_path / "cache.json").read_text())["matches"]
    again = _all(db, tmp_path, monkeypatch)
    assert again.fetched == [2001]
    assert _played(db, "Season 5") == [10, 13, 14]
    assert "could not be read" not in again.out


# --- Report ---

def test_backfill_all_report_per_season_lines_and_totals(db, tmp_path, monkeypatch):
    """The report prints per season: players, new rows, already recorded, unreadable matches; then the totals."""
    r = _all(db, tmp_path, monkeypatch)
    assert ("Season 4: 2 matches, 3 players, 3 new rows, 0 anonymous slots skipped, "
            "0 already recorded, 0 unreadable matches") in r.lines
    assert ("Season 5: 2 matches, 3 players, 3 new rows, 1 anonymous slots skipped, "
            "0 already recorded, 0 unreadable matches") in r.lines
    assert ("Total: 2 seasons, 5 players, 6 played rows, 6 new rows, 0 already recorded, "
            "0 unreadable matches") in r.lines


def test_backfill_all_report_seasons_per_player_distribution(db, tmp_path, monkeypatch):
    """The report prints the seasons-per-player distribution (e.g. '1 season: N players')."""
    r = _all(db, tmp_path, monkeypatch, dry_run=True)
    i = r.lines.index("Seasons per player:")
    assert r.lines[i + 1:i + 3] == ["  1 season: 4 players", "  2 seasons: 1 player"]


def test_backfill_report_already_recorded_counts_existing_rows(db, tmp_path, monkeypatch):
    """Players with an existing played row for the season are reported as 'already recorded', not new."""
    accolades.insert_ignore(db, [{"season_label": "Season 4", "kind": "played", "player_account_id": 10,
                                  "player_name": "ten", "source": "admin", "created_at": 1}])
    db.commit()
    line = "Season 4: 2 matches, 3 players, 2 new rows, 0 anonymous slots skipped, 1 already recorded"
    assert line in _all(db, tmp_path, monkeypatch, dry_run=True).out
    real = _all(db, tmp_path, monkeypatch)
    assert line in real.out
    assert "5 new rows, 1 already recorded" in [x for x in real.lines if x.startswith("Total")][0]


# --- Existing modes unchanged ---

def test_backfill_season_mode_unchanged(db, tmp_path, monkeypatch):
    """--season 'Season 14' with --league ids still works and writes as before (exit 0)."""
    league_map = {111: [9001], 222: [9002]}
    matches = {9001: {"players": [{"account_id": 20, "personaname": "a"}]},
               9002: {"players": [{"account_id": 21, "personaname": "b"}]}}
    names = {111: "Kanaliiga Season 14", 222: "Kanaliiga Season 14 Lower"}
    # The file maps Season 14 elsewhere: explicit --league ids take precedence over it.
    data = {"seasons": [{"season": 14, "leagues": [999]}]}
    r = _one(db, tmp_path, monkeypatch, "Season 14", leagues=(111, 222),
             league_file=_league_file(tmp_path, data), league_map=league_map, matches=matches,
             league_names=names)
    assert r.code == 0
    assert r.match_lists == [111, 222] and r.infos == [111, 222]
    assert _played(db, "Season 14") == [20, 21]
    assert "Season 14: 2 matches, 2 players, 2 new rows, 0 anonymous slots skipped" in r.out


def test_backfill_season_4_resolves_through_league_file(db, tmp_path, monkeypatch):
    """--season 'Season 4' resolves to league 12481 through the file, despite its unnumbered OpenDota name, without name discovery."""
    r = _one(db, tmp_path, monkeypatch, "Season 4", league_file=_league_file(tmp_path),
             league_names={101: "Kanaliiga"})
    assert r.code == 0
    assert r.lists == []  # no name discovery
    assert r.match_lists == [101]
    assert "Season 4: leagues 101 from the league file" in r.out
    assert _played(db, "Season 4") == [10, 11, 12]
    # The real file maps Season 4 to the unnumbered league 12481.
    assert _mod().load_league_file(_REAL_LEAGUE_FILE)[4] == [12481]


def test_backfill_season_not_in_file_falls_back_to_name_discovery(db, tmp_path, monkeypatch):
    """A season missing from the file still uses name discovery; with no match it exits 1 and writes nothing."""
    r = _one(db, tmp_path, monkeypatch, "Season 9", league_file=_league_file(tmp_path), league_list=[])
    assert r.code == 1
    assert r.lists == [1]  # discovery by name ran
    assert 'No OpenDota league is named "Kanaliiga Season 9"' in r.out
    assert _rows(db) == [] and _audits(db) == []
    found = _one(db, tmp_path, monkeypatch, "Season 9", league_file=_league_file(tmp_path),
                 league_list=[{"leagueid": 101, "name": "Kanaliiga Season 9"}])
    assert found.code == 0 and _played(db, "Season 9") == [10, 11, 12]


# ===========================================================================
# Story 2: Counts Say Where They Start
# ===========================================================================

def _players(db):
    from routers import players
    app = FastAPI()
    app.include_router(players.router)

    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db
    res = TestClient(app).get("/players")
    assert res.status_code == 200
    return res.json()


def test_first_counted_season_constant_is_4():
    """accolades.FIRST_COUNTED_SEASON == 4."""
    assert accolades.FIRST_COUNTED_SEASON == 4


def test_get_players_includes_seasons_counted_from(db):
    """Each GET /players row carries seasons_counted_from == accolades.FIRST_COUNTED_SEASON; the response stays a list."""
    db.add_all([Player(id=1, name="Alpha"), Player(id=2, name="Bravo")])
    db.commit()
    rows = _players(db)
    assert isinstance(rows, list) and len(rows) == 2
    assert all(r["seasons_counted_from"] == accolades.FIRST_COUNTED_SEASON == 4 for r in rows)
    assert all("seasons_played" in r for r in rows)


def test_get_players_seasons_counted_from_follows_constant(db, monkeypatch):
    """Changing FIRST_COUNTED_SEASON changes seasons_counted_from (not a hard-coded 4 in the router)."""
    db.add(Player(id=1, name="Alpha"))
    db.commit()
    monkeypatch.setattr(accolades, "FIRST_COUNTED_SEASON", 7)
    assert [r["seasons_counted_from"] for r in _players(db)] == [7]


def test_players_tab_seasons_legend_text():
    """Source-reading: the Players tab legend reads 'Seasons played since Season 4 (earlier seasons have no OpenDota record)', built from seasons_counted_from."""
    html = _fe("index.html")
    js = _fe("app-players.js")
    assert re.search(r'<p class="players-seasons-legend" id="playersSeasonsLegend"[^>]*>', html)
    # The legend sits under the Players table, above its status line.
    assert html.index('id="playersBody"') < html.index('id="playersSeasonsLegend"') < html.index('id="playersStatus"')
    assert "_renderSeasonsLegend(rows)" in _fn_source(js, "loadPlayers")
    out = _run_node(_fn_source(js, "_seasonsCountedFrom") + _fn_source(js, "_renderSeasonsLegend") + """
const el = { textContent: "", hidden: true };
globalThis.document = { getElementById: id => id === "playersSeasonsLegend" ? el : null };
_renderSeasonsLegend([{ seasons_counted_from: 4 }, { seasons_counted_from: 4 }]);
const shown = [el.textContent, el.hidden];
_renderSeasonsLegend([]);
console.log(JSON.stringify([shown, [el.textContent, el.hidden]]));
""")
    assert out[0] == ["Seasons played since Season 4 (earlier seasons have no OpenDota record)", False]
    assert out[1] == ["", True]
    css = _fe("style.css")
    assert css.index(".players-seasons-legend {") < css.index("GUIDED TOUR")
    assert ".players-seasons-legend[hidden]" in css


def test_players_seasons_hover_text_ends_counted_from_season_4():
    """Node harness on _playerSeasonsCellHtml: the count's hover text lists the seasons and ends with 'Counted from Season 4'."""
    globals_js = _fe("app-globals.js")
    src = "".join(_fn_source(globals_js, n) for n in ("_escHtml", "_seasonNumber", "_seasonShort"))
    src += _fn_source(_fe("app-players.js"), "_playerSeasonsCellHtml")
    out = _run_node(src + """
const p = { seasons: ["Season 16", "Season 15"], titles: [], seasons_counted_from: 4 };
const html = _playerSeasonsCellHtml(p, ["Season 15", "Season 16"]);
const none = _playerSeasonsCellHtml({ seasons: [], titles: [], seasons_counted_from: 6 }, []);
console.log(JSON.stringify([/title="([^"]*)"/.exec(html)[1], /aria-label="([^"]*)"/.exec(html)[1],
                            /title="([^"]*)"/.exec(none)[1]]));
""")
    assert out[0] == "S16, S15. Counted from Season 4"
    assert out[1] == "2 seasons: S16, S15. Counted from Season 4"
    assert out[2] == "No seasons yet. Counted from Season 6"  # built from the value, not a literal


def test_players_season_start_not_hard_coded_twice():
    """Source-reading: frontend/app-players.js and index.html don't hard-code 'Season 4'; the text comes from the one value."""
    for name in ("app-players.js", "index.html"):
        assert not re.search(r"Season\s+4\b", _fe(name)), name
    js = _fe("app-players.js")
    assert "seasons_counted_from" in _fn_source(js, "_playerSeasonsCellHtml")
    assert "seasons_counted_from" in _fn_source(js, "_seasonsCountedFrom")
    assert "accolades.FIRST_COUNTED_SEASON" in _read("backend", "routers", "players.py")
