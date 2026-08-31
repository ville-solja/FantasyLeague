"""
Tests for plan-issue-51-weekly-summary.md (resolves GitHub issue #51).

Covers all five user stories from the plan. Most acceptance criteria are backend data/logic
concerns and are tested by calling the router functions directly (this repo's established
pattern — see test_admin_mvp_reflects_in_views.py — passing `db=db` and a plain dict for
`current_user`/`admin`, since bare `Depends()` defaults don't resolve outside FastAPI's real
request pipeline). A few criteria are purely about frontend wiring (button visibility, default
tab selection, reveal-button rendering) and are covered as frontend file-content assertions
instead, following this repo's established frontend-file-content-assertion pattern.

  Story: View the Weekly Report
  Story: Reveal Full Match Results
  Story: New Report Highlight
  Story: Automatic Weekly Summary Generation
  Story: Admin: Attach VOD Links to Matches

Run with: cd backend && python -m pytest tests/test_issue_51_weekly_summary.py -v
"""

import os
import sys
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from models import (
    Card, Match, Player, PlayerMatchStats, Team, User, Week,
    WeeklyRosterEntry, WeeklySummary, WeeklySummaryReveal, WeeklySummarySeen,
)
from routers.admin_matches import set_match_vod, MatchVodBody
from routers.weekly_summary import (
    get_weekly_summary, list_weekly_summaries, mark_weekly_summary_seen,
    reveal_weekly_summary,
)
from weeks import generate_weekly_summaries

_ADMIN = {"user_id": 1, "username": "admin"}

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
_APP_AUTH_JS_PATH = os.path.join(_FRONTEND_DIR, "app-auth.js")
_APP_WEEKLY_SUMMARY_JS_PATH = os.path.join(_FRONTEND_DIR, "app-weekly-summary.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _make_user(db, username="player1"):
    user = User(username=username, email=f"{username}@test.com",
                password_hash="x", is_admin=False, tokens=0)
    db.add(user)
    db.flush()
    return user


def _current_user(user):
    return {"user_id": user.id, "username": user.username, "is_admin": False}


def _make_week(db, label="Week 1", offset_start=-172800, offset_end=-86400):
    """Defaults to a week that has already ended (relative to now)."""
    now = int(time.time())
    w = Week(label=label, start_time=now + offset_start, end_time=now + offset_end,
              is_locked=True)
    db.add(w)
    db.flush()
    return w


def _make_team(db, team_id, name):
    t = Team(id=team_id, name=name, logo_url=f"https://example.com/{team_id}.png")
    db.add(t)
    db.flush()
    return t


def _make_match(db, match_id, week, radiant_id=1, dire_id=2, radiant_win=True, vod_url=None):
    m = Match(match_id=match_id, radiant_team_id=radiant_id, dire_team_id=dire_id,
              start_time=week.start_time + 100, radiant_win=radiant_win, vod_url=vod_url)
    db.add(m)
    db.flush()
    return m


def _make_player_stats(db, match_id, player_id, team_id, name, points=10.0, is_mvp=False):
    db.add(Player(id=player_id, name=name))
    db.add(PlayerMatchStats(player_id=player_id, match_id=match_id, team_id=team_id,
                             fantasy_points=points, is_mvp=is_mvp))
    db.flush()


def _make_roster_entry(db, week, user, player_id, card_id):
    db.add(Card(id=card_id, player_id=player_id, owner_id=user.id, card_type="common",
                is_active=True))
    db.flush()
    db.add(WeeklyRosterEntry(week_id=week.id, user_id=user.id, card_id=card_id))
    db.commit()


def _generate(db, week):
    db.add(WeeklySummary(week_id=week.id, generated_at=int(time.time())))
    db.commit()


# ---------------------------------------------------------------------------
# Bug fix: team logos not visible (Team.logo_url, an OpenDota HTTP field, is
# rarely populated — the report should prefer the same locally-scraped
# Dotabuff PNG cache the card image generator already uses)
# ---------------------------------------------------------------------------

class TestTeamLogoResolution:
    def test_prefers_local_dotabuff_logo_over_db_logo_url(self, db, tmp_path, monkeypatch):
        """The locally-scraped Dotabuff PNG (served under /assets/) takes priority over
        Team.logo_url, since the latter is rarely populated for lower-tier leagues and
        left most teams with no visible logo at all in the report."""
        import routers.weekly_summary as weekly_summary_module
        logo_dir = tmp_path / "dotabuff_league_logos"
        logo_dir.mkdir()
        (logo_dir / "Radiant_Squad.png").write_bytes(b"fake-png-bytes")
        monkeypatch.setattr(weekly_summary_module, "_LOGO_DIR", str(logo_dir))

        user = _make_user(db)
        week = _make_week(db)
        _make_team(db, 1, "Radiant Squad")  # DB logo_url = https://example.com/1.png
        _make_team(db, 2, "Dire Squad")
        _make_match(db, 9001, week)
        _generate(db, week)

        result = get_weekly_summary(week.id, db=db, current_user=_current_user(user))

        radiant_logo = result["series"][0]["matches"][0]["radiant_team"]["logo_url"]
        assert radiant_logo == "/assets/dotabuff_league_logos/Radiant_Squad.png"

    def test_falls_back_to_db_logo_url_when_no_local_file(self, db, tmp_path, monkeypatch):
        """When no locally-scraped PNG exists for a team, the report still falls back to
        Team.logo_url rather than showing nothing."""
        import routers.weekly_summary as weekly_summary_module
        monkeypatch.setattr(weekly_summary_module, "_LOGO_DIR", str(tmp_path / "nonexistent"))

        user = _make_user(db)
        week = _make_week(db)
        _make_team(db, 1, "Radiant Squad")
        _make_team(db, 2, "Dire Squad")
        _make_match(db, 9001, week)
        _generate(db, week)

        result = get_weekly_summary(week.id, db=db, current_user=_current_user(user))

        radiant_logo = result["series"][0]["matches"][0]["radiant_team"]["logo_url"]
        assert radiant_logo == "https://example.com/1.png"


# ---------------------------------------------------------------------------
# Story: View the Weekly Report
# ---------------------------------------------------------------------------

class TestViewWeeklyReport:
    def test_report_button_visible_when_logged_in(self):
        """A "Weekly report" button is shown in a fixed corner of the UI whenever the user is logged in."""
        html = _read(_INDEX_HTML_PATH)
        assert 'id="weeklyReportBtn"' in html

        auth_js = _read(_APP_AUTH_JS_PATH)
        assert 'document.getElementById("weeklyReportBtn").style.display = loggedIn ? "" : "none";' in auth_js

    def test_popup_shows_one_tab_per_generated_week_summary(self, db):
        """Clicking the button opens a popup with one tab per week that has a generated summary, labeled by week number/label."""
        user = _make_user(db)
        w1 = _make_week(db, "Week 1", offset_start=-172800, offset_end=-90000)
        w2 = _make_week(db, "Week 2", offset_start=-86400, offset_end=-3600)
        _generate(db, w1)
        _generate(db, w2)

        result = list_weekly_summaries(db=db, current_user=_current_user(user))

        assert len(result["weeks"]) == 2
        labels = {w["label"] for w in result["weeks"]}
        assert labels == {"Week 1", "Week 2"}

    def test_default_tab_is_most_recent_week(self):
        """The popup defaults to the most recent available week's tab (the first entry returned by GET /weekly-summary)."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert "await selectWeeklySummaryTab(_weeklySummaryWeeks[0].week_id);" in js

    def test_weeks_without_generated_summary_have_no_tab(self, db):
        """Weeks with no generated summary yet do not appear as tabs."""
        user = _make_user(db)
        w1 = _make_week(db, "Generated", offset_start=-172800, offset_end=-90000)
        _make_week(db, "Not generated", offset_start=3600, offset_end=90000)  # future, ungenerated
        _generate(db, w1)

        result = list_weekly_summaries(db=db, current_user=_current_user(user))

        assert len(result["weeks"]) == 1
        assert result["weeks"][0]["label"] == "Generated"

    def test_unrevealed_week_shows_matches_teams_vod_only_grouped_by_series(self, db):
        """Before reveal, a week's tab shows only series-grouped matches, team names/logos (winner highlighted), and VOD links where set — no player names, points, or MVP info."""
        user = _make_user(db)
        week = _make_week(db)
        _make_team(db, 1, "Radiant Squad")
        _make_team(db, 2, "Dire Squad")
        _make_match(db, 9001, week, radiant_id=1, dire_id=2, radiant_win=True,
                    vod_url="https://youtube.com/watch?v=abc")
        _make_player_stats(db, 9001, 101, 1, "Alice")
        _generate(db, week)

        result = get_weekly_summary(week.id, db=db, current_user=_current_user(user))

        assert result["revealed"] is False
        assert len(result["series"]) == 1
        match = result["series"][0]["matches"][0]
        assert match["radiant_team"]["name"] == "Radiant Squad"
        assert match["dire_team"]["name"] == "Dire Squad"
        assert match["winner_team_id"] == 1
        assert match["vod_url"] == "https://youtube.com/watch?v=abc"
        assert "players" not in match


# ---------------------------------------------------------------------------
# Story: Reveal Full Match Results
# ---------------------------------------------------------------------------

class TestRevealWeeklyResults:
    def test_unrevealed_week_shows_reveal_button(self):
        """Each not-yet-revealed week tab shows a "Reveal results" button."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert "if (!data.revealed) {" in js
        assert "Reveal results" in js

    def test_reveal_unlocks_players_mvp_and_points(self, db):
        """Clicking "Reveal results" reveals every player per match grouped under their team, the MVP-highlighted player, and a points-earned number per player."""
        user = _make_user(db)
        week = _make_week(db)
        _make_team(db, 1, "Radiant Squad")
        _make_team(db, 2, "Dire Squad")
        _make_match(db, 9001, week)
        _make_player_stats(db, 9001, 101, 1, "Alice", points=12.5, is_mvp=True)
        _make_player_stats(db, 9001, 102, 2, "Bob", points=8.0)
        _generate(db, week)

        result = reveal_weekly_summary(week.id, db=db, current_user=_current_user(user))

        assert result["revealed"] is True
        players = result["series"][0]["matches"][0]["players"]
        by_name = {p["name"]: p for p in players}
        assert by_name["Alice"]["is_mvp"] is True
        assert by_name["Alice"]["points"] == 12.5
        assert by_name["Bob"]["is_mvp"] is False
        assert by_name["Bob"]["points"] == 8.0

    def test_points_colored_for_rostered_players_neutral_for_others(self, db):
        """Points-earned number is neutral/grey for players not on the viewing user's roster that week, and accent-colored for players who were on it."""
        user = _make_user(db)
        week = _make_week(db)
        _make_team(db, 1, "Radiant Squad")
        _make_team(db, 2, "Dire Squad")
        _make_match(db, 9001, week)
        _make_player_stats(db, 9001, 101, 1, "Alice")
        _make_player_stats(db, 9001, 102, 2, "Bob")
        _make_roster_entry(db, week, user, player_id=101, card_id=501)
        _generate(db, week)

        result = reveal_weekly_summary(week.id, db=db, current_user=_current_user(user))

        players = result["series"][0]["matches"][0]["players"]
        by_name = {p["name"]: p for p in players}
        assert by_name["Alice"]["on_roster"] is True
        assert by_name["Bob"]["on_roster"] is False

    def test_reveal_is_per_user_and_per_week(self, db):
        """One user revealing a week does not reveal it for any other user, and revealing one week does not reveal any other week."""
        user_a = _make_user(db, "usera")
        user_b = _make_user(db, "userb")
        week1 = _make_week(db, "Week 1", offset_start=-172800, offset_end=-90000)
        week2 = _make_week(db, "Week 2", offset_start=-86400, offset_end=-3600)
        _generate(db, week1)
        _generate(db, week2)

        reveal_weekly_summary(week1.id, db=db, current_user=_current_user(user_a))

        assert get_weekly_summary(week1.id, db=db, current_user=_current_user(user_b))["revealed"] is False
        assert get_weekly_summary(week2.id, db=db, current_user=_current_user(user_a))["revealed"] is False

    def test_reopening_popup_keeps_previously_revealed_weeks_revealed(self, db):
        """Reopening the popup later (same session or after re-login) shows previously revealed weeks already revealed, with no need to reveal again."""
        user = _make_user(db)
        week = _make_week(db)
        _generate(db, week)

        reveal_weekly_summary(week.id, db=db, current_user=_current_user(user))
        result = get_weekly_summary(week.id, db=db, current_user=_current_user(user))

        assert result["revealed"] is True


# ---------------------------------------------------------------------------
# Story: New Report Highlight
# ---------------------------------------------------------------------------

class TestWeeklyReportHighlight:
    def test_highlight_shown_when_new_summary_available_and_unseen(self, db):
        """The Weekly report button shows a highlight once a new week's summary has been generated and the current user has not yet opened the popup since then."""
        user = _make_user(db)
        week = _make_week(db)
        _generate(db, week)

        result = list_weekly_summaries(db=db, current_user=_current_user(user))

        assert result["has_unseen"] is True

    def test_opening_popup_clears_highlight(self, db):
        """Opening the report popup clears the highlight, regardless of whether the user reveals any week's results while it's open."""
        user = _make_user(db)
        week = _make_week(db)
        _generate(db, week)

        mark_weekly_summary_seen(db=db, current_user=_current_user(user))
        result = list_weekly_summaries(db=db, current_user=_current_user(user))

        assert result["has_unseen"] is False

    def test_highlight_reappears_after_next_week_summary_generated(self, db):
        """The highlight reappears the next time a further week's summary is generated, following the same per-user "not opened since" rule."""
        user = _make_user(db)
        week1 = _make_week(db, "Week 1", offset_start=-172800, offset_end=-90000)
        _generate(db, week1)
        mark_weekly_summary_seen(db=db, current_user=_current_user(user))
        assert list_weekly_summaries(db=db, current_user=_current_user(user))["has_unseen"] is False

        week2 = _make_week(db, "Week 2", offset_start=-86400, offset_end=-3600)
        _generate(db, week2)

        assert list_weekly_summaries(db=db, current_user=_current_user(user))["has_unseen"] is True


# ---------------------------------------------------------------------------
# Story: Automatic Weekly Summary Generation
# ---------------------------------------------------------------------------

class TestAutomaticSummaryGeneration:
    def test_week_becomes_available_once_end_time_passes(self, db):
        """A week becomes available in the Weekly Report once now >= week.end_time — the same grace-period boundary auto_lock_weeks uses — not a fixed calendar schedule."""
        past_week = _make_week(db, "Past", offset_start=-172800, offset_end=-3600)
        future_week = _make_week(db, "Future", offset_start=3600, offset_end=90000)

        generate_weekly_summaries(db)

        assert db.get(WeeklySummary, past_week.id) is not None
        assert db.get(WeeklySummary, future_week.id) is None

    def test_generation_runs_uniformly_for_irregular_weeks(self, db):
        """The generation check applies the same way to a regular week and an irregular one (e.g. a compressed finals week with a short window)."""
        now = int(time.time())
        finals_week = Week(label="Finals", start_time=now - 3600, end_time=now - 60,
                            is_locked=True)  # short, irregular window, already ended
        db.add(finals_week)
        db.commit()

        generate_weekly_summaries(db)

        assert db.get(WeeklySummary, finals_week.id) is not None

    def test_generation_is_idempotent(self, db):
        """Re-running the check after a week is already marked available does not re-trigger or duplicate anything."""
        week = _make_week(db)

        generate_weekly_summaries(db)
        first = db.get(WeeklySummary, week.id)
        first_generated_at = first.generated_at

        generate_weekly_summaries(db)

        assert db.query(WeeklySummary).filter_by(week_id=week.id).count() == 1
        assert db.get(WeeklySummary, week.id).generated_at == first_generated_at

    def test_week_with_zero_matches_still_generates_empty_state(self, db):
        """A week with zero matches still becomes available, shown as an empty-state tab rather than never appearing."""
        user = _make_user(db)
        week = _make_week(db)

        generate_weekly_summaries(db)
        result = get_weekly_summary(week.id, db=db, current_user=_current_user(user))

        assert result["series"] == []


# ---------------------------------------------------------------------------
# Story: Admin: Attach VOD Links to Matches
# ---------------------------------------------------------------------------

class TestAdminVodLinks:
    def test_admin_can_set_edit_and_clear_vod_url(self, db):
        """Admin can set, edit, or clear a VOD URL on any match from the existing admin match tooling."""
        week = _make_week(db)
        _make_match(db, 9001, week)

        set_match_vod(9001, MatchVodBody(vod_url="https://youtube.com/watch?v=one"), db=db, admin=_ADMIN)
        assert db.query(Match).filter_by(match_id=9001).first().vod_url == "https://youtube.com/watch?v=one"

        set_match_vod(9001, MatchVodBody(vod_url="https://youtube.com/watch?v=two"), db=db, admin=_ADMIN)
        assert db.query(Match).filter_by(match_id=9001).first().vod_url == "https://youtube.com/watch?v=two"

        set_match_vod(9001, MatchVodBody(vod_url=None), db=db, admin=_ADMIN)
        assert db.query(Match).filter_by(match_id=9001).first().vod_url is None

    def test_invalid_vod_url_rejected(self, db):
        """An invalid (non-URL) VOD value is rejected with a clear error."""
        week = _make_week(db)
        _make_match(db, 9001, week)

        with pytest.raises(HTTPException) as exc_info:
            set_match_vod(9001, MatchVodBody(vod_url="not a url"), db=db, admin=_ADMIN)

        assert exc_info.value.status_code == 422

    def test_vod_link_appears_in_already_generated_week_summary(self, db):
        """Once set, the VOD link appears next to its match in the Weekly Report for every user, including weeks whose summary was generated before the link was added."""
        user = _make_user(db)
        week = _make_week(db)
        _make_team(db, 1, "Radiant Squad")
        _make_team(db, 2, "Dire Squad")
        _make_match(db, 9001, week)
        _generate(db, week)

        before = get_weekly_summary(week.id, db=db, current_user=_current_user(user))
        assert before["series"][0]["matches"][0]["vod_url"] is None

        set_match_vod(9001, MatchVodBody(vod_url="https://youtube.com/watch?v=late"), db=db, admin=_ADMIN)

        after = get_weekly_summary(week.id, db=db, current_user=_current_user(user))
        assert after["series"][0]["matches"][0]["vod_url"] == "https://youtube.com/watch?v=late"

    def test_clearing_vod_url_does_not_affect_other_summary_content(self, db):
        """Clearing the VOD URL removes the link from the report without affecting anything else in that week's summary."""
        user = _make_user(db)
        week = _make_week(db)
        _make_team(db, 1, "Radiant Squad")
        _make_team(db, 2, "Dire Squad")
        _make_match(db, 9001, week, vod_url="https://youtube.com/watch?v=x")
        _make_player_stats(db, 9001, 101, 1, "Alice", points=10.0)
        _generate(db, week)

        set_match_vod(9001, MatchVodBody(vod_url=None), db=db, admin=_ADMIN)

        result = reveal_weekly_summary(week.id, db=db, current_user=_current_user(user))
        match = result["series"][0]["matches"][0]
        assert match["vod_url"] is None
        assert match["radiant_team"]["name"] == "Radiant Squad"
        assert match["players"][0]["name"] == "Alice"
        assert match["players"][0]["points"] == 10.0
