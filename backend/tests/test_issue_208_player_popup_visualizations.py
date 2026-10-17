"""
Tests for plan-issue-208-player-popup-visualizations.md (resolves GitHub issue #208).

The player popup turns its season of per-match data into views: a form chart,
points by source (with modifier value), league percentile strips, heroes played,
and a history table with per-match Details. #50's popup pieces (`#playerModalPips`,
`renderPlayerAccolades`, the accolade tooltip) are reused; the tooltip is
generalised from `data-accolade-tip` to `data-tip`.

  Story 1: Season Form at a Glance
  Story 2: Where a Player's Points Come From
  Story 3: Compared with the League
  Story 4: Heroes Played
  Story 5: Match Details on Demand
  #50 reuse: tooltip generalisation, pips and Accolades section kept

Approach notes (for the developer filling these in):

- Backend: `GET /players/{id}` lives in `backend/routers/players.py`; new helpers
  go in `backend/player_insights.py`. Use the `db` fixture below (shared
  StaticPool connection) and `_client(db)` so the TestClient's request thread sees
  seeded rows. Seed Player / Team / Match (`radiant_team_id`, `dire_team_id`,
  `radiant_win`, `duration`, `week_override_id`, `excluded_from_scoring`,
  `parse_status`) and PlayerMatchStats (`hero_id`, `sen_placed`, stats). Seed
  weights with `_weights(db)` (seed.DEFAULT_WEIGHTS) and read them through
  `card_points._current_weights(db)`. Compute expected points with
  `scoring.fantasy_score` rather than hard-coding numbers.
- Hero icons: `schedule._fetch_hero_icon_map()` calls OpenDota; always
  monkeypatch it (or its shared replacement) in tests.
- Week labels: seed `Week` rows and compare with `weeks.scoring_week_for`.
- Frontend "source-reading" stubs read `frontend/app-player-popup.js`,
  `app-globals.js`, `app-players.js`, `index.html`, `style.css` with `_read` /
  `_fe` / `_fn_body` / `_rule`. New CSS goes before "GUIDED TOUR (issue #144)".
- Frontend "Node harness" stubs extract render helpers from
  `app-player-popup.js` (plus `_escHtml` and the tooltip helpers from
  app-globals.js) and run them with `_run_node` (skips when Node is missing),
  using a fake DOM in the style of `_HARNESS` in
  test_issue_205_card_draw_animations.py / test_issue_186_my_team_save_roster.py.
  Re-add `async` when pasting extracted async functions (lessons-learned).

Run with: cd backend && python -m pytest tests/test_issue_208_player_popup_visualizations.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import re
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
from models import Weight

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


def _css_blocks(css, selector_re):
    """(selector, body) for every rule whose selector matches selector_re."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
            if re.search(selector_re, m.group(1))]


def _rule(css, selector):
    """Bodies of the rules whose selector list contains exactly `selector`."""
    return [body for sel, body in _css_blocks(css, re.escape(selector))
            if selector in [x.strip() for x in sel.split(",")]]


def _fn_body(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start)]


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


@pytest.fixture(autouse=True)
def _no_opendota(monkeypatch):
    """The hero icon map calls OpenDota: never let a test reach it. The popup only reads
    the cache (cold here) and would start a background warm-up, which is a no-op here.
    The league aggregates cache starts empty."""
    import player_insights
    import schedule
    monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
    monkeypatch.setattr(schedule, "warm_hero_maps_in_background", lambda: None)
    monkeypatch.setattr(schedule, "_hero_icon_cache", None)
    monkeypatch.setattr(schedule, "_hero_name_cache", {})
    player_insights.clear_league_cache()
    yield
    player_insights.clear_league_cache()


# ---------------------------------------------------------------------------
# Backend seeding
# ---------------------------------------------------------------------------

from models import Match, Player, PlayerMatchStats, Team, Week  # noqa: E402
import schedule as _schedule_module  # noqa: E402

_REAL_FETCH = _schedule_module._fetch_hero_icon_map
_REAL_WARM = _schedule_module.warm_hero_maps_in_background


def _real_fetch_hero_icon_map():
    return _REAL_FETCH()

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
           override=None, duration=1800):
    db.add(Match(match_id=mid, radiant_team_id=radiant, dire_team_id=dire, radiant_win=rw,
                 start_time=_BASE_TS + mid * 3600 if ts is None else ts, duration=duration,
                 excluded_from_scoring=excluded, parse_status=parse, week_override_id=override))
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


def _seed_player(db, pid=10, n=4, **stat_over):
    """Teams, `n` matches for player `pid` (radiant, all won) with weights."""
    if not db.query(Team).count():
        _seed_teams(db)
    if not db.query(Weight).count():
        _weights(db)
    for i in range(n):
        mid = pid * 100 + i
        _match(db, mid)
        _stat(db, pid, mid, **stat_over)


def _get(db, pid=10, **kw):
    res = _client(db).get(f"/players/{pid}", **kw)
    assert res.status_code == 200, res.text
    return res.json()


def _row(data, mid):
    return next(m for m in data["match_history"] if m["match_id"] == mid)


# ===========================================================================
# Story 1: Season Form at a Glance
# ===========================================================================

# --- Backend ---------------------------------------------------------------

def test_get_player_match_history_includes_hero_won_week_label_fields(db):
    """Each match_history row carries hero_id, hero_icon_url, won, duration, week_label, sen_placed and points_breakdown."""
    _seed_player(db, n=0)
    db.add(Week(id=1, label="Week 1", start_time=_BASE_TS, end_time=_BASE_TS + 10 ** 6))
    db.commit()
    _match(db, 1, duration=2100)
    _stat(db, 10, 1, hero=14)
    row = _get(db)["match_history"][0]
    for key in ("hero_id", "hero_icon_url", "won", "duration", "week_label", "sen_placed", "points_breakdown"):
        assert key in row, key
    assert row["hero_id"] == 14 and row["duration"] == 2100 and row["sen_placed"] == 1
    assert row["won"] is True and row["week_label"] == "W1"
    assert isinstance(row["points_breakdown"], dict) and "mvp_bonus" in row["points_breakdown"]


def test_get_player_won_true_when_player_side_won(db):
    """`won` is true when radiant_win matches the player's side (team_id == radiant_team_id, and the dire case)."""
    _seed_player(db, n=0)
    _match(db, 1, radiant=1, dire=2, rw=True)
    _stat(db, 10, 1, team=1)
    _match(db, 2, radiant=2, dire=1, rw=False)
    _stat(db, 10, 2, team=1)
    data = _get(db)
    assert _row(data, 1)["won"] is True
    assert _row(data, 2)["won"] is True


def test_get_player_won_false_when_player_side_lost(db):
    """`won` is false when the player's side lost (radiant player with radiant_win false, dire player with true)."""
    _seed_player(db, n=0)
    _match(db, 1, radiant=1, dire=2, rw=False)
    _stat(db, 10, 1, team=1)
    _match(db, 2, radiant=2, dire=1, rw=True)
    _stat(db, 10, 2, team=1)
    data = _get(db)
    assert _row(data, 1)["won"] is False
    assert _row(data, 2)["won"] is False


def test_get_player_won_null_when_radiant_win_unknown(db):
    """`won` is null when radiant_win is null or the player's side can't be determined."""
    _seed_player(db, n=0)
    _match(db, 1, rw=None)
    _stat(db, 10, 1, team=1)
    db.add(Team(id=3, name="Greens"))
    db.commit()
    _match(db, 2, radiant=2, dire=3, rw=True)  # player's team on neither side
    _stat(db, 10, 2, team=1)
    data = _get(db)
    assert _row(data, 1)["won"] is None
    assert _row(data, 2)["won"] is None
    assert data["summary"]["wins"] == 0 and data["summary"]["losses"] == 0


def test_get_player_week_label_uses_scoring_week(db):
    """`week_label` ("W3") comes from weeks.scoring_week_for for the match's start time."""
    import weeks
    _seed_player(db, n=0)
    db.add(Week(id=1, label="Week 1", start_time=_BASE_TS, end_time=_BASE_TS + 999))
    db.add(Week(id=3, label="Week 3", start_time=_BASE_TS + 1000, end_time=_BASE_TS + 10 ** 6))
    db.commit()
    _match(db, 1, ts=_BASE_TS + 5000)
    _stat(db, 10, 1)
    _match(db, 2, ts=_BASE_TS - 50)  # before every week
    _stat(db, 10, 2)
    data = _get(db)
    week, source = weeks.scoring_week_for(db, db.get(Match, 1))
    assert week.label == "Week 3" and source == "time"
    assert _row(data, 1)["week_label"] == "W3"
    assert _row(data, 2)["week_label"] is None


def test_get_player_week_label_honours_week_override_id(db):
    """A match with week_override_id gets the override week's label, not the start-time week."""
    _seed_player(db, n=0)
    db.add(Week(id=1, label="Week 1", start_time=_BASE_TS, end_time=_BASE_TS + 999))
    db.add(Week(id=2, label="Week 2", start_time=_BASE_TS + 1000, end_time=_BASE_TS + 10 ** 6))
    db.commit()
    _match(db, 1, ts=_BASE_TS + 5000, override=1)
    _stat(db, 10, 1)
    assert _row(_get(db), 1)["week_label"] == "W1"


def test_get_player_summary_wins_losses_mvps_avg_rank(db):
    """`summary` has wins, losses, MVPs and avg_rank {rank, of} among the comparison population."""
    _seed_player(db, n=0)
    _match(db, 1, rw=True)
    _stat(db, 10, 1, mvp=True, kills=20)
    _match(db, 2, rw=False)
    _stat(db, 10, 2, kills=20)
    _match(db, 3, rw=True)
    _stat(db, 10, 3, kills=20)
    for pid, kills in ((20, 1), (30, 40)):  # one weaker, one stronger player
        for i in range(3):
            _match(db, pid * 100 + i)
            _stat(db, pid, pid * 100 + i, kills=kills)
    s = _get(db)["summary"]
    assert (s["wins"], s["losses"], s["mvps"]) == (2, 1, 1)
    assert s["avg_rank"] == {"rank": 2, "of": 3}


def test_get_player_summary_avg_rank_null_below_population_threshold(db):
    """`summary.avg_rank` is null when the player has fewer than 3 scored matches (not in the population)."""
    _seed_player(db, n=2)
    _seed_player(db, pid=20, n=3)
    data = _get(db)
    assert data["summary"]["avg_rank"] is None
    assert _get(db, 20)["summary"]["avg_rank"] == {"rank": 1, "of": 1}


def test_get_player_returns_league_average_points_per_match(db):
    """The response carries the league average points per scored match for the form chart's dashed reference line."""
    from scoring import display_points
    _seed_player(db, n=0)
    pts = []
    for pid, kills in ((10, 2), (20, 8)):
        _match(db, pid)
        pts.append(_stat(db, pid, pid, kills=kills))
    _match(db, 99, excluded=True)
    _stat(db, 20, 99, kills=100)  # excluded: not in the league average
    assert _get(db)["league_avg_points"] == display_points(sum(pts) / 2)


def test_get_player_excluded_match_kept_in_history_but_out_of_every_aggregate(db):
    """An excluded match stays in match_history but counts in no summary, avg, breakdown average, comparison or hero figure."""
    _seed_player(db, n=0)
    for mid in (1, 2, 3):
        _match(db, mid)
        _stat(db, 10, mid, hero=5)
    before = _get(db)
    _match(db, 4, rw=False, excluded=True)
    _stat(db, 10, 4, hero=7, mvp=True, kills=60, deaths=0)
    after = _get(db)
    assert len(after["match_history"]) == 4
    assert _row(after, 4)["excluded_from_scoring"] is True
    for key in ("avg_points", "total_points", "summary", "points_sources", "modifier_values",
                "league_comparison", "heroes", "league_avg_points", "current_season_matches"):
        assert after[key] == before[key], key
    assert [h["hero_id"] for h in after["heroes"]] == [5]


def test_get_player_partial_stats_match_counts_in_aggregates(db):
    """A partial-stats (unparsed) match counts in summary, points_sources, league comparison and heroes."""
    _seed_player(db, n=0)
    for mid in (1, 2):
        _match(db, mid)
        _stat(db, 10, mid, hero=5)
    _match(db, 3, parse="unparsed", rw=False)
    _stat(db, 10, 3, hero=9, obs_placed=0, stuns=0, teamfight_participation=0, camps_stacked=0,
          rune_pickups=0)
    data = _get(db)
    assert data["summary"]["losses"] == 1
    assert data["league_comparison"] is not None  # 3 scored matches, partial included
    assert sorted(h["hero_id"] for h in data["heroes"]) == [5, 9]
    assert data["current_season_matches"] == 3
    vision = next(s for s in data["points_sources"] if s["key"] == "vision")
    weights = {w.key: w.value for w in db.query(Weight).all()}
    assert vision["avg"] == pytest.approx(weights["obs_placed"] * 2 * 2 / 3, abs=0.01)


def test_get_player_unknown_id_returns_404(db):
    """GET /players/{id} for an unknown player still answers 404 'Player not found'."""
    res = _client(db).get("/players/424242")
    assert res.status_code == 404
    assert res.json()["detail"] == "Player not found"


def test_get_player_no_matches_returns_empty_aggregates(db):
    """A player with no matches gets an empty history, zeroed summary, null league_comparison and empty heroes (no 500)."""
    _weights(db)
    db.add(Player(id=10, name="Fresh"))
    db.commit()
    data = _get(db)
    assert data["match_history"] == [] and data["matches"] == 0
    assert data["summary"] == {"wins": 0, "losses": 0, "mvps": 0, "avg_rank": None}
    assert data["league_comparison"] is None and data["heroes"] == []
    assert data["best_match"] is None
    assert all(s["avg"] == 0 for s in data["points_sources"])
    assert data["modifier_values"]["stats"] == []


# --- Frontend --------------------------------------------------------------

def _fn_source(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start) + 2]


_FAKE_DOM = r"""
const __els = {};
const __listeners = {};
let __fetched = false;
let __REDUCED = false;
class El {
  constructor(id) {
    this.id = id; this.attrs = {}; this.cls = new Set(); this.hidden = false;
    this.innerHTML = ""; this.textContent = ""; this.style = {}; this.scrolled = null; this.src = "";
    const self = this;
    this.classList = { add: c => self.cls.add(c), remove: c => self.cls.delete(c),
                       contains: c => self.cls.has(c), toggle: c => self.cls.has(c) ? self.cls.delete(c) : self.cls.add(c) };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  scrollIntoView(o) { this.scrolled = o || {}; }
  getBoundingClientRect() { return { left: 10, bottom: 20 }; }
  contains(x) { return x === this; }
  closest(sel) { const m = /^\[([\w-]+)\]$/.exec(sel); return m && this.getAttribute(m[1]) !== null ? this : null; }
  appendChild(c) { return c; }
}
const document = {
  getElementById: id => __els[id] || (__els[id] = new El(id)),
  createElement: () => new El(null),
  body: { appended: [], appendChild(c) { this.appended.push(c); return c; } },
  addEventListener(type, fn) { (__listeners[type] = __listeners[type] || []).push(fn); },
};
const window = { innerWidth: 1000, matchMedia: () => ({ matches: __REDUCED }) };
function fetch() { __fetched = true; return Promise.reject(new Error("no network")); }
const API = "";
function setStatus() {}
let activeUserId = null;
let _rosterCards = [];
function __fire(type, target, extra) { for (const fn of __listeners[type] || []) fn(Object.assign({ target, stopPropagation() {} }, extra || {})); }
"""


def _popup_src():
    g = _fe("app-globals.js")
    helpers = "\n".join(_fn_source(g, n) for n in
                        ("_escHtml", "_safeUrl", "teamLink", "prefersReducedMotion", "statusBadgeHtml"))
    acc = g[g.index("// ACCOLADES (issue 50)"):g.index("// END ACCOLADES (issue 50)")]
    players = _fe("app-players.js")
    dur = _fn_source(players, "_formatGameDuration")
    dur += "\n" + re.search(r"^const _NOT_SCORED_TOOLTIP = .*$", players, re.M).group(0)
    return _FAKE_DOM + helpers + "\n" + acc + "\n" + dur + "\n" + _fe("app-player-popup.js")


def _js(body):
    """Run `body` after loading the popup with the fake DOM; body sets `out`."""
    return _run_node(_popup_src() + "\nlet out = null;\n" + body + "\nconsole.log(JSON.stringify(out));")


_SOURCE_LABELS = [("kills", "Kills"), ("assists", "Assists"), ("farm", "Farm"), ("gpm", "GPM"),
                  ("vision", "Vision"), ("objectives", "Objectives"), ("teamfight", "Teamfight"),
                  ("stuns", "Stuns"), ("jungle_runes", "Jungle and runes"),
                  ("first_blood", "First blood"), ("survival", "Survival"), ("mvp_bonus", "MVP bonus")]


def _m(mid, pts, week="W1", won=True, mvp=False, excluded=False, parse="parsed", hero=1,
       opp="Blues", ts=None):
    breakdown = {k: 0.0 for k, _ in _SOURCE_LABELS}
    breakdown.update(kills=1.5, assists=2.0, gpm=pts - 3.5 - (1.0 if mvp else 0.0))
    if mvp:
        breakdown["mvp_bonus"] = 1.0
    return dict(match_id=mid, start_time=ts or (_BASE_TS + mid * 86400), fantasy_points=pts,
                is_mvp=mvp, parse_status=parse, excluded_from_scoring=excluded, kills=5,
                assists=7, deaths=2, gold_per_min=480.0, obs_placed=1, sen_placed=2,
                tower_damage=1500, hero_id=hero,
                hero_icon_url=f"https://cdn.example/h{hero}.png" if hero else None,
                hero_name=f"Hero{hero}" if hero else None, won=won, duration=1925,
                week_label=week, last_hits=150, denies=9, towers_killed=1, roshan_kills=1,
                teamfight_participation=0.55, camps_stacked=3, rune_pickups=4,
                firstblood_claimed=1, stuns=12.5, team_id=1, team_name="Reds",
                opponent_team_id=2, opponent_team_name=opp, points_breakdown=breakdown)


def _P(**over):
    """A GET /players/{id} response: 4 matches newest first (excluded, MVP win,
    partial loss, unknown result)."""
    history = [
        _m(4, 9.0, week="W3", excluded=True, won=False, opp="Golds"),
        _m(3, 20.1, week="W2", mvp=True, won=True, opp="Greens", hero=2),
        _m(2, 12.4, week="W2", parse="unparsed", won=False, hero=2),
        _m(1, 10.1, week="W1", won=None),
    ]
    shares = {"kills": 30.0, "assists": 20.0, "gpm": 15.0, "farm": 10.0, "vision": 8.0,
              "survival": 7.0, "objectives": 5.0, "mvp_bonus": 3.0, "stuns": 2.0}
    p = {
        "id": 10, "name": "Alpha", "avatar_url": None, "team_name": "Reds", "team_id": 1,
        "matches": 4, "avg_points": 14.2, "total_points": 42.6,
        "best_match": {"match_id": 3, "fantasy_points": 20.1, "start_time": _BASE_TS,
                       "opponent_team_name": "Greens"},
        "match_history": history,
        "summary": {"wins": 1, "losses": 1, "mvps": 1, "avg_rank": {"rank": 7, "of": 84}},
        "league_avg_points": 11.0,
        "points_sources": [{"key": k, "label": lbl, "avg": round(shares.get(k, 0) * 0.142, 2),
                            "share": shares.get(k, 0.0), "league_avg": 1.0}
                           for k, lbl in _SOURCE_LABELS],
        "modifier_values": {"bonus_pct": 10.0, "stats": [
            {"stat": "kills", "label": "Kills", "base": 4.2, "value": 0.42},
            {"stat": "gold_per_min", "label": "GPM", "base": 3.8, "value": 0.38},
            {"stat": "assists", "label": "Assists", "base": 3.0, "value": 0.3},
            {"stat": "deaths", "label": "Deaths", "base": 2.0, "value": 0.2},
            {"stat": "obs_placed", "label": "Observer wards", "base": 1.0, "value": 0.1},
        ]},
        "league_comparison": {"population": 84, "stats": {
            "kills": {"label": "Kills", "value": 6.2, "percentile": 85, "median": 5.1, "lower_is_better": False},
            "deaths": {"label": "Deaths", "value": 2.0, "percentile": 80, "median": 4.0, "lower_is_better": True},
            "assists": {"label": "Assists", "value": 7.0, "percentile": 30, "median": 9.0, "lower_is_better": False},
            "gold_per_min": {"label": "GPM", "value": 480.0, "percentile": 60, "median": 450.0, "lower_is_better": False},
            "teamfight_participation": {"label": "Teamfight %", "value": 0.55, "percentile": 50, "median": 0.5, "lower_is_better": False},
        }},
        "heroes": [{"hero_id": i, "hero_name": f"Hero{i}", "icon_url": f"https://cdn.example/h{i}.png",
                    "games": 10 - i, "wins": 5, "losses": 10 - i - 5 if i < 5 else 0,
                    "avg_points": 12.0 + i} for i in range(1, 9)],
        "seasons_played": 3, "seasons": [], "titles": [], "accolades": [],
        "current_season": "Season 16", "current_season_matches": 3, "holo_unlocked": False,
    }
    p.update(over)
    return p


def _chart(p=None):
    return _js(f"out = _popupFormChartHtml({json.dumps(p or _P())});")


def _bars(html):
    return re.findall(r'<button type="button" class="(form-bar[^"]*)"[^>]*data-match-id="(\d+)"[^>]*>', html)


def _attr(html, name):
    from html import unescape
    return [unescape(v) for v in re.findall(rf'{name}="([^"]*)"', html)]


def test_popup_moved_to_app_player_popup_js_with_script_tag():
    """Source-reading: openPlayerModal and the popup renderers live in app-player-popup.js, loaded by index.html, and are gone from app-players.js."""
    popup = _fe("app-player-popup.js")
    players = _fe("app-players.js")
    html = _fe("index.html")
    for fn in ("openPlayerModal", "renderPlayerProfile", "renderPlayerAccolades", "_matchPointsCellHtml"):
        assert f"function {fn}(" in popup, fn
        assert f"function {fn}(" not in players, fn
    tags = re.findall(r'<script src="/(app-[\w-]+\.js)"></script>', html)
    assert "app-player-popup.js" in tags
    assert tags.index("app-player-popup.js") == tags.index("app-players.js") + 1
    assert tags.index("app-globals.js") < tags.index("app-player-popup.js") < tags.index("app-init.js")


def test_form_chart_one_bar_per_match_oldest_left():
    """Node harness: the form chart renders one bar button per history match, oldest first, height scaled to fantasy points."""
    html = _chart()
    bars = _bars(html)
    assert [mid for _, mid in bars] == ["1", "2", "3", "4"]
    heights = [float(h) for h in re.findall(r'style="--h: ([\d.]+)%"', html)]
    assert len(heights) == 4
    # 20.1 is the tallest, and heights follow points (10.1 < 12.4 < 20.1).
    assert heights[2] == max(heights) and heights[0] < heights[1] < heights[2]
    assert heights[2] == pytest.approx(100 / 1.1, abs=0.1)


def test_form_chart_excluded_match_is_dashed_ghost_bar_not_scored():
    """Node harness: an excluded match renders as a ghost bar labelled "Not scored"; the ghost class has a dashed style (source-reading style.css)."""
    html = _chart()
    bars = dict((mid, cls) for cls, mid in _bars(html))
    assert "form-bar--ghost" in bars["4"]
    assert all("form-bar--ghost" not in bars[m] for m in ("1", "2", "3"))
    ghost = html[html.index('data-match-id="4"') - 200:]
    assert "Not scored" in _attr(ghost, "aria-label")[0]
    css = _fe("style.css")
    assert any("dashed" in b for b in _rule(css, ".form-bar--ghost .form-bar-fill"))


def test_form_chart_partial_stats_bar_hatched():
    """Node harness: a partial-stats match bar carries the hatched class; source-reading checks the hatch pattern in style.css."""
    bars = dict((mid, cls) for cls, mid in _bars(_chart()))
    assert "form-bar--partial" in bars["2"]
    assert "form-bar--partial" not in bars["1"] and "form-bar--partial" not in bars["4"]
    css = _fe("style.css")
    assert any("repeating-linear-gradient" in b for b in _rule(css, ".form-bar--partial .form-bar-fill"))


def _bar_html(html, mid):
    start = html.index(f'data-match-id="{mid}"')
    return html[start:html.index("</button>", start)]


def test_form_chart_mvp_star_and_win_loss_squares():
    """Node harness: MVP adds a star above the bar; a win is a filled square, a loss a hollow one, null result none."""
    html = _chart()
    assert "form-bar-star" in _bar_html(html, 3)
    assert all("form-bar-star" not in _bar_html(html, m) for m in (1, 2, 4))
    assert "form-bar-result--win" in _bar_html(html, 3)
    assert "form-bar-result--loss" in _bar_html(html, 2)
    one = _bar_html(html, 1)
    assert "form-bar-result--win" not in one and "form-bar-result--loss" not in one
    css = _fe("style.css")
    assert any("background: var(--fg)" in b for b in _rule(css, ".form-bar-result--win"))
    assert any("background: transparent" in b for b in _rule(css, ".form-bar-result--loss"))


def test_form_chart_bars_grouped_under_week_labels():
    """Node harness: bars are grouped under their week_label ("W3") headings."""
    html = _chart()
    groups = re.findall(r'<div class="form-week-bars">(.*?)</div>\s*<div class="form-week-label">([^<]*)</div>', html, re.S)
    assert [(lbl, re.findall(r'data-match-id="(\d+)"', bars)) for bars, lbl in groups] == [
        ("W1", ["1"]), ("W2", ["2", "3"]), ("W3", ["4"])]


def test_form_chart_reference_lines_player_and_league_average_labelled():
    """Node harness: a solid player-average line and a dashed league-average line, each with a text label."""
    html = _chart()
    assert re.search(r'class="form-ref form-ref--player"[^>]*><span class="form-ref-label">Avg 14\.2</span>', html)
    assert re.search(r'class="form-ref form-ref--league"[^>]*><span class="form-ref-label">League 11\.0</span>', html)
    css = _fe("style.css")
    assert any("solid" in b for b in _rule(css, ".form-ref"))
    assert any("dashed" in b for b in _rule(css, ".form-ref--league"))


def test_form_chart_bar_tooltip_text_uses_data_tip():
    """Node harness: each bar's data-tip holds date, opponent, hero, result, points and K/D/A."""
    tip = _attr(_bar_html(_chart(), 3), "data-tip")[0]
    for part in ("vs Greens", "Hero2", "Win", "20.1 pts", "K/D/A 5/2/7", "MVP"):
        assert part in tip, (part, tip)
    assert re.match(r"\d{1,2}\.\d{1,2}\.\d{2} · ", tip)
    assert "Loss" in _attr(_bar_html(_chart(), 2), "data-tip")[0]
    assert "Not scored" in _attr(_bar_html(_chart(), 4), "data-tip")[0]


def test_form_chart_bar_activation_scrolls_and_highlights_history_row():
    """Node harness: activating a bar scrolls to and highlights that match's history row (and only that row)."""
    out = _js(f"""
renderPlayerPopup({json.dumps(_P())});
const hist = document.getElementById("playerModalHistory").innerHTML;
const chart = document.getElementById("playerModalForm").innerHTML;
activatePlayerFormBar(3);
const first = [document.getElementById("playerMatchRow-3").classList.contains("is-highlighted"),
               document.getElementById("playerMatchRow-3").scrolled];
activatePlayerFormBar(2);
out = {{hist, chart, first,
       three: document.getElementById("playerMatchRow-3").classList.contains("is-highlighted"),
       two: document.getElementById("playerMatchRow-2").classList.contains("is-highlighted")}};
""")
    assert 'id="playerMatchRow-3"' in out["hist"]
    assert 'onclick="activatePlayerFormBar(3)"' in out["chart"]
    assert out["first"][0] is True and out["first"][1]["behavior"] == "smooth"
    assert out["two"] is True and out["three"] is False


def test_summary_tiles_show_wl_rank_total_best_opponent_mvps():
    """Node harness: tiles show Matches with W–L, Avg pts with "#7 of 84", Total pts, Best match with opponent, and MVPs."""
    html = _js(f"out = _popupTilesHtml({json.dumps(_P())});")
    tiles = re.findall(r'<div class="val">([^<]*)</div><div class="lbl">([^<]*)</div>(?:<div class="sub">([^<]*)</div>)?', html)
    assert tiles == [("4", "Matches", "1–1"), ("14.2", "Avg pts", "#7 of 84"),
                     ("42.6", "Total pts", ""), ("20.1", "Best match", "vs Greens"), ("1", "MVPs", "")]


def test_summary_tiles_omit_rank_when_avg_rank_null():
    """Node harness: with summary.avg_rank null, the Avg pts tile shows no "#N of M" text."""
    p = _P(summary={"wins": 0, "losses": 0, "mvps": 0, "avg_rank": None})
    html = _js(f"out = _popupTilesHtml({json.dumps(p)});")
    assert "Avg pts" in html and " of " not in html and "#" not in html


def test_form_chart_aria_label_summary():
    """Node harness: the chart has an aria-label like "12 matches, average 14.2, last 3 above average"."""
    html = _chart()
    label = re.search(r'class="form-chart" role="group" aria-label="([^"]*)"', html).group(1)
    # Last 3 scored (newest first): 20.1, 12.4, 10.1 against average 14.2.
    assert label == "4 matches, average 14.2, 1 of last 3 above average"
    high = _P(match_history=[_m(i, 30.0) for i in range(1, 13)], avg_points=14.2)
    label = re.search(r'aria-label="([^"]*)"', _chart(high).split('class="form-chart"')[1]).group(1)
    assert label == "12 matches, average 14.2, last 3 above average"


def test_form_chart_bars_grow_once_and_respect_reduced_motion():
    """Source-reading: the bar grow animation is in style.css, disabled under prefers-reduced-motion: reduce, before GUIDED TOUR."""
    css = _fe("style.css")
    tour = css.index("GUIDED TOUR (issue #144)")
    assert css.index("@keyframes form-bar-grow") < tour
    fill = _rule(css[:tour], ".form-bar-fill")
    assert any("animation: form-bar-grow" in b and " both" in b and "infinite" not in b for b in fill)
    reduced = [m.start() for m in re.finditer(r"@media \(prefers-reduced-motion: reduce\)", css[:tour])]
    assert any("animation: none" in css[i:i + 200] and ".form-bar-fill" in css[i:i + 200] for i in reduced)


def test_popup_empty_state_no_matches():
    """Node harness: with no matches, chart, tiles and the sections below are replaced by "No matches yet this season."."""
    out = _js(f"""
renderPlayerPopup({json.dumps(_P(match_history=[], matches=0, heroes=[], league_comparison=None))});
const ids = ["playerModalStats", "playerModalForm", "playerModalSources", "playerModalCompare",
             "playerModalHeroes", "playerModalHistorySection"];
out = {{hidden: ids.map(id => document.getElementById(id).hidden),
       empty: document.getElementById("playerModalEmpty").textContent,
       emptyHidden: document.getElementById("playerModalEmpty").hidden}};
""")
    assert all(out["hidden"])
    assert out["empty"] == "No matches yet this season." and out["emptyHidden"] is False
    assert 'id="playerModalEmpty"' in _fe("index.html")


# ===========================================================================
# #50 reuse: tooltip generalisation, pips and Accolades section
# ===========================================================================

def test_tooltip_generalised_to_data_tip_attribute():
    """Source-reading: app-globals.js's tooltip target selector uses [data-tip] (not only [data-accolade-tip])."""
    js = _fe("app-globals.js")
    target = _fn_body(js, "_accoladeTipTarget")
    assert 'closest("[data-tip]")' in target
    assert 'getAttribute("data-tip")' in _fn_body(js, "showAccoladeTip")
    assert "data-accolade-tip" not in js


def test_accolade_pips_use_data_tip_and_still_show_tooltip():
    """Node harness: accoladePipsHtml emits data-tip, and the shared tooltip shows its text on hover, focus and tap."""
    out = _js("""
const html = accoladePipsHtml([{kind: "champion", division: "div1", season: "Season 16", season_short: "S16", team_name: "Reds"}]);
const pip = new El("pip"); pip.setAttribute("data-tip", "Div 1 Champion · S16 with Reds");
const bar = new El("bar"); bar.setAttribute("data-tip", "1.1.26 · vs Blues");
const tip = () => document.body.appended[0];
__fire("mouseover", pip);
const hover = [tip().textContent, tip().cls.has("accolade-tip--open")];
__fire("mouseout", pip, {relatedTarget: null});
const closed = tip().cls.has("accolade-tip--open");
__fire("focusin", bar);
const focus = tip().textContent;
__fire("focusout", bar);
__fire("click", pip);
const tap = [tip().textContent, tip().cls.has("accolade-tip--open")];
__fire("click", new El("elsewhere"));
out = {html, hover, closed, focus, tap, after: tip().cls.has("accolade-tip--open")};
""")
    assert 'data-tip="Div 1 Champion · S16 with Reds"' in out["html"]
    assert "data-accolade-tip" not in out["html"]
    assert out["hover"] == ["Div 1 Champion · S16 with Reds", True]
    assert out["closed"] is False
    assert out["focus"] == "1.1.26 · vs Blues"
    assert out["tap"] == ["Div 1 Champion · S16 with Reds", True]
    assert out["after"] is False


def test_player_modal_pips_still_rendered_in_header():
    """Source-reading: index.html keeps #playerModalPips in the popup header and the popup still fills it with accoladePipsHtml."""
    html = _fe("index.html")
    modal = html[html.index('id="playerModal"'):html.index('id="playerModalStats"')]
    assert 'id="playerModalPips"' in modal and 'id="playerModalName"' in modal
    assert 'id="playerModalMeta"' in modal
    fn = _fn_body(_fe("app-player-popup.js"), "renderPlayerAccolades")
    assert 'getElementById("playerModalPips")' in fn and "accoladePipsHtml(list)" in fn


def test_accolades_section_kept_between_heroes_and_history():
    """Source-reading: #playerModalAccolades is still rendered by renderPlayerAccolades, placed after heroes and before match history."""
    html = _fe("index.html")
    order = [html.index(f'id="{i}"') for i in (
        "playerModalStats", "playerModalForm", "playerModalSources", "playerModalCompare",
        "playerModalHeroes", "playerModalAccolades", "playerModalHistorySection", "playerProfile")]
    assert order == sorted(order)
    js = _fe("app-player-popup.js")
    assert 'getElementById("playerModalAccolades")' in _fn_body(js, "renderPlayerAccolades")
    assert "renderPlayerAccolades(p)" in _fn_body(js, "openPlayerModal")


def test_get_player_keeps_issue_50_fields(db):
    """GET /players/{id} still returns seasons_played, seasons, titles, accolades, current_season, current_season_matches and holo_unlocked."""
    _seed_player(db, n=2)
    data = _get(db)
    for key in ("seasons_played", "seasons", "titles", "accolades", "current_season",
                "current_season_matches", "holo_unlocked"):
        assert key in data, key
    assert data["current_season_matches"] == 2 and data["holo_unlocked"] is False


# ===========================================================================
# Story 2: Where a Player's Points Come From
# ===========================================================================

# --- Backend ---------------------------------------------------------------

def _default_weights():
    from seed import DEFAULT_WEIGHTS
    return {w["key"]: w["value"] for w in DEFAULT_WEIGHTS}


def test_points_by_source_parts_sum_to_fantasy_points_without_mvp():
    """player_insights.points_by_source: parts add up to scoring.fantasy_score for a non-MVP match, mvp_bonus 0."""
    import player_insights
    from scoring import fantasy_score
    w = _default_weights()
    parts = player_insights.points_by_source(_STATS, w)
    assert parts["mvp_bonus"] == 0
    assert sum(parts.values()) == pytest.approx(fantasy_score(_STATS, w))


def test_points_by_source_parts_sum_to_fantasy_points_with_mvp():
    """player_insights.points_by_source: for an MVP match the parts plus mvp_bonus add up to its fantasy points."""
    import player_insights
    from scoring import fantasy_score
    w = _default_weights()
    parts = player_insights.points_by_source(_STATS, w, is_mvp=True)
    base = fantasy_score(_STATS, w)
    assert parts["mvp_bonus"] == pytest.approx(base * w["mvp_bonus_pct"] / 100)
    assert sum(parts.values()) == pytest.approx(base * (1 + w["mvp_bonus_pct"] / 100))


def test_points_by_source_has_planned_source_groups():
    """Sources are Kills, Assists, Farm, GPM, Vision, Objectives, Teamfight, Stuns, Jungle and runes, First blood, Survival and MVP bonus."""
    import player_insights
    from scoring import SCORING_STATS
    assert [lbl for _, lbl, _ in player_insights.SOURCE_GROUPS] == [
        "Kills", "Assists", "Farm", "GPM", "Vision", "Objectives", "Teamfight", "Stuns",
        "Jungle and runes", "First blood", "Survival", "MVP bonus"]
    covered = [s for _, _, group in player_insights.SOURCE_GROUPS for s in group]
    assert sorted(covered) == sorted(SCORING_STATS + ["deaths"])
    groups = {k: g for k, _, g in player_insights.SOURCE_GROUPS}
    assert groups["farm"] == ["last_hits", "denies"]
    assert groups["objectives"] == ["towers_killed", "roshan_kills"]
    assert groups["jungle_runes"] == ["camps_stacked", "rune_pickups"]
    assert list(player_insights.points_by_source(_STATS, _default_weights())) == player_insights.SOURCE_KEYS


def test_points_by_source_missing_stats_treated_as_zero():
    """points_by_source with null stat values (partial match) returns zero for those parts and still sums to the match points."""
    import player_insights
    from scoring import fantasy_score
    w = _default_weights()
    partial = dict(_STATS, obs_placed=None, stuns=None, teamfight_participation=None,
                   camps_stacked=None, rune_pickups=None)
    parts = player_insights.points_by_source(partial, w)
    assert parts["vision"] == 0 and parts["stuns"] == 0 and parts["teamfight"] == 0
    assert parts["jungle_runes"] == 0
    zeroed = {k: v or 0 for k, v in partial.items()}
    assert sum(parts.values()) == pytest.approx(fantasy_score(zeroed, w))


def test_get_player_points_breakdown_per_match_sums_to_fantasy_points(db):
    """Each match_history row's points_breakdown adds up to its fantasy_points (within display rounding)."""
    _seed_player(db, n=0)
    _match(db, 1)
    _stat(db, 10, 1, mvp=True)
    _match(db, 2)
    _stat(db, 10, 2, deaths=20)  # death pool floored at 0
    _match(db, 3, parse="unparsed")
    _stat(db, 10, 3, obs_placed=0, stuns=0)
    for row in _get(db)["match_history"]:
        parts = row["points_breakdown"]
        assert sum(parts.values()) == pytest.approx(row["fantasy_points"], abs=0.06 + 0.005 * len(parts))
    assert _row(_get(db), 1)["points_breakdown"]["mvp_bonus"] > 0
    assert _row(_get(db), 2)["points_breakdown"]["survival"] == 0


def test_get_player_points_sources_averages_with_share_and_league_average(db):
    """points_sources gives avg points per scored match, share of total and the league average per source."""
    import player_insights
    _seed_player(db, n=0)
    w = _default_weights()
    _match(db, 1)
    _stat(db, 10, 1, kills=4)
    _match(db, 2)
    _stat(db, 10, 2, kills=8)
    _match(db, 3)
    _stat(db, 20, 3, kills=0)
    data = _get(db)
    sources = {s["key"]: s for s in data["points_sources"]}
    assert list(sources) == player_insights.SOURCE_KEYS
    assert sources["kills"]["label"] == "Kills"
    assert sources["kills"]["avg"] == pytest.approx(w["kills"] * 6, abs=0.01)
    assert sources["kills"]["league_avg"] == pytest.approx(w["kills"] * 12 / 3, abs=0.01)
    assert sum(s["share"] for s in sources.values()) == pytest.approx(100, abs=0.3)
    assert sources["kills"]["share"] == pytest.approx(
        100 * sources["kills"]["avg"] / data["avg_points"], abs=0.3)


def test_get_player_modifier_values_per_stat_top_three(db):
    """modifier_values are per stat (not group): modifier_bonus_pct % of each stat's avg points, sorted, top three first."""
    from scoring import SCORING_STATS
    _seed_player(db, n=3)
    w = _default_weights()
    mv = _get(db)["modifier_values"]
    assert mv["bonus_pct"] == w["modifier_bonus_pct"]
    stats = [r["stat"] for r in mv["stats"]]
    assert sorted(stats) == sorted(SCORING_STATS + ["deaths"])  # per stat: last_hits and denies apart
    values = [r["value"] for r in mv["stats"]]
    assert values == sorted(values, reverse=True)
    kills = next(r for r in mv["stats"] if r["stat"] == "kills")
    assert kills["value"] == pytest.approx(w["kills"] * 5 * w["modifier_bonus_pct"] / 100, abs=0.01)
    assert kills["label"] == "Kills"
    top = max(SCORING_STATS, key=lambda s: w[s] * _STATS[s])
    expected_top = "deaths" if w["death_pool"] - 3 * w["death_deduction"] > w[top] * _STATS[top] else top
    assert stats[0] == expected_top


def test_get_player_modifier_values_follow_current_weights(db):
    """Changing modifier_bonus_pct or a stat weight in the weights table changes modifier_values and breakdowns (card_points._current_weights)."""
    _seed_player(db, n=3)
    before = _get(db)
    db.query(Weight).filter(Weight.key == "modifier_bonus_pct").update({"value": 20.0})
    db.query(Weight).filter(Weight.key == "kills").update({"value": 1.0})
    db.commit()
    after = _get(db)
    assert after["modifier_values"]["bonus_pct"] == 20.0
    kills = next(r for r in after["modifier_values"]["stats"] if r["stat"] == "kills")
    assert kills["value"] == pytest.approx(1.0 * 5 * 0.2, abs=0.01)
    assert after["match_history"][0]["points_breakdown"]["kills"] == pytest.approx(5.0)
    assert before["match_history"][0]["points_breakdown"]["kills"] != 5.0


def test_get_player_points_sources_empty_without_scored_matches(db):
    """A player with only excluded matches gets empty/zero points_sources and modifier_values, not an error."""
    _seed_player(db, n=0)
    _match(db, 1, excluded=True)
    _stat(db, 10, 1)
    data = _get(db)
    assert len(data["match_history"]) == 1
    assert all(s["avg"] == 0 and s["share"] == 0 for s in data["points_sources"])
    assert data["modifier_values"]["stats"] == []
    assert data["summary"]["avg_rank"] is None and data["league_comparison"] is None


def _all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def test_get_player_response_has_no_user_data(db):
    """GET /players/{id} carries no viewer or user data (no user ids, usernames, cards or session-dependent fields), even when logged in."""
    import sessions
    from models import Card, User
    _seed_player(db, n=3)
    user = User(username="viewer", email="v@example.com", password_hash="x")
    db.add(user)
    db.commit()
    db.add(Card(owner_id=user.id, player_id=10, card_type="rare"))
    sid = sessions.create_session(db, user)
    db.commit()
    anon = _get(db)
    client = _client(db)
    client.cookies.set("session", sid)
    logged_in = client.get("/players/10").json()
    assert logged_in == anon
    keys = set(_all_keys(anon))
    for bad in ("user_id", "username", "email", "owner_id", "is_admin", "cards", "card_id",
                "owned", "modifiers", "session"):
        assert bad not in keys, bad
    assert "viewer" not in json.dumps(anon)


# --- Frontend --------------------------------------------------------------

def _sources(p=None, setup=""):
    p = p or _P()
    return _js(setup + f"\nout = _popupSourcesHtml({json.dumps(p)}, _popupOwnCardModifiers({p['id']}));")


def test_points_by_source_renders_stacked_bar_rows_and_league_markers():
    """Node harness: one 100 % stacked bar plus a row per source with avg points, share and a league-average marker."""
    html = _sources()
    assert html.count('class="sources-bar"') == 1
    segs = re.findall(r'class="sources-seg sources-seg--(\w+)" style="--w: ([\d.]+)%"', html)
    assert [s for s, _ in segs] == ["1", "2", "3", "4", "5", "other"]
    assert sum(float(w) for _, w in segs) == pytest.approx(100)
    rows = re.findall(r'<li class="sources-row">(.*?)</li>', html, re.S)
    # Every source with player or league points (all have league_avg 1.0 here).
    assert len(rows) == 12
    first = rows[0]
    assert '<span class="sources-label">Kills</span>' in first
    assert '<span class="sources-avg">4.3</span>' in first and '<span class="sources-share">30.0 %</span>' in first
    assert all('class="sources-league"' in r for r in rows)
    css = _fe("style.css")
    for n in ("1", "2", "3", "4", "5"):
        assert any(f"background: var(--series-{n})" in b for b in _rule(css, f".sources-seg--{n}"))
    assert any("background: var(--series-other)" in b for b in _rule(css, ".sources-seg--other"))
    tokens = _fe("colors_and_type.css")
    for value in ("#e0702e", "#3f8fd8", "#b48a1e", "#8e62d4", "#2a9c84", "#55555e"):
        assert value in tokens
    assert tokens == _read("design", "colors_and_type.css")
    # Text never wears series colours.
    for sel, body in _css_blocks(css, r"sources|modifier|compare|form-"):
        if "--series-" in body:
            assert "color:" not in body.replace("background", ""), sel


def test_modifier_value_line_lists_top_three():
    """Node harness: renders "A +10 % modifier is worth most on: Kills (+0.42 / match), …" with the top three."""
    html = _sources()
    line = re.search(r'<p class="modifier-line">([^<]*)</p>', html).group(1)
    assert line == "A +10 % modifier is worth most on: Kills (+0.42 / match), GPM (+0.38), Assists (+0.30)"


def test_your_card_modifiers_highlighted_when_viewer_owns_card():
    """Node harness: with the viewer's loaded My Team cards including this player, that card's modifiers are highlighted with value per match."""
    html = _sources(setup="""
activeUserId = 5;
_rosterCards = [{id: 1, player_id: 10, modifiers: [{stat: "kills", bonus_pct: 10}, {stat: "deaths", bonus_pct: 20}]},
                {id: 2, player_id: 99, modifiers: [{stat: "assists", bonus_pct: 10}]}];
""")
    own = re.findall(r'<li class="modifier-item modifier-item--own">(.*?)</li>', html)
    assert len(own) == 2
    assert own[0].startswith("Kills +10 %") and "+0.42 / match" in own[0]
    assert own[1].startswith("Deaths +20 %") and "+0.40 / match" in own[1]
    assert "Your card" in html
    assert '<li class="modifier-item">Assists' in html


def test_your_card_list_unhighlighted_when_not_owned_or_logged_out():
    """Node harness: with no owned card of this player (or logged out) the modifier list renders with no highlight and no fetch."""
    not_owned = _js(f"""
activeUserId = 5;
_rosterCards = [{{id: 2, player_id: 99, modifiers: [{{stat: "kills", bonus_pct: 10}}]}}];
const html = _popupSourcesHtml({json.dumps(_P())}, _popupOwnCardModifiers(10));
out = {{html, fetched: __fetched}};
""")
    logged_out = _js(f"""
activeUserId = null;
_rosterCards = [{{id: 1, player_id: 10, modifiers: [{{stat: "kills", bonus_pct: 10}}]}}];
const html = _popupSourcesHtml({json.dumps(_P())}, _popupOwnCardModifiers(10));
out = {{html, fetched: __fetched}};
""")
    for out in (not_owned, logged_out):
        assert "modifier-item--own" not in out["html"]
        assert "Your card" not in out["html"]
        assert '<li class="modifier-item">Kills' in out["html"]
        assert out["fetched"] is False
    assert "fetch(" not in _fn_body(_fe("app-player-popup.js"), "_popupOwnCardModifiers")


# ===========================================================================
# Story 3: Compared with the League
# ===========================================================================

# --- Backend ---------------------------------------------------------------

def test_percentile_ranks_value_within_population():
    """player_insights.percentile places a value correctly in a population (top, bottom, middle)."""
    import player_insights
    pop = [1, 2, 3, 4, 5]
    assert player_insights.percentile(5, pop) == 90
    assert player_insights.percentile(1, pop) == 10
    assert player_insights.percentile(3, pop) == 50
    assert player_insights.percentile(3, []) == 0


def test_percentile_deaths_lower_is_better_inverted():
    """percentile with lower_is_better: the fewest deaths gets the highest percentile."""
    import player_insights
    pop = [1, 2, 3, 4, 5]
    assert player_insights.percentile(1, pop, lower_is_better=True) == 90
    assert player_insights.percentile(5, pop, lower_is_better=True) == 10


def test_league_aggregates_only_scored_matches_and_three_match_population(db):
    """league_aggregates uses scored matches only and includes only players with at least 3 scored matches."""
    import card_points
    import player_insights
    _seed_player(db, pid=10, n=3, kills=4)
    _seed_player(db, pid=20, n=2)
    _match(db, 30)  # player 30: two scored + one excluded match
    _stat(db, 30, 30)
    _match(db, 31)
    _stat(db, 30, 31)
    _match(db, 32, excluded=True)
    _stat(db, 30, 32)
    _match(db, 33, excluded=True)
    _stat(db, 10, 33, kills=100)
    agg = player_insights.league_aggregates(db, card_points._current_weights(db))
    assert set(agg["population"]) == {10}
    assert agg["population"][10]["matches"] == 3
    assert agg["population"][10]["stats"]["kills"] == 4


def test_get_player_league_comparison_has_planned_stats(db):
    """league_comparison has Kills, Deaths, Assists, GPM, Last hits, Wards, Stuns, Teamfight % each with value, percentile, median, lower_is_better, plus population."""
    _seed_player(db, pid=10, n=3, kills=9)
    _seed_player(db, pid=20, n=3, kills=1)
    lc = _get(db)["league_comparison"]
    assert lc["population"] == 2
    assert [s["label"] for s in lc["stats"].values()] == [
        "Kills", "Deaths", "Assists", "GPM", "Last hits", "Wards", "Stuns", "Teamfight %"]
    for s in lc["stats"].values():
        assert set(s) == {"label", "value", "percentile", "median", "lower_is_better"}
    assert lc["stats"]["kills"]["value"] == 9 and lc["stats"]["kills"]["median"] == 5
    assert lc["stats"]["kills"]["percentile"] == 75


def test_get_player_league_comparison_deaths_lower_is_better(db):
    """league_comparison.deaths has lower_is_better true and its percentile is inverted."""
    _seed_player(db, pid=10, n=3, deaths=1)
    _seed_player(db, pid=20, n=3, deaths=8)
    deaths = _get(db)["league_comparison"]["stats"]["deaths"]
    assert deaths["lower_is_better"] is True and deaths["percentile"] == 75
    assert _get(db, 20)["league_comparison"]["stats"]["deaths"]["percentile"] == 25
    assert all(not s["lower_is_better"] for k, s in _get(db)["league_comparison"]["stats"].items()
               if k != "deaths")


def test_get_player_league_comparison_null_below_three_scored_matches(db):
    """league_comparison is null when the player has fewer than 3 scored matches (excluded matches don't count toward 3)."""
    _seed_player(db, n=2)
    _seed_player(db, pid=20, n=3)
    _match(db, 1, excluded=True)
    _stat(db, 10, 1)
    data = _get(db)
    assert len(data["match_history"]) == 3
    assert data["league_comparison"] is None
    assert _get(db, 20)["league_comparison"]["population"] == 1


# --- Frontend --------------------------------------------------------------

def _compare(p=None):
    return _js(f"out = _popupComparisonHtml({json.dumps(p or _P())});")


def test_comparison_strips_render_value_median_tick_dot_and_top_bottom_text():
    """Node harness: each strip shows label, average, a 0–100 track with median tick and dot, and "Top 15 %" / "Bottom 30 %"."""
    html = _compare()
    rows = re.findall(r'<li class="compare-row">(.*?)</li>', html, re.S)
    assert len(rows) == 5
    kills = rows[0]
    assert ">Kills<" in kills and '<span class="compare-value">6.2</span>' in kills
    assert 'class="compare-median" style="--x: 50%"' in kills
    assert 'class="compare-dot" style="--x: 85%"' in kills
    assert "League median 5.1" in kills
    assert '<span class="compare-rank">Top 15 %</span>' in kills
    assert '<span class="compare-rank">Bottom 30 %</span>' in rows[2]
    assert '<span class="compare-value">480</span>' in rows[3]
    assert '<span class="compare-value">55 %</span>' in rows[4]


def test_comparison_deaths_strip_says_fewer_deaths_than():
    """Node harness: the Deaths strip reads "fewer deaths than 80 % of players"."""
    deaths = re.findall(r'<li class="compare-row">(.*?)</li>', _compare(), re.S)[1]
    assert '<span class="compare-rank">Fewer deaths than 80 % of players</span>' in deaths
    assert "lower is better" in deaths


def test_comparison_shows_population_size():
    """Node harness: the section shows "vs 84 players" from league_comparison.population."""
    assert "vs 84 players" in _compare()


def test_comparison_not_enough_matches_when_null():
    """Node harness: with league_comparison null the section shows "Not enough matches to compare yet" and no strips."""
    html = _compare(_P(league_comparison=None))
    assert "Not enough matches to compare yet" in html
    assert "compare-row" not in html


def test_role_chip_support_when_wards_ge_3_and_gpm_lt_450():
    """Node harness: the header shows a Support chip when this season's avg wards >= 3 and GPM < 450, else Core."""
    def chip(wards, gpm, excluded_wards=None):
        history = [dict(_m(i, 10.0), obs_placed=wards, gold_per_min=gpm) for i in (1, 2)]
        if excluded_wards is not None:  # an excluded match doesn't move the averages
            history.append(dict(_m(3, 10.0, excluded=True), obs_placed=excluded_wards, gold_per_min=900))
        return _js(f"out = _popupMetaHtml({json.dumps(_P(match_history=history))});")
    assert ">Support</span>" in chip(3, 449)
    assert ">Core</span>" in chip(2, 300)
    assert ">Core</span>" in chip(5, 450)
    assert ">Support</span>" in chip(4, 400, excluded_wards=0)
    assert "3 seasons played" in chip(3, 400)


def test_role_chip_absent_without_scored_matches():
    """Node harness: with no scored matches the header shows no role chip."""
    only_excluded = _P(match_history=[_m(1, 5.0, excluded=True)])
    html = _js(f"out = _popupMetaHtml({json.dumps(only_excluded)});")
    assert "player-role-chip" not in html
    assert _js(f"out = _popupRoleChipHtml({json.dumps(_P(match_history=[]))});") == ""


# ===========================================================================
# Story 4: Heroes Played
# ===========================================================================

# --- Backend ---------------------------------------------------------------

def _h(hero, pts, won=True, excluded=False):
    return {"hero_id": hero, "fantasy_points": pts, "won": won, "excluded_from_scoring": excluded}


def test_hero_rows_games_wl_avg_sorted_by_games():
    """player_insights.hero_rows: one row per hero with games, wins, losses, avg points and icon, sorted by games."""
    import player_insights
    rows = player_insights.hero_rows(
        [_h(1, 10), _h(2, 20, won=False), _h(2, 10), _h(2, 15, won=None), _h(3, 30)],
        {1: "https://x/1.png", 2: "https://x/2.png"}, {2: "Axe"})
    assert [r["hero_id"] for r in rows] == [2, 3, 1]
    axe = rows[0]
    assert axe == {"hero_id": 2, "games": 3, "wins": 1, "losses": 1, "hero_name": "Axe",
                   "icon_url": "https://x/2.png", "avg_points": 15.0}
    assert rows[1]["icon_url"] is None and rows[1]["avg_points"] == 30.0


def test_hero_rows_skip_matches_without_hero_id():
    """hero_rows: a match with hero_id null counts in no hero row."""
    import player_insights
    rows = player_insights.hero_rows([_h(None, 50), _h(1, 10)], {})
    assert [(r["hero_id"], r["games"], r["avg_points"]) for r in rows] == [(1, 1, 10.0)]


def test_hero_rows_ignore_excluded_matches():
    """hero_rows: excluded matches count in no hero figure."""
    import player_insights
    rows = player_insights.hero_rows([_h(1, 10), _h(1, 90, excluded=True), _h(2, 5, excluded=True)], {})
    assert rows == [{"hero_id": 1, "games": 1, "wins": 1, "losses": 0, "hero_name": None,
                     "icon_url": None, "avg_points": 10.0}]


def test_get_player_heroes_and_hero_icon_url(db, monkeypatch):
    """GET /players/{id} returns `heroes` and per-match hero_icon_url from the (monkeypatched) hero icon map."""
    import schedule
    monkeypatch.setattr(schedule, "_hero_icon_cache", {14: "https://cdn.example/pudge.png"})
    monkeypatch.setattr(schedule, "_hero_name_cache", {14: "Pudge"})
    _seed_player(db, n=0)
    _match(db, 1)
    _stat(db, 10, 1, hero=14)
    _match(db, 2, rw=False)
    _stat(db, 10, 2, hero=14)
    _match(db, 3)
    _stat(db, 10, 3, hero=99)
    data = _get(db)
    assert _row(data, 1)["hero_icon_url"] == "https://cdn.example/pudge.png"
    assert _row(data, 1)["hero_name"] == "Pudge"
    assert _row(data, 3)["hero_icon_url"] is None
    pudge = data["heroes"][0]
    assert (pudge["hero_id"], pudge["games"], pudge["wins"], pudge["losses"]) == (14, 2, 1, 1)
    assert pudge["icon_url"] == "https://cdn.example/pudge.png" and pudge["hero_name"] == "Pudge"
    assert [h["hero_id"] for h in data["heroes"]] == [14, 99]


def test_get_player_hero_icon_map_failure_still_returns_200(db, monkeypatch):
    """If the hero icon map can't be fetched, the response is still 200 with hero_id set and hero_icon_url null."""
    import schedule

    def boom():
        raise RuntimeError("OpenDota down")
    monkeypatch.setattr(schedule, "cached_hero_maps", boom)
    _seed_player(db, n=0)
    _match(db, 1)
    _stat(db, 10, 1, hero=14)
    row = _get(db)["match_history"][0]
    assert row["hero_id"] == 14 and row["hero_icon_url"] is None


# --- Frontend --------------------------------------------------------------

def test_heroes_section_top_six_then_show_all():
    """Node harness: hero icons with games, W–L and avg points; six show, then a "Show all" control reveals the rest."""
    out = _js(f"""
const html = _popupHeroesHtml({json.dumps(_P())});
const btn = new El("btn"); btn.setAttribute("aria-expanded", "false"); btn.setAttribute("data-count", "8");
document.getElementById("playerHeroesMore").hidden = true;
togglePlayerHeroes(btn);
const opened = [document.getElementById("playerHeroesMore").hidden, btn.getAttribute("aria-expanded"), btn.textContent];
togglePlayerHeroes(btn);
out = {{html, opened, closed: [document.getElementById("playerHeroesMore").hidden, btn.textContent]}};
""")
    html = out["html"]
    first, more = html.split('id="playerHeroesMore"')
    assert first.count('class="hero-tile"') == 6 and more.count('class="hero-tile"') == 2
    assert 'id="playerHeroesMore" hidden' in html
    assert "Show all (8)" in html and 'aria-controls="playerHeroesMore"' in html
    assert '<span class="hero-tile-stats">9 games · 5–4 · 13.0 avg</span>' in first
    assert 'src="https://cdn.example/h1.png"' in first and 'draggable="false"' in first
    assert out["opened"] == [False, "true", "Show fewer"]
    assert out["closed"] == [True, "Show all (8)"]
    few = _js(f"out = _popupHeroesHtml({json.dumps(_P(heroes=_P()['heroes'][:3]))});")
    assert "Show all" not in few and few.count('class="hero-tile"') == 3


def test_career_heroes_shown_with_update_date_when_facts_exist():
    """Node harness: with profile facts, a "Career (OpenDota, updated <date>)" list shows games and win rate."""
    profile = {"facts": {"top_heroes_alltime": [{"hero_name": "Pudge", "games": 120, "win_rate": 0.55},
                                                {"hero_name": "<b>Axe</b>", "games": 40, "win_rate": 0.5}]},
               "facts_fetched_at": 1_767_225_600}  # 1.1.2026
    out = _js(f"""
renderPlayerPopup({json.dumps(_P())});
renderPlayerCareerHeroes({json.dumps(profile)});
const el = document.getElementById("playerCareerHeroes");
out = {{html: el.innerHTML, hidden: el.hidden}};
""")
    assert out["hidden"] is False
    assert re.search(r"Career \(OpenDota, updated \d{1,2}\.\d{1,2}\.2026\)", out["html"])
    assert "Pudge" in out["html"] and "120 games, 55 % won" in out["html"]
    assert "<b>Axe" not in out["html"] and "&lt;b&gt;Axe" in out["html"]


def test_career_heroes_hidden_without_facts():
    """Node harness: with no profile facts, the career heroes list is absent and nothing else changes."""
    out = _js(f"""
renderPlayerPopup({json.dumps(_P())});
const heroes = document.getElementById("playerModalHeroes").innerHTML;
renderPlayerCareerHeroes({{facts: null, bio_text: null}});
const el = document.getElementById("playerCareerHeroes");
out = {{html: el.innerHTML, hidden: el.hidden, heroes,
       after: document.getElementById("playerModalHeroes").innerHTML}};
""")
    assert out["html"] == "" and out["hidden"] is True
    assert out["after"] == out["heroes"]
    assert 'id="playerCareerHeroes" class="hero-career" hidden' in out["heroes"]


# ===========================================================================
# Story 5: Match Details on Demand
# ===========================================================================

# --- Backend ---------------------------------------------------------------

def test_get_player_match_history_includes_never_shown_stats(db):
    """match_history rows include last hits, denies, towers, Roshan, teamfight, camps, runes, first blood, stuns, sen_placed and duration."""
    _seed_player(db, n=0)
    _match(db, 1, duration=2345)
    _stat(db, 10, 1, firstblood_claimed=1, roshan_kills=2)
    row = _get(db)["match_history"][0]
    expected = dict(_STATS, firstblood_claimed=1, roshan_kills=2, duration=2345)
    for key in ("last_hits", "denies", "towers_killed", "roshan_kills", "teamfight_participation",
                "camps_stacked", "rune_pickups", "firstblood_claimed", "stuns", "sen_placed", "duration"):
        assert row[key] == expected[key], key


# --- Frontend --------------------------------------------------------------

def _history(p=None):
    p = p or _P()
    return _js(f"""
renderPlayerPopup({json.dumps(p)});
out = document.getElementById("playerModalHistory").innerHTML;
""")


def _cells(row_html):
    return re.findall(r'<td class="(hc-[\w-]+)">(.*?)</td>', row_html, re.S)


def _history_row(html, mid):
    start = html.index(f'<tr class="history-row" id="playerMatchRow-{mid}">')
    return html[start:html.index("</tr>", start)]


def test_history_table_hero_and_result_columns_after_date():
    """Node harness: the history adds Hero (icon) and Result (W/L as text) after Date; existing columns stay."""
    html = _fe("index.html")
    thead = re.search(r'<thead><tr>((?:<th>[^<]*</th>)+)</tr></thead>\s*<tbody id="playerModalHistory">', html)
    headers = re.findall(r"<th>([^<]*)</th>", thead.group(1))
    assert headers == ["MVP", "Date", "Hero", "Result", "Fantasy pts", "K/A/D", "GPM", "Wards",
                       "Tower dmg", "Opponent", "OpenDota", "Details"]
    row = _history_row(_history(), 3)
    cells = _cells(row)
    assert [c for c, _ in cells] == ["hc-mvp", "hc-date", "hc-hero", "hc-result", "hc-pts", "hc-kad",
                                     "hc-gpm", "hc-wards", "hc-tower", "hc-opp", "hc-link", "hc-details"]
    assert len(cells) == len(headers)
    cell = dict(cells)
    assert '<img draggable="false" class="hero-icon" src="https://cdn.example/h2.png" alt="Hero2"' in cell["hc-hero"]
    assert cell["hc-result"] == "W"
    assert dict(_cells(_history_row(_history(), 2)))["hc-result"] == "L"
    assert "★" in cell["hc-mvp"] and "20.1" in cell["hc-pts"]
    assert "https://www.opendota.com/matches/3" in cell["hc-link"]


def test_history_result_blank_when_won_null():
    """Node harness: a row with won null shows no W/L text (no false result)."""
    assert dict(_cells(_history_row(_history(), 1)))["hc-result"] == ""


def test_history_details_toggle_aria_expanded_opens_panel():
    """Node harness: each row's Details toggle flips aria-expanded false→true and shows its panel; a second activation closes it."""
    html = _history()
    for mid in (1, 2, 3, 4):
        row = _history_row(html, mid)
        assert (f'<button type="button" class="ghost history-details-btn" aria-expanded="false" '
                f'aria-controls="playerMatchDetails-{mid}" onclick="togglePlayerMatchDetails(this)">Details</button>') in row
        assert f'<tr class="history-details-row" id="playerMatchDetails-{mid}" hidden>' in html
    out = _js("""
const btn = new El("b"); btn.setAttribute("aria-expanded", "false"); btn.setAttribute("aria-controls", "playerMatchDetails-3");
const panel = document.getElementById("playerMatchDetails-3"); panel.hidden = true;
togglePlayerMatchDetails(btn);
const opened = [btn.getAttribute("aria-expanded"), panel.hidden];
togglePlayerMatchDetails(btn);
out = {opened, closed: [btn.getAttribute("aria-expanded"), panel.hidden]};
""")
    assert out["opened"] == ["true", False]
    assert out["closed"] == ["false", True]


def _details(html, mid):
    start = html.index(f'id="playerMatchDetails-{mid}"')
    end = html.find('<tr class="history-row"', start)
    return html[start:end if end > 0 else len(html)]


def test_history_details_panel_lists_every_stat():
    """Node harness: the Details panel lists every stat incl. last hits, denies, towers, Roshan, teamfight, camps, runes, first blood, stuns, sentry wards, duration."""
    panel = _details(_history(), 3)
    stats = dict(re.findall(r"<dt>([^<]*)</dt><dd>([^<]*)</dd>", panel))
    assert stats == {"Kills": "5", "Deaths": "2", "Assists": "7", "Last hits": "150", "Denies": "9",
                     "GPM": "480", "Observer wards": "1", "Sentry wards": "2", "Tower damage": "1500",
                     "Towers": "1", "Roshan": "1", "Teamfight": "55 %", "Camps stacked": "3",
                     "Runes": "4", "First blood": "Yes", "Stuns": "12.5 s", "Duration": "32:05"}


def test_history_details_panel_shows_points_breakdown_with_mvp_bonus():
    """Node harness: the Details panel shows that match's points breakdown by source, with the MVP bonus."""
    html = _history()
    panel = _details(html, 3)
    parts = re.findall(r'<li(?: class="history-breakdown-total")?><span>([^<]*)</span><span class="history-breakdown-pts">([^<]*)</span></li>', panel)
    assert parts == [("Kills", "1.5"), ("Assists", "2.0"), ("GPM", "15.6"), ("MVP bonus", "1.0"),
                     ("Fantasy points", "20.1")]
    assert "MVP bonus" not in _details(html, 1)
    assert ("Not scored", "—") in re.findall(
        r'<li class="history-breakdown-total"><span>([^<]*)</span><span class="history-breakdown-pts">([^<]*)</span>',
        _details(html, 4))


def test_history_partial_and_not_scored_badges_unchanged():
    """Node harness: Partial stats and Not scored badges and their tooltips render as before (_matchPointsCellHtml)."""
    html = _history()
    partial = dict(_cells(_history_row(html, 2)))["hc-pts"]
    excluded = dict(_cells(_history_row(html, 4)))["hc-pts"]
    assert partial.startswith("12.4 ") and '<span class="badge common" title="The replay has not been parsed, so wards, stuns, teamfight, runes and camps count as 0.">Partial stats</span>' in partial
    assert excluded == '— <span class="badge common" title="An admin excluded this match from scoring. It adds no fantasy points.">Not scored</span>'
    assert dict(_cells(_history_row(html, 1)))["hc-pts"] == "10.1"


def test_history_phone_width_stacked_rows_no_sideways_scroll():
    """Source-reading: below 640 px the history becomes stacked rows (date, opponent, result, hero, points) with the Details toggle and no horizontal overflow."""
    css = _fe("style.css")
    tour = css.index("GUIDED TOUR (issue #144)")
    start = css.index("@media (max-width: 640px)", css.index("PLAYER POPUP VISUALIZATIONS"))
    assert start < tour
    phone = css[start:tour]
    assert any("display: none" in b for b in _rule(phone, ".player-history thead"))
    row = _rule(phone, ".player-history tr.history-row")
    assert row and "display: grid" in row[0]
    areas = re.search(r'grid-template-areas: "([^"]*)"', row[0]).group(1).split()
    assert areas == ["date", "hero", "opp", "result", "pts"]
    for cls, area in ((".hc-date", "date"), (".hc-opp", "opp"), (".hc-result", "result"),
                      (".hc-hero", "hero"), (".hc-pts", "pts"), (".hc-details", "details")):
        assert any(f"grid-area: {area}" in b for b in _rule(phone, f".player-history {cls}")), cls
    assert any("overflow-x: visible" in b for b in _rule(phone, ".player-history-wrap"))
    hidden = _rule(phone, ".player-history .hc-kad")
    assert hidden and "display: none" in hidden[0]
    assert any("display: block" in b for b in _rule(phone, ".player-history tr.history-details-row"))
    assert any("min-width: 0" in b for b in _rule(css[:tour], ".form-week"))


# ===========================================================================
# Security review follow-ups: league cache, hero icon hosts, non-blocking icons
# ===========================================================================

def _count_league(monkeypatch):
    import player_insights
    calls = []
    real = player_insights.league_aggregates

    def counting(db, weights):
        calls.append(1)
        return real(db, weights)
    monkeypatch.setattr(player_insights, "league_aggregates", counting)
    return calls


def test_league_aggregates_cached_between_requests(db, monkeypatch):
    """A second GET /players/{id} (any player) reuses the league aggregates instead of recomputing them."""
    _seed_player(db, n=3)
    _seed_player(db, pid=20, n=3)
    calls = _count_league(monkeypatch)
    first = _get(db)
    _get(db)
    _get(db, 20)
    assert len(calls) == 1
    assert _get(db) == first


def test_league_cache_invalidated_by_new_stat_row(db, monkeypatch):
    """Ingesting a stat row changes the data version, so the next request recomputes."""
    _seed_player(db, n=3)
    calls = _count_league(monkeypatch)
    before = _get(db)
    _match(db, 7)
    _stat(db, 20, 7, kills=40)
    after = _get(db)
    assert len(calls) == 2
    assert after["league_avg_points"] != before["league_avg_points"]


def test_league_cache_invalidated_by_exclusion_toggle(db, monkeypatch):
    """Excluding a match (no stat row changes) invalidates the cached league figures."""
    _seed_player(db, n=3)
    _match(db, 7)
    _stat(db, 20, 7, kills=40)
    calls = _count_league(monkeypatch)
    before = _get(db)
    db.query(Match).filter(Match.match_id == 7).update({"excluded_from_scoring": True})
    db.commit()
    after = _get(db)
    assert len(calls) == 2
    assert after["league_avg_points"] != before["league_avg_points"]


def test_league_cache_invalidated_by_weights_change(db, monkeypatch):
    """Changing a weight changes the fingerprint in the cache key, so the next request recomputes."""
    _seed_player(db, n=3)
    calls = _count_league(monkeypatch)
    before = _get(db)
    db.query(Weight).filter(Weight.key == "kills").update({"value": 2.0})
    db.commit()
    after = _get(db)
    assert len(calls) == 2
    kills = lambda d: next(s for s in d["points_sources"] if s["key"] == "kills")["league_avg"]
    assert kills(after) != kills(before)


def test_league_cache_expires_after_ttl(db, monkeypatch):
    """The cache is a short-lived safety net: after LEAGUE_CACHE_TTL seconds it recomputes even without a change."""
    import player_insights
    _seed_player(db, n=3)
    calls = _count_league(monkeypatch)
    now = [1000.0]
    monkeypatch.setattr(player_insights.time, "monotonic", lambda: now[0])
    _get(db)
    now[0] += player_insights.LEAGUE_CACHE_TTL - 1
    _get(db)
    assert len(calls) == 1
    now[0] += 2
    _get(db)
    assert len(calls) == 2


def test_hero_icon_map_keeps_only_same_host_icon_paths(monkeypatch):
    """_fetch_hero_icon_map accepts only icon paths starting with a single "/", so a crafted icon can't change the CDN host."""
    import schedule
    monkeypatch.setattr(schedule, "_hero_icon_cache", None)
    monkeypatch.setattr(schedule, "_hero_name_cache", {})
    data = {
        "1": {"id": 1, "icon": "/apps/dota2/heroes/icons/antimage.png", "localized_name": "Anti-Mage"},
        "2": {"id": 2, "icon": "@evil.example/x.png"},
        "3": {"id": 3, "icon": "//evil.example/x.png"},
        "4": {"id": 4, "icon": 123},
        "5": {"id": 5, "icon": "/\\evil.example/x.png"},
        "6": {"id": 6, "icon": ".evil.example/x.png"},
    }
    monkeypatch.setattr("opendota_client.get_json", lambda url, label=None: data)
    icons = _real_fetch_hero_icon_map()
    assert icons == {1: "https://cdn.cloudflare.steamstatic.com/apps/dota2/heroes/icons/antimage.png"}
    from urllib.parse import urlsplit
    assert all(urlsplit(u).hostname == "cdn.cloudflare.steamstatic.com" for u in icons.values())
    assert schedule.hero_name_map() == {1: "Anti-Mage"}


def test_player_popup_does_not_call_opendota_on_cold_cache(db, monkeypatch):
    """With a cold hero cache the popup answers 200 without an inline OpenDota call (icons null) and starts the background warm-up once."""
    import opendota_client
    import schedule
    calls, started = [], []
    monkeypatch.setattr(opendota_client, "get_json", lambda *a, **k: calls.append(a) or {})
    monkeypatch.setattr(schedule, "_fetch_hero_icon_map", _REAL_FETCH)
    monkeypatch.setattr(schedule, "warm_hero_maps_in_background", _REAL_WARM)
    monkeypatch.setattr(schedule, "_hero_warm_started", False)

    class _FakeThread:
        def __init__(self, target=None, daemon=None, **kw):
            self.target = target

        def start(self):
            started.append(self.target)
    from types import SimpleNamespace
    monkeypatch.setattr(schedule, "threading", SimpleNamespace(Thread=_FakeThread))
    _seed_player(db, n=0)
    _match(db, 1)
    _stat(db, 10, 1, hero=14)
    row = _get(db)["match_history"][0]
    _get(db)
    assert row["hero_id"] == 14 and row["hero_icon_url"] is None and row["hero_name"] is None
    assert calls == []
    assert started == [schedule.warm_hero_maps]


def test_startup_warms_hero_maps_in_background(monkeypatch):
    """main._start_background_threads starts schedule.warm_hero_maps on a thread, so the cache is warm before popups."""
    import main
    import schedule
    import steam_live
    from types import SimpleNamespace
    started = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None, **kw):
            self.target = target

        def start(self):
            started.append(self.target)
    monkeypatch.setattr(steam_live, "STEAM_API_KEY", "")
    monkeypatch.setattr(main, "threading", SimpleNamespace(Thread=_FakeThread))
    main._start_background_threads()
    assert schedule.warm_hero_maps in started


# --- Security re-check follow-up: popup never waits on the hero fetch lock -----------

import schedule as _schedule_module

_REAL_WARM_IN_BACKGROUND = _schedule_module.warm_hero_maps_in_background


def test_cached_hero_maps_does_not_wait_while_a_fetch_holds_the_lock(monkeypatch):
    """While a slow OpenDota fetch holds the fetch lock, a cold popup lookup returns at once."""
    import threading
    import schedule
    started = []
    result = []
    # Build the worker before patching Thread (schedule.threading is the global module).
    t = threading.Thread(target=lambda: result.append(schedule.cached_hero_maps()))
    monkeypatch.setattr(schedule, "warm_hero_maps_in_background", _REAL_WARM_IN_BACKGROUND)
    monkeypatch.setattr(schedule, "_hero_warm_started", False)
    monkeypatch.setattr(schedule.threading, "Thread",
                        lambda target=None, daemon=None: type("T", (), {"start": lambda self: started.append(target)})())
    with schedule._hero_fetch_lock:  # a fetch is "in progress"
        t.start()
        t.join(timeout=2)
        assert not t.is_alive(), "cached_hero_maps blocked on the fetch lock"
    assert result == [({}, {})]
    assert started == [schedule.warm_hero_maps]


def test_startup_warm_marks_warm_started(monkeypatch):
    """The startup warm-up sets the flag, so popups don't start a second warm-up."""
    import schedule
    monkeypatch.setattr(schedule, "_hero_warm_started", False)
    schedule.warm_hero_maps()  # _fetch_hero_icon_map is stubbed by the autouse fixture
    assert schedule._hero_warm_started is True
