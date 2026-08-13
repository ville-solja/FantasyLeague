"""Regression test: require_admin() must re-verify is_admin against the database on every
call, not trust the cached value in the session dict. Without this, a demoted admin (via the
multi-admin toggle-admin feature) keeps full destructive access — season reset, league purge,
user management — for the rest of their existing session, since request.session["is_admin"]
is only ever set at login time and never refreshed."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from deps import require_admin
from models import User
from auth import hash_password


def _make_user(db, user_id, is_admin):
    db.add(User(id=user_id, username=f"user{user_id}", email=f"user{user_id}@test.com",
                 password_hash=hash_password("secret123"), is_admin=is_admin, is_tester=False))
    db.commit()


class TestRequireAdminSessionFreshness:
    def test_admin_with_fresh_session_passes(self, db):
        _make_user(db, 1, is_admin=True)
        stale_session = {"user_id": 1, "username": "user1", "is_admin": True}

        result = require_admin(stale_session, db=db)

        assert result == stale_session

    def test_demoted_admin_with_stale_session_is_rejected(self, db):
        """The core regression case: session dict still says is_admin=True (as it would for
        an already-logged-in browser tab), but the DB row has since been demoted."""
        _make_user(db, 1, is_admin=False)
        stale_session_claiming_admin = {"user_id": 1, "username": "user1", "is_admin": True}

        with pytest.raises(HTTPException) as exc:
            require_admin(stale_session_claiming_admin, db=db)

        assert exc.value.status_code == 403

    def test_promoted_user_with_stale_non_admin_session_now_passes_immediately(self, db):
        """Symmetric case: DB says admin now, but the cached session dict passed in still says
        False. require_admin only uses the dict's user_id to look up the DB row — the stale
        is_admin value in the dict itself is never read — so the DB is authoritative in both
        directions and this now succeeds without waiting for re-login. (The frontend's Admin
        tab visibility is a separate, still session-cached concern — see GET /me / activeIsAdmin
        — but actual endpoint enforcement is immediate in both directions after this fix.)"""
        _make_user(db, 1, is_admin=True)
        stale_session_claiming_non_admin = {"user_id": 1, "username": "user1", "is_admin": False}

        result = require_admin(stale_session_claiming_non_admin, db=db)
        assert result == stale_session_claiming_non_admin

    def test_nonexistent_user_id_is_rejected(self, db):
        fake_session = {"user_id": 999, "username": "ghost", "is_admin": True}

        with pytest.raises(HTTPException) as exc:
            require_admin(fake_session, db=db)

        assert exc.value.status_code == 403
