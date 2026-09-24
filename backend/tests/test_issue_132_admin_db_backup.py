"""
Tests for plan-issue-132-admin-db-backup.

Covers three user stories from markdown/plans/plan-issue-132-admin-db-backup.md:

  Story: Create a Backup On Demand
    - Settings tab has a "Database Backups" panel with a "Create backup now" button (static HTML check)
    - POST /admin/backups uses backup_sqlite_db() and returns filename, size_bytes, created_at
    - New file follows `{db}.backup-YYYYMMDD-HHmmss` next to the live DB
    - Audit log entry `admin_db_backup` with the filename
    - Request within 60s of newest backup returns 429 and creates no file
    - Non-SQLite DATABASE_URL returns 409 and creates no file
    - Non-admin gets 403; logged-out gets 401

  Story: See Which Backups Exist
    - GET /admin/backups returns every `{db}.backup-*` file, newest first, with
      filename, size_bytes, created_at, plus retention_days
    - Never includes the live DB or its -wal/-shm files
    - Empty directory returns an empty list
    - Non-admin gets 403

  Story: Download a Backup
    - GET /admin/backups/{filename} returns the file as an attachment with
      Content-Disposition set to the backup filename
    - Filenames not in the listing (`../fantasy.db`, the live DB name, unknown names) return 404
    - Audit log entry `admin_db_backup_download` with the filename
    - Non-admin gets 403; logged-out gets 401

IMPORTANT — isolation from the real data/ directory:
  These tests must NEVER write backup files into the real `data/` directory.
  Every test that creates or lists backups must point the live DB at a
  temporary SQLite file under pytest's `tmp_path`, e.g.:

      db_file = tmp_path / "fantasy.db"
      sqlite3.connect(db_file).close()
      monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{db_file}")

  (and, if the router module imports DATABASE_URL / helpers by name, patch the
  attribute on `routers.admin_backups` as well). Use the `db_file_env` fixture
  below once implemented. Audit-log assertions use the conftest in-memory `db`
  fixture, which is separate from the file whose backup is taken.

Conventions (copied from test_issue_81_season_lifecycle.py):
  - Call router functions directly with `db=db, admin=_ADMIN`.
  - 403: `require_admin({"user_id": 2, "username": "u", "is_admin": False}, db=db)`
    raises HTTPException(403) (see test_require_admin_session_freshness.py).
  - 401: `deps.get_current_user` (or equivalent) with no session raises HTTPException(401).
  - Also assert the route is declared with Depends(require_admin) by inspecting
    the router's route dependencies, so the guard can't be dropped silently.

Manual verification (not automated):
  - Create backup button is disabled while its request is in flight and shows
    the new filename or error in the panel status line.
  - Backup table renders Filename / Created (local time) / human-readable Size,
    with a Download link per row and a Refresh button.
  - Panel shows retention text "deleted automatically after N days".
  - Empty list renders "No backups yet".
  - List loads when the Settings tab opens.
  - Downloaded backup passes `PRAGMA integrity_check`.
"""

import os
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.requests import Request

import database
from deps import get_current_user, require_admin
from models import AuditLog, User
from routers import admin_backups

_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}
_NON_ADMIN = {"user_id": 2, "username": "u", "is_admin": False}
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_INDEX_HTML_PATH = _FRONTEND_DIR / "index.html"
_BACKUP_NAME_RE = re.compile(r"^fantasy\.db\.backup-\d{8}-\d{6}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _logged_out_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/admin/backups",
                    "headers": [], "session": {}})


def _make_backup(db_file: Path, suffix: str, age_seconds: float, content: bytes = b"x") -> Path:
    path = db_file.parent / f"{db_file.name}.backup-{suffix}"
    path.write_bytes(content)
    ts = time.time() - age_seconds
    os.utime(path, (ts, ts))
    return path


def _assert_route_guarded(path: str, method: str):
    for route in admin_backups.router.routes:
        if route.path == path and method in route.methods:
            calls = [d.call for d in route.dependant.dependencies]
            assert require_admin in calls
            return
    pytest.fail(f"route {method} {path} not found")


def _assert_non_admin_forbidden(db):
    db.add(User(id=2, username="u", password_hash="x", is_admin=False))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        require_admin(_NON_ADMIN, db=db)
    assert exc.value.status_code == 403


def _assert_logged_out_unauthorized():
    with pytest.raises(HTTPException) as exc:
        get_current_user(_logged_out_request())
    assert exc.value.status_code == 401


def _audit_rows(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).all()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_file_env(tmp_path, monkeypatch):
    """Point database.DATABASE_URL at a temporary SQLite file so no backup is
    ever written into the real data/ directory. Yields the tmp DB Path."""
    db_file = tmp_path / "fantasy.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (username) VALUES ('alice'), ('bob')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    yield db_file


# ---------------------------------------------------------------------------
# Story: Create a Backup On Demand
# ---------------------------------------------------------------------------

class TestCreateBackup:
    def test_index_html_has_database_backups_panel_and_create_button(self):
        """Admin Settings tab has a 'Database Backups' panel with a 'Create backup now' button."""
        html = _INDEX_HTML_PATH.read_text(encoding="utf-8")
        settings = html[html.index('data-admin-tab="settings"'):html.index('data-admin-tab="matches"')]
        assert "<h2 style=\"margin:0;\">Database Backups</h2>" in settings
        assert "Create backup now" in settings
        assert 'onclick="createBackup()"' in settings
        assert '<script src="/app-admin-backups.js"></script>' in html

    def test_create_backup_returns_filename_size_and_created_at(self, db, db_file_env):
        """POST /admin/backups uses backup_sqlite_db() and returns filename, size_bytes, created_at."""
        before = int(time.time())
        result = admin_backups.create_backup(db=db, admin=_ADMIN)
        path = db_file_env.parent / result["filename"]
        assert path.is_file()
        assert result["size_bytes"] == path.stat().st_size > 0
        assert before - 1 <= result["created_at"] <= int(time.time()) + 1
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        finally:
            conn.close()

    def test_create_backup_file_follows_naming_pattern_next_to_live_db(self, db, db_file_env):
        """New file is named `{db}.backup-YYYYMMDD-HHmmss` in the live DB's directory."""
        result = admin_backups.create_backup(db=db, admin=_ADMIN)
        assert _BACKUP_NAME_RE.match(result["filename"])
        assert (db_file_env.parent / result["filename"]).is_file()
        backups = [p for p in db_file_env.parent.iterdir() if ".backup-" in p.name]
        assert [p.name for p in backups] == [result["filename"]]

    def test_create_backup_writes_audit_log_admin_db_backup(self, db, db_file_env):
        """The action is written to the audit log as `admin_db_backup` with the filename."""
        result = admin_backups.create_backup(db=db, admin=_ADMIN)
        rows = _audit_rows(db, "admin_db_backup")
        assert len(rows) == 1
        assert result["filename"] in rows[0].detail
        assert rows[0].actor_id == _ADMIN["user_id"]
        assert rows[0].actor_username == _ADMIN["username"]

    def test_create_backup_within_60_seconds_returns_429_and_creates_no_file(self, db, db_file_env):
        """A request within 60s of the newest existing backup returns 429 and creates no file."""
        _make_backup(db_file_env, "20260101-000000", age_seconds=30)
        before = sorted(p.name for p in db_file_env.parent.iterdir())
        with pytest.raises(HTTPException) as exc:
            admin_backups.create_backup(db=db, admin=_ADMIN)
        assert exc.value.status_code == 429
        assert sorted(p.name for p in db_file_env.parent.iterdir()) == before
        assert _audit_rows(db, "admin_db_backup") == []

        # Once the newest backup is older than the cooldown, creation works again.
        old = db_file_env.parent / f"{db_file_env.name}.backup-20260101-000000"
        ts = time.time() - 120
        os.utime(old, (ts, ts))
        result = admin_backups.create_backup(db=db, admin=_ADMIN)
        assert (db_file_env.parent / result["filename"]).is_file()

    def test_create_backup_non_sqlite_database_returns_409_and_creates_no_file(self, db, tmp_path, monkeypatch):
        """When DATABASE_URL is not a local SQLite file, returns 409 with a clear message and creates no file."""
        monkeypatch.setattr(database, "DATABASE_URL", "postgresql://user:pw@localhost/fantasy")
        with pytest.raises(HTTPException) as exc:
            admin_backups.create_backup(db=db, admin=_ADMIN)
        assert exc.value.status_code == 409
        assert "SQLite" in exc.value.detail
        assert list(tmp_path.iterdir()) == []
        assert _audit_rows(db, "admin_db_backup") == []

    def test_create_backup_non_admin_returns_403(self, db):
        """Non-admin users get 403 (route guarded by Depends(require_admin))."""
        _assert_route_guarded("/admin/backups", "POST")
        _assert_non_admin_forbidden(db)

    def test_create_backup_logged_out_returns_401(self):
        """Logged-out users get 401."""
        _assert_route_guarded("/admin/backups", "POST")
        _assert_logged_out_unauthorized()


# ---------------------------------------------------------------------------
# Story: See Which Backups Exist
# ---------------------------------------------------------------------------

class TestListBackups:
    def test_list_backups_returns_all_backups_newest_first(self, db, db_file_env):
        """GET /admin/backups returns every `{db}.backup-*` file newest first with filename, size_bytes, created_at."""
        oldest = _make_backup(db_file_env, "20260101-000000", age_seconds=3000, content=b"a")
        newest = _make_backup(db_file_env, "20260103-000000", age_seconds=100, content=b"ccc")
        middle = _make_backup(db_file_env, "20260102-000000", age_seconds=2000, content=b"bb")
        result = admin_backups.list_backups(admin=_ADMIN)
        assert [b["filename"] for b in result["backups"]] == [newest.name, middle.name, oldest.name]
        assert [b["size_bytes"] for b in result["backups"]] == [3, 2, 1]
        for b, p in zip(result["backups"], [newest, middle, oldest]):
            assert set(b) == {"filename", "size_bytes", "created_at"}
            assert b["created_at"] == int(p.stat().st_mtime)

    def test_list_backups_includes_retention_days(self, db, db_file_env, monkeypatch):
        """Response includes retention_days read from DB_BACKUP_RETENTION_DAYS."""
        monkeypatch.setenv("DB_BACKUP_RETENTION_DAYS", "30")
        assert admin_backups.list_backups(admin=_ADMIN)["retention_days"] == 30
        monkeypatch.delenv("DB_BACKUP_RETENTION_DAYS")
        assert admin_backups.list_backups(admin=_ADMIN)["retention_days"] == database.DEFAULT_BACKUP_RETENTION_DAYS
        # main.py reads the same helper rather than duplicating the default.
        main_src = (Path(database.__file__).parent / "main.py").read_text(encoding="utf-8")
        assert "_DB_BACKUP_RETENTION_DAYS  = backup_retention_days()" in main_src

    def test_list_backups_excludes_live_db_and_wal_shm_files(self, db, db_file_env):
        """The listing never includes the live DB file or its -wal/-shm files."""
        (db_file_env.parent / f"{db_file_env.name}-wal").write_bytes(b"w")
        (db_file_env.parent / f"{db_file_env.name}-shm").write_bytes(b"s")
        (db_file_env.parent / "other.db.backup-20260101-000000").write_bytes(b"o")
        backup = _make_backup(db_file_env, "20260101-000000", age_seconds=100)
        names = [b["filename"] for b in admin_backups.list_backups(admin=_ADMIN)["backups"]]
        assert names == [backup.name]

    def test_list_backups_empty_directory_returns_empty_list(self, db, db_file_env):
        """With no backup files, the backups list is empty (panel shows 'No backups yet')."""
        assert admin_backups.list_backups(admin=_ADMIN)["backups"] == []
        js = (_FRONTEND_DIR / "app-admin-backups.js").read_text(encoding="utf-8")
        assert "No backups yet" in js

    def test_list_sqlite_backups_non_sqlite_url_returns_empty(self, monkeypatch):
        """database.list_sqlite_backups() returns [] for a non-SQLite DATABASE_URL."""
        monkeypatch.setattr(database, "DATABASE_URL", "postgresql://user:pw@localhost/fantasy")
        assert database.list_sqlite_backups() == []

    def test_list_backups_non_admin_returns_403(self, db):
        """Non-admin users get 403 on GET /admin/backups."""
        _assert_route_guarded("/admin/backups", "GET")
        _assert_non_admin_forbidden(db)


# ---------------------------------------------------------------------------
# Story: Download a Backup
# ---------------------------------------------------------------------------

class TestDownloadBackup:
    def test_download_backup_returns_attachment_with_content_disposition(self, db, db_file_env):
        """GET /admin/backups/{filename} returns the file as an attachment with Content-Disposition set to the filename."""
        backup = _make_backup(db_file_env, "20260101-000000", age_seconds=100, content=b"payload")
        resp = admin_backups.download_backup(backup.name, db=db, admin=_ADMIN)
        assert isinstance(resp, FileResponse)
        assert Path(resp.path) == backup
        disposition = resp.headers["content-disposition"]
        assert disposition.startswith("attachment")
        assert f'filename="{backup.name}"' in disposition

    def test_download_backup_writes_audit_log_admin_db_backup_download(self, db, db_file_env):
        """Each download is written to the audit log as `admin_db_backup_download` with the filename."""
        backup = _make_backup(db_file_env, "20260101-000000", age_seconds=100)
        admin_backups.download_backup(backup.name, db=db, admin=_ADMIN)
        admin_backups.download_backup(backup.name, db=db, admin=_ADMIN)
        rows = _audit_rows(db, "admin_db_backup_download")
        assert len(rows) == 2
        assert all(backup.name in r.detail for r in rows)

    def test_download_backup_path_traversal_returns_404(self, db, db_file_env):
        """Path traversal such as `../fantasy.db` returns 404."""
        backup = _make_backup(db_file_env, "20260101-000000", age_seconds=100)
        for name in ["../fantasy.db", f"../{db_file_env.parent.name}/{backup.name}",
                     f"./{backup.name}", str(backup), "..%2Ffantasy.db"]:
            with pytest.raises(HTTPException) as exc:
                admin_backups.download_backup(name, db=db, admin=_ADMIN)
            assert exc.value.status_code == 404, name
        assert _audit_rows(db, "admin_db_backup_download") == []

    def test_download_backup_live_db_name_returns_404(self, db, db_file_env):
        """Requesting the live database's own filename (or its -wal/-shm) returns 404."""
        (db_file_env.parent / f"{db_file_env.name}-wal").write_bytes(b"w")
        (db_file_env.parent / f"{db_file_env.name}-shm").write_bytes(b"s")
        for name in [db_file_env.name, f"{db_file_env.name}-wal", f"{db_file_env.name}-shm"]:
            with pytest.raises(HTTPException) as exc:
                admin_backups.download_backup(name, db=db, admin=_ADMIN)
            assert exc.value.status_code == 404, name

    def test_download_backup_unknown_filename_returns_404(self, db, db_file_env):
        """Any filename not exactly matching a listed backup returns 404."""
        backup = _make_backup(db_file_env, "20260101-000000", age_seconds=100)
        for name in ["fantasy.db.backup-20990101-000000", backup.name.upper(), backup.name + " ", ""]:
            with pytest.raises(HTTPException) as exc:
                admin_backups.download_backup(name, db=db, admin=_ADMIN)
            assert exc.value.status_code == 404, name

    def test_download_backup_non_admin_returns_403(self, db):
        """Non-admin users get 403 on GET /admin/backups/{filename}."""
        _assert_route_guarded("/admin/backups/{filename}", "GET")
        _assert_non_admin_forbidden(db)

    def test_download_backup_logged_out_returns_401(self):
        """Logged-out users get 401 on GET /admin/backups/{filename}."""
        _assert_route_guarded("/admin/backups/{filename}", "GET")
        _assert_logged_out_unauthorized()
