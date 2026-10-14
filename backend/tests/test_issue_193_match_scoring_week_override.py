"""
Tests for plan-issue-193-match-scoring-week-override.md (resolves GitHub issue #193).

Written as failing stubs before the change; they now check the implementation:
  - `PUT /matches/{match_id}/week` (`routers/admin_ingest.py::set_match_week`, body
    `MatchWeekBody(week_id: int | None, apply_to_series: bool = True)`) sets
    `week_override_id` on every game of the series (same two teams, start within 6 h),
    audits `admin_set_match_week` per changed match, re-runs bench substitutions for every
    affected week whose substitutions already ran (`weeks.rerun_substitutions_for`,
    audited `admin_substitutions_rerun` with `reason=week_override`) and busts the
    schedule and Twitch panel caches.
  - `schedule.out_of_week_series(db)` flags feed series counted outside the fantasy week
    containing their league week's anchor (`schedule.league_week_anchor`, the #194
    Thursday-noon rule). `GET /admin/matches/out-of-week` returns it, and
    `POST /admin/sync-match-weeks[?dry_run=true]` is rebuilt on it.
  - `GET /admin/matches` (`routers/admin_matches.py::list_matches`) adds
    `scoring_week_id`, `scoring_week_label`, `scoring_week_source` (and the time-based
    `time_week_id` / `time_week_label` the picker's "By time (Week N)" option shows).

  Story 1: Admin Sets a Series' Scoring Week               (TestAdminSetsSeriesScoringWeek)
  Story 2: Changing a Week Fixes Scoring and Bench Together (TestWeekChangeFixesScoringAndBench)
  Story 3: Out-of-Week Series Are Flagged                   (TestOutOfWeekSeriesFlagged)

Approach notes:

- `db` fixture from conftest (in-memory SQLite). Import `models` at module level so
  every table exists before the fixture runs (lessons-learned, testing).
- Seeding follows test_issue_129_automatic_bench_substitution.py: weights, one user,
  players, teams, cards (active + bench), weeks, matches, stats, then
  `card_points.rebuild_all(db)`; weeks are snapshotted with `weeks._snapshot_week` and
  marked "substitutions already run" with `weeks.run_substitutions`.
- Admin routes are called as plain functions with `db=db, admin=_ADMIN`. Route guards
  are checked through the route's `dependant.dependencies`.
- Feed: the season-16 copy from test_issue_194 (`_season16_weeks_4_5_feed`), served to
  the real `schedule.get_schedule` by monkeypatching `fetch_fixtures_json`.
- Hoxhunt Fortum case: Week 4 ends Mon 12.10.2026 03:00 UTC; Week 5 starts then. The
  Hoxhunt Fortum-Elisa Oyj series (league week 4) is played Mon 12.10. 21:00 league time.
- Frontend criteria are static text checks of `frontend/app-admin-matches.js`.

STATUS: implemented.

Run with: cd backend && python -m pytest tests/test_issue_193_match_scoring_week_override.py -v
"""

import os
import re
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

import models  # noqa: F401  (register every table before the db fixture runs)
import card_points
import schedule
import weeks
from auth import hash_password
from deps import require_admin, require_recent_reauth
from models import (
    AuditLog, Card, Match, Player, PlayerMatchStats, Team, User, Week, WeeklyRosterEntry, Weight,
)
from routers import admin_ingest, admin_matches
from routers.admin_ingest import MatchWeekBody
from routers.leaderboard import weekly_leaderboard
from scoring import fantasy_score
from tests.test_issue_194_schedule_fixture_week_alignment import _season16_weeks_4_5_feed

_ADMIN = {"user_id": 1, "username": "admin"}

_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "app-admin-matches.js")
_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "index.html")

_WEIGHTS = {
    "kills": 0.3, "gold_per_min": 0.002,
    "death_pool": 3.0, "death_deduction": 0.3, "mvp_bonus_pct": 10.0,
    "rarity_common": 0.0, "rarity_rare": 1.0, "rarity_epic": 2.0, "rarity_legendary": 3.0,
    "modifier_count_common": 0.0, "modifier_count_rare": 1.0, "modifier_count_epic": 2.0,
    "modifier_count_legendary": 3.0, "modifier_bonus_pct": 10.0, "team_booster_cost": 3.0,
}


def _utc(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp())


# Fantasy weeks start Monday 03:00 UTC (issue #111).
W4_START, W5_START, W6_START, W7_START = (
    _utc(2026, 10, 5, 3), _utc(2026, 10, 12, 3), _utc(2026, 10, 19, 3), _utc(2026, 10, 26, 3))

HOX, ELI, VIS, FUT = 1, 2, 3, 4          # team ids
H1, E1, V1, F1 = 101, 102, 103, 104      # players (one per team)
_TEAM_OF = {H1: HOX, E1: ELI, V1: VIS, F1: FUT}

# Hoxhunt Fortum-Elisa Oyj, Mon 12.10. 21:00 and 21:50 league time (18:00 / 18:50 UTC).
HOX_G1, HOX_G2 = 10, 11
HOX_T1, HOX_T2 = _utc(2026, 10, 12, 18), _utc(2026, 10, 12, 18, 50)
# Visma-Futurice, Mon 5.10. 20:30 league time: inside Week 4.
VIS_G1, VIS_T1 = 20, _utc(2026, 10, 5, 17, 30)
# A Hoxhunt Fortum-Elisa Oyj rematch three days later (only seeded on request).
REMATCH, REMATCH_T = 12, _utc(2026, 10, 15, 18)


def _add_match(db, match_id, start, radiant, dire, players):
    db.add(Match(match_id=match_id, radiant_team_id=radiant, dire_team_id=dire, start_time=start,
                 radiant_win=True, league_id=1))
    for pid, (kills, deaths, gpm) in players.items():
        stats = {"kills": kills, "deaths": deaths, "gold_per_min": gpm}
        db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=_TEAM_OF[pid],
                                fantasy_points=round(fantasy_score(stats, _WEIGHTS), 4),
                                is_mvp=False, **stats))


def _seed(db, rematch=False, run_weeks=(4, 5), labels=None):
    """alice (user 2): active H1 (slot 0), V1 (slot 1); bench F1 (order 0), E1 (order 1).
    Weeks 4, 5, 6 locked and snapshotted; substitutions already run for `run_weeks`.
    Before any override: Week 4 subs out H1 (no week-4 game by time) for F1; Week 5 subs
    out V1 for E1."""
    labels = labels or {4: "Week 4", 5: "Week 5", 6: "Week 6"}
    for key, value in _WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    db.add(User(id=1, username="admin", email="admin@test", password_hash=hash_password("x" * 12),
                is_admin=True, tokens=0))
    db.add(User(id=2, username="alice", email="a@test", password_hash=hash_password("x" * 12),
                tokens=5))
    for tid, name in ((HOX, "Hoxhunt Fortum"), (ELI, "Elisa Oyj"), (VIS, "Visma"), (FUT, "Futurice")):
        db.add(Team(id=tid, name=name))
    for pid in (H1, E1, V1, F1):
        db.add(Player(id=pid, name=f"P{pid}", is_active=True))
    for cid, pid, active, slot in ((1, H1, True, 0), (2, V1, True, 1), (3, F1, False, 0), (4, E1, False, 1)):
        db.add(Card(id=cid, player_id=pid, owner_id=2, card_type="common", is_active=active,
                    slot_index=slot))
    db.add(Week(id=4, label=labels[4], start_time=W4_START, end_time=W5_START - 1, is_locked=False))
    db.add(Week(id=5, label=labels[5], start_time=W5_START, end_time=W6_START - 1, is_locked=False))
    db.add(Week(id=6, label=labels[6], start_time=W6_START, end_time=W7_START - 1, is_locked=False))
    _add_match(db, HOX_G1, HOX_T1, HOX, ELI, {H1: (12, 1, 600), E1: (3, 5, 400)})
    _add_match(db, HOX_G2, HOX_T2, ELI, HOX, {H1: (10, 2, 550), E1: (4, 6, 380)})
    _add_match(db, VIS_G1, VIS_T1, VIS, FUT, {V1: (2, 4, 350), F1: (5, 3, 420)})
    if rematch:
        _add_match(db, REMATCH, REMATCH_T, HOX, ELI, {H1: (1, 1, 300), E1: (1, 1, 300)})
    db.commit()
    card_points.rebuild_all(db)
    for wid in (4, 5, 6):
        week = db.get(Week, wid)
        weeks._snapshot_week(db, week)
        week.is_locked = True
    db.commit()
    with patch("clock.time.time", return_value=W7_START + 86400):
        for wid in run_weeks:
            weeks.run_substitutions(db, db.get(Week, wid))
    db.commit()


def _flags(db, week_id):
    """{card_id: (subbed_in, subbed_out)} for alice in the week."""
    return {e.card_id: (bool(e.subbed_in), bool(e.subbed_out))
            for e in db.query(WeeklyRosterEntry).filter_by(week_id=week_id, user_id=2).all()}


def _set_week(db, match_id, week_id, apply_to_series=True):
    return admin_ingest.set_match_week(
        match_id, MatchWeekBody(week_id=week_id, apply_to_series=apply_to_series), db=db, admin=_ADMIN)


def _week_points(db, week_id):
    return {r["id"]: r["week_points"] for r in weekly_leaderboard(week_id=week_id, db=db)}.get(2, 0)


def _audits(db, action):
    return db.query(AuditLog).filter_by(action=action).all()


def _route(router, path, method):
    for route in router.routes:
        if getattr(route, "path", None) == path and method in route.methods:
            return route
    raise AssertionError(f"{method} {path} not registered")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _fn(src, name):
    """Source of a top-level JS function (up to the next top-level declaration)."""
    start = src.index(f"function {name}(")
    nxt = re.search(r"\n(?:async function|function|const|let|// -{5})", src[start + 1:])
    return src[start:start + 1 + nxt.start()] if nxt else src[start:]


@pytest.fixture(autouse=True)
def _schedule_feed(monkeypatch):
    """Serve the season-16 copy of the feed to the real get_schedule, with no network."""
    monkeypatch.setattr(schedule, "SCHEDULE_SHEET_URL", "")
    monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "https://fixtures.test/fixtures.json")
    monkeypatch.setattr(schedule, "fetch_fixtures_json", _season16_weeks_4_5_feed)
    monkeypatch.setattr(schedule, "_hero_icon_cache", {})
    schedule.bust_cache()
    yield
    schedule.bust_cache()


def _schedule_with(monkeypatch, series_list):
    """Replace get_schedule with one week holding the given series."""
    data = {"weeks": [{"label": "Week X", "div1": series_list, "div2": []}], "extra_results": []}
    monkeypatch.setattr(schedule, "get_schedule", lambda db: data)


def _hox_flag(db):
    return [s for s in schedule.out_of_week_series(db) if s["team1"] == "Hoxhunt Fortum"]


# ---------------------------------------------------------------------------
# Story 1: Admin Sets a Series' Scoring Week
# ---------------------------------------------------------------------------

class TestAdminSetsSeriesScoringWeek:
    """As an admin, I want to see and change which fantasy week a series counts for in
    Admin > Matches, so that a series played outside its week scores in the right week."""

    # -- weeks.scoring_week_for --------------------------------------------

    def test_scoring_week_for_by_time(self, db):
        """`scoring_week_for(db, match)` returns (week, "time") for the week whose window contains start_time."""
        _seed(db)
        week, source = weeks.scoring_week_for(db, db.get(Match, HOX_G1))
        assert (week.id, source) == (5, "time")
        week, source = weeks.scoring_week_for(db, db.get(Match, VIS_G1))
        assert (week.id, source) == (4, "time")

    def test_scoring_week_for_by_override(self, db):
        """`scoring_week_for(db, match)` returns (override week, "override") when week_override_id is set, even if start_time is in another week."""
        _seed(db)
        m = db.get(Match, HOX_G1)
        m.week_override_id = 4
        db.commit()
        week, source = weeks.scoring_week_for(db, m)
        assert (week.id, source) == (4, "override")
        # Same answer from a preloaded week list (the list endpoint's path).
        week, source = weeks.scoring_week_for(db, m, db.query(Week).all())
        assert (week.id, source) == (4, "override")

    def test_scoring_week_for_outside_every_week(self, db):
        """`scoring_week_for(db, match)` returns (None, None) when no week contains start_time and no override is set."""
        _seed(db)
        db.add(Match(match_id=99, radiant_team_id=HOX, dire_team_id=VIS, start_time=W7_START + 86400))
        db.commit()
        assert weeks.scoring_week_for(db, db.get(Match, 99)) == (None, None)

    # -- GET /admin/matches --------------------------------------------------

    def test_list_matches_includes_scoring_week_fields(self, db):
        """"`GET /admin/matches` adds, per match: `scoring_week_id` and `scoring_week_label`: the override if set, else the fantasy week whose window contains `start_time`; `scoring_week_source`: `override` or `time`." """
        _seed(db)
        db.get(Match, HOX_G1).week_override_id = 4
        db.commit()
        rows = {r["match_id"]: r for r in admin_matches.list_matches(db=db, _=_ADMIN)}
        assert (rows[HOX_G1]["scoring_week_id"], rows[HOX_G1]["scoring_week_label"],
                rows[HOX_G1]["scoring_week_source"]) == (4, "Week 4", "override")
        assert rows[HOX_G1]["time_week_label"] == "Week 5"
        assert (rows[HOX_G2]["scoring_week_id"], rows[HOX_G2]["scoring_week_label"],
                rows[HOX_G2]["scoring_week_source"]) == (5, "Week 5", "time")
        assert rows[VIS_G1]["scoring_week_label"] == "Week 4"

    def test_list_matches_scoring_week_null_outside_every_week(self, db):
        """"... else null": a match outside every week has scoring_week_id and scoring_week_label null."""
        _seed(db)
        db.add(Match(match_id=99, radiant_team_id=HOX, dire_team_id=VIS, start_time=W7_START + 86400))
        db.commit()
        row = {r["match_id"]: r for r in admin_matches.list_matches(db=db, _=_ADMIN)}[99]
        assert row["scoring_week_id"] is None
        assert row["scoring_week_label"] is None
        assert row["scoring_week_source"] is None

    # -- PUT /matches/{match_id}/week ---------------------------------------

    def test_set_match_week_applies_to_both_games_of_series(self, db):
        """"apply to series: choosing a week applies to every game of the same series" (same two teams, start times within 6 hours); response lists both changed match ids."""
        _seed(db)
        res = _set_week(db, HOX_G2, 4)
        assert sorted(res["changed_match_ids"]) == [HOX_G1, HOX_G2]
        assert db.get(Match, HOX_G1).week_override_id == 4
        assert db.get(Match, HOX_G2).week_override_id == 4
        assert db.get(Match, VIS_G1).week_override_id is None

    def test_set_match_week_does_not_change_rematch_days_later(self, db):
        """A rematch of the same two teams days later (more than 6 hours apart) is not part of the series and keeps its week."""
        _seed(db, rematch=True)
        res = _set_week(db, HOX_G1, 4)
        assert sorted(res["changed_match_ids"]) == [HOX_G1, HOX_G2]
        assert db.get(Match, REMATCH).week_override_id is None

    def test_set_match_week_apply_to_series_false_changes_one_match(self, db):
        """"adds `apply_to_series: bool = true`": with apply_to_series=false only the chosen match changes."""
        _seed(db)
        assert MatchWeekBody().apply_to_series is True
        res = _set_week(db, HOX_G1, 4, apply_to_series=False)
        assert res["changed_match_ids"] == [HOX_G1]
        assert db.get(Match, HOX_G1).week_override_id == 4
        assert db.get(Match, HOX_G2).week_override_id is None

    def test_set_match_week_null_clears_override_back_to_time(self, db):
        """""By time (Week N)" clears the override": week_id null returns the series to time-based scoring (scoring_week_source "time")."""
        _seed(db)
        _set_week(db, HOX_G1, 4)
        res = _set_week(db, HOX_G1, None)
        assert sorted(res["changed_match_ids"]) == [HOX_G1, HOX_G2]
        rows = {r["match_id"]: r for r in admin_matches.list_matches(db=db, _=_ADMIN)}
        for mid in (HOX_G1, HOX_G2):
            assert db.get(Match, mid).week_override_id is None
            assert (rows[mid]["scoring_week_id"], rows[mid]["scoring_week_source"]) == (5, "time")

    def test_set_match_week_audits_each_changed_match(self, db):
        """"One `admin_set_match_week` audit entry per changed match, as today."""
        _seed(db)
        _set_week(db, HOX_G1, 4)
        details = sorted(a.detail for a in _audits(db, "admin_set_match_week"))
        assert details == [f"match_id={HOX_G1} old_override=None new_override=4",
                           f"match_id={HOX_G2} old_override=None new_override=4"]
        # Setting the same week again changes nothing and audits nothing.
        assert _set_week(db, HOX_G1, 4)["changed_match_ids"] == []
        assert len(_audits(db, "admin_set_match_week")) == 2

    def test_set_match_week_unknown_week_returns_404(self, db):
        """"refuses an unknown week with 404 as today", and changes no match."""
        _seed(db)
        with pytest.raises(HTTPException) as exc:
            _set_week(db, HOX_G1, 999)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Week not found"
        assert db.get(Match, HOX_G1).week_override_id is None
        assert db.get(Match, HOX_G2).week_override_id is None

    def test_set_match_week_unknown_match_returns_404(self, db):
        """An unknown match_id gives 404 Match not found and changes nothing."""
        _seed(db)
        with pytest.raises(HTTPException) as exc:
            _set_week(db, 424242, 4)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Match not found"
        assert not _audits(db, "admin_set_match_week")

    def test_set_match_week_route_requires_admin_without_reauth(self):
        """The route keeps Depends(require_admin) and, like PATCH /admin/matches/{id}/scoring, does not require recent re-auth."""
        calls = [d.call for d in _route(admin_ingest.router, "/matches/{match_id}/week", "PUT")
                 .dependant.dependencies]
        assert require_admin in calls
        assert require_recent_reauth not in calls

    # -- Frontend (static) ---------------------------------------------------

    def test_frontend_matches_table_has_week_column(self):
        """"The Matches table shows a "Week" column, for example "Week 4" or "Week 4 (set)"; "—" when no week contains the match."""
        html = _read(_HTML_PATH)
        head = re.search(r'<table id="admin-matches-table">\s*<thead><tr>(.*?)</tr></thead>', html).group(1)
        headers = re.findall(r"<th>([^<]*)</th>", head)
        assert "Week" in headers
        assert f'colspan="{len(headers)}"' in html[html.index('id="adminMatchesBody"') - 30:][:200]
        js = _read(_JS_PATH)
        assert f"colspan='{len(headers)}'" in js
        text_fn = _fn(js, "_scoringWeekText")
        assert "(set)" in text_fn and "'override'" in text_fn and "'—'" in text_fn
        assert "_buildWeekCell(m)" in _fn(js, "renderAdminMatches")

    def test_frontend_week_picker_options(self):
        """The row picker offers "By time (Week N)" plus every fantasy week label, and sends PUT /matches/{id}/week."""
        js = _read(_JS_PATH)
        cell = _fn(js, "_buildWeekCell")
        assert "By time (${m.time_week_label" in cell
        assert "_adminMatchesWeeks.forEach" in cell and "w.label" in cell
        assert "`${API}/admin/weeks`" in _fn(js, "loadAdminMatches")
        put = _fn(js, "setMatchWeek")
        assert "`${API}/matches/${matchId}/week`" in put
        assert "method: 'PUT'" in put
        assert "apply_to_series: true" in put

    def test_frontend_confirmation_names_game_count(self):
        """"The confirmation names the number of games ("Count 2 games for Week 4?")."""
        js = _read(_JS_PATH)
        cell = _fn(js, "_buildWeekCell")
        assert "confirm(`Count ${n} ${n === 1 ? 'game' : 'games'}" in cell
        assert "_seriesGameCount(m)" in cell
        count = _fn(js, "_seriesGameCount")
        assert "_SERIES_GAP_SECONDS" in count
        assert "const _SERIES_GAP_SECONDS = 6 * 3600;" in js

    def test_frontend_picker_no_raw_innerhtml_team_names(self):
        """The picker is built without raw innerHTML interpolation of team or week names (textContent or _escHtml)."""
        js = _read(_JS_PATH)
        for name in ("_buildWeekCell", "_scoringWeekText", "_seriesGameCount"):
            assert "innerHTML" not in _fn(js, name), name
        cell = _fn(js, "_buildWeekCell")
        assert "opt.textContent = w.label" in cell
        assert "label.textContent = _scoringWeekText(m)" in cell


# ---------------------------------------------------------------------------
# Story 2: Changing a Week Fixes Scoring and Bench Together
# ---------------------------------------------------------------------------

class TestWeekChangeFixesScoringAndBench:
    """As an admin, I want a week change to also fix the bench substitutions, so that a
    player who played isn't left replaced in the week their match now counts for."""

    def test_rerun_substitutions_for_only_runs_weeks_already_run(self, db):
        """`weeks.rerun_substitutions_for(db, week_ids, reason)` re-runs only weeks with substitutions_at set and returns [(week, count)]."""
        _seed(db, run_weeks=(4,))
        result = weeks.rerun_substitutions_for(db, [4, 5, None], "week_override")
        assert [(w.id, n) for w, n in result] == [(4, 1)]
        assert db.get(Week, 5).substitutions_at is None
        assert weeks.rerun_substitutions_for(db, [], "week_override") == []

    def test_set_match_week_reruns_new_week_substitutions(self, db):
        """"every affected week ... whose substitutions have already run gets `weeks.run_substitutions` again": moved players' entries in the new week are no longer subbed_out."""
        _seed(db)
        assert _flags(db, 4)[1] == (False, True)     # H1 subbed out
        assert _flags(db, 4)[3] == (True, False)     # F1 subbed in
        _set_week(db, HOX_G1, 4)
        flags = _flags(db, 4)
        assert flags[1] == (False, False)
        assert flags[3] == (False, False)
        assert not any(out for _, out in flags.values())

    def test_set_match_week_reruns_old_week_substitutions(self, db):
        """The match's old scoring week is re-run too: its players, who no longer played that week, are subbed out there."""
        _seed(db)
        assert _flags(db, 5)[1] == (False, False)    # H1 played in Week 5 by time
        assert _flags(db, 5)[4] == (True, False)     # E1 subbed in for V1
        _set_week(db, HOX_G1, 4)
        flags = _flags(db, 5)
        assert flags[1] == (False, True)             # H1 no longer played in Week 5
        assert flags[4] == (False, False)            # E1 no longer played either

    def test_set_match_week_response_lists_rerun_weeks_with_counts(self, db):
        """"The response lists those weeks with their new substitution counts."""
        _seed(db)
        res = _set_week(db, HOX_G1, 4)
        assert res["substitution_reruns"] == [
            {"week_id": 4, "week_label": "Week 4", "substitutions": 0},
            {"week_id": 5, "week_label": "Week 5", "substitutions": 0},
        ]
        assert res["week_override_id"] == 4
        assert res["match_id"] == HOX_G1

    def test_set_match_week_leaves_week_not_yet_run_alone(self, db):
        """"A week whose substitutions haven't run yet is left alone": substitutions_at stays null and no entries change."""
        _seed(db, run_weeks=(5,))
        before = _flags(db, 4)
        res = _set_week(db, HOX_G1, 4)
        assert [r["week_id"] for r in res["substitution_reruns"]] == [5]
        assert db.get(Week, 4).substitutions_at is None
        assert _flags(db, 4) == before

    def test_set_match_week_rerun_audits_with_week_override_reason(self, db):
        """"Each re-run writes an `admin_substitutions_rerun` audit entry with `reason=week_override`."""
        _seed(db)
        _set_week(db, HOX_G1, 4)
        rows = _audits(db, "admin_substitutions_rerun")
        assert len(rows) == 2
        assert all("reason=week_override" in a.detail for a in rows)
        assert all(a.actor_username == "admin" and a.actor_id == 1 for a in rows)
        assert sorted(re.search(r"id=(\d+)", a.detail).group(1) for a in rows) == ["4", "5"]

    def test_set_match_week_busts_response_caches(self, db, monkeypatch):
        """"any response cache the change affects is busted" (schedule.bust_cache and the panel cache are called)."""
        _seed(db)
        calls = []
        monkeypatch.setattr(admin_ingest, "bust_cache", lambda: calls.append("schedule"))
        monkeypatch.setattr(admin_ingest, "bust_panel_cache", lambda: calls.append("panel"))
        _set_week(db, HOX_G1, 4)
        assert sorted(calls) == ["panel", "schedule"]

    def test_weekly_leaderboard_moves_points_to_new_week(self, db):
        """A week leaderboard includes the moved points in the new week and not in the old one."""
        _seed(db, run_weeks=())
        w4_before, w5_before = _week_points(db, 4), _week_points(db, 5)
        assert w5_before > 0
        _set_week(db, HOX_G1, 4)
        # Week 5 had only the Hoxhunt Fortum games; Week 4 gains them.
        assert _week_points(db, 5) == 0
        assert _week_points(db, 4) > w4_before

    def test_hoxhunt_fortum_moved_to_week_4_removes_week_4_substitutions(self, db):
        """"moving its 12.10. games to Week 4 removes the Week 4 substitutions of its players, so their week-4 points count, and removes those points from Week 5."""
        _seed(db)
        w4_before = _week_points(db, 4)
        _set_week(db, HOX_G1, 4)
        assert _flags(db, 4)[1] == (False, False)
        assert _week_points(db, 4) > w4_before
        assert _week_points(db, 5) == 0
        # The schedule's out-of-week flag is gone too.
        assert _hox_flag(db) == []

    def test_set_match_week_unknown_week_reruns_nothing(self, db):
        """Failure path: a 404 for an unknown week leaves every week's substitutions and substitutions_at unchanged."""
        _seed(db)
        before = {wid: (db.get(Week, wid).substitutions_at, _flags(db, wid)) for wid in (4, 5, 6)}
        with pytest.raises(HTTPException):
            _set_week(db, HOX_G1, 999)
        after = {wid: (db.get(Week, wid).substitutions_at, _flags(db, wid)) for wid in (4, 5, 6)}
        assert after == before
        assert not _audits(db, "admin_substitutions_rerun")

    def test_frontend_shows_rerun_summary(self):
        """"the page shows them, for example "Week 4: substitutions re-run (3)"."""
        js = _read(_JS_PATH)
        summary = _fn(js, "_weekChangeSummary")
        assert "`${r.week_label}: substitutions re-run (${r.substitutions})`" in summary
        assert "substitution_reruns" in summary
        assert "setStatus('adminMatchesStatus', _weekChangeSummary(data))" in _fn(js, "setMatchWeek")


# ---------------------------------------------------------------------------
# Story 3: Out-of-Week Series Are Flagged
# ---------------------------------------------------------------------------

class TestOutOfWeekSeriesFlagged:
    """As an admin, I want series played outside their scheduled week to be pointed out,
    so that I don't have to spot them myself before substitutions run."""

    def test_out_of_week_series_flags_series_counted_in_other_week(self, db):
        """"it is out of week when any of its matches counts for a different week (by override or time)" than the week containing its league week's anchor."""
        _seed(db)
        # By time: the 12.10. games count for Week 5, their league week 4 maps to Week 4.
        assert len(_hox_flag(db)) == 1
        # By override: Visma-Futurice (league week 4, Week 4 by time) with one game
        # overridden to Week 6 is flagged.
        db.get(Match, VIS_G1).week_override_id = 6
        db.add(Match(match_id=21, radiant_team_id=VIS, dire_team_id=FUT, start_time=VIS_T1 + 3000))
        db.commit()
        schedule.bust_cache()
        vis = [s for s in schedule.out_of_week_series(db) if s["team1"] == "Visma"]
        assert len(vis) == 1
        assert (vis[0]["scheduled_week_id"], vis[0]["counted_week_id"]) == (4, 6)

    def test_out_of_week_series_not_flagged_when_in_scheduled_week(self, db):
        """A series whose matches all count for its scheduled fantasy week is not flagged."""
        _seed(db)
        teams = [s["team1"] for s in schedule.out_of_week_series(db)]
        assert "Visma" not in teams

    def test_out_of_week_series_not_flagged_without_fantasy_week_for_anchor(self, db, monkeypatch):
        """"a series whose league week has no fantasy week containing its anchor is not flagged."""
        _seed(db)
        _schedule_with(monkeypatch, [{
            "team1": "Hoxhunt Fortum", "team2": "Elisa Oyj", "league_week": 12,
            "league_week_start": "2026-11-30",   # no fantasy week that late
            "series_result": {"match_ids": [HOX_G1, HOX_G2]},
        }])
        assert schedule.out_of_week_series(db) == []

    def test_out_of_week_series_skips_series_without_result_or_league_week(self, db, monkeypatch):
        """Only series with `series_result.match_ids` and a `league_week` are considered."""
        _seed(db)
        base = {"team1": "Hoxhunt Fortum", "team2": "Elisa Oyj", "league_week_start": "2026-10-05"}
        _schedule_with(monkeypatch, [
            dict(base, league_week=None, series_result={"match_ids": [HOX_G1, HOX_G2]}),
            dict(base, league_week=4, series_result=None),
            dict(base, league_week=4, series_result={"match_ids": []}),
        ])
        assert schedule.out_of_week_series(db) == []
        # Control: the same series with both is flagged.
        _schedule_with(monkeypatch, [dict(base, league_week=4,
                                          series_result={"match_ids": [HOX_G1, HOX_G2]})])
        assert len(schedule.out_of_week_series(db)) == 1

    def test_out_of_week_series_hoxhunt_fortum_flagged_week_4_counted_week_5(self, db):
        """"With the season-16 feed, Hoxhunt Fortum–Elisa Oyj (league week 4, played Mon 12.10.) is flagged as scheduled Week 4, counted Week 5."""
        _seed(db)
        flagged = _hox_flag(db)
        assert len(flagged) == 1
        s = flagged[0]
        assert s["team2"] == "Elisa Oyj"
        assert s["league_week"] == 4
        assert (s["scheduled_week_id"], s["scheduled_week_label"]) == (4, "Week 4")
        assert (s["counted_week_id"], s["counted_week_label"]) == (5, "Week 5")
        assert sorted(s["match_ids"]) == [HOX_G1, HOX_G2]
        assert s["played_at"] == HOX_T1

    def test_out_of_week_series_not_flagged_after_count_for_scheduled_week(self, db):
        """""Count for Week N" applies the scheduled week to the series, with the substitution re-run"; the series is then no longer flagged."""
        _seed(db)
        s = _hox_flag(db)[0]
        res = _set_week(db, s["match_ids"][0], s["scheduled_week_id"])
        assert [r["week_id"] for r in res["substitution_reruns"]] == [4, 5]
        assert _hox_flag(db) == []

    def test_out_of_week_series_keep_override_clears_flag(self, db):
        """""Keep in Week M" sets an explicit override to the current week, which clears the flag."""
        _seed(db)
        s = _hox_flag(db)[0]
        res = _set_week(db, s["match_ids"][0], s["counted_week_id"])
        assert sorted(res["changed_match_ids"]) == [HOX_G1, HOX_G2]
        assert res["substitution_reruns"] == []      # still Week 5: nothing to re-run
        assert db.get(Match, HOX_G1).week_override_id == 5
        assert _hox_flag(db) == []

    def test_admin_matches_exposes_out_of_week_list(self, db):
        """Admin > Matches gets the flagged series (teams, played date, scheduled week, counted week) from the out-of-week endpoint or list field."""
        _seed(db)
        rows = admin_matches.list_out_of_week_series(db=db, _=_ADMIN)
        hox = [r for r in rows if r["team1"] == "Hoxhunt Fortum"]
        assert len(hox) == 1
        for key in ("team1", "team2", "played_at", "scheduled_week_id", "scheduled_week_label",
                    "counted_week_id", "counted_week_label", "match_ids"):
            assert key in hox[0]
        calls = [d.call for d in _route(admin_matches.router, "/admin/matches/out-of-week", "GET")
                 .dependant.dependencies]
        assert require_admin in calls

    def test_sync_match_weeks_dry_run_changes_nothing(self, db):
        """"`dry_run=true` returns the flagged series" and changes no override or substitution."""
        _seed(db)
        before = {wid: _flags(db, wid) for wid in (4, 5)}
        res = admin_ingest.sync_match_weeks(dry_run=True, db=db, admin=_ADMIN)
        assert res["dry_run"] is True
        assert [s["team1"] for s in res["series"]] == ["Hoxhunt Fortum"]
        assert res["changes"] == [] and res["substitution_reruns"] == []
        assert db.get(Match, HOX_G1).week_override_id is None
        assert {wid: _flags(db, wid) for wid in (4, 5)} == before
        assert not _audits(db, "admin_sync_match_weeks")

    def test_sync_match_weeks_applies_and_reruns(self, db):
        """"without it, it applies all of them and re-runs substitutions as above."""
        _seed(db)
        res = admin_ingest.sync_match_weeks(dry_run=False, db=db, admin=_ADMIN)
        assert sorted(c["match_id"] for c in res["changes"]) == [HOX_G1, HOX_G2]
        assert all(c["new_override"] == 4 and c["target_week"] == "Week 4" for c in res["changes"])
        assert [r["week_id"] for r in res["substitution_reruns"]] == [4, 5]
        assert db.get(Match, HOX_G1).week_override_id == 4
        assert _flags(db, 4)[1] == (False, False)
        assert len(_audits(db, "admin_sync_match_weeks")) == 1
        assert len(_audits(db, "admin_set_match_week")) == 2
        assert admin_ingest.sync_match_weeks(dry_run=True, db=db, admin=_ADMIN)["series"] == []

    def test_sync_match_weeks_does_not_pair_weeks_by_label(self, db):
        """Failure path: when feed and fantasy week labels differ, sync still uses the anchor rule and reports no label-mismatch errors."""
        _seed(db, labels={4: "Viikko 4", 5: "Viikko 5", 6: "Viikko 6"})
        res = admin_ingest.sync_match_weeks(dry_run=False, db=db, admin=_ADMIN)
        assert res["errors"] == []
        assert sorted(c["match_id"] for c in res["changes"]) == [HOX_G1, HOX_G2]
        assert res["changes"][0]["target_week"] == "Viikko 4"
        assert db.get(Match, HOX_G2).week_override_id == 4

    def test_sync_match_weeks_route_requires_admin(self):
        """POST /admin/sync-match-weeks keeps Depends(require_admin)."""
        calls = [d.call for d in _route(admin_ingest.router, "/admin/sync-match-weeks", "POST")
                 .dependant.dependencies]
        assert require_admin in calls

    def test_frontend_out_of_week_banner(self):
        """"Admin > Matches shows "N series played outside their scheduled week" above the table" with "Count for Week N" and "Keep in Week M" buttons."""
        js = _read(_JS_PATH)
        banner = _fn(js, "renderOutOfWeekBanner")
        assert "`${n} series played outside their scheduled week`" in banner
        assert "`Count for ${s.scheduled_week_label}`" in banner
        assert "`Keep in ${s.counted_week_label}`" in banner
        assert "setMatchWeek(firstMatch, s.scheduled_week_id" in banner
        assert "setMatchWeek(firstMatch, s.counted_week_id" in banner
        assert "`${API}/admin/matches/out-of-week`" in _fn(js, "loadAdminMatches")
        html = _read(_HTML_PATH)
        assert html.index('id="adminMatchesOutOfWeek"') < html.index('id="admin-matches-table"')

    def test_frontend_banner_no_raw_innerhtml_team_names(self):
        """The banner is built without raw innerHTML interpolation of team names (textContent or _escHtml)."""
        banner = _fn(_read(_JS_PATH), "renderOutOfWeekBanner")
        assert "innerHTML" not in banner
        assert "text.textContent = `${s.team1" in banner
