"""
Tests for plan-issue-237-finals-prediction-page.md (resolves GitHub issue #237).

A Finals tab shows the Div 1 final four as a match tree built from our own league
results (no wait on the fixtures site). Logged-in users predict both semi-finals and
the grand final; predictions lock at the first semi game (live, ingested or admin
close); results and correct_picks come from our matches.

  Story 1: The Div 1 Bracket Builds Itself From League Results
  Story 2: Users Predict the Semifinals and Grand Final
  Story 3: Results and Correct Picks Come From Our Matches
  Story 4: Admin Steps In Only for Ties and Exceptions
  Other:   config / tab visibility, models, frontend source checks

Notes:

- A module `db` fixture (in-memory SQLite on a StaticPool, so TestClient threads share it). Div 1 is league 1 ("Kanaliiga Season 16",
  monitored, so the season label is "Season 16"); Div 2 is league 2 ("... Lower").
- The Schedule feed, the feed start times and the fixtures-site standings are
  monkeypatched for every test (autouse `_no_network`), so nothing is fetched.
- State names chosen in finals.py: "projected", "waiting_for_tiebreak", "set",
  "locked", "decided". Saving before the bracket is set, while paused or after the
  lock answers 409.
- Frontend checks read source files; HTML is parsed with html.parser.

Run with: cd backend && python -m pytest tests/test_issue_237_finals_prediction_page.py -v
"""

import inspect
import itertools
import json
import os
import re
from html.parser import HTMLParser

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import models  # noqa: F401  (registers tables for the db fixture)
import finals
from database import get_db
from models import (AuditLog, FinalsBracket, FinalsPrediction, League, LiveMatch, Match,
                    SeasonArchive, Team, User)
from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _media_body

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_FE = os.path.join(_ROOT, "frontend")

DIV1, DIV2 = 1, 2
BASE = 1_760_000_000
DAY = 86400
SEMI_T = BASE + 200 * DAY
T = [101, 102, 103, 104, 105, 106, 107, 108]   # Div 1, strongest first in _rr
NAMES = {101: "OP Platinum", 102: "Reaktor", 103: "Elisa Oyj", 104: "Hoxhunt Fortum",
         105: "Team Five", 106: "Team Six", 107: "Team Seven", 108: "Team Eight"}


def _read(name):
    with open(os.path.join(_FE, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def db():
    """In-memory SQLite shared across threads, so TestClient requests see the test's rows."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(finals, "_feed_series", lambda db: {})
    monkeypatch.setattr(finals, "_feed_semi_start_times", lambda db, b: [])
    monkeypatch.setattr(finals, "fetch_site_standings", lambda: None)
    finals.clear_caches()
    yield
    finals.clear_caches()


_ids = itertools.count(9_000_000_000)


def _leagues(db):
    db.add(League(id=DIV1, name="Kanaliiga Season 16", is_monitored=True))
    db.add(League(id=DIV2, name="Kanaliiga Season 16 Lower", is_monitored=True))
    for tid, name in NAMES.items():
        db.add(Team(id=tid, name=name))
    db.commit()


def _game(db, winner, loser, t, league=DIV1, radiant_win=True):
    """One game; `winner` plays radiant (radiant_win None leaves it undecided)."""
    m = Match(match_id=next(_ids), radiant_team_id=winner, dire_team_id=loser, league_id=league,
              start_time=t, radiant_win=radiant_win)
    db.add(m)
    return m


def _series(db, a, b, result, t, league=DIV1):
    """A best-of-two group series: "2-0", "1-1" or "0-2" from a's side."""
    wa, wb = (int(x) for x in result.split("-"))
    games = [(a, b)] * wa + [(b, a)] * wb
    for i, (w, l) in enumerate(games):
        _game(db, w, l, t + i * 3600, league)


def _play(db, results):
    """results: [(a, b, "2-0"), ...] played on consecutive days from BASE."""
    for k, (a, b, r) in enumerate(results):
        _series(db, a, b, r, BASE + k * DAY)
    db.commit()


def _rr(db, overrides=None, skip=()):
    """Single round robin of T: the lower index wins 2-0 unless overridden."""
    overrides = overrides or {}
    results = []
    for a, b in itertools.combinations(T, 2):
        if (a, b) in skip:
            continue
        results.append((a, b, overrides.get((a, b), "2-0")))
    _play(db, results)


def _user(db, name="alice", admin=False):
    u = User(username=name, email=f"{name}@example.com", password_hash="x", is_admin=admin)
    db.add(u)
    db.commit()
    return u


def _set_bracket(db):
    """Full round robin, bracket stored: sf1 = 101 v 104, sf2 = 102 v 103."""
    _leagues(db)
    _rr(db)
    ctx = finals.refresh(db, now=SEMI_T - DAY)
    db.commit()
    assert ctx["state"] == "set"
    return ctx["bracket"]


def _save(db, user, sf1=101, sf2=102, final=101, now=None):
    out = finals.save_prediction(db, user.id, sf1, sf2, final, now=now)
    db.commit()
    return out


def _row(st, team_id):
    return next(r for r in st["rows"] if r["team_id"] == team_id)


def _client(db, *routers, user=None, reauth=True):
    """A small app on `db`; with `user`, signed in as them, and (reauth) with a recent
    password re-entry, so require_recent_reauth passes."""
    from starlette.middleware.sessions import SessionMiddleware

    import rate_limit
    from deps import get_current_user, require_recent_reauth
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key")
    app.state.limiter = rate_limit.limiter
    for r in routers:
        app.include_router(r)

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    if user is not None:
        identity = {"user_id": user.id, "username": user.username, "is_admin": bool(user.is_admin)}
        app.dependency_overrides[get_current_user] = lambda: identity
        if reauth:
            app.dependency_overrides[require_recent_reauth] = lambda: identity
    return TestClient(app)


@pytest.fixture
def no_limits():
    import routers.finals as rf
    was = rf.limiter.enabled
    rf.limiter.enabled = False
    yield
    rf.limiter.enabled = was


# 2026-10-27 Div 1 table (24/28): OP 12, Reaktor 9, Elisa Oyj and Hoxhunt Fortum 7 shared.
OP, RE, EL, HX, E, F, G, H = T
TABLE_2026_10_27 = [
    (OP, RE, "2-0"), (OP, EL, "2-0"), (OP, HX, "2-0"), (OP, E, "2-0"), (OP, F, "2-0"), (OP, G, "2-0"),
    (RE, EL, "2-0"), (RE, HX, "2-0"), (RE, E, "2-0"), (RE, F, "2-0"), (RE, G, "1-1"),
    (EL, HX, "1-1"), (EL, E, "2-0"), (EL, F, "2-0"), (EL, G, "2-0"),
    (HX, E, "2-0"), (HX, F, "2-0"), (HX, G, "2-0"),
    (E, F, "1-1"), (E, G, "1-1"), (E, H, "1-1"), (F, G, "1-1"), (F, H, "1-1"), (G, H, "1-1"),
]


# ===========================================================================
# Story 1: The Div 1 Bracket Builds Itself From League Results
# ===========================================================================

class TestStory1Standings:

    def test_standings_points_two_one_zero_per_series(self, db):
        """finals standings from ingested Div 1 league matches: a 2-0 series gives the winner 2 points, a 1-1 series gives both teams 1, a 0-2 loss gives 0; each row carries team_id, name, points, series_wins, played."""
        _leagues(db)
        _play(db, [(101, 102, "2-0"), (103, 104, "1-1"), (105, 106, "0-2")])
        st = finals.standings(db)
        pts = {r["team_id"]: r["points"] for r in st["rows"]}
        assert pts[101] == 2 and pts[102] == 0
        assert pts[103] == 1 and pts[104] == 1
        assert pts[105] == 0 and pts[106] == 2
        row = _row(st, 101)
        assert {"team_id", "name", "points", "series_wins", "played"} <= set(row)
        assert row["name"] == "OP Platinum" and row["series_wins"] == 1 and row["played"] == 1
        assert st["played"] == 3

    def test_standings_reproduce_fixtures_site_2026_10_27_table(self, db):
        """Seeding the 2026-10-27 Div 1 results yields OP Platinum 1st on 12 points, Reaktor 2nd on 9, and Elisa Oyj and Hoxhunt Fortum both on 7 marked shared (same rank) after all tiebreaks."""
        _leagues(db)
        _play(db, TABLE_2026_10_27)
        st = finals.standings(db)
        assert (st["played"], st["total"]) == (24, 28)
        assert (st["rows"][0]["name"], st["rows"][0]["points"], st["rows"][0]["rank"]) == ("OP Platinum", 12, 1)
        assert (st["rows"][1]["name"], st["rows"][1]["points"], st["rows"][1]["rank"]) == ("Reaktor", 9, 2)
        el, hx = _row(st, EL), _row(st, HX)
        assert el["points"] == hx["points"] == 7
        assert el["shared"] and hx["shared"] and el["rank"] == hx["rank"] == 3
        assert el["note"] == hx["note"] == "shared"

    def test_standings_tiebreak_series_wins(self, db):
        """Two teams level on points: the one with more series wins ranks higher and is not marked shared (e.g. 3W-0D-2L beats 2W-2D-1L, both on 6 points)."""
        _leagues(db)
        A, B, C, D, E_, F_, G_ = 101, 102, 103, 104, 105, 106, 107
        _play(db, [(A, C, "2-0"), (A, D, "2-0"), (A, E_, "2-0"), (A, F_, "0-2"), (A, G_, "0-2"),
                   (B, C, "2-0"), (B, D, "2-0"), (B, E_, "1-1"), (B, F_, "1-1"), (B, G_, "0-2")])
        st = finals.standings(db)
        a, b = _row(st, A), _row(st, B)
        assert a["points"] == b["points"] == 6
        assert a["rank"] < b["rank"]
        assert not a["shared"] and not b["shared"]
        assert a["note"] == "series wins"

    def test_standings_tiebreak_head_to_head_two_teams(self, db):
        """Two teams level on points and series wins: the winner of their head-to-head series ranks higher; a tiebreak note mentions head-to-head."""
        _leagues(db)
        A, B, C, D, E_ = 101, 102, 103, 104, 105
        _play(db, [(A, B, "2-0"), (A, C, "2-0"), (A, D, "0-2"), (B, D, "2-0"), (B, E_, "2-0")])
        st = finals.standings(db)
        a, b = _row(st, A), _row(st, B)
        assert (a["points"], a["series_wins"]) == (b["points"], b["series_wins"]) == (4, 2)
        assert a["rank"] < b["rank"] and not a["shared"]
        assert "head-to-head" in a["note"] and "head-to-head" in b["note"]

    def test_standings_tiebreak_head_to_head_mini_table_three_teams(self, db):
        """Three teams level on points and wins are ordered by a mini-table of points from only the series among those three teams."""
        _leagues(db)
        A, B, C, D, E_, F_ = 101, 102, 103, 104, 105, 106
        _play(db, [(A, B, "2-0"), (B, C, "2-0"), (C, A, "1-1"),
                   (A, D, "2-0"), (B, E_, "2-0"), (B, F_, "1-1"), (C, D, "2-0"), (C, E_, "2-0")])
        st = finals.standings(db)
        rows = [_row(st, t) for t in (A, B, C)]
        assert {(r["points"], r["series_wins"]) for r in rows} == {(5, 2)}
        assert [r["rank"] for r in rows] == [1, 2, 3]
        assert all(not r["shared"] and r["note"] == "head-to-head" for r in rows)

    def test_standings_level_after_all_tiebreaks_is_shared(self, db):
        """Teams still level after points, series wins and head-to-head (e.g. 1-1 draw between them) get the same rank and shared=True."""
        _leagues(db)
        A, B, C, D = 101, 102, 103, 104
        _play(db, [(A, B, "1-1"), (A, C, "2-0"), (B, D, "2-0")])
        st = finals.standings(db)
        a, b = _row(st, A), _row(st, B)
        assert a["rank"] == b["rank"] == 1
        assert a["shared"] and b["shared"]

    def test_standings_series_falls_back_to_first_two_div1_games(self, db):
        """Without a Schedule feed resolution, a pair's group series is its first two Div 1 league games by start_time; a third game between them (a playoff) is not counted in the group table."""
        _leagues(db)
        _game(db, 102, 101, BASE + 50 * DAY)   # later playoff game, inserted first
        _game(db, 101, 102, BASE)
        _game(db, 101, 102, BASE + 3600)
        db.commit()
        st = finals.standings(db)
        assert _row(st, 101)["points"] == 2 and _row(st, 102)["points"] == 0
        assert _row(st, 101)["played"] == 1 and st["played"] == 1

    def test_standings_feed_resolution_wins_over_first_two_games(self, db, monkeypatch):
        """With a cached Schedule resolution for the pair, its match ids form the group series."""
        _leagues(db)
        g1 = _game(db, 102, 101, BASE)            # friendly before the group series
        g2 = _game(db, 101, 102, BASE + DAY)
        g3 = _game(db, 101, 102, BASE + DAY + 3600)
        db.commit()
        monkeypatch.setattr(finals, "_feed_series", lambda db: {(101, 102): [g2.match_id, g3.match_id]})
        st = finals.standings(db)
        assert _row(st, 101)["points"] == 2 and g1.match_id not in st["group_ids"]

    def test_standings_ignore_div2_and_other_league_matches(self, db):
        """Matches in the Div 2 league, or between a Div 1 team and a non-Div-1 team, do not affect Div 1 standings or the played count."""
        _leagues(db)
        db.add(Team(id=201, name="Lower One"))
        _play(db, [(101, 102, "2-0"), (103, 104, "2-0"), (103, 105, "2-0")])
        for k in range(3):
            _game(db, 201, 202, BASE + k * DAY, league=DIV2)
        _game(db, 101, 103, BASE + 5 * DAY, league=DIV2)
        _game(db, 103, 101, BASE + 5 * DAY + 3600, league=DIV2)
        _game(db, 201, 101, BASE + 6 * DAY, league=DIV1)
        _game(db, 201, 101, BASE + 6 * DAY + 3600, league=DIV1)
        db.commit()
        st = finals.standings(db)
        assert 201 not in st["teams"]
        assert st["played"] == 3
        assert _row(st, 101)["points"] == 2 and _row(st, 101)["played"] == 1
        assert _row(st, 103)["played"] == 2


class TestStory1BracketState:

    def test_bracket_state_projected_while_group_series_remain(self, db):
        """With fewer than 28 Div 1 group series played, bracket_state(db) is "projected" and no FinalsBracket row exists."""
        _leagues(db)
        _rr(db, skip={(105, 108)})
        assert finals.bracket_state(db) == "projected"
        assert db.query(FinalsBracket).count() == 0

    def test_get_finals_projected_tree_slot_labels_and_played_count(self, db):
        """GET /finals in projected state returns played=N, total=28 ("N/28 group series played"), and tree slots labelled "1st place" .. "4th place" with the current team name ("now OP Platinum") or tie=True for shared ranks."""
        _leagues(db)
        _play(db, TABLE_2026_10_27)
        view = finals.public_view(db, None)
        assert view["state"] == "projected"
        assert (view["played"], view["total"]) == (24, 28)
        assert view["notice"] == "24/28 group series played"
        sf1, sf2, final = view["tree"]
        assert [s["slot"] for s in sf1["teams"]] == ["1st place", "4th place"]
        assert [s["slot"] for s in sf2["teams"]] == ["2nd place", "3rd place"]
        assert sf1["teams"][0]["now"] == "OP Platinum" and not sf1["teams"][0]["tie"]
        assert sf2["teams"][0]["now"] == "Reaktor"
        assert sf1["teams"][1]["tie"] and sf2["teams"][1]["tie"]
        assert sf2["teams"][1]["tied"] == ["Elisa Oyj", "Hoxhunt Fortum"]
        assert [s["slot"] for s in final["teams"]] == ["Winner of semi-final 1", "Winner of semi-final 2"]

    def test_get_finals_projected_has_no_pick_controls(self, db):
        """GET /finals in projected state reports picks not open (e.g. can_predict=False) and no own prediction."""
        _leagues(db)
        _play(db, TABLE_2026_10_27)
        u = _user(db)
        view = finals.public_view(db, u.id)
        assert view["open"] is False and view["can_predict"] is False
        assert view["prediction"] is None

    def test_bracket_set_automatically_at_28_of_28(self, db):
        """When all 28 group series have results and seeds 1-4 are clear, one refresh stores a FinalsBracket (season_label, division="div1", seed_source="standings") with semi-final 1 = seed1 vs seed4 and semi-final 2 = seed2 vs seed3, and state becomes "set"."""
        _leagues(db)
        _rr(db)
        ctx = finals.refresh(db)
        db.commit()
        b = db.query(FinalsBracket).one()
        assert (b.season_label, b.division, b.seed_source) == ("Season 16", "div1", "standings")
        assert [b.seed1_team_id, b.seed2_team_id, b.seed3_team_id, b.seed4_team_id] == [101, 102, 103, 104]
        assert finals.series_teams(b)["sf1"] == (101, 104)
        assert finals.series_teams(b)["sf2"] == (102, 103)
        assert ctx["state"] == "set"
        assert json.loads(b.seed_names_json)["101"] == "OP Platinum"

    def test_bracket_set_is_idempotent_per_season_and_division(self, db):
        """Refreshing again after the bracket is set does not create a second row or change the seeds (unique season_label+division)."""
        b = _set_bracket(db)
        seeds = (b.seed1_team_id, b.seed2_team_id, b.seed3_team_id, b.seed4_team_id)
        finals.refresh(db)
        finals.refresh(db)
        db.commit()
        rows = db.query(FinalsBracket).all()
        assert len(rows) == 1
        assert (rows[0].seed1_team_id, rows[0].seed2_team_id, rows[0].seed3_team_id, rows[0].seed4_team_id) == seeds

    def test_bracket_tie_at_cut_holds_waiting_for_tiebreak(self, db):
        """At 28/28 with a shared tie across the 4th/5th cut, no bracket is stored, state is "waiting_for_tiebreak", and GET /finals carries the text "Seeding waits for a tiebreak decision"."""
        _leagues(db)
        _rr(db, overrides={(104, 105): "1-1"})
        assert finals.bracket_state(db) == "waiting_for_tiebreak"
        assert db.query(FinalsBracket).count() == 0
        view = finals.public_view(db, None)
        assert view["notice"] == "Seeding waits for a tiebreak decision"
        assert view["open"] is False

    def test_bracket_tie_inside_top_four_holds(self, db):
        """At 28/28 with a shared tie between seeds 3 and 4 (e.g. Elisa Oyj and Hoxhunt Fortum), the bracket is held in "waiting_for_tiebreak"."""
        _leagues(db)
        _rr(db, overrides={(103, 104): "1-1"})
        st = finals.standings(db)
        assert _row(st, 103)["shared"] and _row(st, 104)["shared"]
        assert finals.bracket_state(db) == "waiting_for_tiebreak"
        assert db.query(FinalsBracket).count() == 0

    def test_bracket_tie_below_cut_does_not_hold(self, db):
        """A shared tie only among ranks 5-8 does not hold the bracket; it is set from the standings."""
        _leagues(db)
        _rr(db, overrides={(106, 107): "1-1"})
        assert _row(finals.standings(db), 106)["shared"]
        assert finals.bracket_state(db) == "set"
        b = db.query(FinalsBracket).one()
        assert b.seed_source == "standings"

    def test_get_finals_tree_scores_and_live_flag(self, db):
        """GET /finals after set: each series has team names/logos, series score once games are in (e.g. 1-0), and live=True while a LiveMatch (ended_at None) between its two teams in the Div 1 league exists."""
        _set_bracket(db)
        _game(db, 101, 104, SEMI_T)
        now = SEMI_T + 3 * 3600
        db.add(LiveMatch(match_id=next(_ids), league_id=DIV1, radiant_team_id=104, dire_team_id=101,
                         players_json="[]", first_seen_at=SEMI_T + 2 * 3600, last_seen_at=now))
        db.commit()
        view = finals.public_view(db, None, finals.refresh(db, now=now))
        sf1, sf2, _ = view["tree"]
        assert [t["name"] for t in sf1["teams"]] == ["OP Platinum", "Hoxhunt Fortum"]
        assert "logo_url" in sf1["teams"][0]
        assert sf1["score"] == [1, 0] and sf1["live"] is True
        assert sf2["score"] is None and sf2["live"] is False


# ===========================================================================
# Story 2: Users Predict the Semifinals and Grand Final
# ===========================================================================

class TestStory2Picking:

    def test_get_finals_open_state_shows_close_notice(self, db):
        """With the bracket set and not locked, GET /finals reports picks open and includes "Predictions close when the first semi-final game starts"."""
        _set_bracket(db)
        u = _user(db)
        view = finals.public_view(db, u.id)
        assert view["state"] == "set" and view["open"] and view["can_predict"]
        assert view["notice"] == "Predictions close when the first semi-final game starts"

    def test_put_prediction_valid_picks_appends_row(self, db, no_limits):
        """PUT /finals/prediction {sf1_pick, sf2_pick, final_pick} by a logged-in user with valid picks answers 200 and adds one FinalsPrediction row (bracket_id, user_id, picks, saved_at)."""
        import routers.finals as rf
        b = _set_bracket(db)
        u = _user(db)
        res = _client(db, rf.router, user=u).put(
            "/finals/prediction", json={"sf1_pick": 104, "sf2_pick": 102, "final_pick": 104})
        assert res.status_code == 200, res.text
        assert res.json()["prediction"]["final_pick"] == 104
        row = db.query(FinalsPrediction).one()
        assert (row.bracket_id, row.user_id, row.sf1_pick, row.sf2_pick, row.final_pick) == (b.id, u.id, 104, 102, 104)
        assert row.saved_at and row.correct_picks is None

    @pytest.mark.parametrize("missing", ["sf1_pick", "sf2_pick", "final_pick"])
    def test_put_prediction_missing_pick_422(self, db, no_limits, missing):
        """PUT /finals/prediction with any of sf1_pick, sf2_pick or final_pick missing answers 422 and stores no row."""
        import routers.finals as rf
        _set_bracket(db)
        body = {"sf1_pick": 101, "sf2_pick": 102, "final_pick": 101}
        body.pop(missing)
        res = _client(db, rf.router, user=_user(db)).put("/finals/prediction", json=body)
        assert res.status_code == 422
        assert db.query(FinalsPrediction).count() == 0

    def test_put_prediction_team_not_in_series_422(self, db):
        """PUT /finals/prediction with sf1_pick not one of semi-final 1's two teams (or sf2_pick outside semi 2) answers 422 and stores no row."""
        from fastapi import HTTPException
        _set_bracket(db)
        u = _user(db)
        for sf1, sf2 in ((102, 102), (101, 104), (105, 102)):
            with pytest.raises(HTTPException) as exc:
                _save(db, u, sf1=sf1, sf2=sf2, final=sf1)
            assert exc.value.status_code == 422
        assert db.query(FinalsPrediction).count() == 0

    def test_put_prediction_final_not_one_of_semi_picks_422(self, db):
        """PUT /finals/prediction with final_pick not equal to the user's sf1_pick or sf2_pick answers 422 and stores no row."""
        from fastapi import HTTPException
        _set_bracket(db)
        with pytest.raises(HTTPException) as exc:
            _save(db, _user(db), sf1=101, sf2=102, final=103)
        assert exc.value.status_code == 422
        assert db.query(FinalsPrediction).count() == 0

    def test_put_prediction_logged_out_401(self, db, no_limits):
        """PUT /finals/prediction without a session answers 401 and stores no row."""
        import routers.finals as rf
        _set_bracket(db)
        res = _client(db, rf.router).put(
            "/finals/prediction", json={"sf1_pick": 101, "sf2_pick": 102, "final_pick": 101})
        assert res.status_code == 401
        assert res.json()["detail"] == "Not authenticated"
        assert db.query(FinalsPrediction).count() == 0

    def test_put_prediction_before_bracket_set_409(self, db):
        """PUT /finals/prediction while state is projected or waiting_for_tiebreak is refused (409) and stores no row."""
        from fastapi import HTTPException
        _leagues(db)
        _rr(db, overrides={(104, 105): "1-1"}, skip={(107, 108)})
        u = _user(db)
        assert finals.bracket_state(db) == "projected"
        with pytest.raises(HTTPException) as exc:
            _save(db, u)
        assert exc.value.status_code == 409
        _play(db, [(107, 108, "2-0")])
        assert finals.bracket_state(db) == "waiting_for_tiebreak"
        with pytest.raises(HTTPException) as exc:
            _save(db, u)
        assert exc.value.status_code == 409
        assert db.query(FinalsPrediction).count() == 0

    def test_put_prediction_while_paused_refused(self, db):
        """PUT /finals/prediction while the admin has paused predictions is refused (409) and stores no row."""
        from fastapi import HTTPException
        b = _set_bracket(db)
        b.paused = True
        db.commit()
        with pytest.raises(HTTPException) as exc:
            _save(db, _user(db))
        assert exc.value.status_code == 409 and exc.value.detail == "Predictions are paused"
        assert db.query(FinalsPrediction).count() == 0
        assert finals.public_view(db, None)["notice"] == "Predictions are paused"

    def test_put_prediction_rate_limited(self, db):
        """PUT /finals/prediction is rate-limited: repeated saves beyond the limit answer 429 (build a small app with app.state.limiter = routers.finals.limiter)."""
        import routers.finals as rf
        # The limit value and the Limiter both come from the router module itself, so
        # another file reloading rate_limit (a new Limiter, other env values) can't skew it.
        assert rf.RATE_LIMIT_FINALS_PREDICTION == "10/minute"
        limits = rf.limiter._route_limits.get("routers.finals.save_prediction_route", [])
        assert [str(lim.limit) for lim in limits] == ["10 per 1 minute"]
        _set_bracket(db)
        client = _client(db, rf.router, user=_user(db))
        client.app.state.limiter = rf.limiter
        was = rf.limiter.enabled
        rf.limiter.enabled = True
        rf.limiter.reset()
        try:
            limit = int(rf.RATE_LIMIT_FINALS_PREDICTION.split("/")[0])
            body = {"sf1_pick": 101, "sf2_pick": 102, "final_pick": 101}
            codes = [client.put("/finals/prediction", json=body).status_code for _ in range(limit + 1)]
        finally:
            rf.limiter.reset()
            rf.limiter.enabled = was
        assert codes[0] == 200
        assert codes[-1] == 429

    def test_put_prediction_append_only_revisions(self, db):
        """Saving twice keeps both rows (append-only); GET /finals returns the latest as the user's own prediction while open."""
        _set_bracket(db)
        u = _user(db)
        _save(db, u, sf1=101, sf2=102, final=101, now=SEMI_T - 500)
        _save(db, u, sf1=104, sf2=103, final=103, now=SEMI_T - 400)
        assert db.query(FinalsPrediction).count() == 2
        own = finals.public_view(db, u.id)["prediction"]
        assert (own["sf1_pick"], own["sf2_pick"], own["final_pick"]) == (104, 103, 103)

    def test_identical_resave_adds_no_row(self, db):
        """Saving the same three picks as the latest save keeps one row."""
        _set_bracket(db)
        u = _user(db)
        _save(db, u, now=SEMI_T - 500)
        _save(db, u, now=SEMI_T - 400)
        assert db.query(FinalsPrediction).count() == 1

    def test_revisions_capped_per_user(self, db):
        """Past MAX_REVISIONS saves per user and bracket a change is refused (429); the last save counts."""
        from fastapi import HTTPException
        _set_bracket(db)
        u, v = _user(db, "u1"), _user(db, "u2")
        for i in range(finals.MAX_REVISIONS):
            sf1 = 101 if i % 2 == 0 else 104
            _save(db, u, sf1=sf1, sf2=102, final=sf1, now=SEMI_T - 1000 + i)
        with pytest.raises(HTTPException) as exc:
            _save(db, u, sf1=101, sf2=103, final=103, now=SEMI_T - 500)
        assert exc.value.status_code == 429
        assert db.query(FinalsPrediction).filter_by(user_id=u.id).count() == finals.MAX_REVISIONS
        _save(db, v, now=SEMI_T - 400)   # other users are not affected
        assert finals.public_view(db, u.id)["prediction"]["sf1_pick"] == 104

    def test_get_finals_logged_out_shows_tree_and_login_prompt(self, db):
        """GET /finals without a session answers 200 with the tree and no own prediction (frontend shows "Log in to predict")."""
        import routers.finals as rf
        _set_bracket(db)
        res = _client(db, rf.router).get("/finals")
        assert res.status_code == 200
        data = res.json()
        assert len(data["tree"]) == 3 and data["logged_in"] is False
        assert data["prediction"] is None and data["can_predict"] is False and data["open"] is True


class TestStory2Lock:

    def test_lock_from_live_match(self, db):
        """A LiveMatch in the Div 1 league between a semi's two teams sets locked_at = LiveMatch.first_seen_at and lock_source="live"; state becomes "locked"."""
        _set_bracket(db)
        db.add(LiveMatch(match_id=next(_ids), league_id=DIV1, radiant_team_id=102, dire_team_id=103,
                         players_json="[]", first_seen_at=SEMI_T, last_seen_at=SEMI_T + 60))
        db.commit()
        ctx = finals.refresh(db, now=SEMI_T + 60)
        b = ctx["bracket"]
        assert (b.locked_at, b.lock_source, ctx["state"]) == (SEMI_T, "live", "locked")

    def test_lock_from_ingested_match(self, db):
        """With no LiveMatch, an ingested Div 1 match between a semi's teams with start_time after set_at sets locked_at = start_time and lock_source="ingested"."""
        _set_bracket(db)
        _game(db, 104, 101, SEMI_T + 100)
        db.commit()
        ctx = finals.refresh(db, now=SEMI_T + 5000)
        assert (ctx["bracket"].locked_at, ctx["bracket"].lock_source) == (SEMI_T + 100, "ingested")
        assert ctx["state"] == "locked"

    def test_lock_earliest_source_wins(self, db):
        """When a live sighting and an ingested start_time both exist, locked_at is the earlier of the two and lock_source names it."""
        _set_bracket(db)
        db.add(LiveMatch(match_id=next(_ids), league_id=DIV1, radiant_team_id=101, dire_team_id=104,
                         players_json="[]", first_seen_at=SEMI_T + 60, last_seen_at=SEMI_T + 120))
        db.commit()
        b = finals.refresh(db, now=SEMI_T + 120)["bracket"]
        assert (b.locked_at, b.lock_source) == (SEMI_T + 60, "live")
        _game(db, 101, 104, SEMI_T)   # the live poll saw it a minute late
        db.commit()
        b = finals.refresh(db, now=SEMI_T + 5000)["bracket"]
        assert (b.locked_at, b.lock_source) == (SEMI_T, "ingested")

    def test_lock_optional_feed_start_time(self, db, monkeypatch):
        """If the fixtures feed carries a semi start time earlier than any other source, locked_at uses it with lock_source="feed_time"; without one, nothing breaks."""
        _set_bracket(db)
        assert finals.refresh(db, now=SEMI_T + 10)["state"] == "set"
        _game(db, 101, 104, SEMI_T + 300)
        db.commit()
        monkeypatch.setattr(finals, "_feed_semi_start_times", lambda db, b: [SEMI_T, SEMI_T + 10 * DAY])
        b = finals.refresh(db, now=SEMI_T + 5000)["bracket"]
        assert (b.locked_at, b.lock_source) == (SEMI_T, "feed_time")

    def test_lock_ignores_unrelated_matches(self, db):
        """Matches before set_at, between non-semi pairings, or in another league do not lock the bracket."""
        _set_bracket(db)
        _game(db, 101, 102, SEMI_T)                 # not a semi pairing
        _game(db, 101, 104, SEMI_T, league=DIV2)    # another league
        db.add(LiveMatch(match_id=next(_ids), league_id=DIV2, radiant_team_id=102, dire_team_id=103,
                         players_json="[]", first_seen_at=SEMI_T, last_seen_at=SEMI_T))
        db.add(LiveMatch(match_id=next(_ids), league_id=DIV1, radiant_team_id=101, dire_team_id=105,
                         players_json="[]", first_seen_at=SEMI_T, last_seen_at=SEMI_T))
        db.commit()
        ctx = finals.refresh(db, now=SEMI_T + 100)
        assert ctx["bracket"].locked_at is None and ctx["state"] == "set"

    def test_put_prediction_after_lock_409(self, db):
        """PUT /finals/prediction after locked_at answers 409 and stores no row; GET /finals shows the picks as locked."""
        from fastapi import HTTPException
        _set_bracket(db)
        u = _user(db)
        _save(db, u, now=SEMI_T - 100)
        _game(db, 101, 104, SEMI_T)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            _save(db, u, sf1=104, sf2=103, final=103, now=SEMI_T + 100)
        assert exc.value.status_code == 409
        assert db.query(FinalsPrediction).count() == 1
        view = finals.public_view(db, u.id)
        assert view["state"] == "locked" and view["open"] is False and view["notice"] == "Predictions closed"
        assert view["prediction"]["sf1_pick"] == 101

    def test_effective_prediction_is_last_saved_before_lock(self, db):
        """With revisions at t1 < t2 < locked_at < t3, the effective prediction is the t2 row; GET /finals returns that one as the user's prediction."""
        b = _set_bracket(db)
        u = _user(db)
        for t, picks in ((SEMI_T - 200, (101, 102, 101)), (SEMI_T - 100, (104, 102, 104)),
                         (SEMI_T + 100, (101, 103, 103))):
            db.add(FinalsPrediction(bracket_id=b.id, user_id=u.id, sf1_pick=picks[0], sf2_pick=picks[1],
                                    final_pick=picks[2], saved_at=t))
        b.locked_at, b.lock_source = SEMI_T, "admin"
        db.commit()
        row = finals.effective_predictions(db, b)[u.id]
        assert row.saved_at == SEMI_T - 100
        own = finals.public_view(db, u.id)["prediction"]
        assert (own["sf1_pick"], own["final_pick"]) == (104, 104)

    def test_late_learned_lock_ignores_saves_after_start(self, db):
        """A save accepted while the live poll missed the start, then an ingested game with start_time before that save: the save is ignored, and the effective prediction is the previous revision (or none)."""
        _set_bracket(db)
        u, v = _user(db, "u1"), _user(db, "u2")
        _save(db, u, sf1=101, sf2=102, final=101, now=SEMI_T - 100)
        _save(db, u, sf1=104, sf2=103, final=104, now=SEMI_T + 600)   # accepted: no lock known yet
        _save(db, v, sf1=104, sf2=103, final=104, now=SEMI_T + 700)
        assert db.query(FinalsPrediction).count() == 3
        _game(db, 101, 104, SEMI_T)
        db.commit()
        view = finals.public_view(db, u.id, finals.refresh(db, now=SEMI_T + 4000))
        assert view["state"] == "locked"
        assert view["prediction"]["sf1_pick"] == 101
        assert finals.public_view(db, v.id)["prediction"] is None

    def test_lock_check_runs_in_background_loop(self):
        """main.py's background loop calls the finals lock check next to the live poll (source check)."""
        import main
        loop = inspect.getsource(main._live_poll_loop)
        assert "_live_poll_once()" in loop and "_run_finals_check()" in loop
        assert loop.index("_live_poll_once()") < loop.index("_run_finals_check()")
        check = inspect.getsource(main._run_finals_check)
        assert "finals.refresh(db)" in check and "except Exception" in check

    def test_background_check_failure_is_contained(self, monkeypatch):
        """A failing finals check is logged and never raises into the live loop."""
        import main

        def _boom(db, now=None):
            raise RuntimeError("boom")

        class _S:
            def commit(self): pass
            def rollback(self): pass
            def close(self): pass

        monkeypatch.setattr(main.database, "SessionLocal", lambda: _S())
        monkeypatch.setattr(main.finals, "refresh", _boom)
        main._run_finals_check()


# ===========================================================================
# Story 3: Results and Correct Picks Come From Our Matches
# ===========================================================================

def _semis(db, sf1=(101, 104), sf2=(102, 103), t=SEMI_T):
    """Both semis 2-0 to the first team of each pair."""
    for i, (w, l) in enumerate((sf1, sf2)):
        _game(db, w, l, t + i * 10 * 3600)
        _game(db, w, l, t + i * 10 * 3600 + 3600)
    db.commit()


class TestStory3Results:

    def test_semi_result_first_to_two_wins(self, db):
        """A semi is won by the first team to two game wins in Div 1 league matches between its two teams after set_at; sf1_winner is stored with result source "matches"."""
        _set_bracket(db)
        _game(db, 104, 101, SEMI_T)
        _game(db, 101, 104, SEMI_T + 3600)
        _game(db, 101, 104, SEMI_T + 7200)
        db.commit()
        b = finals.refresh(db, now=SEMI_T + DAY)["bracket"]
        assert b.sf1_winner == 101
        assert json.loads(b.result_sources_json)["sf1"] == "matches"
        assert b.sf2_winner is None

    def test_semi_result_ignores_games_before_set_at(self, db):
        """Group-stage games between the same two teams (before set_at) do not count toward the semi."""
        _set_bracket(db)   # 101 beat 104 2-0 in the group stage
        b = finals.refresh(db, now=SEMI_T)["bracket"]
        assert b.sf1_winner is None
        _game(db, 104, 101, SEMI_T)
        db.commit()
        view = finals.public_view(db, None, finals.refresh(db, now=SEMI_T + 3600))
        assert view["tree"][0]["score"] == [0, 1]

    def test_semi_result_undecided_at_one_one(self, db):
        """At 1-1 in game wins, the semi has no winner yet."""
        _set_bracket(db)
        _game(db, 104, 101, SEMI_T)
        _game(db, 101, 104, SEMI_T + 3600)
        db.commit()
        b = finals.refresh(db, now=SEMI_T + DAY)["bracket"]
        assert b.sf1_winner is None
        assert "sf1" not in json.loads(b.result_sources_json)

    def test_final_between_semi_winners_first_to_two(self, db):
        """The grand final is between sf1_winner and sf2_winner and decided by the first to two wins after both semis; final_winner set and state becomes "decided"."""
        _set_bracket(db)
        _semis(db, sf1=(104, 101), sf2=(102, 103))
        b = finals.refresh(db, now=SEMI_T + DAY)["bracket"]
        assert (b.sf1_winner, b.sf2_winner, b.final_winner) == (104, 102, None)
        assert finals.series_teams(b)["final"] == (104, 102)
        t = SEMI_T + 7 * DAY
        _game(db, 102, 104, t)
        _game(db, 104, 102, t + 3600)
        _game(db, 104, 102, t + 7200)
        db.commit()
        ctx = finals.refresh(db, now=t + DAY)
        assert ctx["bracket"].final_winner == 104 and ctx["state"] == "decided"

    def test_admin_set_result_wins_over_matches(self, db):
        """An admin-set result for a series overrides the matches-derived winner and its source is "admin"."""
        _set_bracket(db)
        _semis(db)
        assert finals.refresh(db, now=SEMI_T + DAY)["bracket"].sf1_winner == 101
        b = finals.set_result(db, "sf1", 104)
        db.commit()
        b = finals.refresh(db, now=SEMI_T + DAY)["bracket"]
        assert b.sf1_winner == 104
        assert json.loads(b.result_sources_json)["sf1"] == "admin"
        assert finals.series_teams(b)["final"] == (104, 102)

    def test_get_finals_shares_hidden_before_lock(self, db):
        """Before the lock, GET /finals contains no per-team share or other users' picks (only the caller's own prediction)."""
        _set_bracket(db)
        u, v = _user(db, "u1"), _user(db, "u2")
        _save(db, u, sf1=101, sf2=102, final=101)
        _save(db, v, sf1=104, sf2=103, final=103)
        view = finals.public_view(db, u.id)
        assert view["results"] is None and view["summary"] is None
        text = json.dumps(view)
        assert "share" not in text and "pct" not in text
        assert view["prediction"]["sf1_pick"] == 101

    def test_get_finals_shares_after_lock_no_individual_picks(self, db):
        """After the lock, each series carries the share of effective picks per team and the prediction count, and no user ids or individual picks."""
        _set_bracket(db)
        users = [_user(db, f"u{i}") for i in range(4)]
        for u, sf1 in zip(users, (101, 101, 101, 104)):
            _save(db, u, sf1=sf1, sf2=102, final=sf1, now=SEMI_T - 100)
        finals.close_now(db, now=SEMI_T)
        db.commit()
        view = finals.public_view(db, None)
        assert view["state"] == "locked"
        sf1 = view["results"]["sf1"]
        assert sf1["count"] == 4
        assert {(s["team_id"], s["pct"]) for s in sf1["shares"]} == {(101, 75), (104, 25)}
        assert view["results"]["sf2"]["shares"] == [{"team_id": 102, "pct": 100}]
        assert set(view["results"]["sf1"]) == {"count", "shares"}
        assert "user_id" not in json.dumps(view)

    def test_get_finals_own_marks_correct_and_wrong(self, db):
        """Once a series has a winner, the caller's pick for it is marked correct or wrong."""
        _set_bracket(db)
        u = _user(db)
        _save(db, u, sf1=101, sf2=103, final=101, now=SEMI_T - 100)
        _semis(db)
        marks = finals.public_view(db, u.id, finals.refresh(db, now=SEMI_T + DAY))["prediction"]["marks"]
        assert marks == {"sf1": True, "sf2": False, "final": None}

    def test_get_finals_decided_summary(self, db):
        """After the final, GET /finals carries the caller's correct count ("You got N of 3") and how many users got all three."""
        _set_bracket(db)
        u, v, w = _user(db, "u1"), _user(db, "u2"), _user(db, "u3")
        _save(db, u, sf1=101, sf2=102, final=101, now=SEMI_T - 100)
        _save(db, v, sf1=101, sf2=102, final=101, now=SEMI_T - 90)
        _save(db, w, sf1=104, sf2=102, final=102, now=SEMI_T - 80)
        _semis(db)
        t = SEMI_T + 7 * DAY
        _game(db, 101, 102, t)
        _game(db, 101, 102, t + 3600)
        db.commit()
        ctx = finals.refresh(db, now=t + DAY)
        db.commit()
        assert finals.public_view(db, w.id, ctx)["summary"] == {
            "correct": 1, "of": 3, "perfect_count": 2, "prediction_count": 3}
        assert finals.public_view(db, u.id)["summary"]["correct"] == 3
        assert finals.public_view(db, None)["summary"]["correct"] is None


def _decided(db):
    """Bracket set, u1 perfect, u2 one superseded save and one effective, u1 a post-lock save."""
    _set_bracket(db)
    u, v = _user(db, "u1"), _user(db, "u2")
    _save(db, v, sf1=104, sf2=103, final=103, now=SEMI_T - 300)
    _save(db, u, sf1=101, sf2=102, final=101, now=SEMI_T - 200)
    _save(db, v, sf1=104, sf2=102, final=102, now=SEMI_T - 100)
    _save(db, u, sf1=104, sf2=103, final=104, now=SEMI_T + 100)  # after the start: ignored
    _semis(db)
    return u, v


def _final(db, winner=101, loser=102):
    t = SEMI_T + 7 * DAY
    _game(db, winner, loser, t)
    _game(db, winner, loser, t + 3600)
    db.commit()
    finals.refresh(db, now=t + DAY)
    db.commit()


class TestStory3CorrectPicks:

    def test_correct_picks_stored_on_effective_rows_when_final_decided(self, db):
        """When the final is decided, each user's effective prediction gets correct_picks in 0..3; superseded and post-lock rows stay None."""
        u, v = _decided(db)
        _final(db)
        rows = {r.saved_at: r for r in db.query(FinalsPrediction).all()}
        assert rows[SEMI_T - 200].correct_picks == 3     # u1 effective
        assert rows[SEMI_T - 100].correct_picks == 1     # u2 effective: sf2 only
        assert rows[SEMI_T - 300].correct_picks is None  # superseded
        assert rows[SEMI_T + 100].correct_picks is None  # after the lock

    def test_correct_picks_none_before_final_decided(self, db):
        """While the final is undecided, correct_picks stays None on every row."""
        _decided(db)
        finals.refresh(db, now=SEMI_T + DAY)
        db.commit()
        assert all(r.correct_picks is None for r in db.query(FinalsPrediction).all())

    def test_correct_picks_recomputed_after_corrected_result(self, db):
        """Changing a result with PUT /admin/finals/result after the final recomputes correct_picks on effective rows."""
        import routers.admin_finals as ra
        _decided(db)
        _final(db)
        admin = _user(db, "boss", admin=True)
        res = _client(db, ra.router, user=admin).put("/admin/finals/result", json={"series": "final", "winner": 102})
        assert res.status_code == 200, res.text
        db.expire_all()
        rows = {r.saved_at: r for r in db.query(FinalsPrediction).all()}
        assert rows[SEMI_T - 200].correct_picks == 2
        assert rows[SEMI_T - 100].correct_picks == 2
        assert db.query(FinalsBracket).one().final_winner == 102

    def test_season_reset_keeps_finals_tables(self, db, monkeypatch, tmp_path):
        """POST /admin/season/reset leaves finals_brackets and finals_predictions rows (with their season_label) intact."""
        from routers import admin_season
        _decided(db)
        monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda: str(tmp_path / "b.db"))
        admin = _user(db, "boss", admin=True)
        out = admin_season.reset_season(admin_season.SeasonResetBody(force=True), db,
                                        {"user_id": admin.id, "username": admin.username})
        assert out["status"] == "ok"
        assert db.query(Match).count() == 0 and db.query(Team).count() == 0
        b = db.query(FinalsBracket).one()
        assert b.season_label == "Season 16"
        assert db.query(FinalsPrediction).count() == 4
        assert json.loads(b.seed_names_json)["104"] == "Hoxhunt Fortum"

    def test_new_season_label_starts_fresh_bracket(self, db):
        """A bracket from a previous season_label is not shown by GET /finals for the current season."""
        _set_bracket(db)
        db.query(League).filter(League.id == DIV1).update({League.name: "Kanaliiga Season 17"})
        db.query(League).filter(League.id == DIV2).update({League.name: "Kanaliiga Season 17 Lower"})
        db.query(Match).delete()
        db.commit()
        _play(db, [(101, 102, "2-0")])
        view = finals.public_view(db, None)
        assert view["season_label"] == "Season 17"
        assert view["state"] == "projected" and view["locked_at"] is None
        assert db.query(FinalsBracket).count() == 1


# ===========================================================================
# Story 4: Admin Steps In Only for Ties and Exceptions
# ===========================================================================

def _admin_client(db, admin=True):
    import routers.admin_finals as ra
    user = _user(db, "boss" if admin else "viewer", admin=admin)
    return _client(db, ra.router, user=user), user


def _audits(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).all()


class TestStory4Admin:

    def test_admin_get_finals_status_fields(self, db):
        """GET /admin/finals returns standings with tiebreak notes, played/28, state, locked_at and lock_source, paused, and each series' winner and result source."""
        _set_bracket(db)
        _semis(db)
        client, _ = _admin_client(db)
        res = client.get("/admin/finals")
        assert res.status_code == 200, res.text
        data = res.json()
        assert (data["played"], data["total"], data["state"]) == (28, 28, "locked")
        assert {"rank", "points", "series_wins", "note", "shared", "name"} <= set(data["standings"][0])
        b = data["bracket"]
        assert b["lock_source"] == "ingested" and b["locked_at"] == SEMI_T and b["paused"] is False
        assert b["seed_source"] == "standings"
        series = {s["key"]: s for s in b["series"]}
        assert series["sf1"]["winner"] == 101 and series["sf1"]["source"] == "matches"
        assert series["final"]["winner"] is None and series["final"]["source"] is None
        assert data["cross_check"] == {"reachable": False, "differs": False, "site_top4": []}

    @pytest.mark.parametrize("method,path", [
        ("GET", "/admin/finals"),
        ("PUT", "/admin/finals/tiebreak"),
        ("POST", "/admin/finals/pause"),
        ("POST", "/admin/finals/close"),
        ("PUT", "/admin/finals/result"),
    ])
    def test_admin_finals_endpoints_non_admin_403(self, db, method, path):
        """Each admin finals endpoint answers 403 "Admin access required" for a logged-in non-admin and changes nothing."""
        b = _set_bracket(db)
        client, _ = _admin_client(db, admin=False)
        body = {"order": [104, 105]} if path.endswith("tiebreak") else {"series": "sf1", "winner": 104}
        res = client.request(method, path, json=body if method == "PUT" else None)
        assert res.status_code == 403
        assert res.json()["detail"] == "Admin access required"
        db.refresh(b)
        assert (b.paused, b.locked_at, b.sf1_winner) == (False, None, None)
        assert db.query(AuditLog).count() == 0

    def test_admin_tiebreak_sets_bracket_and_audits(self, db):
        """PUT /admin/finals/tiebreak {order: [...]} with exactly the shared group's team ids in waiting_for_tiebreak stores the bracket with seed_source="admin_tiebreak", state "set", and an AuditLog action "admin_finals_tiebreak"."""
        _leagues(db)
        _rr(db, overrides={(104, 105): "1-1"})
        client, _ = _admin_client(db)
        assert {t["team_id"] for t in client.get("/admin/finals").json()["tied"]} == {104, 105}
        res = client.put("/admin/finals/tiebreak", json={"order": [105, 104]})
        assert res.status_code == 200, res.text
        assert res.json() == {"state": "set", "seeds": [101, 102, 103, 105]}
        b = db.query(FinalsBracket).one()
        assert b.seed_source == "admin_tiebreak" and b.seed4_team_id == 105
        assert len(_audits(db, "admin_finals_tiebreak")) == 1

    def test_admin_tiebreak_wrong_team_set_422(self, db):
        """PUT /admin/finals/tiebreak with an order that misses a tied team or includes another team answers 422 and stores nothing."""
        _leagues(db)
        _rr(db, overrides={(104, 105): "1-1"})
        client, _ = _admin_client(db)
        for order in ([104, 106], [104, 105, 106], [105, 105]):
            res = client.put("/admin/finals/tiebreak", json={"order": order})
            assert res.status_code == 422, order
        assert db.query(FinalsBracket).count() == 0
        assert not _audits(db, "admin_finals_tiebreak")

    def test_admin_tiebreak_without_tie_409(self, db):
        """PUT /admin/finals/tiebreak when the state is not waiting_for_tiebreak answers 409."""
        _set_bracket(db)
        client, _ = _admin_client(db)
        res = client.put("/admin/finals/tiebreak", json={"order": [103, 104]})
        assert res.status_code == 409

    def test_admin_tiebreak_offers_fixtures_site_suggestion(self, db, monkeypatch):
        """GET /admin/finals in waiting_for_tiebreak includes the fixtures site's semi-slot order as a suggestion when its mocked feed has one, and none when it doesn't."""
        _leagues(db)
        _rr(db, overrides={(104, 105): "1-1"})
        client, _ = _admin_client(db)
        assert client.get("/admin/finals").json()["suggestion"] is None
        site = [{"name": NAMES[t], "position": i + 1, "shared": False}
                for i, t in enumerate([101, 102, 103, 105, 104, 106, 107, 108])]
        monkeypatch.setattr(finals, "fetch_site_standings", lambda: site)
        assert client.get("/admin/finals").json()["suggestion"] == [105, 104]
        site[3]["shared"] = site[4]["shared"] = True
        site[4]["position"] = 4
        assert client.get("/admin/finals").json()["suggestion"] is None

    def test_admin_pause_toggles_and_audits(self, db):
        """POST /admin/finals/pause flips paused on the bracket (twice returns it) and writes AuditLog "admin_finals_paused"."""
        b = _set_bracket(db)
        client, _ = _admin_client(db)
        assert client.post("/admin/finals/pause").json() == {"paused": True}
        db.refresh(b)
        assert b.paused is True
        assert client.post("/admin/finals/pause").json() == {"paused": False}
        db.refresh(b)
        assert b.paused is False
        assert len(_audits(db, "admin_finals_paused")) == 2

    def test_admin_close_locks_and_audits(self, db):
        """POST /admin/finals/close sets locked_at to now and lock_source="admin" (keeping an earlier lock if already set) and writes AuditLog "admin_finals_closed"."""
        import time as _time
        b = _set_bracket(db)
        client, _ = _admin_client(db)
        before = int(_time.time())
        res = client.post("/admin/finals/close")
        assert res.status_code == 200
        db.refresh(b)
        assert b.lock_source == "admin" and before <= b.locked_at <= int(_time.time())
        assert len(_audits(db, "admin_finals_closed")) == 1
        # An earlier lock is kept.
        b.locked_at, b.lock_source = SEMI_T, "ingested"
        db.commit()
        client.post("/admin/finals/close")
        db.refresh(b)
        assert (b.locked_at, b.lock_source) == (SEMI_T, "ingested")

    def test_admin_close_without_bracket_409(self, db):
        """POST /admin/finals/close with no bracket set answers 409."""
        _leagues(db)
        _play(db, TABLE_2026_10_27)
        client, _ = _admin_client(db)
        assert client.post("/admin/finals/close").status_code == 409
        assert client.post("/admin/finals/pause").status_code == 409
        assert not _audits(db, "admin_finals_closed")

    def test_admin_result_sets_winner_and_audits(self, db):
        """PUT /admin/finals/result {series: "sf1"|"sf2"|"final", winner} stores the winner with source "admin" and writes AuditLog "admin_finals_result_set"."""
        b = _set_bracket(db)
        client, _ = _admin_client(db)
        assert client.put("/admin/finals/result", json={"series": "sf1", "winner": 104}).status_code == 200
        assert client.put("/admin/finals/result", json={"series": "sf2", "winner": 103}).status_code == 200
        res = client.put("/admin/finals/result", json={"series": "final", "winner": 103})
        assert res.status_code == 200 and res.json()["state"] == "decided"
        db.refresh(b)
        assert (b.sf1_winner, b.sf2_winner, b.final_winner) == (104, 103, 103)
        assert b.locked_at is not None and b.lock_source == "admin"   # a result locks open predictions
        assert json.loads(b.result_sources_json) == {"final": "admin", "sf1": "admin", "sf2": "admin"}
        assert len(_audits(db, "admin_finals_result_set")) == 3

    def test_admin_result_invalid_series_or_winner_422(self, db):
        """PUT /admin/finals/result with an unknown series or a winner not one of that series' two teams answers 422."""
        b = _set_bracket(db)
        client, _ = _admin_client(db)
        assert client.put("/admin/finals/result", json={"series": "sf3", "winner": 101}).status_code == 422
        assert client.put("/admin/finals/result", json={"series": "sf1", "winner": 102}).status_code == 422
        # The final needs both semi winners first.
        assert client.put("/admin/finals/result", json={"series": "final", "winner": 101}).status_code == 409
        db.refresh(b)
        assert b.sf1_winner is None and not _audits(db, "admin_finals_result_set")

    def test_cross_check_flags_seed_difference(self, db, monkeypatch):
        """When the mocked fixtures-site standings are reachable and their seeds 1-4 differ from ours, GET /admin/finals sets the cross-check flag."""
        _set_bracket(db)
        client, _ = _admin_client(db)
        same = [{"name": NAMES[t], "position": i + 1, "shared": False} for i, t in enumerate(T)]
        monkeypatch.setattr(finals, "fetch_site_standings", lambda: same)
        cc = client.get("/admin/finals").json()["cross_check"]
        assert cc["reachable"] and not cc["differs"]
        swapped = [dict(r) for r in same]
        swapped[2]["position"], swapped[3]["position"] = 4, 3
        monkeypatch.setattr(finals, "fetch_site_standings", lambda: swapped)
        cc = client.get("/admin/finals").json()["cross_check"]
        assert cc["reachable"] and cc["differs"]
        assert cc["site_top4"] == ["OP Platinum", "Reaktor", "Hoxhunt Fortum", "Elisa Oyj"]

    def test_cross_check_unreachable_is_not_flagged_and_not_used(self, db, monkeypatch):
        """When the fixtures site fails, GET /admin/finals answers 200 with no flag, and seeding/state are unchanged (nothing depends on the cross-check)."""
        import requests

        import schedule
        _set_bracket(db)
        calls = []

        def _fail(url, timeout=None, **kw):
            calls.append((url, timeout))
            raise requests.ConnectionError("down")

        monkeypatch.setattr(finals, "fetch_site_standings", _real_fetch)
        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "https://fixtures.example.test/api/fixtures.json")
        monkeypatch.setattr(finals.requests, "get", _fail)
        client, _ = _admin_client(db)
        res = client.get("/admin/finals")
        assert res.status_code == 200
        data = res.json()
        assert data["cross_check"] == {"reachable": False, "differs": False, "site_top4": []}
        assert data["state"] == "set" and data["bracket"]["seed_source"] == "standings"
        assert calls == [("https://fixtures.example.test/api/standings", finals.SITE_TIMEOUT_SECONDS)]
        assert finals.SITE_TIMEOUT_SECONDS <= 5


_real_fetch = finals.fetch_site_standings


class TestSecurityHardening:

    @pytest.mark.parametrize("method,path,body", [
        ("PUT", "/admin/finals/tiebreak", {"order": [104, 105]}),
        ("POST", "/admin/finals/close", None),
        ("PUT", "/admin/finals/result", {"series": "sf1", "winner": 104}),
    ])
    def test_admin_finals_changes_need_recent_reauth(self, db, method, path, body):
        """Tiebreak, Close now and Set result answer 403 reauth_required without a recent re-auth; Pause doesn't need one."""
        import routers.admin_finals as ra
        b = _set_bracket(db)
        client = _client(db, ra.router, user=_user(db, "boss", admin=True), reauth=False)
        res = client.request(method, path, json=body)
        assert res.status_code == 403 and res.json()["detail"] == "reauth_required"
        db.refresh(b)
        assert (b.locked_at, b.sf1_winner) == (None, None)
        assert client.post("/admin/finals/pause").status_code == 200

    def test_get_finals_shared_part_is_cached_own_part_is_fresh(self, db, monkeypatch):
        """GET /finals refreshes at most once per PUBLIC_CACHE_SECONDS; each caller still gets their own prediction; an admin action clears the cache."""
        import routers.finals as rf
        _set_bracket(db)
        u, v = _user(db, "u1"), _user(db, "u2")
        calls = []
        real = finals.refresh
        monkeypatch.setattr(finals, "refresh", lambda d, now=None: calls.append(1) or real(d, now))
        assert _client(db, rf.router).get("/finals").json()["prediction"] is None
        _save(db, u, sf1=104, sf2=103, final=103)
        calls.clear()
        own_u = finals.cached_public_view(db, u.id)
        own_v = finals.cached_public_view(db, v.id)
        assert calls == []
        assert own_u["prediction"]["final_pick"] == 103 and own_u["can_predict"] is True
        assert own_v["prediction"] is None and own_v["logged_in"] is True
        finals.toggle_pause(db)
        db.commit()
        calls.clear()
        view = finals.cached_public_view(db, u.id)
        assert calls == [1] and view["paused"] is True and view["can_predict"] is False

    def test_correct_picks_only_recomputed_when_results_or_lock_change(self, db, monkeypatch):
        """refresh() skips the correct_picks pass when the lock and results are unchanged."""
        _decided(db)
        _final(db)
        calls = []
        real = finals._update_correct_picks
        monkeypatch.setattr(finals, "_update_correct_picks", lambda d, b: calls.append(1) or real(d, b))
        finals.refresh(db, now=SEMI_T + 20 * DAY)
        assert calls == []

    def test_site_fetch_no_redirects_byte_cap_and_cache(self, monkeypatch):
        """The fixtures-site fetch follows no redirects, reads at most SITE_MAX_BYTES and is cached."""
        import schedule
        monkeypatch.setattr(finals, "fetch_site_standings", _real_fetch)
        monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "https://fixtures.example.test/api/fixtures.json")
        calls = []

        class _Res:
            status_code = 200

            def __init__(self, body):
                self.body = body

            def iter_content(self, chunk_size=1):
                for i in range(0, len(self.body), chunk_size):
                    yield self.body[i:i + chunk_size]

            def close(self):
                pass

        payload = {"body": json.dumps([{"team": "A", "position": 1}]).encode()}

        def _get(url, **kw):
            calls.append(kw)
            return _Res(payload["body"])

        monkeypatch.setattr(finals.requests, "get", _get)
        assert finals.fetch_site_standings() == [{"name": "A", "position": 1, "shared": False}]
        assert finals.fetch_site_standings() is not None
        assert len(calls) == 1
        assert calls[0]["allow_redirects"] is False and calls[0]["stream"] is True
        finals.clear_caches()
        payload["body"] = b"[" + b" " * (finals.SITE_MAX_BYTES + 10) + b"]"
        assert finals.fetch_site_standings() is None


class TestSiteStandingsParsing:

    def test_parse_list_and_nested_shapes(self):
        """The fixtures-site standings are read leniently; unknown shapes give None."""
        rows = [{"team": "A", "position": 1}, {"team": {"name": "B"}, "rank": 2, "shared": True},
                {"name": "C", "division": "lower"}]
        assert finals._parse_site_standings(rows) == [
            {"name": "A", "position": 1, "shared": False}, {"name": "B", "position": 2, "shared": True}]
        assert finals._parse_site_standings({"standings": {"upper": [{"team_name": "X"}]}}) == [
            {"name": "X", "position": 1, "shared": False}]
        assert finals._parse_site_standings("nope") is None
        assert finals._parse_site_standings({"upper": []}) is None


# ===========================================================================
# Other: config / tab visibility, models
# ===========================================================================

class TestConfigAndModels:

    def test_config_finals_available_when_projected(self, db):
        """GET /config returns finals_available=True once every Div 1 team has played at least one group series and the season has not ended."""
        import main
        _leagues(db)
        _play(db, TABLE_2026_10_27)
        assert main.get_config(db)["finals_available"] is True

    def test_config_finals_unavailable_before_and_after_season(self, db):
        """GET /config returns finals_available=False while any Div 1 team has no group series played yet, and after the season ends."""
        import main
        _leagues(db)
        assert main.get_config(db)["finals_available"] is False
        finals.clear_caches()
        _play(db, [(101, 102, "2-0"), (103, 104, "2-0"), (105, 106, "2-0")])
        _game(db, 107, 108, BASE + 10 * DAY)   # 107 v 108: one game, the series isn't complete
        db.commit()
        assert main.get_config(db)["finals_available"] is False
        _game(db, 108, 107, BASE + 10 * DAY + 3600)
        db.commit()
        assert main.get_config(db)["finals_available"] is False   # cached for a minute
        finals.clear_caches()
        assert main.get_config(db)["finals_available"] is True
        finals.clear_caches()
        db.add(SeasonArchive(season_label="Season 16", user_id=1, username="x", points=0, rank=1,
                             archived_at=BASE + 400 * DAY))
        db.commit()
        assert main.get_config(db)["finals_available"] is False

    def test_config_availability_is_cached(self, db, monkeypatch):
        """finals_available is computed at most once per AVAILABILITY_CACHE_SECONDS, not on every page load."""
        import main
        _leagues(db)
        _play(db, TABLE_2026_10_27)
        calls = []
        real = finals.standings
        monkeypatch.setattr(finals, "standings", lambda d: calls.append(1) or real(d))
        assert main.get_config(db)["finals_available"] is True
        assert main.get_config(db)["finals_available"] is True
        assert len(calls) == 1
        assert finals.AVAILABILITY_CACHE_SECONDS <= 120

    def test_models_new_tables_no_migration_needed(self, db):
        """finals_brackets (unique season_label+division) and finals_predictions exist via create_all; migrate.py has no new ALTER for them."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.exc import IntegrityError
        tables = set(sa_inspect(db.get_bind()).get_table_names())
        assert {"finals_brackets", "finals_predictions"} <= tables
        kw = dict(division="div1", seed1_team_id=1, seed2_team_id=2, seed3_team_id=3, seed4_team_id=4,
                  set_at=1, group_end_at=1, seed_source="standings")
        db.add(FinalsBracket(season_label="S", **kw))
        db.commit()
        db.add(FinalsBracket(season_label="S", **kw))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        with open(os.path.join(_ROOT, "backend", "migrate.py"), encoding="utf-8") as f:
            assert "finals_" not in f.read()


# ===========================================================================
# Frontend source checks
# ===========================================================================

class _Tabs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons, self.scripts = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "button" and "tab" in (a.get("class") or "").split():
            self.buttons.append(a)
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])


def _fn(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start)]


def _finals_rules(css):
    return [(sel, body) for sel, body in _css_blocks(css, r"\.finals-")
            if not sel.lstrip().startswith("@")]


class TestFrontend:

    def test_index_html_finals_tab_between_schedule_and_how_to_play(self):
        """frontend/index.html has a Finals tab button between Schedule and How to Play, hidden by default, and loads app-finals.js."""
        p = _Tabs()
        p.feed(_read("index.html"))
        ids = [b.get("id") for b in p.buttons]
        i = ids.index("tab-btn-finals")
        assert ids[i - 1] == "tab-btn-schedule" and ids[i + 1] == "tab-btn-howtoplay"
        assert "hidden" in p.buttons[i]
        assert "/app-finals.js" in p.scripts
        assert 'id="tab-finals"' in _read("index.html")

    def test_app_finals_tab_shown_from_config_finals_available(self):
        """The Finals tab is shown only when /config finals_available is true."""
        cfg = _fn(_read("app-globals.js"), "loadConfig")
        assert "applyFinalsAvailability(cfg.finals_available === true)" in cfg
        apply = _fn(_read("app-finals.js"), "applyFinalsAvailability")
        assert "tab-btn-finals" in apply and ".hidden = !available" in apply
        assert 'if (name === "finals")' in _fn(_read("app-globals.js"), "switchTab")

    def test_style_finals_uses_kana_cards_tokens_only(self):
        """Every .finals-* rule in style.css uses var(--...) tokens for colours (no hex, rgb or rgba literals) and Big Shoulders via the token for team names and labels."""
        css = _read("style.css")
        rules = _finals_rules(css)
        assert rules
        for sel, body in rules:
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), sel
            assert "rgb(" not in body and "rgba(" not in body, sel
            colour_props = r"(?:^|;)\s*(background(?:-color)?|color|border(?:-(?:top|right|bottom|left))?(?:-color)?|stroke|fill|outline(?:-color)?)\s*:\s*([^;]+)"
            for prop in re.findall(colour_props, body):
                value = prop[1]
                assert "var(--" in value or value.strip() in ("none", "transparent", "0", "inherit", "currentColor"), (sel, prop)
        for sel in (".finals-team-name", ".finals-match-label"):
            bodies = [b for s, b in rules if sel in [x.strip() for x in s.split(",")]]
            assert any("font-family: var(--font-display)" in b for b in bodies), sel
            assert any("text-transform: uppercase" in b for b in bodies), sel

    def test_style_finals_block_before_guided_tour(self):
        """All .finals-* rules appear before the "GUIDED TOUR (issue #144)" header in style.css."""
        css = _read("style.css")
        tour = css.index("GUIDED TOUR (issue #144)")
        assert ".finals-" in css[:tour]
        assert ".finals-" not in css[tour:]

    def test_style_finals_phone_stacking(self):
        """A max-width media query stacks the finals tree vertically (flex-direction: column or single grid column), hides the connector lines, and leaves no horizontal overflow."""
        css = _read("style.css")
        start = css.index("@media (max-width: 720px) { /* finals */")
        depth, i = 0, css.index("{", start)
        for j in range(i, len(css)):
            depth += css[j] == "{"
            depth -= css[j] == "}"
            if depth == 0:
                media = css[i + 1:j]
                break
        tree = [b for s, b in _css_blocks(media, r"\.finals-tree") if s.strip() == ".finals-tree"]
        assert tree and ("flex-direction: column" in tree[0] or "grid-template-columns: 1fr" in tree[0])
        conn = [b for s, b in _css_blocks(media, r"\.finals-connector") if s.strip() == ".finals-connector"]
        assert conn and "display: none" in conn[0]
        base = [b for s, b in _css_blocks(css, r"\.finals-tree") if s.strip() == ".finals-tree"]
        assert any("min-width: 0" in b or "max-width: 100%" in b for b in base)
        assert "overflow-x: auto" not in "".join(base)

    def test_style_finals_pick_joins_shared_selected_state_list(self):
        """The finals pick selector (e.g. .finals-pick[aria-pressed="true"]:hover / :focus-visible) is in the SHARED STATES selected-hover and focus-ring selector lists in style.css, with an --accent border of 1.5-2 px on the selected pick."""
        css = _read("style.css")
        start = css.index("SHARED STATES (issue #202)")
        section = css[start:css.index("GUIDED TOUR (issue #144)")]
        sel = '.finals-pick[aria-pressed="true"]'
        hover = [b for s, b in _css_blocks(section, re.escape(sel))
                 if f"{sel}:hover" in [x.strip() for x in s.split(",")]]
        assert any("background: var(--state-selected-hover-bg)" in b for b in hover)
        ring = [b for s, b in _css_blocks(section, re.escape(sel))
                if f"{sel}:focus-visible" in [x.strip() for x in s.split(",")] and "outline" in b]
        assert any("solid var(--accent)" in b for b in ring)
        selected = [b for s, b in _css_blocks(css, re.escape(sel)) if s.strip() == sel]
        assert any(re.search(r"border(-color)?:[^;]*var\(--accent\)", b) for b in selected)
        assert any(re.search(r"var\(--bw-(thin|thick)\)", b) for s, b in _css_blocks(css, r"\.finals-pick")
                   if s.strip() in (".finals-pick", sel))

    def test_app_finals_pick_buttons_use_aria_pressed_and_your_pick_text(self):
        """app-finals.js renders pick buttons with aria-pressed and "Your pick: <team>" text; the final offers only the user's two semi picks."""
        js = _read("app-finals.js")
        assert 'aria-pressed="${' in js and 'class="finals-pick"' in js
        assert "Your pick: " in js
        final = _fn(js, "_finalsPickOptions")
        assert "_finalsPicks.sf1" in final and "_finalsPicks.sf2" in final

    def test_app_finals_winner_uses_mark_winner(self):
        """app-finals.js marks a series winner with a .mark-winner name under a "Winner" label."""
        body = _fn(_read("app-finals.js"), "_finalsWinnerHtml")
        assert ">Winner<" in body and 'class="mark-winner"' in body
        assert body.index(">Winner<") < body.index('class="mark-winner"')

    def test_app_finals_state_texts(self):
        """app-finals.js contains "Log in to predict", "Seeding waits for a tiebreak decision", "Predictions close when the first semi-final game starts", "group series played", "You got" and "Live"."""
        js = _read("app-finals.js")
        for text in ("Log in to predict", "Seeding waits for a tiebreak decision",
                     "Predictions close when the first semi-final game starts", "group series played",
                     "You got", "Live"):
            assert text in js, text

    def test_app_finals_escapes_team_names(self):
        """app-finals.js escapes team names with _escHtml before inserting markup."""
        js = _read("app-finals.js")
        assert "_escHtml(" in js
        names = re.findall(r"\$\{([^}]*\.name[^}]*)\}", js)
        assert names
        for expr in names:
            assert "_escHtml(" in expr or "_teamLogoHtml(" in expr, expr

    def test_app_admin_season_finals_card(self):
        """app-admin-season.js has a Finals card calling /admin/finals, with Pause predictions, Close now, Set result and tiebreak ordering controls."""
        js = _read("app-admin-season.js")
        for text in ("/admin/finals", "/admin/finals/pause", "/admin/finals/close", "/admin/finals/result",
                     "/admin/finals/tiebreak", "Pause predictions", "Close now", "Set result"):
            assert text in js, text
        html = _read("index.html")
        assert 'id="adminFinalsPanel"' in html and "Season Finals" in html
        assert "loadAdminFinals" in _fn(_read("app-globals.js"), "switchTab")
