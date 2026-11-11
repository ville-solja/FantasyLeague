"""
Tests for plan-issue-220-pre-season-team-signup.md (resolves GitHub issue #220).

A Team Finder tab, shown only while an admin has a signup period open, lets a
captain list a partial team (Dota ids, open roles, note, contact, Full) and browse
the other listings in a daily shuffle. Players can remove themselves from a team
that listed them; the organiser exports the listings as CSV.

  Story 1: An Admin Opens and Closes the Signup Period
  Story 2: A Captain Lists a Partial Team
  Story 3: Captains Browse the Other Teams
  Story 4: A Player Removes Themselves From a Team
  Story 5: The Organiser Exports the Signups
  Other:   shared player lookup refactor, models / no migration

Developer notes:

- New modules (`team_signup`, `player_lookup`, `routers.team_signup`,
  `routers.admin_team_signup`) don't exist yet: import them INSIDE each test, never at
  module level, so collection keeps working until they land.
- `db` here is a module fixture on a StaticPool with check_same_thread=False, so
  TestClient threads see the test's rows (same as test_issue_237_*). Plain
  `:memory:` from conftest is invisible to TestClient worker threads.
- `_client(db, *routers, user=..., reauth=...)` is copied from
  test_issue_237_finals_prediction_page.py: it overrides get_db, get_current_user and
  (by default) require_recent_reauth. `POST /admin/team-signup/clear` needs a recent
  re-auth: test the 403 `reauth_required` case with `reauth=False`.
  `require_admin` checks the database, so admin users must be real rows with is_admin.
- Routes that are optional-login (`GET /team-signup`) use deps.session_user_or_none,
  which reads the real session: for the logged-in case build a session with
  `{"sid": sessions.create_session(db, user)}` or override the route's dependency.
- Rate limits: take the Limiter from the router module (`routers.team_signup.limiter`),
  never from `rate_limit` (another file reloading it breaks under -n auto). Split
  limited routes into a plain function and a `*_route` wrapper; look limits up via
  `limiter._route_limits["routers.team_signup.<fn>_route"]` as test_issue_237 does.
- Soft (Twitch) accounts: `deps._session_user` already returns None for
  account_type == "twitch", so a session-based request answers 401, while the plan
  says 403. Pin the refusal at the service layer (team_signup.save_listing on a soft
  User raises HTTPException 403) and accept 401/403 at the HTTP layer, or settle the
  code and fix the plan (lessons: follow the code).
- OpenDota: monkeypatch `player_lookup.opendota_get_json` (today
  `routers.admin_players.opendota_get_json`, see the `lookup` fixture in
  test_issue_214_admin_enhancements.py) and call `player_lookup.clear_lookup_cache()`
  around each test. Keep `routers.admin_players.clear_lookup_cache` / `_lookup_now`
  working (re-export) so the issue 214 lookup tests stay green unchanged.
- Steam64 conversion uses `steam_openid.STEAM32_OFFSET` (76561197960265728); medals
  use `player_rank.medal_name` / `parse_rank`; names use
  `text_safety.clean_display_text` and `looks_like_url`.
- Time: pass `now=` into team_signup functions (period lazy close, daily shuffle seed,
  60-day retention) rather than patching time.time.
- Daily cleanup: add a best-effort helper in main.py with its own try/except (like
  `_run_mvp_vote_cleanup`) and test it the way test_issue_234 does (source check that
  the loop calls it, plus "a failure is logged, never raised").
- Audit rows: query AuditLog by action; detail should include the period label and
  actor_username the admin's name. Not-on-team audit must not reveal the remover to
  the captain via the public response.
- Responses must never contain user ids or emails: walk the JSON for keys
  `captain_user_id`, `user_id`, `email` and for the test users' email strings.

Run with: cd backend && python -m pytest tests/test_issue_220_pre_season_team_signup.py -v
"""

import csv
import inspect
import io
import json
import pathlib
import re
import time
from html.parser import HTMLParser

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import models  # noqa: F401  (registers tables for the db fixture)
from database import get_db
from models import AuditLog, Player, TeamSignup, TeamSignupPeriod, TeamSignupPlayer, User

STEAM64_BASE = 76561197960265728
DAY = 86400
BASE = 1_790_000_000


@pytest.fixture
def db():
    """In-memory SQLite shared across threads, so TestClient requests see the test's rows."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _user(db, name="alice", admin=False, player_id=None, account_type="full"):
    # A player link counts only with the Steam id that verified it (player_links, issue #209).
    u = User(username=name, email=f"{name}@example.com", password_hash="x", is_admin=admin,
             player_id=player_id, account_type=account_type,
             steam_id=str(STEAM64_BASE + player_id) if player_id else None)
    db.add(u)
    db.commit()
    return u


def _client(db, *routers, user=None, reauth=True):
    """A small app on `db`; with `user`, signed in as them, and (reauth) with a recent
    password re-entry, so require_recent_reauth passes."""
    from starlette.middleware.sessions import SessionMiddleware

    import rate_limit
    from deps import get_current_user, require_recent_reauth
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key")
    app.state.limiter = rate_limit.limiter
    for r in routers:
        app.include_router(r)

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    if user is not None:
        identity = {"user_id": user.id, "username": user.username, "is_admin": bool(user.is_admin)}
        app.dependency_overrides[get_current_user] = lambda: identity
        if reauth:
            app.dependency_overrides[require_recent_reauth] = lambda: identity
    return TestClient(app)


FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

# OpenDota as the tests see it: id -> (personaname, rank_tier, leaderboard_rank).
OPENDOTA = {222: ("Miracle", 80, 3), 333: ("Topson", 75, None), 444: ("N0tail", None, None)}


@pytest.fixture(autouse=True)
def opendota(monkeypatch):
    """Every OpenDota call goes to OPENDOTA (never the network); the list records the ids asked."""
    import player_lookup
    calls = []

    def fake(url, **kwargs):
        pid = int(url.rsplit("/", 1)[1])
        calls.append(pid)
        if pid in OPENDOTA:
            name, tier, lb = OPENDOTA[pid]
            return {"profile": {"personaname": name}, "rank_tier": tier, "leaderboard_rank": lb}
        return {"rank_tier": None}

    monkeypatch.setattr(player_lookup, "opendota_get_json", fake)        # admin lookups
    monkeypatch.setattr(player_lookup, "opendota_get_json_once", fake)   # captain lookups
    monkeypatch.setattr(player_lookup, "try_throttle", lambda cost=1: True)
    player_lookup.clear_lookup_cache()
    yield calls
    player_lookup.clear_lookup_cache()


@pytest.fixture(autouse=True)
def no_limits():
    """Limits off by default (many saves per test); the rate-limit tests switch them on."""
    import routers.team_signup as rts
    was = rts.limiter.enabled
    rts.limiter.enabled = False
    yield
    rts.limiter.enabled = was


def _ts():
    import team_signup
    return team_signup


def _rts():
    import routers.team_signup as rts
    return rts


def _ats():
    import routers.admin_team_signup as ats
    return ats


def _period(db, label="Season 17", closes_at=None, now=None, admin=None):
    admin = admin or _user(db, f"admin{db.query(User).count()}", admin=True)
    p = _ts().start_period(db, label, closes_at, admin.id, now=now)
    db.commit()
    return p


def _save(db, user, now=None, **fields):
    body = {"team_name": f"Team {user.username}", "players": [101, 102], "open_roles": [2, 4],
            "note": "Weeknights", "contact": f"Discord: {user.username}", "is_full": False}
    body.update(fields)
    s = _ts().save_listing(db, user, now=now, **body)
    db.commit()
    return s


def _looked_up(db, *ids):
    """What the captain form does before saving: look the ids up (fills the cache)."""
    import player_lookup
    return player_lookup.describe(db, list(ids), user_key="form")


def _body(**fields):
    body = {"team_name": "Excel Ninjat", "players": [101, 102], "open_roles": [2, 3],
            "note": "Tuesdays", "contact": "Discord: pivot_table", "is_full": False}
    body.update(fields)
    return body


def _public_client(db, viewer=None):
    """Team Finder routes; with `viewer`, logged in as them (GET /team-signup included)."""
    rts = _rts()
    client = _client(db, rts.router, user=viewer)
    if viewer is not None:
        client.app.dependency_overrides[rts.optional_user] = lambda: viewer
    return client


def _admin_client(db, user=None, reauth=True):
    user = user or _user(db, "boss", admin=True)
    return _client(db, _ats().router, user=user, reauth=reauth), user


def _players(db, signup_id):
    return [r.account_id for r in db.query(TeamSignupPlayer).filter_by(signup_id=signup_id)
            .order_by(TeamSignupPlayer.id)]


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _read(name):
    return (FRONTEND / name).read_text()


def _fn(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start)]


class _Tabs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons, self.scripts = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "button" and "tab" in (a.get("class") or "").split():
            self.buttons.append(a)
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


# ===========================================================================
# Story 1: An Admin Opens and Closes the Signup Period
# ===========================================================================

class TestStory1Period:

    def test_admin_open_period_with_label_and_closing_time(self, db):
        """Open signup: POST /admin/team-signup/period with a label (required, up to 40 chars) and optional closes_at creates an open period."""
        client, admin = _admin_client(db)
        closes = int(time.time()) + 7 * DAY
        res = client.post("/admin/team-signup/period", json={"label": "Season 17", "closes_at": closes})
        assert res.status_code == 200, res.text
        assert res.json()["open"] is True and res.json()["current"]["label"] == "Season 17"
        p = db.query(TeamSignupPeriod).one()
        assert (p.label, p.closes_at, p.closed_at, p.opened_by_user_id) == ("Season 17", closes, None, admin.id)
        assert _ts().is_open(db)
        assert client.post("/admin/team-signup/period/close").status_code == 200
        assert client.post("/admin/team-signup/period", json={"label": "Season 18"}).status_code == 200
        assert db.query(TeamSignupPeriod).filter_by(label="Season 18").one().closes_at is None

    def test_admin_open_period_refused_while_another_open(self, db):
        """Open signup is refused with 409 while another period is open (one open period at a time)."""
        client, _ = _admin_client(db)
        assert client.post("/admin/team-signup/period", json={"label": "Season 17"}).status_code == 200
        res = client.post("/admin/team-signup/period", json={"label": "Again"})
        assert res.status_code == 409
        assert db.query(TeamSignupPeriod).count() == 1

    def test_admin_open_period_invalid_label_rejected(self, db):
        """A missing, blank or over-40-character label is refused with 422."""
        client, _ = _admin_client(db)
        for body in ({}, {"label": ""}, {"label": "   "}, {"label": "\u200b"}, {"label": "x" * 41},
                     {"label": "S17", "closes_at": int(time.time()) - 10}):
            assert client.post("/admin/team-signup/period", json=body).status_code == 422, body
        assert db.query(TeamSignupPeriod).count() == 0
        assert client.post("/admin/team-signup/period", json={"label": "x" * 40}).status_code == 200

    def test_config_team_signup_open_true_while_period_open(self, db):
        """Visible: GET /config returns team_signup_open: true while a period is open and its closing time hasn't passed."""
        import main
        _period(db, closes_at=int(time.time()) + DAY)
        assert main.get_config(db)["team_signup_open"] is True

    def test_config_team_signup_open_false_without_period(self, db):
        """GET /config returns team_signup_open: false when no period exists or the last one is closed."""
        import main
        assert main.get_config(db)["team_signup_open"] is False
        _period(db)
        _ts().close_period(db)
        db.commit()
        assert main.get_config(db)["team_signup_open"] is False

    def test_admin_close_now_ends_period(self, db):
        """Close now: POST /admin/team-signup/period/close ends the period at once; /config then returns false."""
        import main
        client, _ = _admin_client(db)
        client.post("/admin/team-signup/period", json={"label": "Season 17"})
        assert main.get_config(db)["team_signup_open"] is True
        res = client.post("/admin/team-signup/period/close")
        assert res.status_code == 200 and res.json()["open"] is False
        db.expire_all()
        assert db.query(TeamSignupPeriod).one().closed_at is not None
        assert main.get_config(db)["team_signup_open"] is False
        assert client.post("/admin/team-signup/period/close").status_code == 409

    def test_period_lazy_close_after_closes_at(self, db):
        """A period whose closes_at has passed counts as closed without a background job (/config false, saves 409)."""
        import main
        ts = _ts()
        p = _period(db, closes_at=BASE + DAY, now=BASE)
        assert ts.is_open(db, BASE + DAY - 1) and not ts.is_open(db, BASE + DAY)
        with pytest.raises(HTTPException) as exc:
            _save(db, _user(db, "late"), now=BASE + DAY)
        assert exc.value.status_code == 409
        assert db.get(TeamSignupPeriod, p.id).closed_at is None   # nothing had to run
        # A closing time already past in real time: /config and the HTTP save agree.
        db.query(TeamSignupPeriod).filter_by(id=p.id).delete()
        db.add(TeamSignupPeriod(label="Past", opened_at=int(time.time()) - 100, closes_at=int(time.time()) - 1))
        db.commit()
        assert main.get_config(db)["team_signup_open"] is False
        assert _public_client(db, _user(db, "bob")).put("/team-signup/mine", json=_body()).status_code == 409
        # Opening the next one records the lazy close first (the one-open-period index).
        _period(db, label="Season 18")
        assert db.query(TeamSignupPeriod).filter_by(label="Past").one().closed_at is not None

    def test_save_refused_after_period_closed(self, db):
        """Once the period is closed, PUT /team-signup/mine answers 409."""
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        assert client.put("/team-signup/mine", json=_body()).status_code == 200
        _ts().close_period(db)
        db.commit()
        res = client.put("/team-signup/mine", json=_body(team_name="Renamed"))
        assert res.status_code == 409 and res.json()["detail"] == "Signup is closed"
        assert db.query(TeamSignup).one().team_name == "Excel Ninjat"

    def test_admin_period_actions_audited_with_admin_and_label(self, db):
        """Audit: opening, closing, clearing and removing a listing write AuditLog rows with the admin's name and the period label."""
        client, admin = _admin_client(db)
        client.post("/admin/team-signup/period", json={"label": "Season 17"})
        a = _save(db, _user(db, "cap1"))
        _save(db, _user(db, "cap2"))
        assert client.delete(f"/admin/team-signup/{a.id}").status_code == 200
        assert client.post("/admin/team-signup/period/close").status_code == 200
        pid = db.query(TeamSignupPeriod).one().id
        assert client.post("/admin/team-signup/clear", json={"period_id": pid}).status_code == 200
        rows = {r.action: r for r in db.query(AuditLog).all()}
        for action in ("admin_team_signup_opened", "admin_team_signup_removed",
                       "admin_team_signup_closed", "admin_team_signup_cleared"):
            assert action in rows, action
            assert rows[action].actor_username == "boss" and rows[action].actor_id == admin.id
            assert "Season 17" in rows[action].detail
        assert "Team cap1" in rows["admin_team_signup_removed"].detail

    @pytest.mark.parametrize("method,path", [
        ("GET", "/admin/team-signup"),
        ("POST", "/admin/team-signup/period"),
        ("POST", "/admin/team-signup/period/close"),
        ("DELETE", "/admin/team-signup/1"),
        ("GET", "/admin/team-signup/export.csv"),
        ("POST", "/admin/team-signup/clear"),
    ])
    def test_admin_team_signup_routes_forbidden_for_non_admin(self, db, method, path):
        """Refused: non-admins get 403 from every /admin/team-signup route."""
        _period(db)
        client, _ = _admin_client(db, user=_user(db, "pleb"))
        body = {"label": "Season 18", "period_id": 1} if method == "POST" else None
        res = client.request(method, path, json=body)
        assert res.status_code == 403, res.text
        assert db.query(TeamSignupPeriod).count() == 1 and db.query(AuditLog).count() == 0


# ===========================================================================
# Story 2: A Captain Lists a Partial Team
# ===========================================================================

class TestStory2Listing:

    def test_put_mine_creates_listing_for_logged_in_user(self, db):
        """Who: a logged-in website account creates a listing with PUT /team-signup/mine while a period is open."""
        _period(db)
        bob = _user(db, "bob")
        res = _public_client(db, bob).put("/team-signup/mine", json=_body())
        assert res.status_code == 200, res.text
        mine = res.json()
        assert mine["team_name"] == "Excel Ninjat" and mine["is_mine"] is True
        assert mine["contact"] == "Discord: pivot_table"
        s = db.query(TeamSignup).one()
        assert s.captain_user_id == bob.id and _players(db, s.id) == [101, 102]

    def test_put_mine_one_listing_per_account_per_period(self, db):
        """A second PUT by the same account updates its one listing for the period rather than creating another (unique period_id + captain_user_id)."""
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        first = client.put("/team-signup/mine", json=_body()).json()
        second = client.put("/team-signup/mine", json=_body(team_name="Renamed")).json()
        assert first["id"] == second["id"]
        assert db.query(TeamSignup).count() == 1 and db.query(TeamSignup).one().team_name == "Renamed"

    def test_put_mine_logged_out_refused(self, db):
        """Logged-out visitors can't save (401); the tab shows "Log in to list your team"."""
        _period(db)
        client = _public_client(db)
        assert client.put("/team-signup/mine", json=_body()).status_code == 401
        assert client.delete("/team-signup/mine").status_code == 401
        view = client.get("/team-signup").json()
        assert view["open"] is True and view["logged_in"] is False and view["can_list"] is False
        assert db.query(TeamSignup).count() == 0
        assert "Log in to list your team" in _read("app-team-finder.js")

    def test_save_listing_soft_account_refused(self, db):
        """Twitch soft accounts are refused (403 from team_signup.save_listing; the HTTP layer never sees a soft session)."""
        import deps
        import sessions
        from starlette.requests import Request
        _period(db)
        soft = _user(db, "tw_viewer", account_type="twitch")
        with pytest.raises(HTTPException) as exc:
            _save(db, soft)
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            _ts().delete_listing(db, soft)
        assert exc.value.status_code == 403
        assert db.query(TeamSignup).count() == 0
        # Over HTTP a soft account's session resolves to no user, so the save answers 401.
        sid = sessions.create_session(db, soft)
        db.commit()
        req = Request({"type": "http", "headers": [], "session": {sessions.SID_KEY: sid}})
        assert deps.session_user_or_none(req, db) is None

    def test_put_mine_fields_cleaned_and_stored(self, db):
        """Fields: team name (2-32, cleaned), open roles from 1-5, note (<=280, cleaned) and contact (required, <=100, cleaned) are stored."""
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        res = client.put("/team-signup/mine", json=_body(
            team_name="  Excel\u200b   Ninjat ", open_roles=[4, 2, 2], note="Tue\u202e and   Thu ",
            contact=" Discord:\u200b   pivot "))
        assert res.status_code == 200, res.text
        s = db.query(TeamSignup).one()
        assert s.team_name == "Excel Ninjat"
        assert json.loads(s.open_roles_json) == [2, 4]
        assert s.note == "Tue and Thu"
        assert s.contact == "Discord: pivot"
        assert client.put("/team-signup/mine", json=_body(note="", open_roles=[])).status_code == 200
        db.expire_all()
        assert db.query(TeamSignup).one().note is None
        assert json.loads(db.query(TeamSignup).one().open_roles_json) == []

    @pytest.mark.parametrize("field,value", [
        ("team_name", "a"),
        ("team_name", "x" * 33),
        ("team_name", "www.example.com"),
        ("note", "y" * 281),
        ("note", "join https://example.com"),
        ("contact", ""),
        ("contact", "z" * 101),
        ("open_roles", [0]),
        ("open_roles", [6]),
    ])
    def test_put_mine_invalid_field_rejected(self, db, field, value):
        """A field outside its limits, a team name or note that looks like a link, a missing contact or a role outside 1-5 is refused with 422."""
        _period(db)
        res = _public_client(db, _user(db, "bob")).put("/team-signup/mine", json=_body(**{field: value}))
        assert res.status_code == 422, res.text
        assert db.query(TeamSignup).count() == 0

    def test_put_mine_accepts_steam64_and_converts(self, db):
        """Ids: a Steam64 id (17 digits from 76561197960265728) is accepted and stored as the 32-bit Dota id."""
        _period(db)
        res = _public_client(db, _user(db, "bob")).put(
            "/team-signup/mine", json=_body(players=[str(STEAM64_BASE + 1234), STEAM64_BASE + 222, "333"]))
        assert res.status_code == 200, res.text
        assert _players(db, db.query(TeamSignup).one().id) == [1234, 222, 333]
        assert [p["account_id"] for p in res.json()["players"]] == [1234, 222, 333]

    def test_put_mine_duplicate_or_too_many_ids_rejected(self, db):
        """A duplicate id in the same listing, zero ids, or more than 7 ids is refused with 422."""
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        for players in ([5, 5], [5, str(STEAM64_BASE + 5)], [], list(range(1, 9)), ["12a"], [2**40]):
            assert client.put("/team-signup/mine", json=_body(players=players)).status_code == 422, players
        assert db.query(TeamSignup).count() == 0
        assert client.put("/team-signup/mine", json=_body(players=list(range(1, 8)))).status_code == 200

    def test_lookup_returns_pool_name_and_medal_then_opendota(self, db, opendota):
        """GET /team-signup/lookup gives each id's name and medal from the pool, else from OpenDota."""
        _period(db)
        db.add(Player(id=111, name="Pooled", avatar_url="", is_active=True, rank_tier=52))
        db.commit()
        client = _public_client(db, _user(db, "bob"))
        res = client.get("/team-signup/lookup", params={"ids": f"111, {STEAM64_BASE + 222}"})
        assert res.status_code == 200, res.text
        assert res.json() == [
            {"account_id": 111, "name": "Pooled", "rank_tier": 52, "leaderboard_rank": None,
             "medal": "Legend 2", "source": "pool"},
            {"account_id": 222, "name": "Miracle", "rank_tier": 80, "leaderboard_rank": 3,
             "medal": "Immortal #3", "source": "opendota"}]
        assert opendota == [222]
        client.get("/team-signup/lookup", params={"ids": "222"})
        assert opendota == [222]   # cached
        assert client.get("/team-signup/lookup", params={"ids": "12a"}).status_code == 422

    def test_lookup_unknown_or_opendota_down_gives_unknown_player(self, db, monkeypatch):
        """An id not in the pool and not on OpenDota (or OpenDota failing) shows as "Unknown player", and saving it still works."""
        import player_lookup
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        assert client.get("/team-signup/lookup?ids=999").json()[0]["name"] is None
        monkeypatch.setattr(player_lookup, "opendota_get_json_once", lambda *a, **k: None)   # unreachable
        out = client.get("/team-signup/lookup?ids=998").json()[0]
        assert out["name"] is None and out["source"] is None and out["medal"] is None
        res = client.put("/team-signup/mine", json=_body(players=[998, 999]))
        assert res.status_code == 200
        assert [p["name"] for p in res.json()["players"]] == [None, None]
        assert "Unknown player" in _read("app-team-finder.js")

    def test_put_mine_stores_names_and_medals_with_listing(self, db, opendota):
        """Names and medals are stored with the listing (GET /team-signup doesn't call OpenDota per view)."""
        _period(db)
        bob = _user(db, "bob")
        client = _public_client(db, bob)
        client.get("/team-signup/lookup?ids=222,333")   # the form looks ids up before saving
        client.put("/team-signup/mine", json=_body(players=[222, 333]))
        rows = {r.account_id: r for r in db.query(TeamSignupPlayer).all()}
        assert (rows[222].name, rows[222].rank_tier, rows[222].leaderboard_rank) == ("Miracle", 80, 3)
        assert (rows[333].name, rows[333].rank_tier) == ("Topson", 75)
        calls_after_save = list(opendota)
        import player_lookup
        player_lookup.clear_lookup_cache()
        for viewer in (None, _user(db, "eve")):
            team = _public_client(db, viewer).get("/team-signup").json()["teams"][0]
            assert [(p["name"], p["medal"]) for p in team["players"]] == [("Miracle", "Immortal #3"), ("Topson", "Divine 5")]
        client.put("/team-signup/mine", json=_body(players=[222, 333], team_name="Renamed"))
        assert opendota == calls_after_save   # stored names are reused on a re-save too

    def test_put_mine_captain_verified_player_added_first(self, db):
        """Own player: when the captain has a Steam-verified player_id, it is the first player and labelled Verified; typed ids are Listed by captain."""
        _period(db)
        db.add(Player(id=555, name="Me", avatar_url="", is_active=True, rank_tier=34))
        db.commit()
        cap = _user(db, "cap", player_id=555)
        client = _public_client(db, cap)
        view = client.get("/team-signup").json()
        assert view["own_player"]["account_id"] == 555 and view["own_player"]["name"] == "Me"
        mine = client.put("/team-signup/mine", json=_body(players=[222, 555])).json()
        assert [(p["account_id"], p["verified"]) for p in mine["players"]] == [(555, True), (222, False)]
        mine = client.put("/team-signup/mine", json=_body(players=[])).json()   # own player alone is enough
        assert [p["account_id"] for p in mine["players"]] == [555]
        assert client.put("/team-signup/mine", json=_body(players=list(range(1, 8)))).status_code == 422
        typed = User(username="typed", email="typed@example.com", password_hash="x", player_id=556)
        db.add(typed)   # a player_id without the Steam id that verified it is no link (issue #209)
        db.commit()
        assert _public_client(db, typed).get("/team-signup").json()["own_player"] is None
        mine = _public_client(db, typed).put("/team-signup/mine", json=_body(players=[556])).json()
        assert [(p["account_id"], p["verified"]) for p in mine["players"]] == [(556, False)]

    def test_put_mine_listed_ids_do_not_change_user_links(self, db):
        """Typed ids are claims: listing an id doesn't change any User.player_id, cards or tags."""
        from models import Card, UserTag
        _period(db)
        target = _user(db, "target", player_id=777)
        other = _user(db, "other")
        cap = _user(db, "cap", player_id=555)
        _public_client(db, cap).put("/team-signup/mine", json=_body(players=[777, 888]))
        db.expire_all()
        assert (db.get(User, target.id).player_id, db.get(User, other.id).player_id,
                db.get(User, cap.id).player_id) == (777, None, 555)
        assert db.query(Card).count() == 0 and db.query(UserTag).count() == 0
        assert db.query(Player).count() == 0
        verified = {r.account_id: r.verified for r in db.query(TeamSignupPlayer).all()}
        assert verified == {555: True, 777: False, 888: False}

    def test_put_mine_edits_every_field(self, db):
        """Edit: the captain can change any field while the period is open."""
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        client.put("/team-signup/mine", json=_body())
        new = {"team_name": "Paperinen Tiikeri", "players": [102, 333], "open_roles": [1, 5],
               "note": "Mondays", "contact": "Steam: tulostin", "is_full": True}
        mine = client.put("/team-signup/mine", json=new).json()
        assert (mine["team_name"], mine["open_roles"], mine["note"], mine["contact"], mine["is_full"]) == \
            ("Paperinen Tiikeri", [1, 5], "Mondays", "Steam: tulostin", True)
        assert [p["account_id"] for p in mine["players"]] == [102, 333]
        assert sorted(_players(db, mine["id"])) == [102, 333]

    def test_delete_mine_removes_listing_players_and_contact(self, db):
        """Delete: DELETE /team-signup/mine removes the listing, its players and its contact at once; the captain can list again."""
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        client.put("/team-signup/mine", json=_body())
        assert client.delete("/team-signup/mine").status_code == 200
        assert db.query(TeamSignup).count() == 0 and db.query(TeamSignupPlayer).count() == 0
        assert "pivot_table" not in json.dumps(client.get("/team-signup").json())
        assert client.delete("/team-signup/mine").status_code == 404
        assert client.put("/team-signup/mine", json=_body()).status_code == 200
        assert db.query(TeamSignup).count() == 1

    def test_delete_mine_refused_after_period_closed(self, db):
        """Edits and deletes are refused (409) once the period has closed."""
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        client.put("/team-signup/mine", json=_body())
        _ts().close_period(db)
        db.commit()
        assert client.delete("/team-signup/mine").status_code == 409
        assert client.put("/team-signup/mine", json=_body(note="later")).status_code == 409
        assert db.query(TeamSignup).count() == 1 and db.query(TeamSignupPlayer).count() == 2

    def test_put_mine_full_toggle_and_undo(self, db):
        """Full: the captain can mark the team full and undo it; a full team is listed in the Full teams section."""
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        client.put("/team-signup/mine", json=_body(is_full=True))
        view = client.get("/team-signup").json()
        assert view["teams"] == [] and [t["team_name"] for t in view["full_teams"]] == ["Excel Ninjat"]
        client.put("/team-signup/mine", json=_body(is_full=False))
        view = client.get("/team-signup").json()
        assert view["full_teams"] == [] and [t["team_name"] for t in view["teams"]] == ["Excel Ninjat"]

    def test_put_mine_rate_limited_per_user(self, db):
        """Limits: saves are rate-limited per user; going past the limit answers 429 (use routers.team_signup.limiter)."""
        rts = _rts()
        assert rts.RATE_LIMIT_TEAM_SIGNUP_SAVE == "10/minute"
        for fn in ("save_mine_route", "delete_mine_route", "not_on_team_route"):
            limits = rts.limiter._route_limits.get(f"routers.team_signup.{fn}", [])
            assert [str(lim.limit) for lim in limits] == ["10 per 1 minute"], fn
            assert limits[0].key_func is rts.key_by_user_or_ip
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        client.app.state.limiter = rts.limiter
        was = rts.limiter.enabled
        rts.limiter.enabled = True
        rts.limiter.reset()
        try:
            codes = [client.put("/team-signup/mine", json=_body()).status_code for _ in range(11)]
        finally:
            rts.limiter.reset()
            rts.limiter.enabled = was
        assert codes[:10] == [200] * 10 and codes[10] == 429


# ===========================================================================
# Story 3: Captains Browse the Other Teams
# ===========================================================================

def _teams(db, n, now=BASE, **fields):
    """n listings by captains c0..c(n-1) in a period opened at BASE."""
    if not db.query(TeamSignupPeriod).count():
        _period(db, now=BASE)
    return [_save(db, _user(db, f"c{i}"), now=now, players=[1000 + i], **fields) for i in range(n)]


class TestStory3Browse:

    def test_get_team_signup_lists_partial_teams_with_fields(self, db):
        """List: each partial team has its name, players (name, medal, Verified / Listed by captain), open roles, players needed, note and last update date."""
        _period(db)
        db.add(Player(id=555, name="Me", avatar_url="", is_active=True, rank_tier=34))
        db.commit()
        _looked_up(db, 222)
        _save(db, _user(db, "cap", player_id=555), players=[222], open_roles=[1, 5], note="Mondays")
        team = _public_client(db).get("/team-signup").json()["teams"][0]
        assert team["team_name"] == "Team cap" and team["open_roles"] == [1, 5] and team["note"] == "Mondays"
        assert team["players_needed"] == 3 and team["player_count"] == 2
        assert isinstance(team["updated_at"], int) and team["is_full"] is False
        assert [(p["name"], p["medal"], p["verified"]) for p in team["players"]] == \
            [("Me", "Crusader 4", True), ("Miracle", "Immortal #3", False)]
        js = _read("app-team-finder.js")
        assert "Verified" in js and "Listed by captain" in js

    def test_players_needed_is_five_minus_players_at_least_zero(self, db):
        """Players needed is 5 minus the listed players, never below 0 (a team of 7 needs 0)."""
        _period(db)
        for name, ids in (("one", [1]), ("five", list(range(10, 15))), ("seven", list(range(20, 27)))):
            _save(db, _user(db, name), players=ids)
        teams = {t["team_name"]: t for t in _ts().public_view(db, None)["teams"]}
        assert [teams[f"Team {n}"]["players_needed"] for n in ("one", "five", "seven")] == [4, 0, 0]

    def test_daily_shuffle_stable_within_a_day_changes_next_day(self, db):
        """Order: partial teams are shuffled, seeded by period and date; the order is the same all day and changes the next day."""
        _teams(db, 8)
        ts = _ts()
        day_start = BASE - BASE % DAY

        def order(now):
            return [t["id"] for t in ts.public_view(db, None, now=now)["teams"]]
        today = order(day_start + 60)
        assert order(day_start + DAY - 60) == today
        later = [order(day_start + k * DAY + 60) for k in range(1, 4)]
        assert all(sorted(o) == sorted(today) for o in later)
        assert any(o != today for o in later)
        assert today != sorted(today) or later[0] != sorted(today)   # not the signup order every day

    def test_daily_shuffle_unaffected_by_edits(self, db):
        """Editing a listing (updated_at changes) doesn't move it in the daily order."""
        teams = _teams(db, 6)
        ts = _ts()
        before = [t["id"] for t in ts.public_view(db, None, now=BASE + 100)["teams"]]
        last = db.get(User, db.get(TeamSignup, before[-1]).captain_user_id)
        _save(db, last, now=BASE + 50, players=[1999], note="edited")
        after = ts.public_view(db, None, now=BASE + 100)["teams"]
        assert [t["id"] for t in after] == before
        assert after[-1]["updated_at"] == BASE + 50 and len(teams) == 6

    def test_full_teams_listed_last_in_full_section(self, db):
        """Full teams are returned separately, after the partial teams (collapsed Full teams section)."""
        _period(db)
        _save(db, _user(db, "zfull"), is_full=True)
        _save(db, _user(db, "partial"))
        _save(db, _user(db, "afull"), is_full=True)
        view = _public_client(db).get("/team-signup").json()
        assert [t["team_name"] for t in view["teams"]] == ["Team partial"]
        assert [t["team_name"] for t in view["full_teams"]] == ["Team afull", "Team zfull"]
        assert list(view).index("teams") < list(view).index("full_teams")

    def test_get_team_signup_contacts_shown_to_logged_in_users(self, db):
        """Contact: logged-in users get each team's contact in GET /team-signup."""
        _period(db)
        _save(db, _user(db, "a"))
        _save(db, _user(db, "b"), is_full=True)
        view = _public_client(db, _user(db, "viewer")).get("/team-signup").json()
        assert [t["contact"] for t in view["teams"] + view["full_teams"]] == ["Discord: a", "Discord: b"]

    def test_get_team_signup_contacts_hidden_when_logged_out(self, db):
        """Logged-out visitors get no contact field (or value) for any team in GET /team-signup."""
        _period(db)
        _save(db, _user(db, "a"))
        _save(db, _user(db, "b"), is_full=True)
        view = _public_client(db).get("/team-signup").json()
        assert "contact" not in set(_keys(view))
        assert "Discord" not in json.dumps(view)
        assert "Log in to see contact details" in _read("app-team-finder.js")

    def test_get_team_signup_flags_player_on_two_teams(self, db):
        """Duplicates: an id listed on more than one team is flagged "Also listed by another team" on each."""
        _period(db)
        _save(db, _user(db, "a"), players=[777, 1])
        _save(db, _user(db, "b"), players=[2, 777])
        view = _public_client(db).get("/team-signup").json()
        flags = {(t["team_name"], p["account_id"]): p["also_listed"] for t in view["teams"] for p in t["players"]}
        assert flags == {("Team a", 777): True, ("Team a", 1): False, ("Team b", 2): False, ("Team b", 777): True}
        assert "Also listed by another team" in _read("app-team-finder.js")

    def test_get_team_signup_never_exposes_user_ids_or_emails(self, db):
        """Responses never include user ids or emails; captains are shown by team name only."""
        _period(db)
        cap = _user(db, "captainname", player_id=555)
        viewer = _user(db, "viewer")
        _save(db, cap, team_name="Kahvihuone", contact="Discord: kahvi")
        bodies = [_public_client(db).get("/team-signup").json(),
                  _public_client(db, viewer).get("/team-signup").json(),
                  _public_client(db, cap).get("/team-signup").json(),
                  _public_client(db, cap).put("/team-signup/mine", json=_body()).json()]
        for body in bodies:
            keys = set(_keys(body))
            assert not keys & {"captain_user_id", "user_id", "email", "captain", "username"}, keys
            dumped = json.dumps(body)
            for u in db.query(User).all():
                assert u.email not in dumped
            assert "captainname" not in dumped

    def test_get_team_signup_when_no_open_period(self, db):
        """With no open period, GET /team-signup reports the period closed and saves are not offered (non-admin view)."""
        client = _public_client(db, _user(db, "bob"))
        view = client.get("/team-signup").json()
        assert view["open"] is False and view["period"] is None and view["can_list"] is False
        _period(db)
        _save(db, _user(db, "a"))
        _ts().close_period(db)
        db.commit()
        view = client.get("/team-signup").json()
        assert view["open"] is False and view["can_list"] is False
        assert view["period"]["label"] == "Season 17" and view["period"]["open"] is False
        assert view["teams"] == [] and view["full_teams"] == []

    def test_frontend_team_finder_escapes_user_fields(self):
        """Escaping: app-team-finder.js renders team name, player names, note and contact through the escape helper or textContent."""
        js = _read("app-team-finder.js")
        exprs = re.findall(r"\$\{([^`]*?)\}", js)
        for field in ("team_name", "note", "contact", "name"):
            uses = [e for e in exprs if re.search(rf"\w\.{field}\b", e)]
            assert uses, field
            for e in uses:
                assert "_escHtml(" in e or "Number(" in e, (field, e)
        assert "innerHTML = d." not in js and "innerHTML = t." not in js
        assert 'getElementById("tfPeriodLabel").textContent = p ? p.label' in js   # the admin's label: textContent
        for name in ("_tfCardHtml", "_tfPlayerRowsHtml", "_tfContactHtml"):
            assert f"function {name}(" in js

    def test_frontend_team_finder_tab_gated_by_config(self):
        """The Team Finder tab button sits between Schedule and How to Play and is hidden unless team_signup_open (or the viewer is an admin)."""
        p = _Tabs()
        p.feed(_read("index.html"))
        ids = [b.get("id") for b in p.buttons]
        i = ids.index("tab-btn-teamfinder")
        assert ids.index("tab-btn-schedule") < i < ids.index("tab-btn-howtoplay")
        assert "hidden" in p.buttons[i]
        assert "/app-team-finder.js" in p.scripts
        assert 'id="tab-teamfinder"' in _read("index.html")
        cfg = _fn(_read("app-globals.js"), "loadConfig")
        assert "applyTeamFinderAvailability(cfg.team_signup_open === true)" in cfg
        apply = _fn(_read("app-team-finder.js"), "applyTeamFinderAvailability")
        assert "tab-btn-teamfinder" in apply and "activeIsAdmin" in apply
        assert 'if (name === "teamfinder")' in _fn(_read("app-globals.js"), "switchTab")
        assert "applyTeamFinderAvailability" in _fn(_read("app-auth.js"), "applyAuthState")


# ===========================================================================
# Story 4: A Player Removes Themselves From a Team
# ===========================================================================

class TestStory4NotOnTeam:

    def _setup(self, db):
        _period(db)
        cap = _user(db, "cap", player_id=555)
        listing = _save(db, cap, players=[777, 888])
        return cap, listing, _user(db, "kiiski", player_id=777)

    def test_not_on_team_removes_verified_player_row(self, db):
        """Effect: POST /team-signup/{id}/not-on-team by the user whose Steam-verified player is listed deletes that player row; the listing shows the change."""
        cap, listing, me = self._setup(db)
        client = _public_client(db, me)
        team = client.get("/team-signup").json()["teams"][0]
        assert [p["is_you"] for p in team["players"]] == [False, True, False]
        assert client.post(f"/team-signup/{listing.id}/not-on-team").status_code == 200
        assert sorted(_players(db, listing.id)) == [555, 888]
        team = client.get("/team-signup").json()["teams"][0]
        assert [p["account_id"] for p in team["players"]] == [555, 888] and team["players_needed"] == 3
        assert "Not on this team" in _read("app-team-finder.js")

    def test_not_on_team_audited_without_telling_captain(self, db):
        """An audit row records the removal; the captain's view of the listing doesn't say who removed it."""
        cap, listing, me = self._setup(db)
        _public_client(db, me).post(f"/team-signup/{listing.id}/not-on-team")
        row = db.query(AuditLog).filter_by(action="team_signup_not_on_team").one()
        assert row.actor_id == me.id and row.actor_username == "kiiski"
        assert "Season 17" in row.detail and "777" in row.detail
        cap_view = json.dumps(_public_client(db, cap).get("/team-signup").json())
        assert "kiiski" not in cap_view and "removed" not in cap_view.lower()

    def test_not_on_team_refused_without_matching_verified_player(self, db):
        """Refused: a user without that verified player on the listing (or with no Steam link) gets 403."""
        cap, listing, _ = self._setup(db)
        for user in (_user(db, "nolink"), _user(db, "elsewhere", player_id=999)):
            assert _public_client(db, user).post(f"/team-signup/{listing.id}/not-on-team").status_code == 403
        assert _public_client(db).post(f"/team-signup/{listing.id}/not-on-team").status_code == 401
        assert sorted(_players(db, listing.id)) == [555, 777, 888]

    def test_not_on_team_refused_for_own_listing(self, db):
        """A captain removing their own player is refused (403); they use the edit form instead."""
        cap, listing, _ = self._setup(db)
        res = _public_client(db, cap).post(f"/team-signup/{listing.id}/not-on-team")
        assert res.status_code == 403 and res.json()["detail"] == "Edit your own listing instead"
        assert 555 in _players(db, listing.id)

    def test_not_on_team_missing_listing_404(self, db):
        """POST /team-signup/{id}/not-on-team for a listing that doesn't exist answers 404."""
        _, _, me = self._setup(db)
        assert _public_client(db, me).post("/team-signup/9999/not-on-team").status_code == 404

    def test_not_on_team_id_can_be_relisted_and_removed_again(self, db):
        """Re-adding: the captain can list the id again, and the player can remove it again."""
        cap, listing, me = self._setup(db)
        client = _public_client(db, me)
        assert client.post(f"/team-signup/{listing.id}/not-on-team").status_code == 200
        _public_client(db, cap).put("/team-signup/mine", json=_body(players=[777, 888]))
        assert 777 in _players(db, listing.id)
        assert client.post(f"/team-signup/{listing.id}/not-on-team").status_code == 200
        assert 777 not in _players(db, listing.id)
        assert db.query(AuditLog).filter_by(action="team_signup_not_on_team").count() == 2


# ===========================================================================
# Story 5: The Organiser Exports the Signups
# ===========================================================================

def _csv(res):
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(res.text)))


class TestStory5Export:

    def test_admin_export_csv_columns_one_row_per_player(self, db):
        """Download: export.csv has the columns period, team, captain username, contact, full, open roles, note, Dota id, name, medal, verified, also on another team, updated at; one row per player."""
        _period(db)
        db.add(Player(id=555, name="Me", avatar_url="", is_active=True, rank_tier=34))
        db.commit()
        _save(db, _user(db, "cap1", player_id=555), players=[222, 777], open_roles=[2, 4])
        _save(db, _user(db, "cap2"), players=[777, 999], is_full=True, note="Full", open_roles=[])
        client, _ = _admin_client(db)
        rows = _csv(client.get("/admin/team-signup/export.csv"))
        assert rows[0] == ["period", "team", "captain username", "contact", "full", "open roles", "note",
                           "Dota id", "name", "medal", "verified", "also on another team", "updated at"]
        assert len(rows) == 1 + 5
        first = dict(zip(rows[0], rows[1]))
        assert {k: first[k] for k in rows[0][:-1]} == {
            "period": "Season 17", "team": "Team cap1", "captain username": "cap1", "contact": "Discord: cap1",
            "full": "no", "open roles": "2 4", "note": "Weeknights", "Dota id": "555", "name": "Me",
            "medal": "Crusader 4", "verified": "yes", "also on another team": "no"}
        assert first["updated at"].endswith("UTC")
        by_id = {(r[1], r[7]): r for r in rows[1:]}
        assert by_id[("Team cap1", "777")][11] == "yes" and by_id[("Team cap2", "777")][11] == "yes"
        assert by_id[("Team cap2", "999")][8] == "Unknown player" and by_id[("Team cap2", "999")][4] == "yes"
        assert client.get("/admin/team-signup/export.json").json()["rows"] == rows[1:]

    def test_admin_export_csv_defaults_to_current_or_last_period(self, db):
        """Without period_id the export covers the current open period, or the last one when none is open."""
        client, _ = _admin_client(db)
        p1 = _period(db, label="Season 16")
        _save(db, _user(db, "old"))
        _ts().close_period(db)
        db.commit()
        _period(db, label="Season 17")
        _save(db, _user(db, "new"))
        teams = lambda res: {r[1] for r in _csv(res)[1:]}   # noqa: E731
        assert teams(client.get("/admin/team-signup/export.csv")) == {"Team new"}
        _ts().close_period(db)
        db.commit()
        assert teams(client.get("/admin/team-signup/export.csv")) == {"Team new"}
        assert teams(client.get(f"/admin/team-signup/export.csv?period_id={p1.id}")) == {"Team old"}

    @pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
    def test_admin_export_csv_formula_injection_prefixed(self, db, prefix):
        """Safe for spreadsheets: a cell starting with =, +, -, @, tab or CR is prefixed with an apostrophe."""
        _period(db)
        s = _save(db, _user(db, "cap"), players=[101])
        evil = prefix + "HYPERLINK(1)"
        s.contact, s.note, s.team_name = evil, evil, evil
        db.query(TeamSignupPlayer).filter_by(signup_id=s.id).update({"name": evil})
        db.commit()
        client, _ = _admin_client(db)
        row = dict(zip(*_csv(client.get("/admin/team-signup/export.csv"))[:2]))
        for col in ("team", "contact", "note", "name"):
            assert row[col] == "'" + evil, col
        assert _ts()._safe_cell("ok=1") == "ok=1"
        if prefix in "=+-@":   # typed through the form: cleaning keeps these characters
            _save(db, db.query(User).filter_by(username="cap").one(), players=[101], contact=evil)
            row = dict(zip(*_csv(client.get("/admin/team-signup/export.csv"))[:2]))
            assert row["contact"] == "'" + evil

    def test_admin_export_csv_unknown_period_404(self, db):
        """export.csv?period_id=<missing> answers 404."""
        client, _ = _admin_client(db)
        assert client.get("/admin/team-signup/export.csv").status_code == 404   # no period at all
        _period(db)
        assert client.get("/admin/team-signup/export.csv?period_id=9999").status_code == 404

    def test_admin_get_team_signup_lists_every_listing(self, db):
        """Admin list: GET /admin/team-signup returns the periods and every listing (full ones included) with player counts."""
        _period(db)
        _save(db, _user(db, "a"), players=[1, 2, 3])
        _save(db, _user(db, "b"), players=[4], is_full=True)
        client, _ = _admin_client(db)
        data = client.get("/admin/team-signup").json()
        assert data["open"] is True and data["current"]["label"] == "Season 17"
        assert [(p["label"], p["listing_count"]) for p in data["periods"]] == [("Season 17", 2)]
        assert [(r["team_name"], r["captain"], r["player_count"], r["is_full"]) for r in data["listings"]] == \
            [("Team a", "a", 3, False), ("Team b", "b", 1, True)]

    def test_admin_remove_listing_deletes_and_audits(self, db):
        """Remove: DELETE /admin/team-signup/{id} deletes the listing and its players and writes an audit row."""
        _period(db)
        sid = _save(db, _user(db, "a")).id
        keep = _save(db, _user(db, "b")).id
        client, _ = _admin_client(db)
        assert client.delete(f"/admin/team-signup/{sid}").status_code == 200
        assert [t.id for t in db.query(TeamSignup).all()] == [keep]
        assert db.query(TeamSignupPlayer).filter_by(signup_id=sid).count() == 0
        assert db.query(AuditLog).filter_by(action="admin_team_signup_removed").count() == 1

    def test_admin_remove_missing_listing_404(self, db):
        """DELETE /admin/team-signup/{id} for a listing that doesn't exist answers 404."""
        client, _ = _admin_client(db)
        assert client.delete("/admin/team-signup/9999").status_code == 404
        assert db.query(AuditLog).count() == 0

    def test_admin_clear_signups_deletes_period_listings_and_audits(self, db):
        """Clear signups: POST /admin/team-signup/clear deletes the period's listings and players at once and writes an audit row."""
        p = _period(db)
        _save(db, _user(db, "a"))
        _save(db, _user(db, "b"))
        client, _ = _admin_client(db)
        res = client.post("/admin/team-signup/clear", json={"period_id": p.id})
        assert res.status_code == 200 and res.json() == {"deleted": 2}
        assert db.query(TeamSignup).count() == 0 and db.query(TeamSignupPlayer).count() == 0
        assert db.query(TeamSignupPeriod).count() == 1
        row = db.query(AuditLog).filter_by(action="admin_team_signup_cleared").one()
        assert "Season 17" in row.detail and "listings=2" in row.detail
        assert client.post("/admin/team-signup/clear", json={"period_id": 9999}).status_code == 404

    def test_admin_clear_signups_requires_recent_reauth(self, db):
        """Clear signups without a recent re-auth answers 403 reauth_required."""
        p = _period(db)
        _save(db, _user(db, "a"))
        client, _ = _admin_client(db, reauth=False)
        res = client.post("/admin/team-signup/clear", json={"period_id": p.id})
        assert res.status_code == 403 and res.json()["detail"] == "reauth_required"
        assert db.query(TeamSignup).count() == 1

    def test_retention_cleanup_deletes_periods_closed_over_60_days(self, db):
        """Retention: the daily cleanup deletes periods closed more than 60 days ago with their listings and players, and keeps newer ones."""
        ts = _ts()
        now = BASE + 200 * DAY
        old = _period(db, label="Old", now=BASE)
        _save(db, _user(db, "o"), now=BASE)
        ts.close_period(db, now=now - 61 * DAY)
        lazy = _period(db, label="Lazy", now=BASE + DAY, closes_at=now - 61 * DAY)
        _save(db, _user(db, "l"), now=BASE + DAY)
        recent = _period(db, label="Recent", now=now - 60 * DAY - 3600)   # opening records Lazy's close
        _save(db, _user(db, "r"), now=now - 60 * DAY - 3600)
        ts.close_period(db, now=now - 59 * DAY)
        db.commit()
        old_id, lazy_id, recent_id = old.id, lazy.id, recent.id
        assert ts.cleanup(db, now) == 2
        db.commit()
        assert [p.id for p in db.query(TeamSignupPeriod).all()] == [recent_id]
        assert {s.period_id for s in db.query(TeamSignup).all()} == {recent_id}
        assert db.query(TeamSignupPlayer).count() == 2
        assert old_id != lazy_id and ts.RETENTION_DAYS == 60
        assert ts.cleanup(db, now) == 0

    def test_daily_cleanup_wired_and_best_effort(self, monkeypatch):
        """main's daily task calls the team-signup cleanup helper, and a failure in it is logged, never raised."""
        import main
        import team_signup
        loop = inspect.getsource(main._week_maintenance_loop)
        assert "_run_team_signup_cleanup(db)" in loop
        assert "_TEAM_SIGNUP_CLEANUP_INTERVAL" in loop and main._TEAM_SIGNUP_CLEANUP_INTERVAL == 86400
        calls = []

        class _Db:
            committed = rolled_back = False

            def commit(self):
                self.committed = True

            def rollback(self):
                self.rolled_back = True
        monkeypatch.setattr(team_signup, "cleanup", lambda db, now: calls.append(now) or 0)
        ok = _Db()
        main._run_team_signup_cleanup(ok)
        assert len(calls) == 1 and abs(calls[0] - time.time()) < 5 and ok.committed

        def boom(db, now):
            raise RuntimeError("db is gone")
        monkeypatch.setattr(team_signup, "cleanup", boom)
        broken = _Db()
        main._run_team_signup_cleanup(broken)   # a failure is logged, never raised
        assert broken.rolled_back

    def test_privacy_page_describes_team_signup_and_60_days(self):
        """The privacy page describes what a listing stores, who sees the contact and the 60-day retention."""
        p = _Text()
        p.feed(_read("privacy.html"))
        text = " ".join(" ".join(p.parts).split())
        assert "Team Finder" in text
        i = text.index("Team Finder")
        section = text[i:i + 2500]
        for phrase in ("team name", "Dota ids", "contact", "logged-in", "60 days", "delete"):
            assert phrase in section, phrase


# ===========================================================================
# Other: shared player lookup, models
# ===========================================================================

class TestPlayerLookupRefactor:

    def test_player_lookup_parses_32bit_and_steam64_ids(self):
        """player_lookup parses comma/space-separated ids, accepts 32-bit ids and converts Steam64 ids to 32-bit."""
        import player_lookup
        assert player_lookup.parse_ids("123, 456 789,\n42") == [123, 456, 789, 42]
        assert player_lookup.parse_ids(str(STEAM64_BASE + 42)) == [42]
        assert player_lookup.to_account_id(STEAM64_BASE + 2**32 - 1) == 2**32 - 1
        assert player_lookup.to_account_id("4294967295") == 2**32 - 1
        from steam_openid import STEAM32_OFFSET
        assert STEAM32_OFFSET == STEAM64_BASE

    def test_player_lookup_rejects_non_numeric_ids(self):
        """Non-numeric or out-of-range ids are refused with 422."""
        import player_lookup
        for raw in ("12a", "-5", "0", "1.5", str(2**32), str(STEAM64_BASE), str(STEAM64_BASE + 2**32), "9" * 20, "", " , "):
            with pytest.raises(HTTPException) as exc:
                player_lookup.parse_ids(raw)
            assert exc.value.status_code == 422, raw
        with pytest.raises(HTTPException):
            player_lookup.parse_ids(",".join(["1"] * 9), max_ids=8)

    def test_admin_players_lookup_uses_shared_module(self, monkeypatch):
        """routers.admin_players uses player_lookup for parsing and the OpenDota name cache (behaviour and issue 214 tests unchanged)."""
        import player_lookup
        from routers import admin_players as ap
        assert ap._parse_lookup_ids is player_lookup._parse_lookup_ids
        assert ap._lookup_cache is player_lookup._lookup_cache
        assert ap.clear_lookup_cache is player_lookup.clear_lookup_cache
        src = inspect.getsource(ap)
        assert "def _parse_lookup_ids" not in src and "_lookup_lock" not in src
        monkeypatch.setattr(ap, "opendota_get_json", lambda *a, **k: {"profile": {"personaname": "P"}, "rank_tier": 45})
        assert ap._opendota_name(4242) == (True, "P")
        assert player_lookup.opendota_lookup(4242) == (True, "P", 45, None)   # one shared cache
        with pytest.raises(HTTPException):
            ap._parse_lookup_ids("111,,222")

    def test_team_signup_lookup_rate_limited_and_login_required(self, db):
        """GET /team-signup/lookup needs a login (401 when logged out) and is rate-limited per user (429)."""
        rts = _rts()
        assert _public_client(db).get("/team-signup/lookup?ids=222").status_code == 401
        assert rts.RATE_LIMIT_TEAM_SIGNUP_LOOKUP == "30/minute"
        limits = rts.limiter._route_limits.get("routers.team_signup.lookup_route", [])
        assert [str(lim.limit) for lim in limits] == ["30 per 1 minute"]
        _period(db)
        client = _public_client(db, _user(db, "bob"))
        client.app.state.limiter = rts.limiter
        was = rts.limiter.enabled
        rts.limiter.enabled = True
        rts.limiter.reset()
        try:
            codes = [client.get("/team-signup/lookup?ids=222").status_code for _ in range(31)]
        finally:
            rts.limiter.reset()
            rts.limiter.enabled = was
        assert codes[:30] == [200] * 30 and codes[30] == 429


class TestModels:

    def test_models_new_tables_no_migration_needed(self, db):
        """team_signup_periods, team_signups (unique period+captain) and team_signup_players (unique signup+account_id) exist via create_all; migrate.py has no ALTER for them."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.exc import IntegrityError
        tables = set(sa_inspect(db.get_bind()).get_table_names())
        assert {"team_signup_periods", "team_signups", "team_signup_players"} <= tables
        p = _period(db)
        cap = _user(db, "cap")
        db.add_all([TeamSignup(period_id=p.id, captain_user_id=cap.id, team_name="A", contact="c",
                               created_at=1, updated_at=1),
                    TeamSignup(period_id=p.id, captain_user_id=cap.id, team_name="B", contact="c",
                               created_at=1, updated_at=1)])
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        s = _save(db, cap, players=[5])
        db.add(TeamSignupPlayer(signup_id=s.id, account_id=5, added_at=1))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(TeamSignupPeriod(label="Second open", opened_at=1))
        with pytest.raises(IntegrityError):   # one open period at a time
            db.commit()
        db.rollback()
        migrate_src = (pathlib.Path(__file__).resolve().parents[1] / "migrate.py").read_text()
        assert "team_signup" not in migrate_src

    def test_season_reset_leaves_listings_intact(self, db, monkeypatch):
        """Listings don't reference teams or players by foreign key, so a season Reset leaves them intact."""
        from routers import admin_season
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(db.get_bind())
        for table in ("team_signups", "team_signup_players", "team_signup_periods"):
            targets = {fk["referred_table"] for fk in insp.get_foreign_keys(table)}
            assert not targets & {"teams", "players"}, table
        _period(db)
        db.add(Player(id=222, name="Miracle", avatar_url="", is_active=True))
        db.commit()
        _save(db, _user(db, "cap"), players=[222, 333])
        admin = _user(db, "boss", admin=True)
        monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda: "/tmp/backup.db")
        admin_season.reset_season(admin_season.SeasonResetBody(force=True), db=db,
                                  admin={"user_id": admin.id, "username": "boss", "is_admin": True})
        assert db.query(Player).count() == 0
        assert db.query(TeamSignup).count() == 1 and sorted(_players(db, db.query(TeamSignup).one().id)) == [222, 333]
        assert db.query(TeamSignupPlayer).filter_by(account_id=222).one().name == "Miracle"
        assert _ts().is_open(db)


# ===========================================================================
# Security review: captains can't drain the server's OpenDota capacity
# ===========================================================================

class TestOpenDotaBudget:

    def test_lookup_per_user_hourly_cap(self, db, opendota):
        """Each user gets CAPTAIN_USER_PER_HOUR uncached OpenDota lookups per rolling hour; beyond it ids come back as Unknown player at once, with no call. Cached ids still resolve."""
        import player_lookup
        cap = player_lookup.CAPTAIN_USER_PER_HOUR
        assert cap <= 20
        _period(db)
        bob, eve = _user(db, "bob"), _user(db, "eve")
        client = _public_client(db, bob)
        ids = list(range(5000, 5000 + cap + 3))
        out = []
        for i in range(0, len(ids), 8):
            out += client.get("/team-signup/lookup", params={"ids": ",".join(map(str, ids[i:i + 8]))}).json()
        assert len(opendota) == cap
        assert [o["source"] for o in out[cap:]] == [None] * 3 and all(o["name"] is None for o in out[cap:])
        before = len(opendota)
        assert client.get("/team-signup/lookup?ids=5000").json()[0]["account_id"] == 5000   # cached: no call
        assert len(opendota) == before
        res = _public_client(db, eve).get("/team-signup/lookup?ids=6000").json()   # another user's budget
        assert len(opendota) == before + 1 and res[0]["account_id"] == 6000
        # An hour later the user's budget is back.
        assert player_lookup.captain_lookup(7000, bob.id, wall=time.time() + 3601) is not None
        assert opendota[-1] == 7000

    def test_lookup_global_hourly_cap(self, db, opendota):
        """All captains together get CAPTAIN_TOTAL_PER_HOUR uncached lookups per hour; then every user gets Unknown player without a call."""
        import player_lookup
        total = player_lookup.CAPTAIN_TOTAL_PER_HOUR
        assert total <= 60
        per_user = player_lookup.CAPTAIN_USER_PER_HOUR
        for n in range(total):
            player_lookup.captain_lookup(10_000 + n, f"user{n // per_user}")
        assert len(opendota) == total
        assert player_lookup.captain_lookup(20_000, "fresh-user") == (False, None, None, None)
        assert len(opendota) == total
        assert player_lookup.cached(20_000) is None   # refused ids aren't cached: retried later

    def test_lookup_never_blocks_when_rate_window_full(self, db, monkeypatch, opendota):
        """With the shared OpenDota window full, a captain lookup answers Unknown player at once (try_throttle, no sleep, no call); admin and ingest still use the blocking throttle."""
        import opendota_client
        import player_lookup
        monkeypatch.setattr(opendota_client, "_req_times", [time.time()] * 200)
        slept = []
        monkeypatch.setattr(opendota_client.time, "sleep", lambda s: slept.append(s))
        assert opendota_client.try_throttle() is False and slept == []
        assert len(opendota_client._req_times) == 200   # a refused try takes no slot
        monkeypatch.setattr(player_lookup, "try_throttle", opendota_client.try_throttle)
        _period(db)
        t0 = time.monotonic()
        out = _public_client(db, _user(db, "bob")).get("/team-signup/lookup?ids=222,333").json()
        assert time.monotonic() - t0 < 2 and slept == []
        assert [(o["name"], o["source"]) for o in out] == [(None, None), (None, None)]
        assert opendota == []
        monkeypatch.setattr(opendota_client, "_req_times", [])
        assert opendota_client.try_throttle() is True and len(opendota_client._req_times) == 1
        src = inspect.getsource(player_lookup.captain_lookup)
        assert "try_throttle()" in src and "opendota_get_json_once" in src and "opendota_get_json(" not in src

    def test_lookup_stops_calling_after_a_failure(self, db, monkeypatch):
        """After one failed OpenDota call in a request, the remaining ids skip OpenDota."""
        import player_lookup
        calls = []
        monkeypatch.setattr(player_lookup, "opendota_get_json_once", lambda url, **k: calls.append(url))
        _period(db)
        _public_client(db, _user(db, "bob")).get("/team-signup/lookup?ids=1,2,3,4")
        assert len(calls) == 1

    def test_lookup_refused_when_no_period_open(self, db, opendota):
        """GET /team-signup/lookup answers 409 while no signup period is open, without calling OpenDota."""
        client = _public_client(db, _user(db, "bob"))
        assert client.get("/team-signup/lookup?ids=222").status_code == 409
        _period(db)
        assert client.get("/team-signup/lookup?ids=222").status_code == 200
        _ts().close_period(db)
        db.commit()
        res = client.get("/team-signup/lookup?ids=333")
        assert res.status_code == 409 and res.json()["detail"] == "Signup is closed"
        assert opendota == [222]

    def test_save_makes_no_opendota_call(self, db, opendota):
        """PUT /team-signup/mine uses the pool and the lookup cache only: an id not known there is stored as Unknown player, with no OpenDota call."""
        _period(db)
        db.add(Player(id=111, name="Pooled", avatar_url="", is_active=True))
        db.commit()
        _looked_up(db, 222)
        assert opendota == [222]
        mine = _public_client(db, _user(db, "bob")).put("/team-signup/mine", json=_body(players=[111, 222, 333])).json()
        assert opendota == [222]
        assert [(p["account_id"], p["name"]) for p in mine["players"]] == [(111, "Pooled"), (222, "Miracle"), (333, None)]

    def test_opendota_names_cleaned_before_caching(self, db, monkeypatch):
        """OpenDota personanames pass through clean_display_text (control and bidi characters dropped, 64 characters at most) before they are cached or stored; the admin lookup gets the cleaned name too."""
        import player_lookup
        from routers import admin_players as ap
        raw = "Evil\u202e\u200bName\n" + "x" * 100
        fake = lambda *a, **k: {"profile": {"personaname": raw}, "rank_tier": 45}   # noqa: E731
        monkeypatch.setattr(player_lookup, "opendota_get_json_once", fake)
        monkeypatch.setattr(ap, "opendota_get_json", fake)
        _period(db)
        out = _public_client(db, _user(db, "bob")).get("/team-signup/lookup?ids=4242").json()[0]
        assert out["name"] == ("EvilName" + "x" * 100)[:64] and len(out["name"]) == 64
        assert player_lookup.cached(4242)[1] == out["name"]
        assert ap._opendota_name(4343) == (True, out["name"])
        blank = lambda *a, **k: {"profile": {"personaname": "\u200b\u202e"}}   # noqa: E731
        monkeypatch.setattr(player_lookup, "opendota_get_json_once", blank)
        assert player_lookup.captain_lookup(4444, "u")[1] == "4444"
