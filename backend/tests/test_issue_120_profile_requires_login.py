"""Failing test stubs for plan-issue-120-profile-requires-login.md (resolves
GitHub issue #120).

Issue #120: `GET /profile/{user_id}` (backend/routers/profile.py::get_profile)
currently has no authentication requirement at all. Since `user_id` is a
small sequential integer, the entire user base can be scraped anonymously —
every username, linked-Twitch status, tags, and season history — with no
auth trail. The fix adds `current_user: dict = Depends(get_current_user)` to
the handler signature. This is NOT an ownership restriction: any
authenticated account can still view any other user's profile, matching the
plan's explicit "any logged-in user, not just the profile owner" acceptance
criterion — only anonymous access is closed off.

Covers Story 1 ("Require Login to View a Profile") from
markdown/plans/plan-issue-120-profile-requires-login.md. Story 2
("Documentation Reflects the New Requirement") is doc-only — updating
markdown/features/core/auth.md's "Viewing a Profile" section — and has no
backend test surface, so it is skipped here, consistent with how other
doc-only stories in this repo's plans are handled.

Test approach: TestClient over a real FastAPI app, not bare
`get_profile(...)` calls. The 401-for-no-session behavior is enforced by
FastAPI's dependency-injection layer resolving `Depends(get_current_user)`
*before* the handler body ever runs (see backend/deps.py::get_current_user,
which raises HTTPException(401) when `request.session` has no "user_id").
Calling `get_profile()` directly as a bare Python function bypasses that
DI layer entirely and can never exercise or prove the 401 path — unlike
endpoints such as routers/cards.py::get_roster, whose deeper "is this the
owner or an admin" check happens inside the function body against an
already-resolved `current_user` dict (see
test_get_roster_admin_session_freshness.py's bare-call convention). This
endpoint's auth gate needs a real session lifecycle to test meaningfully, so
this file mirrors test_issue_115_username_xss_fix.py's TestClient +
SessionMiddleware fixture pattern (same routers under test: auth + profile).

Run with: cd backend && python -m pytest tests/test_issue_120_profile_requires_login.py -v

---
IMPORTANT FOR THE DEVELOPER STAGE: backend/tests/test_issue_81_season_lifecycle.py
(around line 386, inside TestSeasonLifecycle or similar) has an EXISTING test,
`test_profile_includes_past_seasons_array`, that calls the router function
directly and bare:

    profile = get_profile(user.id, db=db)

Because the planned signature gives `current_user` a default
(`Depends(get_current_user)`), this bare call will NOT raise a TypeError
after the fix — FastAPI's `Depends(...)` sentinel object is a valid default
value in plain Python, so the call still succeeds without error. However it
silently stops exercising anything resembling real auth (current_user is
never a real session dict there), and it's a landmine if `get_profile`'s
body is ever changed to actually read from `current_user`. The developer
stage should update that call site to pass an explicit `current_user=`
dict (matching the `_current_user(user)` / session-dict convention used in
test_get_roster_admin_session_freshness.py and test_issue_51_weekly_summary.py)
so the test continues to reflect a realistic authenticated call.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from database import Base, get_db
from models import User
from auth import hash_password
from routers import auth as auth_router
from routers import profile as profile_router


# ---------------------------------------------------------------------------
# Fixtures — TestClient + SessionMiddleware, matching
# test_issue_115_username_xss_fix.py's established pattern for exercising
# routers/profile.py + routers/auth.py together through a real session.
# ---------------------------------------------------------------------------


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _make_app(engine):
    """Create a minimal FastAPI test app with the auth and profile routers."""
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    # /login carries a @limiter.limit(...) decorator bound to a shared,
    # process-wide rate_limit.limiter singleton — disable it here so this
    # file's request volume never interacts with rate-limit state left over
    # from, or shared with, other test files/runs (same reasoning as
    # test_issue_115_username_xss_fix.py::_make_app).
    import rate_limit
    rate_limit.limiter.enabled = False

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-123")
    app.include_router(auth_router.router)
    app.include_router(profile_router.router)
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.fixture()
def engine():
    return _make_engine()


@pytest.fixture()
def app(engine):
    return _make_app(engine)


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def db_session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _create_user(db, username="alice", email="alice@example.com",
                  password="secret123", tokens=5):
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        tokens=tokens,
        created_at=int(time.time()),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client, username, password="secret123"):
    resp = client.post("/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp


# ---------------------------------------------------------------------------
# Story 1 — Require Login to View a Profile
# ---------------------------------------------------------------------------

class TestRequireLoginToViewAProfile:

    def test_unauthenticated_request_returns_401(self, client, db_session):
        """GET /profile/{user_id} with no session cookie at all returns 401,
        for any user_id (including one that exists)."""
        user = _create_user(db_session, username="alice")

        resp = client.get(f"/profile/{user.id}")

        assert resp.status_code == 401

    def test_authenticated_user_can_view_any_profile_unchanged_shape(self, client, db_session):
        """Any logged-in user (not just the profile's own owner) can view
        another user's profile once authenticated, and the response shape/
        content is completely unchanged from before this fix (id, username,
        player_id, player_name, player_avatar_url, twitch_linked, tags,
        past_seasons)."""
        target = _create_user(db_session, username="bob", email="bob@example.com")
        viewer = _create_user(db_session, username="carol", email="carol@example.com")
        _login(client, viewer.username)

        resp = client.get(f"/profile/{target.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "id": target.id,
            "username": "bob",
            "player_id": None,
            "player_name": None,
            "player_avatar_url": None,
            "twitch_linked": False,
            "tags": [],
            "past_seasons": [],
        }

    def test_authenticated_request_for_nonexistent_user_returns_404(self, client, db_session):
        """An authenticated caller requesting a user_id that does not exist
        still gets 404 — the auth dependency runs before the handler body,
        so a missing user is still reported as 404, not swallowed by the
        401 path."""
        viewer = _create_user(db_session, username="dave")
        _login(client, viewer.username)

        resp = client.get("/profile/999999")

        assert resp.status_code == 404
