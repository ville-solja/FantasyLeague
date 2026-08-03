"""
Failing test stubs for plan-schedule-independent-results.

Pre-implementation stage: none of `_tally_wins()`, `_build_unscheduled_results()`, or the
`extra_results` top-level key on `get_schedule()`'s return value exist yet in
`backend/schedule.py`. Every stub below is a `pytest.fail("not yet implemented")`
placeholder — the developer replaces each body with the real assertion once the feature
lands. This plan directly extends `_build_games()` and `resolve_series_result()` from the
prior schedule-game-breakdown feature (see `test_issue_87_schedule_game_breakdown.py`),
reusing their DB fixture / monkeypatch conventions.

Covers three user stories from markdown/plans/plan-schedule-independent-results.md:

  Story: Show Past Results Without Requiring a Schedule-Sheet Row
    - `_build_unscheduled_results(db, claimed_match_ids, div1_team_ids, div2_team_ids)`
      derives a series from a completed match (both radiant_team_id/dire_team_id set)
      not already claimed by a resolved sheet series, with correct team1/team2 names
      (via the teams table) and a `games` array built via `_build_games()`
    - A match already present in `claimed_match_ids` is excluded — never shown twice
    - Two matches between the same team pair with a gap <= 6 hours cluster into one
      derived series with a combined team1_wins/team2_wins tally
    - Two matches between the same team pair with a gap > 6 hours (including a
      regular-season match vs. a months-later playoff rematch) produce two separate
      derived series rather than one incorrectly merged series
    - A derived series is labeled "div1"/"div2" when either of its teams was ever seen
      in that division's column across the season's sheet data
    - A derived series has `division: None` when neither team ever appeared in the sheet

  Story: Results Remain Available Without a Configured Schedule Sheet
    - `get_schedule()` returns populated `extra_results` (derived from the DB) with an
      empty `weeks` list when `SCHEDULE_SHEET_URL` is unset and there is no prior cache
    - When there is also nothing in the DB to derive, `get_schedule()` degrades to an
      empty `extra_results` list and the existing "Schedule unavailable" `error`,
      without raising

  Story: Upcoming Fixtures Remain Sheet-Sourced (regression guard)
    - `_tally_wins(rows, team1_id)` produces the same team1_wins/team2_wins tally as
      `resolve_series_result()`'s existing inline win/loss loop that it replaces
    - An existing sheet-resolved series' fields (team ids, series_result, games) are
      byte-for-byte unaffected by the addition of `extra_results`
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import schedule
from models import Match, PlayerMatchStats, Team


def _csv_for_series(team1, team2, dt):
    """Minimal single-series CSV matching schedule.parse_schedule()'s expected shape."""
    date_str = dt.strftime("%d.%m.%Y")
    time_str = dt.strftime("%H:%M")
    return (
        "Week 1,,,,,,,,,,,\n"
        "Upper,,,,,,,,,,,\n"
        "Team 1,Team 2,Date,Time,Stream,,Team 1,Team 2,Date,Time,Stream,\n"
        f"{team1},{team2},{date_str},{time_str},,,,,,,,\n"
    )


# ---------------------------------------------------------------------------
# Story: Show Past Results Without Requiring a Schedule-Sheet Row
# ---------------------------------------------------------------------------

class TestShowPastResultsWithoutRequiringAScheduleSheetRow:

    def test_build_unscheduled_results_includes_match_with_no_sheet_row(self, db, monkeypatch):
        """A completed match between two teams with no sheet row at all appears in
        _build_unscheduled_results()'s output with correct team1/team2 names (resolved
        via the teams table) and a games array built via _build_games()."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(match_id=9101, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=1_700_000_000))
        db.commit()

        results = schedule._build_unscheduled_results(db, set(), set(), set())

        assert len(results) == 1
        series = results[0]
        assert series["team1"] == "TeamA"
        assert series["team1_id"] == 1
        assert series["team2"] == "TeamB"
        assert series["team2_id"] == 2
        assert series["match_status"] == "past"
        assert series["series_result"]["match_ids"] == [9101]
        assert series["series_result"]["games"] == schedule._build_games(db, [9101], 1, 2)

    def test_build_unscheduled_results_excludes_matches_claimed_by_sheet_series(self, db, monkeypatch):
        """A completed match whose match_id is already present in claimed_match_ids
        (because a sheet-resolved series claimed it) is excluded from
        _build_unscheduled_results()'s output — a match is never shown twice."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Team(id=3, name="TeamC"))
        db.add(Match(match_id=9201, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=1_700_000_000))
        db.add(Match(match_id=9202, radiant_team_id=1, dire_team_id=3, radiant_win=False,
                      start_time=1_700_100_000))
        db.commit()

        results = schedule._build_unscheduled_results(db, {9201}, set(), set())

        match_ids_seen = {mid for r in results for mid in r["series_result"]["match_ids"]}
        assert 9201 not in match_ids_seen
        assert 9202 in match_ids_seen
        assert len(results) == 1

    def test_build_unscheduled_results_merges_matches_within_six_hour_gap(self, db, monkeypatch):
        """Two unclaimed matches between the same team pair with a gap of <= 6 hours
        between them cluster into one derived series with a combined
        team1_wins/team2_wins tally reflecting both matches."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        base = 1_700_000_000
        db.add(Match(match_id=9301, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=base))
        db.add(Match(match_id=9302, radiant_team_id=2, dire_team_id=1, radiant_win=False,
                      start_time=base + 3600))
        db.commit()

        results = schedule._build_unscheduled_results(db, set(), set(), set())

        assert len(results) == 1
        r = results[0]["series_result"]
        assert r["match_ids"] == [9301, 9302]
        assert r["game_count"] == 2
        assert r["team1_wins"] == 2
        assert r["team2_wins"] == 0

    def test_build_unscheduled_results_keeps_matches_beyond_six_hour_gap_as_separate_series(self, db, monkeypatch):
        """Two unclaimed matches between the same team pair with a gap of more than 6
        hours (e.g. a regular-season match and a playoff rematch months later) produce
        two separate derived series rather than one incorrectly merged series."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        base = 1_700_000_000
        db.add(Match(match_id=9401, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=base))
        db.add(Match(match_id=9402, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=base + 60 * 24 * 3600))  # ~60 days later
        db.commit()

        results = schedule._build_unscheduled_results(db, set(), set(), set())

        assert len(results) == 2
        match_id_lists = sorted(r["series_result"]["match_ids"] for r in results)
        assert match_id_lists == [[9401], [9402]]

    def test_build_unscheduled_results_infers_div1_badge_from_sheet_division_columns(self, db, monkeypatch):
        """A derived series is labeled division="div1" when either of its two teams
        was ever seen in a div1 column anywhere in the season's sheet data, even though
        the derived series itself has no sheet row."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(match_id=9501, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=1_700_000_000))
        db.commit()

        results = schedule._build_unscheduled_results(db, set(), {1}, set())

        assert len(results) == 1
        assert results[0]["division"] == "div1"

    def test_build_unscheduled_results_division_none_when_team_never_seen_in_sheet(self, db, monkeypatch):
        """A derived series involving a team that never appears in the sheet at all
        (fully sheet-independent league, or a foreign playoff opponent) has
        division=None rather than a guessed division badge."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(match_id=9601, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=1_700_000_000))
        db.commit()

        results = schedule._build_unscheduled_results(db, set(), set(), set())

        assert len(results) == 1
        assert results[0]["division"] is None


# ---------------------------------------------------------------------------
# Story: Results Remain Available Without a Configured Schedule Sheet
# ---------------------------------------------------------------------------

class TestResultsRemainAvailableWithoutAConfiguredScheduleSheet:

    def test_get_schedule_populates_extra_results_when_schedule_sheet_url_unset(self, db, monkeypatch):
        """get_schedule() returns an empty weeks list but a fully-populated
        extra_results list derived from the DB when SCHEDULE_SHEET_URL is unset (or
        fetch_csv_text() returns None) and there is no prior cache."""
        monkeypatch.setattr(schedule, "fetch_csv_text", lambda: None)
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        schedule.bust_cache()
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(match_id=9701, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=1_700_000_000))
        db.commit()

        data = schedule.get_schedule(db)

        assert data["weeks"] == []
        assert data["error"] == "Schedule unavailable"
        assert len(data["extra_results"]) == 1
        assert data["extra_results"][0]["series_result"]["match_ids"] == [9701]

    def test_get_schedule_extra_results_empty_and_error_present_when_no_sheet_and_no_matches(self, db, monkeypatch):
        """When SCHEDULE_SHEET_URL is unset with no prior cache and the DB has no
        qualifying completed matches either, get_schedule() degrades to an empty
        extra_results list alongside the existing "Schedule unavailable" error, without
        raising — Results has nothing to show, same as Upcoming."""
        monkeypatch.setattr(schedule, "fetch_csv_text", lambda: None)
        schedule.bust_cache()

        data = schedule.get_schedule(db)

        assert data["weeks"] == []
        assert data["extra_results"] == []
        assert data["error"] == "Schedule unavailable"


# ---------------------------------------------------------------------------
# Story: Upcoming Fixtures Remain Sheet-Sourced (regression guard)
# ---------------------------------------------------------------------------

class TestUpcomingFixturesRemainSheetSourced:

    def test_tally_wins_matches_existing_resolve_series_result_tally_logic(self):
        """_tally_wins(rows, team1_id) produces the same (team1_wins, team2_wins) tally
        as resolve_series_result()'s existing inline win/loss loop that it replaces, for
        an equivalent set of (radiant_team_id, radiant_win) rows."""
        rows = [(1, True), (2, False), (1, False), (2, True), (1, None)]
        team1_id = 1

        result = schedule._tally_wins(rows, team1_id)

        # Reference implementation: the original inline loop resolve_series_result()
        # used before it was extracted into _tally_wins().
        team1_wins = team2_wins = 0
        for radiant_id, radiant_win in rows:
            if radiant_win is None:
                continue
            if radiant_id == team1_id:
                team1_wins += 1 if radiant_win else 0
                team2_wins += 0 if radiant_win else 1
            else:
                team2_wins += 1 if radiant_win else 0
                team1_wins += 0 if radiant_win else 1

        assert result == (team1_wins, team2_wins)
        assert result == (2, 2)

    def test_sheet_resolved_series_fields_unaffected_by_extra_results_addition(self, db, monkeypatch):
        """An existing sheet-resolved series' fields (team1_id, team2_id,
        series_result including its games array) are byte-for-byte unchanged by the
        addition of the extra_results key — Upcoming/Results sheet-anchored behavior is
        a pure addition, not a modification."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Team(id=3, name="TeamC"))
        past_dt = datetime.now() - timedelta(days=1)
        db.add(Match(match_id=9801, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=int(past_dt.timestamp()), duration=1800))
        # Unclaimed match between an unrelated pair — should surface only via
        # extra_results, and must not perturb the sheet-resolved series below.
        db.add(Match(match_id=9802, radiant_team_id=1, dire_team_id=3, radiant_win=False,
                      start_time=int(past_dt.timestamp()) - 500_000))
        db.commit()

        csv_text = _csv_for_series("TeamA", "TeamB", past_dt)
        monkeypatch.setattr(schedule, "fetch_csv_text", lambda: csv_text)
        schedule.bust_cache()

        data = schedule.get_schedule(db)

        series = data["weeks"][0]["div1"][0]
        assert series["team1_id"] == 1
        assert series["team2_id"] == 2
        assert series["series_result"]["team1_wins"] == 1
        assert series["series_result"]["team2_wins"] == 0
        assert series["series_result"]["match_ids"] == [9801]
        assert series["series_result"]["games"] == schedule._build_games(db, [9801], 1, 2)

        assert "extra_results" in data
        extra_match_ids = {mid for r in data["extra_results"] for mid in r["series_result"]["match_ids"]}
        assert 9801 not in extra_match_ids  # claimed by the sheet series, not duplicated
        assert 9802 in extra_match_ids
