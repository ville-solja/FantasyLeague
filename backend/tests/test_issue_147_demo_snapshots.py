"""
Failing test stubs for plan-issue-147-demo-snapshots.md (resolves GitHub issue #147).

On a Demo Mode server an admin can save the live SQLite database under a name
(`POST /admin/demo/snapshots`), list the saved snapshots (`GET /admin/demo/snapshots`)
and restore one into the running app (`POST /admin/demo/snapshots/{name:path}/restore`,
recent re-auth required). One class per acceptance criterion of the single user story,
each with its happy path and primary failure path, plus stubs for the testable
Verification bullets.

Developer notes
---------------

  Modules the plan adds (none exist yet, verified 2026-11-21)
    - `backend/demo_snapshots.py`: `NAME_RE`, `folder()`, `path_for(name)`, `save(name)`,
      `list_all()` -> [{name, size_bytes, saved_at}], `restore(name, keep_user_id)`.
      Import it inside tests (or behind `pytest.importorskip`-free lazy imports) so this
      file keeps collecting before the module exists.
    - `routers/admin_demo.py`: `SnapshotBody(name: str = Field(pattern=...))` and three
      route functions (suggest `list_demo_snapshots`, `save_demo_snapshot`,
      `restore_demo_snapshot`). Each has `Depends(_require_demo_mode)` first AND calls
      `_require_demo_mode()` imperatively (direct-call tests bypass Depends). Restore
      also declares `Depends(require_recent_reauth)` in `dependencies=[...]`.

  A temporary FILE database is required
    The conftest / StaticPool in-memory databases can't be backed up to a file or
    restored from one, so every test that saves or restores needs a real file:

      @pytest.fixture
      def live_db(tmp_path, monkeypatch):
          db_file = tmp_path / "fantasy.db"
          url = f"sqlite:///{db_file.as_posix()}"
          engine = create_engine(url, connect_args={"check_same_thread": False,
                                                    "timeout": 10})
          Base.metadata.create_all(engine)
          Session = sessionmaker(bind=engine)
          monkeypatch.setattr(database, "DATABASE_URL", url)
          monkeypatch.setattr(database, "engine", engine)
          monkeypatch.setattr(database, "SessionLocal", Session)
          # and the names demo_snapshots imported, if it uses `from database import ...`:
          monkeypatch.setattr(demo_snapshots, "engine", engine, raising=False)
          monkeypatch.setattr(demo_snapshots, "SessionLocal", Session, raising=False)
          yield db_file, engine, Session
          engine.dispose()

    `database._sqlite_db_path()` reads `database.DATABASE_URL` at call time, so the
    snapshot folder resolves to `tmp_path / "demo-snapshots"` (next to the live file).
    Never let a test touch the real `data/fantasy.db` or `data/demo-snapshots/`; with
    pytest-xdist (`-n auto`) every path must be under tmp_path. Create the schema with
    `Base.metadata.create_all` and stamp it with `migrate.run_migrations(engine)` so a
    restore's migration step is a no-op for current-schema snapshots.

    Because restore calls `engine.dispose()` and replaces the file underneath, open a
    NEW session (`Session()`) after each restore to read data; don't reuse objects
    loaded before it.

  Fixtures and patterns to reuse
    - Direct calls: test_issue_83_demo_mode.py / test_issue_145_season_scenarios.py:
      `monkeypatch.setenv("DEMO_MODE", "true")` / `delenv`, call the router function
      with `db=session, admin=dict(_ADMIN)`, `pytest.raises(HTTPException)` and check
      `.status_code` (404 / 409 / 422).
    - Name validation over HTTP (422 for `../x`, `a/b`, `..%2Fx`, 41 chars, empty):
      the `{name:path}` route must receive these, so test through a TestClient. Build
      a small app like test_issue_133's `_client(db, login=None, reauth=True)` but
      include `routers.admin_demo.router`, override `get_db` to yield a session on the
      tmp file engine, and log in via `/_test/login/{id}?fresh=true|false`
      (`sessions.start_session` + optional `sessions.mark_reauth`). Note an empty name
      in the URL is `/admin/demo/snapshots//restore`; assert 422 (or document the
      alternative if routing gives 404) and for save POST `{"name": ""}`.
      After each invalid request, assert the set of files under tmp_path is unchanged
      (and nothing appears in tmp_path's parent).
    - Re-auth 403 `reauth_required`: same small app, logged in with `fresh=false`;
      assert `resp.json()["detail"] == "reauth_required"` (check the exact shape in
      test_issue_145 / deps.require_recent_reauth).
    - Session survival / other session 401: two TestClients on the small app, one
      logged in as the restoring admin (fresh) and one as a second user; both sessions
      must live in the tmp file database. After the restore, the admin client's next
      authenticated request (e.g. GET /admin/demo/snapshots) is 200 and the other
      client gets 401 on an authenticated route. Alternatively use the `main`
      TestClient pattern from test_issue_83's `client` fixture, but point
      `database.engine`/`SessionLocal` (and enrich/ingest/seed SessionLocal) at the tmp
      FILE engine instead of :memory:.
    - 404 with DEMO_MODE off: call all three with an admin and DEMO_MODE unset.
    - Caches: fill with test_issue_133's `_fill_caches()` pattern, then assert
      `_caches_empty()` after restore (or monkeypatch `season_reset.bust_caches` with a
      recorder and assert it was called once, after the data swap).
    - Card points: `card_points.rebuild_all` must run; assert stored card points match
      `card_points.check_week(db, week_id)` for a locked week after restore, or patch it
      with a recorder.
    - Older schema: build a snapshot file whose schema lacks a recent migration's
      column (create tables with `Base.metadata.create_all`, then rebuild one table
      without the column via sqlite3, as test_migrate.py does), place it in the snapshot
      folder at mode 0600, restore, and assert the column exists afterwards.
    - Snapshot without caller as admin: produce a snapshot file via `save()` before the
      admin user exists (or flip `is_admin=0` in the snapshot with sqlite3), then
      restore -> 409, and the live file's data (row counts / a sentinel row) unchanged.
    - Audit: `AuditLog` rows with action `demo_snapshot_saved` / `demo_snapshot_restored`
      and the name in the detail; the restored entry must exist AFTER the restore (it
      would be wiped if written before).
    - Frontend checks read `frontend/app-admin-demo.js` as text (see `_fe` in
      test_issue_133); `.gitignore` is read from the repo root.
"""

import os
import sqlite3
import stat
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

import models  # noqa: F401
import card_points
import database
import deps
import migrate
import season_reset
from database import Base, get_db
from models import AuditLog, Card, User, UserSession, Week, WeeklyRosterEntry

_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}
_NON_ADMIN = {"user_id": 2, "username": "u", "is_admin": False}
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_PHRASE = "RESTORE SNAPSHOT"
_SCENARIO_PASSWORD = "scenario-pass-147"
_INVALID = ["../x", "a/b", "..%2Fx", "a" * 41, ""]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def live_db(tmp_path, monkeypatch):
    """A temporary FILE database as the app's live database (tmp_path/data/fantasy.db),
    so snapshots go to tmp_path/data/demo-snapshots."""
    data = tmp_path / "data"
    data.mkdir()
    db_file = data / "fantasy.db"
    url = f"sqlite:///{db_file.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    migrate.run_migrations(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "DATABASE_URL", url)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    yield db_file, engine, Session
    engine.dispose()


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", _SCENARIO_PASSWORD)
    monkeypatch.delenv("SUBSTITUTION_DELAY_HOURS", raising=False)
    monkeypatch.delenv("INITIAL_TOKENS", raising=False)


@pytest.fixture(autouse=True)
def _clean_caches():
    season_reset.bust_caches()
    yield
    season_reset.bust_caches()


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _fe(name):
    return _read("frontend", name)


def _fn_source(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start) + 2]


def _user(Session, username, admin=False, tokens=10):
    from auth import hash_password
    with Session() as s:
        u = User(username=username, email=f"{username}@example.com",
                 password_hash=hash_password("secret123"), is_admin=admin, tokens=tokens,
                 created_at=int(time.time()))
        s.add(u)
        s.commit()
        return u.id


def _admin_dict(user_id):
    return {"user_id": user_id, "username": "admin", "is_admin": True}


def _save(Session, name, admin_id):
    from routers.admin_demo import SnapshotBody, save_demo_snapshot
    with Session() as s:
        return save_demo_snapshot(SnapshotBody(name=name), db=s, admin=_admin_dict(admin_id))


def _restore(Session, name, admin_id):
    from routers.admin_demo import restore_demo_snapshot
    with Session() as s:
        return restore_demo_snapshot(name=name, db=s, admin=_admin_dict(admin_id))


def _snap_folder(db_file):
    return db_file.parent / "demo-snapshots"


def _files(root):
    """Every file under root, without SQLite's -wal/-shm/-journal side files."""
    return {str(p.relative_to(root)) for p in root.rglob("*")
            if p.is_file() and not p.name.endswith(("-wal", "-shm", "-journal"))}


def _sentinel(Session):
    with Session() as s:
        return sorted((u.id, u.username, u.tokens, bool(u.is_admin)) for u in s.query(User))


def _client(Session, login=None, reauth=True):
    """A small app around admin_demo on the tmp file database, signed in as user id `login`."""
    import rate_limit
    import sessions
    from deps import get_current_user
    from routers import admin_demo
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-147")
    app.state.limiter = rate_limit.limiter
    app.include_router(admin_demo.router)

    def _get_db():
        s = database.SessionLocal()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = _get_db

    @app.post("/_test/login/{user_id}")
    def _login(user_id: int, request: Request, fresh: bool = True):
        with database.SessionLocal() as s:
            sessions.start_session(request, s, s.get(User, user_id))
            if fresh:
                sessions.mark_reauth(sessions.current_row(request, s))
            s.commit()
        return {"ok": True}

    @app.get("/_test/me")
    def _me(user: dict = Depends(get_current_user)):
        return user

    client = TestClient(app)
    if login is not None:
        assert client.post(f"/_test/login/{login}", params={"fresh": reauth}).status_code == 200
    return client


def _restore_url(name):
    # The HTTP client removes "." / ".." segments (as browsers do), so a literal
    # "../x" is sent with its slash encoded; the server decodes it back to "../x".
    if name.startswith("../"):
        name = name.replace("/", "%2F")
    return f"/admin/demo/snapshots/{name}/restore"


def _load_scenario(Session, admin_id):
    import scenarios
    with Session() as s:
        scenarios.load(s, "mid-season", admin_id)


def _standings(Session):
    from routers.leaderboard import compute_season_standings
    with Session() as s:
        return sorted((r["id"], r["points"]) for r in compute_season_standings(s))


def _fill_caches():
    import finals
    import player_insights
    import schedule
    import team_insights
    import twitch
    schedule._cache.update(data={"weeks": [], "extra_results": []}, fetched_at=datetime.now())
    schedule._game_players_cache[1001] = (time.monotonic(), {"match_id": 1001})
    twitch._panel_cache.update(at=time.monotonic(), body={"old": True})
    finals._public_cache.update(at=time.monotonic(), entry={"old": True})
    finals._available_cache.update(at=time.monotonic(), value=True)
    finals._site_cache.update(at=time.monotonic(), value={"old": True}, filled=True)
    team_insights._league_cache.update(key="k", at=time.monotonic(), value={"old": True})
    team_insights._list_cache.update(key="k", at=time.monotonic(), value=[1])
    player_insights._league_cache.update(key="k", at=time.monotonic(), value={"old": True})


def _caches_empty():
    import finals
    import player_insights
    import schedule
    import team_insights
    import twitch
    return (schedule._cache["data"] is None and schedule._game_players_cache == {}
            and twitch._panel_cache["body"] is None and finals._public_cache["entry"] is None
            and finals._available_cache["value"] is None and finals._site_cache["value"] is None
            and team_insights._league_cache["value"] is None
            and team_insights._list_cache["value"] is None
            and player_insights._league_cache["value"] is None)


# ===========================================================================
# Story: Save and Restore a Test Snapshot
# ===========================================================================

# --- AC1: save to data/demo-snapshots/{name}.db with the online backup; 409 on an existing name

class TestSaveSnapshot:

    def test_save_snapshot_writes_backup_file_in_snapshot_folder(self, live_db, demo):
        """POST /admin/demo/snapshots {"name"} saves a copy of the live database to demo-snapshots/{name}.db."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        client = _client(Session, login=admin_id, reauth=False)
        resp = client.post("/admin/demo/snapshots", json={"name": "mid-week-3"})
        assert resp.status_code == 200, resp.text
        path = _snap_folder(db_file) / "mid-week-3.db"
        assert path.is_file()
        body = resp.json()
        assert body["name"] == "mid-week-3"
        assert body["size_bytes"] == path.stat().st_size > 0
        assert isinstance(body["saved_at"], int)
        assert str(db_file.parent) not in resp.text  # no filesystem path in the response

    def test_save_snapshot_file_is_a_valid_copy_of_live_data(self, live_db, demo):
        """The saved file opens as SQLite and holds the live rows (online backup, not a partial copy)."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _user(Session, "alice", tokens=7)
        _save(Session, "copy", admin_id)
        conn = sqlite3.connect(_snap_folder(db_file) / "copy.db")
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            rows = sorted(conn.execute("SELECT id, username, tokens, is_admin FROM users").fetchall())
            migrations = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        finally:
            conn.close()
        assert [(i, n, t, bool(a)) for i, n, t, a in rows] == _sentinel(Session)
        assert migrations == len(migrate.MIGRATIONS)

    def test_save_snapshot_existing_name_returns_409(self, live_db, demo):
        """Saving over an existing snapshot name gives 409 and leaves the existing file unchanged."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "dup", admin_id)
        path = _snap_folder(db_file) / "dup.db"
        before = path.read_bytes()
        _user(Session, "later")
        with pytest.raises(HTTPException) as exc:
            _save(Session, "dup", admin_id)
        assert exc.value.status_code == 409
        assert path.read_bytes() == before

    def test_save_snapshot_writes_demo_snapshot_saved_audit_entry(self, live_db, demo):
        """Save writes a demo_snapshot_saved audit entry naming the snapshot."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "audited", admin_id)
        with Session() as s:
            rows = s.query(AuditLog).filter_by(action="demo_snapshot_saved").all()
            assert [(r.actor_id, r.detail) for r in rows] == [(admin_id, "name=audited")]

    def test_save_snapshot_file_and_folder_modes(self, live_db, demo):
        """Snapshot files are 0600 and the demo-snapshots folder is 0700."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "modes", admin_id)
        folder = _snap_folder(db_file)
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        assert stat.S_IMODE((folder / "modes.db").stat().st_mode) == 0o600


# --- AC2: list with name, size, time; newest first

class TestListSnapshots:

    def test_list_snapshots_returns_name_size_and_time_newest_first(self, live_db, demo):
        """GET /admin/demo/snapshots lists name, size_bytes and saved_at, newest first."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        for name in ("first", "second", "third"):
            _save(Session, name, admin_id)
        folder = _snap_folder(db_file)
        os.utime(folder / "first.db", (1_700_000_000, 1_700_000_000))
        os.utime(folder / "second.db", (1_700_000_300, 1_700_000_300))
        os.utime(folder / "third.db", (1_700_000_100, 1_700_000_100))
        client = _client(Session, login=admin_id, reauth=False)
        resp = client.get("/admin/demo/snapshots")
        assert resp.status_code == 200
        snaps = resp.json()["snapshots"]
        assert [s["name"] for s in snaps] == ["second", "third", "first"]
        assert [s["saved_at"] for s in snaps] == [1_700_000_300, 1_700_000_100, 1_700_000_000]
        for s in snaps:
            assert set(s) == {"name", "size_bytes", "saved_at"}
            assert s["size_bytes"] == (folder / f"{s['name']}.db").stat().st_size

    def test_list_snapshots_empty_when_folder_missing(self, live_db, demo, tmp_path):
        """With no snapshot folder yet, the list is empty (no error, no folder outside tmp)."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        before = _files(tmp_path)
        from routers.admin_demo import list_demo_snapshots
        assert list_demo_snapshots(_=_admin_dict(admin_id)) == {"snapshots": []}
        assert not _snap_folder(db_file).exists()
        assert _files(tmp_path) == before


# --- AC3: restore into the live database while running; rebuild card points; empty caches

class TestRestoreSnapshot:

    def test_restore_snapshot_round_trips_leaderboard_cards_and_tokens(self, live_db, demo):
        """Save, change data (draw a card, edit a roster, spend tokens), restore: season leaderboard, the user's cards and tokens equal the saved values."""
        from database import credit_tokens
        from routers.cards import draw_card
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _load_scenario(Session, admin_id)
        with Session() as s:
            user = s.query(User).filter_by(username="scenario1").one()
            uid = user.id
            cards_before = sorted((c.id, c.player_id, c.card_type, bool(c.is_active))
                                  for c in s.query(Card).filter_by(owner_id=uid))
            tokens_before = user.tokens
        standings_before = _standings(Session)
        assert any(points for _, points in standings_before)
        _save(Session, "before-change", admin_id)

        with Session() as s:
            credit_tokens(s, uid, 2)
            s.commit()
            draw_card(db=s, current_user={"user_id": uid, "username": "scenario1", "is_admin": False})
            locked = s.query(Week).filter_by(is_locked=True).order_by(Week.start_time).first()
            s.query(WeeklyRosterEntry).filter_by(user_id=uid, week_id=locked.id).delete()
            s.execute(text("UPDATE users SET tokens = 0 WHERE id = :u"), {"u": uid})
            s.commit()
        assert _standings(Session) != standings_before

        _restore(Session, "before-change", admin_id)

        with Session() as s:
            assert sorted((c.id, c.player_id, c.card_type, bool(c.is_active))
                          for c in s.query(Card).filter_by(owner_id=uid)) == cards_before
            assert s.get(User, uid).tokens == tokens_before
        assert _standings(Session) == standings_before

    def test_restore_snapshot_rebuilds_stored_card_points(self, live_db, demo):
        """After restore, card_points.rebuild_all has run and stored card points match check_week."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _load_scenario(Session, admin_id)
        _save(Session, "points", admin_id)
        conn = sqlite3.connect(_snap_folder(db_file) / "points.db")
        conn.execute("DELETE FROM card_match_points")
        conn.commit()
        conn.close()

        _restore(Session, "points", admin_id)

        with Session() as s:
            from models import CardMatchPoints
            assert s.query(CardMatchPoints).count() > 0
            locked = s.query(Week).filter_by(is_locked=True).all()
            assert locked
            for week in locked:
                result = card_points.check_week(s, week.id)
                assert result["mismatches"] == [], week.label
            assert any(card_points.check_week(s, w.id)["checked"] for w in locked)

    def test_restore_snapshot_busts_caches(self, live_db, demo):
        """After restore, season_reset.bust_caches() has emptied the in-memory caches."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "caches", admin_id)
        _fill_caches()
        assert not _caches_empty()
        _restore(Session, "caches", admin_id)
        assert _caches_empty()

    def test_restore_snapshot_missing_name_returns_404(self, live_db, demo, tmp_path):
        """Restoring a valid name with no snapshot file gives 404 and changes nothing."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        before, files = _sentinel(Session), _files(tmp_path)
        with pytest.raises(HTTPException) as exc:
            _restore(Session, "nothing-here", admin_id)
        assert exc.value.status_code == 404
        assert _sentinel(Session) == before
        assert _files(tmp_path) == files

    def test_restore_snapshot_migrates_older_schema(self, live_db, demo):
        """A snapshot from an older schema is brought up to date by run_migrations on restore."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "old-schema", admin_id)
        conn = sqlite3.connect(_snap_folder(db_file) / "old-schema.db")
        conn.execute("ALTER TABLE player_match_stats DROP COLUMN courier_kills")
        conn.execute("DELETE FROM schema_migrations WHERE id = '047_pms_courier_kills'")
        conn.commit()
        conn.close()

        _restore(Session, "old-schema", admin_id)

        conn = sqlite3.connect(db_file)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(player_match_stats)")}
            applied = conn.execute("SELECT COUNT(*) FROM schema_migrations "
                                   "WHERE id = '047_pms_courier_kills'").fetchone()[0]
        finally:
            conn.close()
        assert "courier_kills" in cols
        assert applied == 1

    def test_restore_snapshot_writes_restored_audit_entry_after_restore(self, live_db, demo):
        """demo_snapshot_restored is in audit_logs after the restore (written after the data swap, so it survives), with the pre-restore time as replaced_state_at."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "audit", admin_id)
        conn = sqlite3.connect(_snap_folder(db_file) / "audit.db")
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = "
                            "'demo_snapshot_restored'").fetchone()[0] == 0
        conn.close()
        t0 = int(time.time())
        _restore(Session, "audit", admin_id)
        with Session() as s:
            rows = s.query(AuditLog).filter_by(action="demo_snapshot_restored").all()
            assert [r.actor_id for r in rows] == [admin_id]
            name_part, ts_part = rows[0].detail.split(" ")
            assert name_part == "name=audit"
            key, ts = ts_part.split("=")
            assert key == "replaced_state_at" and t0 <= int(ts) <= int(time.time())
            # The snapshot predates its own save entry, so the restore replaced it.
            assert s.query(AuditLog).filter_by(action="demo_snapshot_saved").count() == 0


# --- AC4: admin and DEMO_MODE only (404 otherwise); restore needs re-auth (403 reauth_required)

class TestDemoModeAndAuth:

    def test_snapshot_endpoints_require_demo_mode_and_admin(self):
        """All three routes declare _require_demo_mode first and require_admin; restore declares require_recent_reauth."""
        import inspect
        from routers import admin_demo
        from routers.admin_demo import (_require_demo_mode, list_demo_snapshots,
                                        restore_demo_snapshot, save_demo_snapshot)
        routes = {(r.path, tuple(sorted(r.methods))): r for r in admin_demo.router.routes}
        expected = {
            ("/admin/demo/snapshots", ("GET",)): list_demo_snapshots,
            ("/admin/demo/snapshots", ("POST",)): save_demo_snapshot,
            ("/admin/demo/snapshots/{name:path}/restore", ("POST",)): restore_demo_snapshot,
        }
        for key, fn in expected.items():
            route = routes[key]
            assert route.endpoint is fn
            calls = [d.call for d in route.dependant.dependencies]
            assert calls[0] is _require_demo_mode, key
            flat = []

            def _walk(dep):
                for d in dep.dependencies:
                    flat.append(d.call)
                    _walk(d)
            _walk(route.dependant)
            assert deps.require_admin in flat, key
            assert "_require_demo_mode()" in inspect.getsource(fn)
        restore_calls = [d.call for d in routes[("/admin/demo/snapshots/{name:path}/restore",
                                                 ("POST",))].dependant.dependencies]
        assert deps.require_recent_reauth in restore_calls
        assert restore_calls.index(deps.require_recent_reauth) == 1
        assert deps.CONFIRM_PHRASES["demo_snapshot_restore"] == _PHRASE

    def test_snapshot_endpoints_return_404_when_demo_mode_off_even_for_admin(self, live_db, monkeypatch, tmp_path):
        """With DEMO_MODE off, list, save and restore all give 404 for an admin."""
        from routers.admin_demo import (SnapshotBody, list_demo_snapshots,
                                        restore_demo_snapshot, save_demo_snapshot)
        _, _, Session = live_db
        monkeypatch.delenv("DEMO_MODE", raising=False)
        admin_id = _user(Session, "admin", admin=True)
        files = _files(tmp_path)
        with Session() as s:
            for call in (lambda: list_demo_snapshots(_=_admin_dict(admin_id)),
                         lambda: save_demo_snapshot(SnapshotBody(name="x"), db=s, admin=_admin_dict(admin_id)),
                         lambda: restore_demo_snapshot(name="x", db=s, admin=_admin_dict(admin_id))):
                with pytest.raises(HTTPException) as exc:
                    call()
                assert exc.value.status_code == 404
        client = _client(Session, login=admin_id)
        assert client.get("/admin/demo/snapshots").status_code == 404
        assert client.post("/admin/demo/snapshots", json={"name": "x"}).status_code == 404
        assert client.post(_restore_url("x"), json={"confirm": _PHRASE}).status_code == 404
        assert _files(tmp_path) == files

    def test_snapshot_endpoints_non_admin_rejected(self, live_db, demo, tmp_path):
        """A non-admin on a Demo Mode server can't list, save or restore (403)."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "exists", admin_id)
        user_id = _user(Session, "player")
        files, before = _files(tmp_path), _sentinel(Session)
        client = _client(Session, login=user_id)
        assert client.get("/admin/demo/snapshots").status_code == 403
        assert client.post("/admin/demo/snapshots", json={"name": "mine"}).status_code == 403
        assert client.post(_restore_url("exists"), json={"confirm": _PHRASE}).status_code == 403
        assert _files(tmp_path) == files
        assert _sentinel(Session) == before

    def test_restore_snapshot_without_recent_reauth_returns_403_reauth_required(self, live_db, demo):
        """Restore without a recent password re-entry gives 403 reauth_required and restores nothing."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "early", admin_id)
        _user(Session, "added-later")
        before = _sentinel(Session)
        client = _client(Session, login=admin_id, reauth=False)
        resp = client.post(_restore_url("early"), json={"confirm": _PHRASE})
        assert resp.status_code == 403
        assert resp.json() == {"detail": "reauth_required"}
        assert _sentinel(Session) == before

    @pytest.mark.parametrize("confirm", [None, "", "yes", "RESTORE", "LOAD SCENARIO"])
    def test_restore_snapshot_without_typed_confirmation_returns_400(self, live_db, demo, confirm):
        """Security: restore also needs the typed phrase RESTORE SNAPSHOT (after a recent re-auth); otherwise 400 confirmation_required and nothing is restored."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "early", admin_id)
        _user(Session, "added-later")
        before = _sentinel(Session)
        client = _client(Session, login=admin_id)
        body = {} if confirm is None else {"confirm": confirm}
        resp = client.post(_restore_url("early"), json=body)
        assert resp.status_code == 400
        assert resp.json() == {"detail": "confirmation_required"}
        assert _sentinel(Session) == before
        ok = client.post(_restore_url("early"), json={"confirm": " restore snapshot "})
        assert ok.status_code == 200, ok.text
        assert "added-later" not in [u[1] for u in _sentinel(Session)]

    def test_save_and_list_snapshot_do_not_need_reauth(self, live_db, demo):
        """Save and list work for an admin session without a recent re-auth."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        client = _client(Session, login=admin_id, reauth=False)
        assert client.post("/admin/demo/snapshots", json={"name": "quick"}).status_code == 200
        resp = client.get("/admin/demo/snapshots")
        assert resp.status_code == 200
        assert [s["name"] for s in resp.json()["snapshots"]] == ["quick"]


# --- AC5: names never become paths outside the folder; invalid names get 422

class TestNameValidation:

    def test_path_for_accepts_valid_names_inside_folder(self, live_db):
        """path_for('mid-week-3') resolves to demo-snapshots/mid-week-3.db inside the folder."""
        import demo_snapshots
        db_file, _, _ = live_db
        folder = _snap_folder(db_file).resolve()
        assert demo_snapshots.folder().resolve() == folder
        for name in ("mid-week-3", "A", "a" * 40, "Season-17-pre"):
            p = demo_snapshots.path_for(name)
            assert p == folder / f"{name}.db"
            assert p.parent == folder

    def test_path_for_rejects_invalid_names(self, live_db):
        """path_for raises ValueError for ../x, a/b, ..%2Fx, a 41-character name and an empty name."""
        import demo_snapshots
        for name in _INVALID + ["a.b", "a b", "a\n", "..", "/etc/passwd", "a\\b", None]:
            with pytest.raises(ValueError):
                demo_snapshots.path_for(name)

    @pytest.mark.parametrize("name", ["../x", "a/b", "..%2Fx", "a" * 41, ""])
    def test_save_snapshot_invalid_name_returns_422_and_touches_no_file(self, name, live_db, demo, tmp_path):
        """POST /admin/demo/snapshots with an invalid name gives 422 and creates no file anywhere."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        client = _client(Session, login=admin_id)
        files = _files(tmp_path)
        resp = client.post("/admin/demo/snapshots", json={"name": name})
        assert resp.status_code == 422
        assert _files(tmp_path) == files

    @pytest.mark.parametrize("name", ["../x", "a/b", "..%2Fx", "a" * 41, ""])
    def test_restore_snapshot_invalid_name_returns_422_and_touches_no_file(self, name, live_db, demo, tmp_path):
        """POST /admin/demo/snapshots/{name:path}/restore with an invalid name gives 422 (not 404) and reads/writes no file outside the folder."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "decoy", admin_id)
        # A valid database where "../x" and "a/b" would land if names became paths.
        folder = _snap_folder(db_file)
        for target in (db_file.parent / "x.db", folder / "a" / "b.db"):
            target.parent.mkdir(exist_ok=True)
            target.write_bytes((folder / "decoy.db").read_bytes())
        _user(Session, "added-later")
        before, files = _sentinel(Session), _files(tmp_path)
        client = _client(Session, login=admin_id)
        resp = client.post(_restore_url(name), json={"confirm": _PHRASE})
        assert resp.status_code == 422, (resp.status_code, resp.text)
        assert _sentinel(Session) == before
        assert _files(tmp_path) == files


# --- AC6: restoring admin stays logged in; every other session ends; 409 without that admin

class TestSessionsOnRestore:

    def test_restore_snapshot_keeps_caller_session_and_ends_others(self, live_db, demo):
        """After restore the caller's session still works and another user's session gets 401."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        other_id = _user(Session, "other")
        admin_client = _client(Session, login=admin_id)
        other_client = _client(Session, login=other_id)
        assert other_client.get("/_test/me").status_code == 200
        # The snapshot holds both sessions; restoring it must still end the other one.
        assert admin_client.post("/admin/demo/snapshots", json={"name": "sessions"}).status_code == 200
        resp = admin_client.post(_restore_url("sessions"), json={"confirm": _PHRASE})
        assert resp.status_code == 200, resp.text
        assert resp.json()["restored"] == "sessions"
        assert admin_client.get("/admin/demo/snapshots").status_code == 200
        assert admin_client.get("/_test/me").json()["user_id"] == admin_id
        assert other_client.get("/_test/me").status_code == 401
        with Session() as s:
            assert {r.user_id for r in s.query(UserSession)} == {admin_id}

    def test_restore_snapshot_without_caller_as_admin_returns_409_and_keeps_live_data(self, live_db, demo, tmp_path):
        """A snapshot whose users lack the caller as admin gives 409 and the live data is unchanged."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "demoted", admin_id)
        conn = sqlite3.connect(_snap_folder(db_file) / "demoted.db")
        conn.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (admin_id,))
        conn.commit()
        conn.close()
        _save(Session, "no-such-user", admin_id)
        conn = sqlite3.connect(_snap_folder(db_file) / "no-such-user.db")
        conn.execute("DELETE FROM user_sessions")
        conn.execute("DELETE FROM users WHERE id = ?", (admin_id,))
        conn.commit()
        conn.close()
        _user(Session, "added-later")
        client = _client(Session, login=admin_id)
        before, files = _sentinel(Session), _files(tmp_path)
        for name in ("demoted", "no-such-user"):
            resp = client.post(_restore_url(name), json={"confirm": _PHRASE})
            assert resp.status_code == 409, resp.text
            assert str(tmp_path) not in resp.text
        assert _sentinel(Session) == before
        assert _files(tmp_path) == files
        assert client.get("/_test/me").json()["user_id"] == admin_id


class TestRestoreFailureAndLogging:
    """Security review (Low): sessions are rewritten right after the swap, a failure
    after the swap ends every session, and the swap is logged before it happens."""

    def test_sessions_rewritten_before_migrations_run(self, live_db, demo, monkeypatch):
        """When the migrations run, the restored file already holds only the caller's sessions."""
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        other_id = _user(Session, "other")
        admin_client = _client(Session, login=admin_id)
        _client(Session, login=other_id)
        assert admin_client.post("/admin/demo/snapshots", json={"name": "s"}).status_code == 200
        seen = []
        real = migrate.run_migrations

        def _spy(engine):
            conn = sqlite3.connect(db_file)
            seen.append({r[0] for r in conn.execute("SELECT user_id FROM user_sessions")})
            conn.close()
            real(engine)
        monkeypatch.setattr(migrate, "run_migrations", _spy)
        assert admin_client.post(_restore_url("s"), json={"confirm": _PHRASE}).status_code == 200
        assert seen == [{admin_id}]

    def test_failure_after_swap_ends_every_session(self, live_db, demo, monkeypatch, tmp_path):
        """If the migrations fail after the swap, every session ends (no snapshot session stays valid) and the response names only the exception type."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        other_id = _user(Session, "other")
        admin_client = _client(Session, login=admin_id)
        other_client = _client(Session, login=other_id)
        assert admin_client.post("/admin/demo/snapshots", json={"name": "s"}).status_code == 200

        def _boom(engine):
            raise RuntimeError(f"disk trouble at {tmp_path}")
        monkeypatch.setattr(migrate, "run_migrations", _boom)
        resp = admin_client.post(_restore_url("s"), json={"confirm": _PHRASE})
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Restoring the snapshot failed (RuntimeError)"}
        with Session() as s:
            assert s.query(UserSession).count() == 0
        assert other_client.get("/_test/me").status_code == 401
        assert admin_client.get("/_test/me").status_code == 401

    def test_session_rewrite_failure_right_after_swap_ends_every_session(self, live_db, demo, monkeypatch):
        """If rewriting the sessions on the raw connection fails just after the swap, every session still ends."""
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        other_id = _user(Session, "other")
        admin_client = _client(Session, login=admin_id)
        other_client = _client(Session, login=other_id)
        assert admin_client.post("/admin/demo/snapshots", json={"name": "s"}).status_code == 200

        import demo_snapshots

        def _boom(conn, kept):
            raise sqlite3.OperationalError("boom")
        monkeypatch.setattr(demo_snapshots, "_rewrite_sessions", _boom)
        resp = admin_client.post(_restore_url("s"), json={"confirm": _PHRASE})
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Restoring the snapshot failed (OperationalError)"}
        with Session() as s:
            assert s.query(UserSession).count() == 0
        assert other_client.get("/_test/me").status_code == 401
        assert admin_client.get("/_test/me").status_code == 401

    def test_restore_logs_a_warning_before_the_swap(self, live_db, demo, caplog):
        """A WARNING names the snapshot and the actor before the data is replaced."""
        import logging
        _, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        _save(Session, "logged", admin_id)
        with caplog.at_level(logging.WARNING, logger="demo_snapshots"):
            _restore(Session, "logged", admin_id)
        warnings = [r.getMessage() for r in caplog.records
                    if r.name == "demo_snapshots" and r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "logged" in warnings[0] and "admin" in warnings[0]


class TestSymlinks:
    """Security review (Low): a symlink in the snapshot folder never stands in for a name."""

    def _alias(self, db_file, Session, admin_id):
        _save(Session, "real", admin_id)
        folder = _snap_folder(db_file)
        os.symlink(folder / "real.db", folder / "alias.db")
        return folder

    def test_path_for_rejects_symlinked_name(self, live_db, demo):
        import demo_snapshots
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        self._alias(db_file, Session, admin_id)
        with pytest.raises(ValueError):
            demo_snapshots.path_for("alias")
        assert demo_snapshots.path_for("real").name == "real.db"

    def test_restore_and_save_through_symlink_get_422(self, live_db, demo, tmp_path):
        db_file, _, Session = live_db
        admin_id = _user(Session, "admin", admin=True)
        folder = self._alias(db_file, Session, admin_id)
        _user(Session, "added-later")
        before = _sentinel(Session)
        real_bytes = (folder / "real.db").read_bytes()
        client = _client(Session, login=admin_id)
        assert client.post(_restore_url("alias"), json={"confirm": _PHRASE}).status_code == 422
        assert client.post("/admin/demo/snapshots", json={"name": "alias"}).status_code == 422
        assert _sentinel(Session) == before
        assert (folder / "real.db").read_bytes() == real_bytes
        names = [s["name"] for s in client.get("/admin/demo/snapshots").json()["snapshots"]]
        assert names == ["real"]


# --- AC7: Demo panel lists snapshots with Save and Restore; in-page confirmation, never confirm()

class TestDemoPanelUi:

    def test_demo_panel_has_snapshot_list_save_and_restore(self):
        """app-admin-demo.js renders a Snapshots list with a name input, Save and Restore buttons, calling the three endpoints."""
        js = _fe("app-admin-demo.js")
        panel = _fn_source(js, "renderDemoModePanel")
        assert "Snapshots" in panel
        assert 'id="demoSnapshotName"' in panel
        assert 'onclick="saveDemoSnapshot()"' in panel
        assert 'id="demoSnapshotsBody"' in panel
        assert "loadDemoSnapshots()" in panel
        load = _fn_source(js, "loadDemoSnapshots")
        assert "/admin/demo/snapshots`" in load
        assert "textContent" in load and "innerHTML" not in load.replace("tbody.innerHTML = \"\"", "")
        assert "Restore" in load
        save = _fn_source(js, "saveDemoSnapshot")
        assert "/admin/demo/snapshots`" in save and 'method: "POST"' in save
        restore = _fn_source(js, "restoreDemoSnapshot")
        assert "/restore`" in restore and "encodeURIComponent(" in restore
        assert "adminFetch(" in restore
        assert "location.reload()" in restore

    def test_demo_panel_restore_uses_in_page_confirmation_not_confirm(self):
        """Restore shows an in-page confirmation ('everyone else is logged out') and the file never calls confirm()."""
        import re
        js = _fe("app-admin-demo.js")
        assert not re.search(r"(?<![\w.])confirm\(", js)
        assert "window.confirm" not in js
        panel = _fn_source(js, "renderDemoModePanel")
        assert 'id="demoSnapshotConfirm" hidden' in panel
        assert "everyone else is logged out" in panel
        assert 'id="demoSnapshotConfirmInput"' in panel
        ask = _fn_source(js, "askRestoreDemoSnapshot")
        assert "ADMIN_CONFIRM_PHRASES.demo_snapshot_restore" in ask
        assert "textContent = name" in ask
        restore = _fn_source(js, "restoreDemoSnapshot")
        assert restore.index("ADMIN_CONFIRM_PHRASES.demo_snapshot_restore") < restore.index("adminFetch(")
        assert "confirm: typed" in restore
        assert 'demo_snapshot_restore: "RESTORE SNAPSHOT"' in _fe("app-admin.js")


# --- Repository hygiene

class TestRepoHygiene:

    def test_gitignore_covers_demo_snapshots_folder(self):
        """.gitignore ignores data/demo-snapshots/ (snapshots hold password hashes and emails)."""
        lines = [l.strip() for l in _read(".gitignore").splitlines()]
        assert "data/demo-snapshots/" in lines
        assert "data/" in _read(".dockerignore").split()
