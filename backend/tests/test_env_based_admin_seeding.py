"""
Tests for plan: Env-Based Admin Seeding.
Each test corresponds to one acceptance criterion from the plan's user stories.
Run with: cd backend && python -m pytest tests/test_env_based_admin_seeding.py -v
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import User
from seed import seed_admin_from_env, seed_users


# --- Story 1: Configure the Admin Account via Environment Variables ---

class TestSeedAdminFromEnvHappyPath:
    def test_admin_created_when_all_env_vars_set(self, db, monkeypatch):
        """If SEED_ADMIN_USERNAME, SEED_ADMIN_EMAIL, and SEED_ADMIN_PASSWORD are all set, an admin user with is_admin=True is created."""
        monkeypatch.setenv("SEED_ADMIN_USERNAME", "adminuser")
        monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@test.com")
        monkeypatch.setenv("SEED_ADMIN_PASSWORD", "secret123")

        # Patch SessionLocal to return our test db session
        import seed as seed_module
        monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)

        seed_admin_from_env()

        user = db.query(User).filter_by(email="admin@test.com").first()
        assert user is not None
        assert user.username == "adminuser"
        assert user.is_admin is True

    def test_admin_not_duplicated_when_email_already_exists(self, db, monkeypatch):
        """If the env vars are set but a user with that email already exists, no duplicate is created."""
        monkeypatch.setenv("SEED_ADMIN_USERNAME", "adminuser")
        monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@test.com")
        monkeypatch.setenv("SEED_ADMIN_PASSWORD", "secret123")

        import seed as seed_module
        monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)

        # Call twice
        seed_admin_from_env()
        seed_admin_from_env()

        count = db.query(User).filter_by(email="admin@test.com").count()
        assert count == 1


class TestSeedAdminFromEnvMissingVars:
    def test_no_admin_created_when_env_vars_absent(self, db, monkeypatch):
        """If the SEED_ADMIN_* env vars are absent, no admin account is auto-created and no exception is raised."""
        monkeypatch.delenv("SEED_ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("SEED_ADMIN_EMAIL", raising=False)
        monkeypatch.delenv("SEED_ADMIN_PASSWORD", raising=False)

        import seed as seed_module
        monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)

        # Should not raise
        seed_admin_from_env()

        count = db.query(User).count()
        assert count == 0

    def test_no_admin_created_when_env_vars_empty(self, db, monkeypatch):
        """If any of the SEED_ADMIN_* env vars are empty strings, seeding is skipped silently."""
        monkeypatch.setenv("SEED_ADMIN_USERNAME", "")
        monkeypatch.setenv("SEED_ADMIN_EMAIL", "")
        monkeypatch.setenv("SEED_ADMIN_PASSWORD", "")

        import seed as seed_module
        monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)

        seed_admin_from_env()

        count = db.query(User).count()
        assert count == 0


class TestUsersJsonStub:
    def test_users_json_is_empty_array(self):
        """The backend/seed/users.json file contains only an empty array [] so no real passwords are committed."""
        users_json_path = os.path.join(os.path.dirname(__file__), "..", "seed", "users.json")
        with open(users_json_path) as f:
            data = json.load(f)
        assert data == []

    def test_seed_users_does_not_crash_with_empty_json(self, db, monkeypatch):
        """seed_users() does not raise when users.json contains []."""
        import seed as seed_module
        monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)

        # Should not raise
        seed_users()

        count = db.query(User).count()
        assert count == 0


class TestDotEnvExample:
    def _read_env_example(self):
        env_example_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env.example")
        with open(env_example_path) as f:
            return f.read()

    def test_env_example_documents_seed_admin_username(self):
        """.env.example documents the SEED_ADMIN_USERNAME variable."""
        content = self._read_env_example()
        assert "SEED_ADMIN_USERNAME" in content

    def test_env_example_documents_seed_admin_email(self):
        """.env.example documents the SEED_ADMIN_EMAIL variable."""
        content = self._read_env_example()
        assert "SEED_ADMIN_EMAIL" in content

    def test_env_example_documents_seed_admin_password(self):
        """.env.example documents the SEED_ADMIN_PASSWORD variable."""
        content = self._read_env_example()
        assert "SEED_ADMIN_PASSWORD" in content


# --- Story 2: Prevent Accidental Credential Leakage in CI ---

class TestCICompatibility:
    def test_pytest_passes_without_seed_admin_env_vars(self, monkeypatch):
        """pytest suite works with users.json set to [] and no SEED_ADMIN_* env vars set — no crash or missing-credential error."""
        monkeypatch.delenv("SEED_ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("SEED_ADMIN_EMAIL", raising=False)
        monkeypatch.delenv("SEED_ADMIN_PASSWORD", raising=False)

        # Importing seed and calling seed_admin_from_env without env vars must not raise
        from seed import seed_admin_from_env as fn
        fn()  # no exception expected — early return path

    def test_no_hardcoded_admin_credentials_in_users_json(self):
        """backend/seed/users.json does not contain any username or password fields (only an empty array)."""
        users_json_path = os.path.join(os.path.dirname(__file__), "..", "seed", "users.json")
        with open(users_json_path) as f:
            data = json.load(f)
        assert data == []
        # Confirm no credential keys exist in the data
        for entry in data:
            assert "password" not in entry
            assert "username" not in entry
