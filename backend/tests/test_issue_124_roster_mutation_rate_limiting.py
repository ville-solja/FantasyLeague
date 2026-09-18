"""
Tests for plan-issue-124-roster-mutation-rate-limiting.md (resolves GitHub issue #124).

A community security disclosure found that `POST /roster/{card_id}/activate`,
`/roster/{card_id}/deactivate`, `/roster/swap`, and `/roster/reorder`
(`backend/routers/cards.py`) have no rate limiting, and each mutation is
immediately followed by a frontend re-fetch of the full scored roster — rapid
toggling from even one account is a usable DoS vector on this app's
single-process, single-SQLite-file deployment. This plan reuses the shared
`slowapi` `Limiter` already built for issue #121 (`backend/rate_limit.py`),
adding a new `key_by_user_or_ip()` key function so the four roster mutation
routes are limited *per authenticated user* (session `user_id`) rather than
per IP, via a new `RATE_LIMIT_ROSTER_MUTATION` env var (default `30/minute`).

Only Story 1 ("Per-User Rate Limiting on Roster Mutations") has a backend test
surface. Story 2 ("Prevent Rapid Re-Fire from the Roster UI") is a
frontend-only in-flight guard in `frontend/app-roster.js` with no backend
behavior to assert on — skipped here, same as how a prior plan in this repo
skipped its frontend-only story.

--- Testing approach (mirrors backend/tests/test_issue_121_rate_limiting.py) ---
A `@limiter.limit(...)`-decorated route needs a real ASGI `Request` for
slowapi to key off of, so these tests use `TestClient` against a real FastAPI
app instance rather than calling router functions directly (that direct-call
style is what backend/tests/test_issue_125_roster_limit_race_fix.py uses
instead, for a different reason — see the note on stub 8 below).

Two import-order/isolation details apply here exactly as in
test_issue_121_rate_limiting.py's module docstring:

1. `RATE_LIMIT_ROSTER_MUTATION` will be captured as a module-level constant at
   import time in `routers/cards.py` (mirroring `RATE_LIMIT_LOGIN` etc. in
   `routers/auth.py`). Reloading `main` alone will not pick up a
   monkeypatched env var — `_setup_test_app` below reloads, in order:
   `rate_limit` (fresh `Limiter` instance), then `routers.cards` (re-applies
   its `@limiter.limit(...)` decorators against the fresh limiter and
   re-reads `RATE_LIMIT_ROSTER_MUTATION`), then `main`.
2. `rate_limit.limiter` is a single module-level `Limiter` instance holding
   in-memory hit counters. Reloading `rate_limit` per test gives each test
   fresh, empty counters instead of leaking accumulated hits across tests.

Run with: cd backend && python -m pytest tests/test_issue_124_roster_mutation_rate_limiting.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Shared app/client setup — same shape as test_issue_121_rate_limiting.py's
# `_setup_test_app`, but reloads `routers.cards` (not `routers.auth`) since
# that's where issue #124's `@limiter.limit(...)` decorators and
# `RATE_LIMIT_ROSTER_MUTATION` constant will live.
# ---------------------------------------------------------------------------

def _setup_test_app(monkeypatch):
    """Build a fresh `main` app against an in-memory SQLite database, with a
    fresh reload of `rate_limit` -> `routers.cards` -> `main` (in that order)
    so:

    (a) any RATE_LIMIT_ROSTER_MUTATION env var the caller monkeypatched
        *before* calling this function is actually picked up, and
    (b) each call starts from clean, empty in-memory rate-limit counters
        instead of accumulating hits left over from a previous test.

    Returns the reloaded `main` module. Callers build their own
    `TestClient(main_module.app, ...)`.
    """
    monkeypatch.setenv("AUTO_INGEST_LEAGUES", "")
    monkeypatch.setenv("DEBUG", "true")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import importlib
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

    import enrich
    import ingest
    import seed
    monkeypatch.setattr(enrich, "SessionLocal", test_session_factory)
    monkeypatch.setattr(ingest, "SessionLocal", test_session_factory)
    monkeypatch.setattr(seed, "SessionLocal", test_session_factory)

    # Reload order matters — see module docstring point 1.
    import rate_limit
    importlib.reload(rate_limit)
    import routers.cards as cards_router_module
    importlib.reload(cards_router_module)
    importlib.reload(main_module)

    main_module.engine = test_engine
    main_module.SessionLocal = test_session_factory

    return main_module


@pytest.fixture
def client(monkeypatch):
    """TestClient backed by an in-memory SQLite database, default
    RATE_LIMIT_ROSTER_MUTATION env (whatever the real implementation's
    default ends up being — expected 30/minute per the plan)."""
    main_module = _setup_test_app(monkeypatch)
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        yield c


def _register_and_login(client, username, password="secret123"):
    """Register + log in a fresh user via HTTP (mirrors how the real frontend
    authenticates), returning their user_id (queried from the DB directly,
    since /register's response body doesn't include it).

    routers/auth.py's own RATE_LIMIT_REGISTER/RATE_LIMIT_LOGIN limiter is not
    reloaded by this file's _setup_test_app (only rate_limit + routers.cards
    are — see module docstring point 1), so its @limiter.limit(...)
    decorators stay bound to whatever Limiter instance was live when
    routers.auth was first imported in this process, and its hit counts
    persist across every test in this file rather than resetting per test.
    That's irrelevant to what this file tests (roster mutation rate
    limiting, not login/register), and several tests below call this helper
    more than once, so disable that unrelated limiter here — same precedent
    as test_issue_115_username_xss_fix.py / test_issue_77_temp_password_expiry.py.
    """
    import routers.auth as auth_router_module
    auth_router_module.limiter.enabled = False

    resp = client.post("/register", json={
        "username": username,
        "email": f"{username}@example.com",
        "password": password,
    })
    assert resp.status_code == 200
    import main as main_module
    from models import User
    with main_module.SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        return user.id


def _seed_bench_cards(main_module, user_id, count, start_player_id=9000):
    """Insert `count` distinct bench (inactive) cards, each for its own
    player, directly owned by user_id — for tests that need real card_ids to
    call the roster mutation endpoints against without burning draw tokens."""
    from models import Card, Player
    card_ids = []
    with main_module.SessionLocal() as db:
        for i in range(count):
            player = Player(id=start_player_id + i, name=f"RateLimitTestPlayer{i}")
            db.add(player)
            db.flush()
            card = Card(owner_id=user_id, player_id=player.id, card_type="common",
                        league_id=None, is_active=False, generation=1)
            db.add(card)
            db.flush()
            card_ids.append(card.id)
        db.commit()
    return card_ids


# ---------------------------------------------------------------------------
# Story 1 — Per-User Rate Limiting on Roster Mutations
# ---------------------------------------------------------------------------

def test_activate_card_exceeding_rate_limit_returns_429_with_detail_shape(client):
    """POST /roster/{card_id}/activate enforces RATE_LIMIT_ROSTER_MUTATION
    (default 30/minute); exceeding it returns HTTP 429 with the established
    {"detail": "Rate limit exceeded: ..."} shape from issue #121, not a
    new/different error format."""
    _register_and_login(client, "activate_burst")
    # A nonexistent card_id still passes auth and reaches the decorated route
    # (404 from the business logic), so every call still counts as a hit
    # against the limiter regardless of the eventual response.
    for _ in range(30):
        resp = client.post("/roster/999999/activate")
        assert resp.status_code == 404

    blocked = client.post("/roster/999999/activate")
    assert blocked.status_code == 429
    body = blocked.json()
    assert "detail" in body
    assert body["detail"].startswith("Rate limit exceeded")
    assert "error" not in body


def test_deactivate_card_exceeding_rate_limit_returns_429_with_detail_shape(client):
    """POST /roster/{card_id}/deactivate enforces RATE_LIMIT_ROSTER_MUTATION
    (default 30/minute); exceeding it returns HTTP 429 with the established
    {"detail": "Rate limit exceeded: ..."} shape."""
    _register_and_login(client, "deactivate_burst")
    for _ in range(30):
        resp = client.post("/roster/999999/deactivate")
        assert resp.status_code == 404

    blocked = client.post("/roster/999999/deactivate")
    assert blocked.status_code == 429
    body = blocked.json()
    assert "detail" in body
    assert body["detail"].startswith("Rate limit exceeded")
    assert "error" not in body


def test_swap_roster_exceeding_rate_limit_returns_429_with_detail_shape(client):
    """POST /roster/swap enforces RATE_LIMIT_ROSTER_MUTATION (default
    30/minute); exceeding it returns HTTP 429 with the established
    {"detail": "Rate limit exceeded: ..."} shape."""
    _register_and_login(client, "swap_burst")
    payload = {"bench_card_id": 999998, "active_card_id": 999999, "slot_index": 0}
    for _ in range(30):
        resp = client.post("/roster/swap", json=payload)
        assert resp.status_code == 404

    blocked = client.post("/roster/swap", json=payload)
    assert blocked.status_code == 429
    body = blocked.json()
    assert "detail" in body
    assert body["detail"].startswith("Rate limit exceeded")
    assert "error" not in body


def test_reorder_roster_exceeding_rate_limit_returns_429_with_detail_shape(client):
    """POST /roster/reorder enforces RATE_LIMIT_ROSTER_MUTATION (default
    30/minute); exceeding it returns HTTP 429 with the established
    {"detail": "Rate limit exceeded: ..."} shape."""
    _register_and_login(client, "reorder_burst")
    # reorder_roster silently skips card_ids it can't find/own and still
    # returns 200 — so use a nonexistent id and rely on the hit count alone.
    payload = {"card_ids": [999999]}
    for _ in range(30):
        resp = client.post("/roster/reorder", json=payload)
        assert resp.status_code == 200

    blocked = client.post("/roster/reorder", json=payload)
    assert blocked.status_code == 429
    body = blocked.json()
    assert "detail" in body
    assert body["detail"].startswith("Rate limit exceeded")
    assert "error" not in body


def test_rate_limit_keyed_by_user_id_two_users_each_get_own_budget(client):
    """The limit is keyed by the authenticated user's session user_id, not
    source IP: two different logged-in users hitting the same roster
    mutation endpoint from the same TestClient (same source IP, since
    TestClient reports one fixed client host per instance) each get their
    own independent RATE_LIMIT_ROSTER_MUTATION budget — exhausting user A's
    budget must not 429 user B's very next request against the same
    endpoint."""
    _register_and_login(client, "user_a")
    for _ in range(30):
        resp = client.post("/roster/999999/activate")
        assert resp.status_code == 404
    blocked = client.post("/roster/999999/activate")
    assert blocked.status_code == 429

    # A second TestClient wrapping the same already-started app (same source
    # IP as `client`), logged in as a different user — mirrors
    # test_issue_121_rate_limiting.py's approach to varying identity without
    # paying extra app-startup cost.
    client_b = TestClient(client.app, raise_server_exceptions=True)
    _register_and_login(client_b, "user_b")
    resp_b = client_b.post("/roster/999999/activate")
    assert resp_b.status_code == 404  # not 429 — user B has their own budget


def test_key_by_user_or_ip_falls_back_to_remote_address_without_session_user_id():
    """key_by_user_or_ip() falls back to get_remote_address(request) when
    request.session has no user_id — the defensive fallback the plan
    describes for an unauthenticated caller. This is tested by calling
    rate_limit.key_by_user_or_ip() directly against a minimal request-like
    object with an empty session, NOT via HTTP through the four roster
    routes: those routes all also depend on Depends(get_current_user), and
    FastAPI resolves dependencies (raising 401 for no session) before the
    route's own @limiter.limit(...) decorator body runs, so this fallback
    branch is not reachable through the real endpoints in practice — the
    plan's own text calls this "should never happen given these routes
    already require login." Exercising the key function directly is the
    only way to cover this line."""
    import types
    from rate_limit import key_by_user_or_ip

    class _FakeRequest:
        session = {}
        client = types.SimpleNamespace(host="203.0.113.5")

    assert key_by_user_or_ip(_FakeRequest()) == "203.0.113.5"


def test_normal_roster_building_sequence_not_blocked_by_default_rate_limit(client):
    """A normal-paced sequence of activate/deactivate/swap calls well under
    RATE_LIMIT_ROSTER_MUTATION's default 30/minute — e.g. drawing and
    activating a handful of cards while setting up a 5-card active roster —
    is never blocked with a 429, confirming the default is generous enough
    for real usage."""
    import main as main_module

    user_id = _register_and_login(client, "normal_user")
    card_ids = _seed_bench_cards(main_module, user_id, 5)

    for cid in card_ids:
        resp = client.post(f"/roster/{cid}/activate")
        assert resp.status_code == 200

    resp = client.post(f"/roster/{card_ids[0]}/deactivate")
    assert resp.status_code == 200

    resp = client.post("/roster/reorder", json={"card_ids": card_ids[1:]})
    assert resp.status_code == 200

    resp = client.post("/roster/swap", json={
        "bench_card_id": card_ids[0],
        "active_card_id": card_ids[1],
        "slot_index": 0,
    })
    assert resp.status_code == 200


def test_issue_125_concurrent_activate_volume_does_not_trip_default_rate_limit(client):
    """Checks the interaction risk the plan's own Verification section flags:
    that RATE_LIMIT_ROSTER_MUTATION (default 30/minute) doesn't make
    test_issue_125_roster_limit_race_fix.py's concurrency tests start
    failing with 429s.

    Finding from reading test_issue_125_roster_limit_race_fix.py: its
    concurrency tests fire at most `ROSTER_LIMIT + 10` (15, with the default
    ROSTER_LIMIT=5) concurrent activate() calls for one user, and only 2
    concurrent swap_roster() calls for one user — both comfortably under a
    30/minute default budget for a single user, so the *rate-limit count*
    itself is not actually a risk and this stub's HTTP-level check (fire 15
    activate requests for one seeded-with-15-bench-cards user, assert none
    return 429) is expected to pass once implemented, not act as a redundant
    no-op.

    A separate, more serious interaction risk that is NOT a rate-limiting
    problem: test_issue_125's two concurrency tests call
    `activate_card(card_id, session, {"user_id": user_id})` and
    `swap_roster(SwapRequest(...), {"user_id": user_id}, session)` directly
    as plain Python function calls (positional args, no Request object) to
    exercise the race condition without going through TestClient/ASGI. The
    plan's Step 2 adds a new leading `request: Request` parameter to both
    functions' signatures (required by slowapi's decorator). That changes
    the functions' positional-argument order/arity, which will break
    test_issue_125's direct calls with a TypeError (wrong argument count/
    type) independent of and in addition to whatever RATE_LIMIT_ROSTER_MUTATION
    is set to — the developer implementing this plan must either keep
    `request: Request` as a keyword-only/defaulted trailing parameter, or
    update test_issue_125_roster_limit_race_fix.py's direct call sites to
    pass a request. Running the full suite (as the plan's Verification
    section already instructs) will surface this as a hard error, not a 429,
    so don't mistake a green run of this stub alone for proof that
    test_issue_125 is unaffected.

    Resolution actually implemented: `activate_card`/`swap_roster` (and
    `deactivate_card`/`reorder_roster`) keep their exact pre-existing
    signatures — no `request` param was added to them at all, so
    test_issue_125's (and test_issue_40_my_team_drag_and_drop.py's) direct
    positional calls are untouched. The `request: Request` parameter and the
    `@limiter.limit(...)` decorator live on new, separate `*_route` wrapper
    functions (`activate_card_route`, etc.) that FastAPI actually registers
    and which simply delegate to the plain functions. This stub still
    verifies the volume claim at the HTTP layer, independent of that
    resolution."""
    import main as main_module
    from routers.cards import ROSTER_LIMIT

    user_id = _register_and_login(client, "concurrent_style_user")
    num_bench = ROSTER_LIMIT + 10
    card_ids = _seed_bench_cards(main_module, user_id, num_bench)

    statuses = [client.post(f"/roster/{cid}/activate").status_code for cid in card_ids]

    assert 429 not in statuses
    assert statuses.count(200) == ROSTER_LIMIT
