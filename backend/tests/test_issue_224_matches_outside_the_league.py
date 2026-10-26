"""
Tests for plan-issue-224-matches-outside-the-league.md (resolves GitHub issue #224).

A match played outside the league lobby can be added from Admin > Matches >
Add match, either from OpenDota by match id (source "opendota_manual") or from
a JSON summary produced locally from the .dem replay by
`backend/scripts/replay_to_match.py` (source "replay"). A new `matches.source`
column ("league" by default) records where a match came from; parse retry,
stuck flagging and Retry parse skip "replay" matches.

  Migration and model: Match.source
  Shared store: store_manual_match / ingest_match(source=...)
  Story 1: Add a Match OpenDota Has Outside the League
  Everything follows: week, Schedule series result, leaderboard, team view, follow-ups
  Story 2: Import a Match From a Replay (validation, preview, store, parse retry, corrections)
  Local script: replay_to_match.py aggregation against a recorded parser fixture
  Story 3: Manual Matches Are Visible as Such (API source, chips, filter, frontend)

Approach notes (for the developer filling these in):

- Use the `db` fixture below (in-memory SQLite on one shared StaticPool
  connection, overriding conftest's) so a TestClient's request thread sees the
  seeded rows. Never touch the real app database or `data/fantasy.db`.
- Never reach the network: monkeypatch `ingest.opendota_get_json` (and
  `opendota_post_json` / `request_parse`) with a fake that returns a hand-built
  `/matches/{id}` payload (`players` with account_id, player_slot / isRadiant,
  hero_id, kills, deaths, assists and the other stats `_build_stat_row` reads;
  `picks_bans`; radiant_name / dire_name; start_time; duration; radiant_win).
  Also stub `ingest._bust_panel_cache` and `schedule.get_schedule` /
  `schedule._fetch_hero_icon_map` where the code path calls them.
- Routes: `POST /admin/matches/manual/preview` and `POST /admin/matches/manual`
  in `backend/routers/admin_matches.py`. For HTTP tests, build a small FastAPI
  app with that router, `SessionMiddleware`, an override of `get_db`, and an
  override of `deps.get_current_user` returning the admin identity dict
  (`_signed_in` pattern in test_issue_214_admin_enhancements.py); `require_admin`
  still checks `is_admin` in the database, so seed a User row. For the re-auth
  check, assert `require_recent_reauth` is in the store route's dependencies
  (as test_issue_214 does) and/or call without a recent reauth and expect
  403 {"detail": "reauth_required"}. Disable rate limits on the router's own
  limiter instance if the route is limited, and restore it on teardown.
- Compute expected fantasy points with `scoring.fantasy_score` and the seeded
  weights (`seed.DEFAULT_WEIGHTS`), never hard-coded numbers. After seeding
  stats directly, call `card_points.rebuild_all(db)` / `refresh_card_points`.
- "Partial stats" uses the existing markers from unparseable-match-handling.md
  (`Match.parse_status` other than "parsed", as `routers/players.py` exposes
  it); check in the code which value the implementation picks and pin that.
- Recorded parser output fixture: put a small file under `backend/tests/fixtures/`
  (e.g. `replay_parser_sample.jsonl`, a trimmed odota/parser event stream for
  ten players) and load `backend/scripts/replay_to_match.py` with
  `spec_from_file_location` (no `@dataclass` in the script, see lessons-learned).
  The parser container itself is never run in tests.
- Migration tests follow tests/test_migrate.py and the `_legacy_engine` pattern
  in tests/test_issue_129_*.py (earlier migrations recorded as applied).
- Frontend stubs read `frontend/app-admin.js` (and any `app-admin-*.js` module
  the dialog lands in), `index.html`, `style.css`. Parse markup with
  `html.parser`, never regex over tags. Node harnesses: reuse `_js` /
  `_ADMIN_HARNESS` patterns from test_issue_213 / test_issue_214 and skip when
  Node is missing. New CSS goes before "GUIDED TOUR (issue #144)", tokens only.

Run with: cd backend && python -m pytest tests/test_issue_224_matches_outside_the_league.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registers every table for the db fixture)
from database import Base

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


import ast
import importlib.util
import json
import re
import time
from datetime import datetime
from html.parser import HTMLParser

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

import ingest
import manual_match
import schedule
import weeks
from database import get_db
from models import (AuditLog, Card, CardMatchPoints, League, Match, MatchBan, Player, PlayerMatchStats,
                    Team, User, Week, Weight, WeeklyRosterEntry)
from scoring import display_points, fantasy_score
from seed import DEFAULT_WEIGHTS

NOW = int(time.time())
_FRONTEND = os.path.join(_ROOT, "frontend")
_SCRIPT = os.path.join(_ROOT, "backend", "scripts", "replay_to_match.py")
_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "replay_parser_sample.jsonl")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stats(i, **over):
    s = {"kills": i, "deaths": 10 - i, "assists": i + 2, "last_hits": 20 * i, "denies": i,
         "gold_per_min": 300 + 20 * i, "obs_placed": i % 3, "sen_placed": i % 2, "tower_damage": 100 * i,
         "towers_killed": i % 2, "roshan_kills": 1 if i == 0 else 0,
         "teamfight_participation": round(0.05 * (i + 1), 2), "camps_stacked": i % 4,
         "rune_pickups": i + 1, "firstblood_claimed": 1 if i == 3 else 0, "stuns": 2.5 * i}
    s.update(over)
    return s


def _od_player(i, account_base=100, **over):
    radiant = i < 5
    p = {"account_id": account_base + i, "player_slot": i if radiant else 128 + i - 5, "isRadiant": radiant,
         "hero_id": i + 1, "personaname": f"Player {i}", **_stats(i)}
    p.update(over)
    return p


def _od(match_id=7001, duration=2400, start=None, version=21, radiant_name="Alpha", dire_name="Bravo",
        players=None):
    return {
        "match_id": match_id, "duration": duration, "start_time": NOW - 3600 if start is None else start,
        "radiant_win": True, "version": version, "radiant_team_id": None, "dire_team_id": None,
        "radiant_name": radiant_name, "dire_name": dire_name,
        "players": [_od_player(i) for i in range(10)] if players is None else players,
        "picks_bans": [{"is_pick": False, "hero_id": 50, "team": 0}, {"is_pick": True, "hero_id": 1, "team": 0}],
    }


def _replay_player(i, **over):
    p = {"account_id": 200 + i, "side": "radiant" if i < 5 else "dire", "hero_id": i + 1,
         "personaname": f"Replay {i}", **_stats(i)}
    p.update(over)
    return p


def _replay(match_id=8001, missing=(), start=None, duration=2400, players=None, **over):
    r = {"match_id": match_id, "start_time": NOW - 3600 if start is None else start, "duration": duration,
         "radiant_win": False, "radiant_name": "Alpha", "dire_name": "Bravo",
         "picks_bans": [{"hero_id": 60, "is_pick": False, "team": 1}],
         "players": [_replay_player(i) for i in range(10)] if players is None else players,
         "missing_stats": list(missing)}
    r.update(over)
    return r


def _seed(db) -> dict:
    for w in DEFAULT_WEIGHTS:
        db.add(Weight(key=w["key"], label=w["label"], value=w["value"]))
    db.add_all([
        League(id=1, name="Kanaliiga Season 9 Upper", is_monitored=True),
        League(id=2, name="Kanaliiga Season 9 Lower", is_monitored=True),
        League(id=3, name="Some Other League", is_monitored=False),
        Team(id=11, name="Alpha"), Team(id=12, name="Bravo"),
    ])
    db.commit()
    return {w.key: w.value for w in db.query(Weight).all()}


def _league_match(db, match_id, start=None, source="league", parse_status="parsed", zero=False,
                  account_base=500):
    db.add(Match(match_id=match_id, league_id=1, radiant_team_id=11, dire_team_id=12,
                 start_time=NOW - 3600 if start is None else start, radiant_win=True, duration=2400,
                 parse_status=parse_status, source=source))
    for i in range(10):
        aid = account_base + i
        if db.get(Player, aid) is None:
            db.add(Player(id=aid, name=f"L{i}"))
        stats = _stats(i, teamfight_participation=0, stuns=0, obs_placed=0) if zero else _stats(i)
        db.add(PlayerMatchStats(player_id=aid, match_id=match_id, team_id=11 if i < 5 else 12,
                                fantasy_points=1.0, hero_id=i + 1, **stats))
    db.commit()


def _rows(db, match_id):
    return (db.query(PlayerMatchStats).filter(PlayerMatchStats.match_id == match_id)
            .order_by(PlayerMatchStats.player_id).all())


@pytest.fixture
def quiet(monkeypatch):
    """No network and no Twitch panel: records panel cache busts and OpenDota calls."""
    calls = {"bust": 0, "od": [], "parse": []}

    def _bust():
        calls["bust"] += 1

    monkeypatch.setattr(ingest, "_bust_panel_cache", _bust)
    monkeypatch.setattr(ingest, "request_parse", lambda mid: calls["parse"].append(mid) or False)
    monkeypatch.setattr(schedule, "get_schedule", lambda db: {})
    monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
    monkeypatch.setattr(schedule, "cached_hero_maps", lambda: ({}, {}))
    return calls


def _fake_od(monkeypatch, calls, payloads):
    def _get(url, **kw):
        mid = int(url.rsplit("/", 1)[1])
        calls["od"].append(mid)
        payload = payloads.get(mid)
        return json.loads(json.dumps(payload)) if payload is not None else None
    monkeypatch.setattr(ingest, "opendota_get_json", _get)


def _client(db):
    from starlette.middleware.sessions import SessionMiddleware
    from routers import admin_matches
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key")
    app.include_router(admin_matches.router)

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _sign_in(db, client, admin=True, reauth=True, username=None):
    from deps import get_current_user, require_recent_reauth
    username = username or ("admin" if admin else "viewer")
    user = User(username=username, email=f"{username}@example.com", password_hash="x", is_admin=admin)
    db.add(user)
    db.commit()
    identity = {"user_id": user.id, "username": user.username, "is_admin": admin}
    client.app.dependency_overrides[get_current_user] = lambda: identity
    if reauth:
        client.app.dependency_overrides[require_recent_reauth] = lambda: identity
    return user


@pytest.fixture
def env(db, monkeypatch, quiet):
    """(client signed in as an admin with a recent re-auth, call log); OpenDota knows 7001."""
    _seed(db)
    _fake_od(monkeypatch, quiet, {7001: _od()})
    client = _client(db)
    _sign_in(db, client)
    return client, quiet


def _store_body(**over):
    body = {"league_id": 1, "radiant_team_id": 11, "dire_team_id": 12}
    body.update(over)
    return body


def _audits(db, action="admin_match_added"):
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


# ---------------------------------------------------------------------------
# Migration and model: Match.source
# ---------------------------------------------------------------------------

def _legacy_file_engine(tmp_path, drop_source=True):
    import migrate
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        if drop_source:
            conn.execute(text("ALTER TABLE matches DROP COLUMN source"))
            conn.execute(text("INSERT INTO matches (match_id, league_id, start_time) VALUES (1, 1, 100), (2, 1, 200)"))
        conn.commit()
        migrate._ensure_migrations_table(conn)
        for migration_id, _ in migrate.MIGRATIONS:
            if migration_id < "043":
                migrate._record(conn, migration_id)
        conn.commit()
    return engine


class TestSourceColumn:

    def test_match_model_source_defaults_to_league(self, db):
        """A Match inserted without `source` reads back source == "league"; the column is NOT NULL."""
        db.add(Match(match_id=1, start_time=100))
        db.commit()
        db.expire_all()
        assert db.get(Match, 1).source == "league"
        assert Match.__table__.c.source.nullable is False
        db.execute(text("INSERT INTO matches (match_id, start_time) VALUES (2, 200)"))
        assert db.execute(text("SELECT source FROM matches WHERE match_id = 2")).scalar() == "league"

    def test_migration_adds_source_and_backfills_league(self, tmp_path):
        """On a legacy matches table without `source` (earlier migrations recorded as applied), run_migrations adds the column and every existing row reads "league"."""
        import migrate
        engine = _legacy_file_engine(tmp_path)
        with engine.connect() as conn:
            assert "source" not in {r[1] for r in conn.execute(text("PRAGMA table_info(matches)"))}
        migrate.run_migrations(engine)
        with engine.connect() as conn:
            cols = {r[1]: r for r in conn.execute(text("PRAGMA table_info(matches)"))}
            assert "source" in cols and cols["source"][3] == 1  # NOT NULL
            assert [r[0] for r in conn.execute(text("SELECT source FROM matches ORDER BY match_id"))] == \
                ["league", "league"]
            assert conn.execute(text("SELECT 1 FROM schema_migrations WHERE id = '043_matches_source'")
                                ).scalar() == 1
        engine.dispose()

    def test_migration_source_is_idempotent(self, tmp_path):
        """Running run_migrations twice on a database that already has matches.source raises nothing and leaves existing source values (e.g. "replay") unchanged."""
        import migrate
        engine = _legacy_file_engine(tmp_path, drop_source=False)
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO matches (match_id, start_time, source) VALUES (5, 1, 'replay'), "
                              "(6, 2, 'opendota_manual')"))
            conn.commit()
        migrate.run_migrations(engine)
        migrate._m043_matches_source(engine.connect())  # the function itself is safe to repeat
        migrate.run_migrations(engine)
        with engine.connect() as conn:
            assert [r[0] for r in conn.execute(text("SELECT source FROM matches ORDER BY match_id"))] == \
                ["replay", "opendota_manual"]
            assert [r[1] for r in conn.execute(text("PRAGMA table_info(matches)"))].count("source") == 1
        engine.dispose()


# ---------------------------------------------------------------------------
# Shared store: ingest_match(source=...) and store_manual_match
# ---------------------------------------------------------------------------

class TestSharedStore:

    def test_ingest_match_league_path_writes_source_league(self, db, monkeypatch, quiet):
        """ingest.ingest_match with a faked OpenDota payload and no source argument stores Match.source == "league" (regular ingest unchanged)."""
        weights = _seed(db)
        _fake_od(monkeypatch, quiet, {7001: _od()})
        assert ingest.ingest_match(db, 7001, 1, set(), set(), weights) == "stored"
        match = db.get(Match, 7001)
        assert match.source == "league"
        assert match.league_id == 1 and match.parse_status == "parsed"
        assert len(_rows(db, 7001)) == 10
        assert quiet["bust"] == 1

    def test_store_manual_match_stat_rows_match_build_stat_row(self, db, monkeypatch, quiet):
        """store_manual_match writes one PlayerMatchStats row per player with raw stats from the payload and fantasy_points equal to scoring.fantasy_score with the seeded weights (same as _build_stat_row), team_id set from the chosen radiant/dire team ids."""
        weights = _seed(db)
        payload = _od()
        assert ingest.store_manual_match(db, payload, 1, 11, 12, "opendota_manual") == "stored"
        rows = _rows(db, 7001)
        assert len(rows) == 10
        for row, p in zip(rows, payload["players"]):
            built = ingest._build_stat_row(p, 7001, 11, 12, weights)
            assert row.player_id == p["account_id"]
            assert row.team_id == (11 if p["isRadiant"] else 12)
            assert row.fantasy_points == pytest.approx(fantasy_score(p, weights))
            for stat in manual_match.STAT_FIELDS:
                assert getattr(row, stat) == pytest.approx(getattr(built, stat)), stat

    def test_store_manual_match_creates_missing_players_and_bans(self, db, monkeypatch, quiet):
        """store_manual_match creates Player rows for unknown account ids (as _ensure_players does) and MatchBan rows for non-pick picks_bans entries."""
        _seed(db)
        db.add(Player(id=100, name="Known"))
        db.commit()
        ingest.store_manual_match(db, _od(), 1, 11, 12, "opendota_manual")
        assert db.query(Player).filter(Player.id.between(100, 109)).count() == 10
        assert db.get(Player, 100).name == "Known"
        assert db.get(Player, 105).name == "Player 5"
        assert [b.hero_id for b in db.query(MatchBan).filter(MatchBan.match_id == 7001)] == [50]

    def test_store_manual_match_skips_short_match(self, db, monkeypatch, quiet):
        """A payload with duration < 900 s stores no Match and no PlayerMatchStats rows (same short-match rule as ingest_match) and reports the refusal."""
        _seed(db)
        assert ingest.store_manual_match(db, _od(duration=899), 1, 11, 12, "opendota_manual") == "too_short"
        assert db.query(Match).count() == 0
        assert db.query(PlayerMatchStats).count() == 0


# ---------------------------------------------------------------------------
# Story 1: Add a Match OpenDota Has Outside the League
# ---------------------------------------------------------------------------

class TestOpenDotaPreview:

    def test_manual_preview_opendota_returns_match_summary(self, db, env):
        """POST /admin/matches/manual/preview with a match id (OpenDota faked) answers 200 with start_time, duration, winner, ten players (name, hero, kills/deaths/assists) and the radiant/dire team names from OpenDota; nothing is written to the database."""
        client, calls = env
        res = client.post("/admin/matches/manual/preview", json={"match_id": 7001})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["source"] == "opendota_manual"
        assert data["start_time"] == NOW - 3600 and data["duration"] == 2400
        assert data["winner"] == "radiant" and data["radiant_win"] is True
        assert (data["radiant_name"], data["dire_name"]) == ("Alpha", "Bravo")
        assert len(data["players"]) == 10
        first = data["players"][0]
        assert first["name"] == "Player 0" and first["hero_id"] == 1
        assert (first["kills"], first["deaths"], first["assists"]) == (0, 10, 2)
        assert [p["side"] for p in data["players"]] == ["radiant"] * 5 + ["dire"] * 5
        assert calls["od"] == [7001]
        assert db.query(Match).count() == 0 and db.query(PlayerMatchStats).count() == 0
        assert db.query(Player).count() == 0

    def test_manual_preview_opendota_prefills_teams_by_name(self, db, env, monkeypatch):
        """When OpenDota's radiant_name / dire_name match seeded Team names, the preview returns their ids as suggested radiant/dire team ids; an unmatched name suggests none."""
        client, calls = env
        data = client.post("/admin/matches/manual/preview", json={"match_id": 7001}).json()
        assert (data["suggested_radiant_team_id"], data["suggested_dire_team_id"]) == (11, 12)
        _fake_od(monkeypatch, calls, {7002: _od(match_id=7002, radiant_name="  alpha ", dire_name="Nobody")})
        data = client.post("/admin/matches/manual/preview", json={"match_id": 7002}).json()
        assert data["suggested_radiant_team_id"] == 11
        assert data["suggested_dire_team_id"] is None
        assert {"id": 12, "name": "Bravo"} in data["teams"]

    def test_manual_preview_opendota_lists_monitored_leagues(self, db, env):
        """The preview (or the league options it returns) offers only monitored leagues (League.is_monitored), each with its division label; an unmonitored league is absent."""
        client, _ = env
        leagues = client.post("/admin/matches/manual/preview", json={"match_id": 7001}).json()["leagues"]
        assert [(lg["id"], lg["division"], lg["division_label"]) for lg in leagues] == \
            [(1, "div1", "Div 1"), (2, "div2", "Div 2")]
        assert 3 not in [lg["id"] for lg in leagues]

    def test_manual_preview_refuses_league_duplicate(self, db, env):
        """Previewing a match id already stored with source "league" answers 4xx with a message saying it is already a league match."""
        client, calls = env
        _league_match(db, 7001)
        res = client.post("/admin/matches/manual/preview", json={"match_id": 7001})
        assert res.status_code == 409
        assert "already stored as a league match" in res.json()["detail"]
        assert calls["od"] == []

    def test_manual_preview_refuses_no_player_data(self, db, env, monkeypatch):
        """When OpenDota returns no players (or is unavailable), the preview answers 4xx with a message containing "Use a replay import instead"."""
        client, calls = env
        _fake_od(monkeypatch, calls, {7003: _od(match_id=7003, players=[])})
        for mid in (7003, 7004):  # 7004: OpenDota answers nothing
            res = client.post("/admin/matches/manual/preview", json={"match_id": mid})
            assert res.status_code == 422
            assert "Use a replay import instead" in res.json()["detail"]

    def test_manual_preview_refuses_short_match(self, db, env, monkeypatch):
        """A match shorter than 15 minutes (duration < 900) is refused with a 4xx message about its length."""
        client, calls = env
        _fake_od(monkeypatch, calls, {7005: _od(match_id=7005, duration=600)})
        res = client.post("/admin/matches/manual/preview", json={"match_id": 7005})
        assert res.status_code == 422
        assert "shorter than 15 minutes" in res.json()["detail"]

    def test_manual_preview_requires_admin(self, db, monkeypatch, quiet):
        """A signed-in non-admin calling POST /admin/matches/manual/preview gets 403 and OpenDota is never called."""
        _seed(db)
        _fake_od(monkeypatch, quiet, {7001: _od()})
        client = _client(db)
        _sign_in(db, client, admin=False)
        res = client.post("/admin/matches/manual/preview", json={"match_id": 7001})
        assert res.status_code == 403
        assert quiet["od"] == []


class TestOpenDotaStore:

    def test_manual_store_opendota_stores_with_chosen_league_and_teams(self, db, env):
        """POST /admin/matches/manual (OpenDota path) stores the Match with the chosen league_id, radiant_team_id and dire_team_id (overriding OpenDota's empty team ids), start_time/duration/radiant_win from OpenDota, and ten stat rows."""
        client, _ = env
        res = client.post("/admin/matches/manual", json=_store_body(match_id=7001, league_id=2))
        assert res.status_code == 200, res.text
        match = db.get(Match, 7001)
        assert (match.league_id, match.radiant_team_id, match.dire_team_id) == (2, 11, 12)
        assert (match.start_time, match.duration, match.radiant_win) == (NOW - 3600, 2400, True)
        assert len(_rows(db, 7001)) == 10
        assert res.json()["players"] == 10

    def test_manual_store_opendota_sets_source_opendota_manual(self, db, env):
        """The stored Match has source == "opendota_manual"."""
        client, _ = env
        res = client.post("/admin/matches/manual", json=_store_body(match_id=7001))
        assert res.json()["source"] == "opendota_manual"
        assert db.get(Match, 7001).source == "opendota_manual"

    def test_manual_store_opendota_audits_admin_match_added(self, db, env):
        """An AuditLog row with action "admin_match_added" is written, actor = the admin, detail naming source opendota_manual, the match id and the league id."""
        client, _ = env
        client.post("/admin/matches/manual", json=_store_body(match_id=7001, league_id=2))
        rows = _audits(db)
        assert len(rows) == 1
        assert rows[0].actor_username == "admin" and rows[0].actor_id is not None
        assert "source=opendota_manual" in rows[0].detail
        assert "match_id=7001" in rows[0].detail and "league_id=2" in rows[0].detail
        assert "replaced=no" in rows[0].detail

    def test_manual_store_requires_recent_reauth(self, db, monkeypatch, quiet):
        """POST /admin/matches/manual has require_recent_reauth among its route dependencies; without a recent reauth it answers 403 {"detail": "reauth_required"} and stores nothing."""
        from deps import require_recent_reauth
        from routers import admin_matches
        route = next(r for r in admin_matches.router.routes
                     if getattr(r, "path", "") == "/admin/matches/manual" and "POST" in r.methods)
        assert require_recent_reauth in [d.call for d in route.dependant.dependencies]
        _seed(db)
        _fake_od(monkeypatch, quiet, {7001: _od()})
        client = _client(db)
        _sign_in(db, client, reauth=False)
        res = client.post("/admin/matches/manual", json=_store_body(match_id=7001))
        assert res.status_code == 403 and res.json() == {"detail": "reauth_required"}
        assert db.query(Match).count() == 0 and quiet["od"] == []

    def test_manual_store_requires_both_teams(self, db, env):
        """Storing without a radiant or dire team id answers 4xx naming the missing team and stores nothing."""
        client, _ = env
        res = client.post("/admin/matches/manual", json=_store_body(match_id=7001, dire_team_id=None))
        assert res.status_code == 422 and "dire_team_id" in res.json()["detail"]
        body = _store_body(match_id=7001)
        del body["radiant_team_id"]
        res = client.post("/admin/matches/manual", json=body)
        assert res.status_code == 422 and "radiant_team_id" in res.json()["detail"]
        assert db.query(Match).count() == 0

    def test_manual_store_rejects_unmonitored_league(self, db, env):
        """A league_id that is not a monitored league answers 4xx and stores nothing."""
        client, _ = env
        res = client.post("/admin/matches/manual", json=_store_body(match_id=7001, league_id=3))
        assert res.status_code == 422 and "league_id" in res.json()["detail"]
        assert db.query(Match).count() == 0

    def test_manual_store_refuses_league_duplicate(self, db, env):
        """Storing a match id already stored with source "league" answers 4xx (409) even with a confirm flag, and the existing match and stat rows are unchanged."""
        client, _ = env
        _league_match(db, 7001)
        before = [(r.player_id, r.kills, r.fantasy_points) for r in _rows(db, 7001)]
        res = client.post("/admin/matches/manual", json=_store_body(match_id=7001, confirm=True, league_id=2))
        assert res.status_code == 409
        db.expire_all()
        assert [(r.player_id, r.kills, r.fantasy_points) for r in _rows(db, 7001)] == before
        assert db.get(Match, 7001).source == "league" and db.get(Match, 7001).league_id == 1
        assert _audits(db) == []

    def test_opendota_manual_match_parse_retry_treated_normally(self, db, env, monkeypatch):
        """An opendota_manual match with zero signature stats inside the retry window is returned by ingest.find_unparsed_match_ids (parse retry treats it like an ingested match)."""
        client, calls = env
        zero = [_od_player(i, teamfight_participation=0, stuns=0, obs_placed=0) for i in range(10)]
        _fake_od(monkeypatch, calls, {7010: _od(match_id=7010, version=None, players=zero)})
        assert client.post("/admin/matches/manual", json=_store_body(match_id=7010)).status_code == 200
        assert db.get(Match, 7010).parse_status == "unparsed"
        assert 7010 in ingest.find_unparsed_match_ids(db, 48)
        assert calls["parse"] == [7010]  # a parse was requested, as ingest does


# ---------------------------------------------------------------------------
# Everything follows: week, Schedule, leaderboard, team view, follow-ups
# ---------------------------------------------------------------------------

def _week(db, wid=1, label="Week 1", start=None, end=None, substitutions_at=None):
    w = Week(id=wid, label=label, start_time=NOW - 86400 if start is None else start,
             end_time=NOW + 86400 if end is None else end, is_locked=True, substitutions_at=substitutions_at)
    db.add(w)
    db.commit()
    return w


class TestEverythingFollows:

    def test_stored_manual_match_counts_in_scoring_week(self, db, env):
        """After store, weeks.scoring_week_for returns the Week containing the match's start_time, and a week_override_id still wins over start_time."""
        client, _ = env
        _week(db, 1)
        _week(db, 2, "Week 2", start=NOW + 86400 + 1, end=NOW + 3 * 86400)
        client.post("/admin/matches/manual", json=_store_body(match_id=7001))
        match = db.get(Match, 7001)
        week, source = weeks.scoring_week_for(db, match)
        assert (week.id, source) == (1, "time")
        match.week_override_id = 2
        db.commit()
        week, source = weeks.scoring_week_for(db, match)
        assert (week.id, source) == (2, "override")

    def test_stored_manual_match_resolves_schedule_series_result(self, db, env):
        """schedule.resolve_series_result for a fixture between the two chosen teams within ±4 days counts the stored manual match (wins and match_ids include it)."""
        client, _ = env
        client.post("/admin/matches/manual", json=_store_body(match_id=7001))
        lookup = schedule.build_team_lookup(db)
        iso = datetime.fromtimestamp(NOW - 86400).isoformat()
        result = schedule.resolve_series_result(db, "Alpha", "Bravo", lookup, iso)
        assert result is not None
        assert result["match_ids"] == [7001]
        assert (result["team1_wins"], result["team2_wins"]) == (1, 0)

    def test_stored_manual_match_appears_in_leaderboard(self, db, env):
        """The players of the stored manual match appear in the leaderboard / weekly points for that week with points equal to their fantasy_score sums."""
        from routers import leaderboard
        client, _ = env
        weights = {w.key: w.value for w in db.query(Weight).all()}
        week = _week(db, 1)
        manager = User(username="manager", email="m@example.com", password_hash="x")
        db.add_all([manager, Player(id=100, name="Player 0")])
        db.commit()
        card = Card(player_id=100, owner_id=manager.id, card_type="common", league_id=1, is_active=True)
        db.add(card)
        db.commit()
        db.add(WeeklyRosterEntry(week_id=week.id, user_id=manager.id, card_id=card.id))
        db.commit()
        client.post("/admin/matches/manual", json=_store_body(match_id=7001))
        board = leaderboard.weekly_leaderboard(week_id=week.id, db=db)
        row = next(r for r in board if r["username"] == "manager")
        assert row["week_points"] == display_points(fantasy_score(_od_player(0), weights))

    def test_stored_manual_match_appears_in_team_view(self, db, env):
        """GET /teams/{id} for a chosen team includes the stored manual match's games and points, grouped under the chosen league's division."""
        import team_insights
        client, _ = env
        team_insights.clear_league_cache()
        client.post("/admin/matches/manual", json=_store_body(match_id=7001, league_id=2))
        weights = {w.key: w.value for w in db.query(Weight).all()}
        detail = team_insights.team_detail(db, db.get(Team, 11), weights)
        assert detail["division"] == "div2"
        assert detail["summary"]["games"] == 1 and detail["summary"]["wins"] == 1
        assert sorted(p["id"] for p in detail["players"]) == [100, 101, 102, 103, 104]
        expected = sum(fantasy_score(_od_player(i), weights) for i in range(5))
        assert sum(p["total_points"] for p in detail["players"]) == pytest.approx(expected, abs=0.05)
        team_insights.clear_league_cache()

    def test_store_manual_match_runs_ingest_followups(self, db, monkeypatch, quiet):
        """Storing calls the MVP re-apply (_reapply_mvp_bonus), refreshes card points for the match (card_match_points rows exist) and busts the panel cache (_bust_panel_cache called once)."""
        _seed(db)
        owner = User(username="owner", email="o@example.com", password_hash="x")
        db.add_all([owner, Player(id=100, name="Player 0")])
        db.commit()
        db.add(Card(player_id=100, owner_id=owner.id, card_type="common", league_id=1, is_active=True))
        db.commit()
        reapplied = []
        original = ingest._reapply_mvp_bonus
        monkeypatch.setattr(ingest, "_reapply_mvp_bonus",
                            lambda d, mid: reapplied.append(mid) or original(d, mid))
        ingest.store_manual_match(db, _od(), 1, 11, 12, "opendota_manual")
        assert reapplied == [7001]
        assert db.query(CardMatchPoints).filter(CardMatchPoints.match_id == 7001).count() == 1
        assert quiet["bust"] == 1

    def test_store_manual_match_reruns_substitutions_for_week(self, db, monkeypatch, quiet):
        """Storing calls weeks.rerun_substitutions_for with the match's scoring week id (spy on it); a match outside any week calls it with no ids or not at all."""
        _seed(db)
        _week(db, 1, substitutions_at=NOW)
        calls = []
        original = weeks.rerun_substitutions_for
        monkeypatch.setattr(weeks, "rerun_substitutions_for",
                            lambda d, ids, reason, **kw: calls.append((set(ids), reason)) or original(d, ids, reason, **kw))
        ingest.store_manual_match(db, _od(), 1, 11, 12, "opendota_manual")
        assert calls == [({1}, "match_added")]
        assert [a.detail for a in _audits(db, "admin_substitutions_rerun")][0].startswith("id=1 ")
        calls.clear()
        ingest.store_manual_match(db, _od(match_id=7002, start=NOW - 30 * 86400), 1, 11, 12, "opendota_manual")
        assert calls == [] or calls == [(set(), "match_added")]

    def test_store_manual_match_clears_schedule_cache(self, db, monkeypatch, quiet):
        """After storing, schedule._cache["data"] (set to a sentinel before) is cleared so the next get_schedule recomputes series results."""
        _seed(db)
        monkeypatch.setitem(schedule._cache, "data", {"sentinel": True})
        monkeypatch.setitem(schedule._cache, "fetched_at", NOW)
        ingest.store_manual_match(db, _od(), 1, 11, 12, "opendota_manual")
        assert schedule._cache["data"] is None


# ---------------------------------------------------------------------------
# Story 2: Import a Match From a Replay — validation
# ---------------------------------------------------------------------------

def _invalid(payload):
    with pytest.raises(manual_match.ManualMatchError) as exc:
        manual_match.validate_replay(payload)
    return exc.value


class TestReplayValidation:

    def test_validate_replay_accepts_valid_payload(self):
        """manual_match validation accepts a well-formed payload (match id, start time, duration, winner, picks_bans, team names, ten players with account_id, side, hero_id and every stat _build_stat_row reads, missing_stats list) and returns the normalised payload."""
        payload = _replay(missing=["stuns", "teamfight_participation"], radiant_name="  Alpha ")
        out = manual_match.validate_replay(payload)
        assert out["match_id"] == 8001 and out["duration"] == 2400 and out["radiant_win"] is False
        assert out["radiant_name"] == "Alpha" and out["dire_name"] == "Bravo"
        assert out["missing_stats"] == ["teamfight_participation", "stuns"]  # schema order
        assert out["picks_bans"] == [{"hero_id": 60, "is_pick": False, "team": 1}]
        assert len(out["players"]) == 10
        assert set(out["players"][0]) == {"account_id", "side", "hero_id", "personaname", *manual_match.STAT_FIELDS}
        assert isinstance(out["players"][3]["stuns"], float)
        built = ingest._build_stat_row(manual_match.replay_to_store_payload(out)["players"][7], 8001, 11, 12, {})
        assert built.team_id == 12 and built.player_id == 207

    def test_validate_replay_rejects_wrong_player_count(self):
        """Nine or eleven players are rejected with an error naming the `players` field."""
        assert _invalid(_replay(players=[_replay_player(i) for i in range(9)])).field == "players"
        eleven = [_replay_player(i) for i in range(10)] + [_replay_player(10, side="dire")]
        assert _invalid(_replay(players=eleven)).field == "players"

    def test_validate_replay_rejects_unbalanced_sides(self):
        """Ten players split six/four between radiant and dire are rejected with an error naming the side field."""
        players = [_replay_player(i, side="radiant" if i < 6 else "dire") for i in range(10)]
        err = _invalid(_replay(players=players))
        assert "side" in err.field and "radiant 6" in err.message

    def test_validate_replay_rejects_unknown_top_level_key(self):
        """An extra top-level key is rejected with an error naming that key."""
        err = _invalid(_replay(extra_field=1))
        assert err.field == "extra_field" and "unknown" in err.message

    def test_validate_replay_rejects_unknown_player_key(self):
        """An extra key inside a player object is rejected with an error naming players[i].<key>."""
        players = [_replay_player(i) for i in range(10)]
        players[3]["xp"] = 100
        assert _invalid(_replay(players=players)).field == "players[3].xp"

    def test_validate_replay_rejects_unknown_hero_id(self):
        """A hero_id not in the known hero ids is rejected with an error naming players[i].hero_id."""
        players = [_replay_player(i) for i in range(10)]
        players[0]["hero_id"] = 9999
        assert _invalid(_replay(players=players)).field == "players[0].hero_id"
        players[0]["hero_id"] = 24  # an id Dota never used
        assert _invalid(_replay(players=players)).field == "players[0].hero_id"

    def test_validate_replay_rejects_out_of_range_numbers(self):
        """Negative kills, a GPM above the sane maximum, a duration of 0 or an account id above 2**63-1 are each rejected with the failing field named."""
        for field, value in (("kills", -1), ("gold_per_min", 5000), ("account_id", 2**63),
                             ("teamfight_participation", 1.5), ("kills", True)):
            players = [_replay_player(i) for i in range(10)]
            players[0][field] = value
            assert _invalid(_replay(players=players)).field == f"players[0].{field}", field
        assert _invalid(_replay(duration=0)).field == "duration"

    def test_validate_replay_rejects_missing_required_field(self):
        """A payload without match_id (or a player without account_id) is rejected with the missing field named."""
        payload = _replay()
        del payload["match_id"]
        err = _invalid(payload)
        assert err.field == "match_id" and err.message == "is required"
        players = [_replay_player(i) for i in range(10)]
        del players[0]["account_id"]
        assert _invalid(_replay(players=players)).field == "players[0].account_id"

    def test_validate_replay_rejects_unknown_missing_stats_name(self):
        """missing_stats entries must be stat names _build_stat_row reads; an unknown name is rejected."""
        err = _invalid(_replay(missing=["kills", "net_worth"]))
        assert err.field == "missing_stats[1]"

    def test_manual_preview_replay_rejects_oversized_upload(self, db, env):
        """A replay JSON body over the limit answers 413 before parsing and stores nothing."""
        client, _ = env
        payload = _replay(radiant_name="x" * (300 * 1024))
        res = client.post("/admin/matches/manual/preview", json={"replay": payload})
        assert res.status_code == 413
        res = client.post("/admin/matches/manual", json={"replay": payload, **_store_body()})
        assert res.status_code == 413
        assert db.query(Match).count() == 0
        # Between the route's 60 KB and the site-wide 64 KB cap: the route's own message.
        payload = _replay(radiant_name="x" * (61 * 1024))
        res = client.post("/admin/matches/manual/preview", json={"replay": payload})
        assert res.status_code == 413 and res.json()["detail"] == "The replay file is larger than 56 KB"

    def test_manual_preview_rejects_deeply_nested_json(self, db, env):
        """Deeply nested brackets answer 422, not a 500 (security review Low)."""
        client, _ = env
        res = client.post("/admin/matches/manual/preview", content=b"[" * 50000,
                          headers={"Content-Type": "application/json"})
        assert res.status_code == 422

    def test_manual_preview_replay_rejects_malformed_json(self, db, env):
        """A body that is not valid JSON answers 422 with a clear message, not a 500."""
        client, _ = env
        res = client.post("/admin/matches/manual/preview", content=b'{"replay": {not json',
                          headers={"Content-Type": "application/json"})
        assert res.status_code == 422 and res.json()["detail"] == "The request is not valid JSON"
        res = client.post("/admin/matches/manual/preview", json=[1, 2])
        assert res.status_code == 422
        res = client.post("/admin/matches/manual/preview", json={"replay": "text"})
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# Story 2: Import a Match From a Replay — preview and store
# ---------------------------------------------------------------------------

class TestReplayPreviewAndStore:

    def test_manual_preview_replay_returns_same_shape_as_opendota(self, db, env):
        """POST /admin/matches/manual/preview with replay JSON answers 200 with the same keys as the OpenDota preview (start time, duration, winner, ten players with name/hero/K/D/A, team names, suggested team ids)."""
        client, _ = env
        od = client.post("/admin/matches/manual/preview", json={"match_id": 7001}).json()
        res = client.post("/admin/matches/manual/preview", json={"replay": _replay()})
        assert res.status_code == 200, res.text
        rp = res.json()
        assert set(rp) == set(od)
        assert set(rp["players"][0]) == set(od["players"][0])
        assert rp["source"] == "replay" and rp["winner"] == "dire" and len(rp["players"]) == 10
        assert (rp["suggested_radiant_team_id"], rp["suggested_dire_team_id"]) == (11, 12)
        assert rp["players"][0]["name"] == "Replay 0"
        assert db.query(Match).count() == 0

    def test_manual_preview_replay_partial_stats_note(self, db, env):
        """With missing_stats ["teamfight_participation"], the preview includes a partial-stats note listing it; with an empty list there is no note."""
        client, _ = env
        data = client.post("/admin/matches/manual/preview",
                           json={"replay": _replay(missing=["teamfight_participation"])}).json()
        assert data["partial_note"] == "Partial stats: teamfight_participation"
        assert data["missing_stats"] == ["teamfight_participation"]
        data = client.post("/admin/matches/manual/preview", json={"replay": _replay()}).json()
        assert data["partial_note"] is None and data["missing_stats"] == []

    def test_manual_preview_replay_warns_players_not_in_pool(self, db, env):
        """Players whose account id is not in the season's pool are flagged with a warning in the preview; pool players are not."""
        client, _ = env
        db.add_all([Player(id=200, name="Pooled", is_active=True), Player(id=201, name="Retired", is_active=False)])
        db.commit()
        data = client.post("/admin/matches/manual/preview", json={"replay": _replay()}).json()
        flags = {p["account_id"]: p["in_pool"] for p in data["players"]}
        assert flags[200] is True and flags[201] is False and flags[205] is False
        assert 200 not in data["not_in_pool"] and sorted(data["not_in_pool"]) == list(range(201, 210))

    def test_manual_store_replay_sets_source_replay(self, db, env):
        """POST /admin/matches/manual with replay JSON stores the Match with source == "replay", the chosen league and teams, and ten stat rows scored with fantasy_score."""
        client, calls = env
        weights = {w.key: w.value for w in db.query(Weight).all()}
        res = client.post("/admin/matches/manual", json={"replay": _replay(), **_store_body(league_id=2)})
        assert res.status_code == 200, res.text
        match = db.get(Match, 8001)
        assert match.source == "replay"
        assert (match.league_id, match.radiant_team_id, match.dire_team_id, match.radiant_win) == (2, 11, 12, False)
        rows = _rows(db, 8001)
        assert len(rows) == 10
        for row in rows:
            p = _replay_player(row.player_id - 200)
            assert row.fantasy_points == pytest.approx(fantasy_score(p, weights))
        assert [b.hero_id for b in db.query(MatchBan).filter(MatchBan.match_id == 8001)] == [60]
        assert calls["od"] == [] and calls["parse"] == []

    def test_manual_store_replay_missing_stats_marked_partial(self, db, env):
        """Stats listed in missing_stats are stored as 0 and the Match carries the existing partial-stat marker (parse_status as chosen by the implementation, not "parsed")."""
        client, _ = env
        res = client.post("/admin/matches/manual",
                          json={"replay": _replay(missing=["teamfight_participation"]), **_store_body()})
        assert res.status_code == 200
        assert res.json()["missing_stats"] == ["teamfight_participation"]
        assert db.get(Match, 8001).parse_status == "unparseable"
        assert all(r.teamfight_participation == 0 for r in _rows(db, 8001))
        assert any(r.stuns for r in _rows(db, 8001))

    def test_manual_store_replay_complete_stats_not_partial(self, db, env):
        """With an empty missing_stats the stored replay match has parse_status "parsed" (no partial marker)."""
        client, _ = env
        client.post("/admin/matches/manual", json={"replay": _replay(), **_store_body()})
        assert db.get(Match, 8001).parse_status == "parsed"

    def test_manual_store_replay_stores_players_not_in_pool(self, db, env):
        """Players not in the season pool are still stored (Player row created, stat row written), as ingest does."""
        client, _ = env
        client.post("/admin/matches/manual", json={"replay": _replay(), **_store_body()})
        assert db.get(Player, 205).name == "Replay 5"
        assert db.query(PlayerMatchStats).filter_by(player_id=205, match_id=8001).count() == 1

    def test_manual_store_replay_audits_with_source_replay(self, db, env):
        """An AuditLog "admin_match_added" row is written whose detail includes source=replay, the match id and the league id."""
        client, _ = env
        client.post("/admin/matches/manual", json={"replay": _replay(missing=["stuns"]), **_store_body(league_id=2)})
        detail = _audits(db)[0].detail
        assert "source=replay" in detail and "match_id=8001" in detail and "league_id=2" in detail
        assert "missing_stats=stuns" in detail

    def test_manual_store_replay_requires_recent_reauth(self, db, monkeypatch, quiet):
        """Storing replay JSON without a recent reauth answers 403 {"detail": "reauth_required"} and stores nothing."""
        _seed(db)
        client = _client(db)
        _sign_in(db, client, reauth=False)
        res = client.post("/admin/matches/manual", json={"replay": _replay(), **_store_body()})
        assert res.status_code == 403 and res.json() == {"detail": "reauth_required"}
        assert db.query(Match).count() == 0

    def test_manual_store_replay_invalid_payload_stores_nothing(self, db, env):
        """Storing a payload that fails validation answers 422 naming the field and leaves matches / player_match_stats empty."""
        client, _ = env
        bad = _replay(players=[_replay_player(i) for i in range(9)])
        res = client.post("/admin/matches/manual", json={"replay": bad, **_store_body()})
        assert res.status_code == 422 and res.json()["detail"].startswith("players:")
        assert db.query(Match).count() == 0 and db.query(PlayerMatchStats).count() == 0


# ---------------------------------------------------------------------------
# Story 2: parse retry leaves replay matches alone
# ---------------------------------------------------------------------------

class TestParseRetrySkipsReplay:

    def test_find_unparsed_match_ids_skips_replay(self, db):
        """A recent source="replay" match whose signature stats sum to 0 is not returned by ingest.find_unparsed_match_ids, while an otherwise identical league match is."""
        db.add_all([Team(id=11, name="Alpha"), Team(id=12, name="Bravo")])
        _league_match(db, 1, zero=True, parse_status="unparsed")
        _league_match(db, 2, zero=True, parse_status="unparsed", source="replay", account_base=600)
        assert ingest.find_unparsed_match_ids(db, 48) == [1]

    def test_mark_stuck_matches_unparseable_skips_replay(self, db):
        """An old source="replay" match with parse_status "unparsed" is not marked unparseable and gets no match_marked_unparseable audit row; a league match in the same state is."""
        old = NOW - 10 * 86400
        _league_match(db, 1, start=old, zero=True, parse_status="unparsed")
        _league_match(db, 2, start=old, zero=True, parse_status="unparsed", source="replay", account_base=600)
        assert ingest.mark_stuck_matches_unparseable(db, 48) == [1]
        assert db.get(Match, 1).parse_status == "unparseable"
        assert db.get(Match, 2).parse_status == "unparsed"
        assert [a.detail for a in _audits(db, "match_marked_unparseable")] == ["match 1 still unparsed after 48h"]

    def test_retry_unparsed_pass_never_refreshes_replay(self, db, monkeypatch, quiet):
        """ingest.retry_unparsed_matches (OpenDota faked to return parsed data) never calls refresh_match_stats for a replay match; its stat rows are unchanged."""
        _seed(db)
        _league_match(db, 8001, zero=True, parse_status="parsed", source="replay", account_base=600)
        before = [(r.player_id, r.kills, r.fantasy_points) for r in _rows(db, 8001)]
        _fake_od(monkeypatch, quiet, {8001: _od(match_id=8001)})
        refreshed = []
        original = ingest.refresh_match_stats
        monkeypatch.setattr(ingest, "refresh_match_stats",
                            lambda d, mid, w: refreshed.append(mid) or original(d, mid, w))
        monkeypatch.setattr(ingest, "SessionLocal", lambda: db)
        monkeypatch.setattr(ingest, "_parse_requested", {})
        summary = ingest.retry_unparsed_matches(48)
        assert refreshed == [] and summary["checked"] == 0
        assert quiet["od"] == []
        assert [(r.player_id, r.kills, r.fantasy_points) for r in _rows(db, 8001)] == before

    def test_retry_parse_endpoint_refuses_replay(self, db, env):
        """POST /admin/matches/{id}/retry-parse for a replay match answers 4xx with a message, makes no OpenDota call and leaves stat rows unchanged."""
        client, calls = env
        _league_match(db, 8001, zero=True, parse_status="unparsed", source="replay", account_base=600)
        before = [(r.player_id, r.kills, r.fantasy_points) for r in _rows(db, 8001)]
        res = client.post("/admin/matches/8001/retry-parse")
        assert res.status_code == 409 and "replay" in res.json()["detail"]
        assert calls["od"] == [] and calls["parse"] == []
        assert [(r.player_id, r.kills, r.fantasy_points) for r in _rows(db, 8001)] == before


# ---------------------------------------------------------------------------
# Story 2: corrections (re-import)
# ---------------------------------------------------------------------------

class TestReimport:

    def test_reimport_replaces_replay_match_rows_after_confirm(self, db, env):
        """Re-importing the same match id with corrected replay JSON and the confirm flag replaces the replay match's stat rows (new values, still ten rows, no duplicates) and its match fields."""
        client, _ = env
        assert client.post("/admin/matches/manual", json={"replay": _replay(), **_store_body()}).status_code == 200
        db.get(Match, 8001).vod_url = "https://example.com/vod"
        db.commit()
        corrected = _replay(duration=2500, radiant_win=True,
                            players=[_replay_player(i, kills=i + 10) for i in range(10)])
        res = client.post("/admin/matches/manual", json={"replay": corrected, **_store_body(confirm=True)})
        assert res.status_code == 200, res.text
        assert res.json()["replaced"] is True
        db.expire_all()
        rows = _rows(db, 8001)
        assert len(rows) == 10 and len({r.player_id for r in rows}) == 10
        assert [r.kills for r in rows] == [i + 10 for i in range(10)]
        match = db.get(Match, 8001)
        assert (match.duration, match.radiant_win, match.vod_url) == (2500, True, "https://example.com/vod")
        assert db.query(MatchBan).filter(MatchBan.match_id == 8001).count() == 1

    def test_reimport_replaces_opendota_manual_match(self, db, env):
        """Re-adding an opendota_manual match (from OpenDota or a replay) with confirm replaces its rows; source becomes the new path's source."""
        client, _ = env
        client.post("/admin/matches/manual", json=_store_body(match_id=7001))
        res = client.post("/admin/matches/manual", json=_store_body(match_id=7001, confirm=True))
        assert res.status_code == 200 and res.json()["replaced"] is True
        assert len(_rows(db, 7001)) == 10
        res = client.post("/admin/matches/manual",
                          json={"replay": _replay(match_id=7001), **_store_body(confirm=True)})
        assert res.status_code == 200, res.text
        db.expire_all()
        assert db.get(Match, 7001).source == "replay"
        assert sorted(r.player_id for r in _rows(db, 7001)) == list(range(200, 210))

    def test_reimport_without_confirm_is_refused(self, db, env):
        """Re-importing an existing manual/replay match without the confirm flag answers 409 (asking for confirmation) and leaves the rows unchanged."""
        client, _ = env
        client.post("/admin/matches/manual", json={"replay": _replay(), **_store_body()})
        corrected = _replay(players=[_replay_player(i, kills=i + 10) for i in range(10)])
        res = client.post("/admin/matches/manual", json={"replay": corrected, **_store_body()})
        assert res.status_code == 409 and "Confirm to replace" in res.json()["detail"]
        assert [r.kills for r in _rows(db, 8001)] == list(range(10))
        preview = client.post("/admin/matches/manual/preview", json={"replay": corrected}).json()
        assert preview["existing_source"] == "replay"

    def test_reimport_never_replaces_league_match(self, db, env):
        """Importing replay JSON for a match id stored with source "league" answers 4xx even with confirm; its stat rows and source are unchanged."""
        client, _ = env
        _league_match(db, 8001)
        before = [(r.player_id, r.kills, r.fantasy_points) for r in _rows(db, 8001)]
        res = client.post("/admin/matches/manual", json={"replay": _replay(), **_store_body(confirm=True)})
        assert res.status_code == 409 and "league match" in res.json()["detail"]
        db.expire_all()
        assert db.get(Match, 8001).source == "league"
        assert [(r.player_id, r.kills, r.fantasy_points) for r in _rows(db, 8001)] == before
        with pytest.raises(ValueError):
            ingest.store_manual_match(db, manual_match.replay_to_store_payload(manual_match.validate_replay(_replay())),
                                      1, 11, 12, "replay", replace=True)

    def test_reimport_is_audited(self, db, env):
        """A replacing re-import writes an admin_match_added audit row whose detail marks it as a replacement."""
        client, _ = env
        client.post("/admin/matches/manual", json=_store_body(match_id=7001))
        client.post("/admin/matches/manual", json={"replay": _replay(match_id=7001), **_store_body(confirm=True)})
        rows = _audits(db)
        assert len(rows) == 2
        assert "replaced=no" in rows[0].detail
        assert "replaced=yes" in rows[1].detail and "previous_source=opendota_manual" in rows[1].detail


# ---------------------------------------------------------------------------
# Local script: replay_to_match.py against a recorded parser output fixture
# ---------------------------------------------------------------------------

def _script():
    spec = importlib.util.spec_from_file_location("replay_to_match_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture_events(mod):
    with open(_FIXTURE, encoding="utf-8") as fh:
        return mod.parse_events(fh)


def _final_intervals():
    """Each slot's last interval event in the fixture, read independently of the script."""
    last = {}
    with open(_FIXTURE, encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e["type"] == "interval" and e["time"] >= 0 and e["time"] >= last.get(e["slot"], {}).get("time", -1):
                last[e["slot"]] = e
    return last


class TestReplayToMatchScript:

    def test_replay_to_match_aggregates_fixture(self):
        """Loading scripts/replay_to_match.py and running its aggregation on tests/fixtures/replay_parser_sample.jsonl yields ten players with account_id, side, hero_id and the expected per-player kills/deaths/assists/last_hits/gpm etc. recorded in the fixture."""
        mod = _script()
        out = mod.aggregate(_fixture_events(mod))
        assert (out["match_id"], out["duration"], out["radiant_win"]) == (8100000001, 2400, True)
        # endTime_ 1790002400 minus playbackTime_ 2700.5 (draft and pre-game included; Step 0 finding)
        assert out["start_time"] == 1790002400 - 2700
        assert (out["radiant_name"], out["dire_name"]) == ("Synthetic Radiant", "Synthetic Dire")
        assert [pb["hero_id"] for pb in out["picks_bans"] if not pb["is_pick"]] == [74, 86]
        assert len(out["players"]) == 10
        final = _final_intervals()
        for slot, p in enumerate(out["players"]):
            e = final[slot]
            assert p["account_id"] == 1001 + slot  # matched through the file info, listed out of order
            assert p["side"] == ("radiant" if slot < 5 else "dire")
            assert p["hero_id"] == e["hero_id"]
            assert (p["kills"], p["deaths"], p["assists"]) == (e["kills"], e["deaths"], e["assists"])
            assert (p["last_hits"], p["denies"]) == (e["lh"], e["denies"])
            assert p["gold_per_min"] == round(e["gold"] * 60 / 2400)
            assert (p["obs_placed"], p["sen_placed"], p["camps_stacked"]) == \
                (e["obs_placed"], e["sen_placed"], e["camps_stacked"])
            assert (p["towers_killed"], p["roshan_kills"], p["rune_pickups"]) == \
                (e["towers_killed"], e["roshans_killed"], e["rune_pickups"])
            assert p["stuns"] == pytest.approx(e["stuns"]) and p["tower_damage"] == e["tower_damage"]
            assert p["firstblood_claimed"] == e["firstblood_claimed"]

    def test_replay_to_match_lists_missing_stats(self):
        """Stats the fixture's events cannot produce (e.g. teamfight_participation) are 0 for every player and listed under missing_stats."""
        mod = _script()
        out = mod.aggregate(_fixture_events(mod))
        assert out["missing_stats"] == ["teamfight_participation"]
        assert all(p["teamfight_participation"] == 0 for p in out["players"])

    def test_replay_to_match_output_passes_server_validation(self):
        """The aggregated output dict passes manual_match validation unchanged (script and server agree on the schema)."""
        mod = _script()
        out = mod.aggregate(_fixture_events(mod))
        assert manual_match.validate_replay(json.loads(json.dumps(out))) == out
        assert mod.STAT_ORDER == list(manual_match.STAT_FIELDS)

    def test_replay_to_match_writes_match_id_json(self, tmp_path, monkeypatch):
        """With the parser call stubbed to return the fixture events, main(["replay.dem"]) writes match-<id>.json in the output directory containing the aggregated payload."""
        mod = _script()
        events = _fixture_events(mod)
        dem = tmp_path / "replay.dem"
        dem.write_bytes(b"PBDEMS2\0")
        seen = []
        monkeypatch.setattr(mod, "run_parser", lambda path, url: seen.append((path, url)) or events)
        out_dir = tmp_path / "out"
        assert mod.main([str(dem), "--out-dir", str(out_dir)]) == 0
        assert seen == [(str(dem), mod.DEFAULT_PARSER_URL)]
        written = json.loads((out_dir / "match-8100000001.json").read_text())
        assert written == mod.aggregate(events)

    def test_replay_to_match_parser_unreachable_exits_cleanly(self, tmp_path, monkeypatch, capsys):
        """When the local parser container cannot be reached (stubbed connection error), the script exits non-zero with a readable message and writes no file."""
        mod = _script()
        dem = tmp_path / "replay.dem"
        dem.write_bytes(b"PBDEMS2\0")

        def _refused(*a, **kw):
            raise mod.urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

        monkeypatch.setattr(mod.urllib.request, "urlopen", _refused)
        code = mod.main([str(dem), "--out-dir", str(tmp_path)])
        assert code != 0
        assert "could not reach the replay parser" in capsys.readouterr().err
        assert list(tmp_path.glob("match-*.json")) == []

    def test_replay_to_match_uses_standard_library_only(self):
        """Every import in scripts/replay_to_match.py (parsed with ast) is from the standard library."""
        with open(_SCRIPT, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0
                names.add(node.module.split(".")[0])
        assert names and names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


# ---------------------------------------------------------------------------
# Story 3: Manual Matches Are Visible as Such — API
# ---------------------------------------------------------------------------

class TestAdminMatchesSource:

    def test_admin_matches_list_includes_source(self, db, env):
        """GET /admin/matches returns `source` for each match: "league", "opendota_manual" or "replay"."""
        client, _ = env
        _league_match(db, 1)
        _league_match(db, 2, source="opendota_manual", account_base=600)
        _league_match(db, 3, source="replay", account_base=700)
        res = client.get("/admin/matches")
        assert res.status_code == 200
        assert {r["match_id"]: r["source"] for r in res.json()} == \
            {1: "league", 2: "opendota_manual", 3: "replay"}

    def test_admin_matches_list_includes_added_by_and_when(self, db, env):
        """For manual and replay matches, GET /admin/matches returns who added them and when, taken from the latest admin_match_added audit row; league matches have none."""
        client, _ = env
        _league_match(db, 1)
        client.post("/admin/matches/manual", json=_store_body(match_id=7001))
        client.post("/admin/matches/manual", json={"replay": _replay(), **_store_body()})
        rows = {r["match_id"]: r for r in client.get("/admin/matches").json()}
        for mid in (7001, 8001):
            assert rows[mid]["added_by"] == "admin"
            assert abs(rows[mid]["added_at"] - time.time()) < 60
        assert rows[1]["added_by"] is None and rows[1]["added_at"] is None

    def test_admin_matches_list_requires_admin(self, db, quiet):
        """A non-admin calling GET /admin/matches gets 403 (source data not exposed)."""
        _seed(db)
        client = _client(db)
        _sign_in(db, client, admin=False)
        assert client.get("/admin/matches").status_code == 403

    def test_public_match_views_do_not_expose_source(self, db, env):
        """Public player/team match endpoints (routers/players.py) return no `source` key for a replay match; only the existing parse_status partial marker differs."""
        from routers import players as players_router
        import team_insights
        client, _ = env
        client.post("/admin/matches/manual",
                    json={"replay": _replay(missing=["teamfight_participation"]), **_store_body()})
        data = players_router.get_player(200, db=db)
        row = data["match_history"][0]
        assert "source" not in row
        assert row["parse_status"] == "unparseable"
        assert '"source"' not in json.dumps(data) and '"replay"' not in json.dumps(data)
        team_insights.clear_league_cache()
        team = players_router.get_team(11, db=db)
        assert '"source"' not in json.dumps(team)
        team_insights.clear_league_cache()


# ---------------------------------------------------------------------------
# Story 1 + 3: Admin UI (frontend source-reading and Node harness)
# ---------------------------------------------------------------------------

def _fe(name):
    with open(os.path.join(_FRONTEND, name), encoding="utf-8") as fh:
        return fh.read()


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []  # (tag, attrs, position)
        self.text_by_id = {}
        self._open = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.els.append((tag, a))
        if a.get("id") and tag in ("button", "label", "h2", "option"):
            self._open.append(a["id"])

    def handle_endtag(self, tag):
        if self._open and tag in ("button", "label", "h2", "option"):
            self._open.pop()

    def handle_data(self, data):
        for el_id in self._open:
            self.text_by_id[el_id] = self.text_by_id.get(el_id, "") + data


def _harness(body):
    from tests.test_issue_214_admin_enhancements import _js
    return _js(["app-admin-matches.js"], body)


_PREVIEW = {
    "source": "replay", "match_id": 8001, "start_time": 1790000000, "duration": 2405, "radiant_win": False,
    "winner": "dire", "radiant_name": "Alpha", "dire_name": "<b>Bravo</b>",
    "suggested_radiant_team_id": 11, "suggested_dire_team_id": 12,
    "players": [{"account_id": 200 + i, "name": "<img src=x>" if i == 0 else f"P{i}",
                 "side": "radiant" if i < 5 else "dire", "hero_id": i + 1,
                 "hero_name": "Anti-Mage" if i == 0 else None, "kills": i, "deaths": 1, "assists": 2,
                 "in_pool": i != 3} for i in range(10)],
    "not_in_pool": [203], "missing_stats": ["teamfight_participation"],
    "partial_note": "Partial stats: teamfight_participation", "existing_source": None,
    "leagues": [{"id": 1, "name": "Upper", "division": "div1", "division_label": "Div 1"},
                {"id": 2, "name": "Lower", "division": "div2", "division_label": "Div 2"}],
    "teams": [{"id": 11, "name": "Alpha"}, {"id": 12, "name": "Bravo"}],
}


class TestAdminUi:

    def test_frontend_add_match_dialog_markup(self):
        """index.html (parsed with html.parser) has an Add match button in Admin > Matches and a dialog with two tabs (From OpenDota first, From replay), a match id input, a file input accepting .json, a league select and Radiant/Dire team selects, all labelled."""
        html = _fe("index.html")
        tab = html[html.index('data-admin-tab="matches"'):html.index("<!-- MVP Selection Modal")]
        p = _Collect()
        p.feed(html)
        by_id = {a.get("id"): (tag, a) for tag, a in p.els if a.get("id")}
        assert 'id="adminAddMatchBtn"' in tab and p.text_by_id["adminAddMatchBtn"].strip() == "Add match"
        assert by_id["adminAddMatchBtn"][1]["onclick"] == "openAddMatchDialog()"
        tag, modal = by_id["addMatchModal"]
        assert modal["role"] == "dialog" and modal["aria-modal"] == "true"
        assert modal["data-close"] == "closeAddMatchDialog"
        tabs = [a for tag, a in p.els if a.get("role") == "tab"
                and a.get("id", "").startswith("addMatchTab")]
        assert [t["id"] for t in tabs] == ["addMatchTabOpenDota", "addMatchTabReplay"]
        assert p.text_by_id["addMatchTabOpenDota"].strip() == "From OpenDota"
        assert p.text_by_id["addMatchTabReplay"].strip() == "From replay"
        assert tabs[0]["aria-selected"] == "true" and tabs[1]["aria-selected"] == "false"
        assert by_id["addMatchId"][0] == "input"
        assert by_id["addMatchFile"][1]["type"] == "file" and ".json" in by_id["addMatchFile"][1]["accept"]
        for sel in ("addMatchLeague", "addMatchRadiant", "addMatchDire"):
            assert by_id[sel][0] == "select"
        labels = {a.get("for") for tag, a in p.els if tag == "label"}
        assert {"addMatchId", "addMatchFile", "addMatchLeague", "addMatchRadiant", "addMatchDire"} <= labels
        assert by_id["addMatchStoreBtn"][1].get("disabled") is not None or "disabled" in by_id["addMatchStoreBtn"][1]
        assert 'id="adminMatchesManualOnly"' in tab

    def test_frontend_add_match_preview_renders(self):
        """Node harness: the preview render helper given a preview payload renders start time, duration, winner, ten player rows (escaped names, hero, K/D/A), prefilled team selects, the partial-stats note and not-in-pool warnings."""
        out = _harness(f"""
            renderAddMatchPreview({json.dumps(_PREVIEW)});
            out = {{
              html: document.getElementById("addMatchPreview").innerHTML,
              radiant: document.getElementById("addMatchRadiant").value,
              dire: document.getElementById("addMatchDire").value,
              leagues: document.getElementById("addMatchLeague").children.map(o => o.textContent),
              disabled: document.getElementById("addMatchStoreBtn").disabled,
              start: new Date(1790000000 * 1000).toLocaleString(),
            }};
        """)
        html = out["html"]
        assert out["start"] in html and "40:05" in html
        assert "Dire won (&lt;b&gt;Bravo&lt;/b&gt;)" in html
        assert html.count("<tr><td>") == 10
        assert "&lt;img src=x&gt;" in html and "<img" not in html
        assert "Anti-Mage" in html and "Hero 2" in html and "<td>3/1/2</td>" in html
        assert '<p class="add-match-partial">Partial stats: teamfight_participation</p>' in html
        assert html.count('<span class="add-match-warn">Not in pool</span>') == 1
        assert (out["radiant"], out["dire"]) == ("11", "12")
        assert out["leagues"] == ["Choose…", "Upper (Div 1)", "Lower (Div 2)"]
        assert out["disabled"] is False

    def test_frontend_add_match_store_uses_adminfetch(self):
        """Node harness / source: Add posts to /admin/matches/manual through adminFetch (so the re-auth popup flow runs), and a 409 replace answer asks for confirmation before resending with confirm."""
        assert "adminFetch(`${API}/admin/matches/manual`" in _fe("app-admin-matches.js")
        out = _harness(f"""
            const viaAdmin = [];
            adminFetch = async (url, opts) => {{ viaAdmin.push(url); return fetch(url, opts); }};
            let asked = 0;
            globalThis.confirm = () => {{ asked += 1; return true; }};
            let stores = 0;
            __routes.push(["/admin/matches/manual/preview", () => __resp(200, {json.dumps(_PREVIEW)})]);
            __routes.push(["/admin/matches/manual", (url, opts) => {{
              stores += 1;
              return stores === 1
                ? __resp(409, {{detail: "Match 8001 was already added (replay). Confirm to replace its stats."}})
                : __resp(200, {{match_id: 8001, source: "replay", replaced: true, missing_stats: []}});
            }}]);
            __routes.push(["/admin/matches/out-of-week", () => __resp(200, [])]);
            __routes.push(["/admin/matches", () => __resp(200, [])]);
            __routes.push(["/admin/weeks", () => __resp(200, [])]);
            document.getElementById("addMatchId").value = "8001";
            setAddMatchMode("opendota");
            await previewAddMatch();
            document.getElementById("addMatchLeague").value = "2";
            await storeAddMatch();
            const posts = __fetchCalls.filter(c => c.method === "POST" && c.url === "/admin/matches/manual");
            out = {{viaAdmin, asked, bodies: posts.map(c => JSON.parse(c.body)),
                    status: __status.adminMatchesStatus, modal: document.getElementById("addMatchModal").style.display}};
        """)
        assert out["viaAdmin"] == ["/admin/matches/manual", "/admin/matches/manual"]
        assert out["asked"] == 1
        assert [b["confirm"] for b in out["bodies"]] == [False, True]
        assert out["bodies"][0] == {"match_id": 8001, "league_id": 2, "radiant_team_id": 11,
                                    "dire_team_id": 12, "confirm": False}
        assert out["status"]["msg"] == "Match 8001 replaced as Replay"
        assert out["modal"] == "none"

    def test_frontend_add_match_shows_refusal_message(self):
        """Node harness: a 4xx preview answer (e.g. "Use a replay import instead") is shown in the dialog's status line and no preview is rendered."""
        out = _harness("""
            __routes.push(["/admin/matches/manual/preview", () => __resp(422,
              {detail: "OpenDota has no player data for match 5. Use a replay import instead."})]);
            document.getElementById("addMatchId").value = "5";
            setAddMatchMode("opendota");
            await previewAddMatch();
            out = {status: __status.addMatchStatus, preview: document.getElementById("addMatchPreview").innerHTML,
                   disabled: document.getElementById("addMatchStoreBtn").disabled};
        """)
        assert out["status"] == {"msg": "OpenDota has no player data for match 5. Use a replay import instead.",
                                 "ok": False}
        assert out["preview"] == "" and out["disabled"] is True

    def test_frontend_source_chip_renders_manual_and_replay(self):
        """Node harness: the admin matches row renderer shows a "Manual" chip for opendota_manual and a "Replay" chip for replay, with a tooltip naming who added it and when; a league match has no chip."""
        base = {"radiant_team_id": 11, "dire_team_id": 12, "team1": "Alpha", "team2": "Bravo",
                "start_time": 1790000000, "league_name": "Upper", "division": "div1"}
        rows = [dict(base, match_id=1, source="opendota_manual", added_by="ville", added_at=1790003600),
                dict(base, match_id=2, source="replay", added_by="<b>x</b>", added_at=1790003600),
                dict(base, match_id=3, source="league")]
        out = _harness(f"""
            const rows = {json.dumps(rows)};
            out = {{html: rows.map(_adminMatchRowHtml), when: new Date(1790003600 * 1000).toLocaleString()}};
        """)
        manual, replay, league = out["html"]
        assert ">Manual</span>" in manual and f'title="Added by ville, {out["when"]}"' in manual
        assert ">Replay</span>" in replay and "Added by &lt;b&gt;x&lt;/b&gt;" in replay
        assert "admin-source-chip" not in league

    def test_frontend_manual_only_filter(self):
        """Node harness: enabling the "Manual only" filter lists only opendota_manual and replay matches; disabling it lists all."""
        rows = [{"match_id": 1, "source": "league"}, {"match_id": 2, "source": "opendota_manual"},
                {"match_id": 3, "source": "replay"}, {"match_id": 4}]
        out = _harness(f"""
            const rows = {json.dumps(rows)};
            const pick = on => filterAdminMatches(rows, {{mvpMissing: false, league: "", unparseable: false, manualOnly: on}})
              .map(m => m.match_id);
            document.getElementById("adminMatchesManualOnly").checked = true;
            out = {{on: pick(true), off: pick(false), fromDom: adminMatchesFilters().manualOnly,
                    empty: adminMatchesEmptyText({{manualOnly: true}})}};
        """)
        assert out == {"on": [2, 3], "off": [1, 2, 3, 4], "fromDom": True,
                       "empty": "No matches for the filters: Manual only"}

    def test_frontend_add_match_css_before_guided_tour_tokens_only(self):
        """style.css rules for the Add match dialog and source chips sit before "GUIDED TOUR (issue #144)" and use var(--…) tokens, no raw hex colours."""
        css = _fe("style.css")
        tour = css.index("GUIDED TOUR (issue #144)")
        start = css.index("/* Add match dialog and source chips (issue 224)")
        assert start < tour
        block = css[start:css.rindex("/* ===", 0, tour)]
        for selector in (".admin-source-chip", ".add-match-modal", ".add-match-tabs", ".add-match-preview",
                         ".add-match-warn", ".add-match-partial", ".add-match-pickers"):
            assert selector in block and css.index(selector) < tour, selector
        assert ".add-match-" not in css[tour:] and ".admin-source-chip" not in css[tour:]
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", block)
        assert "rgba(" not in block and "var(--" in block
        assert "#224" not in block


def _bytestring(text):
    """Gson's serialisation of a protobuf ByteString, as the real parser sends it
    (Java's signed bytes)."""
    return {"bytes": [b - 256 if b > 127 else b for b in text.encode("utf-8")], "hash": 0}


class TestReplayToMatchRealParserFormat:
    """Step 0 findings (2026-10-26, a real Kanaliiga replay checked against OpenDota):
    names arrive as ByteStrings, and the start time comes from the playback time."""

    def test_text_decodes_gson_bytestrings(self):
        """_text reads {"bytes": [...]} with signed bytes (UTF-8), plain strings, and drops control characters."""
        mod = _script()
        assert mod._text(_bytestring("HOLISA")) == "HOLISA"
        assert mod._text(_bytestring("无为")) == "无为"
        assert mod._text("  SC ") == "SC"
        assert mod._text(_bytestring("Bad\x1b[31mName")) == "Bad[31mName"
        assert mod._text({"bytes": "nope"}) is None and mod._text(None) is None
        # C1 controls (8-bit CSI) and bidi overrides are dropped too (security review of #236)
        assert mod._text("A\u009b31mB") == "A31mB"
        assert mod._text("Evil\u202eName") == "EvilName"

    def test_bytestring_names_match_players_and_playback_sets_start(self):
        """With ByteString hero/player names and team tags plus playbackTime_, slots match by hero name (the file info lists players out of order), names and tags are decoded, and start_time = endTime - playbackTime."""
        mod = _script()
        events = _fixture_events(mod)
        for e in events:
            if e.get("type") != "epilogue":
                continue
            epi = json.loads(e["key"])
            dota = epi["gameInfo_"]["dota_"]
            for info in dota["playerInfo_"]:
                info["heroName_"] = _bytestring(info["heroName_"])
                info["playerName_"] = _bytestring(info["playerName_"])
            dota["radiantTeamTag_"] = _bytestring("SC")
            dota["direTeamTag_"] = _bytestring("HOLISA")
            epi["playbackTime_"] = 3879.3335
            end_time = dota["endTime_"]
            e["key"] = json.dumps(epi)
        out = mod.aggregate(events)
        assert out["start_time"] == end_time - 3879
        assert (out["radiant_name"], out["dire_name"]) == ("SC", "HOLISA")
        assert [p["account_id"] for p in out["players"]] == [1001 + s for s in range(10)]
        assert all(p["personaname"] for p in out["players"])
