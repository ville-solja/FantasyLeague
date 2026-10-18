"""
Tests for plan-issue-50-season-winners-and-holo-cards.md (resolves GitHub issues
#50, #53 and #105).

Seasons remember who won and who played: a `season_accolades` table that Season
Reset never touches, End Season records awards / champions / played rows, admins
manage champions and accolades, a one-off Played backfill script, Holo
Legendaries for past champions, accolade pips and chips, Players-tab seasons and
titles, and a public History tab.

  Story 1: Accolades Survive Season Changes
  Story 2: End Season Records Champions and Accolades
  Story 3: Admins Manage Champions and Accolades
  Story 4: Seasons Played Are Backfilled
  Story 5: Cards Show Titles, and Champions' Legendaries Can Be Holo
  Story 6: Accolade Symbols Read at a Glance
  Story 7: Seasons Played and Titles Are Easy to Find
  Step 8:  Verification / Tests list (migration 040, computation, audit)

Approach notes (for the developer filling these in):

- Backend: use the `db` fixture plus a TestClient with `get_db` overridden.
  Sessions via `{"sid": sessions.create_session(db, user)}`; destructive admin
  routes (`require_recent_reauth`) need `POST /reauth` first (lessons-learned
  2026-10-13). End Season / Reset live in `backend/routers/admin_season.py`
  (`POST /admin/season/end`, `POST /admin/season/reset`); see
  test_issue_81_season_lifecycle.py for fixtures that seed a season.
- After seeding stats directly, call `card_points.rebuild_all(db)` before
  comparing scores.
- Holo roll: patch the RNG used by `draw_card` / `draw_booster` in
  `backend/routers/cards.py` (or a helper in `accolades.py`) so the roll is
  deterministic.
- Backfill script: import `backend/scripts/backfill_played.py` as a module and
  mock `ingest.get_league_matches` and the per-match fetch; point the cache file
  at `tmp_path`; patch the sleep so tests don't pause.
- Migration 040: the latest migration today is `039_user_tags_source`; reuse the
  `_legacy_engine` pattern from test_issue_129_* and the coverage test in
  test_migrate.py.
- Frontend "source-reading" stubs read frontend/app-globals.js, app-cards.js,
  app-players.js, app-history.js, app-admin-*.js, index.html, style.css and
  colors_and_type.css (both copies) with `_read` / `_css_blocks` / `_fn_body`
  from test_issue_151_weekly_report_aesthetics.py and `_rule` as in
  test_issue_205_card_draw_animations.py. New CSS goes before the
  "GUIDED TOUR (issue #144)" section.
- Frontend "Node harness" stubs extract `accoladePipsHtml` /
  `accoladeChipsHtml` (and the tooltip helpers) from app-globals.js and run them
  in Node (`_node()` from test_issue_159_flicker_free_tab_switching.py; skip
  when Node is missing). Re-add `async` when pasting extracted functions.

Run with: cd backend && python -m pytest tests/test_issue_50_season_winners_and_holo_cards.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import models  # noqa: F401  (registers every table for the db fixture)

import importlib.util
import json
import re
import shutil
import subprocess
import time
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

import accolades
import migrate
from database import Base, get_db
from models import (
    AuditLog, Card, CardMatchPoints, CardModifier, Match, Player, PlayerMatchStats,
    SeasonAccolade, SeasonArchive, TagDefinition, Team, User, UserTag, Weight,
)

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_FRONTEND = os.path.join(_ROOT, "frontend")
_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}


@pytest.fixture
def db():
    """The usual in-memory database, on one shared connection so a TestClient's
    request thread sees the same data (overrides conftest's `db`)."""
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


def _user(db, username="alice", admin=False, player_id=None, uid=None, steam_id=None, **fields):
    from auth import hash_password
    u = User(id=uid, username=username, email=f"{username}@example.com",
             password_hash=hash_password("secret123"), is_admin=admin, tokens=10,
             created_at=int(time.time()), player_id=player_id, steam_id=steam_id, **fields)
    db.add(u)
    db.commit()
    return u


def _client(db, login=None, reauth=True):
    """A small app around the routers this feature touches, sharing `db`. login: a
    User to sign in as (with a recent re-auth unless reauth=False)."""
    import sessions
    from routers import admin_accolades, admin_season, cards, history, players
    import rate_limit
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-50")
    app.state.limiter = rate_limit.limiter
    for m in (admin_season, admin_accolades, history, players, cards):
        app.include_router(m.router)

    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db

    @app.post("/_test/login/{user_id}")
    def _login(user_id: int, request: Request, fresh: bool = True):
        user = db.get(User, user_id)
        sessions.start_session(request, db, user)
        if fresh:
            sessions.mark_reauth(sessions.current_row(request, db))
        db.commit()
        return {"ok": True}

    client = TestClient(app)
    if login is not None:
        assert client.post(f"/_test/login/{login.id}", params={"fresh": reauth}).status_code == 200
    return client


def _admin_client(db, reauth=True):
    admin = db.query(User).filter_by(username="admin").first() or _user(db, "admin", admin=True)
    return _client(db, login=admin, reauth=reauth), admin


def _acc(db, season, kind, pid=None, name=None, division=None, team=None, user_id=None,
         username=None, value=None, match_id=None, source="admin"):
    row = SeasonAccolade(season_label=season, kind=kind, player_account_id=pid,
                         player_name=name, division=division, team_name=team,
                         user_id=user_id, username=username, value=value, match_id=match_id,
                         source=source, created_at=int(time.time()))
    db.add(row)
    db.commit()
    return row


def _rows(db, **filters):
    db.expire_all()
    return db.query(SeasonAccolade).filter_by(**filters).all()


def _audits(db, action):
    db.expire_all()
    return db.query(AuditLog).filter_by(action=action).all()


_PLAYERS = {1: "Alpha", 2: "Bravo", 3: "Charlie", 4: "Delta"}
_STATS = [  # (player, team, match, points)
    (1, 100, 1001, 30.0), (1, 100, 1002, 10.0), (1, 100, 1003, 20.0),
    (2, 100, 1001, 50.0),
    (3, 200, 1001, 25.0), (3, 200, 1002, 25.0),
    (4, 200, 1004, 999.0),  # only in an excluded match
]


def _seed_season(db, stats=_STATS, players=_PLAYERS):
    """Alpha: most points (60); Bravo: best match (50) but one match only; Charlie: best
    average (25 over 2 of max 3); Delta played only an excluded match."""
    for pid, name in players.items():
        db.add(Player(id=pid, name=name, is_active=True))
    db.add(Team(id=100, name="Reds"))
    db.add(Team(id=200, name="Blues"))
    for mid in sorted({s[2] for s in stats}):
        db.add(Match(match_id=mid, radiant_team_id=100, dire_team_id=200, start_time=1_000_000 + mid,
                     excluded_from_scoring=(mid == 1004)))
    for pid, team, mid, pts in stats:
        db.add(PlayerMatchStats(player_id=pid, team_id=team, match_id=mid, fantasy_points=pts))
    db.commit()


def _standings(monkeypatch, rows):
    import routers.leaderboard as lb
    monkeypatch.setattr(lb, "compute_season_standings", lambda db: [dict(r) for r in rows])


def _end(db, label="Season 16", champions=None):
    from routers.admin_season import SeasonEndBody, end_season
    body = SeasonEndBody(season_label=label, champions=champions)
    return end_season(body, db=db, admin=dict(_ADMIN))


def _put(client, players, label="Season 16", division="div1", team="Reds"):
    return client.put("/admin/season-champions", json={
        "season_label": label, "division": division, "team_name": team,
        "players": [{"account_id": a, "name": n} for a, n in players]})


def _weights(db, **over):
    from seed import DEFAULT_WEIGHTS
    for w in DEFAULT_WEIGHTS:
        db.add(Weight(key=w["key"], label=w["label"], value=over.get(w["key"], w["value"])))
    db.commit()


def _draw_setup(db, champion_season="Season 15", holo_chance=None):
    """A user with tokens, one pool player (7, "Glete") and a champion row for them."""
    over = {} if holo_chance is None else {"holo_chance": holo_chance}
    _weights(db, **over)
    db.add(Player(id=7, name="Glete", is_active=True))
    db.add(Team(id=300, name="Greens"))
    db.add(Match(match_id=2001, radiant_team_id=300, dire_team_id=100, start_time=1_000_000))
    db.add(PlayerMatchStats(player_id=7, team_id=300, match_id=2001, fantasy_points=12.0))
    user = User(username="collector", email="c@example.com", password_hash="x", tokens=20)
    db.add(user)
    db.commit()
    if champion_season:
        _acc(db, champion_season, "champion", 7, "Glete", division="div1", team="Greens")
    return user


def _draw(db, user, rarity="legendary", roll=0.0, monkeypatch=None, booster=False):
    import routers.cards as cards
    monkeypatch.setattr(cards, "_roll_rarity", lambda weights: rarity)
    monkeypatch.setattr(accolades.random, "random", lambda: roll)
    cu = {"user_id": user.id, "username": user.username, "is_admin": False}
    if booster:
        return cards.draw_booster(300, db, cu)
    return cards.draw_card(db, cu)


def _backfill():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "backfill_played.py")
    spec = importlib.util.spec_from_file_location("backfill_played_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_LEAGUES = {
    111: [9001, 9002],
    222: [9003],
}
_MATCHES = {
    9001: {"players": [{"account_id": 10, "personaname": "tenpub"}, {"account_id": 11, "personaname": None},
                       {"account_id": None, "personaname": "anon"}]},
    9002: {"players": [{"account_id": 10, "personaname": "tenpub"}, {"account_id": 12, "personaname": "twelve"}]},
    9003: {"players": [{"account_id": 13, "personaname": "thirteen"}, {"personaname": "anon2"}]},
}


_LEAGUE_NAMES = {111: "Kanaliiga Season 14", 222: "Kanaliiga Season 14 Lower"}


def _run_backfill(db, tmp_path, monkeypatch, leagues=(111, 222), dry_run=False, matches=None,
                  league_map=None, season="Season 14", league_names=None, league_list=None,
                  name_prefix="Kanaliiga"):
    """Runs backfill_played.run with OpenDota mocked: matchIds (league_map), match
    details (matches), league info names (league_names) and the league list."""
    mod = _backfill()
    import ingest
    league_map = _LEAGUES if league_map is None else league_map
    matches = _MATCHES if matches is None else matches
    league_names = _LEAGUE_NAMES if league_names is None else league_names
    fetched, sleeps, out, infos, lists = [], [], [], [], []
    monkeypatch.setattr(ingest, "get_league_matches", lambda lid: league_map.get(lid))
    monkeypatch.setattr(ingest, "get_league_info",
                        lambda lid: (infos.append(lid), {"name": league_names[lid]} if lid in league_names else None)[1])
    monkeypatch.setattr(mod, "fetch_match", lambda mid: (fetched.append(mid), matches.get(mid))[1])
    monkeypatch.setattr(mod, "fetch_leagues", lambda: (lists.append(1), league_list)[1])
    code = mod.run(db, season, list(leagues), dry_run, cache_path=str(tmp_path / "cache.json"),
                   pause=0.5, sleep=sleeps.append, out=out.append, name_prefix=name_prefix)
    return SimpleNamespace(code=code, fetched=fetched, sleeps=sleeps, out="\n".join(out),
                           infos=infos, lists=lists)


# Node harness for the shared accolade helpers in app-globals.js.
def _globals_helpers_js():
    js = _fe("app-globals.js")
    start = js.index("// ACCOLADES (issue 50)")
    end = js.index("// END ACCOLADES (issue 50)")
    return _fn_source(js, "_escHtml") + "\n" + js[start:end]


def _fn_source(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start) + 2]


def _run_node(script):
    node = _node()
    if not node:
        pytest.skip("node not available")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _pips(accolades_list, opts=None):
    return _run_node(_globals_helpers_js() + f"""
const out = accoladePipsHtml({json.dumps(accolades_list)}, {json.dumps(opts or {})});
console.log(JSON.stringify(out));
""")


def _chips(accolades_list):
    return _run_node(_globals_helpers_js() + f"""
console.log(JSON.stringify(accoladeChipsHtml({json.dumps(accolades_list)})));
""")


def _a(kind, season, division=None, team=None, value=None):
    return {"kind": kind, "season": season, "season_short": accolades.short_season(season),
            "division": division, "team_name": team, "value": value}


def _pip_attrs(html):
    """[(class, aria-label, count text or None)] per pip in rendered markup."""
    out = []
    for chunk in html.split('<span class="accolade-pip ')[1:]:
        cls = "accolade-pip " + chunk[:chunk.index('"')]
        aria = re.search(r'aria-label="([^"]*)"', chunk).group(1)
        count = re.search(r'class="accolade-pip-count">([^<]*)<', chunk)
        out.append((cls, aria, count.group(1) if count else None))
    return out



# ===========================================================================
# Story 1: Accolades Survive Season Changes
# ===========================================================================

def test_season_accolades_table_has_planned_columns(db):
    """`season_accolades` exists via create_all with id, season_label, kind, division, team_name, player_account_id, player_name, user_id, username, value, match_id, source, created_at, created_by."""
    cols = {c["name"] for c in sa_inspect(db.get_bind()).get_columns("season_accolades")}
    assert cols == {"id", "season_label", "kind", "division", "team_name", "player_account_id",
                    "player_name", "user_id", "username", "value", "match_id", "source",
                    "created_at", "created_by"}


def test_season_accolades_unique_key_rejects_duplicate(db):
    """Inserting the same (season_label, kind, division, player_account_id, user_id) twice violates the unique constraint."""
    _acc(db, "Season 15", "most_points", 7, "Glete", value=60)
    db.add(SeasonAccolade(season_label="Season 15", kind="most_points", player_account_id=7,
                          player_name="Glete again", source="admin"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # NULL division / user_id still collide (the index compares them through COALESCE).
    _acc(db, "Season 15", "fantasy_winner", user_id=5, username="jiri")
    db.add(SeasonAccolade(season_label="Season 15", kind="fantasy_winner", user_id=5,
                          username="jiri", source="admin"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # A different division is a different row.
    _acc(db, "Season 15", "champion", 7, "Glete", division="div1", team="Reds")
    _acc(db, "Season 15", "champion", 7, "Glete", division="div2", team="Blues")
    assert len(_rows(db, kind="champion")) == 2


def test_season_reset_keeps_all_accolade_rows(db):
    """POST /admin/season/reset keeps every season_accolades row, and the response reports the kept count."""
    import database
    from routers.admin_season import SeasonResetBody, reset_season
    _seed_season(db)
    _acc(db, "Season 15", "champion", 1, "Alpha", division="div1", team="Reds")
    _acc(db, "Season 15", "played", 2, "Bravo")
    _acc(db, "Season 15", "fantasy_winner", user_id=9, username="ghost")
    original = database.backup_sqlite_db
    import routers.admin_season as admin_season
    admin_season.backup_sqlite_db = lambda: "/tmp/fake-backup.db"
    try:
        result = reset_season(SeasonResetBody(force=True), db=db, admin=dict(_ADMIN))
    finally:
        admin_season.backup_sqlite_db = original
    assert result["kept"] == {"season_accolades": 3}
    assert db.query(Player).count() == 0  # the season itself is gone
    assert len(_rows(db)) == 3
    assert "kept_season_accolades=3" in _audits(db, "admin_season_reset")[0].detail


def test_accolades_render_from_row_names_after_players_and_users_deleted(db):
    """With players, teams, cards and users gone or renamed, accolade readers (GET /accolades, GET /history/seasons) still return the names stored on the rows."""
    _acc(db, "Season 15", "champion", 10, "Glete", division="div1", team="Kanat")
    _acc(db, "Season 15", "best_match", 11, "ImperialZod", value=55.5, match_id=123)
    _acc(db, "Season 15", "fantasy_winner", user_id=99, username="Jiri")
    # A pool player renamed since: readers keep the name stored on the row.
    db.add(Player(id=11, name="Renamed Now"))
    db.commit()
    client = _client(db)
    pips = client.get("/accolades").json()["players"]
    assert pips["10"][0]["team_name"] == "Kanat" and pips["10"][0]["kind"] == "champion"
    hist = client.get("/history/seasons").json()
    season = hist["seasons"][0]
    assert season["champions"]["div1"] == {"team_name": "Kanat",
                                           "players": [{"account_id": 10, "name": "Glete"}]}
    assert season["awards"]["best_match"][0]["player_name"] == "ImperialZod"
    assert season["awards"]["fantasy_winner"] == [{"username": "Jiri", "value": None}]
    assert {f["player_name"] for f in hist["hall_of_fame"]} == {"Glete", "ImperialZod"}


# ===========================================================================
# Story 2: End Season Records Champions and Accolades
# ===========================================================================

def test_accolades_preview_returns_awards_played_count_and_teams(db):
    """GET /admin/season/accolades-preview returns most_points, best_average, best_match, fantasy_winner, the played count and each team with its players (player_match_stats.team_id)."""
    _seed_season(db)
    client, _ = _admin_client(db)
    data = client.get("/admin/season/accolades-preview").json()
    assert data["awards"]["most_points"] == [{"player_account_id": 1, "player_name": "Alpha", "value": 60.0}]
    assert data["awards"]["best_average"][0]["player_account_id"] == 3
    assert data["awards"]["best_match"][0]["player_account_id"] == 2
    assert data["awards"]["fantasy_winner"] == []
    assert data["played_count"] == 3
    teams = {t["team_name"]: sorted(p["account_id"] for p in t["players"]) for t in data["teams"]}
    assert teams == {"Reds": [1, 2], "Blues": [3, 4]}
    assert data["season_label"] == "Season 1"


def test_accolades_preview_requires_admin(db):
    """GET /admin/season/accolades-preview answers 401/403 for anonymous and non-admin users."""
    assert _client(db).get("/admin/season/accolades-preview").status_code == 401
    bob = _user(db, "bob")
    assert _client(db, login=bob).get("/admin/season/accolades-preview").status_code == 403


def test_compute_awards_uses_raw_points_of_scored_matches(db):
    """compute_awards picks most_points and best_match from raw fantasy_points of scored matches only."""
    _seed_season(db)
    awards = accolades.compute_awards(db)
    # Delta's 999 is in an excluded match, so it wins nothing.
    assert [a["player_account_id"] for a in awards["most_points"]] == [1]
    assert awards["most_points"][0]["value"] == 60.0
    assert awards["best_match"] == [{"player_account_id": 2, "player_name": "Bravo",
                                     "value": 50.0, "match_id": 1001}]


def test_compute_awards_best_average_requires_half_of_max_matches(db):
    """best_average ignores players with fewer than ceil(max_matches / 2) scored matches."""
    _seed_season(db)
    awards = accolades.compute_awards(db)
    # Bravo averages 50 over 1 match, below ceil(3 / 2) = 2 matches; Charlie averages 25 over 2.
    assert [a["player_account_id"] for a in awards["best_average"]] == [3]
    assert awards["best_average"][0]["value"] == 25.0


def test_compute_awards_records_all_tied_winners(db):
    """Ties in any award return every tied player (or user for fantasy_winner)."""
    stats = [(1, 100, 1001, 20.0), (1, 100, 1002, 20.0), (2, 100, 1001, 20.0), (2, 100, 1002, 20.0)]
    _seed_season(db, stats=stats, players={1: "Alpha", 2: "Bravo"})
    import routers.leaderboard as lb
    original = lb.compute_season_standings
    lb.compute_season_standings = lambda db: [{"id": 5, "username": "jiri", "points": 80.0},
                                              {"id": 6, "username": "bob", "points": 80.0},
                                              {"id": 7, "username": "carl", "points": 10.0}]
    try:
        awards = accolades.compute_awards(db)
    finally:
        lb.compute_season_standings = original
    for kind in ("most_points", "best_average", "best_match"):
        assert [a["player_account_id"] for a in awards[kind]] == [1, 2], kind
    assert [w["username"] for w in awards["fantasy_winner"]] == ["bob", "jiri"]


def test_played_player_ids_only_players_with_scored_match(db):
    """played_player_ids returns every player with >=1 scored match and no one else (unscored-only players excluded)."""
    _seed_season(db)
    assert accolades.played_player_ids(db) == [1, 2, 3]


def test_season_end_records_awards_champions_and_played(db):
    """POST /admin/season/end with champions inserts awards, champion rows and one played row per player, all with source='season_end'."""
    _seed_season(db)
    result = _end(db, champions=[{"division": "div1", "team_name": "Reds", "player_account_ids": [1, 2]}])
    assert result["champions"] == 2 and result["played"] == 3 and result["awards"] == 3
    rows = _rows(db, season_label="Season 16")
    assert {r.source for r in rows} == {"season_end"}
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r.kind, []).append(r)
    assert sorted(r.player_account_id for r in by_kind["played"]) == [1, 2, 3]
    assert sorted((r.player_account_id, r.player_name, r.team_name, r.division) for r in by_kind["champion"]) == [
        (1, "Alpha", "Reds", "div1"), (2, "Bravo", "Reds", "div1")]
    assert by_kind["most_points"][0].player_account_id == 1
    assert by_kind["best_match"][0].match_id == 1001


def test_season_end_grants_season_winner_tag_to_fantasy_winners(db, monkeypatch):
    """Each fantasy winner gets the existing `season_winner` user tag at End Season."""
    _seed_season(db)
    jiri = _user(db, "jiri")
    _standings(monkeypatch, [{"id": jiri.id, "username": "jiri", "points": 120.0}])
    _end(db)
    tag = db.query(TagDefinition).filter_by(key="season_winner").one()
    assert db.query(UserTag).filter_by(user_id=jiri.id, tag_id=tag.id).count() == 1
    fw = _rows(db, kind="fantasy_winner")
    assert [(r.user_id, r.username, r.value) for r in fw] == [(jiri.id, "jiri", 120.0)]


def test_season_end_without_champions_still_records_awards(db):
    """Champions are optional: End Season without `champions` records awards and played rows and no champion rows."""
    _seed_season(db)
    result = _end(db)
    assert result["champions"] == 0
    assert result["warning"] == "No champions recorded; add them in Player management"
    assert len(_rows(db, kind="played")) == 3
    assert len(_rows(db, kind="most_points")) == 1
    assert _rows(db, kind="champion") == []


def test_season_end_is_atomic_when_accolade_insert_fails(db, monkeypatch):
    """If recording accolades fails, neither the season_archive rows nor any accolade rows are committed."""
    _seed_season(db)
    _user(db, "alice")

    def boom(*args, **kwargs):
        db.add(SeasonAccolade(season_label="Season 16", kind="played", player_account_id=1,
                              player_name="Alpha", source="season_end"))
        db.flush()
        raise RuntimeError("insert failed")
    monkeypatch.setattr(accolades, "record_season", boom)
    with pytest.raises(HTTPException) as exc:
        _end(db)
    assert exc.value.status_code == 500
    assert exc.value.detail == "Recording accolades failed; nothing was archived"  # no exception name
    db.expire_all()
    assert db.query(SeasonArchive).count() == 0
    assert db.query(SeasonAccolade).count() == 0


def test_season_end_empty_season_records_no_awards(db):
    """With no scored matches, End Season records no awards and no played rows and says so in the response."""
    _user(db, "alice")
    result = _end(db)
    assert result["accolades"] == 0 and result["played"] == 0
    assert result["note"] == "No scored matches: no awards or played rows recorded"
    assert db.query(SeasonAccolade).count() == 0


def test_season_end_rejects_invalid_champion_division(db):
    """`champions` with a division other than div1/div2 (or bad account ids) answers 422 and records nothing."""
    _seed_season(db)
    client, _ = _admin_client(db)
    for champions in ([{"division": "div3", "team_name": "Reds", "player_account_ids": [1]}],
                      [{"division": "div1", "team_name": "Reds", "player_account_ids": [0]}],
                      [{"division": "div1", "team_name": "Reds", "player_account_ids": [2**63]}]):
        resp = client.post("/admin/season/end", json={"season_label": "Season 16", "confirm": "END SEASON",
                                                      "champions": champions})
        assert resp.status_code == 422, resp.text
    db.expire_all()
    assert db.query(SeasonArchive).count() == 0 and db.query(SeasonAccolade).count() == 0


def test_season_end_audit_detail_counts_accolades_and_champions(db):
    """The admin_season_archived audit detail includes `accolades=N champions=M`."""
    _seed_season(db)
    _end(db, champions=[{"division": "div2", "team_name": "Blues", "player_account_ids": [3, 4]}])
    detail = _audits(db, "admin_season_archived")[0].detail
    assert "accolades=8 champions=2" in detail  # 3 awards + 2 champions + 3 played


def test_end_season_dialog_champion_picker_and_warning_source():
    """Source-reading (app-admin-season.js): the End Season dialog shows awards and Played count, Div 1 / Div 2 team pickers with pre-ticked players and add-by-id, and the 'No champions recorded; add them in Player management' warning before the END SEASON confirmation."""
    js = _fe("app-admin-season.js")
    html = _fe("index.html")
    opener = _fn_body(js, "endSeason")
    assert "/admin/season/accolades-preview" in opener
    assert "endSeasonAwards" in opener and "endSeasonPlayed" in opener and "played_count" in opener
    for div in ("div1", "div2"):
        assert f'id="endSeasonTeam_{div}"' in html and f'id="endSeasonAdd_{div}"' in html
    pick = _fn_body(js, "endSeasonPickTeam")
    assert "checked: true" in pick  # the team's players come pre-ticked
    assert "endSeasonTogglePlayer" in js and "function endSeasonAddPlayer(" in js
    assert "No champions recorded; add them in Player management" in html
    confirm = _fn_body(js, "confirmEndSeason")
    assert confirm.index("_endSeasonChampions()") < confirm.index('typedConfirm("season_end"')
    assert "champions" in confirm[confirm.index("JSON.stringify"):]


# ===========================================================================
# Story 3: Admins Manage Champions and Accolades
# ===========================================================================

# --- PUT /admin/season-champions -------------------------------------------

def test_put_season_champions_creates_set(db):
    """PUT /admin/season-champions with {season_label, division, team_name, players} writes one champion row per player with the given names."""
    client, _ = _admin_client(db)
    resp = _put(client, [(1, "Alpha"), (2, "Bravo")])
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == 2
    rows = _rows(db, kind="champion")
    assert sorted((r.player_account_id, r.player_name, r.team_name, r.division, r.season_label, r.source) for r in rows) == [
        (1, "Alpha", "Reds", "div1", "Season 16", "admin"), (2, "Bravo", "Reds", "div1", "Season 16", "admin")]


def test_put_season_champions_replaces_set_in_one_save(db):
    """Saving again adds new players, deletes removed ones, and updates names and team name in one transaction."""
    client, _ = _admin_client(db)
    _put(client, [(1, "Alpha"), (2, "Bravo"), (3, "Charlie")])
    resp = _put(client, [(1, "Alpha Prime"), (2, "Bravo"), (4, "Delta")], team="Reds United")
    assert resp.json()["added"] == 1 and resp.json()["removed"] == 1
    rows = _rows(db, kind="champion")
    assert sorted((r.player_account_id, r.player_name, r.team_name) for r in rows) == [
        (1, "Alpha Prime", "Reds United"), (2, "Bravo", "Reds United"), (4, "Delta", "Reds United")]


def test_put_season_champions_past_season_players_not_in_pool(db):
    """A past season (e.g. 'Season 15') saves with typed team name and OpenDota ids that don't exist in players/teams."""
    client, _ = _admin_client(db)
    resp = _put(client, [(555001, "Old Timer"), (555002, "Legend")], label="Season 15", team="Gone FC")
    assert resp.status_code == 200, resp.text
    assert db.query(Player).count() == 0 and db.query(Team).count() == 0
    assert {r.player_name for r in _rows(db, season_label="Season 15")} == {"Old Timer", "Legend"}


def test_put_season_champions_allows_more_than_five_players(db):
    """No fixed size: six players (a stand-in) are accepted."""
    client, _ = _admin_client(db)
    resp = _put(client, [(i, f"P{i}") for i in range(1, 7)])
    assert resp.status_code == 200 and resp.json()["players"] == 6
    assert len(_rows(db, kind="champion")) == 6


def test_put_season_champions_empty_list_clears_division(db):
    """An empty `players` list removes that season and division's champions only."""
    client, _ = _admin_client(db)
    _put(client, [(1, "Alpha")], division="div1")
    _put(client, [(2, "Bravo")], division="div2", team="Blues")
    _put(client, [(9, "Old")], label="Season 15", division="div1")
    resp = _put(client, [], division="div1", team="")
    assert resp.status_code == 200 and resp.json()["removed"] == 1
    left = sorted((r.season_label, r.division) for r in _rows(db, kind="champion"))
    assert left == [("Season 15", "div1"), ("Season 16", "div2")]


def test_put_season_champions_rejects_duplicate_ids(db):
    """The same account_id twice in `players` answers 422 and changes nothing."""
    client, _ = _admin_client(db)
    _put(client, [(1, "Alpha")])
    resp = _put(client, [(2, "Bravo"), (2, "Bravo again")])
    assert resp.status_code == 422
    assert [r.player_account_id for r in _rows(db, kind="champion")] == [1]


def test_put_season_champions_rejects_non_positive_or_oversized_ids(db):
    """account_id <= 0, non-integer or > 2**63-1 answers 422 (not 500)."""
    client, _ = _admin_client(db)
    for bad in (0, -5, 2**63, "abc", 1.5):
        resp = client.put("/admin/season-champions", json={
            "season_label": "Season 16", "division": "div1", "team_name": "Reds",
            "players": [{"account_id": bad, "name": "X"}]})
        assert resp.status_code == 422, (bad, resp.status_code)
    assert _rows(db) == []


def test_put_season_champions_rejects_missing_name(db):
    """A player row with an empty name answers 422."""
    client, _ = _admin_client(db)
    assert _put(client, [(1, "   ")]).status_code == 422
    assert _put(client, [(1, "")]).status_code == 422
    assert _rows(db) == []


def test_put_season_champions_rejects_invalid_division(db):
    """A division other than div1/div2 answers 422."""
    client, _ = _admin_client(db)
    assert _put(client, [(1, "Alpha")], division="div3").status_code == 422
    assert _rows(db) == []


def test_put_season_champions_requires_recent_reauth(db):
    """Admin without a recent re-auth gets the re-auth error; a non-admin gets 403."""
    client, _ = _admin_client(db, reauth=False)
    resp = _put(client, [(1, "Alpha")])
    assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"
    bob = _user(db, "bob")
    assert _put(_client(db, login=bob), [(1, "Alpha")]).status_code == 403
    assert _rows(db) == []


def test_put_season_champions_audit_counts_added_and_removed(db):
    """One admin_champions_set audit entry names the season, division and added / removed counts."""
    client, _ = _admin_client(db)
    _put(client, [(1, "Alpha"), (2, "Bravo")])
    _put(client, [(2, "Bravo"), (3, "Charlie"), (4, "Delta")])
    entries = _audits(db, "admin_champions_set")
    assert len(entries) == 2
    assert "season_label=Season 16 division=div1" in entries[1].detail
    assert "added=2 removed=1" in entries[1].detail


def test_holo_eligible_true_once_past_champion_recorded(db):
    """holo_eligible(db, player_id) is true as soon as a past-season champion row exists for that player."""
    db.add(Player(id=7, name="Glete"))
    db.commit()
    assert accolades.holo_eligible(db, 7) is False
    client, _ = _admin_client(db)
    _put(client, [(7, "Glete")], label="Season 15")
    db.expire_all()
    assert accolades.holo_eligible(db, 7) is True


def test_holo_eligible_false_after_removed_from_champion_set_existing_holo_kept(db):
    """A player removed via PUT loses eligibility for future draws; cards already drawn with is_holo stay Holo."""
    client, _ = _admin_client(db)
    db.add(Player(id=7, name="Glete"))
    db.add(Card(player_id=7, owner_id=1, card_type="legendary", is_holo=True))
    db.commit()
    _put(client, [(7, "Glete"), (8, "Other")], label="Season 15")
    assert accolades.holo_eligible(db, 7) is True
    _put(client, [(8, "Other")], label="Season 15")
    db.expire_all()
    assert accolades.holo_eligible(db, 7) is False
    assert db.query(Card).filter_by(player_id=7).one().is_holo is True


# --- /admin/season-accolades -----------------------------------------------

def test_post_season_accolades_adds_single_row(db):
    """POST /admin/season-accolades adds one row (player award with value) with source='admin' and an admin_accolade_added audit entry."""
    client, admin = _admin_client(db)
    resp = client.post("/admin/season-accolades", json={
        "season_label": "Season 15", "kind": "most_points", "player_account_id": 7,
        "player_name": "Glete", "value": 61.5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["kind"], body["player_name"], body["value"], body["source"]) == ("most_points", "Glete", 61.5, "admin")
    row = _rows(db)[0]
    assert row.created_by == admin.id and row.source == "admin"
    audit = _audits(db, "admin_accolade_added")
    assert len(audit) == 1 and "season_label=Season 15 kind=most_points added=1" in audit[0].detail


def test_post_season_accolades_bulk_played_list(db):
    """POST with a list of played rows (several OpenDota ids with names) inserts them all."""
    client, _ = _admin_client(db)
    rows = [{"season_label": "Season 3", "kind": "played", "player_account_id": i, "player_name": f"P{i}"}
            for i in (101, 102, 103)]
    resp = client.post("/admin/season-accolades", json=rows)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"added": 3, "skipped": 0}
    assert sorted(r.player_account_id for r in _rows(db, kind="played")) == [101, 102, 103]
    # A pasted list may overlap rows already recorded: those are skipped, not an error.
    again = client.post("/admin/season-accolades", json=rows[:1] + [
        {"season_label": "Season 3", "kind": "played", "player_account_id": 104, "player_name": "P104"}])
    assert again.json() == {"added": 1, "skipped": 1}


def test_post_season_accolades_fantasy_winner_requires_user(db):
    """kind=fantasy_winner needs a user (user_id/username); a player-only body answers 422."""
    client, _ = _admin_client(db)
    resp = client.post("/admin/season-accolades", json={
        "season_label": "Season 15", "kind": "fantasy_winner", "player_account_id": 7, "player_name": "Glete"})
    assert resp.status_code == 422
    resp = client.post("/admin/season-accolades", json={
        "season_label": "Season 15", "kind": "fantasy_winner", "username": "nobody"})
    assert resp.status_code == 422  # no such user
    jiri = _user(db, "Jiri")
    resp = client.post("/admin/season-accolades", json={
        "season_label": "Season 15", "kind": "fantasy_winner", "username": "jiri", "value": 140})
    assert resp.status_code == 200, resp.text
    row = _rows(db, kind="fantasy_winner")[0]
    assert (row.user_id, row.username, row.player_account_id) == (jiri.id, "Jiri", None)


def test_post_season_accolades_rejects_invalid_kind_or_division(db):
    """Unknown kind, or a champion without a valid division, answers 422."""
    client, _ = _admin_client(db)
    bad = [
        {"season_label": "Season 15", "kind": "veteran", "player_account_id": 7, "player_name": "G"},
        {"season_label": "Season 15", "kind": "champion", "player_account_id": 7, "player_name": "G", "team_name": "T"},
        {"season_label": "Season 15", "kind": "champion", "division": "div9", "player_account_id": 7,
         "player_name": "G", "team_name": "T"},
        {"season_label": "Season 15", "kind": "most_points", "division": "div1", "player_account_id": 7,
         "player_name": "G"},
    ]
    for body in bad:
        assert client.post("/admin/season-accolades", json=body).status_code == 422, body
    assert _rows(db) == []


def test_post_season_accolades_duplicate_returns_409(db):
    """Adding a row that matches the unique key answers 409."""
    client, _ = _admin_client(db)
    body = {"season_label": "Season 15", "kind": "best_match", "player_account_id": 7,
            "player_name": "Glete", "value": 50, "match_id": 99}
    assert client.post("/admin/season-accolades", json=body).status_code == 200
    resp = client.post("/admin/season-accolades", json=body)
    assert resp.status_code == 409
    assert len(_rows(db)) == 1


def test_post_season_accolades_requires_recent_reauth(db):
    """POST /admin/season-accolades without recent re-auth is refused; non-admin gets 403."""
    body = {"season_label": "Season 15", "kind": "played", "player_account_id": 7, "player_name": "G"}
    client, _ = _admin_client(db, reauth=False)
    resp = client.post("/admin/season-accolades", json=body)
    assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"
    bob = _user(db, "bob")
    assert _client(db, login=bob).post("/admin/season-accolades", json=body).status_code == 403
    assert _rows(db) == []


def test_get_season_accolades_filters_by_season_and_kind(db):
    """GET /admin/season-accolades?season=…&kind=… returns only matching rows."""
    _acc(db, "Season 15", "played", 1, "Alpha")
    _acc(db, "Season 15", "most_points", 1, "Alpha", value=60)
    _acc(db, "Season 14", "played", 1, "Alpha")
    client, _ = _admin_client(db)
    rows = client.get("/admin/season-accolades", params={"season": "Season 15", "kind": "played"}).json()
    assert [(r["season_label"], r["kind"]) for r in rows] == [("Season 15", "played")]
    assert len(client.get("/admin/season-accolades", params={"season": "Season 15"}).json()) == 2
    everything = client.get("/admin/season-accolades").json()
    assert [r["season_label"] for r in everything] == ["Season 15", "Season 15", "Season 14"]


def test_get_season_accolades_requires_admin(db):
    """GET /admin/season-accolades answers 403 for a non-admin."""
    bob = _user(db, "bob")
    assert _client(db, login=bob).get("/admin/season-accolades").status_code == 403
    assert _client(db).get("/admin/season-accolades").status_code == 401


def test_patch_season_accolade_updates_value_name_team(db):
    """PATCH /admin/season-accolades/{id} updates value, name and team name, with re-auth and an audit entry."""
    row = _acc(db, "Season 15", "champion", 7, "Glete", division="div1", team="Kanat")
    client, _ = _admin_client(db)
    resp = client.patch(f"/admin/season-accolades/{row.id}",
                        json={"value": 3, "player_name": "Glete K", "team_name": "Kanat FC"})
    assert resp.status_code == 200, resp.text
    db.expire_all()
    fresh = db.get(SeasonAccolade, row.id)
    assert (fresh.value, fresh.player_name, fresh.team_name) == (3, "Glete K", "Kanat FC")
    assert len(_audits(db, "admin_accolade_updated")) == 1
    noauth, _ = _admin_client(db, reauth=False)
    assert noauth.patch(f"/admin/season-accolades/{row.id}", json={"value": 9}).status_code == 403


def test_patch_season_accolade_unknown_id_returns_404(db):
    """PATCH on a missing id answers 404."""
    client, _ = _admin_client(db)
    assert client.patch("/admin/season-accolades/999", json={"value": 1}).status_code == 404
    assert client.patch(f"/admin/season-accolades/{2**63}", json={"value": 1}).status_code == 422


def test_delete_season_accolade_removes_row_with_audit(db):
    """DELETE /admin/season-accolades/{id} removes the row and writes admin_accolade_removed."""
    row = _acc(db, "Season 15", "played", 7, "Glete")
    client, _ = _admin_client(db)
    resp = client.delete(f"/admin/season-accolades/{row.id}")
    assert resp.status_code == 200
    assert _rows(db) == []
    audit = _audits(db, "admin_accolade_removed")
    assert len(audit) == 1 and "kind=played" in audit[0].detail


def test_delete_fantasy_winner_accolade_keeps_season_winner_tag(db):
    """Removing a fantasy_winner row doesn't remove a season_winner tag already granted."""
    jiri = _user(db, "jiri")
    accolades.grant_winner_tag(db, jiri.id, None)
    db.commit()
    row = _acc(db, "Season 15", "fantasy_winner", user_id=jiri.id, username="jiri")
    client, _ = _admin_client(db)
    assert client.delete(f"/admin/season-accolades/{row.id}").status_code == 200
    db.expire_all()
    tag = db.query(TagDefinition).filter_by(key="season_winner").one()
    assert db.query(UserTag).filter_by(user_id=jiri.id, tag_id=tag.id).count() == 1


def test_delete_season_accolade_unknown_id_returns_404(db):
    """DELETE on a missing id answers 404."""
    client, _ = _admin_client(db)
    assert client.delete("/admin/season-accolades/12345").status_code == 404


# --- Frontend: Player management --------------------------------------------

def test_admin_players_mark_champions_and_add_accolade_buttons():
    """Source-reading (index.html / app-admin-players.js): Mark champions and Add accolade buttons sit next to Add in Player management."""
    html = _fe("index.html")
    start = html.index('data-admin-tab="player-management"')
    section = html[start:html.index("<!-- Audit Log tab -->", start)]
    add = section.index('onclick="openAddPlayerPopup()">Add</button>')
    assert section.index('onclick="openMarkChampions()">Mark champions</button>') > add
    assert section.index('onclick="openAddAccolade()">Add accolade</button>') > add
    assert section.index("openAddAccolade()") < section.index("openBulkAddPlayersPopup()")
    js = _fe("app-admin-players.js")
    assert "async function openMarkChampions(" in js and "async function openAddAccolade(" in js


def test_admin_players_mark_champions_two_modes_and_roster_editor():
    """Source-reading (app-admin-players.js): Mark champions offers 'From this season' (team prefill) and 'Past season' (typed team, ids), ending in one roster editor with + Add player, Remove and the 'N players (usually 5)' note; saving calls PUT /admin/season-champions.
    Issue 214 removed the paste box (champPaste); + Add player stays."""
    html = _fe("index.html")
    js = _fe("app-admin-players.js")
    modal = html[html.index('id="markChampionsModal"'):html.index("<!-- Player Management: Add accolade")]
    assert "From this season" in modal and "Past season" in modal
    assert 'id="champTeamPick"' in modal and 'id="champTeamName"' in modal
    assert "+ Add player" in modal and 'id="champPaste"' not in modal
    row = _fn_body(js, "_champRowHtml")
    assert "Remove" in row and "champ-id" in row and "champ-name" in row
    assert "(usually 5)" in _fn_body(js, "_updateChampCount")
    assert "team.players" in _fn_body(js, "champPickTeam")  # this season: the team's players pre-fill
    assert "Season ${i}" in _fn_body(js, "_fillChampSeasons")  # past season: Season 1 to the last ended
    save = _fn_body(js, "saveChampions")
    assert "validateChampionRoster(rows)" in save
    assert '/admin/season-champions' in save and 'method: "PUT"' in save
    assert "_knownPlayerName" in _fn_body(js, "champIdTyped")


def test_admin_players_roster_editor_validation_rejects_bad_rows():
    """Node harness (app-admin-players.js validator): non-positive or duplicate ids and empty names block saving with a message."""
    fn = _fn_source(_fe("app-admin-players.js"), "validateChampionRoster")
    cases = {
        "ok": [{"account_id": "123", "name": "Glete"}, {"account_id": " 456 ", "name": "Jiri"}],
        "zero": [{"account_id": "0", "name": "X"}],
        "negative": [{"account_id": "-4", "name": "X"}],
        "text": [{"account_id": "abc", "name": "X"}],
        "decimal": [{"account_id": "1.5", "name": "X"}],
        "dup": [{"account_id": "7", "name": "A"}, {"account_id": "7", "name": "B"}],
        "noname": [{"account_id": "8", "name": "  "}],
        "empty": [],
    }
    out = _run_node(fn + f"\nconst cases = {json.dumps(cases)};\n"
                    "const out = {}; for (const k in cases) out[k] = validateChampionRoster(cases[k]);\n"
                    "console.log(JSON.stringify(out));")
    assert out["ok"] is None and out["empty"] is None
    for k in ("zero", "negative", "text", "decimal"):
        assert "positive whole number" in out[k], k
    assert "listed twice" in out["dup"]
    assert "needs a name" in out["noname"]


def test_admin_players_accolade_table_groups_champions_with_edit_remove():
    """Source-reading (app-admin-players.js): 'Champions and accolades' table groups a season+division into one '[Team] · N players' row whose Edit opens Mark champions filled in and whose Remove confirms before clearing."""
    js = _fe("app-admin-players.js")
    html = _fe("index.html")
    assert "Champions and accolades" in html
    assert "<th>Season</th><th>Title</th><th>Winner</th><th>Value</th><th>Source</th>" in html
    group = _fn_body(js, "_accoladeTableRows")
    assert 'r.kind !== "champion"' in group and "season_label" in group and "division" in group
    table = _fn_body(js, "_renderAccoladeTable")
    assert "player${n === 1 ? \"\" : \"s\"}" in table and "editChampionSet(" in table and "removeChampionSet(" in table
    assert "openMarkChampions(" in _fn_body(js, "editChampionSet")
    remove = _fn_body(js, "removeChampionSet")
    assert remove.index("confirm(") < remove.index("adminFetch(")
    assert "players: []" in remove
    # Run the grouping on sample rows.
    out = _run_node(_fn_source(js, "_accoladeTableRows") + """
const rows = [
  {kind: "champion", season_label: "Season 15", division: "div1", team_name: "Reds", player_account_id: 1, player_name: "A"},
  {kind: "most_points", season_label: "Season 15", player_account_id: 1, player_name: "A"},
  {kind: "champion", season_label: "Season 15", division: "div1", team_name: "Reds", player_account_id: 2, player_name: "B"},
  {kind: "champion", season_label: "Season 15", division: "div2", team_name: "Blues", player_account_id: 3, player_name: "C"},
];
console.log(JSON.stringify(_accoladeTableRows(rows).map(r => r.type === "champions" ? [r.division, r.players.length] : r.row.kind)));
""")
    assert out == [["div1", 2], "most_points", ["div2", 1]]


# ===========================================================================
# Story 4: Seasons Played Are Backfilled (backend/scripts/backfill_played.py)
# ===========================================================================

def test_backfill_played_records_one_row_per_account_both_leagues(db, tmp_path, monkeypatch):
    """Two --league ids for one --season: every account_id from both leagues' matches gets one played row with source='admin'."""
    r = _run_backfill(db, tmp_path, monkeypatch)
    assert r.code == 0
    rows = _rows(db, kind="played", season_label="Season 14")
    assert sorted(x.player_account_id for x in rows) == [10, 11, 12, 13]
    assert {x.source for x in rows} == {"admin"}


def test_backfill_played_dry_run_writes_nothing(db, tmp_path, monkeypatch):
    """--dry-run prints matches found, players, new rows and skipped anonymous slots, and writes no rows or audit entries."""
    r = _run_backfill(db, tmp_path, monkeypatch, dry_run=True)
    assert "Dry run" in r.out
    assert "Season 14: 3 matches, 4 players, 4 new rows, 2 anonymous slots skipped" in r.out
    assert _rows(db) == [] and _audits(db, "admin_accolade_added") == []


def test_backfill_played_rerun_adds_nothing(db, tmp_path, monkeypatch):
    """A second run leaves existing rows alone (ON CONFLICT DO NOTHING) and inserts zero new rows."""
    _run_backfill(db, tmp_path, monkeypatch)
    again = _run_backfill(db, tmp_path, monkeypatch)
    assert "0 new rows" in again.out
    assert len(_rows(db, kind="played")) == 4


def test_backfill_played_skips_and_counts_anonymous_accounts(db, tmp_path, monkeypatch):
    """Player slots without account_id are skipped and counted in the report."""
    r = _run_backfill(db, tmp_path, monkeypatch)
    assert "2 anonymous slots skipped" in r.out
    assert None not in {x.player_account_id for x in _rows(db)}


def test_backfill_played_names_from_pool_then_personaname_then_fallback(db, tmp_path, monkeypatch):
    """Name is the current pool name, else the match personaname, else 'Player <id>'."""
    db.add(Player(id=12, name="Pool Twelve"))
    db.commit()
    _run_backfill(db, tmp_path, monkeypatch)
    names = {x.player_account_id: x.player_name for x in _rows(db, kind="played")}
    assert names == {10: "tenpub", 11: "Player 11", 12: "Pool Twelve", 13: "thirteen"}


def test_backfill_played_cached_matches_not_refetched(db, tmp_path, monkeypatch):
    """Matches already in the local cache file are not fetched from OpenDota again on resume."""
    first = _run_backfill(db, tmp_path, monkeypatch, dry_run=True)
    assert sorted(first.fetched) == [9001, 9002, 9003]
    cache = json.loads((tmp_path / "cache.json").read_text())
    assert set(cache["matches"]) == {"9001", "9002", "9003"}
    assert cache["leagues"] == {"111": "Kanaliiga Season 14", "222": "Kanaliiga Season 14 Lower"}
    second = _run_backfill(db, tmp_path, monkeypatch)
    assert second.fetched == [] and second.infos == []  # league names come from the cache too
    assert len(_rows(db, kind="played")) == 4


def test_backfill_played_pauses_between_calls(db, tmp_path, monkeypatch):
    """The script sleeps between OpenDota calls (sleep patched and asserted)."""
    r = _run_backfill(db, tmp_path, monkeypatch)
    # Seven calls (two league names, two match lists, three matches): a wait before each after the first.
    assert r.sleeps == [0.5] * 6


def test_backfill_played_writes_one_audit_entry_per_season(db, tmp_path, monkeypatch):
    """One admin_accolade_added audit entry per season with detail 'played=N source=backfill'."""
    _run_backfill(db, tmp_path, monkeypatch)
    audit = _audits(db, "admin_accolade_added")
    assert [a.detail for a in audit] == ["season_label=Season 14 played=4 source=backfill"]
    assert audit[0].actor_username == "script"


def test_backfill_played_missing_league_reports_error_writes_nothing(db, tmp_path, monkeypatch):
    """A league OpenDota can't return (error / empty) reports the failure and writes no rows for it."""
    r = _run_backfill(db, tmp_path, monkeypatch, leagues=(333,))
    assert r.code == 1
    assert "league 333: OpenDota returned no matches; nothing recorded for it" in r.out
    assert _rows(db) == []
    # One good league and one missing: only the good league's players are recorded.
    mixed = _run_backfill(db, tmp_path, monkeypatch, leagues=(222, 333))
    assert mixed.code == 1
    assert [x.player_account_id for x in _rows(db)] == [13]


def test_backfill_played_requires_season_and_league_args():
    """Missing --season or --league exits non-zero with usage; no league ids are stored in the script.
    Follow-up: --season alone is now valid (it finds the leagues by name), and --league alone
    takes the season from the league names; giving neither, an empty --season or a bad id is the usage error."""
    mod = _backfill()
    for argv in ([], ["--season", "  "], ["--league", "0"], ["--league", "abc"], ["--dry-run"]):
        with pytest.raises(SystemExit) as exc:
            mod.main(argv)
        assert exc.value.code != 0
    src = _read("backend", "scripts", "backfill_played.py")
    # No league ids are stored in the script: no 4+ digit numbers at all.
    assert not re.search(r"\b\d{4,}\b", src)


# ===========================================================================
# Story 5: Cards Show Titles, and Champions' Legendaries Can Be Holo
# ===========================================================================

def test_draw_card_champion_legendary_becomes_holo_with_roll(db, monkeypatch):
    """draw_card for a past-season champion's Legendary with a mocked winning roll stores is_holo=True and card_type='legendary'."""
    user = _draw_setup(db)
    out = _draw(db, user, roll=0.0, monkeypatch=monkeypatch)
    assert out["is_holo"] is True and out["card_type"] == "legendary"
    card = db.get(Card, out["id"])
    assert card.is_holo is True and card.card_type == "legendary"


def test_draw_card_champion_legendary_not_holo_when_roll_fails(db, monkeypatch):
    """With a losing roll against holo_chance, the champion's Legendary is a plain Legendary."""
    user = _draw_setup(db)
    out = _draw(db, user, roll=0.2, monkeypatch=monkeypatch)  # 20.0 is not below holo_chance 20
    assert out["is_holo"] is False
    assert db.get(Card, out["id"]).is_holo is False


def test_draw_card_current_season_champion_not_holo(db, monkeypatch):
    """A champion row only in the current season does not make the player Holo-eligible."""
    user = _draw_setup(db, champion_season="Season 16")
    _acc(db, "Season 15", "played", 7, "Glete")  # the live season is therefore Season 16
    assert accolades.current_season_label(db) == "Season 16"
    out = _draw(db, user, roll=0.0, monkeypatch=monkeypatch)
    assert out["is_holo"] is False


def test_draw_card_award_winner_not_champion_never_holo(db, monkeypatch):
    """A most_points / best_match winner without a champion accolade never gets is_holo, even with a forced roll."""
    user = _draw_setup(db, champion_season=None)
    _acc(db, "Season 15", "most_points", 7, "Glete", value=60)
    _acc(db, "Season 15", "best_match", 7, "Glete", value=40)
    out = _draw(db, user, roll=0.0, monkeypatch=monkeypatch)
    assert out["is_holo"] is False


def test_draw_card_non_legendary_never_holo(db, monkeypatch):
    """Common, rare and epic cards of a champion are never Holo."""
    user = _draw_setup(db)
    for rarity in ("common", "rare", "epic"):
        out = _draw(db, user, rarity=rarity, roll=0.0, monkeypatch=monkeypatch)
        assert out["is_holo"] is False and out["card_type"] == rarity


def test_draw_card_holo_chance_zero_disables_holo(db, monkeypatch):
    """With weights.holo_chance = 0 no card is ever Holo."""
    user = _draw_setup(db, holo_chance=0.0)
    out = _draw(db, user, roll=0.0, monkeypatch=monkeypatch)
    assert out["is_holo"] is False


def test_draw_booster_champion_legendary_can_be_holo(db, monkeypatch):
    """draw_booster applies the same Holo roll to a champion's Legendary."""
    user = _draw_setup(db)
    out = _draw(db, user, roll=0.0, monkeypatch=monkeypatch, booster=True)
    assert out["is_holo"] is True and out["card_type"] == "legendary"
    lose = _draw(db, user, roll=0.99, monkeypatch=monkeypatch, booster=True)
    assert lose["is_holo"] is False


def test_seed_holo_chance_weight_defaults_to_20(db, monkeypatch):
    """seed adds a `holo_chance` weights row with default 20, shown in Scoring config."""
    import seed
    from seed import DEFAULT_WEIGHTS
    assert next(w for w in DEFAULT_WEIGHTS if w["key"] == "holo_chance")["value"] == 20.0
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.delenv("WEIGHTS_JSON", raising=False)
    seed.seed_weights()
    db.expire_all()
    w = db.get(Weight, "holo_chance")
    assert w.value == 20.0 and "Holo" in w.label
    # Scoring config lists every weight (GET /weights), so it shows there too.
    from routers.leaderboard import get_weights
    assert any(x["key"] == "holo_chance" for x in get_weights(db=db))


def test_holo_card_scored_like_legendary(db):
    """A Holo card's points and modifiers equal a non-Holo Legendary of the same player."""
    import card_points
    _weights(db)
    db.add(Player(id=7, name="Glete"))
    db.add(Match(match_id=1, start_time=1000, radiant_team_id=1, dire_team_id=2))
    db.add(PlayerMatchStats(player_id=7, match_id=1, team_id=1, fantasy_points=30.0, kills=10,
                            assists=5, deaths=2, gold_per_min=600, last_hits=200))
    plain = Card(player_id=7, owner_id=1, card_type="legendary", is_holo=False)
    holo = Card(player_id=7, owner_id=2, card_type="legendary", is_holo=True)
    db.add_all([plain, holo])
    db.flush()
    for c in (plain, holo):
        db.add(CardModifier(card_id=c.id, stat_key="kills", bonus_pct=10.0))
    db.commit()
    card_points.rebuild_all(db)
    pts = {r.card_id: r.points for r in db.query(CardMatchPoints).all()}
    assert pts[plain.id] > 0 and pts[holo.id] == pts[plain.id]


def test_holo_card_roster_rules_and_deck_counts_unchanged(db):
    """Holo counts as legendary for roster rules, GET /deck and booster counts."""
    import routers.cards as cards
    user = _draw_setup(db)
    db.add(Player(id=8, name="Other", is_active=True))
    holo = Card(player_id=7, owner_id=user.id, card_type="legendary", is_holo=True, is_active=False)
    db.add(holo)
    db.commit()
    client = _client(db, login=user)
    deck = client.get("/deck").json()
    assert deck["legendary"] == 1 and deck["common"] == 2  # the Holo card is a legendary combo
    cu = {"user_id": user.id, "username": user.username, "is_admin": False}
    assert cards.activate_card(holo.id, db, cu)["status"] == "ok"
    # A second card of the same player still can't join the roster beside it.
    other = Card(player_id=7, owner_id=user.id, card_type="common", is_active=False)
    db.add(other)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        cards.activate_card(other.id, db, cu)
    assert exc.value.status_code == 409
    booster = {t["team_id"]: t["remaining"] for t in cards.booster_deck_for_user(db, user.id)}
    assert booster[300] == 0  # Glete is owned, Holo or not


def test_card_responses_include_is_holo(db, monkeypatch):
    """Draw, roster, collection and card detail responses include is_holo."""
    import routers.cards as cards
    user = _draw_setup(db)
    drawn = _draw(db, user, roll=0.0, monkeypatch=monkeypatch)
    assert drawn["is_holo"] is True
    cu = {"user_id": user.id, "username": user.username, "is_admin": False}
    roster = cards._build_roster_response(db, user.id, None)
    assert [c["is_holo"] for c in roster["active"] + roster["bench"]] == [True]
    assert [c["is_holo"] for c in cards.collection_for_user(db, user.id)] == [True]
    detail = cards.get_card(drawn["id"], db=db, current_user=cu)
    assert detail["is_holo"] is True


def test_image_holo_uses_template_when_present(tmp_path, monkeypatch):
    """image.py uses Card_Template_Holo.png for a Holo card when the file exists."""
    image = pytest.importorskip("image")
    if not image.PIL_AVAILABLE:
        pytest.skip("Pillow not installed")
    from PIL import Image
    for name in ("Legendary", "Epic"):
        shutil.copy(os.path.join(image._ASSETS_DIR, f"Card_Template_{name}.png"), tmp_path)
    Image.new("RGBA", (597, 845), (255, 0, 0, 255)).save(tmp_path / "Card_Template_Holo.png")
    monkeypatch.setattr(image, "_ASSETS_DIR", str(tmp_path))
    assert image._load_template("legendary", True).getpixel((5, 5)) == (255, 0, 0, 255)
    # A non-Holo Legendary, and a "Holo" flag on another rarity, keep their own template.
    assert image._load_template("legendary", False).getpixel((5, 5)) != (255, 0, 0, 255)
    assert image._load_template("epic", True).getpixel((5, 5)) != (255, 0, 0, 255)


def test_image_holo_fallback_sheen_warns_once(tmp_path, monkeypatch, caplog):
    """Without Card_Template_Holo.png, Holo uses the Legendary template plus a sheen and logs one warning only."""
    import logging
    image = pytest.importorskip("image")
    if not image.PIL_AVAILABLE:
        pytest.skip("Pillow not installed")
    from PIL import ImageChops
    shutil.copy(os.path.join(image._ASSETS_DIR, "Card_Template_Legendary.png"), tmp_path)
    monkeypatch.setattr(image, "_ASSETS_DIR", str(tmp_path))
    monkeypatch.setattr(image, "_holo_warned", False)
    caplog.set_level(logging.WARNING, logger="image")
    holo = image._load_template("legendary", True)
    image._load_template("legendary", True)
    image.warn_if_holo_template_missing()
    plain = image._load_template("legendary", False)
    warnings = [r for r in caplog.records if "Card_Template_Holo.png" in r.getMessage()]
    assert len(warnings) == 1
    assert holo.size == plain.size
    assert ImageChops.difference(holo, plain).getbbox() is not None  # the sheen is there


def test_image_does_not_draw_accolades():
    """Source-reading (image.py): accolades are not composited into the card image (caster stickers still are)."""
    src = _read("backend", "image.py")
    assert "accolade" not in src.replace("Accolades are not drawn", "")
    assert "season_accolades" not in src and "SeasonAccolade" not in src
    assert "_apply_stickers(base, tag_keys)" in src  # caster stickers are still baked in
    cards_src = _read("backend", "routers", "cards.py")
    img_fn = cards_src[cards_src.index("def get_card_image("):cards_src.index("def get_card_image_route(")]
    assert "accolade" not in img_fn


def test_cards_ui_holo_rarity_label_and_reveal_sweep():
    """Source-reading (app-cards.js / style.css): rarity label reads 'Legendary · Holo'; the reveal sweep targets card art only and is disabled under prefers-reduced-motion."""
    js = _fe("app-cards.js")
    css = _fe("style.css")
    label = _fn_source(js, "_rarityLabel")
    out = _run_node(label + """
console.log(JSON.stringify([_rarityLabel({card_type: "legendary", is_holo: true}), _rarityLabel({card_type: "legendary"}), _rarityLabel({card_type: "epic", is_holo: false})]));
""")
    assert out == ["legendary · Holo", "legendary", "epic"]
    assert "text-transform: uppercase" in _rule(css, ".reveal-card .rarity-label")[0]  # reads LEGENDARY · HOLO
    show = _fn_body(js, "showCard")
    assert 'textContent = _rarityLabel(card)' in show
    assert "card.is_holo" in show and "reveal-img-wrap--holo" in show
    assert show.index("if (reduceMotion)") < show.index("reveal-img-wrap--holo")
    assert "reveal-img-wrap--holo" in _fn_body(js, "_stripRevealDrawFx")
    sweep = _rule(css, ".reveal-img-wrap--holo::after")
    assert sweep and "animation: holo-sweep" in sweep[0] and "inset: 0" in sweep[0]
    reduced = re.findall(r"@media \(prefers-reduced-motion: reduce\) \{([^@]*?)\n\}", css, re.S)
    assert any(".reveal-img-wrap--holo::after" in block and "animation: none" in block for block in reduced)


def test_cards_ui_pip_overlay_on_every_card_view():
    """Source-reading (app-cards.js, app-roster.js): card viewer, draw reveal, My Team and collection render an HTML pip overlay via accoladePipsHtml, and the viewer lists chips via accoladeChipsHtml."""
    cards = _fe("app-cards.js")
    roster = _fe("app-roster.js")
    html = _fe("index.html")
    overlay = _fn_body(cards, "_renderCardAccolades")
    assert "accoladePipsHtml(" in overlay and "accoladeChipsHtml(" in overlay and "card-pips" in overlay
    show = _fn_body(cards, "showCard")
    assert "_renderCardAccolades(card, drawFx)" in show  # the card viewer and the draw reveal
    assert 'id="revealPips"' in html and 'id="revealAccolades"' in html
    slot = _fn_body(roster, "_cardSlotHTML")  # My Team roster and bench (the collection)
    assert "accoladePipsHtml(playerAccolades(c.player_id))" in slot and "card-pips" in slot
    assert "_rerenderRosterPips" in _fe("app-globals.js")
    css = _fe("style.css")
    pos = _rule(css, ".card-slot .card-pips")[0]
    assert "position: absolute" in pos and "right:" in pos and "top:" in pos
    assert "flex-direction: column" in _rule(css, ".card-pips .accolade-pips")[0]


# ===========================================================================
# Story 6: Accolade Symbols Read at a Glance
# ===========================================================================

def test_accolade_kinds_backend_order_names_icons_tokens():
    """accolades.ACCOLADE_KINDS lists div1 champion, div2 champion, most_points, best_average, best_match, fantasy_winner, played in that order with the planned names, Lucide icons, plates and --accolade-* tokens."""
    got = [(k["key"], k["name"], k["icon"], k["plate"], k["token"]) for k in accolades.ACCOLADE_KINDS]
    assert got == [
        ("div1", "Div 1 Champion", "crown", "filled", "--accolade-div1"),
        ("div2", "Div 2 Champion", "trophy", "filled", "--accolade-div2"),
        ("most_points", "Most Points", "flame", "outlined", "--accolade-points"),
        ("best_average", "Best Average", "gauge", "outlined", "--accolade-average"),
        ("best_match", "Best Single Match", "zap", "outlined", "--accolade-match"),
        ("fantasy_winner", "Fantasy Winner", "medal", "outlined", "--accolade-fantasy"),
        ("played", "Played", "calendar-check", "muted", "--accolade-played"),
    ]
    assert [k["kind"] for k in accolades.ACCOLADE_KINDS[:2]] == ["champion", "champion"]


def test_accolade_kinds_backend_and_frontend_agree():
    """Source-reading: ACCOLADE_KINDS in app-globals.js matches backend accolades.ACCOLADE_KINDS (order, name, icon, token)."""
    js = _fe("app-globals.js")
    block = js[js.index("const ACCOLADE_KINDS = ["):]
    block = block[:block.index("];")]
    fields = ("key", "kind", "division", "name", "icon", "plate", "token")
    frontend = []
    for line in block.splitlines()[1:]:
        if not line.strip():
            continue
        entry = {}
        for f in fields:
            m = re.search(rf'\b{f}: (?:"([^"]*)"|null)', line)
            assert m, (f, line)
            entry[f] = m.group(1)
        frontend.append(entry)
    backend = [{f: k[f] for f in fields} for k in accolades.ACCOLADE_KINDS]
    assert frontend == backend


def test_accolade_pips_group_by_kind_in_fixed_order():
    """Node harness (accoladePipsHtml): one pip per earned kind in ACCOLADE_KINDS order regardless of input order; unearned kinds left out; no '+N'."""
    html = _pips([_a("played", "Season 16"), _a("best_match", "Season 14"),
                  _a("champion", "Season 15", "div2", "Blues"), _a("most_points", "Season 13"),
                  _a("fantasy_winner", "Season 12"), _a("champion", "Season 16", "div1", "Reds"),
                  _a("best_average", "Season 11")])
    classes = [c.split()[2] for c, _, _ in _pip_attrs(html)]
    assert classes == ["accolade-pip--div1", "accolade-pip--div2", "accolade-pip--most_points",
                       "accolade-pip--best_average", "accolade-pip--best_match",
                       "accolade-pip--fantasy_winner", "accolade-pip--played"]
    assert "+" not in re.sub(r"<[^>]*>", "", html)
    only_two = _pips([_a("best_match", "Season 14"), _a("champion", "Season 15", "div1", "Reds")])
    assert [c.split()[2] for c, _, _ in _pip_attrs(only_two)] == ["accolade-pip--div1", "accolade-pip--best_match"]


def test_accolade_pips_count_shown_only_from_two():
    """Node harness: a kind earned once shows no number, twice shows '2' (Played excepted)."""
    once = _pip_attrs(_pips([_a("most_points", "Season 15")]))
    assert once[0][2] is None
    twice = _pip_attrs(_pips([_a("most_points", "Season 15"), _a("most_points", "Season 12")]))
    assert twice[0][2] == "2"
    played_once = _pip_attrs(_pips([_a("played", "Season 16")]))
    assert played_once[0][2] == "1"  # Played always shows its seasons count


def test_accolade_pips_tooltip_and_aria_newest_first_with_team():
    """Node harness: pip text and aria-label name the kind and seasons newest first ('Div 1 Champion, 2 times: S16, S15'), champions add 'with [Team]'."""
    html = _pips([_a("champion", "Season 15", "div1", "Blues"), _a("champion", "Season 16", "div1", "Reds")])
    (_, aria, _), = _pip_attrs(html)
    assert aria == "Div 1 Champion, 2 times: S16 with Reds, S15 with Blues"
    # Issue 208 generalised the tooltip attribute from data-accolade-tip to data-tip.
    assert 'data-tip="Div 1 Champion · S16 with Reds, S15 with Blues"' in html
    assert 'tabindex="0"' in html
    award = _pip_attrs(_pips([_a("best_match", "Season 14"), _a("best_match", "Season 16")]))
    assert award[0][1] == "Best Single Match, 2 times: S16, S14"
    single = _pip_attrs(_pips([_a("most_points", "Season 15")]))
    assert single[0][1] == "Most Points: S15"


def test_accolade_pips_played_last_with_seasons_count_and_compressed_runs():
    """Node harness: Played is the last, muted pip; its number is seasons played even at one; tooltip compresses runs ('Played · 12 seasons: S1–S10, S14, S16')."""
    played = [_a("played", f"Season {n}") for n in list(range(1, 11)) + [14, 16]]
    html = _pips(played + [_a("best_average", "Season 9")])
    pips = _pip_attrs(html)
    cls, aria, count = pips[-1]
    assert "accolade-pip--played" in cls and "accolade-pip--muted" in cls
    assert count == "12"
    assert aria == "Played, 12 seasons: S1–S10, S14, S16"
    assert 'data-tip="Played · 12 seasons: S1–S10, S14, S16"' in html
    assert _pips(played, {"omitPlayed": True}) == ""


def test_accolade_pips_empty_input_renders_nothing():
    """Node harness: a player with no accolades gets empty markup (no empty container)."""
    assert _pips([]) == ""
    assert _run_node(_globals_helpers_js() + "console.log(JSON.stringify([accoladePipsHtml(null), accoladePipsHtml(undefined), accoladeChipsHtml([])]));") == ["", "", ""]


def test_accolade_chips_one_per_accolade_full_name_ordered():
    """Node harness (accoladeChipsHtml): one chip per accolade with the full name ('S16 Div 1 Champion'), newest season first, champions first within a season."""
    html = _chips([_a("best_match", "Season 15"), _a("played", "Season 16"),
                   _a("champion", "Season 16", "div1", "Reds"), _a("most_points", "Season 16"),
                   _a("champion", "Season 15", "div2", "Blues")])
    labels = re.findall(r'<span class="accolade-chip [^"]*"[^>]*><i [^>]*></i>([^<]*)</span>', html)
    assert labels == ["S16 Div 1 Champion", "S16 Most Points", "S16 Played",
                      "S15 Div 2 Champion", "S15 Best Single Match"]
    with_matches = _chips([dict(_a("played", "Season 16"), matches=7)])
    assert "S16 Played · 7 matches" in with_matches


def test_accolade_chips_escape_names():
    """Node harness: team and player names in chips / tooltips are HTML-escaped."""
    evil = '<img src=x onerror="alert(1)">'
    chips = _chips([_a("champion", "Season 16", "div1", evil), _a("champion", "<b>S</b>", "div2", "T")])
    pips = _pips([_a("champion", "Season 16", "div1", evil)])
    for html in (chips, pips):
        assert "<img" not in html and "<b>" not in html
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html


def test_accolade_tooltip_closes_on_escape_blur_and_outside_tap():
    """Source-reading (app-globals.js): the pip tooltip opens on hover/focus/tap and closes on Escape, blur and a tap elsewhere."""
    js = _fe("app-globals.js")
    init = _fn_body(js, "_initAccoladeTips")
    for event in ('"mouseover"', '"mouseout"', '"focusin"', '"focusout"', '"click"', '"keydown"'):
        assert event in init, event
    assert '"Escape"' in init and "hideAccoladeTip()" in init
    assert "a tap elsewhere" in init  # click outside a pip closes it
    show = _fn_body(js, "showAccoladeTip")
    assert 'setAttribute("role", "tooltip")' in show and "aria-describedby" in show


def test_get_accolades_public_returns_champions_awards_and_played(db):
    """GET /accolades (no auth) returns per player champion/award accolades (kind, division, short and full season, team, value) and played seasons including the live season."""
    _seed_season(db)  # live season: Alpha, Bravo and Charlie have scored matches
    _acc(db, "Season 15", "champion", 1, "Alpha", division="div1", team="Reds")
    _acc(db, "Season 15", "best_match", 1, "Alpha", value=55.5, match_id=9)
    _acc(db, "Season 15", "played", 1, "Alpha")
    _acc(db, "Season 14", "played", 1, "Alpha")
    data = _client(db).get("/accolades").json()
    assert data["current_season"] == "Season 16" and data["current_season_short"] == "S16"
    alpha = data["players"]["1"]
    champ = next(a for a in alpha if a["kind"] == "champion")
    assert champ == {"kind": "champion", "division": "div1", "season": "Season 15",
                     "season_short": "S15", "team_name": "Reds", "value": None, "match_id": None}
    assert next(a for a in alpha if a["kind"] == "best_match")["value"] == 55.5
    assert sorted(a["season"] for a in alpha if a["kind"] == "played") == ["Season 14", "Season 15", "Season 16"]
    assert [a["season"] for a in data["players"]["3"]] == ["Season 16"]  # live season only
    assert "4" not in data["players"]  # Delta has no scored match


def test_get_accolades_fantasy_winner_only_while_linked(db):
    """fantasy_winner seasons appear on a player only while the winning user's users.player_id links to them; gone after unlinking.
    Security review: only a Steam-verified link counts (steam_id set); a self-reported id doesn't."""
    jiri = _user(db, "jiri")
    _acc(db, "Season 15", "fantasy_winner", user_id=jiri.id, username="jiri", value=140)
    client = _client(db)
    assert client.get("/accolades").json()["players"] == {}
    jiri.player_id = 7  # stale id without Steam (typed in before #209): no pip
    db.commit()
    assert client.get("/accolades").json()["players"] == {}
    assert client.get("/history/seasons").json()["hall_of_fame"] == []
    jiri.steam_id = "76561197960265735"  # Steam-verified link
    db.commit()
    linked = client.get("/accolades").json()["players"]
    assert [(a["kind"], a["season"]) for a in linked["7"]] == [("fantasy_winner", "Season 15")]
    jiri.player_id = None
    db.commit()
    assert client.get("/accolades").json()["players"] == {}


def test_get_accolades_has_no_user_ids_or_usernames(db):
    """The GET /accolades payload contains no user_id or username fields or values."""
    jiri = _user(db, "jiri_the_winner", player_id=7, steam_id="76561197960265735")
    _acc(db, "Season 15", "fantasy_winner", user_id=jiri.id, username="jiri_the_winner", value=140)
    _acc(db, "Season 15", "champion", 7, "Glete", division="div1", team="Kanat")
    raw = _client(db).get("/accolades").text
    assert "user_id" not in raw and "username" not in raw
    assert "jiri_the_winner" not in raw
    assert json.loads(raw)["players"]["7"]


def test_short_season_label():
    """short_season('Season 16') returns 'S16'; an unparseable label is returned unchanged."""
    assert accolades.short_season("Season 16") == "S16"
    assert accolades.short_season("season 3") == "S3"
    assert accolades.short_season("S15") == "S15"
    assert accolades.short_season("Spring Cup") == "Spring Cup"
    assert accolades.short_season("") == ""


def test_no_view_builds_pip_or_chip_markup_outside_shared_helpers():
    """Source-reading: 'accolade-pip' / 'accolade-chip' class strings appear only inside accoladePipsHtml / accoladeChipsHtml in frontend/*.js."""
    import glob
    offenders = []
    for path in glob.glob(os.path.join(_FRONTEND, "*.js")):
        js = open(path, encoding="utf-8").read()
        if os.path.basename(path) == "app-globals.js":
            start = js.index("// ACCOLADES (issue 50)")
            end = js.index("// END ACCOLADES (issue 50)")
            section = js[start:end]
            # Inside the section, the class strings are only in the two renderers.
            helpers = _fn_body(section, "accoladePipsHtml") + _fn_body(section, "accoladeChipsHtml")
            rest = section.replace(_fn_body(section, "accoladePipsHtml"), "").replace(_fn_body(section, "accoladeChipsHtml"), "")
            assert "accolade-pip " in helpers and "accolade-chip " in helpers
            assert not re.search(r"accolade-(pip|chip)\b(?!s\b|-count)", rest)
            js = js[:start] + js[end:]
        if re.search(r"accolade-(pip|chip)", js):
            offenders.append(os.path.basename(path))
    assert offenders == []


def test_accolade_tokens_in_both_colors_and_type_css_identical():
    """Source-reading: --accolade-div1/div2/points/average/match/fantasy/played exist in frontend/ and design/ colors_and_type.css with identical values."""
    fe = _read("frontend", "colors_and_type.css")
    de = _read("design", "colors_and_type.css")
    assert fe == de
    for name in ("div1", "div2", "points", "average", "match", "fantasy", "played"):
        m = re.search(rf"--accolade-{name}:\s*([^;]+);", fe)
        assert m, name
        assert m.group(1).startswith("var(--"), (name, m.group(1))  # built from palette tokens


def test_accolade_pip_chip_css_in_shared_states_before_tour():
    """Source-reading (style.css): .accolade-pip, .accolade-chip and the tooltip rules sit in SHARED STATES before the GUIDED TOUR section, sized in em, using tokens (no hex)."""
    css = _fe("style.css")
    start = css.index("SHARED STATES (issue #202)")
    end = css.index("GUIDED TOUR (issue #144)")
    assert start < end
    section = css[start:end]
    for sel in (".accolade-pip", ".accolade-chip", ".accolade-tip", ".accolade-pip-count"):
        bodies = _rule(section, sel)
        assert bodies, sel
        for body in bodies:
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), (sel, body)
            assert "rgba(" not in body
    assert any("width: 1.7em" in b and "height: 1.7em" in b for b in _rule(section, ".accolade-pip"))
    assert "var(--accolade-div1)" in section and "var(--accolade-played)" in section
    assert ".accolade-pip" not in css[end:]


def test_design_readme_documents_symbol_table():
    """Source-reading (.claude/skills/README.md): the accolade symbol table and the rule 'pips for a glance, chips where the names fit'."""
    md = _read(".claude", "skills", "README.md")
    assert "pips for a glance, chips where the names fit" in md
    for name, icon, token in (("Div 1 Champion", "crown", "--accolade-div1"), ("Div 2 Champion", "trophy", "--accolade-div2"),
                              ("Most Points", "flame", "--accolade-points"), ("Best Average", "gauge", "--accolade-average"),
                              ("Best Single Match", "zap", "--accolade-match"), ("Fantasy Winner", "medal", "--accolade-fantasy"),
                              ("Played", "calendar-check", "--accolade-played")):
        row = next((l for l in md.splitlines() if l.startswith("|") and f"`{icon}`" in l), "")
        assert name in row and token in row, name
    assert "Holo" in md and "card art" in md


# ===========================================================================
# Story 7: Seasons Played and Titles Are Easy to Find
# ===========================================================================

def test_get_players_seasons_played_includes_live_season(db):
    """GET /players seasons_played counts distinct played seasons plus the current season when the player has a scored match; `seasons` lists those labels."""
    _seed_season(db)
    _acc(db, "Season 15", "played", 1, "Alpha")
    _acc(db, "Season 13", "played", 1, "Alpha")
    rows = {r["id"]: r for r in _client(db).get("/players").json()}
    assert rows[1]["seasons_played"] == 3
    assert rows[1]["seasons"] == ["Season 16", "Season 15", "Season 13"]
    assert rows[2]["seasons_played"] == 1 and rows[2]["seasons"] == ["Season 16"]


def test_get_players_live_season_not_counted_without_scored_match(db):
    """A player with no scored match this season doesn't get the current season counted."""
    _seed_season(db)
    _acc(db, "Season 15", "played", 4, "Delta")
    rows = {r["id"]: r for r in _client(db).get("/players").json()}
    assert rows[4]["seasons_played"] == 1 and rows[4]["seasons"] == ["Season 15"]


def test_get_players_titles_newest_first_excludes_played(db):
    """GET /players `titles` lists champion and award accolades newest first, without played."""
    _seed_season(db)
    _acc(db, "Season 14", "most_points", 1, "Alpha", value=60)
    _acc(db, "Season 15", "best_match", 1, "Alpha", value=40)
    _acc(db, "Season 15", "champion", 1, "Alpha", division="div2", team="Reds")
    _acc(db, "Season 15", "played", 1, "Alpha")
    rows = {r["id"]: r for r in _client(db).get("/players").json()}
    titles = [(t["season"], t["kind"]) for t in rows[1]["titles"]]
    assert titles == [("Season 15", "champion"), ("Season 15", "best_match"), ("Season 14", "most_points")]
    assert rows[2]["titles"] == []


def test_player_detail_includes_seasons_and_titles(db):
    """The player detail endpoint carries seasons_played, seasons and titles."""
    _seed_season(db)
    _acc(db, "Season 15", "champion", 1, "Alpha", division="div1", team="Reds")
    _acc(db, "Season 15", "played", 1, "Alpha")
    p = _client(db).get("/players/1").json()
    assert p["seasons_played"] == 2 and p["seasons"] == ["Season 16", "Season 15"]
    assert [(t["season"], t["kind"]) for t in p["titles"]] == [("Season 15", "champion")]
    assert p["holo_unlocked"] is True
    assert p["current_season"] == "Season 16" and p["current_season_matches"] == 3


def test_get_history_seasons_newest_first_with_champions_and_awards(db):
    """GET /history/seasons returns one entry per season newest first, with Div 1 / Div 2 champion teams and the four awards (ties included)."""
    _acc(db, "Season 9", "played", 1, "Alpha")
    _acc(db, "Season 15", "champion", 1, "Alpha", division="div1", team="Reds")
    _acc(db, "Season 15", "champion", 2, "Bravo", division="div1", team="Reds")
    _acc(db, "Season 15", "champion", 3, "Charlie", division="div2", team="Blues")
    _acc(db, "Season 15", "most_points", 1, "Alpha", value=60)
    _acc(db, "Season 15", "best_average", 2, "Bravo", value=20)
    _acc(db, "Season 15", "best_average", 3, "Charlie", value=20)  # a tie
    _acc(db, "Season 15", "best_match", 3, "Charlie", value=50, match_id=77)
    _acc(db, "Season 15", "fantasy_winner", user_id=5, username="jiri", value=140)
    _acc(db, "Season 10", "most_points", 2, "Bravo", value=40)
    seasons = _client(db).get("/history/seasons").json()["seasons"]
    assert [s["season_label"] for s in seasons] == ["Season 15", "Season 10", "Season 9"]
    s15 = seasons[0]
    assert s15["season_short"] == "S15"
    assert s15["champions"]["div1"]["team_name"] == "Reds"
    assert [p["name"] for p in s15["champions"]["div1"]["players"]] == ["Alpha", "Bravo"]
    assert s15["champions"]["div2"]["players"] == [{"account_id": 3, "name": "Charlie"}]
    assert [w["player_name"] for w in s15["awards"]["best_average"]] == ["Bravo", "Charlie"]
    assert s15["awards"]["best_match"][0]["match_id"] == 77
    assert s15["awards"]["fantasy_winner"] == [{"username": "jiri", "value": 140}]
    assert seasons[1]["champions"] == {"div1": None, "div2": None}
    assert seasons[2]["played_count"] == 1


def test_get_history_seasons_hall_of_fame_ranks_titles_excludes_played(db):
    """The hall of fame ranks players by champion + award titles; played isn't counted."""
    for n in range(1, 10):
        _acc(db, f"Season {n}", "played", 3, "Charlie")  # many seasons, no titles
    _acc(db, "Season 15", "champion", 1, "Alpha", division="div1", team="Reds")
    _acc(db, "Season 14", "most_points", 1, "Alpha", value=60)
    _acc(db, "Season 15", "best_match", 2, "Bravo", value=50)
    _acc(db, "Season 15", "played", 1, "Alpha")
    fame = _client(db).get("/history/seasons").json()["hall_of_fame"]
    assert [(f["player_name"], f["titles"], f["champion_titles"], f["award_titles"]) for f in fame] == [
        ("Alpha", 2, 1, 1), ("Bravo", 1, 0, 1)]
    assert all(a["kind"] != "played" for f in fame for a in f["accolades"])


def test_get_history_seasons_has_no_user_ids(db):
    """GET /history/seasons is public and its payload has no user_id fields."""
    jiri = _user(db, "jiri", player_id=1)
    _acc(db, "Season 15", "fantasy_winner", user_id=jiri.id, username="jiri", value=140)
    _acc(db, "Season 15", "champion", 1, "Alpha", division="div1", team="Reds")
    raw = _client(db).get("/history/seasons").text  # public: no login
    assert "user_id" not in raw


def test_get_history_seasons_empty(db):
    """With no accolades GET /history/seasons returns an empty list (frontend shows 'No season history yet.')."""
    data = _client(db).get("/history/seasons").json()
    assert data == {"current_season": "Season 1", "seasons": [], "hall_of_fame": []}
    assert "No season history yet." in _fe("app-history.js")


def test_players_tab_seasons_and_titles_columns():
    """Source-reading (app-players.js / style.css): Seasons column with tabular count, six season bars (played grey, champion amber, empty) and hover list; Titles column with pips, sortable by titles."""
    js = _fe("app-players.js")
    html = _fe("index.html")
    head = re.search(r'<thead><tr id="playersTableHead">.*?</tr></thead>', html, re.S).group(0)
    assert re.search(r'data-col="seasons_played"[^>]*>\s*Seasons\s*</th>', head)
    assert re.search(r'data-col="titles_count"[^>]*>\s*Titles\s*</th>', head)
    cell = _fn_body(js, "_playerSeasonsCellHtml")
    for state in ('"champion"', '"played"', '"empty"'):
        assert state in cell
    assert "seasons-count" in cell and "title=" in cell
    assert ".slice(-6)" in _fn_body(js, "_knownSeasons")
    render = _fn_body(js, "renderPlayers")
    assert "accoladePipsHtml(p.titles" in render and "_playerSeasonsCellHtml(p, recent)" in render
    assert "titles_count" in _fn_body(js, "loadPlayers")
    css = _fe("style.css")
    assert "tabular-nums" in _rule(css, ".seasons-count")[0]
    assert "var(--accolade-div1)" in _rule(css, ".season-bar--champion")[0]
    assert "var(--accolade-played)" in _rule(css, ".season-bar--played")[0]


def test_players_tab_filters_and_sorting_no_veteran():
    """Source-reading (app-players.js / index.html): filter chips All, Champions, New this season and sort by seasons/titles/average; no 'Veteran' anywhere."""
    js = _fe("app-players.js")
    html = _fe("index.html")
    for label, key in (("All", "all"), ("Champions", "champions"), ("New this season", "new")):
        assert re.search(rf'data-filter="{key}"[^>]*>{label}</button>', html), label
    fn = _fn_body(js, "_playerMatchesFilter")
    assert '"champion"' in fn and "seasons.length === 1" in fn
    assert "aria-pressed" in _fn_body(js, "setPlayersFilter")
    for col in ("seasons_played", "titles_count", "avg_points"):
        assert f'data-col="{col}"' in html
    import glob
    for path in glob.glob(os.path.join(_FRONTEND, "*.js")) + [os.path.join(_FRONTEND, "index.html")]:
        assert "veteran" not in open(path, encoding="utf-8").read().lower(), path


def test_player_popup_accolades_section():
    """Source-reading (app-player-popup.js since issue 208): popup Accolades section with 'Holo unlocked' banner for champions, counts, pips in header and a per-season chip timeline including 'Played · N matches'."""
    js = _fe("app-player-popup.js")
    html = _fe("index.html")
    fn = _fn_body(js, "renderPlayerAccolades")
    assert "Holo unlocked" in fn and "p.holo_unlocked" in fn
    for label in ("Champion titles", "Season awards", "Seasons played"):
        assert label in fn
    assert 'getElementById("playerModalPips")' in fn and "accoladePipsHtml(list)" in fn
    assert "accoladeChipsHtml(items)" in fn and "current_season_matches" in fn
    assert "renderPlayerAccolades(p)" in _fn_body(js, "openPlayerModal")
    assert 'id="playerModalPips"' in html and 'id="playerModalAccolades"' in html
    # The Played chip of the live season names its matches.
    out = _run_node(_globals_helpers_js() + """
console.log(JSON.stringify(accoladeChipsHtml([{kind: "played", season: "Season 16", matches: 7}])));
""")
    assert "S16 Played · 7 matches" in out


def test_history_tab_after_leaderboards_with_empty_state():
    """Source-reading (index.html / app-history.js): a top-level History tab after Leaderboards, loads GET /history/seasons, renders champion blocks, award chips, hall of fame pips, and 'No season history yet.'"""
    html = _fe("index.html")
    js = _fe("app-history.js")
    tabs = re.findall(r'id="tab-btn-(\w+)"', html)
    assert tabs.index("history") == tabs.index("leaderboard") + 1
    assert 'id="tab-history"' in html and '<script src="/app-history.js"></script>' in html
    assert 'if (name === "history")       loadHistory();' in _fe("app-globals.js")
    load = _fn_body(js, "loadHistory")
    assert "/history/seasons" in load and "No season history yet." in load
    champ = _fn_body(js, "_historyChampionHtml")
    assert "accoladeChipsHtml(" in champ and 'statusBadgeHtml("Holo"' in champ
    assert "accoladeChipsHtml(" in _fn_body(js, "_historyAwardsHtml")
    fame = _fn_body(js, "_historyFameHtml")
    assert "accoladePipsHtml(f.accolades, { omitPlayed: true })" in fame and "f.titles" in fame
    assert "Hall of fame" in html


# ===========================================================================
# Step 8: Verification — migration and schema coverage
# ===========================================================================

def test_migration_040_adds_cards_is_holo():
    """Migration 040 adds cards.is_holo BOOLEAN NOT NULL DEFAULT 0 to a legacy DB, existing cards read False."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE cards"))
        conn.execute(text("""CREATE TABLE cards (id INTEGER PRIMARY KEY, player_id INTEGER,
            owner_id INTEGER, card_type TEXT, league_id INTEGER, is_active BOOLEAN,
            generation INTEGER NOT NULL DEFAULT 1, slot_index INTEGER)"""))
        conn.execute(text("INSERT INTO cards (id, player_id, owner_id, card_type, is_active) "
                          "VALUES (1, 7, 1, 'legendary', 0)"))
        conn.commit()
        migrate._ensure_migrations_table(conn)
        for migration_id, _ in migrate.MIGRATIONS:
            if migration_id < "040":
                migrate._record(conn, migration_id)
    migrate.run_migrations(engine)
    cols = {c["name"]: c for c in sa_inspect(engine).get_columns("cards")}
    assert "is_holo" in cols and cols["is_holo"]["nullable"] is False
    session = sessionmaker(bind=engine)()
    assert session.get(Card, 1).is_holo is False
    session.close()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1 FROM schema_migrations WHERE id = '040_cards_is_holo'")).first()


def test_migration_040_is_idempotent():
    """Running migrations twice leaves cards.is_holo in place and doesn't raise (PRAGMA table_info guard)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)  # cards already has is_holo
    migrate.run_migrations(engine)
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM schema_migrations WHERE id = '040_cards_is_holo'"))
        conn.commit()
        migrate._m040_cards_is_holo(conn)  # the PRAGMA guard skips the ALTER
    migrate.run_migrations(engine)
    names = [c["name"] for c in sa_inspect(engine).get_columns("cards")]
    assert names.count("is_holo") == 1


# ---------------------------------------------------------------------------
# Review follow-ups (security and docs-steward findings)
# ---------------------------------------------------------------------------

def test_fantasy_winner_pip_needs_steam_verified_link(db):
    """A fantasy win shows on a player only through a Steam-verified link: self-reported -> none, Steam -> pip (list, detail, hall of fame), unlink -> gone."""
    db.add(Player(id=7, name="Glete"))
    db.commit()
    jiri = _user(db, "jiri", player_id=7)
    _acc(db, "Season 15", "fantasy_winner", user_id=jiri.id, username="jiri", value=140)
    client = _client(db)
    def kinds():
        rows = {r["id"]: r for r in client.get("/players").json()}
        return [t["kind"] for t in rows[7]["titles"]]
    assert kinds() == [] and client.get("/players/7").json()["titles"] == []
    jiri.steam_id = "76561197960265735"
    db.commit()
    assert kinds() == ["fantasy_winner"]
    assert [f["player_account_id"] for f in client.get("/history/seasons").json()["hall_of_fame"]] == [7]
    jiri.player_id = None
    db.commit()
    assert kinds() == []
    # Soft and demo accounts never count, even with a Steam id.
    demo = _user(db, "demo1", player_id=7, steam_id="76561197960265736", is_demo=True)
    _acc(db, "Season 14", "fantasy_winner", user_id=demo.id, username="demo1")
    assert kinds() == []


def test_post_fantasy_winner_rejects_soft_and_tester_accounts(db):
    """A Twitch viewer soft account or a tester can't be recorded as fantasy winner (422)."""
    client, _ = _admin_client(db)
    _user(db, "tess", is_tester=True)
    soft = User(username=None, email=None, password_hash=None, account_type="twitch", tokens=0)
    db.add(soft)
    db.commit()
    for body in ({"username": "tess"}, {"user_id": soft.id}):
        resp = client.post("/admin/season-accolades", json={"season_label": "Season 15",
                                                            "kind": "fantasy_winner", **body})
        assert resp.status_code == 422, body
    assert _rows(db) == []


def test_backfill_played_rejects_bad_ids_and_long_names(db, tmp_path, monkeypatch):
    """Only real ints in 1..2^63-1 count as match and account ids (bools, strings, huge or negative values are ignored), a non-list matchIds answer is a league error, and personaname is capped at 100 characters."""
    league_map = {111: [9001, True, "9002", 2**63, -1], 222: {"error": "nope"}}
    matches = {9001: {"players": [
        {"account_id": 10, "personaname": "x" * 300}, {"account_id": True, "personaname": "bool"},
        {"account_id": 2**63, "personaname": "huge"}, {"account_id": "12", "personaname": "str"},
        {"account_id": 0}]}}
    r = _run_backfill(db, tmp_path, monkeypatch, league_map=league_map, matches=matches)
    assert r.code == 1
    assert "league 222: OpenDota returned no matches" in r.out
    assert r.fetched == [9001]
    rows = _rows(db, kind="played")
    assert [(x.player_account_id, len(x.player_name)) for x in rows] == [(10, 100)]
    assert "4 anonymous slots skipped" in r.out


def test_history_holo_badge_only_for_past_seasons():
    """Node harness (app-history.js): champions of the current season show "Holo from next season", past champions "Holo"; GET /history/seasons names the current season."""
    js = _fe("app-history.js")
    harness = (_globals_helpers_js() + "\n" + _fn_source(_fe("app-globals.js"), "statusBadgeHtml") + "\n"
               + js[js.index("let _historyCurrentSeason"):js.index("async function loadHistory")]
               + _fn_source(js, "_historyChampionHtml") + """
_historyCurrentSeason = "Season 16";
const team = {team_name: "Reds", players: [{account_id: 1, name: "A"}]};
console.log(JSON.stringify([
  _historyChampionHtml({season_label: "Season 16", season_short: "S16"}, "div1", team),
  _historyChampionHtml({season_label: "Season 15", season_short: "S15"}, "div1", team)]));
""")
    current, past = _run_node(harness)
    assert "Holo from next season" in current
    assert ">Holo</span>" in past and "next season" not in past
    assert "_historyCurrentSeason = data.current_season" in _fn_body(js, "loadHistory")


# ---------------------------------------------------------------------------
# Follow-up: season names and divisions from OpenDota league names
# ---------------------------------------------------------------------------

def _league(db, lid, name, monitored=True):
    from models import League
    db.add(League(id=lid, name=name, is_monitored=monitored))
    db.commit()


def test_league_name_helpers():
    """league_season_number reads "Season N" anywhere in a league name (or None); league_division says div2 for "Lower"."""
    assert accolades.league_season_number("Kanaliiga Season 16") == 16
    assert accolades.league_season_number("Kanaliiga Season 10 Lower Division") == 10
    assert accolades.league_season_number("kanaliiga season 3 Middle") == 3
    for name in ("Kanaliiga", "(pending ingest)", None, "Seasonal Cup 2024"):
        assert accolades.league_season_number(name) is None, name
    assert accolades.league_division("Kanaliiga Season 16 Lower") == "div2"
    assert accolades.league_division("Kanaliiga Season 10 LOWER Division") == "div2"
    assert accolades.league_division("Kanaliiga Season 16") == "div1"
    assert accolades.league_division(None) == "div1"


def test_current_season_label_from_monitored_league_names(db, caplog):
    """The monitored leagues' names give the label; disagreement takes the highest with a warning; pending or numberless names fall back to the archive and accolade inference."""
    import logging
    _acc(db, "Season 9", "played", 1, "Alpha")  # the fallback would say Season 10
    _league(db, 20162, "Kanaliiga Season 16")
    _league(db, 20163, "Kanaliiga Season 16 Lower")
    _league(db, 19368, "Kanaliiga Season 15", monitored=False)  # not monitored: ignored
    assert accolades.current_season_label(db) == "Season 16"
    caplog.set_level(logging.WARNING, logger="accolades")
    _league(db, 30001, "Kanaliiga Season 17")
    assert accolades.current_season_label(db) == "Season 17"
    assert any("different seasons" in r.getMessage() for r in caplog.records)
    from models import League
    db.query(League).filter(League.is_monitored == True).update({League.is_monitored: False})  # noqa: E712
    _league(db, 30002, "(pending ingest)")
    _league(db, 12481, "Kanaliiga")
    assert accolades.current_season_label(db) == "Season 10"


def test_current_season_label_end_season_then_reset_with_leagues(db):
    """End Season keeps the leagues monitored, so the label stays the archived season until Reset unmonitors them; then the fallback names the next season."""
    from models import League
    _seed_season(db)
    _league(db, 20162, "Kanaliiga Season 16")
    _end(db, label="Season 16")
    assert accolades.current_season_label(db) == "Season 16"
    db.query(League).update({League.is_monitored: False})
    db.query(PlayerMatchStats).delete()
    db.query(Match).delete()
    db.commit()
    assert accolades.current_season_label(db) == "Season 17"


def test_season_teams_division_from_league_names(db):
    """The preview's teams carry `division` from the league of their matches ("Lower" = div2) and every division they played in."""
    _seed_season(db)
    _league(db, 20162, "Kanaliiga Season 16")
    _league(db, 20163, "Kanaliiga Season 16 Lower")
    db.query(Match).filter(Match.match_id.in_([1001, 1002])).update({Match.league_id: 20162}, synchronize_session=False)
    db.query(Match).filter(Match.match_id.in_([1003, 1004])).update({Match.league_id: 20163}, synchronize_session=False)
    db.add(Team(id=400, name="Lowers"))
    db.add(Match(match_id=1005, radiant_team_id=400, dire_team_id=200, league_id=20163, start_time=1_001_005))
    db.add(PlayerMatchStats(player_id=5, team_id=400, match_id=1005, fantasy_points=1.0))
    db.commit()
    client, _ = _admin_client(db)
    teams = {t["team_name"]: (t["division"], t["divisions"])
             for t in client.get("/admin/season/accolades-preview").json()["teams"]}
    # Reds: 2 upper matches, 1 lower; Blues: 2 upper (1001, 1002), 1 lower (1004); Lowers: lower only.
    assert teams["Reds"] == ("div1", ["div1", "div2"])
    assert teams["Lowers"] == ("div2", ["div2"])
    assert teams["Blues"][0] == "div1"
    assert accolades.season_teams(db)[0]["division"] in ("div1", "div2")


def test_team_pickers_list_division_teams_first():
    """Node harness: teamOptionsForDivision lists that division's teams first (in an optgroup), then every other team; End Season and Mark champions both use it, and the End Season label is prefilled with the current season."""
    season_js = _fe("app-admin-season.js")
    fn = _fn_source(season_js, "teamOptionsForDivision")
    out = _run_node(_fn_source(_fe("app-globals.js"), "_escHtml") + fn + """
const teams = [
  {team_id: 1, team_name: "Upper A", division: "div1", divisions: ["div1"]},
  {team_id: 2, team_name: "Lower B", division: "div2", divisions: ["div2"]},
  {team_id: 3, team_name: "Both C", division: "div1", divisions: ["div1", "div2"]},
  {team_id: 4, team_name: "Unknown D", division: null, divisions: []},
];
const ids = h => [...h.matchAll(/value="(\\d+)"/g)].map(m => Number(m[1]));
console.log(JSON.stringify([ids(teamOptionsForDivision(teams, "div2")), ids(teamOptionsForDivision(teams, "div1")),
  teamOptionsForDivision(teams, "div2").includes('<optgroup label="Div 2">')]));
""")
    assert out == [[2, 3, 1, 4], [1, 3, 2, 4], True]
    assert 'teamOptionsForDivision(p.teams || [], div)' in _fn_body(season_js, "endSeason")
    assert "teamOptionsForDivision(teams, division)" in _fn_body(_fe("app-admin-players.js"), "_fillChampTeams")
    assert "p.season_label" in _fn_body(season_js, "endSeason")
    assert "_fillChampTeams()" in _fe("index.html")


def test_backfill_season_from_league_names_without_season_arg(db, tmp_path, monkeypatch):
    """With --league only, the label comes from the league names ("Kanaliiga Season 14" + "... Lower" -> Season 14)."""
    r = _run_backfill(db, tmp_path, monkeypatch, season=None)
    assert r.code == 0 and sorted(r.infos) == [111, 222]
    assert {x.season_label for x in _rows(db, kind="played")} == {"Season 14"}


def test_backfill_season_arg_must_agree_with_league_names(db, tmp_path, monkeypatch):
    """A --season that disagrees with the league names, or leagues naming different seasons, is an error and writes nothing."""
    r = _run_backfill(db, tmp_path, monkeypatch, season="Season 13")
    assert r.code == 1 and 'does not match the league names (Season 14)' in r.out
    assert r.fetched == [] and _rows(db) == []
    (tmp_path / "x").mkdir()
    mixed = _run_backfill(db, tmp_path / "x", monkeypatch, season=None,
                          league_names={111: "Kanaliiga Season 14", 222: "Kanaliiga Season 15 Lower"})
    assert mixed.code == 1 and "different seasons" in mixed.out and _rows(db) == []


def test_backfill_season_arg_needed_when_names_have_no_number(db, tmp_path, monkeypatch):
    """League names without a season number need --season; with it, that label is used."""
    names = {111: "Kanaliiga", 222: "Kanaliiga Lower"}
    r = _run_backfill(db, tmp_path, monkeypatch, season=None, league_names=names)
    assert r.code == 1 and "pass --season" in r.out and _rows(db) == []
    ok = _run_backfill(db, tmp_path, monkeypatch, season="Season 4", league_names=names)
    assert ok.code == 0 and {x.season_label for x in _rows(db)} == {"Season 4"}


def test_backfill_discovers_leagues_by_name(db, tmp_path, monkeypatch):
    """--season without --league finds "<prefix> Season N" leagues (with or without a division suffix) in OpenDota's league list, validating ids and names; --dry-run writes nothing."""
    league_list = [
        {"leagueid": 18649, "name": "Kanaliiga Season 14"},
        {"leagueid": 18650, "name": "Kanaliiga Season 14 Lower"},
        {"leagueid": 18651, "name": "Kanaliiga Season 140"},
        {"leagueid": 17814, "name": "Kanaliiga Season 3 Middle"},
        {"leagueid": 12481, "name": "Kanaliiga"},
        {"leagueid": True, "name": "Kanaliiga Season 14"},
        {"leagueid": 2**63, "name": "Kanaliiga Season 14"},
        {"leagueid": 5, "name": "Other Season 14"},
        "junk",
    ]
    league_map = {18649: [9001, 9002], 18650: [9003]}
    r = _run_backfill(db, tmp_path, monkeypatch, leagues=(), dry_run=True, league_list=league_list,
                      league_map=league_map)
    assert r.code == 0
    assert "Found league 18649: Kanaliiga Season 14" in r.out and "Found league 18650: Kanaliiga Season 14 Lower" in r.out
    assert "18651" not in r.out and "17814" not in r.out
    assert r.infos == []  # the names came with the list
    assert "Season 14: 3 matches, 4 players, 4 new rows" in r.out
    assert _rows(db) == [] and _audits(db, "admin_accolade_added") == []
    real = _run_backfill(db, tmp_path, monkeypatch, leagues=(), league_list=league_list, league_map=league_map)
    assert real.code == 0 and len(_rows(db, kind="played", season_label="Season 14")) == 4


def test_backfill_discovery_seasons_one_to_four_have_no_league(db, tmp_path, monkeypatch):
    """Discovery for a season with no numbered league says so; for Seasons 1-4 it points to the Played paste."""
    league_list = [{"leagueid": 20162, "name": "Kanaliiga Season 16"}]
    r = _run_backfill(db, tmp_path, monkeypatch, leagues=(), season="Season 2", league_list=league_list)
    assert r.code == 1
    assert 'No OpenDota league is named "Kanaliiga Season 2"' in r.out
    assert "Seasons 1-4 have no numbered OpenDota league" in r.out and "Played paste" in r.out
    other = _run_backfill(db, tmp_path, monkeypatch, leagues=(), season="Season 9", league_list=league_list)
    assert other.code == 1 and "Seasons 1-4" not in other.out
    broken = _run_backfill(db, tmp_path, monkeypatch, leagues=(), season="Season 14", league_list={"error": 1})
    assert broken.code == 1 and "league list could not be read" in broken.out
    assert _rows(db) == []


# --- Security review follow-ups (league-name change) ------------------------------

def test_league_season_number_ignores_oversized_numbers():
    """A league name with a huge season number is ignored instead of crashing int()."""
    import accolades
    assert accolades.league_season_number("Kanaliiga Season 16 Lower") == 16
    assert accolades.league_season_number("Kanaliiga Season " + "9" * 5000) is None
    assert accolades.league_season_number("Kanaliiga Season 12345") is None


def test_backfill_clean_name_strips_control_characters():
    """External names lose control characters (terminal escapes) and stay capped."""
    import importlib.util, pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "backfill_played.py"
    spec = importlib.util.spec_from_file_location("backfill_played_ctrl", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._clean_name("Kanaliiga\x1b[31m Season 14\x07") == "Kanaliiga[31m Season 14"
    assert mod._clean_name("\x00\x1f") is None
    assert len(mod._clean_name("x" * 500)) == mod.MAX_NAME


def test_archived_seasons_table_escapes_season_label():
    """The archived-seasons table escapes the admin-entered season label."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "app-admin-season.js").read_text()
    assert "${_escHtml(s.season_label)}" in src
    assert "<td>${s.season_label}</td>" not in src
