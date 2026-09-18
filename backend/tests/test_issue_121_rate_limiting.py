"""
Tests for plan-issue-121-rate-limiting.md (resolves GitHub issue #121).

A community security disclosure found that no endpoint enforces any rate
limit — `POST /login` in particular can be brute-forced with unlimited
requests. This plan adds a global per-IP baseline (`slowapi`, in-memory,
applied app-wide via middleware) plus stricter per-IP limits on
`POST /login`, `POST /register`, and `POST /forgot-password`, and a separate
per-username failed-login lockout on `/login` independent of source IP.

These tests make MULTIPLE HTTP requests in a tight loop to actually trip a
rate limit, so they use `TestClient` against a real `FastAPI` app instance
rather than calling router functions directly (a decorator-wrapped
`@limiter.limit(...)` route needs a real ASGI `Request`, not a bare mock).
The plan's stated defaults (`RATE_LIMIT_LOGIN`/`RATE_LIMIT_REGISTER` =
5/minute, `RATE_LIMIT_FORGOT_PASSWORD` = 3/minute, `LOGIN_LOCKOUT_THRESHOLD`
= 10) are low enough to exceed with a handful of requests in a fast test
without any override. `RATE_LIMIT_GLOBAL`'s default (200/minute) is NOT —
tests that need to exceed the global baseline set a low
`monkeypatch.setenv("RATE_LIMIT_GLOBAL", ...)` override *before* the
app/limiter is constructed.

Two import-order/isolation details, resolved in `_setup_test_app` below:

1. `RATE_LIMIT_*`/`LOGIN_LOCKOUT_*` are captured as module-level constants at
   import time (in `rate_limit.py` and `routers/auth.py`). Reloading `main`
   alone is not enough for a monkeypatched env var to take effect — `main`
   only *plain*-imports `routers.auth` (no re-execution of its top-level
   code), and `routers.auth` only plain-imports `rate_limit`. So
   `_setup_test_app` explicitly reloads, in order: `rate_limit` (fresh
   `Limiter` instance — this also matters for isolation, see below), then
   `routers.auth` (re-applies its `@limiter.limit(...)` decorators against
   the fresh limiter and re-reads its own env vars), then `main` (re-imports
   the fresh limiter and re-(plain-)imports the already-reloaded
   `routers.auth` for its router).
2. `rate_limit.limiter` is a single module-level `Limiter` instance holding
   in-memory rate-limit counters. Without reloading `rate_limit` itself, that
   *same* instance (and its accumulated hit counts) would leak across tests
   and across test files that import `routers.auth` (e.g.
   `test_issue_77_temp_password_expiry.py`, `test_issue_115_username_xss_fix.py`).
   Reloading `rate_limit` per test gives each test a brand new `Limiter` with
   empty counters. The other two files disable the shared limiter for their
   own app fixtures (`rate_limit.limiter.enabled = False`) since their intent
   is unrelated to rate limiting and they never reload/isolate it themselves.

For simulating varying source IPs (the per-username lockout must trigger
independent of source IP): `TestClient`'s ASGI transport reports a single
fixed client host for every request by default, and slowapi's default
`get_remote_address` key function keys off `request.client.host` — it does
NOT honor `X-Forwarded-For` (that's `get_ipaddr`, which this app does not
use). So varying "source IP" here uses multiple `TestClient` instances, each
constructed with a distinct `client=(ip, port)` scope tuple, all wrapping the
*same* already-started `app` object (obtained from an existing TestClient's
`.app` attribute) so no additional lifespan/startup cost is paid per IP.

Run with: cd backend && python -m pytest tests/test_issue_121_rate_limiting.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Shared app/client setup — mirrors test_security_headers.py's `client`
# fixture (in-memory SQLite, `main` reloaded so env-driven config changes are
# picked up), extended to also reload `rate_limit` and `routers.auth` (see
# module docstring above).
# ---------------------------------------------------------------------------

def _setup_test_app(monkeypatch):
    """Build a fresh `main` app the same way test_security_headers.py's
    `client` fixture does, against an in-memory SQLite database, with a fresh
    reload of `rate_limit` -> `routers.auth` -> `main` (in that order) so:

    (a) any RATE_LIMIT_*/LOGIN_LOCKOUT_* env var the caller monkeypatched
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
    import routers.auth as auth_router_module
    importlib.reload(auth_router_module)
    importlib.reload(main_module)

    main_module.engine = test_engine
    main_module.SessionLocal = test_session_factory

    return main_module


@pytest.fixture
def client(monkeypatch):
    """TestClient backed by an in-memory SQLite database, default rate-limit
    env (whatever the real implementation's defaults end up being)."""
    main_module = _setup_test_app(monkeypatch)
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Story 1 — Global Rate Limiting Baseline
# ---------------------------------------------------------------------------

def test_global_baseline_allows_requests_under_default_limit(client):
    """A handful of GET /health requests, well under the default
    RATE_LIMIT_GLOBAL (200/minute), all succeed — the app-wide baseline must
    not block normal traffic."""
    for _ in range(5):
        resp = client.get("/health")
        assert resp.status_code == 200


# NOTE: exceeding the default 200/minute baseline directly would be slow and
# wasteful in a unit test — set a low override via
# monkeypatch.setenv("RATE_LIMIT_GLOBAL", "3/minute") before building the
# client (see module docstring re: import-time vs. call-time env reads).
def test_global_baseline_exceeded_returns_429_with_detail_shape(monkeypatch):
    """Exceeding RATE_LIMIT_GLOBAL (configured low for this test) on any
    route returns HTTP 429 with a {"detail": "..."} body — matching the
    app's existing error response shape, not slowapi's default
    {"error": "..."} shape."""
    monkeypatch.setenv("RATE_LIMIT_GLOBAL", "3/minute")
    main_module = _setup_test_app(monkeypatch)
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        for _ in range(3):
            resp = c.get("/health")
            assert resp.status_code == 200
        blocked = c.get("/health")

    assert blocked.status_code == 429
    body = blocked.json()
    assert "detail" in body
    assert body["detail"].startswith("Rate limit exceeded")
    assert "error" not in body


def test_global_baseline_applies_to_route_without_explicit_limiter_decorator(monkeypatch):
    """The baseline is registered once via middleware and applies to every
    route by default, not per-endpoint opt-in — a route with no
    @limiter.limit(...) decorator of its own (e.g. GET /health or
    GET /config) is still subject to RATE_LIMIT_GLOBAL once exceeded."""
    monkeypatch.setenv("RATE_LIMIT_GLOBAL", "2/minute")
    main_module = _setup_test_app(monkeypatch)
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        # /config has no @limiter.limit(...) decorator of its own.
        for _ in range(2):
            resp = c.get("/config")
            assert resp.status_code == 200
        blocked = c.get("/config")

    assert blocked.status_code == 429
    assert "detail" in blocked.json()


def test_docker_healthcheck_frequency_not_blocked_by_default_global_limit(client):
    """Docker's healthcheck polls GET /health every 30s; a small number of
    sequential GET /health calls under the default RATE_LIMIT_GLOBAL never
    receive a 429, confirming the default is generous enough for the
    existing healthcheck and normal frontend polling."""
    for _ in range(10):
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Story 2 — Brute-Force Protection on Login
# ---------------------------------------------------------------------------

def test_login_allows_requests_under_per_ip_limit(client):
    """A handful of POST /login attempts (fewer than the default
    RATE_LIMIT_LOGIN of 5/minute) from one client are not blocked by the
    per-IP limiter, regardless of whether the credentials are valid."""
    for _ in range(4):
        resp = client.post("/login", json={"username": "nouser", "password": "wrong"})
        # Invalid credentials (401), not rate-limited (429).
        assert resp.status_code == 401


def test_login_per_ip_limit_exceeded_returns_429(client):
    """Sending more than RATE_LIMIT_LOGIN's default 5/minute POST /login
    requests from one TestClient (one source IP) within the window returns
    HTTP 429 with a {"detail": "..."} body once the per-IP limit is
    exceeded, stricter than the global baseline."""
    statuses = []
    for _ in range(6):
        resp = client.post("/login", json={"username": "someone", "password": "wrong"})
        statuses.append(resp)
    assert [r.status_code for r in statuses[:5]] == [401] * 5
    blocked = statuses[5]
    assert blocked.status_code == 429
    body = blocked.json()
    assert "detail" in body
    assert "error" not in body


# NOTE: TestClient's ASGI transport reports a single fixed client host for
# every request by default. Since slowapi's default key_func
# (get_remote_address) keys off request.client.host and does NOT honor
# X-Forwarded-For, "varying source IPs" here uses multiple TestClient
# instances, each pinned to a distinct `client=(ip, port)` scope tuple, all
# wrapping the same already-started app (via the `client` fixture's
# `.app` attribute) so the per-IP RATE_LIMIT_LOGIN limiter never sees more
# than one request per simulated IP.
def test_login_username_lockout_triggers_independent_of_source_ip(client):
    """Repeated failed POST /login attempts against the same username, sent
    from varying source IPs so the per-IP RATE_LIMIT_LOGIN limiter never
    trips on its own, still get locked out once LOGIN_LOCKOUT_THRESHOLD
    (default 10) failed attempts accumulate within
    LOGIN_LOCKOUT_WINDOW_SECONDS (default 300) — the scenario the per-IP
    limit alone would not catch."""
    username = "ip-rotating-victim"
    statuses = []
    for i in range(11):
        ip_client = TestClient(client.app, raise_server_exceptions=True,
                                client=(f"10.1.{i}.1", 12345))
        resp = ip_client.post("/login", json={"username": username, "password": "wrong"})
        statuses.append(resp.status_code)

    # First LOGIN_LOCKOUT_THRESHOLD (10) failed attempts are ordinary
    # "invalid credentials" responses — none of them alone trips the per-IP
    # limiter since each came from a distinct simulated source IP.
    assert statuses[:10] == [401] * 10
    # The 11th attempt (still a distinct, never-before-used IP) is blocked by
    # the per-username lockout instead, proving it is independent of IP.
    assert statuses[10] == 429


def test_login_lockout_response_does_not_reveal_username_existence(client):
    """The generic message returned once a username is locked out (or a
    rate limit is otherwise hit on /login) is indistinguishable from the
    response to a login attempt against a nonexistent username — preserving
    the existing username-enumeration protection pattern already used by
    /forgot-password's timing-equalization."""
    reg = client.post("/register", json={
        "username": "reallyexists",
        "email": "real@example.com",
        "password": "secret123",
    })
    assert reg.status_code == 200

    # Exceed the default RATE_LIMIT_LOGIN (5/minute) with failed attempts
    # against a real, existing username.
    for _ in range(5):
        resp = client.post("/login", json={"username": "reallyexists", "password": "wrong"})
        assert resp.status_code == 401
    real_user_blocked = client.post("/login", json={"username": "reallyexists", "password": "wrong"})
    assert real_user_blocked.status_code == 429

    # The per-IP limiter is now tripped for this client (source IP) — a
    # login attempt against a username that has never been seen before gets
    # the exact same generic response, proving the message does not depend
    # on whether the submitted username exists.
    fake_user_blocked = client.post("/login", json={"username": "definitely-does-not-exist", "password": "wrong"})
    assert fake_user_blocked.status_code == 429
    assert fake_user_blocked.json() == real_user_blocked.json()


def test_successful_login_resets_username_failed_attempt_counter(monkeypatch):
    """After some failed POST /login attempts against a username (fewer
    than LOGIN_LOCKOUT_THRESHOLD) followed by one successful login, that
    username's failed-attempt counter is cleared — a subsequent run of up to
    LOGIN_LOCKOUT_THRESHOLD - 1 new failed attempts does not trigger
    lockout, proving the prior count did not carry over."""
    # This needs well over RATE_LIMIT_LOGIN's default 5/minute worth of
    # requests from a single source IP to exercise the lockout counter
    # itself, so raise it out of the way for this test.
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1000/minute")
    main_module = _setup_test_app(monkeypatch)
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        reg = c.post("/register", json={
            "username": "resetter",
            "email": "resetter@example.com",
            "password": "secret123",
        })
        assert reg.status_code == 200
        c.post("/logout")

        # A handful of failed attempts, fewer than LOGIN_LOCKOUT_THRESHOLD (10).
        for _ in range(7):
            resp = c.post("/login", json={"username": "resetter", "password": "wrongpass"})
            assert resp.status_code == 401

        # One successful login clears the counter.
        ok = c.post("/login", json={"username": "resetter", "password": "secret123"})
        assert ok.status_code == 200

        # A fresh run of up to LOGIN_LOCKOUT_THRESHOLD - 1 (9) new failed
        # attempts must NOT trigger lockout, proving the prior 7 did not
        # carry over.
        for _ in range(9):
            resp = c.post("/login", json={"username": "resetter", "password": "wrongpass"})
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Story 3 — Rate Limiting on Registration
# ---------------------------------------------------------------------------

def test_register_allows_requests_under_per_ip_limit(client):
    """A handful of POST /register attempts (fewer than the default
    RATE_LIMIT_REGISTER of 5/minute) from one client are not blocked by the
    per-IP limiter."""
    for i in range(4):
        resp = client.post("/register", json={
            "username": f"regsuccess{i}",
            "email": f"regsuccess{i}@example.com",
            "password": "secret123",
        })
        assert resp.status_code == 200


def test_register_per_ip_limit_exceeded_returns_429(client):
    """Sending more than RATE_LIMIT_REGISTER's default 5/minute
    POST /register requests from one TestClient within the window returns
    HTTP 429 with a {"detail": "..."} body, stricter than and independent of
    the global baseline."""
    statuses = []
    for i in range(6):
        resp = client.post("/register", json={
            "username": f"reguser{i}",
            "email": f"reguser{i}@example.com",
            "password": "secret123",
        })
        statuses.append(resp)
    assert [r.status_code for r in statuses[:5]] == [200] * 5
    blocked = statuses[5]
    assert blocked.status_code == 429
    body = blocked.json()
    assert "detail" in body
    assert "error" not in body


# ---------------------------------------------------------------------------
# Story 4 — Rate Limiting on Forgot Password
# ---------------------------------------------------------------------------

def test_forgot_password_allows_requests_under_per_ip_limit(client):
    """A handful of POST /forgot-password attempts (fewer than the default
    RATE_LIMIT_FORGOT_PASSWORD of 3/minute) from one client are not blocked
    by the per-IP limiter."""
    for _ in range(2):
        resp = client.post("/forgot-password", json={"username": "nonexistent-user"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_forgot_password_per_ip_limit_exceeded_returns_429(client):
    """Sending more than RATE_LIMIT_FORGOT_PASSWORD's default 3/minute
    POST /forgot-password requests from one TestClient within the window
    returns HTTP 429 with a {"detail": "..."} body."""
    statuses = []
    for _ in range(4):
        resp = client.post("/forgot-password", json={"username": "nonexistent-user"})
        statuses.append(resp)
    assert [r.status_code for r in statuses[:3]] == [200] * 3
    blocked = statuses[3]
    assert blocked.status_code == 429
    body = blocked.json()
    assert "detail" in body
    assert "error" not in body


def test_forgot_password_enumeration_safe_behavior_unchanged_under_limit(client):
    """Within the per-IP limit, POST /forgot-password still always returns
    {"status": "ok"} regardless of whether the submitted username exists,
    and the bcrypt timing-equalization fast-exit path is unaffected by the
    new `request: Request` parameter and @limiter.limit decorator added to
    the route."""
    resp = client.post("/forgot-password", json={"username": "still-nonexistent"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
