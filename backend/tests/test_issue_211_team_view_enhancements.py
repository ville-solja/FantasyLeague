"""
Tests for plan-issue-211-team-view-enhancements.md (resolves GitHub issue #211).

The team popup and the Teams tab get the player popup's (#208) depth: a header
with division, season and title chips; summary tiles; the season's series with
upcoming fixtures; a roster with games, share and ownership; points by source
against the average team; top heroes. GET /teams gains divisions, records,
points per game and titles.

  Story 1: A Team's Season at a Glance
  Story 2: The Roster Explained
  Story 3: Where the Team's Points Come From
  Story 4: Teams Tab Ranks Teams
  Cross-cutting: feed-down safety, cache reuse, issue #171 logo allowlist

Approach notes (for the developer filling these in):

- Backend: GET /teams and GET /teams/{id} live in `backend/routers/players.py`;
  new helpers go in `backend/team_insights.py`. Use the `db` fixture below
  (shared StaticPool connection) and `_client(db)` so the TestClient's request
  thread sees seeded rows. Seed Team (`logo_url` on an allowlisted host, see
  `logo_hosts.DEFAULT_LOGO_HOSTS`), League (name carries the division and
  season), Match, PlayerMatchStats with `_match` / `_stat`, and weights with
  `_weights(db)`. Compute expected points with `scoring.fantasy_score` /
  `player_insights.points_by_source`, never hard-coded numbers.
- Schedule feed: ALWAYS monkeypatch `schedule.get_schedule` (the autouse
  `_no_network` fixture sets it to an empty feed; override per test with
  `_feed(monkeypatch, [...])`, using `series_result` with `wins` / `match_ids`
  in the same shape `schedule._fixture_to_series` produces). For feed-down,
  make it raise.
- Hero icons: `schedule._fetch_hero_icon_map()` calls OpenDota and is stubbed
  by the autouse fixture; never let a test reach the network.
- Ownership: seed User rows (`account_type` "full" vs "twitch", `is_tester`)
  and Card rows (`owner_id`, `player_id`, `is_active`).
- Titles: seed SeasonAccolade champion rows (`kind`, `season_label`,
  `division`, `team_name`) via `accolades.set_champions` or directly.
- Frontend "source-reading" stubs read `frontend/app-team-popup.js`,
  `app-players.js`, `index.html`, `style.css`. Parse markup with `html.parser`,
  never with regex over tags (lessons-learned). New CSS goes before
  "GUIDED TOUR (issue #144)".
- Frontend "Node harness" stubs extract render helpers from
  `app-team-popup.js` / `app-players.js` (plus `_escHtml`, `teamLink`,
  `playerLink` and the tooltip/pip helpers from app-globals.js) and run them
  with `_run_node` (skips when Node is missing), using a fake DOM like
  `_FAKE_DOM` in test_issue_208_player_popup_visualizations.py.

Run with: cd backend && python -m pytest tests/test_issue_211_team_view_enhancements.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import shutil
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registers every table for the db fixture)
from database import Base, get_db
from models import Match, Player, PlayerMatchStats, Team, Weight

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


@pytest.fixture
def db():
    """In-memory database on one shared connection so a TestClient's request
    thread sees the same data (overrides conftest's `db`)."""
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


def _client(db):
    """A small app around the players router, sharing `db`."""
    from routers import players
    import rate_limit
    app = FastAPI()
    app.state.limiter = rate_limit.limiter
    app.include_router(players.router)

    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _weights(db, **over):
    from seed import DEFAULT_WEIGHTS
    for w in DEFAULT_WEIGHTS:
        db.add(Weight(key=w["key"], label=w["label"], value=over.get(w["key"], w["value"])))
    db.commit()


def _empty_feed():
    return {"weeks": [], "cached_at": None, "stale": False, "error": None,
            "source": "test", "extra_results": []}


def _feed(monkeypatch, weeks, extra_results=None):
    """Point schedule.get_schedule at a fixed feed (never the network). `weeks` use
    get_schedule's shape: each week has "div1"/"div2" lists of series with team1/team2,
    team1_id/team2_id, datetime_iso, stream_url and series_result (None when upcoming,
    else wins and match_ids as resolve_series_result returns)."""
    import schedule
    payload = dict(_empty_feed(), weeks=weeks, extra_results=extra_results or [])
    monkeypatch.setattr(schedule, "get_schedule", lambda db: payload)
    return payload


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No OpenDota hero maps, an empty schedule feed and cold insight caches."""
    import player_insights
    import schedule
    monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
    monkeypatch.setattr(schedule, "warm_hero_maps_in_background", lambda: None)
    monkeypatch.setattr(schedule, "_hero_icon_cache", None)
    monkeypatch.setattr(schedule, "_hero_name_cache", {})
    monkeypatch.setattr(schedule, "get_schedule", lambda db: _empty_feed())
    player_insights.clear_league_cache()
    try:
        import team_insights
        if hasattr(team_insights, "clear_league_cache"):
            team_insights.clear_league_cache()
    except ImportError:
        pass
    yield
    player_insights.clear_league_cache()


_BASE_TS = 1_760_000_000
_STATS = dict(kills=5, assists=10, deaths=3, gold_per_min=500.0, obs_placed=2, sen_placed=1,
              tower_damage=2000, last_hits=150, denies=10, towers_killed=1, roshan_kills=0,
              teamfight_participation=0.6, camps_stacked=2, rune_pickups=3,
              firstblood_claimed=0, stuns=10.0)


def _seed_teams(db):
    db.add(Team(id=1, name="Reds"))
    db.add(Team(id=2, name="Blues"))
    db.commit()


def _match(db, mid, ts=None, radiant=1, dire=2, rw=True, excluded=False, parse="parsed",
           duration=1800, league_id=None):
    db.add(Match(match_id=mid, radiant_team_id=radiant, dire_team_id=dire, radiant_win=rw,
                 start_time=_BASE_TS + mid * 3600 if ts is None else ts, duration=duration,
                 excluded_from_scoring=excluded, parse_status=parse, league_id=league_id))
    db.commit()


def _stat(db, pid, mid, team=1, mvp=False, hero=None, **over):
    """A stat row whose fantasy_points follow the scoring formula (MVP bonus included)."""
    import card_points
    from scoring import fantasy_score
    if db.get(Player, pid) is None:
        db.add(Player(id=pid, name=f"P{pid}"))
    stats = dict(_STATS, **over)
    weights = card_points._current_weights(db)
    pts = fantasy_score({k: v or 0 for k, v in stats.items()}, weights)
    if mvp:
        pts *= 1 + weights.get("mvp_bonus_pct", 10.0) / 100
    db.add(PlayerMatchStats(player_id=pid, match_id=mid, team_id=team, hero_id=hero, is_mvp=mvp,
                            fantasy_points=pts, **stats))
    db.commit()
    return pts


_LOGO = "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/1.png"
_LOGO2 = "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/2.png"
_EVIL = "https://evil.example/logo.png"


def _league(db, lid, name, monitored=True):
    from models import League
    db.add(League(id=lid, name=name, is_monitored=monitored))
    db.commit()


def _get(db, path):
    res = _client(db).get(path)
    assert res.status_code == 200, res.text
    return res.json()


def _champion(db, season, division, team_name, pid=900, kind="champion"):
    from models import SeasonAccolade
    db.add(SeasonAccolade(season_label=season, kind=kind, division=division if kind == "champion" else None,
                          team_name=team_name if kind == "champion" else None,
                          player_account_id=pid, player_name=f"P{pid}", source="admin", created_at=1))
    db.commit()


def _series(t1, t2, t1_id, t2_id, result=None, dt="2026-10-01T19:00:00", status=None, stream=None):
    """One feed series as get_schedule emits it; result = (team1_wins, team2_wins,
    start_time, match_ids) or None for an unplayed series."""
    out = {"team1": t1, "team2": t2, "team1_id": t1_id, "team2_id": t2_id, "datetime_iso": dt,
           "date": None, "time": None, "stream_url": stream, "stream_label": None, "scheduled": True,
           "match_status": status or ("past" if result else "upcoming"), "series_result": None}
    if result:
        w1, w2, start, ids = result
        out["series_result"] = {"team1_wins": w1, "team2_wins": w2, "game_count": w1 + w2,
                                "start_time": start, "match_ids": ids, "games": []}
    return out


def _week(label, div1=(), div2=()):
    return {"label": label, "div1": list(div1), "div2": list(div2)}


def _user(db, uid, account_type="full", tester=False, demo=False, username=None):
    from models import User
    db.add(User(id=uid, username=username or f"user{uid}", email=f"u{uid}@example.com",
                password_hash="x", account_type=account_type, is_tester=tester, is_demo=demo))
    db.commit()


def _card(db, owner, player, active=True):
    from models import Card
    db.add(Card(player_id=player, owner_id=owner, card_type="common", is_active=active, generation=1))
    db.commit()


def _min_managers(monkeypatch, n):
    """Lower team_insights.OWNERSHIP_MIN_MANAGERS so small fixtures show percentages."""
    import team_insights
    monkeypatch.setattr(team_insights, "OWNERSHIP_MIN_MANAGERS", n)


def _played(db, n, team=1, players=(10, 11), **kw):
    """n matches (ids 1..n) won by team 1 as radiant, each with a stat row per player."""
    total = 0.0
    for mid in range(1, n + 1):
        _match(db, mid, **kw)
        for pid in players:
            total += _stat(db, pid, mid, team=team)
    return total


# ===========================================================================
# Story 1: A Team's Season at a Glance
# ===========================================================================

# --- Backend: header -------------------------------------------------------

def test_get_team_header_has_logo_division_and_season(db, monkeypatch):
    """Backend: GET /teams/{id} returns logo_url (allowlisted host), division from the league name (accolades.league_division) and the season label."""
    monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
    _weights(db)
    _seed_teams(db)
    db.get(Team, 1).logo_url = _LOGO
    db.commit()
    _league(db, 1, "Kanaliiga Season 17")
    _league(db, 2, "Kanaliiga Season 17 Lower")
    _match(db, 1, league_id=2)
    _match(db, 2, league_id=2)
    body = _get(db, "/teams/1")
    assert body["logo_url"] == _LOGO
    assert body["division"] == "div2"
    assert body["season"] == "Season 17"
    assert body["name"] == "Reds"


def test_get_team_titles_matched_by_team_name_case_and_whitespace_insensitive(db):
    """Backend: champion accolades from all seasons whose team_name matches the team's name ignoring case and extra whitespace appear in titles ("S16 Div 1 Champion")."""
    _weights(db)
    db.add(Team(id=1, name="Red  Dragons"))
    db.commit()
    _champion(db, "Season 16", "div1", "  red dragons ", pid=901)
    _champion(db, "Season 16", "div1", "RED DRAGONS", pid=902)   # same title, another player
    _champion(db, "Season 12", "div2", "Red Dragons", pid=903)
    body = _get(db, "/teams/1")
    assert [t["label"] for t in body["titles"]] == ["S16 Div 1 Champion", "S12 Div 2 Champion"]
    first = body["titles"][0]
    assert (first["kind"], first["division"], first["season"], first["season_short"]) == \
        ("champion", "div1", "Season 16", "S16")


def test_get_team_titles_exclude_other_teams_champion_rows(db):
    """Backend: champion rows for a differently named team are not in this team's titles; non-champion accolades are not titles."""
    _weights(db)
    _seed_teams(db)
    _champion(db, "Season 16", "div1", "Blues", pid=901)
    _champion(db, "Season 15", "div1", "Reds United", pid=902)
    _champion(db, "Season 16", None, None, pid=903, kind="most_points")
    _champion(db, "Season 14", "div2", "reds", pid=904)
    assert [t["label"] for t in _get(db, "/teams/1")["titles"]] == ["S14 Div 2 Champion"]
    assert [t["label"] for t in _get(db, "/teams/2")["titles"]] == ["S16 Div 1 Champion"]


def test_get_team_unknown_id_returns_404(db):
    """Backend: GET /teams/{id} for an unknown team still answers 404 "Team not found"."""
    _seed_teams(db)
    res = _client(db).get("/teams/999")
    assert res.status_code == 404
    assert res.json()["detail"] == "Team not found"


# --- Backend: summary ------------------------------------------------------

def test_get_team_summary_series_record_from_schedule_feed(db, monkeypatch):
    """Backend: summary series wins and losses come from the mocked feed's series_result for series involving the team (schedule.find_team_id)."""
    _weights(db)
    _seed_teams(db)
    db.add(Team(id=3, name="Greens"))
    db.commit()
    _feed(monkeypatch, [
        _week("Week 1", div1=[_series("Reds", "Blues", 1, 2, (2, 1, _BASE_TS, [1, 2, 3]))]),
        # No ids on the feed row: the team is found by name (schedule.find_team_id).
        _week("Week 2", div1=[_series("Greens", "REDS", None, None, (2, 0, _BASE_TS + 10, [4, 5]))]),
        _week("Week 3", div1=[_series("Blues", "Greens", 2, 3, (2, 0, _BASE_TS + 20, [6, 7]))]),
    ])
    s = _get(db, "/teams/1")["summary"]
    assert (s["series_wins"], s["series_losses"]) == (1, 1)
    s3 = _get(db, "/teams/3")["summary"]
    assert (s3["series_wins"], s3["series_losses"]) == (1, 1)


def test_get_team_summary_games_record_from_matches(db):
    """Backend: summary games wins and losses come from matches (radiant_win against the team's side)."""
    _weights(db)
    _seed_teams(db)
    _match(db, 1, radiant=1, dire=2, rw=True)    # Reds win as radiant
    _match(db, 2, radiant=2, dire=1, rw=True)    # Reds lose as dire
    _match(db, 3, radiant=1, dire=2, rw=False)   # Reds lose as radiant
    _match(db, 4, radiant=2, dire=1, rw=False)   # Reds win as dire
    _match(db, 5, radiant=1, dire=2, rw=True)
    s = _get(db, "/teams/1")["summary"]
    assert (s["games"], s["wins"], s["losses"]) == (5, 3, 2)
    s2 = _get(db, "/teams/2")["summary"]
    assert (s2["games"], s2["wins"], s2["losses"]) == (5, 2, 3)


def test_get_team_summary_points_per_game_is_combined_scored_points_per_game(db):
    """Backend: points_per_game is the team's players' summed scored fantasy points divided by the team's games."""
    from scoring import display_points
    _weights(db)
    _seed_teams(db)
    total = 0.0
    for mid in (1, 2):
        _match(db, mid)
        for pid in (10, 11, 12, 13, 14):
            total += _stat(db, pid, mid, team=1, kills=mid + pid % 3)
        _stat(db, 20, mid, team=2, kills=30)   # the other team's points don't count
    body = _get(db, "/teams/1")
    assert body["summary"]["points_per_game"] == display_points(total / 2)


def test_get_team_summary_avg_game_length_and_mvps(db):
    """Backend: summary carries the average match duration in seconds and the count of MVPs earned by the team's players."""
    _weights(db)
    _seed_teams(db)
    _match(db, 1, duration=1800)
    _match(db, 2, duration=2001)
    _stat(db, 10, 1, mvp=True)
    _stat(db, 11, 1)
    _stat(db, 10, 2)
    _stat(db, 11, 2, mvp=True)
    _stat(db, 20, 2, team=2, mvp=True)
    s = _get(db, "/teams/1")["summary"]
    assert s["avg_game_length"] == round((1800 + 2001) / 2)
    assert s["mvps"] == 2


def test_get_team_excluded_matches_count_in_no_figure(db, monkeypatch):
    """Backend: an excluded_from_scoring match changes no figure: games W-L, points_per_game, game length, MVPs, roster games/share, sources, heroes."""
    import player_insights
    from scoring import display_points
    _weights(db)
    _seed_teams(db)
    _match(db, 1, duration=1800)
    p10 = _stat(db, 10, 1, hero=1)
    p11 = _stat(db, 11, 1, hero=2)
    _match(db, 2, rw=False, excluded=True, duration=3600)
    _stat(db, 10, 2, mvp=True, hero=3, kills=40)
    _stat(db, 12, 2, hero=4, kills=40)
    body = _get(db, "/teams/1")
    s = body["summary"]
    assert (s["games"], s["wins"], s["losses"]) == (1, 1, 0)
    assert s["points_per_game"] == display_points(p10 + p11)
    assert s["avg_game_length"] == 1800
    assert s["mvps"] == 0
    assert {p["id"]: p["games"] for p in body["players"]} == {10: 1, 11: 1}
    assert all(p["team_games"] == 1 for p in body["players"])
    assert sorted(h["hero_id"] for h in body["heroes"]) == [1, 2]
    from card_points import _current_weights
    weights = _current_weights(db)
    rows = db.query(PlayerMatchStats).filter(PlayerMatchStats.match_id == 1).all()
    stats = [{c: getattr(r, c) for c in player_insights._STAT_COLS} for r in rows]
    expected = {k: sum(player_insights.points_by_source(st, weights)[k] for st in stats)
                for k in player_insights.SOURCE_KEYS}
    assert {r["key"]: r["avg"] for r in body["points_sources"]} == \
        {k: display_points(v, 2) for k, v in expected.items()}
    assert next(r for r in body["points_sources"] if r["key"] == "mvp_bonus")["avg"] == 0


def test_get_team_partial_stat_matches_count(db):
    """Backend: a match with parse_status other than "parsed" (partial stats) still counts in games, points and roster figures."""
    from scoring import display_points
    _weights(db)
    _seed_teams(db)
    _match(db, 1, parse="unparsed")
    pts = _stat(db, 10, 1, obs_placed=None, stuns=None, teamfight_participation=None)
    _match(db, 2, parse="unparseable", rw=False)
    pts += _stat(db, 10, 2)
    body = _get(db, "/teams/1")
    assert body["summary"]["games"] == 2
    assert (body["summary"]["wins"], body["summary"]["losses"]) == (1, 1)
    assert body["summary"]["points_per_game"] == display_points(pts / 2)
    assert body["players"][0]["games"] == 2
    assert body["players"][0]["total_points"] == display_points(pts)


# --- Backend: series list --------------------------------------------------

def test_get_team_series_rows_week_opponent_score_result_oldest_first(db, monkeypatch):
    """Backend: series lists one row per played feed series for the team, newest last, with week, opponent id/name/logo, score ("2-1" parts) and result W or L."""
    monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
    _weights(db)
    _seed_teams(db)
    db.add(Team(id=3, name="Greens"))
    db.get(Team, 2).logo_url = _LOGO2
    db.commit()
    # The feed lists the later series first; the response is oldest first.
    _feed(monkeypatch, [
        _week("Week 2", div1=[_series("Greens", "Reds", 3, 1, (2, 0, _BASE_TS + 7 * 86400, [4, 5]))]),
        _week("Week 1", div1=[_series("Reds", "Blues", 1, 2, (2, 1, _BASE_TS, [1, 2, 3]))]),
    ])
    series = _get(db, "/teams/1")["series"]
    assert [s["week"] for s in series] == ["Week 1", "Week 2"]
    first, second = series
    assert first["week_short"] == "W1"
    assert first["opponent"] == {"id": 2, "name": "Blues", "logo_url": _LOGO2}
    assert (first["wins"], first["losses"], first["result"]) == (2, 1, "W")
    assert first["match_ids"] == [1, 2, 3]
    assert second["opponent"] == {"id": 3, "name": "Greens", "logo_url": None}
    assert (second["wins"], second["losses"], second["result"]) == (0, 2, "L")


def test_get_team_series_upcoming_include_date_and_stream_url(db, monkeypatch):
    """Backend: upcoming series for the team are listed with their date/time and stream_url (null when the feed has none)."""
    _weights(db)
    _seed_teams(db)
    db.add(Team(id=3, name="Greens"))
    db.commit()
    _feed(monkeypatch, [
        _week("Week 1", div1=[_series("Reds", "Blues", 1, 2, dt="2026-10-01T19:00:00", status="past")]),  # no result: dropped
        _week("Week 5", div1=[_series("Greens", "Reds", 3, 1, dt="2026-10-29T19:00:00")]),
        _week("Week 4", div1=[_series("Reds", "Blues", 1, 2, dt="2026-10-22T19:00:00",
                                      stream="https://www.twitch.tv/kanaliiga")]),
    ])
    body = _get(db, "/teams/1")
    assert body["series"] == []
    up = body["upcoming"]
    assert [u["datetime_iso"] for u in up] == ["2026-10-22T19:00:00", "2026-10-29T19:00:00"]
    assert up[0]["stream_url"] == "https://www.twitch.tv/kanaliiga"
    assert up[0]["opponent"]["name"] == "Blues" and up[0]["week"] == "Week 4"
    assert up[1]["stream_url"] is None
    assert up[1]["opponent"]["id"] == 3


def test_get_team_no_matches_returns_empty_state_with_header_and_titles(db, monkeypatch):
    """Backend: a team without matches answers 200 with zeroed summary, empty series/players/heroes, and still its header fields and titles."""
    monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
    _weights(db)
    db.add(Team(id=7, name="Newcomers", logo_url=_LOGO))
    db.commit()
    _champion(db, "Season 9", "div2", "Newcomers")
    body = _get(db, "/teams/7")
    assert body["name"] == "Newcomers" and body["logo_url"] == _LOGO
    assert [t["label"] for t in body["titles"]] == ["S9 Div 2 Champion"]
    assert body["summary"] == {"series_wins": 0, "series_losses": 0, "series_draws": 0, "games": 0,
                               "wins": 0, "losses": 0, "points_per_game": 0.0,
                               "avg_game_length": None, "mvps": 0}
    assert body["series"] == [] and body["upcoming"] == []
    assert body["players"] == [] and body["heroes"] == []
    assert body["division"] is None
    assert body["season"]


# --- Frontend --------------------------------------------------------------

from html.parser import HTMLParser

_VOID = {"img", "br", "input", "meta", "link", "hr", "source"}


class _Collect(HTMLParser):
    """Every element (tag, attrs, inner text) in document order, plus the page text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.els, self.text = [], [], []

    def handle_starttag(self, tag, attrs):
        el = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self.els.append(el)
        if tag not in _VOID:
            self.stack.append(el)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.text.append(data)
        for el in self.stack:
            el["text"] += data


def _parse(html):
    p = _Collect()
    p.feed(html)
    p.close()
    return p


def _by_class(html, cls):
    return [e for e in _parse(html).els if cls in (e["attrs"].get("class") or "").split()]


def _text(html):
    return " ".join("".join(_parse(html).text).split())


def _squash(s):
    return " ".join(s.split())


_FAKE_DOM = r"""
const __els = {};
const __selectors = {};
class El {
  constructor(id) {
    this.id = id; this.attrs = {}; this.cls = new Set(); this.hidden = false; this.children = [];
    this.innerHTML = ""; this.textContent = ""; this.style = {}; this.onclick = null;
    const self = this;
    this.classList = {
      add: (...c) => c.forEach(x => self.cls.add(x)),
      remove: (...c) => c.forEach(x => self.cls.delete(x)),
      contains: c => self.cls.has(c),
      toggle: (c, on) => { if (on === undefined) on = !self.cls.has(c); if (on) self.cls.add(c); else self.cls.delete(c); return on; },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  getBoundingClientRect() { return { left: 10, bottom: 20 }; }
  contains(x) { return x === this; }
  closest() { return null; }
  appendChild(c) { return c; }
  querySelectorAll() { return this.children; }
}
const document = {
  getElementById: id => __els[id] || (__els[id] = new El(id)),
  createElement: () => new El(null),
  body: { appendChild(c) { return c; } },
  addEventListener() {},
  querySelectorAll: sel => __selectors[sel] || [],
};
const window = { innerWidth: 1000, matchMedia: () => ({ matches: true }) };
let __fetchBody = null, __fetchOk = true, __fetchUrl = null;
function fetch(url) { __fetchUrl = url; return Promise.resolve({ ok: __fetchOk, json: () => Promise.resolve(__fetchBody) }); }
const API = "";
const __status = {};
function setStatus(id, msg, ok = true) { __status[id] = { msg: msg, ok: ok }; }
let activeUserId = null;
function __el(id) { const e = document.getElementById(id); return { html: e.innerHTML, text: e.textContent, hidden: e.hidden }; }
"""


def _frontend_src():
    g = _fe("app-globals.js")
    helpers = "\n".join(_fn_source(g, n) for n in (
        "_escHtml", "_safeUrl", "playerLink", "teamLink", "prefersReducedMotion",
        "statusBadgeHtml", "_ownValue", "renderIfChanged"))
    acc = g[g.index("// ACCOLADES (issue 50)"):g.index("// END ACCOLADES (issue 50)")]
    return (_FAKE_DOM + "const _lastHtml = new WeakMap();\n" + helpers + "\n" + acc + "\n"
            + _fe("app-players.js") + "\n" + _fe("app-team-popup.js"))


def _js(body):
    """Run `body` (async; sets `out`) with the Teams tab and the team popup loaded."""
    script = (_frontend_src() + "\nlet out = null;\n(async () => {\n" + body
              + "\nconsole.log(JSON.stringify(out));\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });")
    return _run_node(script)


_SOURCES = [("kills", "Kills"), ("assists", "Assists"), ("farm", "Farm"), ("gpm", "GPM"),
            ("vision", "Vision"), ("objectives", "Objectives"), ("teamfight", "Teamfight"),
            ("stuns", "Stuns"), ("jungle_runes", "Jungle and runes"), ("first_blood", "First blood"),
            ("survival", "Survival"), ("mvp_bonus", "MVP bonus")]


def _RP(pid, name, games, total, share, owned, also=False, role="Core", accolades=None, tags=None):
    return dict(id=pid, name=name, avatar_url=f"https://cdn.example/a{pid}.png", role=role,
                games=games, matches=games, team_games=13, avg_points=round(total / games, 1),
                total_points=total, mvps=0, share=share, owned_pct=owned, also_played=also,
                accolades=accolades or [], tags=tags or [])


def _T(**over):
    """A GET /teams/{id} response."""
    avgs = {"kills": 14.0, "gpm": 11.0, "assists": 9.5, "farm": 6.0, "survival": 4.0,
            "teamfight": 3.0, "vision": 2.0}
    total = sum(avgs.values())
    t = dict(
        id=1, name="Reds <b>", logo_url=_LOGO, division="div1", season="Season 17",
        titles=[{"kind": "champion", "division": "div1", "season": "Season 16", "season_short": "S16",
                 "team_name": "Reds <b>", "label": "S16 Div 1 Champion"}],
        matches=13,
        summary=dict(series_wins=3, series_losses=1, series_draws=0, games=13, wins=8, losses=5,
                     points_per_game=61.24, avg_game_length=1925.4, mvps=4),
        series=[
            dict(week="Week 1", week_short="W1", division="div1",
                 opponent=dict(id=2, name="Blues", logo_url=_LOGO2), wins=2, losses=1, result="W",
                 start_time=_BASE_TS, match_ids=[1, 2, 3], datetime_iso="2026-09-10T19:00:00"),
            dict(week="Week 2", week_short="W2", division="div1",
                 opponent=dict(id=3, name="Greens", logo_url=None), wins=0, losses=2, result="L",
                 start_time=_BASE_TS + 1, match_ids=[4, 5], datetime_iso="2026-09-17T19:00:00"),
        ],
        upcoming=[
            dict(week="Week 5", week_short="W5", division="div1", opponent=dict(id=4, name="Yellows", logo_url=None),
                 datetime_iso="2026-10-22T19:00:00", date=None, time=None, scheduled=True,
                 stream_url="https://www.twitch.tv/kanaliiga", stream_label=None),
            dict(week="Week 6", week_short="W6", division="div1", opponent=dict(id=5, name="Purples", logo_url=None),
                 datetime_iso="2026-10-29T19:00:00", date=None, time=None, scheduled=True,
                 stream_url=None, stream_label=None),
        ],
        players=[
            _RP(10, "Alice", 13, 266.5, 40.1, 25,
                accolades=[{"kind": "champion", "division": "div1", "season": "Season 16",
                            "season_short": "S16", "team_name": "Reds"}],
                tags=[{"key": "caster", "label": "Caster"}]),
            _RP(11, "Bob", 12, 230.0, 34.6, 50, role="Support"),
            _RP(13, "Dan", 13, 150.0, 22.6, 0),
            _RP(12, "Cara", 3, 18.0, 2.7, 10, also=True),
        ],
        points_sources=[{"key": k, "label": lbl, "avg": avgs.get(k, 0.0),
                         "share": round(100 * avgs.get(k, 0.0) / total, 1),
                         "league_avg": round(avgs.get(k, 0.0) * 0.9, 2)} for k, lbl in _SOURCES],
        modifier_values={"bonus_pct": 10.0, "stats": [
            {"stat": "kills", "label": "Kills", "base": 14.0, "value": 1.4},
            {"stat": "gold_per_min", "label": "GPM", "base": 11.0, "value": 1.1},
            {"stat": "assists", "label": "Assists", "base": 9.5, "value": 0.95},
            {"stat": "deaths", "label": "Deaths", "base": 4.0, "value": 0.4}]},
        heroes=[
            dict(hero_id=1, hero_name="Axe", icon_url="https://cdn.example/axe.png", games=4, wins=3, losses=1,
                 avg_points=20.0, players=[dict(id=10, name="Alice", games=3), dict(id=11, name="Bob", games=1)]),
            dict(hero_id=2, hero_name="Lion", icon_url=None, games=2, wins=1, losses=1, avg_points=12.0,
                 players=[dict(id=11, name="Bob <i>", games=2)]),
        ],
    )
    t.update(over)
    return t


_SECTIONS = ["teamModalStats", "teamModalResults", "teamModalRoster", "teamModalSources", "teamModalHeroes"]


def _render(t=None, extra=""):
    body = (f"renderTeamPopup({json.dumps(t or _T())});\n" + extra + "\nout = {};\n"
            + "for (const id of " + json.dumps(_SECTIONS + ["teamModalName", "teamModalLogo", "teamModalMeta",
                                                            "teamModalTitles", "teamModalEmpty"])
            + ") out[id] = __el(id);")
    return _js(body)


def test_team_popup_moved_to_app_team_popup_js_with_script_tag():
    """Source-reading: openTeamModal and the team popup renderers live in frontend/app-team-popup.js, loaded by index.html, and are gone from app-players.js."""
    popup = _fe("app-team-popup.js")
    players = _fe("app-players.js")
    for fn in ("openTeamModal", "closeTeamModal", "renderTeamPopup", "_teamTilesHtml", "_teamResultsHtml",
               "_teamRosterHtml", "_teamSourcesHtml", "_teamHeroesHtml"):
        assert f"function {fn}(" in popup, fn
        assert f"function {fn}(" not in players, fn
    assert "function loadTeams(" in players
    scripts = [e["attrs"].get("src") for e in _parse(_fe("index.html")).els
               if e["tag"] == "script" and e["attrs"].get("src", "").startswith("/app-")]
    assert "/app-team-popup.js" in scripts
    for before in ("/app-globals.js", "/app-players.js", "/app-player-popup.js"):
        assert scripts.index(before) < scripts.index("/app-team-popup.js")
    assert scripts.index("/app-team-popup.js") < scripts.index("/app-init.js")
    # The globals other modules call still exist.
    assert "openTeamModal(" in _fn_source(_fe("app-globals.js"), "teamLink")
    assert "openTeamModal(" in _fe("app-player-popup.js")


def test_team_popup_renders_sections_in_planned_order():
    """Node harness: the popup renders header, summary tiles, season results, roster, points sources and heroes, in that order."""
    els = _parse(_fe("index.html")).els
    ids = [e["attrs"]["id"] for e in els if e["attrs"].get("id", "").startswith("teamModal")]
    order = ["teamModal", "teamModalLogo", "teamModalName", "teamModalMeta", "teamModalTitles"] + _SECTIONS
    assert [i for i in ids if i in order] == order
    out = _render()
    headings = {"teamModalResults": "Season results", "teamModalRoster": "Roster",
                "teamModalSources": "Where the points come from", "teamModalHeroes": "Heroes"}
    for sid in _SECTIONS:
        assert out[sid]["hidden"] is False and out[sid]["html"], sid
    for sid, h in headings.items():
        h2 = [e["text"] for e in _parse(out[sid]["html"]).els if e["tag"] == "h2"]
        assert h2 == [h], sid
    assert len(_by_class(out["teamModalStats"]["html"], "player-modal-stat")) == 5
    assert out["teamModalEmpty"]["hidden"] is True


def test_team_popup_header_division_season_and_title_chips():
    """Node harness: the header shows logo, name, "Div 1 · Season 17" and one chip per title, all escaped."""
    out = _render()
    assert out["teamModalName"]["text"] == "Reds <b>"   # textContent, not markup
    logo = [e for e in _parse(out["teamModalLogo"]["html"]).els if e["tag"] == "img"]
    assert logo and logo[0]["attrs"]["src"] == _LOGO
    assert _text(out["teamModalMeta"]["html"]) == "Div 1 · Season 17"
    chips = _by_class(out["teamModalTitles"]["html"], "accolade-chip")
    assert [_squash(c["text"]) for c in chips] == ["S16 Div 1 Champion"]
    assert chips[0]["attrs"]["title"] == "with Reds <b>"
    assert "<b>" not in out["teamModalTitles"]["html"] and "&lt;b&gt;" in out["teamModalTitles"]["html"]
    # Without a logo: the monogram chip, escaped.
    mono = _render(_T(logo_url=None, name="<x>Reds", division="div2"))
    chip = _by_class(mono["teamModalLogo"]["html"], "team-logo--mono")
    assert chip and chip[0]["text"] == "XR"
    assert _text(mono["teamModalMeta"]["html"]) == "Div 2 · Season 17"


def test_team_popup_summary_tiles_format_game_length_mm_ss():
    """Node harness: summary tiles show Series W-L, Games W-L, pts per game, mm:ss average game length and MVPs."""
    out = _render()
    tiles = _by_class(out["teamModalStats"]["html"], "player-modal-stat")
    vals = [_squash(e["text"]) for e in _by_class(out["teamModalStats"]["html"], "val")]
    lbls = [_squash(e["text"]) for e in _by_class(out["teamModalStats"]["html"], "lbl")]
    assert len(tiles) == 5
    assert vals == ["3–1", "8–5", "61.2", "32:05", "4"]
    assert lbls == ["Series W–L", "Games W–L", "Pts per game", "Avg game", "MVPs"]
    unknown = _render(_T(summary=dict(_T()["summary"], avg_game_length=None, series_draws=2)))
    vals = [_squash(e["text"]) for e in _by_class(unknown["teamModalStats"]["html"], "val")]
    assert vals[0] == "3–1–2" and vals[3] == "—"


def test_team_popup_form_chips_use_text_and_shape_not_colour_alone():
    """Node harness: each form chip and series row carries a visible W or L text and a shape class, plus an accessible label."""
    out = _render()
    html = out["teamModalResults"]["html"]
    form = _by_class(html, "team-form")[0]
    assert form["attrs"]["aria-label"] == "Form: W L"
    chips = _by_class(html, "team-result")
    assert len(chips) == 4   # two in the form strip, one per series row
    for chip in chips:
        cls = chip["attrs"]["class"].split()
        assert chip["text"] in ("W", "L")
        shape = "team-result--win" if chip["text"] == "W" else "team-result--loss"
        assert shape in cls
        assert chip["attrs"]["aria-label"].startswith("Won 2–1 against Blues" if chip["text"] == "W"
                                                      else "Lost 0–2 against Greens")
    css = _fe("style.css")
    win = css[css.index(".team-result--win {"):]
    win = win[:win.index("}")]
    loss = css[css.index(".team-result--loss {"):]
    loss = loss[:loss.index("}")]
    assert "background: transparent" in loss and "background: transparent" not in win


def test_team_popup_series_opponent_links_to_its_popup_and_upcoming_shows_stream():
    """Node harness: a series row's opponent uses teamLink (openTeamModal), and an upcoming row shows date/time and a stream link only when stream_url is set (via _safeUrl)."""
    t = _T()
    t["upcoming"].append(dict(t["upcoming"][1], week_short="W7", stream_url="javascript:alert(1)",
                              datetime_iso="2026-11-05T19:00:00"))
    html = _render(t)["teamModalResults"]["html"]
    rows = _by_class(html, "team-series-row")
    assert len(rows) == 5
    played = [r for r in rows if "team-series-row--upcoming" not in r["attrs"]["class"]]
    upcoming = [r for r in rows if "team-series-row--upcoming" in r["attrs"]["class"]]
    links = [e for e in _parse(html).els if "entity-link" in (e["attrs"].get("class") or "")]
    assert [e["attrs"]["onclick"] for e in links][:2] == ["openTeamModal(2)", "openTeamModal(3)"]
    assert "Blues" in played[0]["text"] and "2–1" in played[0]["text"]
    first = _squash(upcoming[0]["text"])
    assert first.startswith("W5") and "Yellows" in first and "22.10. 19:00" in first
    assert first.index("Yellows") < first.index("22.10. 19:00") < first.index("Stream")
    streams = [e for e in _parse(html).els if e["tag"] == "a" and "stream-link" in e["attrs"].get("class", "")]
    assert [a["attrs"]["href"] for a in streams] == ["https://www.twitch.tv/kanaliiga"]
    assert "javascript:" not in html
    assert "Stream" not in upcoming[1]["text"] and "Stream" not in upcoming[2]["text"]
    assert "_escHtml(_safeUrl(s.stream_url))" in _fn_source(_fe("app-team-popup.js"), "_teamStreamHtml")


def test_team_popup_empty_state_text_keeps_header_and_titles():
    """Node harness: with no matches the popup shows "No matches yet this season." and still renders header and titles."""
    t = _T(summary=dict(series_wins=0, series_losses=0, series_draws=0, games=0, wins=0, losses=0,
                        points_per_game=0, avg_game_length=None, mvps=0),
           series=[], upcoming=[], players=[], heroes=[], matches=0)
    out = _render(t)
    assert out["teamModalEmpty"]["hidden"] is False
    assert out["teamModalEmpty"]["text"] == "No matches yet this season."
    for sid in _SECTIONS:
        assert out[sid]["hidden"] is True, sid
    assert out["teamModalName"]["text"] == "Reds <b>"
    assert [_squash(c["text"]) for c in _by_class(out["teamModalTitles"]["html"], "accolade-chip")] == \
        ["S16 Div 1 Champion"]
    # Upcoming fixtures still show without games.
    soon = _render(dict(t, upcoming=_T()["upcoming"]))
    assert soon["teamModalResults"]["hidden"] is False
    assert len(_by_class(soon["teamModalResults"]["html"], "team-series-row--upcoming")) == 2
    assert soon["teamModalEmpty"]["hidden"] is False


# ===========================================================================
# Story 2: The Roster Explained
# ===========================================================================

def test_get_team_players_rows_have_role_games_avg_total_share_owned(db):
    """Backend: each player row has id, name, avatar_url, role (Core/Support, #208 rule), games, team_games, avg_points, total_points, share, owned_pct, also_played."""
    from scoring import display_points
    _weights(db)
    _seed_teams(db)
    pts = {10: 0.0, 11: 0.0}
    for mid in (1, 2):
        _match(db, mid)
        pts[10] += _stat(db, 10, mid, obs_placed=5, gold_per_min=300.0)   # Support: wards >= 3, GPM < 450
        pts[11] += _stat(db, 11, mid, obs_placed=4, gold_per_min=450.0)   # Core: GPM not under 450
    db.get(Player, 10).avatar_url = "https://cdn.example/a10.png"
    db.commit()
    rows = {p["id"]: p for p in _get(db, "/teams/1")["players"]}
    assert set(rows) == {10, 11}
    for key in ("id", "name", "avatar_url", "role", "games", "team_games", "avg_points", "total_points",
                "share", "owned_pct", "also_played", "accolades", "tags"):
        assert key in rows[10], key
    p = rows[10]
    assert (p["name"], p["avatar_url"], p["role"]) == ("P10", "https://cdn.example/a10.png", "Support")
    assert rows[11]["role"] == "Core"
    # No managers: below OWNERSHIP_MIN_MANAGERS, so ownership is withheld.
    assert (p["games"], p["team_games"], p["also_played"], p["owned_pct"]) == (2, 2, False, None)
    assert p["total_points"] == display_points(pts[10])
    assert p["avg_points"] == display_points(pts[10] / 2)
    assert p["share"] == display_points(100 * pts[10] / (pts[10] + pts[11]))


def test_get_team_players_default_order_by_total_points(db):
    """Backend: players are ordered by total_points descending."""
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    for pid, kills in ((10, 2), (11, 12), (12, 7), (13, 0), (14, 20)):
        _stat(db, pid, 1, kills=kills)
    players = _get(db, "/teams/1")["players"]
    assert [p["id"] for p in players] == [14, 11, 12, 10, 13]
    totals = [p["total_points"] for p in players]
    assert totals == sorted(totals, reverse=True)


def test_get_team_players_share_sums_to_100(db):
    """Backend: the players' share values sum to 100 % (within rounding) when the team has scored points."""
    _weights(db)
    _seed_teams(db)
    for mid in (1, 2, 3):
        _match(db, mid)
        for pid, kills in ((10, 3), (11, 7), (12, 1), (13, 11), (14, 5)):
            _stat(db, pid, mid, kills=kills + mid)
    shares = [p["share"] for p in _get(db, "/teams/1")["players"]]
    assert len(shares) == 5
    assert abs(sum(shares) - 100) <= 0.25


def test_get_team_players_also_played_under_30_percent_of_team_games(db):
    """Backend: also_played is true below 30 % of team_games and false at exactly 30 % and above."""
    _weights(db)
    _seed_teams(db)
    for mid in range(1, 11):          # 10 team games
        _match(db, mid)
        _stat(db, 10, mid)
        if mid <= 3:
            _stat(db, 11, mid)        # 3 / 10 = 30 %: a regular
        if mid <= 2:
            _stat(db, 12, mid)        # 2 / 10 = 20 %: also played
    rows = {p["id"]: p for p in _get(db, "/teams/1")["players"]}
    assert {pid: (p["games"], p["team_games"], p["also_played"]) for pid, p in rows.items()} == \
        {10: (10, 10, False), 11: (3, 10, False), 12: (2, 10, True)}


def test_get_team_owned_pct_counts_full_non_tester_users_with_active_cards(db, monkeypatch):
    """Backend: owned_pct = % of full, non-tester users with at least one active card who hold an active card of the player."""
    _min_managers(monkeypatch, 1)
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    for pid in (10, 11, 12):
        _stat(db, pid, 1)
    db.add(Player(id=50, name="Elsewhere"))
    db.commit()
    for uid in (1, 2, 3):
        _user(db, uid)
    _card(db, 1, 10)
    _card(db, 2, 11)
    _card(db, 3, 10)
    _card(db, 3, 50)
    owned = {p["id"]: p["owned_pct"] for p in _get(db, "/teams/1")["players"]}
    assert owned == {10: round(100 * 2 / 3), 11: round(100 * 1 / 3), 12: 0}


def test_get_team_owned_pct_excludes_soft_tester_and_inactive_cards(db, monkeypatch):
    """Backend: soft (twitch) accounts, testers, users with no active card and inactive (bench) cards don't count in numerator or denominator."""
    _min_managers(monkeypatch, 1)
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    for pid in (10, 11):
        _stat(db, pid, 1)
    _user(db, 1)
    _user(db, 2)
    _card(db, 1, 10)
    _card(db, 2, 11)
    baseline = {p["id"]: p["owned_pct"] for p in _get(db, "/teams/1")["players"]}
    assert baseline == {10: 50, 11: 50}
    _user(db, 3, account_type="twitch")
    _card(db, 3, 10)
    _user(db, 4, tester=True)
    _card(db, 4, 10)
    _user(db, 5)
    _card(db, 5, 10, active=False)        # bench card only: not a manager, not a holder
    _user(db, 6)                           # no cards at all
    _user(db, 7, demo=True)
    _card(db, 7, 10)
    _card(db, 2, 10, active=False)        # a manager's bench card of player 10 doesn't count
    after = {p["id"]: p["owned_pct"] for p in _get(db, "/teams/1")["players"]}
    assert after == baseline


def test_get_team_owned_pct_zero_without_managers(db, monkeypatch):
    """Backend: with no qualifying managers owned_pct is 0 (no division by zero)."""
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _stat(db, 10, 1)
    _user(db, 1, tester=True)
    _card(db, 1, 10)
    # Default threshold: no managers is below OWNERSHIP_MIN_MANAGERS, so ownership is hidden.
    body = _get(db, "/teams/1")
    assert [p["owned_pct"] for p in body["players"]] == [None] and body["ownership_hidden"] is True
    # With no threshold, zero managers still gives 0 rather than a division by zero.
    _min_managers(monkeypatch, 0)
    import team_insights
    team_insights.clear_league_cache()
    body = _get(db, "/teams/1")
    assert [p["owned_pct"] for p in body["players"]] == [0] and body["ownership_hidden"] is False


def test_get_team_owned_pct_hidden_below_min_managers(db):
    """Security review: below OWNERSHIP_MIN_MANAGERS (10) managers every owned_pct is null and ownership_hidden is true; at 10 the percentages show."""
    import team_insights
    assert team_insights.OWNERSHIP_MIN_MANAGERS == 10
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _stat(db, 10, 1)
    _stat(db, 11, 1)
    for uid in range(1, 10):          # 9 managers, all holding player 10
        _user(db, uid)
        _card(db, uid, 10)
    body = _get(db, "/teams/1")
    assert body["ownership_hidden"] is True
    assert [p["owned_pct"] for p in body["players"]] == [None, None]
    _user(db, 10)                     # the 10th manager holds player 11
    _card(db, 10, 11)
    body = _get(db, "/teams/1")
    assert body["ownership_hidden"] is False
    assert {p["id"]: p["owned_pct"] for p in body["players"]} == {10: 90, 11: 10}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_get_team_response_has_no_user_identities(db, monkeypatch):
    """Backend: no key or value in GET /teams/{id} or GET /teams exposes user ids, usernames or owner ids."""
    from models import TagDefinition, User, UserTag
    _min_managers(monkeypatch, 1)
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _stat(db, 10, 1)
    _user(db, 41, username="secret_manager_name")
    _user(db, 42, username="other_secret_name")
    _card(db, 41, 10)
    _card(db, 42, 10)
    _champion(db, "Season 16", "div1", "Reds")
    _champion(db, "Season 16", None, None, pid=10, kind="most_points")
    db.add(TagDefinition(id=1, key="caster", label="Caster"))
    db.commit()
    db.add(UserTag(user_id=41, tag_id=1))
    db.commit()
    for path in ("/teams/1", "/teams"):
        body = _get(db, path)
        dumped = json.dumps(body)
        assert "secret_manager_name" not in dumped and "other_secret_name" not in dumped
        assert "u41@example.com" not in dumped
        forbidden = {"user_id", "user_ids", "owner_id", "owner_ids", "username", "usernames", "users",
                     "owners", "email", "created_by"}
        assert not forbidden & set(_keys(body)), path
    assert _get(db, "/teams/1")["players"][0]["owned_pct"] == 100
    assert db.query(User).count() == 2


def test_team_popup_roster_row_shows_games_share_bar_and_owned_pct():
    """Node harness: a roster row shows player link, role chip, pips, "12 / 13", average, total, a share bar with its percentage and "Owned by N %"."""
    html = _render()["teamModalRoster"]["html"]
    rows = _by_class(html, "team-roster-row")
    assert len(rows) == 4
    alice = rows[0]
    assert _squash(alice["text"]).startswith("Alice")
    cells = {(e["attrs"].get("class") or ""): _squash(e["text"]) for e in _parse(html).els if e["tag"] == "td"}
    bob = [e for e in _parse(html).els if e["tag"] == "td" and "tr-games" in e["attrs"].get("class", "")]
    assert [_squash(e["text"]) for e in bob][:2] == ["13 / 13", "12 / 13"]
    assert cells  # parsed
    by_cls = lambda cls: [_squash(e["text"]) for e in _parse(html).els  # noqa: E731
                          if e["tag"] == "td" and cls in e["attrs"].get("class", "")]
    assert by_cls("tr-role")[:2] == ["Core", "Support"]
    assert by_cls("tr-avg")[0] == "20.5" and by_cls("tr-total")[0] == "266.5"
    assert by_cls("tr-share")[0] == "40.1 %"
    assert by_cls("tr-owned")[:2] == ["Owned by 25 %", "Owned by 50 %"]
    fills = _by_class(html, "team-share-fill")
    assert fills[0]["attrs"]["style"] == "--w: 40.1%"
    links = [e for e in _parse(html).els if "entity-link" in (e["attrs"].get("class") or "")]
    assert links[0]["attrs"]["onclick"] == "closeTeamModal();openPlayerModal(10)" and links[0]["text"] == "Alice"
    assert _by_class(html, "player-role-chip")
    # Alice's pips: the caster tag pip first, then the Div 1 champion accolade pip.
    pips = [e["attrs"]["class"] for e in _parse(html).els
            if "card-tag-pip" in (e["attrs"].get("class") or "").split()
            or "accolade-pip" in (e["attrs"].get("class") or "").split()]
    assert pips[0].startswith("card-tag-pip card-tag-pip--caster")
    assert "accolade-pip--div1" in pips[1]
    # Ownership withheld (too few managers): "—", sorted last, and the note says why.
    t = _T(ownership_hidden=True)
    t["players"] = [dict(p, owned_pct=None) for p in t["players"]]
    hidden = _render(t)["teamModalRoster"]["html"]
    owned = [_squash(e["text"]) for e in _parse(hidden).els
             if e["tag"] == "td" and "tr-owned" in e["attrs"].get("class", "")]
    assert owned == ["—"] * 4
    assert "shows once at least 10 managers have cards" in _text(hidden)
    mixed = _T()
    mixed["players"][0]["owned_pct"] = None
    out = _js(f"""
      renderTeamPopup({json.dumps(mixed)});
      sortTeamRoster("owned_pct"); const desc = document.getElementById("teamModalRoster").innerHTML;
      sortTeamRoster("owned_pct"); out = [desc, document.getElementById("teamModalRoster").innerHTML];
    """)
    assert _roster_names(out[0])[:3] == ["Bob", "Dan", "Alice"]
    assert _roster_names(out[1])[:3] == ["Dan", "Bob", "Alice"]


def _roster_names(html):
    return [e["text"] for e in _parse(html).els if "entity-link" in (e["attrs"].get("class") or "")]


def test_team_popup_roster_columns_sort():
    """Node harness: clicking a roster column header re-sorts rows (default total points descending; toggles direction)."""
    out = _js(f"""
      renderTeamPopup({json.dumps(_T())});
      const snap = () => document.getElementById("teamModalRoster").innerHTML;
      out = [snap()];
      sortTeamRoster("name"); out.push(snap());
      sortTeamRoster("name"); out.push(snap());
      sortTeamRoster("games"); out.push(snap());
      sortTeamRoster("games"); out.push(snap());
    """)
    names = [_roster_names(h) for h in out]
    # The also-played group (Cara) stays under its heading in every order.
    assert names[0] == ["Alice", "Bob", "Dan", "Cara"]
    assert names[1] == ["Alice", "Bob", "Dan", "Cara"]          # name ascending
    assert names[2] == ["Dan", "Bob", "Alice", "Cara"]          # name descending
    assert names[3][:3] in (["Alice", "Dan", "Bob"], ["Dan", "Alice", "Bob"])   # games descending
    assert names[4][:3] == ["Bob", "Alice", "Dan"]              # games ascending
    heads = [e for e in _parse(out[0]).els if e["tag"] == "th" and e["attrs"].get("data-col")]
    assert [h["attrs"]["data-col"] for h in heads] == ["name", "role", "games", "avg_points", "total_points",
                                                       "share", "owned_pct"]
    total = next(h for h in heads if h["attrs"]["data-col"] == "total_points")
    assert "sort-desc" in total["attrs"]["class"] and total["attrs"]["aria-sort"] == "descending"
    assert all(h["attrs"]["onclick"] == f"sortTeamRoster('{h['attrs']['data-col']}')" for h in heads)
    name_head = next(h for h in _parse(out[1]).els if h["tag"] == "th" and h["attrs"].get("data-col") == "name")
    assert name_head["attrs"]["aria-sort"] == "ascending"


def test_team_popup_also_played_heading_groups_low_game_players():
    """Node harness: also_played players render after an "Also played" heading; with none, the heading is absent."""
    html = _render()["teamModalRoster"]["html"]
    groups = _by_class(html, "team-roster-group")
    assert [_squash(g["text"]) for g in groups] == ["Also played"]
    assert html.index("Also played") < html.index(">Cara<")
    assert html.index(">Dan<") < html.index("Also played")
    t = _T()
    t["players"] = [p for p in t["players"] if not p["also_played"]]
    html = _render(t)["teamModalRoster"]["html"]
    assert "Also played" not in html and not _by_class(html, "team-roster-group")


# ===========================================================================
# Story 3: Where the Team's Points Come From
# ===========================================================================

def _breakdowns(db, team):
    import player_insights
    from card_points import _current_weights
    weights = _current_weights(db)
    rows = (db.query(PlayerMatchStats).join(Match, Match.match_id == PlayerMatchStats.match_id)
            .filter(PlayerMatchStats.team_id == team, Match.excluded_from_scoring == False).all())  # noqa: E712
    return [player_insights.points_by_source({c: getattr(r, c) for c in player_insights._STAT_COLS},
                                             weights, bool(r.is_mvp)) for r in rows], rows, weights


def test_get_team_points_sources_sum_over_players_per_game_with_league_avg(db):
    """Backend: points_sources has the #208 source groups, each the team's per-game sum (player_insights.points_by_source) with share and the average team's value."""
    import player_insights
    from scoring import display_points
    _weights(db)
    _seed_teams(db)
    for mid in (1, 2):
        _match(db, mid)
        _stat(db, 10, mid, kills=4 + mid, mvp=(mid == 1))
        _stat(db, 11, mid, obs_placed=6, gold_per_min=320.0)
        _stat(db, 20, mid, team=2, kills=15)
    mine, _, _ = _breakdowns(db, 1)
    theirs, _, _ = _breakdowns(db, 2)
    team = {k: sum(b[k] for b in mine) / 2 for k in player_insights.SOURCE_KEYS}
    league = {k: (sum(b[k] for b in mine) + sum(b[k] for b in theirs)) / 4   # 4 team games
              for k in player_insights.SOURCE_KEYS}
    total = sum(team.values())
    sources = _get(db, "/teams/1")["points_sources"]
    assert [s["key"] for s in sources] == player_insights.SOURCE_KEYS
    assert [s["label"] for s in sources] == [lbl for _, lbl, _ in player_insights.SOURCE_GROUPS]
    for s in sources:
        assert s["avg"] == display_points(team[s["key"]], 2), s["key"]
        assert s["share"] == display_points(100 * team[s["key"]] / total), s["key"]
        assert s["league_avg"] == display_points(league[s["key"]], 2), s["key"]
    assert next(s for s in sources if s["key"] == "mvp_bonus")["avg"] > 0


def test_get_team_points_sources_empty_without_scored_matches(db):
    """Backend: with no scored matches every source avg is 0 and modifier_values stats are empty."""
    _weights(db)
    _seed_teams(db)
    _match(db, 1, excluded=True)
    _stat(db, 10, 1)
    body = _get(db, "/teams/1")
    assert len(body["points_sources"]) == 12
    assert all(s["avg"] == 0 and s["share"] == 0 for s in body["points_sources"])
    assert body["modifier_values"]["stats"] == []
    assert body["modifier_values"]["bonus_pct"] == 10.0


def test_get_team_modifier_values_top_three_from_team_totals(db):
    """Backend: modifier_values lists stats by the value of a +10 % modifier on the team's totals; the top three lead in descending order."""
    import player_insights
    from scoring import display_points
    _weights(db)
    _seed_teams(db)
    for mid in (1, 2, 3):
        _match(db, mid)
        _stat(db, 10, mid, kills=12, gold_per_min=700.0)
        _stat(db, 11, mid, assists=25, obs_placed=8)
    _, rows, weights = _breakdowns(db, 1)
    sums = {}
    for r in rows:
        for k, v in player_insights.stat_points({c: getattr(r, c) for c in player_insights._STAT_COLS},
                                                weights).items():
            sums[k] = sums.get(k, 0.0) + v
    pct = weights.get("modifier_bonus_pct", 10.0)
    expected = sorted(((k, display_points(v / 3 * pct / 100, 2)) for k, v in sums.items()),
                      key=lambda kv: kv[1], reverse=True)
    mv = _get(db, "/teams/1")["modifier_values"]
    assert mv["bonus_pct"] == pct
    got = [(s["stat"], s["value"]) for s in mv["stats"]]
    assert [v for _, v in got] == sorted((v for _, v in got), reverse=True)
    assert [v for _, v in got[:3]] == [v for _, v in expected[:3]]
    assert {k for k, _ in got[:3]} == {k for k, _ in expected[:3]}
    assert all(s["label"] for s in mv["stats"])


def test_get_team_heroes_top_six_with_wl_and_players(db, monkeypatch):
    """Backend: heroes is at most six rows by games descending, each with hero_id, hero_name, icon_url, games, wins, losses and the players who played it."""
    import schedule
    monkeypatch.setattr(schedule, "cached_hero_maps",
                        lambda: ({1: "https://cdn.example/axe.png"}, {1: "Axe", 2: "Lion"}))
    _weights(db)
    _seed_teams(db)
    _match(db, 1, rw=True)
    _match(db, 2, rw=False)
    _match(db, 3, rw=True)
    _stat(db, 10, 1, hero=1)
    _stat(db, 10, 2, hero=1)
    _stat(db, 11, 3, hero=1)
    _stat(db, 11, 1, hero=2)
    _stat(db, 11, 2, hero=2)
    for i, hero in enumerate((3, 4, 5, 6, 7)):
        _stat(db, 12 + i, 3, hero=hero)
    _stat(db, 20, 1, team=2, hero=9)
    heroes = _get(db, "/teams/1")["heroes"]
    assert len(heroes) == 6
    assert [h["games"] for h in heroes] == sorted((h["games"] for h in heroes), reverse=True)
    axe = heroes[0]
    assert (axe["hero_id"], axe["hero_name"], axe["icon_url"]) == (1, "Axe", "https://cdn.example/axe.png")
    assert (axe["games"], axe["wins"], axe["losses"]) == (3, 2, 1)
    assert axe["players"] == [{"id": 10, "name": "P10", "games": 2}, {"id": 11, "name": "P11", "games": 1}]
    lion = heroes[1]
    assert (lion["hero_id"], lion["hero_name"], lion["icon_url"], lion["games"], lion["wins"], lion["losses"]) == \
        (2, "Lion", None, 2, 1, 1)
    assert 9 not in [h["hero_id"] for h in heroes]


def test_team_popup_sources_bar_has_average_team_ticks_and_no_scoring_maths():
    """Node harness + source-reading: the stacked bar renders one segment per non-zero source with an average-team tick, the modifier sentence names the top three, and app-team-popup.js holds no weights/scoring formula."""
    html = _render()["teamModalSources"]["html"]
    bar = _by_class(html, "sources-bar")[0]
    segs = _by_class(html, "sources-seg")
    in_bar = [s for s in segs if s["tag"] == "span" and "sources-swatch" not in s["attrs"]["class"]]
    # Seven non-zero sources: five coloured segments and one "Other".
    assert len(in_bar) == 6
    assert "sources-seg--other" in in_bar[-1]["attrs"]["class"]
    assert "Kills" in bar["attrs"]["aria-label"]
    rows = _by_class(html, "sources-row")
    assert len(rows) == 7
    assert len(_by_class(html, "sources-league")) == 7
    assert "average team" in _text(html)
    line = _by_class(html, "modifier-line")
    assert [_squash(e["text"]) for e in line] == \
        ["A +10 % modifier pays most on this team's players: Kills, GPM, Assists"]
    src = _fe("app-team-popup.js")
    for banned in ("weight", "fantasy_score", "mvp_bonus_pct", "death_pool", "_death"):
        assert banned not in src, banned


def test_team_popup_heroes_section_lists_games_wl_and_players():
    """Node harness: the heroes section shows icon, name, games, W-L and the players for each hero."""
    html = _render()["teamModalHeroes"]["html"]
    tiles = _by_class(html, "hero-tile")
    assert len(tiles) == 2
    imgs = [e for e in _parse(html).els if e["tag"] == "img"]
    assert imgs[0]["attrs"]["src"] == "https://cdn.example/axe.png"
    assert [_squash(e["text"]) for e in _by_class(html, "hero-tile-name")] == ["Axe", "Lion"]
    assert [_squash(e["text"]) for e in _by_class(html, "hero-tile-stats")] == ["4 games · 3–1", "2 games · 1–1"]
    assert [_squash(e["text"]) for e in _by_class(html, "hero-tile-players")] == ["Alice (3), Bob", "Bob <i> (2)"]
    assert "<i>" not in html
    assert _by_class(html, "hero-icon-placeholder")


# ===========================================================================
# Story 4: Teams Tab Ranks Teams
# ===========================================================================

def test_list_teams_rows_have_logo_division_records_ppg_players_titles(db, monkeypatch):
    """Backend: each GET /teams row has id, name, logo_url, division, series_wins/series_losses, game wins/losses, points_per_game, player_count and titles."""
    from scoring import display_points
    monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
    _weights(db)
    _seed_teams(db)
    db.get(Team, 1).logo_url = _LOGO
    db.add(Team(id=3, name="Greens"))
    db.commit()
    _league(db, 1, "Kanaliiga Season 17")
    _league(db, 2, "Kanaliiga Season 17 Lower")
    pts = 0.0
    _match(db, 1, league_id=1)
    _match(db, 2, rw=False, league_id=1)
    for mid in (1, 2):
        pts += _stat(db, 10, mid) + _stat(db, 11, mid)
        _stat(db, 20, mid, team=2)
    _match(db, 3, radiant=3, dire=2, league_id=2)   # Blues play one Div 2 game: still mostly Div 1
    _champion(db, "Season 16", "div1", "reds")
    _feed(monkeypatch, [_week("Week 1", div1=[_series("Reds", "Blues", 1, 2, (2, 0, _BASE_TS, [1, 2]))])])
    rows = {r["id"]: r for r in _get(db, "/teams")}
    reds = rows[1]
    assert reds["name"] == "Reds" and reds["logo_url"] == _LOGO
    assert reds["division"] == "div1"
    assert (reds["series_wins"], reds["series_losses"]) == (1, 0)
    assert (reds["wins"], reds["losses"], reds["matches"]) == (1, 1, 2)
    assert reds["points_per_game"] == display_points(pts / 2)
    assert reds["player_count"] == 2
    assert [t["label"] for t in reds["titles"]] == ["S16 Div 1 Champion"]
    assert (rows[2]["series_wins"], rows[2]["series_losses"]) == (0, 1)
    assert rows[2]["division"] == "div1" and rows[3]["division"] == "div2"
    assert rows[2]["logo_url"] is None
    assert rows[3]["player_count"] == 0 and rows[3]["points_per_game"] == 0
    # Default order: division, then series wins.
    assert [r["id"] for r in _get(db, "/teams")] == [1, 2, 3]


def test_list_teams_excluded_matches_left_out_of_records(db):
    """Backend: excluded matches don't count in a GET /teams row's games record or points_per_game."""
    from scoring import display_points
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    pts = _stat(db, 10, 1)
    _match(db, 2, rw=False, excluded=True)
    _stat(db, 10, 2, kills=50)
    _stat(db, 12, 2)
    reds = next(r for r in _get(db, "/teams") if r["id"] == 1)
    assert (reds["wins"], reds["losses"], reds["matches"]) == (1, 0, 1)
    assert reds["points_per_game"] == display_points(pts)
    assert reds["player_count"] == 1


def test_teams_tab_table_columns_in_index_html():
    """Source-reading (html.parser): the Teams tab table has headers Team, Division, Series W-L, Games W-L, Fantasy pts per game, Players, Titles."""
    els = _parse(_fe("index.html")).els
    start = next(i for i, e in enumerate(els) if e["attrs"].get("id") == "teamsTableHead")
    end = next(i for i, e in enumerate(els) if e["attrs"].get("id") == "teamsBody")
    ths = [e for e in els[start:end] if e["tag"] == "th"]
    assert [_squash(e["text"]).replace("–", "-") for e in ths] == \
        ["Team", "Division", "Series W-L", "Games W-L", "Fantasy pts per game", "Players", "Titles"]
    assert [e["attrs"].get("data-col") for e in ths] == \
        ["name", "division", "series_wins", "wins", "points_per_game", "player_count", "titles_count"]
    chips = [e for e in els if e["attrs"].get("data-teams-filter")]
    assert [(c["attrs"]["data-teams-filter"], _squash(c["text"])) for c in chips] == \
        [("all", "All"), ("div1", "Div 1"), ("div2", "Div 2")]


def _team_row(tid, name, div, sw, sl=0, w=0, ppg=50.0, titles=None):
    return dict(id=tid, name=name, logo_url=None, division=div, series_wins=sw, series_losses=sl,
                series_draws=0, wins=w, losses=0, matches=w, points_per_game=ppg, player_count=5,
                titles=titles or [])


_TEAMS = [
    _team_row(1, "Alpha", "div2", 3, w=7, ppg=40.0),
    _team_row(2, "Bravo", "div1", 1, w=3, ppg=70.0),
    _team_row(3, "Charlie", "div1", 4, w=9, ppg=55.0,
              titles=[{"kind": "champion", "division": "div1", "season": "Season 16", "season_short": "S16",
                       "team_name": "Charlie", "label": "S16 Div 1 Champion"}]),
    _team_row(4, "Delta", "div2", 5, w=10, ppg=30.0),
    _team_row(5, "Echo", None, 0, ppg=0.0),
]


def _teams_names(html):
    return [e["text"] for e in _parse(html).els if "entity-link" in (e["attrs"].get("class") or "")]


def test_teams_tab_division_filter_chips():
    """Node harness: filter chips All, Div 1, Div 2 show only matching teams; All shows every team."""
    out = _js(f"""
      const chips = ["all", "div1", "div2"].map(f => {{ const c = new El(null); c.setAttribute("data-teams-filter", f); return c; }});
      __selectors[".players-filter-chip[data-teams-filter]"] = chips;
      _teamsData = {json.dumps(_TEAMS)};
      const body = () => document.getElementById("teamsBody").innerHTML;
      const state = () => chips.map(c => [c.classList.contains("active"), c.getAttribute("aria-pressed")]);
      out = {{}};
      setTeamsFilter("div1"); out.div1 = [body(), state()];
      setTeamsFilter("div2"); out.div2 = [body(), state()];
      setTeamsFilter("all"); out.all = [body(), state()];
      setTeamsFilter("bogus"); out.bogus = [body(), state()];
    """)
    assert _teams_names(out["div1"][0]) == ["Charlie", "Bravo"]
    assert out["div1"][1] == [[False, "false"], [True, "true"], [False, "false"]]
    assert _teams_names(out["div2"][0]) == ["Delta", "Alpha"]
    assert out["div2"][1] == [[False, "false"], [False, "false"], [True, "true"]]
    assert _teams_names(out["all"][0]) == ["Charlie", "Bravo", "Delta", "Alpha", "Echo"]
    assert out["all"][1][0] == [True, "true"]
    assert _teams_names(out["bogus"][0]) == _teams_names(out["all"][0])
    # Players-tab chips are left alone: setPlayersFilter only touches chips with data-filter.
    assert '.players-filter-chip[data-filter]' in _fn_source(_fe("app-players.js"), "setPlayersFilter")


def test_teams_tab_sorting_default_division_then_series_wins():
    """Node harness: default order is division then series wins descending; clicking a column header sorts by it."""
    out = _js(f"""
      const head = document.getElementById("teamsTableHead");
      head.children = ["name", "division", "series_wins", "wins", "points_per_game", "player_count", "titles_count"]
        .map(col => {{ const th = new El(null); th.setAttribute("data-col", col); if (col === "name" || col === "division") th.setAttribute("data-default-dir", "asc"); return th; }});
      __fetchBody = {json.dumps(_TEAMS)};
      await loadTeams();
      const body = () => document.getElementById("teamsBody").innerHTML;
      out = {{ initial: body(), status: __status.teamsStatus }};
      const th = col => head.children.find(t => t.getAttribute("data-col") === col);
      th("series_wins").onclick(); out.series = [body(), [...th("series_wins").cls]];
      th("series_wins").onclick(); out.seriesAsc = body();
      th("points_per_game").onclick(); out.ppg = body();
      th("name").onclick(); out.name = body();
      th("titles_count").onclick(); out.titles = body();
      await loadTeams(); out.refresh = body();
    """)
    assert _teams_names(out["initial"]) == ["Charlie", "Bravo", "Delta", "Alpha", "Echo"]
    assert out["status"] == {"msg": "5 teams", "ok": True}
    assert _teams_names(out["series"][0]) == ["Delta", "Charlie", "Alpha", "Bravo", "Echo"]
    assert "sort-desc" in out["series"][1] and "sortable" in out["series"][1]
    assert _teams_names(out["seriesAsc"]) == ["Echo", "Bravo", "Alpha", "Charlie", "Delta"]
    assert _teams_names(out["ppg"]) == ["Bravo", "Charlie", "Alpha", "Delta", "Echo"]
    assert _teams_names(out["name"]) == ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    assert _teams_names(out["titles"])[0] == "Charlie"
    # The chosen sort survives a refresh (issue #159).
    assert out["refresh"] == out["titles"]
    row = _by_class(out["initial"], "accolade-swap")[0]
    assert "S16 Div 1 Champion" in row["text"]
    cells = [e for e in _parse(out["initial"]).els if e["tag"] == "td"][:7]
    assert [e["attrs"].get("data-label") for e in cells] == \
        ["Team", "Division", "Series W–L", "Games W–L", "Pts per game", "Players", "Titles"]
    assert [_squash(e["text"]) for e in cells][1:6] == ["Div 1", "4–0", "9–0", "55.0", "5"]


def _issue_211_css():
    css = _fe("style.css")
    start = css.index("TEAM POPUP AND TEAMS TAB (issue 211)")
    end = css.index("GUIDED TOUR (issue #144)")
    assert start < end
    return css[start:end]


def test_teams_tab_phone_width_stacked_rows():
    """Source-reading: style.css has a narrow-width media rule turning the Teams table into stacked rows with no horizontal overflow, before GUIDED TOUR, using tokens only."""
    import re
    css = _issue_211_css()
    media = css[css.index("@media (max-width: 640px)"):]
    for rule in (".teams-table thead { display: none; }", ".teams-table tr {", "display: grid;",
                 "content: attr(data-label)", "overflow-wrap: anywhere;"):
        assert rule in media, rule
    assert "overflow-x: auto" not in media
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert "rgb(" not in css and "rgba(" not in css
    assert "#211" not in css


# ===========================================================================
# Cross-cutting: feed safety, caching, #171 logo allowlist
# ===========================================================================

def _boom(db):
    raise RuntimeError("feed down")


def test_get_team_schedule_feed_down_returns_200_with_empty_series(db, monkeypatch):
    """Backend: when schedule.get_schedule raises, GET /teams/{id} answers 200 with empty series and upcoming, games record from matches, roster, sources and heroes intact."""
    import schedule
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _match(db, 2, rw=False)
    for mid in (1, 2):
        _stat(db, 10, mid, hero=1)
        _stat(db, 11, mid, hero=2)
    monkeypatch.setattr(schedule, "get_schedule", _boom)
    body = _get(db, "/teams/1")
    assert body["series"] == [] and body["upcoming"] == []
    s = body["summary"]
    assert (s["series_wins"], s["series_losses"]) == (0, 0)
    assert (s["games"], s["wins"], s["losses"]) == (2, 1, 1)
    assert [p["id"] for p in body["players"]] and len(body["players"]) == 2
    assert any(src["avg"] > 0 for src in body["points_sources"])
    assert [h["hero_id"] for h in body["heroes"]] == [1, 2] or [h["hero_id"] for h in body["heroes"]] == [2, 1]
    # An error payload (no weeks) is just as safe.
    monkeypatch.setattr(schedule, "get_schedule", lambda db: {"weeks": None, "error": "Schedule unavailable"})
    assert _get(db, "/teams/1")["series"] == []


def test_list_teams_schedule_feed_down_returns_200(db, monkeypatch):
    """Backend: when schedule.get_schedule raises, GET /teams answers 200 with series records zeroed and games records from matches."""
    import schedule
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _stat(db, 10, 1)
    monkeypatch.setattr(schedule, "get_schedule", _boom)
    rows = {r["id"]: r for r in _get(db, "/teams")}
    assert (rows[1]["series_wins"], rows[1]["series_losses"]) == (0, 0)
    assert (rows[1]["wins"], rows[1]["losses"]) == (1, 0)
    assert (rows[2]["wins"], rows[2]["losses"]) == (0, 1)


def _count_league_numbers(monkeypatch):
    import team_insights
    calls = []
    real = team_insights.league_numbers

    def counting(db, weights):
        calls.append(1)
        return real(db, weights)
    monkeypatch.setattr(team_insights, "league_numbers", counting)
    return calls


def test_team_league_numbers_cached_across_requests(db, monkeypatch):
    """Backend: two GET /teams/{id} requests with unchanged data compute the average-team sources / ownership denominator once (versioned in-process cache)."""
    _min_managers(monkeypatch, 1)
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _stat(db, 10, 1)
    _stat(db, 20, 1, team=2)
    _user(db, 1)
    _card(db, 1, 10)
    calls = _count_league_numbers(monkeypatch)
    first = _get(db, "/teams/1")
    second = _get(db, "/teams/1")
    _get(db, "/teams/2")
    assert len(calls) == 1
    assert first == second
    # A change to the active cards is a new version (ownership is recomputed).
    _user(db, 2)
    _card(db, 2, 20)
    assert _get(db, "/teams/1")["players"][0]["owned_pct"] == 50
    assert len(calls) == 2


def test_team_league_cache_invalidated_when_data_changes(db, monkeypatch):
    """Backend: after a new match is added the cached league numbers are recomputed."""
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _stat(db, 10, 1)
    _stat(db, 20, 1, team=2)
    calls = _count_league_numbers(monkeypatch)
    before = {s["key"]: s["league_avg"] for s in _get(db, "/teams/1")["points_sources"]}
    _match(db, 2)
    _stat(db, 10, 2, kills=40)
    _stat(db, 20, 2, team=2, kills=40)
    after = {s["key"]: s["league_avg"] for s in _get(db, "/teams/1")["points_sources"]}
    assert len(calls) == 2
    assert after["kills"] > before["kills"]
    # Excluding a match is a data change too.
    m = db.get(Match, 2)
    m.excluded_from_scoring = True
    db.commit()
    again = {s["key"]: s["league_avg"] for s in _get(db, "/teams/1")["points_sources"]}
    assert len(calls) == 3 and again == before


def test_team_logo_urls_only_from_allowlisted_hosts(db, monkeypatch):
    """Backend: logo_url in GET /teams, GET /teams/{id} and series opponents passes through logo_hosts.safe_logo_url (unknown host -> null)."""
    monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
    _weights(db)
    _seed_teams(db)
    db.get(Team, 1).logo_url = _EVIL
    db.get(Team, 2).logo_url = _LOGO2
    db.add(Team(id=3, name="Greens", logo_url="http://steamcdn-a.akamaihd.net/x.png"))   # not https
    db.commit()
    _feed(monkeypatch, [_week("Week 1", div1=[
        _series("Reds", "Blues", 1, 2, (2, 0, _BASE_TS, [1, 2])),
        _series("Greens", "Blues", 3, 2, dt="2099-01-01T19:00:00"),
    ])])
    rows = {r["id"]: r for r in _get(db, "/teams")}
    assert (rows[1]["logo_url"], rows[2]["logo_url"], rows[3]["logo_url"]) == (None, _LOGO2, None)
    reds = _get(db, "/teams/1")
    assert reds["logo_url"] is None
    assert reds["series"][0]["opponent"]["logo_url"] == _LOGO2
    blues = _get(db, "/teams/2")
    assert blues["logo_url"] == _LOGO2
    assert blues["series"][0]["opponent"]["logo_url"] is None
    assert blues["upcoming"][0]["opponent"]["logo_url"] is None
    for body in (rows, reds, blues, _get(db, "/teams/3")):
        dumped = json.dumps(body)
        assert "evil.example" not in dumped and "http://steamcdn" not in dumped


def _count_team_list(monkeypatch):
    import team_insights
    calls = []
    real = team_insights.team_list

    def counting(db, data=None):
        calls.append(1)
        return real(db, data)
    monkeypatch.setattr(team_insights, "team_list", counting)
    return calls


def test_list_teams_cached_across_requests(db, monkeypatch):
    """Security review: a second GET /teams with unchanged data, weights and feed reuses the cached list."""
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _stat(db, 10, 1)
    feed = _feed(monkeypatch, [_week("Week 1", div1=[_series("Reds", "Blues", 1, 2, (1, 0, _BASE_TS, [1]))])])
    feed["cached_at"] = "2026-10-18T10:00:00"
    calls = _count_team_list(monkeypatch)
    first = _get(db, "/teams")
    assert _get(db, "/teams") == first
    assert len(calls) == 1
    # A refreshed feed (new cached_at) is a new version.
    feed["cached_at"] = "2026-10-18T11:00:00"
    _get(db, "/teams")
    assert len(calls) == 2


def test_list_teams_cache_invalidated_when_data_changes(db, monkeypatch):
    """Security review: a new match, an exclusion or a renamed team recomputes the cached GET /teams list."""
    _weights(db)
    _seed_teams(db)
    _match(db, 1)
    _stat(db, 10, 1)
    calls = _count_team_list(monkeypatch)
    reds = lambda: next(r for r in _get(db, "/teams") if r["id"] == 1)  # noqa: E731
    assert (reds()["wins"], len(calls)) == (1, 1)
    _match(db, 2, rw=False)                 # a match without stats still changes the record
    assert (reds()["losses"], len(calls)) == (1, 2)
    db.get(Match, 2).excluded_from_scoring = True
    db.commit()
    assert (reds()["losses"], len(calls)) == (0, 3)
    db.get(Team, 1).name = "Reds Renamed"
    db.commit()
    assert (reds()["name"], len(calls)) == ("Reds Renamed", 4)


def test_list_teams_games_records_in_one_pass():
    """Security review: team_list computes every team's games record in one pass (games_records), not per team."""
    import team_insights
    src = _fn_source_py(team_insights.team_list)
    assert "games_records(" in src and "games_record(" not in src.replace("games_records(", "")
    recs = team_insights.games_records([
        {"radiant_team_id": 1, "dire_team_id": 2, "radiant_win": True, "duration": 1800},
        {"radiant_team_id": 2, "dire_team_id": 1, "radiant_win": True, "duration": 2000},
        {"radiant_team_id": 3, "dire_team_id": None, "radiant_win": None, "duration": None},
    ])
    assert recs[1] == {"games": 2, "wins": 1, "losses": 1, "avg_game_length": 1900}
    assert recs[2] == {"games": 2, "wins": 1, "losses": 1, "avg_game_length": 1900}
    assert recs[3] == {"games": 1, "wins": 0, "losses": 0, "avg_game_length": None}
    assert None not in recs


def _fn_source_py(fn):
    import inspect
    return inspect.getsource(fn)
