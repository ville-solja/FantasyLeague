"""Regression test: GET /roster/{user_id} (backend/routers/cards.py::get_roster) must
authorize cross-user access via deps.is_admin_fresh() (a DB-authoritative check), not the
session-cached current_user["is_admin"] value. Without this, a demoted admin keeps the
ability to read any other user's roster for the rest of their existing session, since
request.session["is_admin"] is only ever set at login and never refreshed — the same class
of gap test_require_admin_session_freshness.py covers for require_admin()."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from auth import hash_password
from models import User
from routers.cards import get_roster


def _make_user(db, user_id, is_admin):
    db.add(User(id=user_id, username=f"user{user_id}", email=f"user{user_id}@test.com",
                 password_hash=hash_password("secret123"), is_admin=is_admin, is_tester=False))
    db.commit()


class TestGetRosterAdminSessionFreshness:
    def test_owner_can_always_view_own_roster(self, db):
        _make_user(db, 1, is_admin=False)
        session = {"user_id": 1, "username": "user1", "is_admin": False}

        result = get_roster(1, week_id=None, db=db, current_user=session)

        assert isinstance(result, dict)

    def test_demoted_admin_with_stale_session_cannot_view_another_users_roster(self, db):
        """The core regression case: session dict still says is_admin=True (as it would for
        an already-logged-in browser tab), but the DB row has since been demoted."""
        _make_user(db, 1, is_admin=False)   # demoted in the DB
        _make_user(db, 2, is_admin=False)
        stale_session_claiming_admin = {"user_id": 1, "username": "user1", "is_admin": True}

        with pytest.raises(HTTPException) as exc:
            get_roster(2, week_id=None, db=db, current_user=stale_session_claiming_admin)

        assert exc.value.status_code == 403

    def test_current_admin_can_view_another_users_roster(self, db):
        _make_user(db, 1, is_admin=True)
        _make_user(db, 2, is_admin=False)
        session = {"user_id": 1, "username": "user1", "is_admin": True}

        result = get_roster(2, week_id=None, db=db, current_user=session)

        assert isinstance(result, dict)

    def test_non_admin_cannot_view_another_users_roster(self, db):
        _make_user(db, 1, is_admin=False)
        _make_user(db, 2, is_admin=False)
        session = {"user_id": 1, "username": "user1", "is_admin": False}

        with pytest.raises(HTTPException) as exc:
            get_roster(2, week_id=None, db=db, current_user=session)

        assert exc.value.status_code == 403
