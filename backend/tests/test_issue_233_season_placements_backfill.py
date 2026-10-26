"""
Tests for plan-issue-233-season-placements-backfill.md (resolves GitHub issue #233).

Past seasons' placements 1-3 and each placed team's players are derived from OpenDota
into a reviewed table (backend/scripts/season_placements.csv), then written as
champion / runner_up / third_place accolades.

  Story 1: Build the Placements Table From OpenDota
  Story 2: Apply the Reviewed Table
  Story 3: Runner-up and Third Place Accolades

Approach notes (for the developer filling these in):

- OpenDota is ALWAYS mocked. Follow test_issue_212_season_participation_backfill.py:
  load backend/scripts/season_placements.py with importlib (`_mod()` below, no
  sys.modules entry, so no @dataclass in the script), monkeypatch its match-id and
  match fetchers so they record calls, point the cache at `tmp_path`, pass
  `sleep=list.append` / `out=list.append`, point the script at a small `tmp_path`
  league file, and pin `accolades.current_season_label` with monkeypatch to pick
  the live season. Write the CSV to `tmp_path` too, never the real
  backend/scripts/season_placements.csv.
- The `db` fixture below is an in-memory StaticPool database (never the real app db).
- Match fixtures are slim dicts shaped like `/matches/{id}`: `match_id`, `series_id`,
  `series_type`, `start_time`, `radiant_team_id` / `dire_team_id`, `radiant_name` /
  `dire_name`, `radiant_win`, and `players` with `account_id`, `personaname`,
  `isRadiant` (or `player_slot`).
- The Season 15 spike fixture (series ids, teams, winners for leagues 19368 and 19369)
  is created by the developer, e.g. as a JSON file under backend/tests/fixtures/ or a
  module-level constant; keep it small (the final day plus the series the rules look at).
- test_issue_50's `test_accolade_kinds_backend_order_names_icons_tokens` pins the full
  ACCOLADE_KINDS list; it must be extended for the new kinds, not weakened.
- Frontend checks are source-reading or Node harnesses, as in
  test_issue_50_season_winners_and_holo_cards.py (`_read`, `_fn_body`, `_run_node`,
  `_a`, `_pips`, `_chips`) and test_issue_230_accolades_and_rank_in_player_popup.py
  (`_section`, `_entries` for the popup timeline). New CSS goes before GUIDED TOUR.

Run with: cd backend && python -m pytest tests/test_issue_233_season_placements_backfill.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import csv
import importlib.util
import re
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import accolades
import models  # noqa: F401  (registers every table for the db fixture)
from database import Base
from models import AuditLog, Player, SeasonAccolade
from tests.test_issue_50_season_winners_and_holo_cards import (
    _a, _chips, _fe, _fn_body, _fn_source, _globals_helpers_js, _pip_attrs, _pips, _read, _rule,
    _run_node,
)
from tests.test_issue_230_accolades_and_rank_in_player_popup import _entries, _section

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_SCRIPT = os.path.join(_ROOT, "backend", "scripts", "season_placements.py")


@pytest.fixture
def db():
    """In-memory database on one shared connection (overrides conftest's `db`)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _mod():
    spec = importlib.util.spec_from_file_location("season_placements_233", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures: slim /matches/{id} dicts, the Season 15 spike and a small league file
# ---------------------------------------------------------------------------

def _team(tid, name, first):
    """A team with five accounts first..first+4."""
    return {"id": tid, "name": name, "players": list(range(first, first + 5))}


def _m(mid, sid, t, rad, dire, radiant_win, stype=1, ids=True, names=True, players=None):
    """A match shaped like GET /matches/{id}."""
    if players is None:
        players = ([{"account_id": a, "personaname": f"p{a}", "isRadiant": True} for a in rad["players"]]
                   + [{"account_id": a, "personaname": f"p{a}", "isRadiant": False} for a in dire["players"]])
    return {"match_id": mid, "series_id": sid, "series_type": stype, "start_time": t,
            "radiant_team_id": rad["id"] if ids else None, "dire_team_id": dire["id"] if ids else None,
            "radiant_name": rad["name"] if names else None, "dire_name": dire["name"] if names else None,
            "radiant_win": radiant_win, "players": players}


_T = 1_700_000_000
# Season 15 Div 1 (league 19368): the final day of the spike.
OPP = _team(101, "OP Platinum", 1)
ELISA = _team(102, "Elisa Oyj", 6)
VT = _team(103, "Visma Tormentor", 11)
REAK = _team(104, "Reaktor", 16)
# Season 15 Div 2 (league 19369).
PV1 = _team(201, "PV-1", 21)
OPG = _team(202, "OP Gold", 26)
GOF = _team(203, "Gofore/Loihde", 31)
VW = _team(204, "Visma Wisdom", 36)

S15_DIV1 = [
    _m(1501, 9001, _T, OPP, ELISA, True), _m(1502, 9001, _T + 3000, ELISA, OPP, False),      # OPP 2-0 Elisa
    _m(1503, 9002, _T + 10, VT, REAK, True), _m(1504, 9002, _T + 3010, REAK, VT, False),     # VT 2-0 Reaktor
    _m(1505, 9003, _T + 7000, ELISA, REAK, True, stype=0),                                    # Elisa beat Reaktor
    _m(1506, 9004, _T + 10000, OPP, VT, True), _m(1507, 9004, _T + 13000, VT, OPP, True),
    _m(1508, 9004, _T + 16000, OPP, VT, True),                                                # OPP 2-1 VT
]
S15_DIV2 = [
    _m(1511, 9101, _T - 7 * 86400, PV1, OPG, True), _m(1512, 9101, _T - 7 * 86400 + 3000, OPG, PV1, False),
    _m(1513, 9102, _T, GOF, VW, True), _m(1514, 9102, _T + 3000, VW, GOF, False),             # Gofore 2-0 VW
    _m(1515, 9103, _T + 7000, PV1, GOF, True), _m(1516, 9103, _T + 10000, GOF, PV1, True),
    _m(1517, 9103, _T + 13000, PV1, GOF, True),                                               # PV-1 2-1 Gofore
]

# Season 14 (one league): a plain best-of-3 final, teams Blues and Reds.
BLUES = _team(301, "Blues", 41)
REDS = _team(302, "Reds", 46)
S14 = [_m(1401, 9201, _T, BLUES, REDS, True), _m(1402, 9201, _T + 3000, REDS, BLUES, False)]

_FILE = {
    "seasons": [
        {"season": 13, "leagues": [1301], "empty_leagues": [1302]},
        {"season": 14, "leagues": [1400]},
        {"season": 15, "leagues": [19368, 19369]},
        {"season": 16, "leagues": [1600]},
    ],
}
S13 = [_m(1301 * 10 + i, 9300 + i, _T + i * 4000, REDS, BLUES, True) for i in range(1)]  # one game: review
_LEAGUES = {1301: [m["match_id"] for m in S13], 1400: [m["match_id"] for m in S14],
            19368: [m["match_id"] for m in S15_DIV1], 19369: [m["match_id"] for m in S15_DIV2],
            1600: [99901]}
_MATCHES = {m["match_id"]: m for m in S13 + S14 + S15_DIV1 + S15_DIV2}


def _slim(mod, matches):
    return [mod.slim_match(m) for m in matches]


def _places(mod, matches):
    return mod.derive_placements(_slim(mod, matches))


def _league_file(tmp_path, data=None):
    import json
    path = tmp_path / "leagues.json"
    path.write_text(json.dumps(_FILE if data is None else data))
    return str(path)


def _build(db, tmp_path, monkeypatch, data=None, live="Season 16", max_calls=None, mod=None, **kw):
    """Run `build` against the mocked OpenDota; returns code, calls, output and the CSV rows."""
    mod = mod or _mod()
    calls = SimpleNamespace(ids=[], matches=[])

    def ids(lid):
        calls.ids.append(lid)
        return _LEAGUES.get(lid)

    def match(mid):
        calls.matches.append(mid)
        return _MATCHES.get(mid)
    monkeypatch.setattr(mod, "fetch_match_ids", ids)
    monkeypatch.setattr(mod, "fetch_match", match)
    monkeypatch.setattr(accolades, "current_season_label", lambda _db: live)
    out, sleeps = [], []
    table = tmp_path / "table.csv"
    code = mod.run_build(db, league_file=_league_file(tmp_path, data), cache_path=str(tmp_path / "cache.json"),
                         table_path=str(table), max_calls=max_calls, pause=0.5, sleep=sleeps.append,
                         out=out.append, **kw)
    rows, header = [], None
    if table.exists():
        with open(table, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header, rows = reader.fieldnames, list(reader)
    return SimpleNamespace(code=code, calls=calls, out="\n".join(out), rows=rows, header=header,
                           mod=mod, cache=tmp_path / "cache.json")


def _by(rows, season, division):
    return [r for r in rows if r["season"] == str(season) and r["division"] == division]


# Table rows for apply.
def _trow(season=15, division="div1", place=1, team="OP Platinum", players="1:Alpha;2:Bravo",
          reviewed="yes", **extra):
    row = {"season": season, "division": division, "place": place, "team_name": team, "team_id": "",
           "players": players, "matches_per_player": "", "evidence": "final", "confidence": "high",
           "reviewed": reviewed}
    row.update(extra)
    return row


def _table(tmp_path, rows):
    mod = _mod()
    path = tmp_path / "placements.csv"
    mod.write_table(str(path), rows)
    return str(path)


def _apply(db, path, **kw):
    out = []
    code = _mod().run_apply(db, path, out=out.append, **kw)
    return SimpleNamespace(code=code, out="\n".join(out))


def _rows(db, **filters):
    db.expire_all()
    return db.query(SeasonAccolade).filter_by(**filters).all()


def _audits(db):
    db.expire_all()
    return db.query(AuditLog).filter_by(action="admin_placements_backfilled").all()


def _acc(db, season, kind, pid, name, division=None, team=None):
    db.add(SeasonAccolade(season_label=season, kind=kind, player_account_id=pid, player_name=name,
                          division=division, team_name=team, source="admin", created_at=int(time.time())))
    db.commit()


_FULL = [_trow(place=1), _trow(place=2, team="Visma Tormentor", players="3:Charlie;4:Delta"),
         _trow(place=3, team="Elisa Oyj", players="5:Echo")]


# ===========================================================================
# Story 1: Build the Placements Table From OpenDota
# ===========================================================================

class TestSeriesGrouping:

    def test_group_series_by_series_id(self):
        """Matches sharing a `series_id` form one series; the series records both teams,
        the games won by each (e.g. 2-1), its winner/loser and its last start_time, and
        series are ordered by start time."""
        mod = _mod()
        matches = _slim(mod, S15_DIV1)
        series = mod.group_series(matches)
        assert [s["series_id"] for s in series] == [9001, 9002, 9003, 9004]
        final = series[-1]
        assert final["games"] == 3 and final["winner"] == 101 and final["loser"] == 103
        assert final["wins"] == {101: 2, 103: 1}
        assert final["end"] == _T + 16000 and final["start"] == _T + 10000
        teams = mod.Teams(matches)
        assert mod.score(final, teams) == "OP Platinum 2–1 Visma Tormentor"

    def test_group_series_without_series_id_uses_team_pair_and_day(self):
        """Old matches with `series_id` 0/None are grouped by unordered team pair and UTC
        day: two games A-B on the same day form one series; an A-B game on another day
        forms a separate series."""
        mod = _mod()
        day = (_T // 86400) * 86400 + 3600
        matches = _slim(mod, [
            _m(1, None, day, BLUES, REDS, True), _m(2, 0, day + 3000, REDS, BLUES, True),
            _m(3, None, day + 86400, BLUES, REDS, False),
        ])
        series = mod.group_series(matches)
        assert [s["games"] for s in series] == [2, 1]
        assert series[0]["match_ids"] == [1, 2]
        assert series[0]["winner"] is None  # 1-1
        assert series[1]["match_ids"] == [3] and series[1]["winner"] == 302


class TestPlacementRules:

    def test_placements_final_is_last_series_winner_and_loser(self):
        """1st and 2nd are the winner and loser of the league's last series (a best-of-3
        final), and the evidence names it, e.g. "final OP Platinum 2–1 Visma Tormentor"."""
        mod = _mod()
        rows = _places(mod, S14)
        assert [(r["place"], r["team_name"], r["confidence"]) for r in rows[:2]] == [
            (1, "Blues", "high"), (2, "Reds", "high")]
        assert rows[0]["evidence"] == "final Blues 2–0 Reds"
        rows = _places(mod, S15_DIV1)
        assert rows[0]["team_name"] == "OP Platinum" and rows[1]["team_name"] == "Visma Tormentor"
        assert rows[0]["team_id"] == 101
        assert "final OP Platinum 2–1 Visma Tormentor" in rows[0]["evidence"]

    def test_placements_third_place_match_is_high_confidence(self):
        """When a series between the two semifinal losers follows the semifinals, its
        winner is 3rd with confidence `high`, and the evidence lists that series."""
        mod = _mod()
        third = _places(mod, S15_DIV1)[2]
        assert third["team_name"] == "Elisa Oyj" and third["confidence"] == "high"
        assert "3rd-place match Elisa Oyj 1–0 Reaktor" in third["evidence"]
        assert "semifinal OP Platinum 2–0 Elisa Oyj" in third["evidence"]
        assert "semifinal Visma Tormentor 2–0 Reaktor" in third["evidence"]

    def test_placements_double_elimination_third_is_low_confidence(self):
        """With no 3rd-place match, 3rd is the loser of the last series before the final
        involving the final's loser (lower-bracket final), with confidence `low`."""
        mod = _mod()
        third = _places(mod, S15_DIV2)[2]
        assert third["team_name"] == "Visma Wisdom" and third["confidence"] == "low"
        assert "Gofore/Loihde 2–0 Visma Wisdom" in third["evidence"]
        # Without the 3rd-place match the Div 1 shape falls back to the same rule.
        no_bronze = [m for m in S15_DIV1 if m["series_id"] != 9003]
        third = _places(mod, no_bronze)[2]
        assert (third["team_name"], third["confidence"]) == ("Reaktor", "low")

    def test_placements_final_not_best_of_two_or_more_needs_review(self):
        """Failure path: a last series of a single game (series_type 0 / one match) gives
        rows with confidence `review` and no guessed team names for places 1-3."""
        mod = _mod()
        single = S14[:1] + [_m(1499, 9299, _T + 9000, BLUES, REDS, True, stype=0)]
        rows = _places(mod, single)
        assert [r["confidence"] for r in rows] == ["review"] * 3
        assert all(r["team_name"] == "" and r["team_key"] is None for r in rows)
        assert "single game" in rows[0]["evidence"]

    def test_placements_missing_team_names_needs_review(self):
        """Failure path: a final whose matches lack radiant_name/dire_name (and team ids)
        yields `review` rows and no placement is guessed."""
        mod = _mod()
        nameless = [_m(1, 9500, _T, BLUES, REDS, True, ids=False, names=False),
                    _m(2, 9500, _T + 3000, REDS, BLUES, False, ids=False, names=False)]
        rows = _places(mod, nameless)
        assert [r["confidence"] for r in rows] == ["review"] * 3
        assert all(not r["team_name"] for r in rows)
        # Ids but no names: still no guess.
        id_only = [_m(1, 9500, _T, BLUES, REDS, True, names=False), _m(2, 9500, _T + 3000, REDS, BLUES, False, names=False)]
        rows = _places(mod, id_only)
        assert [r["confidence"] for r in rows] == ["review"] * 3 and "names missing" in rows[0]["evidence"]

    def test_placements_season_15_spike_reproduced(self):
        """From the recorded S15 fixture (leagues 19368, 19369): Div 1 places are
        1 OP Platinum, 2 Visma Tormentor, 3 Elisa Oyj, all confidence `high`; Div 2 places
        are 1 PV-1, 2 Gofore/Loihde (final 2–1) and the 3rd-place row has confidence `low`."""
        mod = _mod()
        div1 = _places(mod, S15_DIV1)
        assert [(r["team_name"], r["confidence"]) for r in div1] == [
            ("OP Platinum", "high"), ("Visma Tormentor", "high"), ("Elisa Oyj", "high")]
        div2 = _places(mod, S15_DIV2)
        assert [r["team_name"] for r in div2[:2]] == ["PV-1", "Gofore/Loihde"]
        assert "final PV-1 2–1 Gofore/Loihde" in div2[0]["evidence"]
        assert div2[2]["confidence"] == "low"


class TestRosters:

    def test_roster_lists_players_with_match_counts_by_team_id(self):
        """A team's roster is every account with at least one match on that team's side
        (matched by team id) in the league, with per-player match counts, so a substitute
        with 1 match shows `account:1` in matches_per_player."""
        mod = _mod()
        sub = dict(BLUES, players=[41, 42, 43, 44, 99])
        matches = _slim(mod, S14 + [_m(1403, 9202, _T + 9000, sub, REDS, True)])
        r = mod.roster(matches, 301)
        assert sorted(r) == [41, 42, 43, 44, 45, 99]
        assert r[41]["matches"] == 3 and r[45]["matches"] == 2 and r[99]["matches"] == 1
        names = {a: f"n{a}" for a in r}
        players, counts = mod.format_players(r, names)
        assert counts.startswith("41:3;42:3;43:3;44:3;45:2") and counts.endswith("99:1")
        assert players.split(";")[0] == "41:n41"

    def test_roster_matches_by_team_name_when_id_missing(self):
        """When a match has no team id for a side, its players are credited to the team
        whose name matches that side's name."""
        mod = _mod()
        no_id = _m(1403, 9202, _T + 9000, dict(BLUES, players=[41, 77, 43, 44, 45]), REDS, True, ids=False)
        matches = _slim(mod, S14 + [no_id])
        r = mod.roster(matches, 301)
        assert r[77]["matches"] == 1 and r[41]["matches"] == 3
        assert 46 not in r

    def test_roster_names_prefer_player_pool_then_personaname(self, db):
        """A player in the Player table gets the pool name; one not in the pool gets the
        match's personaname; anonymous players (account_id None) are left out."""
        mod = _mod()
        db.add(Player(id=41, name="Pool Name"))
        db.commit()
        players = {41: {"matches": 2, "personaname": "persona41"}, 42: {"matches": 1, "personaname": "persona42"},
                   43: {"matches": 1, "personaname": None}}
        assert mod.roster_names(db, players) == {41: "Pool Name", 42: "persona42", 43: "Player 43"}
        anon = _m(1403, 9202, _T, BLUES, REDS, True,
                  players=[{"account_id": None, "personaname": "anon", "isRadiant": True},
                           {"account_id": 41, "personaname": "x", "player_slot": 0}])
        r = mod.roster(_slim(mod, [anon]), 301)
        assert list(r) == [41]

    def test_roster_excludes_players_of_other_teams(self):
        """Failure path: players on the opposing side of the placed team's matches are
        not in its roster."""
        mod = _mod()
        r = mod.roster(_slim(mod, S15_DIV1), 101)
        assert sorted(r) == [1, 2, 3, 4, 5]
        assert all(r[a]["matches"] == 5 for a in r)
        assert not set(r) & set(VT["players"] + ELISA["players"])


class TestBuildCommand:

    def test_build_writes_csv_with_planned_columns(self, db, tmp_path, monkeypatch):
        """`build` writes the CSV header exactly: season, division, place, team_name,
        team_id, players (`account_id:name;…`), matches_per_player, evidence, confidence,
        reviewed; one row per season, division and place 1-3; `reviewed` is blank."""
        res = _build(db, tmp_path, monkeypatch)
        assert res.code == 0, res.out
        assert res.header == ["season", "division", "place", "team_name", "team_id", "players",
                              "matches_per_player", "evidence", "confidence", "reviewed"]
        div1 = _by(res.rows, 15, "div1")
        assert [r["place"] for r in div1] == ["1", "2", "3"]
        assert div1[0]["team_name"] == "OP Platinum" and div1[0]["team_id"] == "101"
        assert div1[0]["players"] == "1:p1;2:p2;3:p3;4:p4;5:p5"
        assert div1[0]["matches_per_player"] == "1:5;2:5;3:5;4:5;5:5"
        assert all(r["reviewed"] == "" for r in res.rows)
        assert {(r["season"], r["division"]) for r in res.rows} == {
            ("13", "div1"), ("13", "div2"), ("14", "div1"), ("15", "div1"), ("15", "div2")}
        assert len(res.rows) == 15

    def test_build_skips_live_season(self, db, tmp_path, monkeypatch):
        """`build` covers every season in the league file except the live one (pinned via
        accolades.current_season_label); no OpenDota call is made for the live league."""
        res = _build(db, tmp_path, monkeypatch, live="Season 16")
        assert 1600 not in res.calls.ids and 99901 not in res.calls.matches
        assert not _by(res.rows, 16, "div1")
        assert "Skipping Season 16" in res.out
        res = _build(db, tmp_path, monkeypatch, live="Season 15")
        assert 19368 not in res.calls.ids and not _by(res.rows, 15, "div1")

    def test_build_divisions_single_league_div1_lower_league_div2(self, db, tmp_path, monkeypatch):
        """A season with one league records its rows as `div1`; from S11 on the second
        ("Lower") league is recorded as `div2`."""
        res = _build(db, tmp_path, monkeypatch)
        assert [r["team_name"] for r in _by(res.rows, 14, "div1")][:2] == ["Blues", "Reds"]
        assert not _by(res.rows, 14, "div2")
        assert [r["team_name"] for r in _by(res.rows, 15, "div2")][:2] == ["PV-1", "Gofore/Loihde"]
        assert _by(res.rows, 15, "div2")[2]["confidence"] == "low"

    def test_build_empty_league_listed_as_review(self, db, tmp_path, monkeypatch):
        """Failure path: a league with no matches (listed in `empty_leagues`, like S10 and
        S13 Div 2) appears with confidence `review` and no team names."""
        res = _build(db, tmp_path, monkeypatch)
        empty = _by(res.rows, 13, "div2")
        assert [r["confidence"] for r in empty] == ["review"] * 3
        assert all(r["team_name"] == "" and r["players"] == "" for r in empty)
        assert "empty league" in empty[0]["evidence"]
        assert 1302 not in res.calls.ids
        assert [r["confidence"] for r in _by(res.rows, 13, "div1")] == ["review"] * 3  # single-game final

    def test_build_max_calls_defaults_to_900(self):
        """The CLI parser's `--max-calls` defaults to 900."""
        mod = _mod()
        assert mod.build_parser().parse_args(["build"]).max_calls == 900
        assert mod.DEFAULT_MAX_CALLS == 900

    def test_build_max_calls_stops_with_exit_2_and_keeps_cache(self, db, tmp_path, monkeypatch):
        """With a small --max-calls the build stops cleanly with exit code 2, prints a
        resume message, and the cache file holds every match fetched so far."""
        import json
        res = _build(db, tmp_path, monkeypatch, max_calls=6)
        assert res.code == 2
        assert "Budget used: resume to continue from Season" in res.out
        assert not res.rows  # no table on a budget stop
        cache = json.loads(res.cache.read_text())
        fetched = [m for m in res.calls.matches]
        assert sorted(int(k) for k in cache["matches"]) == sorted(fetched)
        assert len(res.calls.ids) + len(res.calls.matches) == 6

    def test_build_resume_spends_no_calls_on_cached_matches(self, db, tmp_path, monkeypatch):
        """A rerun after a budget stop fetches only uncached matches (the mock records no
        repeat match id) and completes with exit code 0 and the full CSV."""
        first = _build(db, tmp_path, monkeypatch, max_calls=10)
        assert first.code == 2
        second = _build(db, tmp_path, monkeypatch, max_calls=900)
        assert second.code == 0, second.out
        assert not set(first.calls.matches) & set(second.calls.matches)
        assert not set(first.calls.ids) & set(second.calls.ids)
        assert len(set(second.calls.matches)) == len(second.calls.matches)
        assert len(second.rows) == 15

    def test_build_prints_champion_comparison_when_different(self, db, tmp_path, monkeypatch):
        """With a champion recorded for Season N div1 under team "Reds" and the derived
        champion "Blues", `build` output names the season, division and both teams; a
        matching recorded champion prints no difference line."""
        _acc(db, "Season 14", "champion", 41, "A", division="div1", team="Reds")
        _acc(db, "Season 15", "champion", 1, "B", division="div1", team="OP Platinum")
        res = _build(db, tmp_path, monkeypatch)
        lines = [ln for ln in res.out.splitlines() if "differs" in ln]
        assert len(lines) == 1
        assert "Season 14" in lines[0] and "div1" in lines[0] and "Blues" in lines[0] and "Reds" in lines[0]

    def test_build_writes_nothing_to_database(self, db, tmp_path, monkeypatch):
        """`build` leaves season_accolades and audit_log row counts unchanged (zero before
        and after)."""
        assert db.query(SeasonAccolade).count() == 0 and db.query(AuditLog).count() == 0
        res = _build(db, tmp_path, monkeypatch)
        assert res.code == 0
        db.expire_all()
        assert db.query(SeasonAccolade).count() == 0 and db.query(AuditLog).count() == 0


# ===========================================================================
# Story 2: Apply the Reviewed Table
# ===========================================================================

class TestApplyCommand:

    def test_apply_writes_only_reviewed_rows_and_lists_skipped(self, db, tmp_path):
        """Only CSV rows with reviewed=yes are written; other rows are named in the
        output as skipped and produce no accolades."""
        path = _table(tmp_path, [_trow(place=1), _trow(place=2, team="Visma Tormentor", players="3:C", reviewed=""),
                                 _trow(place=3, team="Elisa Oyj", players="5:E", reviewed="no")])
        res = _apply(db, path)
        assert res.code == 0
        assert {r.kind for r in _rows(db)} == {"champion"}
        assert "Skipped line 3 (Season 15 div1 place 2 Visma Tormentor): not reviewed" in res.out
        assert "Skipped line 4 (Season 15 div1 place 3 Elisa Oyj): not reviewed" in res.out

    def test_apply_place_1_written_through_set_champions(self, db, tmp_path, monkeypatch):
        """Place 1 becomes `champion` rows (season label "Season N", division, team name,
        one per player) via accolades.set_champions (spy records the call)."""
        calls = []
        real = accolades.set_champions
        monkeypatch.setattr(accolades, "set_champions", lambda *a, **k: calls.append(a) or real(*a, **k))
        res = _apply(db, _table(tmp_path, [_trow(place=1)]))
        assert res.code == 0
        assert calls and calls[0][1:5] == ("Season 15", "div1", "OP Platinum",
                                           [{"account_id": 1, "name": "Alpha"}, {"account_id": 2, "name": "Bravo"}])
        rows = _rows(db, kind="champion")
        assert sorted((r.season_label, r.division, r.team_name, r.player_account_id, r.player_name) for r in rows) == [
            ("Season 15", "div1", "OP Platinum", 1, "Alpha"), ("Season 15", "div1", "OP Platinum", 2, "Bravo")]

    def test_apply_places_2_and_3_written_as_runner_up_and_third_place(self, db, tmp_path):
        """Places 2 and 3 become `runner_up` and `third_place` rows with division and
        team name, one per player, through accolades.set_placement."""
        res = _apply(db, _table(tmp_path, _FULL + [_trow(division="div2", place=2, team="Gofore/Loihde", players="31:G")]))
        assert res.code == 0
        ru = _rows(db, kind="runner_up")
        assert sorted((r.division, r.team_name, r.player_account_id) for r in ru) == [
            ("div1", "Visma Tormentor", 3), ("div1", "Visma Tormentor", 4), ("div2", "Gofore/Loihde", 31)]
        third = _rows(db, kind="third_place")
        assert [(r.division, r.team_name, r.player_account_id, r.player_name) for r in third] == [
            ("div1", "Elisa Oyj", 5, "Echo")]

    def test_apply_skips_existing_champions_without_replace(self, db, tmp_path):
        """Failure path: with champions already recorded for that season and division,
        `apply` prints a skip message and leaves the existing champion rows untouched."""
        _acc(db, "Season 15", "champion", 9, "Hand", division="div1", team="Hand Team")
        res = _apply(db, _table(tmp_path, [_trow(place=1)]))
        assert "skipped" in res.out and "Hand Team" in res.out and "--replace" in res.out
        rows = _rows(db, kind="champion")
        assert [(r.player_account_id, r.team_name) for r in rows] == [(9, "Hand Team")]

    def test_apply_replace_overwrites_existing_champions(self, db, tmp_path):
        """With --replace the season/division's champions become exactly the table's
        place-1 players."""
        _acc(db, "Season 15", "champion", 9, "Hand", division="div1", team="Hand Team")
        _acc(db, "Season 15", "champion", 2, "Old Bravo", division="div1", team="Hand Team")
        res = _apply(db, _table(tmp_path, [_trow(place=1)]), replace=True)
        assert res.code == 0
        rows = _rows(db, kind="champion", season_label="Season 15", division="div1")
        assert sorted((r.player_account_id, r.player_name, r.team_name) for r in rows) == [
            (1, "Alpha", "OP Platinum"), (2, "Bravo", "OP Platinum")]

    def test_apply_rerun_adds_nothing(self, db, tmp_path):
        """A second `apply` of the same table leaves the season_accolades row count
        unchanged."""
        path = _table(tmp_path, _FULL)
        _apply(db, path)
        n = len(_rows(db))
        assert n == 5
        res = _apply(db, path)
        assert len(_rows(db)) == n
        assert res.out.count("already recorded") == 3
        assert len(_audits(db)) == 1  # the rerun changed nothing, so no second audit

    def test_apply_writes_one_audit_entry_per_season(self, db, tmp_path):
        """Each applied season writes exactly one `admin_placements_backfilled` audit
        entry whose detail names the season, the places written and player counts."""
        rows = _FULL + [_trow(season=14, place=1, team="Blues", players="41:A;42:B;43:C")]
        _apply(db, _table(tmp_path, rows))
        audits = _audits(db)
        assert len(audits) == 2
        s15 = next(a for a in audits if "season_label=Season 15" in a.detail)
        assert "places=div1:1,2,3" in s15.detail and "players=div1:1=2;div1:2=2;div1:3=1" in s15.detail
        assert s15.actor_username == "script"
        s14 = next(a for a in audits if "season_label=Season 14" in a.detail)
        assert "places=div1:1" in s14.detail and "div1:1=3" in s14.detail

    def test_apply_dry_run_writes_nothing(self, db, tmp_path):
        """`--dry-run` prints what would be written and leaves season_accolades and
        audit_log empty."""
        res = _apply(db, _table(tmp_path, _FULL), dry_run=True)
        assert "Dry run" in res.out
        assert "Would write Season 15 Div 1 Champion OP Platinum (2 players)" in res.out
        assert "Would write Season 15 Div 1 Runner-up Visma Tormentor (2 players)" in res.out
        assert "Would write Season 15 Div 1 Third place Elisa Oyj (1 players)" in res.out
        db.expire_all()
        assert db.query(SeasonAccolade).count() == 0 and db.query(AuditLog).count() == 0

    def test_apply_rejects_malformed_row(self, db, tmp_path):
        """Failure path: a reviewed row with an invalid division, place outside 1-3 or an
        unparsable players field is reported and not written."""
        rows = [_trow(division="div3"), _trow(place=4), _trow(players="1-Alpha"), _trow(players="x:Alpha"),
                _trow(team=""), _trow(place=2, team="Visma Tormentor", players="3:Charlie")]
        res = _apply(db, _table(tmp_path, rows))
        assert res.code == 1
        assert "division must be div1 or div2" in res.out
        assert "place must be 1, 2 or 3" in res.out
        assert res.out.count("is not id:name") == 2
        assert "team_name is empty" in res.out
        assert [(r.kind, r.player_account_id) for r in _rows(db)] == [("runner_up", 3)]


# ===========================================================================
# Story 3: Runner-up and Third Place Accolades
# ===========================================================================

class TestNewKindsBackend:

    def test_kinds_include_runner_up_and_third_place(self):
        """accolades.KINDS contains "runner_up" and "third_place"."""
        assert "runner_up" in accolades.KINDS and "third_place" in accolades.KINDS
        assert accolades.PLACEMENT_KINDS == ("runner_up", "third_place")

    def test_accolade_kinds_new_entries_icons_and_tokens(self):
        """accolades.ACCOLADE_KINDS has runner_up entries (Lucide `medal`, token
        `--accolade-runner-up`) and third_place entries (Lucide `award`, token
        `--accolade-third`), named "Div N Runner-up" / "Div N Third place", after the
        champion entries."""
        kinds = accolades.ACCOLADE_KINDS
        got = [(k["key"], k["kind"], k["division"], k["name"], k["icon"], k["token"]) for k in kinds[2:6]]
        assert got == [
            ("div1_runner_up", "runner_up", "div1", "Div 1 Runner-up", "medal", "--accolade-runner-up"),
            ("div2_runner_up", "runner_up", "div2", "Div 2 Runner-up", "medal", "--accolade-runner-up"),
            ("div1_third", "third_place", "div1", "Div 1 Third place", "award", "--accolade-third"),
            ("div2_third", "third_place", "div2", "Div 2 Third place", "award", "--accolade-third"),
        ]
        assert [k["kind"] for k in kinds[:2]] == ["champion", "champion"]
        assert accolades.kind_key({"kind": "runner_up", "division": "div2"}) == "div2_runner_up"
        assert accolades.kind_key({"kind": "third_place", "division": "div1"}) == "div1_third"

    def test_accolade_kinds_backend_and_frontend_agree_with_new_kinds(self):
        """Source-reading: ACCOLADE_KINDS in frontend/app-globals.js includes the new
        kinds and matches the backend list (order, name, icon, token)."""
        js = _fe("app-globals.js")
        block = js[js.index("const ACCOLADE_KINDS = ["):]
        block = block[:block.index("];")]
        fields = ("key", "kind", "division", "name", "icon", "plate", "token")
        frontend = []
        for line in block.splitlines()[1:]:
            if line.strip():
                frontend.append({f: re.search(rf'\b{f}: (?:"([^"]*)"|null)', line).group(1) for f in fields})
        backend = [{f: k[f] for f in fields} for k in accolades.ACCOLADE_KINDS]
        assert frontend == backend
        assert {"runner_up", "third_place"} <= {k["kind"] for k in frontend}

    def test_set_placement_writes_rows_per_player(self, db):
        """accolades.set_placement(db, "Season 15", "div1", "runner_up", "Visma
        Tormentor", players) writes one row per player with that kind, division and team."""
        players = [{"account_id": 11, "name": "K"}, {"account_id": 12, "name": "L"}]
        assert accolades.set_placement(db, "Season 15", "div1", "runner_up", "Visma Tormentor", players) == (2, 0)
        db.commit()
        rows = _rows(db, kind="runner_up")
        assert sorted((r.season_label, r.division, r.team_name, r.player_account_id, r.player_name) for r in rows) == [
            ("Season 15", "div1", "Visma Tormentor", 11, "K"), ("Season 15", "div1", "Visma Tormentor", 12, "L")]
        assert accolades.set_placement(db, "Season 15", "div1", "runner_up", "Visma Tormentor", players) == (0, 0)
        assert accolades.set_placement(db, "Season 15", "div1", "runner_up", "Visma Tormentor", players[:1]) == (0, 1)
        with pytest.raises(ValueError):
            accolades.set_placement(db, "Season 15", "div1", "champion", "X", players)

    def test_holo_not_unlocked_by_runner_up_or_third_place(self, db):
        """Failure path: a player with only runner_up and third_place accolades in a past
        season is not holo_eligible; a past champion is."""
        _acc(db, "Season 14", "runner_up", 5, "E", division="div1", team="T")
        _acc(db, "Season 13", "third_place", 5, "E", division="div2", team="U")
        _acc(db, "Season 14", "champion", 6, "F", division="div1", team="V")
        assert accolades.holo_eligible(db, 5, current="Season 16") is False
        assert accolades.holo_eligible(db, 6, current="Season 16") is True


class TestAdminValidation:

    def test_post_accolade_accepts_runner_up_with_division_and_team(self, db):
        """POST /admin/season-accolades (or AccoladeIn) accepts kind runner_up and
        third_place with a division and team name, and the row is stored."""
        from routers import admin_accolades
        admin = {"user_id": 1, "username": "admin"}
        for kind in ("runner_up", "third_place"):
            body = admin_accolades.AccoladeIn(season_label="Season 15", kind=kind, division="div2",
                                              team_name=" Gofore/Loihde ", player_account_id=31, player_name="G")
            out = admin_accolades.add_season_accolades(body, db=db, admin=admin)
            assert (out["kind"], out["division"], out["team_name"]) == (kind, "div2", "Gofore/Loihde")
        assert sorted(r.kind for r in _rows(db, player_account_id=31)) == ["runner_up", "third_place"]
        listed = admin_accolades.list_season_accolades(season=None, kind=None, db=db, _=admin)
        assert [r["kind"] for r in listed] == ["runner_up", "third_place"]

    def test_post_accolade_runner_up_without_division_or_team_rejected(self, db):
        """Failure path: kind runner_up/third_place without a division or without a team
        name answers 422 (AccoladeIn raises), like champion."""
        from routers import admin_accolades
        for kind, name in (("runner_up", "runner-up"), ("third_place", "third place")):
            with pytest.raises(ValidationError, match=f"A {name} needs a division"):
                admin_accolades.AccoladeIn(season_label="Season 15", kind=kind, team_name="T", player_account_id=1)
            with pytest.raises(ValidationError, match=f"A {name} needs a team name"):
                admin_accolades.AccoladeIn(season_label="Season 15", kind=kind, division="div1", player_account_id=1)
        with pytest.raises(ValidationError, match="has a division"):
            admin_accolades.AccoladeIn(season_label="Season 15", kind="most_points", division="div1", player_account_id=1)

    def test_admin_accolade_editor_offers_new_kinds(self):
        """Source-reading: the Player management accolade editor's kind options include
        runner_up and third_place, and require division and team for them."""
        html = _fe("index.html")
        select = html[html.index('<select id="accKind"'):]
        select = select[:select.index("</select>")]
        assert '<option value="runner_up">' in select and '<option value="third_place">' in select
        assert 'id="accDivisionWrap"' in html and 'id="accTeamWrap"' in html and 'id="accTeam"' in html
        js = _fe("app-admin-players.js")
        assert 'const ACCOLADE_PLACEMENT_KINDS = ["runner_up", "third_place"];' in js
        changed = _fn_body(js, "accKindChanged")
        assert '"accDivisionWrap").hidden = !isPlacement' in changed and '"accTeamWrap").hidden = !isPlacement' in changed
        save = _fn_body(js, "saveAccolade")
        assert "Enter the team name" in save and 'division: document.getElementById("accDivision").value' in save
        assert "team_name" in _fn_body(js, "editAccoladeValue")


class TestNewKindsDisplay:

    def test_timeline_runner_up_line_names_place_and_team(self):
        """Popup timeline (test_issue_230 `_section`): a runner_up S15 div1 "Visma
        Tormentor" renders "S15 Div 1 Runner-up · with Visma Tormentor"."""
        _, html = _section([_a("runner_up", "Season 15", "div1", "Visma Tormentor")])
        assert _entries(html) == [["S15 Div 1 Runner-up · with Visma Tormentor"]]
        _, html = _section([_a("runner_up", "Season 15", "div1", "Visma Tormentor"),
                            _a("champion", "Season 15", "div2", "PV-1"), _a("most_points", "Season 15", value=5)])
        assert _entries(html) == [["S15 Div 2 Champion · with PV-1", "S15 Div 1 Runner-up · with Visma Tormentor",
                                   "S15 Most Points · 5.0 pts"]]

    def test_timeline_third_place_line_names_place_and_team(self):
        """Popup timeline: a third_place S15 div1 "Elisa Oyj" renders
        "S15 Div 1 Third place · with Elisa Oyj"."""
        _, html = _section([_a("third_place", "Season 15", "div1", "Elisa Oyj")])
        assert _entries(html) == [["S15 Div 1 Third place · with Elisa Oyj"]]
        # Placements are not season awards: the tile counts only the four awards.
        _, html = _section([_a("third_place", "Season 15", "div1", "Elisa Oyj"), _a("best_match", "Season 14", value=1)])
        assert "".join(html.split()).count('<divclass="val">1</div><divclass="lbl">Seasonawards') == 1

    def test_new_kind_without_team_omits_with_clause(self):
        """Failure path: a runner_up with no team name renders "S15 Div 1 Runner-up" with
        no " · with", "undefined" or "null"."""
        _, html = _section([_a("runner_up", "Season 15", "div1", None)])
        assert _entries(html) == [["S15 Div 1 Runner-up"]]
        for bad in (" · with", "undefined", "null"):
            assert bad not in html

    def test_pips_and_chips_render_new_kinds_with_text(self):
        """Node harness (accoladePipsHtml / accoladeChipsHtml): runner_up and third_place
        get their own pip/chip classes and their text or aria label names the place, so
        meaning does not depend on colour."""
        acc = [_a("third_place", "Season 14", "div2", "U"), _a("runner_up", "Season 15", "div1", "T"),
               _a("champion", "Season 13", "div1", "V")]
        pips = _pip_attrs(_pips(acc))
        assert [c.split()[2] for c, _, _ in pips] == ["accolade-pip--div1", "accolade-pip--div1_runner_up",
                                                      "accolade-pip--div2_third"]
        assert "accolade-pip--outlined" in pips[1][0]
        assert pips[1][1] == "Div 1 Runner-up: S15 with T"
        assert pips[2][1] == "Div 2 Third place: S14 with U"
        chips = _chips(acc)
        assert 'class="accolade-chip accolade-chip--outlined accolade-chip--div1_runner_up" title="with T"' in chips
        assert "S15 Div 1 Runner-up</span>" in chips and "S14 Div 2 Third place</span>" in chips
        assert 'data-lucide="medal"' in chips and 'data-lucide="award"' in chips

    def test_hall_of_fame_lists_new_kinds(self, db):
        """accolades.history (Hall of fame) includes runner_up and third_place rows with
        place, division and team name."""
        _acc(db, "Season 15", "runner_up", 3, "Charlie", division="div1", team="Visma Tormentor")
        _acc(db, "Season 15", "third_place", 5, "Echo", division="div2", team="Visma Wisdom")
        _acc(db, "Season 15", "champion", 1, "Alpha", division="div1", team="OP Platinum")
        data = accolades.history(db, current="Season 17")
        s15 = data["seasons"][0]
        assert s15["placements"]["div1"]["runner_up"] == {"team_name": "Visma Tormentor",
                                                          "players": [{"account_id": 3, "name": "Charlie"}]}
        assert s15["placements"]["div2"]["third_place"]["team_name"] == "Visma Wisdom"
        assert s15["placements"]["div1"]["third_place"] is None
        fame = {f["player_name"]: f for f in data["hall_of_fame"]}
        assert [(a["kind"], a["division"], a["team_name"]) for a in fame["Charlie"]["accolades"]] == [
            ("runner_up", "div1", "Visma Tormentor")]
        assert (fame["Echo"]["titles"], fame["Echo"]["placement_titles"], fame["Echo"]["award_titles"]) == (1, 1, 0)
        assert fame["Alpha"]["champion_titles"] == 1
        # The History tab renders them under each division's champion.
        import json
        hist = _fe("app-history.js")
        html = _run_node(_globals_helpers_js() + "\n" + _fn_source(hist, "_historyPlacementsHtml") + f"""
const s = {json.dumps({"season_label": "Season 15", "season_short": "S15", **s15})};
console.log(JSON.stringify([_historyPlacementsHtml(s, "div1"), _historyPlacementsHtml({{}}, "div1")]));
""")
        assert "S15 Div 1 Runner-up</span>" in html[0] and "Visma Tormentor" in html[0]
        assert "Third place" not in html[0] and html[1] == ""
        assert "_historyPlacementsHtml(season, \"div2\")" in _fn_body(hist, "_historySeasonHtml")

    def test_tokens_in_both_colour_files_identical(self):
        """`--accolade-runner-up` and `--accolade-third` are defined in
        frontend/colors_and_type.css and design/colors_and_type.css, and the files are
        byte-identical."""
        fe = _read("frontend", "colors_and_type.css")
        de = _read("design", "colors_and_type.css")
        assert fe == de
        for name in ("runner-up", "third"):
            m = re.search(rf"--accolade-{name}:\s*([^;]+);", fe)
            assert m, name
            assert m.group(1).startswith("var(--"), name

    def test_style_css_new_kind_rules_use_tokens_before_guided_tour(self):
        """style.css pip/chip rules for the new kinds use var(--accolade-runner-up) /
        var(--accolade-third) (no raw colours) and sit before the GUIDED TOUR section."""
        css = _fe("style.css")
        tour = css.index("GUIDED TOUR (issue #144)")
        for key, token in (("div1_runner_up", "runner-up"), ("div2_runner_up", "runner-up"),
                           ("div1_third", "third"), ("div2_third", "third")):
            for sel in (f".accolade-pip--{key}", f".accolade-chip--{key}"):
                bodies = _rule(css[:tour], sel)
                assert bodies, sel
                assert f"var(--accolade-{token})" in bodies[0]
                assert not re.search(r"#[0-9a-fA-F]{3,8}\b", bodies[0]) and "rgba(" not in bodies[0]
            assert key not in css[tour:]
        assert "#233" not in css


# ---------------------------------------------------------------------------
# Security review Lows (change review of issue 233)
# ---------------------------------------------------------------------------

class TestScriptHardening:
    def test_parse_row_caps_players_per_team(self):
        """A reviewed row naming more than 50 players is rejected, like the admin API's cap."""
        sp = _mod()
        players = ";".join(f"{i}:P{i}" for i in range(1, 52))
        row = {"season": "15", "division": "div1", "place": "1", "team_name": "Team", "players": players}
        with pytest.raises(sp.RowError):
            sp.parse_row(row)
        row["players"] = ";".join(f"{i}:P{i}" for i in range(1, 51))
        assert len(sp.parse_row(row)["players"]) == 50

    def test_formula_cells_are_neutralised_and_read_back(self, tmp_path):
        """Cells starting with = + - @ are written with a leading ' and parse_row reads the name back unchanged."""
        sp = _mod()
        path = tmp_path / "t.csv"
        row = {c: "" for c in sp.COLUMNS}
        row.update(season=15, division="div1", place=1, team_name="=HYPERLINK(1)", players="7:Bob")
        sp.write_table(str(path), [row])
        text = path.read_text(encoding="utf-8")
        assert "'=HYPERLINK(1)" in text
        import csv as _csv
        back = next(_csv.DictReader(path.open(encoding="utf-8", newline="")))
        assert sp.parse_row(back)["team_name"] == "=HYPERLINK(1)"

    def test_terminal_output_strips_control_characters(self, db, tmp_path):
        """apply's skipped/rejected lines show table values without control characters."""
        sp = _mod()
        path = tmp_path / "t.csv"
        row = {c: "" for c in sp.COLUMNS}
        row.update(season=15, division="div1", place=1, team_name="Bad\x1b[31mTeam", players="7:Bob", reviewed="no")
        sp.write_table(str(path), [row])
        lines = []
        sp.run_apply(db, table_path=str(path), dry_run=True, out=lines.append)
        assert any("Skipped" in l for l in lines)
        assert not any("\x1b" in l for l in lines)
