"""
Failing test stubs for plan-issue-85-split-admin-router.

Pre-implementation stage: `backend/routers/admin.py` still exists as a single
1,236-line module; none of the ten focused modules it will be split into
(`admin_users`, `admin_ingest`, `admin_weeks`, `admin_notifications`,
`admin_tags`, `admin_players`, `admin_leagues`, `admin_season`, `admin_matches`,
`admin_demo`) exist yet. Every stub below is a `pytest.fail("not yet implemented")`
placeholder — the developer replaces each body with the real assertion once the
split lands. This is a pure internal refactor: no endpoint path, method,
request/response shape, or `Depends()` auth guard should change, so nearly every
stub here is a structural/import check rather than a behavior check.

Covers two user stories from markdown/plans/plan-issue-85-split-admin-router.md
that are testable via pytest:

  Story: Split Admin Endpoints into Focused Router Modules
    - backend/routers/admin.py is replaced by ten focused APIRouter() modules
      (see the Critical Files table in the plan for the exact split)
    - backend/routers/admin.py itself is removed once the split lands
    - Every existing endpoint/function keeps its exact behavior and Depends()
      auth guard across the move (spot-checked via known function names and the
      one auth-guard-sensitive endpoint the plan calls out: POST /redeem)
    - backend/main.py imports and include_router()s each of the ten new modules
      in place of the single admin_router, and no longer imports the old module
    - No new module exceeds roughly 350 lines

  Story: Preserve Existing Test Coverage Through the Split
    - test_issue_81_season_lifecycle.py and test_issue_83_demo_mode.py import
      their admin handler functions from the correct new module paths instead
      of the retired `routers.admin`
    - The `_stub_backup` monkeypatch fixture in TestSeasonReset targets
      `routers.admin_season.backup_sqlite_db`, not the old path
    - `cd backend && python -m pytest tests/ -v` passes with the same pass/skip
      counts as before the split (462 passed, 10 skipped as of this writing —
      this number grows over time as new feature test files land; it is not an
      eternal invariant, just a regression tripwire for the split itself)
    - `python -c "import main"` succeeds with no import errors, and the old
      `routers.admin` module is no longer importable at all

Story "Keep Developer Agent Definitions Accurate After the Split" is a manual
follow-up performed by running `/agent-steward` after implementation (per the
plan's Step 4) and is out of scope for pytest — it produces no stub here.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")

_NEW_ADMIN_MODULES = [
    "admin_users",
    "admin_ingest",
    "admin_weeks",
    "admin_notifications",
    "admin_tags",
    "admin_players",
    "admin_leagues",
    "admin_season",
    "admin_matches",
    "admin_demo",
]


# ---------------------------------------------------------------------------
# Story: Split Admin Endpoints into Focused Router Modules
# ---------------------------------------------------------------------------

class TestAdminRouterSplitIntoFocusedModules:

    def test_admin_router_split_into_ten_focused_modules(self):
        """backend/routers/admin.py is replaced by ten self-contained APIRouter() modules (one per Critical Files table row)."""
        import importlib

        for mod_name in _NEW_ADMIN_MODULES:
            mod = importlib.import_module(f"routers.{mod_name}")
            assert hasattr(mod, "router"), f"routers.{mod_name} has no module-level `router`"
            from fastapi import APIRouter
            assert isinstance(mod.router, APIRouter), f"routers.{mod_name}.router is not an APIRouter()"

    def test_old_admin_module_file_removed(self):
        """backend/routers/admin.py is deleted once every section has a new home (the monolith is replaced, not kept alongside the split)."""
        admin_path = os.path.join(_BACKEND_DIR, "routers", "admin.py")
        assert not os.path.exists(admin_path)

    def test_known_admin_functions_importable_from_new_modules(self):
        """reset_season/end_season import from routers.admin_season, create_week/edit_week/delete_week from routers.admin_weeks, and get_demo_clock/set_demo_clock/clear_demo_clock/seed_demo_accounts from routers.admin_demo."""
        from routers.admin_season import reset_season, end_season
        from routers.admin_weeks import create_week, edit_week, delete_week
        from routers.admin_demo import (
            get_demo_clock, set_demo_clock, clear_demo_clock, seed_demo_accounts,
        )
        assert all(callable(f) for f in (
            reset_season, end_season, create_week, edit_week, delete_week,
            get_demo_clock, set_demo_clock, clear_demo_clock, seed_demo_accounts,
        ))

    def test_redeem_code_retains_get_current_user_not_require_admin(self):
        """POST /redeem keeps its Depends(get_current_user) guard (not require_admin) after moving to routers.admin_users with the rest of the promo-code CRUD."""
        admin_users_path = os.path.join(_BACKEND_DIR, "routers", "admin_users.py")
        with open(admin_users_path) as f:
            source = f.read()
        assert '"/redeem"' in source

        import inspect
        from routers.admin_users import redeem_code
        sig = inspect.signature(redeem_code)
        current_user_param = sig.parameters["current_user"]
        default_repr = repr(current_user_param.default)
        assert "get_current_user" in default_repr
        assert "require_admin" not in default_repr

    def test_main_py_mounts_all_ten_admin_router_modules(self):
        """backend/main.py imports and include_router()s each of the ten new admin_* modules in place of the single admin_router."""
        main_path = os.path.join(_BACKEND_DIR, "main.py")
        with open(main_path) as f:
            source = f.read()
        for mod_name in _NEW_ADMIN_MODULES:
            assert f"routers import {mod_name}" in source, f"main.py does not import routers.{mod_name}"
            assert f"{mod_name}_router.router" in source, f"main.py does not include_router() for {mod_name}"

    def test_main_py_no_longer_imports_monolithic_admin_router(self):
        """backend/main.py no longer contains `from routers import admin as admin_router` / `app.include_router(admin_router.router)`."""
        main_path = os.path.join(_BACKEND_DIR, "main.py")
        with open(main_path) as f:
            source = f.read()
        assert "from routers import admin as admin_router" not in source
        assert "app.include_router(admin_router.router)" not in source

    def test_no_new_admin_module_exceeds_350_lines(self):
        """None of the ten new backend/routers/admin_*.py files exceeds roughly 350 lines."""
        for mod_name in _NEW_ADMIN_MODULES:
            mod_path = os.path.join(_BACKEND_DIR, "routers", f"{mod_name}.py")
            with open(mod_path) as f:
                line_count = sum(1 for _ in f)
            assert line_count <= 350, f"routers/{mod_name}.py has {line_count} lines (> 350)"


# ---------------------------------------------------------------------------
# Story: Preserve Existing Test Coverage Through the Split
# ---------------------------------------------------------------------------

class TestPreserveExistingTestCoverageThroughSplit:

    def test_issue_81_imports_from_new_admin_modules(self):
        """test_issue_81_season_lifecycle.py imports end_season/reset_season from routers.admin_season and create_week/edit_week/delete_week from routers.admin_weeks."""
        path = os.path.join(_BACKEND_DIR, "tests", "test_issue_81_season_lifecycle.py")
        with open(path) as f:
            source = f.read()
        assert "from routers.admin_season import" in source
        assert "end_season" in source and "reset_season" in source
        assert "from routers.admin_weeks import" in source
        assert "create_week" in source and "edit_week" in source and "delete_week" in source

    def test_issue_83_imports_from_new_admin_modules(self):
        """test_issue_83_demo_mode.py imports get_demo_clock/set_demo_clock/clear_demo_clock/seed_demo_accounts from routers.admin_demo."""
        path = os.path.join(_BACKEND_DIR, "tests", "test_issue_83_demo_mode.py")
        with open(path) as f:
            source = f.read()
        assert "from routers.admin_demo import" in source
        for name in ("get_demo_clock", "set_demo_clock", "clear_demo_clock", "seed_demo_accounts"):
            assert name in source

    def test_issue_81_and_83_no_longer_import_old_admin_module(self):
        """Neither test_issue_81_season_lifecycle.py nor test_issue_83_demo_mode.py contains a `from routers.admin import ...` line referencing the retired monolith."""
        for filename in ("test_issue_81_season_lifecycle.py", "test_issue_83_demo_mode.py"):
            path = os.path.join(_BACKEND_DIR, "tests", filename)
            with open(path) as f:
                source = f.read()
            assert "from routers.admin import" not in source, f"{filename} still imports from the retired routers.admin"

    def test_stub_backup_fixture_targets_admin_season_module(self):
        """The _stub_backup monkeypatch fixture in TestSeasonReset patches routers.admin_season.backup_sqlite_db."""
        path = os.path.join(_BACKEND_DIR, "tests", "test_issue_81_season_lifecycle.py")
        with open(path) as f:
            source = f.read()
        assert "import routers.admin_season as admin_season_module" in source
        assert 'monkeypatch.setattr(admin_season_module, "backup_sqlite_db"' in source

    def test_stub_backup_fixture_no_longer_targets_old_admin_module(self):
        """The _stub_backup fixture no longer imports routers.admin as admin_module or patches routers.admin.backup_sqlite_db."""
        path = os.path.join(_BACKEND_DIR, "tests", "test_issue_81_season_lifecycle.py")
        with open(path) as f:
            source = f.read()
        assert "import routers.admin as admin_module" not in source
        assert "routers.admin.backup_sqlite_db" not in source

    def test_full_suite_pass_skip_counts_match_pre_split_baseline(self):
        """`cd backend && python -m pytest tests/ -v` reports the same 494 passed / 10 skipped as before the split.

        This baseline is a regression tripwire for the admin router split, not an
        eternal invariant — it is expected to be bumped upward whenever a later
        feature legitimately adds new passing tests elsewhere in the suite (as
        plan-issue-87-schedule-game-breakdown's 14 new tests did,
        plan-schedule-independent-results's 10 new tests did after that, and
        plan-how-to-play-role-subtabs's 22 new tests did after that)."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q",
             "--ignore=tests/test_issue_85_split_admin_router.py"],
            cwd=_BACKEND_DIR, capture_output=True, text=True,
        )
        output = result.stdout + result.stderr
        assert "494 passed" in output, output[-3000:]
        assert "10 skipped" in output, output[-3000:]

    def test_full_suite_collects_without_import_errors(self):
        """pytest collection of backend/tests/ produces zero collection errors after the split (no stale import paths left behind)."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
            cwd=_BACKEND_DIR, capture_output=True, text=True,
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, output[-3000:]
        # pytest reports collection failures as "ERROR" (uppercase) lines in the
        # short summary and an "errors" count in the final summary line — plain
        # lowercase "error" also appears legitimately inside unrelated test names
        # (e.g. "...clear_error...") so it is not a safe substring to check.
        assert "ERROR" not in output, output[-3000:]

    def test_main_module_imports_cleanly_after_split(self):
        """`python -c "import main"` succeeds with no import errors once main.py is rewired to the ten new admin_* modules."""
        env = dict(os.environ)
        env["DEBUG"] = "true"
        result = subprocess.run(
            [sys.executable, "-c", "import main"],
            cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_old_admin_module_no_longer_importable(self):
        """`import routers.admin` raises ModuleNotFoundError once the monolithic file has been deleted."""
        with pytest.raises(ModuleNotFoundError):
            import importlib
            importlib.import_module("routers.admin")

    def test_no_lingering_references_to_old_admin_module_in_backend(self):
        """grep -rn "from routers.admin import\\|routers\\.admin\\b" backend/ returns no matches once Step 3 of the plan is complete."""
        result = subprocess.run(
            ["grep", "-rn",
             r"from routers\.admin import\|routers\.admin\b",
             "."],
            cwd=_BACKEND_DIR, capture_output=True, text=True,
        )
        matches = [
            line for line in result.stdout.splitlines()
            if not line.startswith("./tests/test_issue_85_split_admin_router.py:")
            and "__pycache__" not in line
        ]
        assert matches == [], f"Unexpected lingering references:\n" + "\n".join(matches)
