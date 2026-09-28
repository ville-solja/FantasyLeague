"""
Tests for plan-test-background-task-isolation.md.

Opening `TestClient(main.app)` as a context manager runs the lifespan, which
starts four daemon threads (week maintenance, ingest poll, profile enrichment,
DB backup). They outlive the test that started them, share its database and
touch the real data/ directory, causing the test_issue_124 flake. The plan adds
a `BACKGROUND_TASKS_ENABLED` env var (default "true") and has conftest.py set
it to "false" before any app module is imported.

Testing approach:
  - Thread detection: the lifespan starts unnamed `threading.Thread(target=...)`
    objects. On Python 3.10+ their default name is "Thread-N (<target name>)",
    so match `threading.enumerate()` names against the four target names:
    `_week_maintenance_loop`, `_ingest_poll_loop`, `_profile_enrichment_loop`,
    `_backup_loop`. Compare the set of live thread idents before and after.
  - In-process lifespan tests: build the app like test_security_headers.py's
    `client` fixture (DEBUG=true, AUTO_INGEST_LEAGUES="", in-memory StaticPool
    engine patched into database/enrich/ingest/seed SessionLocal, reload main)
    and ALSO point `database.DATABASE_URL` at tmp_path so nothing touches the
    real data/fantasy.db. Per lessons-learned (2026-09-27), reload only modules
    already in `sys.modules`; never reload a router twice.
  - Production-behaviour test: run in a subprocess (python3, cwd=backend/) with
    BACKGROUND_TASKS_ENABLED and TWITCH_LOCAL_DEV removed from the env,
    DEBUG=true, DATABASE_URL=sqlite:///<tmp_path>/fantasy.db. The child enters
    `TestClient(main.app)` as a context manager, prints the matching thread
    names, then exits (daemon threads die with the process). The real threads
    must never reach the real data/ dir, hence the tmp DATABASE_URL.
  - conftest ordering: static check that the
    `os.environ.setdefault("BACKGROUND_TASKS_ENABLED", "false")` line appears
    in conftest.py before any `import main` / `from main` / `routers` /
    `database` import, plus a runtime check of os.environ.

Manual verification (not automated):
  - `test_issue_124_roster_mutation_rate_limiting.py` and the suite-size
    tripwire in `test_issue_85_split_admin_router.py` pass in 10 consecutive
    full-suite runs (`cd backend && python3 -m pytest tests/` x10). Record the
    results in the implementation report. Bump the tripwire count by the
    number of new tests in this file.
  - Starting the app normally (variable unset) logs all four
    "thread started" lines.
"""

import importlib
import logging
import os
import pathlib
import subprocess
import sys
import textwrap
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_REAL_DATA_DIR = _BACKEND_DIR.parent / "data"
_LOOP_TARGETS = (
    "_week_maintenance_loop",
    "_ingest_poll_loop",
    "_profile_enrichment_loop",
    "_backup_loop",
)
_DISABLED_LINE = "Background tasks disabled (BACKGROUND_TASKS_ENABLED=false)"


def _loop_threads():
    return [
        t for t in threading.enumerate()
        if any(f"({target})" in t.name for target in _LOOP_TARGETS)
    ]


def _build_main(monkeypatch, tmp_path):
    """Reload `main` against an in-memory StaticPool engine (same shape as
    test_security_headers.py's fixture), with DATABASE_URL pointed at
    tmp_path so nothing can reach the real data/fantasy.db."""
    monkeypatch.setenv("AUTO_INGEST_LEAGUES", "")
    monkeypatch.setenv("DEBUG", "true")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database
    import main as main_module

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_session_factory)
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'fantasy.db'}")

    import enrich
    import ingest
    import seed
    monkeypatch.setattr(enrich, "SessionLocal", test_session_factory)
    monkeypatch.setattr(ingest, "SessionLocal", test_session_factory)
    monkeypatch.setattr(seed, "SessionLocal", test_session_factory)

    importlib.reload(main_module)
    main_module.engine = test_engine
    main_module.SessionLocal = test_session_factory
    return main_module, test_session_factory


class _RecordingThread:
    """Stand-in for threading.Thread that records targets without running them."""
    started: list = []

    def __init__(self, target=None, daemon=None, **kwargs):
        self.target = target

    def start(self):
        _RecordingThread.started.append(self.target.__name__)


def _run_lifespan_recording_threads(monkeypatch, tmp_path):
    main_module, _ = _build_main(monkeypatch, tmp_path)
    _RecordingThread.started = []
    monkeypatch.setattr(main_module.threading, "Thread", _RecordingThread)
    with TestClient(main_module.app):
        pass
    return list(_RecordingThread.started)


# ---------------------------------------------------------------------------
# Story 1 — Tests Never Start Background Threads
# ---------------------------------------------------------------------------

def test_lifespan_background_tasks_enabled_by_default(monkeypatch, tmp_path):
    """BACKGROUND_TASKS_ENABLED defaults to true: with the variable unset, the lifespan code path starts the four threads (in-process, variable removed via monkeypatch, tmp DATABASE_URL)."""
    monkeypatch.delenv("BACKGROUND_TASKS_ENABLED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    # threading.Thread is replaced with a recorder so the real loops never
    # run in this process; the subprocess tests below start the real ones.
    started = _run_lifespan_recording_threads(monkeypatch, tmp_path)
    assert sorted(started) == sorted(_LOOP_TARGETS)


def test_lifespan_background_tasks_disabled_when_false(monkeypatch, tmp_path):
    """With BACKGROUND_TASKS_ENABLED=false none of the four loop targets appear in threading.enumerate() after entering the lifespan."""
    monkeypatch.setenv("BACKGROUND_TASKS_ENABLED", "false")
    main_module, _ = _build_main(monkeypatch, tmp_path)
    with TestClient(main_module.app):
        assert _loop_threads() == []


@pytest.mark.parametrize("value", ["FALSE", "False"])
def test_lifespan_background_tasks_value_case_insensitive(monkeypatch, tmp_path, value):
    """Failure path: 'FALSE' / 'False' also disables the threads (the check lowercases the value)."""
    monkeypatch.setenv("BACKGROUND_TASKS_ENABLED", value)
    started = _run_lifespan_recording_threads(monkeypatch, tmp_path)
    assert started == []


def test_conftest_sets_variable_before_app_imports():
    """Static check: conftest.py sets BACKGROUND_TASKS_ENABLED=false before any import of main, routers or database."""
    lines = (_BACKEND_DIR / "tests" / "conftest.py").read_text().splitlines()
    setdefault_line = 'os.environ.setdefault("BACKGROUND_TASKS_ENABLED", "false")'
    idx = next(i for i, line in enumerate(lines) if line.strip() == setdefault_line)
    app_import_prefixes = (
        "import main", "from main", "import routers", "from routers",
        "import database", "from database",
    )
    first_app_import = next(
        i for i, line in enumerate(lines)
        if line.strip().startswith(app_import_prefixes)
    )
    assert idx < first_app_import


def test_conftest_variable_is_false_at_runtime():
    """Runtime check: os.environ['BACKGROUND_TASKS_ENABLED'] == 'false' while the suite runs."""
    assert os.environ.get("BACKGROUND_TASKS_ENABLED") == "false"


def test_lifespan_disabled_still_runs_startup_work(monkeypatch, tmp_path):
    """With tasks disabled, the lifespan still creates tables, runs migrations and seeds (e.g. weights/tags present in the patched DB)."""
    from models import TagDefinition, Weight
    monkeypatch.setenv("BACKGROUND_TASKS_ENABLED", "false")
    main_module, session_factory = _build_main(monkeypatch, tmp_path)
    with TestClient(main_module.app):
        db = session_factory()
        try:
            assert db.query(Weight).count() > 0
            assert db.query(TagDefinition).count() > 0
        finally:
            db.close()


def test_lifespan_disabled_logs_single_disabled_line(monkeypatch, tmp_path, caplog):
    """With tasks disabled, exactly one 'Background tasks disabled (BACKGROUND_TASKS_ENABLED=false)' line is logged and no 'thread started' lines appear."""
    monkeypatch.setenv("BACKGROUND_TASKS_ENABLED", "false")
    main_module, _ = _build_main(monkeypatch, tmp_path)
    with caplog.at_level(logging.INFO, logger="main"):
        with TestClient(main_module.app):
            pass
    messages = [r.getMessage() for r in caplog.records if r.name == "main"]
    assert messages.count(_DISABLED_LINE) == 1
    assert not [m for m in messages if "thread started" in m]


def test_testclient_context_manager_starts_no_new_threads(monkeypatch, tmp_path):
    """Opening TestClient(main.app) as a context manager leaves the live thread count unchanged before vs. after."""
    main_module, _ = _build_main(monkeypatch, tmp_path)
    before = {t.ident for t in threading.enumerate()}
    # No request is made: the first rate-limited request starts the limits
    # library's MemoryStorage expiry threading.Timer, which is not a lifespan thread.
    with TestClient(main_module.app):
        pass
    after = {t.ident for t in threading.enumerate()}
    new = [t.name for t in threading.enumerate() if t.ident in after - before]
    assert new == []
    assert len(after) == len(before)


def test_testclient_context_manager_no_loop_threads_linger_after_exit(monkeypatch, tmp_path):
    """Failure path: after the `with` block exits, no thread named for any of the four loop targets is alive."""
    main_module, _ = _build_main(monkeypatch, tmp_path)
    with TestClient(main_module.app):
        pass
    assert _loop_threads() == []


def _snapshot(directory: pathlib.Path) -> set:
    if not directory.exists():
        return set()
    return {str(p) for p in directory.rglob("*")}


def test_lifespan_disabled_writes_no_backup_to_real_data_dir(monkeypatch, tmp_path):
    """Entering the lifespan with tasks disabled creates no new file in the real data/ (or data/backups/) directory."""
    before = _snapshot(_REAL_DATA_DIR)
    main_module, _ = _build_main(monkeypatch, tmp_path)
    with TestClient(main_module.app):
        pass
    assert _snapshot(_REAL_DATA_DIR) - before == set()
    assert not (tmp_path / "backups").exists()


def test_lifespan_disabled_no_backup_failed_log_line(monkeypatch, tmp_path, caplog):
    """Failure path: the 'Automatic DB backup failed' log line is not emitted while the lifespan runs under tests."""
    main_module, _ = _build_main(monkeypatch, tmp_path)
    with caplog.at_level(logging.INFO):
        with TestClient(main_module.app):
            pass
    assert "Automatic DB backup failed" not in caplog.text


# ---------------------------------------------------------------------------
# Story 2 — Stable Full-Suite Runs
# (10 consecutive full-suite runs: manual verification, see module docstring)
# ---------------------------------------------------------------------------

_CHILD_SCRIPT = textwrap.dedent("""
    import threading
    from fastapi.testclient import TestClient
    import main

    targets = %r
    with TestClient(main.app):
        live = [t for t in threading.enumerate()
                if any("(%%s)" %% name in t.name for name in targets)]
        print("STARTED:" + ",".join(sorted(
            name for name in targets if any("(%%s)" %% name in t.name for t in live))))
    # Lifespan exit set _stop_event; every loop must now finish on its own.
    for t in live:
        t.join(timeout=20)
    print("ALIVE:" + str(sum(t.is_alive() for t in live)))
""") % (_LOOP_TARGETS,)


def _run_child(tmp_path, extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    for name in ("BACKGROUND_TASKS_ENABLED", "TWITCH_LOCAL_DEV", "SECRET_KEY", "ENV", "DEMO_MODE"):
        env.pop(name, None)
    env.update({
        "DEBUG": "true",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'fantasy.db'}",
        "AUTO_INGEST_LEAGUES": "",
    })
    env.update(extra_env or {})
    result = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        cwd=str(_BACKEND_DIR), env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    started = next(l for l in lines if l.startswith("STARTED:"))[len("STARTED:"):]
    alive = next(l for l in lines if l.startswith("ALIVE:"))[len("ALIVE:"):]
    assert alive == "0", result.stdout + result.stderr
    return set(filter(None, started.split(","))), result.stdout + result.stderr


def test_lifespan_production_unset_starts_all_four_threads(tmp_path):
    """Subprocess with the variable unset (DEBUG=true, tmp DATABASE_URL, TWITCH_LOCAL_DEV unset): entering the lifespan starts all four loop threads, then shuts down cleanly."""
    started, output = _run_child(tmp_path)
    assert started == set(_LOOP_TARGETS), output
    assert _DISABLED_LINE not in output


def test_lifespan_production_explicit_true_starts_all_four_threads(tmp_path):
    """Subprocess with BACKGROUND_TASKS_ENABLED=true behaves like unset: all four threads start."""
    started, output = _run_child(tmp_path, {"BACKGROUND_TASKS_ENABLED": "true"})
    assert started == set(_LOOP_TARGETS), output


def test_lifespan_production_demo_mode_still_skips_ingest(tmp_path):
    """Failure path: with the variable unset and DEMO_MODE=true, the existing ingest skip is preserved (three threads, no _ingest_poll_loop)."""
    started, output = _run_child(tmp_path, {"DEMO_MODE": "true"})
    assert started == set(_LOOP_TARGETS) - {"_ingest_poll_loop"}, output
    assert "Ingest poll thread skipped (DEMO_MODE=true)" in output
