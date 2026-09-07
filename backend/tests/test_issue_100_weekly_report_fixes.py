"""
Tests for plan-issue-100-weekly-report-fixes.md (resolves GitHub issue #100).

Covers all four user stories from the plan. Backend acceptance criteria (reveal-all
endpoint, winner_team_id gating in `_build_week_summary`) are tested by calling the
router functions directly, matching the established pattern in
test_issue_51_weekly_summary.py (this repo's predecessor plan for the same router) --
FastAPI and `routers.weekly_summary` both import cleanly in this environment, so no
replicated-logic helpers are needed here. Frontend-only acceptance criteria (docked
reveal footer, match date rendering) are covered as frontend file-content assertions,
following the same established pattern (see test_issue_51_weekly_summary.py's
TestViewWeeklyReport / TestRevealWeeklyResults frontend-wiring tests).

  Story: Reveal Button Stays Visible While Scrolling
  Story: Reveal All Currently Available Results at Once
  Story: Hide Match Outcome Until Revealed
  Story: Match Date Displayed

STATUS: stubs only -- every test body is `pytest.fail("not yet implemented")`.
The developer implementing plan-issue-100-weekly-report-fixes.md fills these in.

Run with: cd backend && python -m pytest tests/test_issue_100_weekly_report_fixes.py -v
"""

import os
import sys
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from models import (
    Match, Player, PlayerMatchStats, Team, User, Week,
    WeeklySummary, WeeklySummaryReveal,
)
from routers.weekly_summary import (
    get_weekly_summary, reveal_all_weekly_summaries, reveal_weekly_summary,
)

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
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


def _generate(db, week):
    db.add(WeeklySummary(week_id=week.id, generated_at=int(time.time())))
    db.commit()


# ---------------------------------------------------------------------------
# Story: Reveal Button Stays Visible While Scrolling
# (frontend-only -- covered as file-content assertions once implemented)
# ---------------------------------------------------------------------------

class TestRevealFooterDocked:
    def test_reveal_footer_rendered_outside_scrollable_content(self):
        """The reveal control is docked to the bottom of the popup, as a sibling
        element outside `#weeklySummaryContent` (not inside the scrollable match
        list), so scrolling the match list never moves, hides, or duplicates it."""
        html = _read(_INDEX_HTML_PATH)
        # The footer element exists and carries the reveal-all action.
        assert 'id="weeklySummaryRevealFooter"' in html
        assert 'revealAllWeeklySummaries()' in html
        # It is a sibling that comes *after* the scrollable content div closes,
        # not a child nested inside it.
        content_open = html.index('id="weeklySummaryContent"')
        content_close = html.index('</div>', content_open)
        footer_pos = html.index('id="weeklySummaryRevealFooter"')
        assert footer_pos > content_close

        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        # The old per-match inline reveal button is gone from the scrollable content.
        assert 'revealWeeklySummary(' not in js

    def test_reveal_footer_hidden_when_all_listed_weeks_revealed(self):
        """The docked reveal control is shown whenever at least one currently-listed
        week is not yet revealed, and hidden once everything currently listed has
        been revealed."""
        html = _read(_INDEX_HTML_PATH)
        # Starts hidden until the week list is loaded and evaluated.
        assert 'id="weeklySummaryRevealFooter" class="weekly-summary-reveal-footer hidden"' in html

        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert 'function _updateWeeklySummaryRevealFooter()' in js
        # Visibility is driven by whether any listed week is still unrevealed.
        assert '_weeklySummaryWeeks.some(w => w.revealed === false)' in js
        assert "footer.classList.toggle('hidden'" in js
        # And it is re-evaluated when the tab list (re)renders.
        tabs_fn = js[js.index('function renderWeeklySummaryTabs()'):]
        assert '_updateWeeklySummaryRevealFooter()' in tabs_fn[:tabs_fn.index('\n}')]


# ---------------------------------------------------------------------------
# Story: Reveal All Currently Available Results at Once
# ---------------------------------------------------------------------------

class TestRevealAllWeeklySummaries:
    def test_reveal_all_reveals_every_currently_listed_unrevealed_week(self, db):
        """Clicking the reveal control (POST /weekly-summary/reveal-all) reveals
        every week currently listed in the popup that the user has not yet
        revealed, not just the currently active tab."""
        user = _make_user(db)
        w1 = _make_week(db, "Week 1", offset_start=-172800, offset_end=-90000)
        w2 = _make_week(db, "Week 2", offset_start=-86400, offset_end=-3600)
        _generate(db, w1)
        _generate(db, w2)

        result = reveal_all_weekly_summaries(db=db, current_user=_current_user(user))

        assert set(result["revealed_week_ids"]) == {w1.id, w2.id}
        assert get_weekly_summary(w1.id, db=db, current_user=_current_user(user))["revealed"] is True
        assert get_weekly_summary(w2.id, db=db, current_user=_current_user(user))["revealed"] is True

    def test_reveal_all_is_idempotent_for_already_revealed_weeks(self, db):
        """Weeks already revealed before the reveal-all click are unaffected --
        calling it again changes nothing for them (no duplicate WeeklySummaryReveal
        rows, no revealed_at overwrite)."""
        user = _make_user(db)
        week = _make_week(db)
        _generate(db, week)

        reveal_weekly_summary(week.id, db=db, current_user=_current_user(user))
        row = db.query(WeeklySummaryReveal).filter_by(
            week_id=week.id, user_id=user.id).one()
        original_revealed_at = row.revealed_at

        reveal_all_weekly_summaries(db=db, current_user=_current_user(user))
        reveal_all_weekly_summaries(db=db, current_user=_current_user(user))

        rows = db.query(WeeklySummaryReveal).filter_by(
            week_id=week.id, user_id=user.id).all()
        assert len(rows) == 1
        assert rows[0].revealed_at == original_revealed_at

    def test_reveal_all_does_not_affect_week_generated_after_prior_call(self, db):
        """A week that becomes available (gets listed) after a previous reveal-all
        click starts unrevealed, requiring the reveal control to be used again to
        reveal it."""
        user = _make_user(db)
        w1 = _make_week(db, "Week 1", offset_start=-172800, offset_end=-90000)
        _generate(db, w1)

        reveal_all_weekly_summaries(db=db, current_user=_current_user(user))

        w2 = _make_week(db, "Week 2", offset_start=-86400, offset_end=-3600)
        _generate(db, w2)

        assert get_weekly_summary(w2.id, db=db, current_user=_current_user(user))["revealed"] is False

        reveal_all_weekly_summaries(db=db, current_user=_current_user(user))

        assert get_weekly_summary(w2.id, db=db, current_user=_current_user(user))["revealed"] is True

    def test_reveal_all_requires_authentication(self, db):
        """POST /weekly-summary/reveal-all rejects a request with no authenticated
        current_user rather than revealing weeks for an anonymous caller."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.middleware.sessions import SessionMiddleware

        from database import get_db
        from routers.weekly_summary import router

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret-key")
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post("/weekly-summary/reveal-all")

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Story: Hide Match Outcome Until Revealed
# ---------------------------------------------------------------------------

class TestHideMatchOutcomeUntilRevealed:
    def _setup_played_week(self, db):
        user = _make_user(db)
        week = _make_week(db)
        _make_team(db, 1, "Radiant Squad")
        _make_team(db, 2, "Dire Squad")
        _make_match(db, 9001, week, radiant_id=1, dire_id=2, radiant_win=True)
        _make_player_stats(db, 9001, 101, 1, "Alice", points=12.5, is_mvp=True)
        _make_player_stats(db, 9001, 102, 2, "Bob", points=8.0)
        _generate(db, week)
        return user, week

    def test_build_week_summary_hides_winner_team_id_before_reveal(self, db):
        """Before a week is revealed, `_build_week_summary` sets winner_team_id to
        None for every match, so no team is visually marked as the winner and no
        "Winner" label is shown pre-reveal."""
        user, week = self._setup_played_week(db)

        result = get_weekly_summary(week.id, db=db, current_user=_current_user(user))

        assert result["revealed"] is False
        match = result["series"][0]["matches"][0]
        assert match["winner_team_id"] is None

    def test_build_week_summary_shows_winner_team_id_after_reveal(self, db):
        """After reveal, the winning team's id is populated on the match exactly as
        before this fix, alongside the existing MVP and points breakdown."""
        user, week = self._setup_played_week(db)

        result = reveal_weekly_summary(week.id, db=db, current_user=_current_user(user))

        assert result["revealed"] is True
        match = result["series"][0]["matches"][0]
        assert match["winner_team_id"] == 1
        by_name = {p["name"]: p for p in match["players"]}
        assert by_name["Alice"]["is_mvp"] is True
        assert by_name["Alice"]["points"] == 12.5

    def test_unrevealed_week_still_hides_players_mvp_and_points(self, db):
        """MVP highlighting and per-player points remain hidden before reveal --
        existing gating (no "players" key pre-reveal) is unaffected by the
        winner_team_id fix."""
        user, week = self._setup_played_week(db)

        result = get_weekly_summary(week.id, db=db, current_user=_current_user(user))

        assert "players" not in result["series"][0]["matches"][0]


# ---------------------------------------------------------------------------
# Story: Match Date Displayed
# ---------------------------------------------------------------------------

class TestMatchDateDisplayed:
    def _match_html_fn(self):
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        start = js.index('function _weeklySummaryMatchHtml(')
        end = js.index('\nfunction ', start)
        return js[start:end]

    def test_weekly_summary_match_html_renders_start_time_as_date(self):
        """`_weeklySummaryMatchHtml` in app-weekly-summary.js formats and renders
        each match's `start_time` as a played-on date, so every match in the
        Weekly Report shows the date it was played."""
        fn = self._match_html_fn()
        assert 'm.start_time' in fn
        assert 'toLocaleDateString' in fn
        assert 'weekly-summary-match-date' in fn

    def test_match_date_rendered_regardless_of_reveal_state(self):
        """The match date is rendered unconditionally (not inside the `revealed`
        branch), consistent with the other always-visible match fields (teams, VOD
        link) -- shown both before and after a week is revealed."""
        fn = self._match_html_fn()
        date_render = fn.index('weekly-summary-match-date')
        reveal_branch = fn.index('if (revealed')
        # The date markup is emitted before (outside) the revealed-only players block.
        assert date_render < reveal_branch
