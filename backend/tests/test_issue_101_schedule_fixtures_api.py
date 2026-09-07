"""
Failing test stubs for plan-issue-101-schedule-fixtures-api.md (resolves GitHub issue #101).

Pre-implementation stage: none of `SCHEDULE_FIXTURES_URL`, `fetch_fixtures_json()`,
`parse_fixtures_json()`, `_fixture_to_series()`, or `_parse_iso_date()` exist yet in
`backend/schedule.py`, the JSON-source branch of `get_schedule()` is unwritten, and
`schedule_debug` in `backend/routers/admin_ingest.py` still only knows the CSV sheet.
Every stub below is a `pytest.fail("not yet implemented")` placeholder — the developer
implementing the plan replaces each body with the real assertion.

The `schedule` module imports cleanly with no FastAPI dependency, so its functions are
exercised directly (matching test_schedule_independent_results.py); `routers.admin_ingest`
also imports cleanly here, so `schedule_debug` is called as a plain function. Frontend-only
acceptance criteria (the "Time TBD" render in frontend/app-players.js) are covered as
frontend file-content assertions, following the established test_issue_* pattern.

Covers four user stories from markdown/plans/plan-issue-101-schedule-fixtures-api.md:

  Story: Configure a JSON Schedule Source
  Story: Fixtures Map to the Same Week/Division Structure
  Story: Unscheduled Fixtures Still Appear
  Story: Diagnose the Active Schedule Source

STATUS: stubs only -- every test body is `pytest.fail("not yet implemented")`.

Run with: cd backend && python -m pytest tests/test_issue_101_schedule_fixtures_api.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import schedule  # noqa: F401  (module under test; helpers added by the plan)
from models import Match, Team  # noqa: F401  (registers tables on Base for the db fixture)

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_APP_PLAYERS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-players.js")
_ENV_EXAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env.example")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _sample_feed():
    """A minimal fixtures.json payload shaped like the Kanaliiga feed: an
    `upper` and a `lower` fixture in week 1, one `upper` fixture in week 2,
    every fixture currently unscheduled (starts_at null, empty date/time)."""
    return {
        "season": "2026",
        "count": 3,
        "fixtures": [
            {"week": 1, "division": "upper", "team1": "Alpha", "team2": "Bravo",
             "starts_at": None, "date": "", "time": "", "week_start": "2026-09-14",
             "scheduled": False, "stream": "https://twitch.tv/kanaliiga"},
            {"week": 1, "division": "lower", "team1": "Charlie", "team2": "Delta",
             "starts_at": None, "date": "", "time": "", "week_start": "2026-09-14",
             "scheduled": False, "stream": "Kanaliiga Studio"},
            {"week": 2, "division": "upper", "team1": "Echo", "team2": "Foxtrot",
             "starts_at": None, "date": "", "time": "", "week_start": "2026-09-21",
             "scheduled": False, "stream": ""},
        ],
    }


# ---------------------------------------------------------------------------
# Story: Configure a JSON Schedule Source
# ---------------------------------------------------------------------------

class TestConfigureAJsonScheduleSource:

    def test_get_schedule_sources_weeks_from_fixtures_json_when_url_set(self, db, monkeypatch):
        """When SCHEDULE_FIXTURES_URL is set, GET /schedule sources its weeks[] from
        that JSON feed (source == "fixtures_json") and does not fetch the CSV sheet,
        while keeping the same /schedule response shape (weeks[] with label/div1/div2)."""
        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "https://feed.test/api/fixtures.json")
        monkeypatch.setattr(schedule, "fetch_fixtures_json", lambda: _sample_feed())
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})

        def _boom():
            raise AssertionError("fetch_csv_text must not be called when SCHEDULE_FIXTURES_URL is set")
        monkeypatch.setattr(schedule, "fetch_csv_text", _boom)
        schedule.bust_cache()

        data = schedule.get_schedule(db)

        assert data["source"] == "fixtures_json"
        assert [w["label"] for w in data["weeks"]] == ["Week 1", "Week 2"]
        wk1 = data["weeks"][0]
        assert [(s["team1"], s["team2"]) for s in wk1["div1"]] == [("Alpha", "Bravo")]
        assert [(s["team1"], s["team2"]) for s in wk1["div2"]] == [("Charlie", "Delta")]
        assert [(s["team1"], s["team2"]) for s in data["weeks"][1]["div1"]] == [("Echo", "Foxtrot")]

    def test_get_schedule_falls_back_to_csv_sheet_when_fixtures_url_unset(self, db, monkeypatch):
        """When SCHEDULE_FIXTURES_URL is unset, behaviour is exactly as today — the CSV
        sheet path is used (source == "sheet_csv"), fetch_fixtures_json is never called,
        and .env.example documents SCHEDULE_FIXTURES_URL and its precedence."""
        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "")
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})

        def _boom():
            raise AssertionError("fetch_fixtures_json must not be called when SCHEDULE_FIXTURES_URL is unset")
        monkeypatch.setattr(schedule, "fetch_fixtures_json", _boom)
        monkeypatch.setattr(schedule, "fetch_csv_text", lambda: None)
        schedule.bust_cache()

        data = schedule.get_schedule(db)

        assert data["source"] == "sheet_csv"
        assert data["weeks"] == []
        assert data["error"] == "Schedule unavailable"

        env = _read(_ENV_EXAMPLE_PATH)
        assert "SCHEDULE_FIXTURES_URL" in env
        assert "Preferred over" in env
        assert env.index("SCHEDULE_FIXTURES_URL") < env.index("# SCHEDULE_SHEET_URL=")


# ---------------------------------------------------------------------------
# Story: Fixtures Map to the Same Week/Division Structure
# ---------------------------------------------------------------------------

class TestFixturesMapToTheSameWeekDivisionStructure:

    def test_parse_fixtures_json_maps_divisions_and_groups_by_week_ascending(self, db):
        """parse_fixtures_json() maps division upper->div1 and lower->div2, groups
        fixtures by their week integer into weeks labelled "Week {n}" ordered ascending,
        and carries team1/team2 plus stream (as stream_url for an http(s) URL, else
        stream_label) across into the same series dict the sheet path produces."""
        # week 2 fixture listed first in the feed to prove ascending ordering
        feed = _sample_feed()
        feed["fixtures"] = [feed["fixtures"][2], feed["fixtures"][0], feed["fixtures"][1]]

        weeks, dropped = schedule.parse_fixtures_json(feed)

        assert dropped == 0
        assert [w["label"] for w in weeks] == ["Week 1", "Week 2"]

        wk1 = weeks[0]
        assert len(wk1["div1"]) == 1 and len(wk1["div2"]) == 1
        upper = wk1["div1"][0]
        lower = wk1["div2"][0]
        assert (upper["team1"], upper["team2"]) == ("Alpha", "Bravo")
        assert upper["stream_url"] == "https://twitch.tv/kanaliiga"
        assert upper["stream_label"] is None
        assert (lower["team1"], lower["team2"]) == ("Charlie", "Delta")
        assert lower["stream_url"] is None
        assert lower["stream_label"] == "Kanaliiga Studio"

        # same series-dict shape as the sheet path (parse_match_row keys)
        sheet_keys = {"team1", "team2", "date", "time", "stream_label",
                      "stream_url", "datetime_iso", "match_status"}
        assert sheet_keys.issubset(upper.keys())

    def test_parse_fixtures_json_skips_fixture_with_missing_or_unknown_week_or_division(self, db):
        """A fixture with a missing/unrecognised week or division is skipped and counted
        in the returned dropped count, not allowed to crash the parse."""
        feed = {
            "fixtures": [
                {"week": 1, "division": "upper", "team1": "Alpha", "team2": "Bravo",
                 "starts_at": None, "week_start": "2026-09-14", "scheduled": False},
                {"week": None, "division": "upper", "team1": "X", "team2": "Y"},
                {"week": 2, "division": "middle", "team1": "P", "team2": "Q"},
                {"division": "lower", "team1": "M", "team2": "N"},
            ]
        }

        weeks, dropped = schedule.parse_fixtures_json(feed)

        assert dropped == 3
        assert [w["label"] for w in weeks] == ["Week 1"]
        assert (weeks[0]["div1"][0]["team1"], weeks[0]["div1"][0]["team2"]) == ("Alpha", "Bravo")


# ---------------------------------------------------------------------------
# Story: Unscheduled Fixtures Still Appear
# ---------------------------------------------------------------------------

class TestUnscheduledFixturesStillAppear:

    def test_fixture_to_series_uses_real_starts_at_and_marks_scheduled_true(self, db):
        """A fixture with a real starts_at (ISO datetime) uses that as its datetime_iso,
        converted to local time, and is marked scheduled: true; when both starts_at and
        date/time are present, starts_at wins."""
        from datetime import datetime

        f = {
            "week": 1, "division": "upper", "team1": "Alpha", "team2": "Bravo",
            "starts_at": "2026-09-14T15:00:00Z",
            "date": "14.9.2026", "time": "19:00",   # deliberately different from starts_at
            "week_start": "2026-09-14", "scheduled": True,
        }

        s = schedule._fixture_to_series(f)

        expected = (datetime.fromisoformat("2026-09-14T15:00:00+00:00")
                    .astimezone().replace(tzinfo=None).isoformat())
        assert s["datetime_iso"] == expected
        assert s["datetime_iso"] != "2026-09-14T19:00:00"  # date/time did not win
        assert s["scheduled"] is True

    def test_fixture_to_series_falls_back_to_week_start_midnight_when_unscheduled(self, db):
        """A fixture with starts_at: null and empty date/time is given an approximate
        datetime_iso of its week_start date at 00:00 (so it is not filtered out of the
        Upcoming list) and is marked scheduled: false in the /schedule response."""
        f = {
            "week": 1, "division": "upper", "team1": "Alpha", "team2": "Bravo",
            "starts_at": None, "date": "", "time": "",
            "week_start": "2026-09-14", "scheduled": False,
        }

        s = schedule._fixture_to_series(f)

        assert s["datetime_iso"] == "2026-09-14T00:00:00"
        assert s["scheduled"] is False

    def test_render_row_shows_time_tbd_for_unscheduled_series(self):
        """frontend/app-players.js renderRow shows "Time TBD" instead of a specific time
        when a series has scheduled === false, while still rendering team names, the
        division badge, and week grouping."""
        src = _read(_APP_PLAYERS_JS_PATH)

        assert "s.scheduled === false" in src
        assert "Time TBD" in src
        assert 'class="series-time tbd"' in src
        # team names, division badge and date grouping still rendered
        assert "series-team" in src
        assert "badge-division" in src
        assert "_groupByDate" in src


# ---------------------------------------------------------------------------
# Story: Diagnose the Active Schedule Source
# ---------------------------------------------------------------------------

class TestDiagnoseTheActiveScheduleSource:

    def test_schedule_debug_reports_fixtures_json_source_and_feed_summary(self, monkeypatch):
        """GET /schedule/debug with the JSON feed configured reports source
        "fixtures_json", the configured URL (prefix only), the HTTP status, the feed's
        season and count, the number of weeks parsed, and the number of fixtures dropped
        for a missing/unknown week or division."""
        from routers.admin_ingest import schedule_debug

        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "https://feed.test/api/fixtures.json")

        feed = _sample_feed()
        feed["fixtures"].append({"week": None, "division": "upper", "team1": "No", "team2": "Week"})

        class _Resp:
            status_code = 200
            headers = {"content-type": "application/json"}

            def json(self):
                return feed

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())

        result = schedule_debug()

        assert result["source"] == "fixtures_json"
        assert result["url_prefix"] == "https://feed.test/api/fixtures.json"
        assert result["status_code"] == 200
        assert result["season"] == "2026"
        assert result["count"] == 3
        assert result["weeks_parsed"] == 2
        assert result["fixtures_dropped"] == 1

    def test_schedule_debug_reports_error_string_for_malformed_feed(self, monkeypatch):
        """A fetch failure or a non-JSON / schema-mismatched response is reported by
        /schedule/debug as a clear error string, not raised as an unhandled exception."""
        from routers.admin_ingest import schedule_debug

        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "https://feed.test/api/fixtures.json")

        # 1. fetch failure -> error string is the exception class name, no raise
        def _raise(*a, **k):
            raise ConnectionError("boom")
        monkeypatch.setattr("requests.get", _raise)
        result = schedule_debug()
        assert result["source"] == "fixtures_json"
        assert result["error"] == "ConnectionError"

        # 2. schema-mismatched response -> clear error string, no raise
        class _Resp:
            status_code = 200
            headers = {}

            def json(self):
                return {"not": "a fixtures payload"}

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        result = schedule_debug()
        assert result["error"] == "response is not a fixtures.json payload"
