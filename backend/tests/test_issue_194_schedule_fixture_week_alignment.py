"""
Failing test stubs for plan-issue-194-schedule-fixture-week-alignment.md (resolves GitHub issue #194).

Pre-implementation stage: `backend/schedule.py::_fixture_to_series` still anchors an
unscheduled fixture at its `week_start` Monday 00:00 and marks it `past` once that
moment has passed; it emits no `league_week`. `norm_team_name` keeps punctuation such
as "/", and `find_team_id`'s substring fallback returns the first containing key (so
"Innofactor/NordCloud" resolves to the old "Innofactor"). `frontend/app-players.js::seriesRow`
has no "League week N" tag. The tests below were written as stubs before the change
and now check the implementation.

The `schedule` module imports cleanly with no FastAPI dependency, so its functions are
exercised directly (as in test_issue_101_schedule_fixtures_api.py). `_league_now` is
monkeypatched for status checks. Frontend criteria are checked statically on
app-players.js and, when `node` is available, by running the real functions under the
Node harness from test_issue_156_schedule_visuals.py (`_run_schedule`, Europe/Helsinki).
Without Node only the static checks run (no skip).

  Story 1: Unscheduled Fixtures Stay in Their Own Week          (TestUnscheduledFixturesStayInTheirOwnWeek)
  Story 2: TBD Fixtures Don't Say "No Result" Before Their Week Ends (TestTbdFixturesNoResultOnlyAfterWeekEnds)
  Story 3: Team Names Match Despite Punctuation and Old Teams    (TestTeamNamesMatchDespitePunctuationAndOldTeams)
  Story 4: League Week Shown When It Differs                     (TestLeagueWeekShownWhenItDiffers)

Also to do in the same change (plan, Step 5): update
`test_issue_101_schedule_fixtures_api.py::test_fixture_to_series_falls_back_to_week_start_midnight_when_unscheduled`
to expect the Thursday-noon anchor.

Manual-only (see the plan's Verification section): the live season-16 feed after
`POST /schedule/refresh`, and the absence of ambiguous-name warnings in the logs.

STATUS: implemented.

Run with: cd backend && python -m pytest tests/test_issue_194_schedule_fixture_week_alignment.py -v
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import models  # noqa: F401  (register every table before the db fixture runs)
import schedule  # noqa: F401  (module under test)
from models import Match, Team  # noqa: F401
from tests.test_issue_151_weekly_report_aesthetics import _fn_body
from tests.test_issue_156_schedule_visuals import _load_schedule, _nested, _row, _run_schedule, _ts

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_APP_PLAYERS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-players.js")
_STYLE_CSS_PATH = os.path.join(_FRONTEND_DIR, "style.css")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _season16_weeks_4_5_feed():
    """A minimal copy of the season-16 feed around weeks 4 and 5: one played week-4
    fixture with `starts_at` (Visma-Futurice), the week-4 fixture played Mon 12.10.
    21:00 (Hoxhunt Fortum-Elisa Oyj), Reaktor-Innofactor/NordCloud (Wed 7.10.), and
    the four unscheduled week-5 fixtures (starts_at null, empty date, scheduled false)."""
    return {
        "season": "16",
        "fixtures": [
            {"week": 4, "division": "upper", "team1": "Visma", "team2": "Futurice",
             "starts_at": "2026-10-05T17:30:00Z", "date": "2026-10-05", "time": "20:30",
             "week_start": "2026-10-05", "scheduled": True, "stream": ""},
            {"week": 4, "division": "upper", "team1": "Reaktor", "team2": "Innofactor/NordCloud",
             "starts_at": "2026-10-07T17:30:00Z", "date": "2026-10-07", "time": "20:30",
             "week_start": "2026-10-05", "scheduled": True, "stream": ""},
            {"week": 4, "division": "lower", "team1": "Hoxhunt Fortum", "team2": "Elisa Oyj",
             "starts_at": "2026-10-12T18:00:00Z", "date": "2026-10-12", "time": "21:00",
             "week_start": "2026-10-05", "scheduled": True, "stream": ""},
            {"week": 5, "division": "upper", "team1": "Elisa Oyj", "team2": "OP Platinum",
             "starts_at": None, "date": "", "time": "", "week_start": "2026-10-12",
             "scheduled": False, "stream": ""},
            {"week": 5, "division": "upper", "team1": "Gofore/Frends", "team2": "Visma",
             "starts_at": None, "date": "", "time": "", "week_start": "2026-10-12",
             "scheduled": False, "stream": ""},
            {"week": 5, "division": "lower", "team1": "Elisa Appelsiini", "team2": "HOLISA",
             "starts_at": None, "date": "", "time": "", "week_start": "2026-10-12",
             "scheduled": False, "stream": ""},
            {"week": 5, "division": "lower", "team1": "PV-1", "team2": "Supercell",
             "starts_at": None, "date": "", "time": "", "week_start": "2026-10-12",
             "scheduled": False, "stream": ""},
        ],
    }


@pytest.fixture(autouse=True)
def _reset_schedule_cache(monkeypatch):
    monkeypatch.setattr(schedule, "SCHEDULE_SHEET_URL", "")
    monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "")
    monkeypatch.setattr(schedule, "_hero_icon_cache", {})
    schedule.bust_cache()
    yield
    schedule.bust_cache()


def _at(monkeypatch, *args):
    """Pin the league clock (naive Europe/Helsinki wall time)."""
    monkeypatch.setattr(schedule, "_league_now", lambda: datetime(*args))


def _tbd(week=5, week_start="2026-10-12", **extra):
    f = {"week": week, "division": "upper", "team1": "Elisa Oyj", "team2": "OP Platinum",
         "starts_at": None, "date": "", "time": "", "week_start": week_start,
         "scheduled": False, "stream": ""}
    f.update(extra)
    return f


# Fantasy weeks start Monday 03:00 UTC (06:00 Helsinki), issue #111.
_FANTASY_WEEKS = [
    {"week_id": 4, "label": "Week 4", "start_time": _ts(2026, 10, 5, 6), "end_time": _ts(2026, 10, 12, 6)},
    {"week_id": 5, "label": "Week 5", "start_time": _ts(2026, 10, 12, 6), "end_time": _ts(2026, 10, 19, 6)},
]
_TBD_TEAMS = [("Elisa Oyj", "OP Platinum"), ("Gofore", "Visma"), ("Elisa Appelsiini", "HOLISA"),
              ("PV-1", "Supercell")]


def _season16_schedule_data(monkeypatch, now=(2026, 10, 12, 10, 0), fantasy_weeks=None):
    """The /schedule payload the frontend gets for the season-16 copy: series built by
    the real parser, the clock pinned to `now`, no DB results."""
    _at(monkeypatch, *now)
    weeks, dropped = schedule.parse_fixtures_json(_season16_weeks_4_5_feed())
    assert dropped == 0
    return {
        "weeks": weeks, "extra_results": [], "cached_at": "2026-10-12T10:00:00", "stale": False,
        "error": None, "source": "fixtures_json", "live": [],
        "fantasy_weeks": fantasy_weeks if fantasy_weeks is not None else _FANTASY_WEEKS,
    }


def _panels(data):
    """Week 4 and Week 5 panels rendered by the real loadSchedule, or None without Node."""
    return _run_schedule("""
  await loadSchedule();
  out.panels = [];
  for (let i = 0; i < _schedWeeks.length; i++) { selectScheduleWeek(i); out.panels.push(snap().content); }
""", data=data)


def _tbd_group(panel):
    i = panel.find('<div class="schedule-date-hd">Time TBD</div>')
    return panel[i:] if i >= 0 else ""


# ---------------------------------------------------------------------------
# Story 1: Unscheduled Fixtures Stay in Their Own Week
# ---------------------------------------------------------------------------

class TestUnscheduledFixturesStayInTheirOwnWeek:
    """
    - A feed fixture with no `starts_at` and no `date` keeps `scheduled: false` and gets
      `datetime_iso` = its `week_start` + 3 days at 12:00, league time (the Thursday of
      its league week)
    - On the Schedule, it appears in the fantasy week that contains that Thursday, under
      "Time TBD"; for the season-16 feed, the four TBD week-5 fixtures appear in Week 5,
      not Week 4
    - A fixture with a `starts_at`, or a `date` and `time`, keeps today's behaviour
    - A fixture with neither a date nor a `week_start` is still dropped, and counted in
      `dropped`
    """

    def test_fixture_to_series_anchors_unscheduled_at_thursday_noon(self):
        """A fixture with no `starts_at` and no `date` keeps `scheduled: false` and gets `datetime_iso` = `week_start` + 3 days at 12:00 league time (week_start 2026-10-12 -> 2026-10-15T12:00:00)."""
        s = schedule._fixture_to_series(_tbd())
        assert s["datetime_iso"] == "2026-10-15T12:00:00"
        assert s["scheduled"] is False
        assert s["time"] is None

    def test_season16_tbd_week5_anchors_fall_in_fantasy_week_starting_mon_12_10(self):
        """With the season-16 week 4-5 copy, the four TBD week-5 fixtures' anchors fall inside the fantasy week starting Mon 12.10. 03:00 UTC, not the week before it."""
        weeks, dropped = schedule.parse_fixtures_json(_season16_weeks_4_5_feed())
        assert dropped == 0
        wk5 = next(w for w in weeks if w["label"] == "Week 5")
        tbd = [s for s in wk5["div1"] + wk5["div2"] if s["scheduled"] is False]
        assert len(tbd) == 4
        start = _FANTASY_WEEKS[1]["start_time"]
        end = _FANTASY_WEEKS[1]["end_time"]
        assert start == int(datetime(2026, 10, 12, 3, tzinfo=timezone.utc).timestamp())
        for s in tbd:
            t = int(datetime.fromisoformat(s["datetime_iso"]).replace(tzinfo=schedule.LEAGUE_TZ).timestamp())
            assert start <= t < end, s
            assert t >= _FANTASY_WEEKS[0]["end_time"]

    def test_assign_week_puts_tbd_fixture_in_week_containing_thursday(self, monkeypatch):
        """Node harness: `assignWeek` places a TBD series anchored on Thursday 15.10. 12:00 in Week 5 (fantasy week from Mon 12.10. 06:00 Helsinki), and the Week 5 view lists it under "Time TBD"; Week 4 lists none of the four."""
        out = _run_schedule("""
  const W = %s;
  out.r = assignWeek({datetime_iso: "2026-10-15T12:00:00", scheduled: false}, W);
  out.old = assignWeek({datetime_iso: "2026-10-12T00:00:00", scheduled: false}, W);
""" % json.dumps(_FANTASY_WEEKS))
        panels = _panels(_season16_schedule_data(monkeypatch))
        if out is None or panels is None:
            return
        assert out["r"] == 1
        assert out["old"] == 0  # the old Monday-midnight anchor fell into Week 4
        wk4, wk5 = panels["panels"]
        assert ">Week 4</h3>" in wk4 and ">Week 5</h3>" in wk5
        group = _tbd_group(wk5)
        for t1, t2 in _TBD_TEAMS:
            assert t1 in group and t2 in group, (t1, t2)
        for name in ("OP Platinum", "Gofore", "HOLISA", "Supercell"):
            assert name not in wk4, name
        assert "Time TBD" not in wk4

    def test_fixture_to_series_keeps_starts_at_and_date_time_behaviour(self, monkeypatch):
        """A fixture with `starts_at`, or with a `date` and `time`, gets the same `datetime_iso` and `scheduled: true` as before (no Thursday anchor applied)."""
        _at(monkeypatch, 2026, 10, 12, 10, 0)
        a = schedule._fixture_to_series(_tbd(starts_at="2026-10-13T17:30:00Z", time="20:30", scheduled=True))
        assert a["datetime_iso"] == "2026-10-13T20:30:00"
        assert a["scheduled"] is True
        assert a["match_status"] == "upcoming"
        b = schedule._fixture_to_series(_tbd(date="13.10.2026", time="19:00"))
        assert b["datetime_iso"] == "2026-10-13T19:00:00"
        assert b["scheduled"] is True
        c = schedule._fixture_to_series(_tbd(starts_at="2026-10-12T05:00:00Z", scheduled=True))
        assert c["datetime_iso"] == "2026-10-12T08:00:00"
        assert c["match_status"] == "past"  # a timed fixture is past once its time has passed

    def test_parse_fixtures_json_drops_fixture_without_date_or_week_start(self):
        """Failure path: a fixture with no `starts_at`, no `date` and no `week_start` is dropped from the series and counted in `dropped`."""
        weeks, dropped = schedule.parse_fixtures_json({"fixtures": [
            _tbd(week_start=""), _tbd(week_start=None), _tbd(team1="Kept"),
        ]})
        assert dropped == 2
        assert [(s["team1"], s["datetime_iso"]) for w in weeks for s in w["div1"] + w["div2"]] == [
            ("Kept", "2026-10-15T12:00:00")]


# ---------------------------------------------------------------------------
# Story 2: TBD Fixtures Don't Say "No Result" Before Their Week Ends
# ---------------------------------------------------------------------------

class TestTbdFixturesNoResultOnlyAfterWeekEnds:
    """
    - An unscheduled fixture's `match_status` is `upcoming` until its league week ends
      (`week_start` + 7 days, league time), then `past`
    - While it is `upcoming`, the Schedule row shows "Time TBD" and "vs"
    - After its week, with no games found, it shows "No result" as other past series do
    - A TBD fixture whose games are found (a series result) shows its score and moves out
      of the "Time TBD" group to its played day, as today
    """

    def test_fixture_to_series_unscheduled_upcoming_before_week_end(self, monkeypatch):
        """With `_league_now` monkeypatched to Mon 12.10. 10:00 (after the old midnight anchor and before `week_start` + 7d), an unscheduled week-5 fixture's `match_status` is `upcoming`."""
        for now in [(2026, 10, 12, 10, 0), (2026, 10, 16, 12, 0), (2026, 10, 18, 23, 59)]:
            _at(monkeypatch, *now)
            assert schedule._fixture_to_series(_tbd())["match_status"] == "upcoming", now

    def test_fixture_to_series_unscheduled_past_after_week_end(self, monkeypatch):
        """Failure path: with `_league_now` monkeypatched to Mon 19.10. 00:00 or later (`week_start` + 7d), the unscheduled fixture's `match_status` is `past`."""
        for now in [(2026, 10, 19, 0, 0), (2026, 10, 25, 12, 0)]:
            _at(monkeypatch, *now)
            assert schedule._fixture_to_series(_tbd())["match_status"] == "past", now

    def test_row_state_upcoming_for_tbd_series_shows_time_tbd_and_vs(self, monkeypatch):
        """Node harness: `rowState` returns `upcoming` for a TBD series (`scheduled: false`, `match_status: "upcoming"`, no `series_result`), and its rendered row shows "Time TBD" and "vs", not "No result"."""
        out = _run_schedule("""
  const ctx = {live: [], hide: true, revealed: new Set(), reportWeeks: new Set(), weekId: 5};
  out.r = rowState({scheduled: false, match_status: "upcoming", datetime_iso: "2026-10-15T12:00:00"}, ctx);
""")
        panels = _panels(_season16_schedule_data(monkeypatch))
        if out is None or panels is None:
            return
        assert out["r"] == "upcoming"
        wk5 = panels["panels"][1]
        for t1, t2 in _TBD_TEAMS:
            row = _row(wk5, t1, t2)
            assert "Time TBD" in row and ">vs<" in row and "No result" not in row, row

    def test_row_state_noresult_for_tbd_series_after_its_week(self, monkeypatch):
        """Failure path, Node harness: a TBD series with `match_status: "past"` and no `series_result` gets `rowState` `noresult` and its row reads "No result", as other past series do."""
        out = _run_schedule("""
  const ctx = {live: [], hide: true, revealed: new Set(), reportWeeks: new Set(), weekId: 5};
  out.r = rowState({scheduled: false, match_status: "past", datetime_iso: "2026-10-15T12:00:00"}, ctx);
""")
        panels = _panels(_season16_schedule_data(monkeypatch, now=(2026, 10, 19, 9, 0)))
        if out is None or panels is None:
            return
        assert out["r"] == "noresult"
        wk5 = panels["panels"][1]
        for t1, t2 in _TBD_TEAMS:
            row = _row(wk5, t1, t2)
            assert "No result" in row and ">vs<" not in row, row

    def test_tbd_series_with_result_moves_to_played_day(self, monkeypatch):
        """Node harness: a TBD series with a `series_result` shows its score and is grouped under the day its games were played, not under "Time TBD"."""
        data = _season16_schedule_data(monkeypatch, now=(2026, 10, 19, 9, 0))
        wk5 = next(w for w in data["weeks"] if w["label"] == "Week 5")
        s = next(x for x in wk5["div2"] if x["team1"] == "PV-1")
        s["series_result"] = {"team1_wins": 2, "team2_wins": 1, "game_count": 3,
                              "start_time": _ts(2026, 10, 14, 19, 5), "match_ids": [7001, 7002, 7003],
                              "games": []}
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(1);
  out.wk5 = snap().content;
""", data=data, store={"kc_schedule_hide": "0"})
        if out is None:
            return
        panel = out["wk5"]
        assert "PV-1" not in _tbd_group(panel)
        played = panel.index("Wed 14.10.2026")
        assert played < panel.index("PV-1") < panel.index("Time TBD")
        row = _row(panel, "PV-1", "Supercell")
        assert "Time TBD" not in row and "No result" not in row


# ---------------------------------------------------------------------------
# Story 3: Team Names Match Despite Punctuation and Old Teams
# ---------------------------------------------------------------------------

def _seed_reaktor_innofactor(db):
    db.add(Team(id=1, name="Reaktor"))
    db.add(Team(id=2, name="Innofactor"))
    db.add(Team(id=3, name="InnofactorNordcloud"))
    # Wed 7.10. 20:30 and 21:20 Helsinki: Reaktor wins both, once as radiant, once as dire.
    db.add(Match(match_id=8801, radiant_team_id=1, dire_team_id=3, radiant_win=True,
                 start_time=_ts(2026, 10, 7, 20, 30), duration=1800))
    db.add(Match(match_id=8802, radiant_team_id=3, dire_team_id=1, radiant_win=False,
                 start_time=_ts(2026, 10, 7, 21, 20), duration=2000))
    db.commit()


class TestTeamNamesMatchDespitePunctuationAndOldTeams:
    """
    - `norm_team_name` compares names case-insensitively, ignores parentheticals as
      today, and ignores every character that isn't a letter or digit:
      "Innofactor/NordCloud", "InnofactorNordcloud" and "innofactor nordcloud" are the
      same name
    - `find_team_id` returns the exact normalised match when there is one
    - The substring fallback is used only when exactly one team matches. When several
      match (for example "Innofactor" and "InnofactorNordcloud"), it returns the longest
      matching name if that one is unambiguous; otherwise it returns no team and logs a
      warning that names the fixture's team text
    - With the season-16 data, Reaktor-Innofactor/NordCloud (Wed 7.10.) resolves to the
      current team, shows Reaktor 2-0, and the separate "InnofactorNordcloud" result row
      is gone
    """

    def test_norm_team_name_ignores_case_punctuation_and_spaces(self):
        """`norm_team_name` gives the same key for "Innofactor/NordCloud", "InnofactorNordcloud" and "innofactor nordcloud"; letters such as "Ä" are kept (str.isalnum)."""
        keys = {schedule.norm_team_name(n) for n in
                ("Innofactor/NordCloud", "InnofactorNordcloud", "innofactor nordcloud", " INNOFACTOR-NordCloud ")}
        assert keys == {"innofactornordcloud"}
        assert schedule.norm_team_name("Äänekosken Ässät") == "äänekoskenässät"
        assert schedule.norm_team_name("PV-1") == "pv1"
        assert schedule.norm_team_name(None) == ""

    def test_norm_team_name_still_strips_parentheticals(self):
        """"Meta(no)core" still normalises to the same key as "Metacore" and `find_team_id` resolves it to Metacore."""
        assert schedule.norm_team_name("Meta(no)core") == schedule.norm_team_name("Metacore") == "metacore"
        lookup = {schedule.norm_team_name(n): i for i, n in enumerate(["Metacore", "Reaktor"], start=1)}
        assert schedule.find_team_id("Meta(no)core", lookup) == 1

    def test_find_team_id_prefers_exact_normalised_match(self):
        """With "Innofactor" and "InnofactorNordcloud" both in the lookup, "Innofactor/NordCloud" resolves to InnofactorNordcloud (exact normalised match), not the old "Innofactor"."""
        lookup = {schedule.norm_team_name("Innofactor"): 2, schedule.norm_team_name("InnofactorNordcloud"): 3}
        assert schedule.find_team_id("Innofactor/NordCloud", lookup) == 3
        assert schedule.find_team_id("Innofactor", lookup) == 2

    def test_find_team_id_substring_single_candidate_or_longest(self):
        """The substring fallback returns the only matching team, and when several match returns the longest matching key if no other key is as long."""
        lookup = {"innofactor": 2, "innofactornordcloud": 3, "visma": 4, "reaktor": 1}
        assert schedule.find_team_id("Visma Oy", lookup) == 4            # key inside the name
        assert schedule.find_team_id("Reak", lookup) == 1                # name inside the key
        assert schedule.find_team_id("Innofactor Nordcloud Ltd", lookup) == 3   # longest of two
        assert schedule.find_team_id("Nobody", lookup) is None
        assert schedule.find_team_id("", lookup) is None

    def test_find_team_id_ambiguous_returns_none_and_logs_once(self, caplog):
        """Failure path: when several keys match and the longest is tied, `find_team_id` returns None and logs exactly one warning naming the fixture's team text."""
        lookup = {"elisaoyj": 1, "elisaappelsiini": 2, "alpha": 3, "omega": 4}
        with caplog.at_level(logging.WARNING, logger="schedule"):
            assert schedule.find_team_id("Alpha & Omega", lookup) is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "'Alpha & Omega'" in warnings[0].getMessage()
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="schedule"):
            assert schedule.find_team_id("Elisa Oyj", lookup) == 1   # exact: no warning
        assert not caplog.records

    def test_resolve_series_result_finds_reaktor_innofactor_nordcloud_games(self, db, monkeypatch):
        """With teams Reaktor, Innofactor and InnofactorNordcloud and two Reaktor wins over InnofactorNordcloud on Wed 7.10., `resolve_series_result(db, "Reaktor", "Innofactor/NordCloud", ...)` returns a 2-0 Reaktor result with both match ids."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        _seed_reaktor_innofactor(db)
        lookup = schedule.build_team_lookup(db)
        r = schedule.resolve_series_result(db, "Reaktor", "Innofactor/NordCloud", lookup,
                                           scheduled_dt_iso="2026-10-07T20:30:00")
        assert r is not None
        assert (r["team1_wins"], r["team2_wins"], r["game_count"]) == (2, 0, 2)
        assert sorted(r["match_ids"]) == [8801, 8802]

    def test_get_schedule_no_separate_unscheduled_result_for_claimed_games(self, db, monkeypatch):
        """With the season-16 week 4-5 copy as feed, `get_schedule` attaches the Reaktor-InnofactorNordcloud games to the scheduled series and `extra_results` no longer lists them as an unscheduled result row."""
        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "https://feed.test/api/fixtures.json")
        monkeypatch.setattr(schedule, "fetch_fixtures_json", _season16_weeks_4_5_feed)
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        _seed_reaktor_innofactor(db)

        data = schedule.get_schedule(db)

        wk4 = next(w for w in data["weeks"] if w["label"] == "Week 4")
        s = next(x for x in wk4["div1"] if x["team1"] == "Reaktor")
        assert (s["team1_id"], s["team2_id"]) == (1, 3)
        assert (s["series_result"]["team1_wins"], s["series_result"]["team2_wins"]) == (2, 0)
        assert data["extra_results"] == []


# ---------------------------------------------------------------------------
# Story 4: League Week Shown When It Differs
# ---------------------------------------------------------------------------

class TestLeagueWeekShownWhenItDiffers:
    """
    - Each series from the fixtures feed carries its league week (`league_week`, the
      feed's `week`)
    - When a row's league week differs from the number in the fantasy week label it is
      shown under, the row shows a small "League week N" tag after the division badge.
      Example: Hoxhunt Fortum-Elisa Oyj, league week 4, played Mon 12.10. 21:00, shown
      in Week 5
    - No tag when they match, when the fantasy week has no number in its label, or when
      the source is the Google Sheet (no league week)
    - The tag text is set with `textContent` or `_escHtml`
    """

    def test_fixture_to_series_carries_league_week(self, db, monkeypatch):
        """Every series built from the feed (scheduled and unscheduled) has `league_week` equal to the fixture's `week`, and `get_schedule` passes it through."""
        weeks, _ = schedule.parse_fixtures_json(_season16_weeks_4_5_feed())
        for w in weeks:
            n = int(w["label"].split()[-1])
            for s in w["div1"] + w["div2"]:
                assert s["league_week"] == n
        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "https://feed.test/api/fixtures.json")
        monkeypatch.setattr(schedule, "fetch_fixtures_json", _season16_weeks_4_5_feed)
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        data = schedule.get_schedule_for_request(db, 0)
        got = {(s["team1"], s["league_week"]) for w in data["weeks"] for s in w["div1"] + w["div2"]}
        assert ("Hoxhunt Fortum", 4) in got and ("PV-1", 5) in got

    def test_series_row_shows_league_week_tag_on_mismatch(self, monkeypatch):
        """Node harness: Hoxhunt Fortum-Elisa Oyj (league week 4, Mon 12.10. 21:00) is shown in Week 5 with a `league-week-tag` span reading "League week 4" after the division badge."""
        panels = _panels(_season16_schedule_data(monkeypatch))
        if panels is None:
            return
        wk4, wk5 = panels["panels"]
        assert "Hoxhunt Fortum" not in wk4
        row = _row(wk5, "Hoxhunt Fortum", "Elisa Oyj")
        tag = '<span class="league-week-tag">League week 4</span>'
        assert tag in row
        assert row.index("badge-division") < row.index(tag) < row.index("Hoxhunt Fortum")

    def test_series_row_no_tag_when_match_unnumbered_or_sheet_source(self, monkeypatch):
        """Failure path, Node harness: no `league-week-tag` when `league_week` equals the shown week's number, when the fantasy week label has no number, or when the series has no `league_week` (Google Sheet source)."""
        same = _panels(_season16_schedule_data(monkeypatch))
        unnumbered = [dict(w) for w in _FANTASY_WEEKS]
        unnumbered[1]["label"] = "Playoffs"
        unnum = _panels(_season16_schedule_data(monkeypatch, fantasy_weeks=unnumbered))
        sheet = _season16_schedule_data(monkeypatch)
        for w in sheet["weeks"]:
            for s in w["div1"] + w["div2"]:
                del s["league_week"]
        sheet_panels = _panels(sheet)
        if same is None:
            return
        wk4, wk5 = same["panels"]
        assert "league-week-tag" not in wk4  # league week 4 shown in Week 4
        for t1, t2 in _TBD_TEAMS:
            assert "league-week-tag" not in _row(wk5, t1, t2)  # league week 5 in Week 5
        assert "league-week-tag" not in unnum["panels"][1]
        assert ">Playoffs</h3>" in unnum["panels"][1]
        assert "league-week-tag" not in "".join(sheet_panels["panels"])

    def test_series_row_tag_text_escaped(self):
        """Static check: `seriesRow` builds the tag only on a mismatch and sets its text through `_escHtml` or `textContent`; style.css defines `.league-week-tag`."""
        body = _load_schedule()
        tag = _nested(body, "leagueWeekTag")
        assert "String(s.league_week) === String(ctx.weekNum)" in tag
        assert "League week ${_escHtml(s.league_week)}" in tag
        assert "${leagueWeekTag(s, ctx)}" in _nested(body, "seriesRow")
        assert re.search(r"^\.league-week-tag\s*\{", _read(_STYLE_CSS_PATH), re.M)
