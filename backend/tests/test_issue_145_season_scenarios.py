"""
Failing test stubs for plan-issue-145-season-scenarios.md (resolves GitHub issue #145).

`POST /admin/demo/scenario` (Demo Mode only, admin, recent re-auth) replaces the game
data with a named, deterministic season (`pre-season`, `mid-season`, `season-end`) and
sets the demo clock; `ENV=production` refuses to start with `DEMO_MODE=true`. One class
per user story; one stub per acceptance criterion plus the primary failure path, and
stubs for the testable Verification bullets.

Developer notes
---------------

  Modules the plan adds (none exist yet, verified 2026-11-18)
    - `backend/season_generator.py`: `generate(seed, *, weeks, teams, players_per_team,
      games_per_team_week, users, cards_per_user, roster_size, start)` -> plain dicts.
      No database, no app imports beyond `scoring.SCORING_STATS` and
      `card_utils._SCORED_STAT_COLS` (lessons-learned 2026-11-17: modifier keys come
      from `_SCORED_STAT_COLS`, never SCORING_STATS + deaths).
    - `backend/scenarios.py`: `SCENARIOS`, `KEPT_TABLES`, an extra-delete list (name it,
      e.g. `EXTRA_DELETED_TABLES`), `SCENARIO_LEAGUE_ID = 990001`, `load(db, name,
      caller_id)`.
    - `routers/admin_demo.py`: `ScenarioBody(name: Literal[...])` and the route function
      (suggest `load_demo_scenario(body, db, admin)`), with route-level
      `Depends(_require_demo_mode), Depends(require_recent_reauth)` AND an imperative
      `_require_demo_mode()` call in the body (direct-call tests bypass Depends).

  Fixtures and patterns to reuse
    - `db`: copy the StaticPool in-memory `db` fixture from
      test_issue_133_season_reset_clean_slate.py (overrides conftest's) so a TestClient
      request thread sees the same data. Also copy its autouse `_clean_caches`
      (`season_reset.bust_caches()` before and after) since the loader busts caches.
    - Direct calls: follow test_issue_83_demo_mode.py: `monkeypatch.setenv("DEMO_MODE",
      "true")` / `delenv`, call the router function with `db=db, admin=dict(_ADMIN)`,
      and `pytest.raises(HTTPException)` for 404/409. Set `DEMO_ACCOUNT_PASSWORD` with
      monkeypatch in every happy-path test.
    - Re-auth (403 `reauth_required`): build a small FastAPI app like
      test_issue_133's `_client(db, login=None, reauth=True)` but include
      `routers.admin_demo.router`; log in through the `/_test/login/{id}?fresh=false`
      helper (sessions.start_session + optional sessions.mark_reauth), then POST.
      The caller's own session row must survive the load: assert it on that client.
    - 404-before-auth over real HTTP: the `client` fixture in test_issue_83 (reloads
      `main` against an in-memory engine) proves dependency order; reuse it for the
      unauthenticated scenario request.
    - Production guard: `_run_import_main(tmp_path, env)` / `_LONG_SECRET` in
      test_issue_136_security_audit_3.py (subprocess import of main). Expect
      returncode != 0, "RuntimeError", "[SECURITY]" and "DEMO_MODE=true" in stderr.
      `main._active_dev_flags` is at main.py ~line 576.
    - Coverage test: mirror `test_reset_table_lists_cover_every_table_exactly_once`
      (test_issue_133): every name in `Base.metadata.tables` is in
      `season_reset.CLEARED_TABLES`, `scenarios.KEPT_TABLES` or the scenario's
      extra-delete list; no name in two of them; no name that isn't a table.
      Note season_reset also has UPDATED_TABLES (users, leagues, demo_clock): the
      scenario lists must classify those too (users -> extra-delete except the caller,
      demo_clock -> kept, leagues -> extra-delete).
    - Bench: test_issue_149's `_BENCH_SCRIPT` runs `bench_leaderboards.seed(60, 10, 8,
      5, 2, 15, 5, random.Random(141))` in a subprocess (cwd=REPO, DATABASE_URL popped).
      Baseline counts recorded 2026-11-18 before the move: players=40, matches=80,
      stat_rows=800, cards=900, roster_entries=3000. Pin them.
    - Weekly reports: the loader runs `auto_lock_weeks`, `due_substitutions` and
      `generate_weekly_summaries` per week, like `set_demo_clock`. Substitutions show
      as `WeeklyRosterEntry` rows with a substitution marker (check models.py for the
      issue 129/189 column name). Stored card points: compare against
      `card_points.check_week(db, week_id)` for each locked week.
    - Loading is slow-ish (10 weeks of matches): consider a module-scoped cache of a
      loaded mid-season db file if the file gets slow; keep `-n auto` safe (no shared
      on-disk paths outside tmp_path).
    - Frontend checks read `frontend/app-admin-demo.js` as text (see `_fe` in
      test_issue_133).
"""

import ast
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Boolean, Float, Integer, select, text
from starlette.middleware.sessions import SessionMiddleware

import models  # noqa: F401
import card_points
import clock
import scenarios
import season_generator
import season_reset
from database import Base, get_db
from models import (AuditLog, Card, League, Match, Player, PlayerMatchStats, ScoringState,
                    SeasonArchive, TagDefinition, Team, User, UserSession, Week,
                    WeeklyRosterEntry, WeeklySummary, Weight)

_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}
_NON_ADMIN = {"user_id": 2, "username": "u", "is_admin": False}
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
_BENCH_BASELINE = {"players": 40, "matches": 80, "stat_rows": 800, "cards": 900,
                   "roster_entries": 3000}
_PASSWORD = "scenario-pass-145"
_PHRASE = "LOAD SCENARIO"
_LONG_SECRET = "x" * 48
_WEEK1 = 1767571200  # Monday 2026-01-05 00:00 UTC


@pytest.fixture
def db():
    """In-memory database on one shared connection, so a TestClient's request
    thread sees the same data (overrides conftest's `db`)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_caches():
    season_reset.bust_caches()
    yield
    season_reset.bust_caches()


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", _PASSWORD)
    monkeypatch.delenv("SUBSTITUTION_DELAY_HOURS", raising=False)
    monkeypatch.delenv("INITIAL_TOKENS", raising=False)


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _fe(name):
    return _read("frontend", name)


def _user(db, username, admin=False, tokens=10):
    from auth import hash_password
    u = User(username=username, email=f"{username}@example.com",
             password_hash=hash_password("secret123"), is_admin=admin, tokens=tokens,
             created_at=int(time.time()))
    db.add(u)
    db.commit()
    return u


def _caller(db):
    return db.query(User).filter_by(username="admin").first() or _user(db, "admin", admin=True)


def _load(db, name="mid-season"):
    from routers.admin_demo import ScenarioBody, load_demo_scenario
    caller = _caller(db)
    out = load_demo_scenario(ScenarioBody(name=name), db=db,
                             admin={"user_id": caller.id, "username": "admin", "is_admin": True})
    db.expire_all()
    return out


def _client(db, login=None, reauth=True):
    """A small app around admin_demo sharing `db`, signed in as `login`."""
    import rate_limit
    import sessions
    from routers import admin_demo
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-145")
    app.state.limiter = rate_limit.limiter
    app.include_router(admin_demo.router)

    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db

    @app.post("/_test/login/{user_id}")
    def _login(user_id: int, request: Request, fresh: bool = True):
        sessions.start_session(request, db, db.get(User, user_id))
        if fresh:
            sessions.mark_reauth(sessions.current_row(request, db))
        db.commit()
        return {"ok": True}

    client = TestClient(app)
    if login is not None:
        assert client.post(f"/_test/login/{login.id}", params={"fresh": reauth}).status_code == 200
    return client


def _dummy(col, i):
    if isinstance(col.type, Boolean):
        return False
    if isinstance(col.type, Integer):
        return 1000 + i
    if isinstance(col.type, Float):
        return 1.0
    return f"x{i}"


def _fill(db, name, n=2, **over):
    table = Base.metadata.tables[name]
    for i in range(n):
        row = {c.name: _dummy(c, i) for c in table.columns
               if c.primary_key or (not c.nullable and c.default is None and c.server_default is None)}
        row.update(over)
        db.execute(table.insert().values(**row))
    db.commit()


def _old_data(db):
    """A little real-looking data the load must replace."""
    db.add(Team(id=77, name="Old Team"))
    db.add(Player(id=77, name="Old Player", is_active=True))
    db.add(League(id=1, name="Kanaliiga Season 16", is_monitored=True))
    db.add(Week(label="Old Week", start_time=1, end_time=2, is_locked=True))
    db.commit()
    return _user(db, "olduser")


def _snapshot(db):
    db.expire_all()
    return {name: sorted(map(tuple, db.execute(select(t)).fetchall()), key=repr)
            for name, t in Base.metadata.tables.items()}


def _game_tables(db):
    """Every game table's rows, without ids that differ between loads by design."""
    snap = _snapshot(db)
    for name in ("audit_logs", "demo_clock", "user_sessions"):
        snap.pop(name)
    cols = Base.metadata.tables["users"].columns.keys()
    skip = cols.index("password_hash")  # bcrypt salts differ
    snap["users"] = [r[:skip] + r[skip + 1:] for r in snap["users"]]
    return snap


def _scenario_users(db):
    return db.query(User).filter(User.username.in_(scenarios.ACCOUNT_NAMES)).order_by(User.username).all()


def _weeks(db):
    return db.query(Week).order_by(Week.start_time).all()


def _week_matches(db, week):
    return db.query(Match).filter(Match.start_time.between(week.start_time, week.end_time)).all()


def _run_import_main(tmp_path, env_overrides):
    env = {k: v for k, v in os.environ.items()
           if k not in ("ENV", "DEBUG", "TWITCH_LOCAL_DEV", "SECRET_KEY", "AUTO_INGEST_LEAGUES",
                        "DEMO_MODE")}
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'fantasy.db'}"
    env["HTTPS_ONLY"] = "true"
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", "import main"], cwd=_BACKEND_DIR, env=env,
                          capture_output=True, text=True, timeout=120)


# ===========================================================================
# Story 1: Load a Season Scenario
# ===========================================================================

class TestLoadSeasonScenario:

    # --- Endpoint contract -------------------------------------------------

    def test_load_scenario_mid_season_replaces_game_data_and_sets_clock(self, db, demo):
        """POST /admin/demo/scenario {"name": "mid-season"} replaces all game data with the scenario and sets the demo clock to the middle of week 6, before its lock."""
        _old_data(db)
        out = _load(db)
        assert db.query(Team).filter_by(name="Old Team").count() == 0
        assert db.get(Player, 77) is None
        assert db.query(Week).filter_by(label="Old Week").count() == 0
        assert db.query(User).filter_by(username="olduser").count() == 0
        assert {t.name for t in db.query(Team)} == {f"Scenario Team {c}" for c in "ABCDEFGH"}
        week5, week6 = _weeks(db)[4], _weeks(db)[5]
        now = clock.now(db)
        assert clock.get_override(db) == now == out["effective_now"] == out["override_timestamp"]
        # Week 5 is over (report and substitutions done) and week 6 has not locked yet.
        assert week5.end_time + 24 * 3600 <= now < week6.start_time
        assert not week6.is_locked

    def test_load_scenario_response_has_name_clock_usernames_and_counts(self, db, demo):
        """The response gives the scenario name, the effective clock, the account usernames (scenario-admin, scenario1..scenario5) and the counts."""
        out = _load(db)
        assert out["scenario"] == "mid-season"
        assert out["effective_now"] == clock.now(db)
        assert out["accounts"] == ["scenario-admin", "scenario1", "scenario2", "scenario3",
                                   "scenario4", "scenario5"]
        c = out["counts"]
        assert c["weeks"] == 10 and c["locked_weeks"] == 5 and c["teams"] == 8
        assert c["players"] == 40 and c["accounts"] == 6
        assert c["matches"] == db.query(Match).count() == 40
        assert c["cards"] == db.query(Card).count()
        assert c["stat_rows"] == db.query(PlayerMatchStats).count()
        assert c["roster_entries"] == db.query(WeeklyRosterEntry).count()
        assert c["substitutions"] >= 1

    def test_load_scenario_response_never_contains_password(self, db, demo):
        """Failure path: the response (and the audit detail) never contain the DEMO_ACCOUNT_PASSWORD value."""
        out = _load(db)
        assert _PASSWORD not in json.dumps(out)
        for (detail,) in db.query(AuditLog.detail):
            assert _PASSWORD not in (detail or "")
        assert all(u.password_hash != _PASSWORD for u in _scenario_users(db))

    def test_load_scenario_unknown_name_rejected(self, db, demo):
        """Failure path: ScenarioBody refuses a name outside pre-season / mid-season / season-end (422 over HTTP) and nothing is wiped."""
        from routers.admin_demo import ScenarioBody
        with pytest.raises(ValidationError):
            ScenarioBody(name="end-of-days")
        _old_data(db)
        client = _client(db, login=_caller(db))
        before = _snapshot(db)
        resp = client.post("/admin/demo/scenario", json={"name": "end-of-days", "confirm": _PHRASE})
        assert resp.status_code == 422
        after = _snapshot(db)
        assert {k: v for k, v in after.items() if k != "user_sessions"} == \
            {k: v for k, v in before.items() if k != "user_sessions"}

    def test_load_scenario_404_when_demo_mode_off_even_for_admin(self, db, monkeypatch):
        """Failure path: with DEMO_MODE unset, a direct call as admin raises 404 and no table changes."""
        monkeypatch.delenv("DEMO_MODE", raising=False)
        monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", _PASSWORD)
        from routers.admin_demo import ScenarioBody, load_demo_scenario
        _old_data(db)
        before = _snapshot(db)
        with pytest.raises(HTTPException) as exc:
            load_demo_scenario(ScenarioBody(name="mid-season"), db=db, admin=dict(_ADMIN))
        assert exc.value.status_code == 404
        assert _snapshot(db) == before

    def test_load_scenario_403_for_non_admin(self, db, demo):
        """Failure path: with DEMO_MODE=true, a logged-in non-admin gets 403 and nothing is wiped."""
        old = _old_data(db)
        client = _client(db, login=old)
        before = _snapshot(db)
        resp = client.post("/admin/demo/scenario", json={"name": "mid-season", "confirm": _PHRASE})
        assert resp.status_code == 403
        assert resp.json()["detail"] != "reauth_required"
        assert _snapshot(db) == before

    def test_load_scenario_403_reauth_required_without_recent_reauth(self, db, demo):
        """Failure path: an admin session without a recent POST /reauth gets 403 {"detail": "reauth_required"} and nothing is wiped."""
        _old_data(db)
        client = _client(db, login=_caller(db), reauth=False)
        before = _snapshot(db)
        resp = client.post("/admin/demo/scenario", json={"name": "mid-season", "confirm": _PHRASE})
        assert resp.status_code == 403
        assert resp.json() == {"detail": "reauth_required"}
        assert _snapshot(db) == before

    @pytest.mark.parametrize("confirm", [None, "", "yes", "LOAD", "RESET SEASON"])
    def test_load_scenario_400_without_typed_confirmation(self, db, demo, confirm):
        """Security review: without the typed phrase LOAD SCENARIO (after a recent re-auth) the load answers 400 confirmation_required and nothing is wiped."""
        import deps
        assert deps.CONFIRM_PHRASES["demo_scenario"] == _PHRASE
        _old_data(db)
        client = _client(db, login=_caller(db))
        before = _snapshot(db)
        body = {"name": "mid-season"}
        if confirm is not None:
            body["confirm"] = confirm
        resp = client.post("/admin/demo/scenario", json=body)
        assert resp.status_code == 400
        assert resp.json() == {"detail": "confirmation_required"}
        assert {k: v for k, v in _snapshot(db).items() if k != "user_sessions"} == \
            {k: v for k, v in before.items() if k != "user_sessions"}

    def test_load_scenario_route_dependency_order(self):
        """The demo-mode check comes first (404), then the re-auth (403), then the typed confirmation (400)."""
        from deps import require_recent_reauth
        from routers import admin_demo
        route = next(r for r in admin_demo.router.routes if r.path == "/admin/demo/scenario")
        deps_ = [d.dependency for d in route.dependencies]
        assert deps_[0] is admin_demo._require_demo_mode and deps_[1] is require_recent_reauth
        assert deps_[2].__name__ == "_check" and len(deps_) == 3

    def test_load_scenario_409_without_demo_account_password(self, db, demo, monkeypatch):
        """Failure path: without DEMO_ACCOUNT_PASSWORD the loader answers 409 with a message naming the variable, and no table changes."""
        monkeypatch.delenv("DEMO_ACCOUNT_PASSWORD")
        _old_data(db)
        _caller(db)
        before = _snapshot(db)
        with pytest.raises(HTTPException) as exc:
            _load(db)
        assert exc.value.status_code == 409
        assert "DEMO_ACCOUNT_PASSWORD" in exc.value.detail
        assert _snapshot(db) == before

    def test_load_scenario_writes_demo_scenario_loaded_audit(self, db, demo):
        """A load writes an audit_logs row with action demo_scenario_loaded and detail `name=… users=… matches=…`."""
        _load(db)
        rows = db.query(AuditLog).filter_by(action="demo_scenario_loaded").all()
        assert len(rows) == 1
        assert rows[0].detail == "name=mid-season users=6 matches=40"
        assert rows[0].actor_id == _caller(db).id and rows[0].actor_username == "admin"

    # --- What is kept and what is wiped ------------------------------------

    def test_scenario_table_lists_cover_every_table_exactly_once(self):
        """Every Base.metadata table is in exactly one of season_reset.CLEARED_TABLES, scenarios.KEPT_TABLES and the scenario's extra-delete list, and the lists name no table that doesn't exist."""
        lists = [season_reset.CLEARED_TABLES, scenarios.KEPT_TABLES, scenarios.EXTRA_DELETED_TABLES]
        listed = [name for group in lists for name in group]
        assert len(listed) == len(set(listed)), "a table is in more than one list"
        assert set(listed) == set(Base.metadata.tables), set(Base.metadata.tables) ^ set(listed)
        assert set(scenarios.KEPT_TABLES) == {"weights", "scoring_state", "tag_definitions",
                                              "audit_logs", "demo_clock"}
        assert {"users", "user_sessions", "leagues"} <= set(scenarios.EXTRA_DELETED_TABLES)

    def test_load_scenario_keeps_caller_user_sessions_and_kept_tables(self, db, demo):
        """The caller's user row and session rows, weights, scoring_state, tag_definitions, audit_logs and the demo_clock row survive the load; the caller stays logged in."""
        caller = _caller(db)
        other = _old_data(db)
        db.add(Weight(key="kills", label="Kills", value=0.3))
        db.add(ScoringState(key="probe", value="v"))
        db.add(TagDefinition(key="probe", label="Probe Tag"))
        db.add(AuditLog(timestamp=1, action="probe", detail="before"))
        db.commit()
        _client(db, login=other)  # another user's session
        client = _client(db, login=caller)
        caller_sessions = {r.id for r in db.query(UserSession).filter_by(user_id=caller.id)}
        assert db.query(UserSession).filter_by(user_id=other.id).count() == 1

        resp = client.post("/admin/demo/scenario", json={"name": "mid-season", "confirm": _PHRASE})
        assert resp.status_code == 200, resp.text
        db.expire_all()
        assert db.get(User, caller.id).username == "admin"
        assert {r.id for r in db.query(UserSession).filter_by(user_id=caller.id)} == caller_sessions
        assert db.query(UserSession).filter(UserSession.user_id != caller.id).count() == 0
        assert db.get(Weight, "kills").value == 0.3
        assert db.get(ScoringState, "probe").value == "v"
        assert db.query(TagDefinition).filter_by(key="probe").count() == 1
        assert db.query(AuditLog).filter_by(action="probe").count() == 1
        assert clock.get_override(db) == resp.json()["override_timestamp"]
        # Still logged in, with the re-auth still recent.
        assert client.get("/admin/demo/clock").status_code == 200
        assert client.post("/admin/demo/scenario", json={"name": "pre-season", "confirm": _PHRASE.lower()}).status_code == 200

    def test_load_scenario_removes_other_users_and_season_history(self, db, demo):
        """Every other user and their linked rows, season_archive, accolades and season summaries are gone after a load, so scenario history never mixes with real data."""
        caller = _caller(db)
        old = _old_data(db)
        for name in ("season_archive", "season_accolades", "season_player_stats",
                     "season_team_results", "user_tags", "notifications", "promo_codes",
                     "finals_brackets", "password_reset_tokens"):
            _fill(db, name)
        old_id = old.id
        _load(db)
        for name in scenarios.EXTRA_DELETED_TABLES:
            if name in ("users", "user_sessions", "leagues"):
                continue
            assert db.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() == 0, name
        assert db.query(User).filter_by(username="olduser").count() == 0
        assert db.get(User, old_id) is None or db.get(User, old_id).username in scenarios.ACCOUNT_NAMES
        assert {u.username for u in db.query(User)} == {"admin", *scenarios.ACCOUNT_NAMES}
        assert db.get(User, caller.id).username == "admin"
        assert [l.id for l in db.query(League)] == [scenarios.SCENARIO_LEAGUE_ID]

    def test_load_scenario_busts_season_caches(self, db, demo):
        """After the commit the in-memory season caches are empty (season_reset.bust_caches ran)."""
        import schedule
        import twitch
        from datetime import datetime
        schedule._cache.update(data={"weeks": [], "extra_results": []}, fetched_at=datetime.now())
        twitch._panel_cache.update(at=time.monotonic(), body={"old": True})
        _load(db)
        assert schedule._cache["data"] is None
        assert twitch._panel_cache["body"] is None

    def test_load_scenario_failure_rolls_back_everything(self, db, demo, monkeypatch):
        """Failure path: when a build step raises (monkeypatched), the wipe is rolled back with it: the old data is still there and no audit row is written."""
        _caller(db)
        _old_data(db)
        before = _snapshot(db)

        def boom(*a, **k):
            raise RuntimeError("build step failed")
        # Raises after the wipe and after the first week has locked through the real path.
        monkeypatch.setattr(scenarios, "_insert_matches", boom)
        with pytest.raises(RuntimeError):
            _load(db)
        assert _snapshot(db) == before
        assert db.query(AuditLog).filter_by(action="demo_scenario_loaded").count() == 0
        assert db.query(Team).filter_by(name="Old Team").count() == 1
        # The session commits normally again afterwards.
        assert "commit" not in vars(db)

    # --- mid-season --------------------------------------------------------

    def test_mid_season_has_ten_weeks_five_locked_and_week_six_open(self, db, demo):
        """mid-season: 10 weeks, weeks 1-5 locked and scored, week 6 unlocked and editable (get_next_editable_week returns week 6)."""
        from weeks import get_next_editable_week
        _load(db)
        weeks = _weeks(db)
        assert [w.label for w in weeks] == [f"Week {n}" for n in range(1, 11)]
        assert [w.is_locked for w in weeks] == [True] * 5 + [False] * 5
        assert weeks[0].start_time == _WEEK1
        for w in weeks[:5]:
            assert _week_matches(db, w), w.label
            assert w.substitutions_at is not None
        assert get_next_editable_week(db).id == weeks[5].id

    def test_mid_season_matches_only_in_finished_weeks(self, db, demo):
        """mid-season: matches exist only for weeks 1-5; weeks 6-10 have none."""
        _load(db)
        weeks = _weeks(db)
        assert sum(len(_week_matches(db, w)) for w in weeks[:5]) == db.query(Match).count() == 40
        assert all(not _week_matches(db, w) for w in weeks[5:])

    def test_mid_season_teams_players_and_accounts(self, db, demo):
        """mid-season: 8 teams of 5 synthetic players ("Scenario Team A".."H"), league 990001 monitored, scenario-admin (admin) plus scenario1..5, each with 10-15 cards."""
        _load(db)
        assert sorted(t.name for t in db.query(Team)) == [f"Scenario Team {c}" for c in "ABCDEFGH"]
        roster = {}
        for pid, tid in db.query(PlayerMatchStats.player_id, PlayerMatchStats.team_id).distinct():
            roster.setdefault(tid, set()).add(pid)
        assert len(roster) == 8 and all(len(p) == 5 for p in roster.values())
        assert db.query(Player).count() == 40
        league = db.get(League, 990001)
        assert scenarios.SCENARIO_LEAGUE_ID == 990001 and league.is_monitored
        users = {u.username: u for u in _scenario_users(db)}
        assert set(users) == set(scenarios.ACCOUNT_NAMES)
        assert users["scenario-admin"].is_admin
        assert not any(users[f"scenario{n}"].is_admin for n in range(1, 6))
        for u in users.values():
            assert 10 <= db.query(Card).filter_by(owner_id=u.id).count() <= 15, u.username

    def test_scenario_accounts_are_demo_with_password_and_demo_local_email(self, db, demo):
        """Every scenario account has is_demo=True, an @demo.local email, and a password hash that verifies against DEMO_ACCOUNT_PASSWORD."""
        from auth import verify_password
        _load(db)
        users = _scenario_users(db)
        assert len(users) == 6
        for u in users:
            assert u.is_demo and u.email == f"{u.username}@demo.local"
            assert u.account_type == "full" and not u.is_tester
            if u.username == "scenario-admin":
                continue
            assert verify_password(_PASSWORD, u.password_hash)
            assert not u.is_admin

    def test_scenario_admin_gets_its_own_one_time_password(self, db, demo):
        """Security review: scenario-admin gets a random password, returned once as admin_password and never stored in the audit log; the players' DEMO_ACCOUNT_PASSWORD does not open it."""
        from auth import verify_password
        out = _load(db)
        admin_pw = out["admin_password"]
        assert isinstance(admin_pw, str) and len(admin_pw) >= 16 and admin_pw != _PASSWORD
        admin = db.query(User).filter_by(username="scenario-admin").one()
        assert admin.is_admin
        assert verify_password(admin_pw, admin.password_hash)
        assert not verify_password(_PASSWORD, admin.password_hash)
        for (detail,) in db.query(AuditLog.detail):
            assert admin_pw not in (detail or "")
        # A new load makes a new admin password.
        assert _load(db)["admin_password"] != admin_pw

    @pytest.mark.parametrize("weak", ["abc", "x" * 73, "ä" * 37])
    def test_load_scenario_409_when_demo_account_password_breaks_the_rules(self, db, demo, monkeypatch, weak):
        """Security review: a DEMO_ACCOUNT_PASSWORD shorter than 6 characters or longer than 72 bytes is refused with 409 naming the variable (not its value), and nothing changes."""
        monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", weak)
        _old_data(db)
        _caller(db)
        before = _snapshot(db)
        with pytest.raises(HTTPException) as exc:
            _load(db)
        assert exc.value.status_code == 409
        assert "DEMO_ACCOUNT_PASSWORD" in exc.value.detail and weak not in exc.value.detail
        assert _snapshot(db) == before

    def test_mid_season_rosters_have_benches_and_a_bench_substitution(self, db, demo):
        """mid-season: active rosters have bench cards, and weeks 1-5 contain at least one WeeklyRosterEntry substitution produced by due_substitutions."""
        _load(db)
        weeks = _weeks(db)
        for u in _scenario_users(db):
            cards = db.query(Card).filter_by(owner_id=u.id).all()
            active = [c for c in cards if c.is_active]
            assert len(active) == 5 and sorted(c.slot_index for c in active) == list(range(5))
            assert all(c.slot_index is None for c in cards if not c.is_active)
            assert len(cards) > len(active)
        first5 = [w.id for w in weeks[:5]]
        bench = db.query(WeeklyRosterEntry).filter(WeeklyRosterEntry.week_id.in_(first5),
                                                   WeeklyRosterEntry.is_bench == True).count()  # noqa: E712
        assert bench > 0
        subbed_in = db.query(WeeklyRosterEntry).filter(WeeklyRosterEntry.week_id.in_(first5),
                                                       WeeklyRosterEntry.subbed_in == True).all()  # noqa: E712
        assert subbed_in
        out = db.get(WeeklyRosterEntry, subbed_in[0].subbed_for_entry_id)
        assert out.subbed_out and out.week_id == subbed_in[0].week_id
        assert db.query(AuditLog).filter_by(action="weekly_substitutions").count() >= 5

    def test_mid_season_mvps_on_most_matches_not_all(self, db, demo):
        """mid-season: most scored matches have an is_mvp stat row, but not every match."""
        _load(db)
        total = db.query(Match).count()
        with_mvp = db.query(PlayerMatchStats.match_id).filter(
            PlayerMatchStats.is_mvp == True).distinct().count()  # noqa: E712
        assert total / 2 < with_mvp < total

    def test_mid_season_one_unparsed_and_one_excluded_match(self, db, demo):
        """mid-season: exactly one match with parse_status 'unparsed' and partial stats, and exactly one with excluded_from_scoring=True."""
        _load(db)
        unparsed = db.query(Match).filter_by(parse_status="unparsed").all()
        excluded = db.query(Match).filter_by(excluded_from_scoring=True).all()
        assert len(unparsed) == 1 and len(excluded) == 1
        assert unparsed[0].match_id != excluded[0].match_id
        assert db.query(Match).filter_by(parse_status="parsed").count() == 39
        rows = db.query(PlayerMatchStats).filter_by(match_id=unparsed[0].match_id).all()
        assert rows and sum(r.kills for r in rows) > 0
        assert sum(r.obs_placed + r.camps_stacked + r.rune_pickups + r.stuns for r in rows) == 0

    def test_mid_season_weekly_reports_exist_for_finished_weeks(self, db, demo):
        """mid-season: generate_weekly_summaries produced a WeeklySummary for each ended week, none for week 6 onward."""
        _load(db)
        weeks = _weeks(db)
        assert {s.week_id for s in db.query(WeeklySummary)} == {w.id for w in weeks[:5]}

    def test_mid_season_stored_card_points_match_check_week(self, db, demo):
        """Stored card points (#141) are rebuilt: card_points.check_week reports no mismatch for every locked week."""
        _load(db)
        for w in _weeks(db)[:5]:
            result = card_points.check_week(db, w.id)
            assert result["checked"] > 0, w.label
            assert result["mismatches"] == [], w.label

    # --- pre-season / season-end -------------------------------------------

    def test_pre_season_ten_weeks_none_locked_with_starter_tokens_and_few_cards(self, db, demo, monkeypatch):
        """pre-season: 10 weeks, none locked, no matches; accounts have starter tokens (INITIAL_TOKENS) and a few cards."""
        from weeks import get_next_editable_week
        monkeypatch.setenv("INITIAL_TOKENS", "7")
        _load(db, "pre-season")
        weeks = _weeks(db)
        assert len(weeks) == 10 and not any(w.is_locked for w in weeks)
        assert db.query(Match).count() == 0 and db.query(WeeklyRosterEntry).count() == 0
        assert get_next_editable_week(db).id == weeks[0].id
        for u in _scenario_users(db):
            assert u.tokens == 7
            assert 1 <= db.query(Card).filter_by(owner_id=u.id).count() <= 5

    def test_season_end_all_weeks_locked_and_no_archive(self, db, demo):
        """season-end: all 10 weeks locked and scored, and season_archive is empty."""
        _load(db, "season-end")
        weeks = _weeks(db)
        assert len(weeks) == 10 and all(w.is_locked for w in weeks)
        assert all(_week_matches(db, w) for w in weeks)
        assert db.query(WeeklySummary).count() == 10
        assert all(w.substitutions_at is not None for w in weeks)
        assert db.query(SeasonArchive).count() == 0
        assert season_reset.end_season_missing(db)

    def test_season_end_then_end_season_succeeds(self, db, demo, monkeypatch):
        """season-end: end_season runs afterwards without 409 and archives the scenario accounts."""
        import team_insights
        from routers.admin_season import SeasonEndBody, end_season
        monkeypatch.setattr(team_insights, "feed_data", lambda db: {})
        _load(db, "season-end")
        caller = _caller(db)
        out = end_season(SeasonEndBody(season_label="Scenario Season"), db=db,
                         admin={"user_id": caller.id, "username": "admin", "is_admin": True})
        assert out["season_label"] == "Scenario Season"
        archived = {r.user_id for r in db.query(SeasonArchive)}
        assert {u.id for u in _scenario_users(db)} <= archived

    # --- Determinism -------------------------------------------------------

    def test_load_mid_season_twice_gives_identical_results(self, db, demo):
        """Loading mid-season twice gives the same season leaderboard, weekly leaderboard for weeks 1-5, each account's My Team week points and the Weekly Report totals."""
        from routers.cards import _build_roster_response
        from routers.leaderboard import compute_season_standings, weekly_leaderboard
        from routers.weekly_summary import _build_week_summary

        def results():
            weeks = _weeks(db)[:5]
            users = _scenario_users(db)
            return {
                "season": sorted((r["username"], r["points"]) for r in compute_season_standings(db)),
                "weekly": [sorted((r["username"], r["week_points"])
                                  for r in weekly_leaderboard(w.id, db=db)) for w in weeks],
                "my_team": [[(u.username, _build_roster_response(db, u.id, w.id)["combined_value"])
                             for u in users] for w in weeks],
                "report": [[(u.username, _build_week_summary(db, w, True, u.id)["roster"]["week_total"])
                            for u in users] for w in weeks],
            }

        _load(db)
        first, first_tables = results(), _game_tables(db)
        assert any(points for _, points in first["season"])
        _load(db)
        assert results() == first
        assert _game_tables(db) == first_tables

    def test_scenario_data_does_not_depend_on_real_time(self, db, demo, monkeypatch):
        """Two loads with time.time patched to different values give identical data; week 1 starts Monday 2026-01-05 00:00 UTC."""
        monkeypatch.setattr(time, "time", lambda: 1_900_000_000.0)
        _load(db)
        first = _game_tables(db)
        monkeypatch.setattr(time, "time", lambda: 1_600_000_000.0)
        _load(db)
        assert _game_tables(db) == first
        assert _weeks(db)[0].start_time == _WEEK1 == scenarios.SCENARIO_START
        assert time.gmtime(_WEEK1)[:6] == (2026, 1, 5, 0, 0, 0) and time.gmtime(_WEEK1).tm_wday == 0

    def test_scenarios_use_distinct_fixed_seeds(self):
        """SCENARIOS defines pre-season, mid-season and season-end, each with its own fixed seed (145_001, 145_002, 145_003)."""
        assert list(scenarios.SCENARIOS) == ["pre-season", "mid-season", "season-end"]
        assert [s["seed"] for s in scenarios.SCENARIOS.values()] == [145_001, 145_002, 145_003]
        assert [s["locked_weeks"] for s in scenarios.SCENARIOS.values()] == [0, 5, 10]

    # --- Pure generator ----------------------------------------------------

    def test_season_generator_same_seed_same_output(self):
        """season_generator.generate with the same seed and arguments returns equal dicts; a different seed returns different data."""
        args = dict(weeks=4, teams=4, players_per_team=5, games_per_team_week=2, users=3,
                    cards_per_user=8, roster_size=5, start=_WEEK1)
        a = season_generator.generate(7, **args)
        assert a == season_generator.generate(7, **args)
        assert a != season_generator.generate(8, **args)
        assert json.loads(json.dumps(a)) == a  # plain data only

    def test_season_generator_has_no_database_or_app_imports(self):
        """season_generator.py imports nothing from database, models, sqlalchemy or routers (only scoring.SCORING_STATS and card_utils._SCORED_STAT_COLS)."""
        tree = ast.parse(_read("backend", "season_generator.py"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
                if node.module in ("scoring", "card_utils"):
                    assert [a.name for a in node.names] in (["SCORING_STATS"], ["_SCORED_STAT_COLS"])
        assert imported <= {"random", "scoring", "card_utils"}, imported
        assert not imported & {"database", "models", "sqlalchemy", "routers", "fastapi"}

    def test_season_generator_output_has_mock_fields(self):
        """Each generated match has radiant_name, dire_name, parse_status, a start_time inside its week and a series grouping within schedule.SERIES_GAP_SECONDS; each stat row has a hero_id."""
        import schedule
        season = season_generator.generate(
            145_002, users=6, start=_WEEK1, **{k: v for k, v in scenarios._SEASON.items() if k != "start"},
            cards_per_user=12)
        weeks = {w["number"]: w for w in season["weeks"]}
        teams = {t["id"]: t["name"] for t in season["teams"]}
        series = {}
        for m in season["matches"]:
            assert m["radiant_name"] == teams[m["radiant_team_id"]]
            assert m["dire_name"] == teams[m["dire_team_id"]]
            assert m["parse_status"] == "parsed"
            w = weeks[m["week"]]
            assert w["start_time"] <= m["start_time"] <= w["end_time"]
            assert all(isinstance(s["hero_id"], int) and 1 <= s["hero_id"] <= 120 for s in m["stats"])
            assert len({s["hero_id"] for s in m["stats"]}) == len(m["stats"])
            series.setdefault(m["series_id"], []).append(m)
        assert len(series) == 10 * 4
        for games in series.values():
            assert len(games) == 2 and len({(g["radiant_team_id"], g["dire_team_id"]) for g in games}) == 1
            times = sorted(g["start_time"] for g in games)
            assert all(0 < b - a < schedule.SERIES_GAP_SECONDS for a, b in zip(times, times[1:]))

    def test_bench_seed_counts_unchanged_after_generator_move(self):
        """scripts/bench_leaderboards.py seed(60, 10, 8, 5, 2, 15, 5, Random(141)) still reports players=40, matches=80, stat_rows=800, cards=900, roster_entries=3000 (subprocess run)."""
        script = ("import json, random, sys\nsys.path.insert(0, 'scripts')\n"
                  "import bench_leaderboards as b\n"
                  "info = b.seed(60, 10, 8, 5, 2, 15, 5, random.Random(141))\n"
                  "print(json.dumps({k: v for k, v in info.items() if k in "
                  + repr(sorted(_BENCH_BASELINE)) + "}))\n")
        env = {**os.environ, "BACKGROUND_TASKS_ENABLED": "false", "DEBUG": "true"}
        env.pop("DATABASE_URL", None)
        proc = subprocess.run([sys.executable, "-c", script], cwd=_ROOT, env=env,
                              capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, proc.stderr[-4000:]
        assert json.loads(proc.stdout.strip().splitlines()[-1]) == _BENCH_BASELINE

    # --- Admin UI ----------------------------------------------------------

    def test_admin_demo_panel_has_scenario_picker_with_in_page_confirmation(self):
        """app-admin-demo.js has a select with the three scenario names, a Load button and an in-page confirmation ("Replaces every account except yours and all game data") before calling adminFetch on /admin/demo/scenario."""
        js = _fe("app-admin-demo.js")
        select_start = js.index('<select id="demoScenarioSelect"')
        select = js[select_start:js.index("</select>", select_start)]
        assert [v for v in re.findall(r'<option value="([a-z-]+)"', select)] == \
            ["pre-season", "mid-season", "season-end"]
        assert 'onclick="askLoadDemoScenario()">Load Scenario…</button>' in js
        confirm_box = js[js.index('id="demoScenarioConfirm"'):]
        assert confirm_box.index("Replaces every account except yours and all game data") < \
            confirm_box.index('onclick="loadDemoScenario()"')
        ask = js[js.index("function askLoadDemoScenario("):js.index("function cancelDemoScenario(")]
        assert "adminFetch" not in ask and '"demoScenarioConfirm").hidden = false' in ask
        start = js.index("async function loadDemoScenario(")
        load = js[start:js.index("\n}\n", start)]
        assert "adminFetch(`${API}/admin/demo/scenario`" in load
        assert "fetch(`${API}/admin/demo/scenario`" not in load.replace("adminFetch(", "")
        # Server text goes in with textContent, never innerHTML.
        assert "innerHTML" not in load and "innerHTML" not in ask
        # Typed confirmation, like the Reset Season dialog (issue #150 policy).
        assert 'demo_scenario:   "LOAD SCENARIO"' in _fe("app-admin.js")
        assert 'id="demoScenarioConfirmInput"' in confirm_box
        assert "ADMIN_CONFIRM_PHRASES.demo_scenario" in ask
        assert load.index("ADMIN_CONFIRM_PHRASES.demo_scenario") < load.index("adminFetch(")
        assert "JSON.stringify({name, confirm: typed})" in load
        # The one-time admin password is shown with textContent, with a shown-once note.
        assert "adminPw.textContent = `scenario-admin password (shown once" in load
        assert "${data.admin_password}" in load

    def test_admin_demo_panel_never_uses_confirm(self):
        """Failure path: app-admin-demo.js never calls window confirm() for the scenario load."""
        js = _fe("app-admin-demo.js")
        assert not re.search(r"(?<![\w.])confirm\s*\(", js)
        assert "window.confirm" not in js


# ===========================================================================
# Story 2: Demo Mode Can Never Reach Production
# ===========================================================================

class TestDemoModeNeverInProduction:

    def test_production_startup_fails_with_demo_mode_true(self, tmp_path):
        """ENV=production with DEMO_MODE=true fails at import with a RuntimeError whose message has [SECURITY] and DEMO_MODE=true (subprocess)."""
        proc = _run_import_main(tmp_path, {"ENV": "production", "DEMO_MODE": "true",
                                           "SECRET_KEY": _LONG_SECRET})
        assert proc.returncode != 0
        assert "RuntimeError" in proc.stderr
        assert "[SECURITY]" in proc.stderr and "DEMO_MODE=true" in proc.stderr

    def test_non_production_demo_mode_true_still_starts(self, tmp_path):
        """With ENV unset and DEMO_MODE=true (the test-server setup) main imports cleanly."""
        proc = _run_import_main(tmp_path, {"DEMO_MODE": "true", "SECRET_KEY": _LONG_SECRET,
                                           "DEMO_ACCOUNT_PASSWORD": _PASSWORD})
        assert proc.returncode == 0, proc.stderr[-4000:]

    def test_every_demo_endpoint_404_when_demo_mode_off_for_admin_and_non_admin(self, db, monkeypatch):
        """With DEMO_MODE unset, every /admin/demo/* route function (clock GET/POST/DELETE, seed-accounts, scenario) raises 404 for both admin and non-admin."""
        monkeypatch.delenv("DEMO_MODE", raising=False)
        monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", _PASSWORD)
        from routers import admin_demo
        from routers.admin_demo import (DemoClockBody, ScenarioBody, SeedDemoAccountsBody,
                                        clear_demo_clock, get_demo_clock, load_demo_scenario,
                                        seed_demo_accounts, set_demo_clock)
        demo_paths = {r.path for r in admin_demo.router.routes if r.path.startswith("/admin/demo/")}
        assert demo_paths == {"/admin/demo/clock", "/admin/demo/seed-accounts", "/admin/demo/scenario"}
        for identity in (_ADMIN, _NON_ADMIN):
            for call in (
                lambda: get_demo_clock(db=db, _=identity),
                lambda: set_demo_clock(DemoClockBody(timestamp=0), db=db, admin=identity),
                lambda: clear_demo_clock(db=db, admin=identity),
                lambda: seed_demo_accounts(SeedDemoAccountsBody(), db=db, admin=identity),
                lambda: load_demo_scenario(ScenarioBody(name="mid-season"), db=db, admin=identity),
            ):
                with pytest.raises(HTTPException) as exc:
                    call()
                assert exc.value.status_code == 404

    def test_unauthenticated_scenario_request_gets_404_when_demo_mode_off(self, monkeypatch):
        """Failure path: a real HTTP POST /admin/demo/scenario with no session gets 404, not 401/403, proving the demo-mode check runs before any admin or re-auth check."""
        import importlib
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        import database
        import enrich
        import ingest
        import main as main_module
        import seed
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("DEMO_MODE", raising=False)
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(database, "engine", engine)
        monkeypatch.setattr(database, "SessionLocal", factory)
        for mod in (enrich, ingest, seed):
            monkeypatch.setattr(mod, "SessionLocal", factory)
        importlib.reload(main_module)
        main_module.engine = engine
        main_module.SessionLocal = factory
        with TestClient(main_module.app, raise_server_exceptions=True) as c:
            assert c.post("/admin/demo/scenario", json={"name": "mid-season"}).status_code == 404
            monkeypatch.setenv("DEMO_MODE", "true")
            assert c.post("/admin/demo/scenario", json={"name": "mid-season"}).status_code in (401, 403)

    def test_demo_mode_docs_list_test_server_setup(self):
        """demo-mode.md documents the test.kana-cards.com setup: DEMO_MODE=true, DEMO_ACCOUNT_PASSWORD set, ENV unset."""
        doc = _read("markdown", "features", "reference", "demo-mode.md")
        section = doc[doc.index("test.kana-cards.com"):]
        section = section[:section.find("\n## ")] if "\n## " in section else section
        for needle in ("DEMO_MODE=true", "DEMO_ACCOUNT_PASSWORD", "ENV"):
            assert needle in section, needle
        assert "unset" in section

    def test_env_example_documents_demo_account_password(self):
        """.env.example documents DEMO_ACCOUNT_PASSWORD with a comment."""
        lines = _read(".env.example").splitlines()
        idx = next(i for i, l in enumerate(lines) if "DEMO_ACCOUNT_PASSWORD" in l)
        assert lines[idx - 1].lstrip().startswith("#") or lines[idx].lstrip().startswith("#")
