"""
Tests for plan: Multi-Admin Support (markdown/plans/plan-multi-admin-support.md).
Resolves GitHub issue #90.

Covers two user stories:

  Story: Seed Multiple Admin Accounts via Environment Variables
    - `SEED_ADMIN_USERNAME`/`_EMAIL`/`_PASSWORD` (unsuffixed) continue to behave
      exactly as today ("admin #1", fully backward compatible)
    - `SEED_ADMIN_USERNAME_2`/`_EMAIL_2`/`_PASSWORD_2` (and `_3`, `_4`, ...) create
      additional admins under the same rules: all three values in a numbered set
      must be present and non-empty, creation is skipped if a user with that email
      already exists, and the step is idempotent across restarts
    - Seeding stops at the first numbered suffix where the set is incomplete or
      absent — no need to declare a total admin count anywhere
    - Each created account logs at INFO level; each already-existing account is
      skipped at DEBUG level, matching the existing single-admin behavior

  Story: Promote or Demote a User's Admin Status In-App
    - The User Management table shows an ADMIN badge next to the username of any
      user with `is_admin = true`, alongside the existing TESTER badge pattern
    - Each row (except the acting admin's own row) has a "Promote to admin" /
      "Demote from admin" toggle button, matching the existing "Mark tester" /
      "Unmark tester" button
    - An admin cannot toggle their own admin status — the button is not rendered
      on their own row, and the backend independently rejects the attempt with
      409 if it is somehow submitted anyway
    - Demoting the last remaining admin is rejected with 409 — the system can
      never end up with zero admin accounts
    - The action is recorded in the audit log, following the existing
      `admin_toggle_tester` pattern

Every stub below is a `pytest.fail("not yet implemented")` placeholder — the
developer replaces each body with the real assertion once the plan is
implemented. Run with: cd backend && python -m pytest tests/test_multi_admin_support.py -v
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from models import User

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
APP_ADMIN_JS_PATH = os.path.join(FRONTEND_DIR, "app-admin-users.js")

_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}


def _patch_session(monkeypatch, db):
    """Point seed.SessionLocal at the in-memory test db session."""
    import seed as seed_module
    monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)


def _set_admin_env(monkeypatch, n, username, email, password):
    """Set SEED_ADMIN_USERNAME[_n]/_EMAIL[_n]/_PASSWORD[_n] env vars."""
    suffix = "" if n == 1 else f"_{n}"
    monkeypatch.setenv(f"SEED_ADMIN_USERNAME{suffix}", username)
    monkeypatch.setenv(f"SEED_ADMIN_EMAIL{suffix}", email)
    monkeypatch.setenv(f"SEED_ADMIN_PASSWORD{suffix}", password)


def _clear_admin_env(monkeypatch, n):
    suffix = "" if n == 1 else f"_{n}"
    monkeypatch.delenv(f"SEED_ADMIN_USERNAME{suffix}", raising=False)
    monkeypatch.delenv(f"SEED_ADMIN_EMAIL{suffix}", raising=False)
    monkeypatch.delenv(f"SEED_ADMIN_PASSWORD{suffix}", raising=False)


# ===========================================================================
# Story: Seed Multiple Admin Accounts via Environment Variables
# ===========================================================================

class TestSeedMultipleAdminsHappyPath:

    def test_unsuffixed_vars_still_create_single_admin_backward_compatible(self, db, monkeypatch):
        """SEED_ADMIN_USERNAME/_EMAIL/_PASSWORD (unsuffixed) continue to create exactly one admin with no numbered suffix vars set, identical to pre-change behavior."""
        _patch_session(monkeypatch, db)
        _clear_admin_env(monkeypatch, 2)
        _set_admin_env(monkeypatch, 1, "adminuser", "admin@test.com", "secret123")

        from seed import seed_admin_from_env
        seed_admin_from_env()

        users = db.query(User).all()
        assert len(users) == 1
        assert users[0].username == "adminuser"
        assert users[0].email == "admin@test.com"
        assert users[0].is_admin is True

    def test_second_admin_created_when_suffix_2_vars_are_set(self, db, monkeypatch):
        """Setting SEED_ADMIN_USERNAME_2/_EMAIL_2/_PASSWORD_2 alongside the unsuffixed admin #1 vars creates a second admin account at startup."""
        _patch_session(monkeypatch, db)
        _set_admin_env(monkeypatch, 1, "admin1", "admin1@test.com", "secret123")
        _set_admin_env(monkeypatch, 2, "admin2", "admin2@test.com", "secret456")

        from seed import seed_admin_from_env
        seed_admin_from_env()

        admin1 = db.query(User).filter_by(username="admin1").first()
        admin2 = db.query(User).filter_by(username="admin2").first()
        assert admin1 is not None and admin1.is_admin is True
        assert admin2 is not None and admin2.is_admin is True
        assert db.query(User).count() == 2

    def test_seeding_multiple_admins_is_idempotent_across_restarts(self, db, monkeypatch):
        """Calling seed_admin_from_env() twice with both admin #1 and admin #2 env vars set does not create duplicate accounts on the second call."""
        _patch_session(monkeypatch, db)
        _set_admin_env(monkeypatch, 1, "admin1", "admin1@test.com", "secret123")
        _set_admin_env(monkeypatch, 2, "admin2", "admin2@test.com", "secret456")

        from seed import seed_admin_from_env
        seed_admin_from_env()
        seed_admin_from_env()

        assert db.query(User).count() == 2

    def test_seeding_skips_creation_when_numbered_email_already_exists(self, db, monkeypatch):
        """If a user with admin #2's email already exists, seed_admin_from_env() skips creating a duplicate for that numbered slot, matching admin #1's existing-email-skip behavior."""
        _patch_session(monkeypatch, db)
        _set_admin_env(monkeypatch, 1, "admin1", "admin1@test.com", "secret123")
        _set_admin_env(monkeypatch, 2, "admin2", "admin2@test.com", "secret456")

        from auth import hash_password
        db.add(User(username="admin2", email="admin2@test.com",
                     password_hash=hash_password("preexisting"), is_admin=True, is_tester=False))
        db.commit()

        from seed import seed_admin_from_env
        seed_admin_from_env()

        assert db.query(User).filter_by(username="admin2").count() == 1
        assert db.query(User).count() == 2  # admin1 newly created, admin2 was pre-existing (not duplicated)

    def test_third_admin_created_when_suffix_3_vars_are_also_set(self, db, monkeypatch):
        """With admin #1, #2, and #3 all fully set, seed_admin_from_env() creates all three admin accounts in one pass."""
        _patch_session(monkeypatch, db)
        _set_admin_env(monkeypatch, 1, "admin1", "admin1@test.com", "secret1")
        _set_admin_env(monkeypatch, 2, "admin2", "admin2@test.com", "secret2")
        _set_admin_env(monkeypatch, 3, "admin3", "admin3@test.com", "secret3")

        from seed import seed_admin_from_env
        seed_admin_from_env()

        users = db.query(User).all()
        usernames = {u.username for u in users}
        assert usernames == {"admin1", "admin2", "admin3"}
        assert all(u.is_admin for u in users)


class TestSeedMultipleAdminsStopsAtGap:

    def test_seeding_stops_at_first_fully_absent_numbered_set(self, db, monkeypatch):
        """With admin #1 and #2 fully set but admin #3's vars entirely absent, seeding creates exactly two admins, does not raise, and requires no declared total admin count."""
        _patch_session(monkeypatch, db)
        _set_admin_env(monkeypatch, 1, "admin1", "admin1@test.com", "secret1")
        _set_admin_env(monkeypatch, 2, "admin2", "admin2@test.com", "secret2")
        _clear_admin_env(monkeypatch, 3)

        from seed import seed_admin_from_env
        seed_admin_from_env()  # must not raise

        usernames = {u.username for u in db.query(User).all()}
        assert usernames == {"admin1", "admin2"}

    def test_seeding_stops_when_numbered_set_is_only_partially_set(self, db, monkeypatch):
        """If SEED_ADMIN_USERNAME_2 and SEED_ADMIN_EMAIL_2 are set but SEED_ADMIN_PASSWORD_2 is empty, admin #2 is not created and seeding stops there rather than skipping ahead to check _3."""
        _patch_session(monkeypatch, db)
        _set_admin_env(monkeypatch, 1, "admin1", "admin1@test.com", "secret1")
        monkeypatch.setenv("SEED_ADMIN_USERNAME_2", "admin2")
        monkeypatch.setenv("SEED_ADMIN_EMAIL_2", "admin2@test.com")
        monkeypatch.delenv("SEED_ADMIN_PASSWORD_2", raising=False)
        # _3 is fully set, but seeding must stop at the incomplete _2 slot before reaching it.
        _set_admin_env(monkeypatch, 3, "admin3", "admin3@test.com", "secret3")

        from seed import seed_admin_from_env
        seed_admin_from_env()

        usernames = {u.username for u in db.query(User).all()}
        assert usernames == {"admin1"}


class TestSeedMultipleAdminsLogging:

    def test_each_created_admin_logs_at_info_level(self, db, monkeypatch, caplog):
        """Each newly created admin account, including numbered admins beyond #1, logs a message at INFO level, matching the existing single-admin logging behavior."""
        _patch_session(monkeypatch, db)
        _set_admin_env(monkeypatch, 1, "admin1", "admin1@test.com", "secret1")
        _set_admin_env(monkeypatch, 2, "admin2", "admin2@test.com", "secret2")

        from seed import seed_admin_from_env
        with caplog.at_level(logging.DEBUG, logger="seed"):
            seed_admin_from_env()

        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("admin1" in m for m in info_messages)
        assert any("admin2" in m for m in info_messages)

    def test_already_existing_numbered_admin_logs_at_debug_level(self, db, monkeypatch, caplog):
        """A numbered admin account (e.g. admin #2) that already exists is skipped and logs at DEBUG level rather than INFO, matching the existing single-admin behavior."""
        _patch_session(monkeypatch, db)
        _set_admin_env(monkeypatch, 1, "admin1", "admin1@test.com", "secret1")
        _set_admin_env(monkeypatch, 2, "admin2", "admin2@test.com", "secret2")

        from auth import hash_password
        db.add(User(username="admin2", email="admin2@test.com",
                     password_hash=hash_password("existing"), is_admin=True, is_tester=False))
        db.commit()

        from seed import seed_admin_from_env
        with caplog.at_level(logging.DEBUG, logger="seed"):
            seed_admin_from_env()

        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("admin2" in m for m in debug_messages)
        # The already-exists skip for admin2 must not also be logged at INFO level
        info_messages_for_admin2 = [
            r.message for r in caplog.records if r.levelno == logging.INFO and "admin2" in r.message
        ]
        assert info_messages_for_admin2 == []


# ===========================================================================
# Story: Promote or Demote a User's Admin Status In-App
# ===========================================================================

class TestListUsersIncludesAdminField:

    def test_get_users_includes_is_admin_field_for_every_row(self, db):
        """GET /users includes an is_admin boolean field for every user row, alongside the existing is_tester field."""
        from routers.admin_users import list_users
        db.add(User(username="u1", email="u1@test.com", password_hash="h", is_admin=False, is_tester=False))
        db.add(User(username="u2", email="u2@test.com", password_hash="h", is_admin=True, is_tester=True))
        db.commit()

        rows = list_users(db=db, _=_ADMIN)

        assert len(rows) == 2
        for row in rows:
            assert "is_admin" in row
            assert isinstance(row["is_admin"], bool)
            assert "is_tester" in row
        admin_row = next(r for r in rows if r["username"] == "u2")
        non_admin_row = next(r for r in rows if r["username"] == "u1")
        assert admin_row["is_admin"] is True
        assert non_admin_row["is_admin"] is False


class TestToggleAdminEndpointHappyPath:

    def test_toggle_admin_promotes_regular_user_to_admin(self, db):
        """POST /users/{user_id}/toggle-admin, called by an existing admin against a non-admin user, sets is_admin=True and returns it in the response body."""
        from routers.admin_users import toggle_admin
        acting_admin = User(username="admin", email="admin@test.com", password_hash="h", is_admin=True)
        target = User(username="target", email="target@test.com", password_hash="h", is_admin=False)
        db.add_all([acting_admin, target])
        db.commit()

        actor = {"user_id": acting_admin.id, "username": acting_admin.username, "is_admin": True}
        result = toggle_admin(user_id=target.id, admin=actor, db=db)

        assert result["is_admin"] is True
        assert result["user_id"] == target.id
        assert result["username"] == "target"
        db.refresh(target)
        assert target.is_admin is True

    def test_toggle_admin_demotes_admin_when_another_admin_remains(self, db):
        """POST /users/{user_id}/toggle-admin demotes a second admin account (is_admin True -> False) when at least one other admin account still exists."""
        from routers.admin_users import toggle_admin
        admin1 = User(username="admin1", email="admin1@test.com", password_hash="h", is_admin=True)
        admin2 = User(username="admin2", email="admin2@test.com", password_hash="h", is_admin=True)
        db.add_all([admin1, admin2])
        db.commit()

        actor = {"user_id": admin1.id, "username": admin1.username, "is_admin": True}
        result = toggle_admin(user_id=admin2.id, admin=actor, db=db)

        assert result["is_admin"] is False
        db.refresh(admin2)
        assert admin2.is_admin is False

    def test_toggle_admin_records_admin_toggle_admin_audit_log_entry(self, db):
        """Toggling a user's admin status writes an admin_toggle_admin entry to the audit log, following the existing admin_toggle_tester pattern."""
        from routers.admin_users import toggle_admin
        from models import AuditLog
        admin1 = User(username="admin1", email="admin1@test.com", password_hash="h", is_admin=True)
        target = User(username="target", email="target@test.com", password_hash="h", is_admin=False)
        db.add_all([admin1, target])
        db.commit()

        actor = {"user_id": admin1.id, "username": admin1.username, "is_admin": True}
        toggle_admin(user_id=target.id, admin=actor, db=db)

        entries = db.query(AuditLog).filter_by(action="admin_toggle_admin").all()
        assert len(entries) == 1
        assert entries[0].actor_username == "admin1"
        assert entries[0].actor_id == admin1.id
        assert "target" in (entries[0].detail or "")
        assert "True" in (entries[0].detail or "")

    def test_toggle_admin_nonexistent_user_returns_404(self, db):
        """POST /users/{user_id}/toggle-admin for a user_id that does not exist returns 404 'User not found'."""
        from routers.admin_users import toggle_admin
        admin1 = User(username="admin1", email="admin1@test.com", password_hash="h", is_admin=True)
        db.add(admin1)
        db.commit()

        actor = {"user_id": admin1.id, "username": admin1.username, "is_admin": True}
        with pytest.raises(HTTPException) as exc:
            toggle_admin(user_id=999999, admin=actor, db=db)
        assert exc.value.status_code == 404
        assert exc.value.detail == "User not found"


class TestToggleAdminSelfDemotionGuard:

    def test_toggle_admin_rejects_self_toggle_with_409(self, db):
        """An admin calling POST /users/{their_own_id}/toggle-admin against their own account receives 409 'Cannot change your own admin status', and their is_admin status is left unchanged."""
        from routers.admin_users import toggle_admin
        admin1 = User(username="admin1", email="admin1@test.com", password_hash="h", is_admin=True)
        admin2 = User(username="admin2", email="admin2@test.com", password_hash="h", is_admin=True)
        db.add_all([admin1, admin2])
        db.commit()

        actor = {"user_id": admin1.id, "username": admin1.username, "is_admin": True}
        with pytest.raises(HTTPException) as exc:
            toggle_admin(user_id=admin1.id, admin=actor, db=db)
        assert exc.value.status_code == 409
        assert exc.value.detail == "Cannot change your own admin status"
        db.refresh(admin1)
        assert admin1.is_admin is True


class TestToggleAdminLastAdminGuard:

    def test_toggle_admin_rejects_demoting_last_remaining_admin_with_409(self, db):
        """Demoting the sole remaining admin account is rejected with 409 'Cannot demote the last remaining admin', and its is_admin status is left unchanged, even when the request is made against a different actor's own id (i.e. the self-toggle guard does not mask this one)."""
        from routers.admin_users import toggle_admin
        sole_admin = User(username="soleadmin", email="sole@test.com", password_hash="h", is_admin=True)
        other_user = User(username="other", email="other@test.com", password_hash="h", is_admin=False)
        db.add_all([sole_admin, other_user])
        db.commit()

        # Actor's id differs from the target's id, so the self-toggle guard does
        # not fire — this isolates the last-admin guard as the one being tested.
        actor = {"user_id": other_user.id, "username": other_user.username, "is_admin": False}
        with pytest.raises(HTTPException) as exc:
            toggle_admin(user_id=sole_admin.id, admin=actor, db=db)
        assert exc.value.status_code == 409
        assert exc.value.detail == "Cannot demote the last remaining admin"
        db.refresh(sole_admin)
        assert sole_admin.is_admin is True


class TestFrontendAdminBadgeAndToggleButton:

    def test_admin_badge_rendered_for_users_with_is_admin_true(self):
        """_renderUsers() in frontend/app-admin-users.js renders an ADMIN badge next to the username for any user row with is_admin true, alongside the existing TESTER badge pattern."""
        with open(APP_ADMIN_JS_PATH) as f:
            source = f.read()
        assert "u.is_admin" in source
        assert "ADMIN</span>" in source
        assert "TESTER</span>" in source  # existing pattern this mirrors

    def test_toggle_admin_button_omitted_on_acting_admins_own_row(self):
        """_renderUsers() renders a Promote to admin / Demote from admin toggle button on every user row except the one where u.id === activeUserId."""
        with open(APP_ADMIN_JS_PATH) as f:
            source = f.read()
        assert "u.id === activeUserId" in source
        assert "toggleAdmin(${u.id})" in source
        assert "Promote to admin" in source
        assert "Demote from admin" in source

    def test_toggle_admin_js_function_calls_toggle_admin_endpoint(self):
        """toggleAdmin(userId) in frontend/app-admin-users.js POSTs to /users/{userId}/toggle-admin and reloads the user list on success, mirroring toggleTester()'s fetch/status/reload pattern."""
        with open(APP_ADMIN_JS_PATH) as f:
            source = f.read()
        start = source.index("async function toggleAdmin(userId)")
        end = source.index("async function grantTokens")
        body = source[start:end]
        assert "/users/${userId}/toggle-admin" in body
        assert "data.is_admin" in body
        assert "loadUsers()" in body
