"""
Tests for plan-issue-184-action-throttling.md (resolves GitHub issue #184).

Per-user and per-IP limits on every player write route (card draws, booster
draws and rerolls share RATE_LIMIT_CARD_ACTION / RATE_LIMIT_CARD_ACTION_IP;
profile, weekly-summary, session, claim and Twitch/Steam account routes get
RATE_LIMIT_USER_ACTION; /simulate gets RATE_LIMIT_SIMULATE; /twitch/mvp gets
RATE_LIMIT_TWITCH_JOIN_IP), a route coverage test, a request body size cap
(MAX_REQUEST_BODY_BYTES -> 413), and a plain 429 message with Retry-After and
a privacy-safe log line. One class per user story, one stub per acceptance
criterion plus the failure path. The "Operator Guidance" story is
documentation-only; its stubs check the doc text.

Developer notes
---------------

  How the existing rate-limit tests set small limits and reset storage
    - test_issue_121_rate_limiting.py / test_issue_124_roster_mutation_rate_limiting.py:
      `_setup_test_app(monkeypatch)` sets the RATE_LIMIT_* env vars with
      `monkeypatch.setenv(...)` BEFORE building the app, swaps `database.engine`
      / `SessionLocal` (and enrich/ingest/seed SessionLocal) for an in-memory
      `StaticPool` engine with `check_same_thread=False`, then reloads in
      order: `rate_limit` (fresh Limiter, fresh in-memory counters, re-reads
      the constants) -> the router module(s) holding the decorators (here:
      routers.cards, routers.profile, routers.weekly_summary, routers.auth,
      routers.leaderboard, twitch_oauth, steam_openid as needed) -> `main`.
      Limits are module-level constants read at import, so a reload is the
      only way to pick up a monkeypatched value.
    - A module that is NOT reloaded keeps decorators bound to an older Limiter
      instance (lessons-learned 2026-10-06). For routes in such modules (e.g.
      `twitch.py`, POST /twitch/mvp), build a small FastAPI app with that
      router, set `app.state.limiter = <module>.limiter`, and call
      `<module>.limiter.reset()` before and after, saving/restoring
      `<module>.limiter.enabled` in a try/finally (pattern:
      test_issue_171 `test_heartbeat_rate_limited_per_viewer`, which also uses
      `limits.parse(...).amount` to read the configured limit).
    - Unrelated limiters (login/register) can be switched off per test with
      `routers.auth.limiter.enabled = False` (see `_register_and_login` in
      test_issue_124), restoring afterwards.
    - "Route declares limit X" checks can use `inspect.getsource` + a decorator
      regex (test_issue_171 `test_heartbeat_route_declares_per_viewer_and_per_ip_limits`)
      or slowapi's `limiter._route_limits` keyed by the endpoint's qualified
      name (plan Step 3). Note lessons-learned 2026-10-08: newer FastAPI may wrap
      included routers in `app.routes`; walk nested routes or fall back to the
      router modules' own `router.routes` when listing APIRoutes.

  Existing tests to update (plan Step 5)
    - test_issue_121_rate_limiting.py and test_issue_124_roster_mutation_rate_limiting.py
      assert `detail.startswith("Rate limit exceeded")`; change them to the new
      text "Too many requests. Wait a moment and try again.".
    - Bump test_issue_85_split_admin_router.py's suite-size baseline from the
      actual "N passed" output (lessons-learned 2026-10-11).

  Card-action tests
    - Use `/register` + login via TestClient to get session cookies; give the
      user tokens directly in the DB and seed players/teams so draws succeed,
      then compare token balance and Card count before/after the refused call.
    - `key_by_user_or_ip` needs `get_current_user` resolved first (it sets
      `request.state.session_user_id`), so the dependency stays on the route.

Run with: cd backend && python -m pytest tests/test_issue_184_action_throttling.py -v
"""

import importlib
import importlib.util
import os
import re
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from limits import parse
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registers every table before the conftest db fixture runs)

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_REPO = os.path.dirname(_BACKEND)
THROTTLE_MESSAGE = "Too many requests. Wait a moment and try again."
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Routes that keep only the global baseline on purpose.
ALLOWED_GLOBAL_ONLY = {
    # Needs no login and deletes at most one session row; a limit could keep a
    # player signed in on a shared computer.
    ("POST", "/logout"),
    # main.py's catch-alls only answer 404 for unknown /twitch/* and /auth/steam/*
    # paths (issues #160, #150); they touch no data.
    *{(m, "/twitch/{rest:path}") for m in _WRITE_METHODS},
    *{(m, "/auth/steam/{rest:path}") for m in _WRITE_METHODS},
}

# Modules holding the decorators these tests reconfigure through env vars.
_RELOADED_ROUTERS = ("routers.auth", "routers.cards", "routers.profile",
                     "routers.weekly_summary", "routers.leaderboard")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_test_app(monkeypatch, **env):
    """Fresh `main` on an in-memory database, with `rate_limit`, the routers above and
    `main` reloaded so the env limits apply and the counters start empty."""
    monkeypatch.setenv("AUTO_INGEST_LEAGUES", "")
    monkeypatch.setenv("DEBUG", "true")
    # Registration and login are not under test; keep their limits out of the way.
    monkeypatch.setenv("RATE_LIMIT_REGISTER", "1000/minute")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1000/minute")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database
    import enrich
    import ingest
    import seed

    test_engine = create_engine("sqlite:///:memory:",
                                connect_args={"check_same_thread": False},
                                poolclass=StaticPool)
    factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    for module in (enrich, ingest, seed):
        monkeypatch.setattr(module, "SessionLocal", factory)

    import rate_limit
    importlib.reload(rate_limit)
    for name in _RELOADED_ROUTERS:
        importlib.reload(importlib.import_module(name))
    import main as main_module
    importlib.reload(main_module)
    main_module.engine = test_engine
    main_module.SessionLocal = factory
    return main_module


@contextmanager
def _app(monkeypatch, **env):
    main_module = _setup_test_app(monkeypatch, **env)
    with TestClient(main_module.app, raise_server_exceptions=True) as client:
        yield main_module, client


def _register(main_module, client, username):
    """Register (which signs the client in) and return the new user's id."""
    resp = client.post("/register", json={"username": username,
                                          "email": f"{username}@example.com",
                                          "password": "secret123"})
    assert resp.status_code == 200, resp.text
    from models import User
    with main_module.SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def _second_client(main_module, username):
    client = TestClient(main_module.app, raise_server_exceptions=True)
    return client, _register(main_module, client, username)


def _set_tokens(main_module, user_id, tokens):
    from models import User
    with main_module.SessionLocal() as db:
        db.get(User, user_id).tokens = tokens
        db.commit()


def _tokens_and_cards(main_module, user_id):
    from models import Card, User
    with main_module.SessionLocal() as db:
        return (db.get(User, user_id).tokens,
                db.query(Card).filter(Card.owner_id == user_id).count())


def _seed_drawable(main_module, team_id=7):
    """Players for plain draws, plus one team with match stats for booster draws."""
    from models import League, Match, Player, PlayerMatchStats, Team
    with main_module.SessionLocal() as db:
        db.add(League(id=1, name="TestLeague"))
        db.add(Team(id=team_id, name="Booster Team"))
        for pid in range(500, 510):
            db.add(Player(id=pid, name=f"Throttle{pid}"))
        db.flush()
        db.add(Match(match_id=4242, radiant_team_id=team_id, dire_team_id=team_id + 100,
                     league_id=1, start_time=0, radiant_win=True))
        db.flush()
        for pid in range(500, 505):
            db.add(PlayerMatchStats(player_id=pid, match_id=4242, team_id=team_id,
                                    fantasy_points=0.0))
        db.commit()


def _api_routes(routes, prefix=""):
    """Every APIRoute with its full path. Newer FastAPI wraps included routers in
    `_IncludedRouter` objects (lessons-learned 2026-10-08), so walk into them."""
    from fastapi.routing import APIRoute
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif getattr(route, "original_router", None) is not None:
            context = getattr(route, "include_context", None)
            extra = getattr(context, "prefix", "") or ""
            yield from _api_routes(route.original_router.routes, prefix + extra)
        elif getattr(route, "routes", None) is not None and not hasattr(route, "app"):
            yield from _api_routes(route.routes, prefix)


def _dependency_names(dependant):
    for dep in dependant.dependencies:
        yield getattr(dep.call, "__name__", "")
        yield from _dependency_names(dep)


def _is_admin_route(path, route):
    return path.startswith("/admin") or "require_admin" in set(_dependency_names(route.dependant))


def _route_limits(endpoint):
    """The slowapi limits registered for an endpoint, from any Limiter in its module."""
    from slowapi import Limiter
    module = sys.modules.get(endpoint.__module__)
    name = f"{endpoint.__module__}.{endpoint.__name__}"
    found = []
    for value in vars(module).values() if module else ():
        if isinstance(value, Limiter):
            found.extend(value._route_limits.get(name, []))
            found.extend(value._dynamic_route_limits.get(name, []))
    return found


def _unlimited_write_routes(routes, allowed=ALLOWED_GLOBAL_ONLY):
    """(method, path) of every non-admin write route with no route-level limit."""
    missing = []
    for path, route in _api_routes(routes):
        if _is_admin_route(path, route):
            continue
        for method in sorted(route.methods & _WRITE_METHODS):
            if (method, path) in allowed:
                continue
            if not _route_limits(route.endpoint):
                missing.append((method, path))
    return missing


def _find_route(method, path):
    import main
    for full_path, route in _api_routes(main.app.routes):
        if full_path == path and method in route.methods:
            return route
    raise AssertionError(f"{method} {path} is not registered")


def _limit_amount(value):
    return parse(value).amount, parse(value).get_expiry()


def _limit_shape(lim):
    return lim.limit.amount, lim.limit.get_expiry()


def _fresh_rate_limit_module():
    """Execute rate_limit.py as a separate module so the shared `rate_limit` (and the
    Limiter every router is bound to) is left alone."""
    spec = importlib.util.spec_from_file_location("_rate_limit_defaults",
                                                  os.path.join(_BACKEND, "rate_limit.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(rel_path):
    with open(os.path.join(_REPO, rel_path), encoding="utf-8") as fh:
        return fh.read()


def _layered_section():
    doc = _read("markdown/features/reference/rate-limiting.md")
    m = re.search(r"^## Layered protection\n(.*?)(?=^## |\Z)", doc, re.M | re.S)
    assert m, "rate-limiting.md has no '## Layered protection' section"
    return m.group(1)


def _app_records(caplog):
    return [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]


# ---------------------------------------------------------------------------
# Story 1 — Throttle Card Actions per Player
# ---------------------------------------------------------------------------

class TestThrottleCardActionsPerPlayer:

    def test_card_action_limit_constants_have_defaults(self, monkeypatch):
        """AC: RATE_LIMIT_CARD_ACTION defaults to 20/minute and RATE_LIMIT_CARD_ACTION_IP to 60/minute, defined in backend/rate_limit.py."""
        monkeypatch.delenv("RATE_LIMIT_CARD_ACTION", raising=False)
        monkeypatch.delenv("RATE_LIMIT_CARD_ACTION_IP", raising=False)
        module = _fresh_rate_limit_module()
        assert module.RATE_LIMIT_CARD_ACTION == "20/minute"
        assert module.RATE_LIMIT_CARD_ACTION_IP == "60/minute"
        monkeypatch.setenv("RATE_LIMIT_CARD_ACTION", "7/minute")
        assert _fresh_rate_limit_module().RATE_LIMIT_CARD_ACTION == "7/minute"

    def test_card_action_routes_declare_per_user_and_per_ip_limits(self):
        """AC: POST /draw, /draw/booster/{team_id} and /roster/{card_id}/reroll carry @limiter.limit(RATE_LIMIT_CARD_ACTION, key_func=key_by_user_or_ip) and @limiter.limit(RATE_LIMIT_CARD_ACTION_IP)."""
        import rate_limit
        for path in ("/draw", "/draw/booster/{team_id}", "/roster/{card_id}/reroll"):
            limits = _route_limits(_find_route("POST", path).endpoint)
            per_user = [l for l in limits if l.key_func.__name__ == "key_by_user_or_ip"]
            per_ip = [l for l in limits if l.key_func.__name__ == "get_remote_address"]
            assert len(per_user) == 1 and len(per_ip) == 1, path
            assert _limit_shape(per_user[0]) == _limit_amount(rate_limit.RATE_LIMIT_CARD_ACTION)
            assert _limit_shape(per_ip[0]) == _limit_amount(rate_limit.RATE_LIMIT_CARD_ACTION_IP)
            # Shared scopes: the three actions draw from one budget.
            assert per_user[0].scope == "card_action" and per_ip[0].scope == "card_action_ip"

    def test_draw_exceeding_per_user_limit_returns_429(self, monkeypatch):
        """AC: the N+1th card action from one account within a minute gets 429 (small RATE_LIMIT_CARD_ACTION set via env)."""
        with _app(monkeypatch, RATE_LIMIT_CARD_ACTION="3/minute") as (main_module, client):
            _register(main_module, client, "drawburst")
            statuses = [client.post("/draw").status_code for _ in range(4)]
        assert 429 not in statuses[:3]
        assert statuses[3] == 429

    def test_card_actions_share_one_per_user_budget(self, monkeypatch):
        """AC: draw, booster draw and reroll share the per-user limit: mixing them still trips 429 after N total calls."""
        with _app(monkeypatch, RATE_LIMIT_CARD_ACTION="3/minute") as (main_module, client):
            _register(main_module, client, "mixer")
            first = [client.post("/draw").status_code,
                     client.post("/draw/booster/999").status_code,
                     client.post("/roster/999999/reroll").status_code]
            assert 429 not in first
            assert client.post("/draw/booster/999").status_code == 429
            assert client.post("/roster/999999/reroll").status_code == 429
            assert client.post("/draw").status_code == 429

    def test_draw_limit_does_not_affect_other_accounts(self, monkeypatch):
        """AC: after one account is throttled, a second account (different session) can still draw."""
        with _app(monkeypatch, RATE_LIMIT_CARD_ACTION="2/minute") as (main_module, client):
            _seed_drawable(main_module)
            _register(main_module, client, "throttled")
            for _ in range(2):
                client.post("/draw")
            assert client.post("/draw").status_code == 429
            other, _ = _second_client(main_module, "unaffected")
            assert other.post("/draw").status_code == 200

    def test_card_action_per_ip_limit_holds_across_accounts(self, monkeypatch):
        """AC: RATE_LIMIT_CARD_ACTION_IP caps the total across many accounts behind one address."""
        with _app(monkeypatch, RATE_LIMIT_CARD_ACTION="10/minute",
                  RATE_LIMIT_CARD_ACTION_IP="4/minute") as (main_module, client):
            _register(main_module, client, "ipuser1")
            other, _ = _second_client(main_module, "ipuser2")
            assert [client.post("/draw").status_code for _ in range(2)].count(429) == 0
            assert [other.post("/draw").status_code for _ in range(2)].count(429) == 0
            # Both accounts are far under their own budget; the shared address is not.
            assert other.post("/draw").status_code == 429
            assert client.post("/roster/1/reroll").status_code == 429

    def test_refused_draw_spends_no_tokens_and_creates_no_card(self, monkeypatch):
        """Failure path: a 429-refused draw leaves the token balance and the user's Card count unchanged."""
        with _app(monkeypatch, RATE_LIMIT_CARD_ACTION="1/minute") as (main_module, client):
            _seed_drawable(main_module)
            user_id = _register(main_module, client, "nospend")
            _set_tokens(main_module, user_id, 5)
            assert client.post("/draw").status_code == 200
            before = _tokens_and_cards(main_module, user_id)
            assert before == (4, 1)
            assert client.post("/draw").status_code == 429
            assert _tokens_and_cards(main_module, user_id) == before

    def test_refused_booster_draw_spends_no_tokens_and_creates_no_card(self, monkeypatch):
        """Failure path: a 429-refused booster draw leaves the token balance and the user's Card count unchanged."""
        with _app(monkeypatch, RATE_LIMIT_CARD_ACTION="1/minute") as (main_module, client):
            _seed_drawable(main_module, team_id=7)
            user_id = _register(main_module, client, "nospendboost")
            _set_tokens(main_module, user_id, 10)
            assert client.post("/draw/booster/7").status_code == 200
            before = _tokens_and_cards(main_module, user_id)
            assert before[1] == 1 and before[0] < 10
            assert client.post("/draw/booster/7").status_code == 429
            assert _tokens_and_cards(main_module, user_id) == before

    def test_draw_card_direct_call_unchanged(self, db):
        """AC (Step 2): the plain draw_card(db, current_user) function still works when called directly, without a Request."""
        from models import Card, Player, User
        from routers.cards import draw_card
        user = User(username="direct", email="direct@example.com", password_hash="x",
                    tokens=2, is_admin=False)
        db.add(user)
        db.add(Player(id=77, name="DirectPlayer"))
        db.commit()
        result = draw_card(db, {"user_id": user.id})
        assert result["player_id"] == 77
        assert result["tokens"] == 1
        assert db.query(Card).filter(Card.owner_id == user.id).count() == 1


# ---------------------------------------------------------------------------
# Story 2 — Every Player Action Has a Limit
# ---------------------------------------------------------------------------

class TestEveryPlayerActionHasALimit:

    def test_user_action_limit_constant_defaults_to_60_per_minute(self, monkeypatch):
        """AC: RATE_LIMIT_USER_ACTION defaults to 60/minute and RATE_LIMIT_SIMULATE to 20/minute, defined in backend/rate_limit.py."""
        monkeypatch.delenv("RATE_LIMIT_USER_ACTION", raising=False)
        monkeypatch.delenv("RATE_LIMIT_SIMULATE", raising=False)
        module = _fresh_rate_limit_module()
        assert module.RATE_LIMIT_USER_ACTION == "60/minute"
        assert module.RATE_LIMIT_SIMULATE == "20/minute"

    @pytest.mark.parametrize("method,path", [
        ("PUT", "/profile/username"),
        # PUT /profile/player-id was removed by issue #209.
        ("PUT", "/profile/password"),
        ("POST", "/weekly-summary/{week_id}/reveal"),
        ("POST", "/weekly-summary/reveal-all"),
        ("POST", "/weekly-summary/seen"),
        ("POST", "/weekly-summary/prompted"),
        ("POST", "/claim-events"),
        ("POST", "/notifications/{notification_id}/dismiss"),
        ("DELETE", "/sessions/{session_id}"),
        ("POST", "/logout-everywhere"),
        ("POST", "/twitch/merge/confirm"),
        ("POST", "/twitch/disconnect"),
        ("POST", "/profile/steam/unlink"),
    ])
    def test_player_route_declares_user_action_limit(self, method, path):
        """AC: each listed player route carries a per-user RATE_LIMIT_USER_ACTION limit keyed by key_by_user_or_ip."""
        import rate_limit
        limits = _route_limits(_find_route(method, path).endpoint)
        per_user = [l for l in limits if l.key_func.__name__ == "key_by_user_or_ip"]
        assert per_user, f"{method} {path} has no per-user limit"
        assert _limit_shape(per_user[0]) == _limit_amount(rate_limit.RATE_LIMIT_USER_ACTION)

    def test_user_action_route_exceeding_limit_returns_429(self, monkeypatch):
        """AC: with a small RATE_LIMIT_USER_ACTION, the N+1th call to e.g. POST /weekly-summary/seen from one account gets 429."""
        with _app(monkeypatch, RATE_LIMIT_USER_ACTION="3/minute") as (main_module, client):
            _register(main_module, client, "seenburst")
            statuses = [client.post("/weekly-summary/seen").status_code for _ in range(4)]
        assert statuses == [200, 200, 200, 429]

    def test_user_action_limit_does_not_affect_other_accounts(self, monkeypatch):
        """AC: per-user keying: a second account on the same IP is unaffected when the first is throttled."""
        with _app(monkeypatch, RATE_LIMIT_USER_ACTION="2/minute") as (main_module, client):
            _register(main_module, client, "seenone")
            for _ in range(2):
                assert client.post("/weekly-summary/seen").status_code == 200
            assert client.post("/weekly-summary/seen").status_code == 429
            other, _ = _second_client(main_module, "seentwo")
            assert other.post("/weekly-summary/seen").status_code == 200

    def test_simulate_exceeding_per_ip_limit_returns_429(self, monkeypatch):
        """AC: POST /simulate/{match_id} gets 429 past RATE_LIMIT_SIMULATE from one IP."""
        with _app(monkeypatch, RATE_LIMIT_SIMULATE="2/minute") as (main_module, client):
            statuses = [client.post("/simulate/123", json={}).status_code for _ in range(3)]
        assert 429 not in statuses[:2]
        assert statuses[2] == 429

    def test_twitch_mvp_declares_per_ip_limit(self):
        """AC: POST /twitch/mvp carries @limiter.limit(RATE_LIMIT_TWITCH_JOIN_IP)."""
        import twitch
        limits = _route_limits(_find_route("POST", "/twitch/mvp").endpoint)
        per_ip = [l for l in limits if l.key_func.__name__ == "get_remote_address"]
        assert per_ip
        assert _limit_shape(per_ip[0]) == _limit_amount(twitch.RATE_LIMIT_TWITCH_JOIN_IP)

    def test_every_non_admin_write_route_has_explicit_limit(self):
        """AC: every non-admin POST/PUT/PATCH/DELETE route has a route-level @limiter.limit or is in ALLOWED_GLOBAL_ONLY = {("POST", "/logout")}."""
        import main
        assert _unlimited_write_routes(main.app.routes) == []
        # The allowlist entries are real routes (a stale entry would hide nothing).
        assert _find_route("POST", "/logout")

    def test_route_coverage_check_flags_undecorated_write_route(self):
        """Failure path: the coverage check reports a newly added non-admin write route that has no @limiter.limit and is not allowlisted."""
        from fastapi import APIRouter, Depends
        from deps import require_admin

        router = APIRouter()

        @router.post("/brand-new-action")
        def brand_new_action():
            return {"ok": True}

        @router.put("/another/{thing_id}")
        def another_action(thing_id: int):
            return {"ok": True}

        @router.post("/admin-ish", dependencies=[Depends(require_admin)])
        def admin_only_action():
            return {"ok": True}

        @router.post("/logout")
        def logout():
            return {"ok": True}

        @router.get("/read-only")
        def read_only():
            return {"ok": True}

        assert _unlimited_write_routes(router.routes) == [
            ("POST", "/brand-new-action"), ("PUT", "/another/{thing_id}")]

    def test_route_coverage_check_skips_admin_guarded_routes(self):
        """AC: admin routes (/admin/* and require_admin-guarded routes such as /grant-tokens, /codes, /ingest, /recalculate, /audit-logs) stay on the global baseline and are skipped."""
        import main
        checked = 0
        for method, path in [("POST", "/grant-tokens"), ("POST", "/codes"),
                             ("POST", "/ingest/league/{league_id}"), ("POST", "/recalculate"),
                             ("POST", "/admin/weeks")]:
            route = _find_route(method, path)
            assert _is_admin_route(path, route), path
            assert _route_limits(route.endpoint) == [], f"{path} should stay on the baseline"
            checked += 1
        audit = [(p, r) for p, r in _api_routes(main.app.routes) if p.startswith("/audit-logs")]
        for path, route in audit:
            assert _is_admin_route(path, route)
        assert checked == 5


# ---------------------------------------------------------------------------
# Story 3 — Oversized Requests Refused Early
# ---------------------------------------------------------------------------

class TestOversizedRequestsRefusedEarly:

    def test_oversized_content_length_returns_413_without_running_route(self, monkeypatch):
        """AC: a request with Content-Length above MAX_REQUEST_BODY_BYTES gets 413 {"detail": "Request too large"} and the route does not run."""
        with _app(monkeypatch) as (main_module, client):
            user_id = _register(main_module, client, "bigbody")
            monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 200)
            resp = client.put("/profile/username",
                              json={"username": "renamed", "padding": "x" * 500})
            assert resp.status_code == 413
            assert resp.json() == {"detail": "Request too large"}
            from models import User
            with main_module.SessionLocal() as db:
                assert db.get(User, user_id).username == "bigbody"

    def test_oversized_chunked_body_returns_413(self, monkeypatch):
        """AC: a chunked request without Content-Length is cut off with 413 once its body passes the cap."""
        with _app(monkeypatch) as (main_module, client):
            user_id = _register(main_module, client, "chunked")
            monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 200)

            def chunks():
                yield b'{"username": "renamed", "padding": "'
                for _ in range(20):
                    yield b"x" * 50
                yield b'"}'

            resp = client.put("/profile/username", content=chunks(),
                              headers={"Content-Type": "application/json"})
            assert resp.status_code == 413
            assert resp.json() == {"detail": "Request too large"}
            from models import User
            with main_module.SessionLocal() as db:
                assert db.get(User, user_id).username == "chunked"

    def test_body_at_or_under_cap_passes(self, monkeypatch):
        """AC: a normal-sized JSON body (e.g. PUT /profile/username) still reaches the route and succeeds."""
        monkeypatch.delenv("MAX_REQUEST_BODY_BYTES", raising=False)
        with _app(monkeypatch) as (main_module, client):
            _register(main_module, client, "smallbody")
            assert main_module.MAX_REQUEST_BODY_BYTES == 65536
            resp = client.put("/profile/username", json={"username": "smallbody2"})
            assert resp.status_code == 200, resp.text
            assert resp.json()["username"] == "smallbody2"

            def chunks():
                yield b'{"username": '
                yield b'"smallbody3"}'

            resp = client.put("/profile/username", content=chunks(),
                              headers={"Content-Type": "application/json"})
            # Under the cap, a chunked body is replayed whole to the route (the
            # rename cooldown answering is proof it arrived and parsed).
            assert resp.status_code in (200, 429), resp.text
            assert resp.status_code != 413

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_safe_methods_unaffected_by_size_cap(self, method, monkeypatch):
        """AC: GET, HEAD and OPTIONS requests are not refused by the body size cap."""
        with _app(monkeypatch) as (main_module, client):
            monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 1)
            resp = client.request(method, "/health", content=b"x" * 1000,
                                  headers={"Content-Length": "1000"})
            assert resp.status_code != 413
            if method == "GET":
                assert resp.status_code == 200

    def test_max_request_body_bytes_defaults_to_65536(self, monkeypatch):
        """AC: MAX_REQUEST_BODY_BYTES defaults to 65536 when unset."""
        import main
        monkeypatch.delenv("MAX_REQUEST_BODY_BYTES", raising=False)
        assert main._read_max_request_body_bytes() == 65536
        monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "1024")
        assert main._read_max_request_body_bytes() == 1024

    def test_invalid_max_request_body_bytes_falls_back_to_default(self, monkeypatch):
        """Failure path: a non-numeric MAX_REQUEST_BODY_BYTES falls back to 65536 instead of crashing at import."""
        import main
        for bad in ("lots", "", "-5", "0", "64k"):
            monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", bad)
            assert main._read_max_request_body_bytes() == 65536, bad
        monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "not-a-number")
        main_module = _setup_test_app(monkeypatch)
        assert main_module.MAX_REQUEST_BODY_BYTES == 65536


# ---------------------------------------------------------------------------
# Story 4 — Clear Throttle Responses
# ---------------------------------------------------------------------------

class TestClearThrottleResponses:

    def test_429_body_has_plain_message(self, monkeypatch):
        """AC: 429 responses carry {"detail": "Too many requests. Wait a moment and try again."}."""
        with _app(monkeypatch, RATE_LIMIT_USER_ACTION="1/minute",
                  RATE_LIMIT_GLOBAL="3/minute") as (main_module, client):
            _register(main_module, client, "plainmsg")
            client.post("/weekly-summary/seen")
            route_level = client.post("/weekly-summary/seen")
            assert route_level.status_code == 429
            assert route_level.json() == {"detail": THROTTLE_MESSAGE}
            # The global baseline (middleware path) answers the same way.
            statuses = [client.get("/health") for _ in range(4)]
            assert statuses[-1].status_code == 429
            assert statuses[-1].json() == {"detail": THROTTLE_MESSAGE}

    def test_429_has_retry_after_header_in_seconds(self, monkeypatch):
        """AC: 429 responses carry a Retry-After header with a positive integer number of seconds from the limit's window."""
        with _app(monkeypatch, RATE_LIMIT_USER_ACTION="1/minute",
                  RATE_LIMIT_SIMULATE="1/hour") as (main_module, client):
            _register(main_module, client, "retryafter")
            client.post("/weekly-summary/seen")
            blocked = client.post("/weekly-summary/seen")
            assert blocked.status_code == 429
            assert blocked.headers["Retry-After"] == "60"
            client.post("/simulate/1", json={})
            blocked = client.post("/simulate/1", json={})
            assert blocked.status_code == 429
            assert blocked.headers["Retry-After"] == "3600"

    def test_throttled_request_logs_one_info_line_with_route_and_key_kind(self, monkeypatch, caplog):
        """AC: a refused request logs one INFO line "Rate limited: <METHOD> <route template> (<user|ip|twitch>)"."""
        with _app(monkeypatch, RATE_LIMIT_CARD_ACTION="1/minute",
                  RATE_LIMIT_SIMULATE="1/minute") as (main_module, client):
            _register(main_module, client, "logline")
            client.post("/roster/12345/reroll")
            client.post("/simulate/9", json={})
            caplog.clear()
            with caplog.at_level("INFO"):
                assert client.post("/roster/12345/reroll").status_code == 429
                assert client.post("/simulate/9", json={}).status_code == 429
        lines = [r for r in _app_records(caplog) if r.getMessage().startswith("Rate limited:")]
        assert [(r.levelname, r.getMessage()) for r in lines] == [
            ("INFO", "Rate limited: POST /roster/{card_id}/reroll (user)"),
            ("INFO", "Rate limited: POST /simulate/{match_id} (ip)"),
        ]

    def test_throttle_log_line_contains_no_ip_or_user_id(self, monkeypatch, caplog):
        """Failure path: the throttle log line never contains the client IP or the user id (ignore httpx/httpcore records)."""
        with _app(monkeypatch, RATE_LIMIT_USER_ACTION="1/minute",
                  RATE_LIMIT_GLOBAL="2/minute") as (main_module, client):
            user_id = _register(main_module, client, "privacy")
            client.post("/weekly-summary/seen")
            caplog.clear()
            with caplog.at_level("DEBUG"):
                assert client.post("/weekly-summary/seen").status_code == 429
                for _ in range(3):
                    client.get("/health")
        records = _app_records(caplog)
        assert any(r.getMessage().startswith("Rate limited:") for r in records)
        for record in records:
            message = record.getMessage()
            assert "testclient" not in message  # TestClient's client address
            assert f"user:{user_id}" not in message
            if message.startswith("Rate limited:"):
                assert re.fullmatch(r"Rate limited: [A-Z]+ \S+ \((user|ip|twitch)\)", message)

    def test_throttle_log_emitted_at_most_once_per_key_and_route_per_minute(self, monkeypatch, caplog):
        """AC: repeated refusals for the same key and route within a minute log only one line."""
        with _app(monkeypatch, RATE_LIMIT_USER_ACTION="1/minute") as (main_module, client):
            _register(main_module, client, "dedupone")
            other, _ = _second_client(main_module, "deduptwo")
            client.post("/weekly-summary/seen")
            other.post("/weekly-summary/seen")
            client.post("/weekly-summary/prompted")
            caplog.clear()
            with caplog.at_level("INFO"):
                for _ in range(4):
                    assert client.post("/weekly-summary/seen").status_code == 429
                assert client.post("/weekly-summary/prompted").status_code == 429
                assert other.post("/weekly-summary/seen").status_code == 429
        lines = [r.getMessage() for r in _app_records(caplog)
                 if r.getMessage().startswith("Rate limited:")]
        # One per (key, route): user one on two routes, user two on one.
        assert lines == ["Rate limited: POST /weekly-summary/seen (user)",
                         "Rate limited: POST /weekly-summary/prompted (user)",
                         "Rate limited: POST /weekly-summary/seen (user)"]

    def test_frontend_card_and_roster_actions_show_429_detail(self):
        """AC: draw, booster, reroll and roster handlers in frontend/app-cards.js and app-roster.js show data.detail on a non-OK response via setStatus (textContent)."""
        cards = _read("frontend/app-cards.js")
        roster = _read("frontend/app-roster.js")

        def body(src, name):
            m = re.search(r"async function " + re.escape(name) + r"\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
            assert m, name
            return m.group(1)

        assert 'setStatus("deckStatus", data.detail, false)' in body(cards, "drawCard")
        assert 'setStatus("deckStatus", data.detail, false)' in body(cards, "_drawBoosterForTeam")
        assert "statusEl.textContent = data.detail" in body(cards, "confirmReroll")
        # Issue #186: roster changes are saved by PUT /roster. A refused save shows
        # the server's detail; a 429 (or other unexpected answer) shows it with Retry.
        start = roster.index("function _runRosterSave(")
        save = roster[start:roster.index("\n}\n", start)]
        assert "_reloadRosterAfterRefusal(_detailText(data.detail) || \"Couldn't save.\")" in save
        assert "_rosterSaveFailed(_detailText(data.detail));" in save
        start = roster.index("function _setRosterStatus(")
        assert "el.textContent = msg;" in roster[start:roster.index("\n}\n", start)]
        for src in (cards, roster):
            assert not re.search(r"innerHTML\s*=\s*[^;]*\.detail", src)


# ---------------------------------------------------------------------------
# Story 5 — Operator Guidance Against Denial of Service
# ---------------------------------------------------------------------------

class TestOperatorGuidanceAgainstDenialOfService:

    def test_rate_limiting_doc_has_layered_protection_section(self):
        """AC: markdown/features/reference/rate-limiting.md has a Layered protection section covering edge/CDN, reverse proxy, app, and host settings (APP_BIND_ADDRESS=127.0.0.1, FORWARDED_ALLOW_IPS, single process)."""
        section = _layered_section()
        lower = section.lower()
        for term in ("cdn", "cloudflare", "reverse proxy", "timeout", "body size",
                     "connection", "atomic", "/twitch/panel"):
            assert term in lower, term
        assert "APP_BIND_ADDRESS=127.0.0.1" in section
        assert "FORWARDED_ALLOW_IPS=*" in section
        assert "single process" in lower or "one process" in lower

    def test_rate_limiting_doc_has_nginx_and_caddy_snippets(self):
        """AC: the section includes example nginx (limit_req) and Caddy (rate_limit) snippets."""
        section = _layered_section()
        assert "```nginx" in section and "limit_req" in section and "limit_conn" in section
        assert "client_max_body_size" in section
        assert "```caddy" in section and "rate_limit" in section

    def test_rate_limiting_doc_states_app_limits(self):
        """AC: the section says what the app can't do (absorb bandwidth floods, share limits across processes without Redis)."""
        lower = _layered_section().lower()
        assert "bandwidth" in lower
        assert "redis" in lower

    def test_env_example_lists_new_variables(self):
        """Failure path: .env.example and the docs must name RATE_LIMIT_CARD_ACTION, RATE_LIMIT_CARD_ACTION_IP, RATE_LIMIT_USER_ACTION, RATE_LIMIT_SIMULATE and MAX_REQUEST_BODY_BYTES; a missing one fails."""
        env_example = _read(".env.example")
        rate_doc = _read("markdown/features/reference/rate-limiting.md")
        commands = _read("markdown/features/reference/commands.md")
        for var in ("RATE_LIMIT_CARD_ACTION", "RATE_LIMIT_CARD_ACTION_IP",
                    "RATE_LIMIT_USER_ACTION", "RATE_LIMIT_SIMULATE", "MAX_REQUEST_BODY_BYTES"):
            for name, text in ((".env.example", env_example), ("rate-limiting.md", rate_doc),
                               ("commands.md", commands)):
                assert re.search(rf"\b{var}\b", text), f"{var} missing from {name}"


def test_throttle_log_memory_is_capped(monkeypatch):
    """Security review (Low): many distinct throttled keys within one interval can't grow
    the "already logged" map past its cap; it starts over instead."""
    import main
    from starlette.requests import Request

    monkeypatch.setattr(main, "_throttle_logged", {(f"k{i}", "/x"): 0.0 for i in range(10001)})
    monkeypatch.setattr(main.time, "monotonic", lambda: 1.0)  # nothing has expired yet
    monkeypatch.setattr(main, "_throttle_key_kind", lambda request, exc: ("ip", "fresh"))
    monkeypatch.setattr(main, "_route_template", lambda request: "/draw")
    request = Request({"type": "http", "method": "POST", "path": "/draw", "headers": []})
    main._log_throttled(request, None)
    assert len(main._throttle_logged) == 1
    assert ("fresh", "/draw") in main._throttle_logged
