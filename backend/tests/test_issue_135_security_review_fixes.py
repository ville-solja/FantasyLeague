"""
Tests for plan-issue-135-security-review-fixes.md (resolves GitHub issue #135).

An external manual review (SECURITY_REVIEW.md, 2026-09-26) listed 20 findings;
the plan triages them into five user stories. One test per acceptance
criterion (happy path plus the primary failure path for each).

Testing approach per story (copy the fixtures from the named precedent files):

  Story 1 — Twitch MVP and Token Drops Only for Real, Recent Matches
    - `set_mvp` / `current_matches` in `backend/twitch.py`. Bypass JWT
      validation with `monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")` (and no
      production marker) the way the Twitch tests do, or override
      `verify_twitch_jwt` via `app.dependency_overrides`. PubSub HTTP is
      skipped under TWITCH_LOCAL_DEV; never hit the real Twitch API.
    - Seed `Match` / `PlayerMatchStats` / monitored league rows in the
      conftest `db` fixture so a match is inside (or outside) the series
      window `GET /twitch/matches/current` offers.
    - "Writes nothing" assertions check `twitch_mvp`, `twitch_token_drops`
      and `PlayerMatchStats.is_mvp` are unchanged.
    - `TWITCH_MVP_CHANNEL_IDS` is set/unset with monkeypatch.setenv/delenv.
    - `/twitch/link` rate limit: TestClient against a reloaded app, following
      test_issue_121_rate_limiting.py / test_issue_124_...py — reload
      `rate_limit` (fresh Limiter, empty counters), then `twitch`, then
      `main`, in that order; disable routers.auth's unrelated limiter.

  Story 2 — External Text Is Always Escaped
    - No JS runtime/DOM is available, so these are static source checks on
      `frontend/*.js` (precedent: test_issue_115_username_xss_fix.py). Named
      sites:
        app-players.js: player profile `profile.bio_text`, `heroLine()`
          `h.hero_name`, every `facts.*` in the stat grid
          (`facts.kanaliiga_seasons`, `facts.role_tendency`, ...), player /
          team name cells (`p.name` in the players table and team modal),
          schedule `time`, `s.stream_label`, team labels, `data.error`,
          `p.avatar_url` in `<img src>`, `s.stream_url` in `<a href>`,
          hero icon `url` in `_gameHeroIconsHtml`.
        app-roster.js: card `alt="${c.player_name}"` and the `onerror`
          fallback's `${c.player_name}`.
        app-admin-ingest.js: audit log `r.action` and `r.detail`.
        app-globals.js: new `_safeUrl()` helper beside `_escHtml`.
    - The failure-path stub proves the checker flags a planted raw
      interpolation, so the static checks cannot pass vacuously.

  Story 3 — Reliable and Safe Password Reset
    - TestClient with SessionMiddleware as in
      test_issue_123_password_reset_token_flow.py and
      test_issue_122_forgot_password_cooldown.py. `send_email` is ALWAYS
      monkeypatched (to return True or False) in the router module that
      calls it — never hit real SMTP.

  Story 4 — Abuse Limits on Public and Bulk Endpoints
    - Rate limits: same reload caveats as Story 1 (reload `rate_limit`, then
      the router under test — routers.admin_users / routers.auth /
      routers.cards — then `main`). Handlers are wrapped in `*_route`
      functions so direct calls in older tests still work.
    - Card image rendering fetches external images; monkeypatch the image
      render/fetch helpers so no network call is made (no OpenDota/Steam).
    - Bounds (`Field(max_length=...)`, `Field(le=...)`, `Query(le=...)`)
      are checked via Pydantic model validation or TestClient 422s.

  Story 5 — Deployment and File Hardening
    - SRI: static parse of `frontend/index.html`; never fetch the CDN.
    - Tags: `TagBody` validation (precedent: test_user_tag_system.py).
    - Stickers: `image._apply_stickers` with `image.STICKER_DIR`
      monkeypatched to a tmp_path directory.
    - Backups: `monkeypatch.setattr(database, "DATABASE_URL",
      f"sqlite:///{tmp_path / 'fantasy.db'}")` as in
      test_issue_132_admin_db_backup.py — never touch the real data/ dir.
      Season-reset abort monkeypatches `backup_sqlite_db` to return None.

Note for the implementer: adding this file changes the suite size; bump the
tripwire in test_issue_85_split_admin_router.py as the plan says.

Manual verification (not automated):
  - Seed a player named `<img src=x onerror=alert(1)>` with the same text in
    the bio. The Players tab, player and team popups, and My Team show the
    text literally and no alert fires.
  - The browser console shows no SRI errors, and Alpine-driven UI (How to
    Play subtabs) still works with the pinned version.
  - With SMTP pointed at a closed port, the Forgot Password form shows the
    503 error and a second attempt is not blocked by the cooldown.
  - On the host, a newly written backup file shows mode `-rw-------`.

Run with: cd backend && python3 -m pytest tests/test_issue_135_security_review_fixes.py -v
"""

import importlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from html.parser import HTMLParser
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

import database
from database import Base, get_db
from deps import require_admin
from models import (AuditLog, Card, Match, PasswordResetToken, Player,
                    PlayerMatchStats, Team, TwitchMVP, TwitchPresence,
                    TwitchTokenDrop, User, Weight)
from auth import hash_password

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_FRONTEND_DIR = os.path.abspath(os.path.join(_BACKEND_DIR, "..", "frontend"))

_ADMIN = {"user_id": 1, "username": "admin"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_app(router_module_names, *, rate_limited=False, admin_override=False):
    """Minimal app around the named router modules, backed by a fresh in-memory DB.

    Reloads `rate_limit` first, then each router module, so every call starts
    with a brand-new Limiter (empty counters) that the reloaded routers'
    @limiter.limit decorators are bound to (test_issue_121/124 precedent).
    When rate_limited is False the fresh limiter is disabled.

    Adds a test-only POST /_test/login/{user_id} that starts a session the way
    /login does (a server-side user_sessions row; the cookie holds only {"sid"},
    issue #117), and GET /_test/session that echoes the cookie payload back.
    """
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    import rate_limit
    importlib.reload(rate_limit)
    # Import-then-reload would decorate twice against the same fresh limiter
    # and count every request twice, so reload only modules already loaded.
    modules = [importlib.reload(sys.modules[n]) if n in sys.modules else importlib.import_module(n)
               for n in router_module_names]
    rate_limit.limiter.enabled = rate_limited

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-135")
    app.state.limiter = rate_limit.limiter
    for m in modules:
        app.include_router(m.router)

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if admin_override:
        app.dependency_overrides[require_admin] = lambda: dict(_ADMIN)

    @app.post("/_test/login/{user_id}")
    def _test_login(user_id: int, request: Request):
        import sessions
        db = Session()
        try:
            user = db.get(User, user_id)
            assert user is not None, f"seed user {user_id} before logging in"
            sessions.start_session(request, db, user)
            db.commit()
        finally:
            db.close()
        return {"ok": True}

    @app.get("/_test/session")
    def _test_session(request: Request):
        return dict(request.session)

    return app, Session


def _add_user(Session_or_db, user_id=1, username="alice", email="alice@example.com",
              password="secret123", tokens=5):
    db = Session_or_db() if callable(Session_or_db) else Session_or_db
    user = User(id=user_id, username=username, email=email,
                password_hash=hash_password(password), tokens=tokens,
                created_at=int(time.time()))
    db.add(user)
    db.commit()
    if callable(Session_or_db):
        db.close()
    return user_id


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Story 1 — Twitch MVP and Token Drops Only for Real, Recent Matches
# ---------------------------------------------------------------------------

import twitch  # noqa: E402

_BROADCASTER = {"channel_id": "test_channel", "role": "broadcaster", "opaque_user_id": "Utest"}


@pytest.fixture
def twitch_env(monkeypatch):
    """No real Twitch calls: PubSub/chat short-circuit under TWITCH_LOCAL_DEV."""
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)


def _seed_match(db, match_id, team1_id, team2_id, start_time, player_ids=None, with_stats=True):
    for tid in (team1_id, team2_id):
        if not db.get(Team, tid):
            db.add(Team(id=tid, name=f"Team{tid}"))
    db.add(Match(match_id=match_id, radiant_team_id=team1_id, dire_team_id=team2_id,
                 start_time=start_time, radiant_win=True))
    if with_stats:
        for i, pid in enumerate(player_ids or ()):
            if not db.get(Player, pid):
                db.add(Player(id=pid, name=f"Player{pid}"))
            db.add(PlayerMatchStats(player_id=pid, match_id=match_id,
                                    team_id=team1_id if i % 2 == 0 else team2_id,
                                    fantasy_points=10.0, kills=3, is_mvp=False))
    db.commit()


def _seed_world(db):
    """Six series (only the five newest are offered), a future match with stats,
    and a recent match with no ingested stats."""
    now = int(time.time())
    if not db.query(Weight).filter_by(key="mvp_bonus_pct").first():
        db.add(Weight(key="mvp_bonus_pct", label="MVP bonus (%)", value=10.0))
    # Series k uses teams (10k+1, 10k+2); series 1 is the newest.
    for k in range(1, 7):
        _seed_match(db, 1000 + k, 10 * k + 1, 10 * k + 2, now - 3600 * k,
                    player_ids=(100 + 2 * k, 100 + 2 * k + 1))
    # Future match (not started yet) with stats.
    _seed_match(db, 2001, 91, 92, now + 3600, player_ids=(190, 191))
    # Recent, started match with no ingested stats.
    _seed_match(db, 3001, 93, 94, now - 60, with_stats=False)
    return {
        "eligible": 1001, "eligible_player": 102, "other_match_player": 104,
        "outside_window": 1006, "outside_window_player": 112,
        "future": 2001, "no_stats": 3001,
    }


def _assert_nothing_written(db):
    db.expire_all()
    assert db.query(TwitchMVP).count() == 0
    assert db.query(TwitchTokenDrop).count() == 0
    assert db.query(PlayerMatchStats).filter(PlayerMatchStats.is_mvp == True).count() == 0  # noqa: E712
    assert db.query(AuditLog).filter(AuditLog.action.like("twitch_%")).count() == 0


def _call_set_mvp(db, match_id, player_id, payload=_BROADCASTER):
    return twitch.set_mvp(twitch.MVPBody(match_id=match_id, player_id=player_id),
                          payload=dict(payload), db=db)


def test_set_mvp_unknown_match_returns_404_and_writes_nothing(db, twitch_env):
    """POST /twitch/mvp returns 404 for a nonexistent match, before any MVP row, bonus or drop is written."""
    w = _seed_world(db)
    with pytest.raises(HTTPException) as exc:
        _call_set_mvp(db, 987654321, w["eligible_player"])
    assert exc.value.status_code == 404
    _assert_nothing_written(db)


def test_set_mvp_eligible_match_sets_mvp_and_drops_tokens(db, twitch_env):
    """An eligible match in the current series window still sets the MVP, applies the bonus and drops tokens."""
    w = _seed_world(db)
    now = int(time.time())
    db.add(User(id=50, username="viewer", tokens=0, twitch_user_id="Uviewer"))
    db.add(TwitchPresence(twitch_user_id="Uviewer", channel_id="test_channel", seen_at=now))
    db.commit()

    result = _call_set_mvp(db, w["eligible"], w["eligible_player"])

    assert result["player_id"] == w["eligible_player"]
    assert result["token_drop"]["winners"] == ["viewer"]
    db.expire_all()
    mvp = db.query(TwitchMVP).filter_by(match_id=w["eligible"]).one()
    assert mvp.player_id == w["eligible_player"]
    row = db.query(PlayerMatchStats).filter_by(match_id=w["eligible"],
                                               player_id=w["eligible_player"]).one()
    assert row.is_mvp is True
    assert row.fantasy_points != pytest.approx(10.0)  # recomputed with the MVP bonus
    assert db.get(User, 50).tokens == 1
    assert db.query(TwitchTokenDrop).filter_by(channel_id="test_channel",
                                               series_id=str(w["eligible"])).count() == 1


def test_set_mvp_match_outside_series_window_returns_403(db, twitch_env):
    """POST /twitch/mvp returns 403 for a real match that GET /twitch/matches/current does not offer; nothing written."""
    w = _seed_world(db)
    for match_id, player_id in ((w["outside_window"], w["outside_window_player"]),
                                (w["future"], 190)):
        with pytest.raises(HTTPException) as exc:
            _call_set_mvp(db, match_id, player_id)
        assert exc.value.status_code == 403
    _assert_nothing_written(db)


def test_set_mvp_match_without_ingested_stats_returns_403(db, twitch_env):
    """A recent match with no ingested stats (or not in a monitored league) is not eligible: 403."""
    w = _seed_world(db)
    with pytest.raises(HTTPException) as exc:
        _call_set_mvp(db, w["no_stats"], w["eligible_player"])
    assert exc.value.status_code == 403
    _assert_nothing_written(db)


def test_set_mvp_eligible_ids_match_current_matches_helper(db, twitch_env):
    """The eligibility helper returns exactly the match IDs current_matches() offers."""
    w = _seed_world(db)
    offered = twitch.current_matches(payload=dict(_BROADCASTER), db=db)
    offered_ids = {m["match_id"] for s in offered["series"] for m in s["matches"]}
    assert len(offered["series"]) == 5
    assert offered_ids == {1001, 1002, 1003, 1004, 1005}
    assert twitch._eligible_mvp_match_ids(db) == offered_ids
    assert w["outside_window"] not in offered_ids
    # Output shape unchanged: newest series first, per-match player lists intact.
    first = offered["series"][0]
    assert first["team1_name"] == "Team11" and first["team2_name"] == "Team12"
    assert first["matches"][0]["match_number"] == 1
    assert {p["player_id"] for p in first["matches"][0]["players"]} == {102, 103}


def test_set_mvp_player_not_in_match_returns_404(db, twitch_env):
    """POST /twitch/mvp returns 404 when the player has no stat row for that match; nothing written."""
    w = _seed_world(db)
    for player_id in (w["other_match_player"], 99999):
        with pytest.raises(HTTPException) as exc:
            _call_set_mvp(db, w["eligible"], player_id)
        assert exc.value.status_code == 404
    _assert_nothing_written(db)


def test_set_mvp_channel_not_in_allowlist_returns_403(db, twitch_env, monkeypatch):
    """With TWITCH_MVP_CHANNEL_IDS set, a channel not in the list gets 403 and nothing is written."""
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "111, 222")
    w = _seed_world(db)
    outsider = {**_BROADCASTER, "channel_id": "333"}
    # The allowlist check runs first, so every request gets the same 403 and an
    # outside channel learns nothing about which match or player IDs exist.
    for match_id, player_id in ((w["eligible"], w["eligible_player"]),
                                (987654321, w["eligible_player"]),
                                (w["outside_window"], w["outside_window_player"]),
                                (w["eligible"], 99999)):
        with pytest.raises(HTTPException) as exc:
            _call_set_mvp(db, match_id, player_id, payload=outsider)
        assert exc.value.status_code == 403
        assert exc.value.detail == "This channel cannot set match MVPs"
    _assert_nothing_written(db)


def test_set_mvp_allowlisted_channel_succeeds(db, twitch_env, monkeypatch):
    """With TWITCH_MVP_CHANNEL_IDS set (comma-separated), a listed channel can set the MVP."""
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "111, 222")
    w = _seed_world(db)
    result = _call_set_mvp(db, w["eligible"], w["eligible_player"],
                           payload={**_BROADCASTER, "channel_id": "222"})
    assert result["player_id"] == w["eligible_player"]
    assert db.query(TwitchMVP).filter_by(match_id=w["eligible"], channel_id="222").count() == 1


def test_set_mvp_allowlist_unset_allows_any_channel(db, twitch_env, monkeypatch):
    """With TWITCH_MVP_CHANNEL_IDS unset, any channel can set an MVP on an eligible match (today's behaviour)."""
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    w = _seed_world(db)
    result = _call_set_mvp(db, w["eligible"], w["eligible_player"],
                           payload={**_BROADCASTER, "channel_id": "any-channel-xyz"})
    assert result["player_id"] == w["eligible_player"]
    assert db.query(TwitchMVP).filter_by(match_id=w["eligible"]).count() == 1


def test_link_code_generated_with_secrets(db, monkeypatch):
    """POST /twitch/link-code generates the code with the secrets module (6 chars, A-Z0-9)."""
    _add_user(db, user_id=7, username="linker", email="linker@example.com")
    calls = []
    real_choice = twitch.secrets.choice

    def _spy(seq):
        calls.append(seq)
        return real_choice(seq)

    monkeypatch.setattr(twitch.secrets, "choice", _spy)
    result = twitch.generate_link_code(current_user={"user_id": 7}, db=db)
    assert re.fullmatch(r"[A-Z0-9]{6}", result["code"])
    assert len(calls) == 6


def test_link_code_does_not_use_random_module():
    """twitch.py's link-code generation no longer calls random.choices."""
    import inspect
    src = inspect.getsource(twitch.generate_link_code)
    assert "random." not in src
    assert "secrets.choice" in src
    assert "random.choices" not in _read(os.path.join(_BACKEND_DIR, "twitch.py"))


def _twitch_link_client(monkeypatch):
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    app, _ = _build_app(["twitch"], rate_limited=True)
    return TestClient(app)


def _post_link(client):
    return client.post("/twitch/link", json={"code": "ZZZZZZ"},
                       headers={"Authorization": "Bearer dev"})


def test_twitch_link_first_ten_requests_not_rate_limited(db, monkeypatch):
    """POST /twitch/link allows 10 requests a minute from one client IP."""
    client = _twitch_link_client(monkeypatch)
    for _ in range(10):
        resp = _post_link(client)
        assert resp.status_code == 400  # invalid code, but not rate limited


def test_twitch_link_eleventh_request_returns_429(db, monkeypatch):
    """The 11th POST /twitch/link from the same IP within a minute returns 429."""
    client = _twitch_link_client(monkeypatch)
    for _ in range(10):
        assert _post_link(client).status_code == 400
    blocked = _post_link(client)
    assert blocked.status_code == 429
    # A different client IP has its own budget.
    other = TestClient(client.app, client=("10.9.9.9", 1234))
    assert _post_link(other).status_code == 400


# ---------------------------------------------------------------------------
# Story 2 — External Text Is Always Escaped (static checks on frontend/*.js)
# ---------------------------------------------------------------------------

_SAFE_BUILDERS = ("_escHtml", "playerLink", "teamLink", "heroSection")


def _template_expressions(src):
    """Every `${...}` expression body in the source (nested ones included)."""
    out = []
    for m in re.finditer(r"\$\{", src):
        depth, i = 1, m.end()
        while i < len(src) and depth:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        out.append(src[m.end():i - 1])
    return out


def _strip_safe_calls(expr, builders=_SAFE_BUILDERS):
    """Remove every `builder(...)` call (balanced parens) from expr."""
    pattern = re.compile(r"\b(?:%s)\(" % "|".join(map(re.escape, builders)))
    while True:
        m = pattern.search(expr)
        if not m:
            return expr
        depth, i = 1, m.end()
        while i < len(expr) and depth:
            if expr[i] == "(":
                depth += 1
            elif expr[i] == ")":
                depth -= 1
            i += 1
        expr = expr[:m.start()] + expr[i:]


def _raw_interpolations(src, field_patterns):
    """Template expressions that still reference a field after safe calls are removed."""
    regexes = [re.compile(p) for p in field_patterns]
    bad = []
    for expr in _template_expressions(src):
        stripped = _strip_safe_calls(expr)
        if any(r.search(stripped) for r in regexes):
            bad.append(expr)
    return bad


def _players_js():
    return _read(os.path.join(_FRONTEND_DIR, "app-players.js"))


def _function_source(src, name):
    m = re.search(r"function\s+%s\s*\(" % re.escape(name), src)
    assert m, f"{name}() not found"
    start = src.index("{", m.end())
    depth, i = 0, start
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():i + 1]
        i += 1


def test_player_profile_bio_text_escaped():
    """app-players.js renders profile.bio_text through _escHtml (or textContent)."""
    src = _players_js()
    assert "_escHtml(profile.bio_text)" in src
    assert _raw_interpolations(src, [r"\bprofile\.bio_text\b"]) == []


def test_player_profile_hero_names_escaped():
    """heroLine() in app-players.js wraps h.hero_name in _escHtml."""
    fn = _function_source(_players_js(), "heroLine")
    assert fn.count("_escHtml(h.hero_name)") == 2
    assert _raw_interpolations(fn, [r"\bh\.hero_name\b"]) == []


def test_player_profile_facts_values_escaped():
    """Every facts.* value in the player profile stat grid is escaped with _escHtml or set via textContent."""
    fn = _function_source(_players_js(), "renderPlayerProfile")
    for field in ("kanaliiga_seasons", "role_tendency", "avg_kills", "avg_deaths",
                  "avg_assists", "avg_gpm", "avg_wards"):
        assert f"facts.{field}" in fn
    assert _raw_interpolations(fn, [r"\bfacts\.\w+"]) == []


def test_players_table_player_and_team_names_escaped():
    """Player names and team names in app-players.js tables and the team modal are escaped."""
    src = _players_js()
    fields = [r"\bp\.name\b", r"\bp\.team_name\b", r"\bt\.name\b",
              r"\bm\.opponent_team_name\b", r"\bg\.mvp_player_name\b"]
    assert _raw_interpolations(src, fields) == []
    team_modal = _function_source(src, "openTeamModal")
    assert "_escHtml(p.name)" in team_modal


def test_schedule_time_stream_label_and_team_labels_escaped():
    """Schedule time, s.stream_label and team labels in app-players.js are escaped."""
    fn = _function_source(_players_js(), "loadSchedule")
    fields = [r"\bs\.time\b", r"\bs\.stream_label\b", r"\bs\.team1\b", r"\bs\.team2\b"]
    assert _raw_interpolations(fn, fields) == []
    assert "_escHtml(s.time)" in fn
    assert "_escHtml(s.stream_label)" in fn


def test_schedule_data_error_escaped():
    """The schedule's data.error message is escaped before innerHTML."""
    fn = _function_source(_players_js(), "loadSchedule")
    assert "_escHtml(data.error)" in fn
    assert _raw_interpolations(fn, [r"\bdata\.error\b"]) == []


def test_roster_card_alt_and_onerror_escape_player_name():
    """app-roster.js escapes c.player_name in the card img alt attribute and the onerror fallback."""
    src = _read(os.path.join(_FRONTEND_DIR, "app-roster.js"))
    slot = _function_source(src, "_cardSlotHTML")
    assert 'alt="${_escHtml(c.player_name)}"' in slot
    assert _raw_interpolations(slot, [r"\bc\.player_name\b"]) == []
    onerror = re.search(r'onerror="([^"]*)"', slot).group(1)
    assert "player_name" not in onerror  # name is not spliced into inline HTML/JS
    fallback = _function_source(src, "_cardImgFallback")
    assert "textContent" in fallback and "innerHTML" not in fallback and "outerHTML" not in fallback


def _safe_url_source():
    return _function_source(_read(os.path.join(_FRONTEND_DIR, "app-globals.js")), "_safeUrl")


def test_safe_url_helper_defined_in_app_globals():
    """app-globals.js defines _safeUrl(u) returning u only for http:// or https://, otherwise ''."""
    src = _safe_url_source()
    assert "https?" in src
    node = shutil.which("node")
    if not node:
        return
    cases = ["https://a.example/x.png", "http://b.example", "javascript:alert(1)",
             "data:text/html,x", "", None, "  https://c.example/y  ", "/relative.png"]
    script = src + "\nconsole.log(JSON.stringify(%s.map(_safeUrl)));" % json.dumps(cases)
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["https://a.example/x.png", "http://b.example", "", "",
                                      "", "", "https://c.example/y", ""]


def test_urls_in_src_and_href_use_safe_url_and_esc_html():
    """p.avatar_url, s.stream_url and hero icon URLs are placed as _escHtml(_safeUrl(...))."""
    src = _players_js()
    attrs = re.findall(r'(?:src|href)="\$\{([^"]*)\}"', src)
    assert attrs, "no interpolated src/href attributes found"
    for expr in attrs:
        assert expr.startswith("_escHtml(_safeUrl("), expr
    assert "_escHtml(_safeUrl(p.avatar_url))" in src
    assert "_escHtml(_safeUrl(s.stream_url))" in src
    assert "_escHtml(_safeUrl(url))" in _function_source(src, "_gameHeroIconsHtml")
    # DOM-property assignments of external URLs go through _safeUrl too.
    assert not re.search(r"\.src\s*=\s*p\.avatar_url", src)


def test_audit_log_action_and_detail_escaped():
    """app-admin-ingest.js audit log wraps r.action and r.detail in _escHtml."""
    src = _read(os.path.join(_FRONTEND_DIR, "app-admin-ingest.js"))
    fn = _function_source(src, "loadAuditLog")
    assert "_escHtml(r.action)" in fn
    assert "_escHtml(r.detail" in fn
    assert _raw_interpolations(fn, [r"\br\.action\b", r"\br\.detail\b"]) == []


def test_escaping_checker_flags_raw_interpolation():
    """The static checker fails on a planted raw ${p.name} / ${profile.bio_text} interpolation (not vacuous)."""
    planted = 'x = `<td>${p.name}</td><div>${profile.bio_text}</div><b>${_escHtml(p.name)}</b>`;'
    bad = _raw_interpolations(planted, [r"\bp\.name\b", r"\bprofile\.bio_text\b"])
    assert bad == ["p.name", "profile.bio_text"]
    nested = 'y = `${ok ? `<i>${facts.role_tendency}</i>` : ""}`;'
    assert _raw_interpolations(nested, [r"\bfacts\.\w+"])
    mixed = '`${p.team_id ? teamLink(p.team_id, p.team_name) : (p.team_name || "-")}`'
    assert _raw_interpolations(mixed, [r"\bp\.team_name\b"])


# ---------------------------------------------------------------------------
# Story 3 — Reliable and Safe Password Reset (send_email always monkeypatched)
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_app(monkeypatch):
    monkeypatch.delenv("FORGOT_PASSWORD_COOLDOWN_SECONDS", raising=False)
    # A configured SMTP host, so a False from send_email() is a real send failure.
    # send_email itself is always monkeypatched; nothing connects to this host.
    monkeypatch.setenv("SMTP_HOST", "smtp.invalid")
    app, Session = _build_app(["routers.auth", "routers.profile"])
    _add_user(Session)
    return app, Session


def _forgot(client, send_result):
    calls = []

    def fake_send_email(to_address, subject, body):
        calls.append(to_address)
        return send_result

    with patch("routers.auth.send_email", side_effect=fake_send_email):
        resp = client.post("/forgot-password", json={"username": "alice"})
    return resp, calls


def test_forgot_password_send_success_returns_ok(db, auth_app):
    """When send_email() returns True, POST /forgot-password still returns ok and stores the token."""
    app, Session = auth_app
    resp, calls = _forgot(TestClient(app), True)
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    assert calls == ["alice@example.com"]
    with Session() as s:
        assert s.query(PasswordResetToken).filter_by(user_id=1).count() == 1


def test_forgot_password_send_failure_returns_503(db, auth_app):
    """When send_email() returns False, POST /forgot-password returns 503."""
    app, _ = auth_app
    resp, calls = _forgot(TestClient(app), False)
    assert resp.status_code == 503
    assert len(calls) == 1


def test_forgot_password_send_exception_returns_503(db, auth_app):
    """A send that raises is treated like a failed send: 503 and no token kept."""
    app, Session = auth_app

    def boom(to_address, subject, body):
        raise OSError("connection refused")

    with patch("routers.auth.send_email", side_effect=boom):
        resp = TestClient(app).post("/forgot-password", json={"username": "alice"})
    assert resp.status_code == 503
    with Session() as s:
        assert s.query(PasswordResetToken).count() == 0


def test_forgot_password_smtp_unconfigured_keeps_dev_fallback(db, auth_app, monkeypatch):
    """With SMTP_HOST unset, send_email() returns False without trying; the request
    still returns ok and keeps the token (the documented local-dev fallback)."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    import email_utils
    app, Session = auth_app
    with patch("routers.auth.send_email", side_effect=email_utils.send_email) as spy:
        resp = TestClient(app).post("/forgot-password", json={"username": "alice"})
    assert spy.call_count == 1
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    with Session() as s:
        assert s.query(PasswordResetToken).filter_by(user_id=1).count() == 1
        assert s.query(AuditLog).filter_by(action="password_reset_requested").count() == 1


def test_email_configured_reflects_smtp_host(monkeypatch):
    """email_configured() is True only when SMTP_HOST is set."""
    import email_utils
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert email_utils.email_configured() is False
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    assert email_utils.email_configured() is True


def test_forgot_password_send_failure_rolls_back_token_and_cooldown(db, auth_app):
    """On send failure the new token and cooldown stamp are rolled back, so a retry is not blocked by the cooldown."""
    app, Session = auth_app
    import routers.auth as auth_router
    client = TestClient(app)
    resp, _ = _forgot(client, False)
    assert resp.status_code == 503
    with Session() as s:
        assert s.query(PasswordResetToken).count() == 0
        assert s.query(AuditLog).filter_by(action="password_reset_requested").count() == 0
    assert "alice" not in auth_router._last_forgot_password_request

    retry, calls = _forgot(client, True)
    assert retry.status_code == 200
    assert len(calls) == 1  # not suppressed by the cooldown
    with Session() as s:
        assert s.query(PasswordResetToken).filter_by(user_id=1).count() == 1


def test_forgot_password_send_failure_keeps_previous_token(db, auth_app):
    """On send failure the user's previous, still-valid reset token is not deleted."""
    app, Session = auth_app
    with Session() as s:
        s.add(PasswordResetToken(token="previous-token", user_id=1,
                                 expires_at=int(time.time()) + 3600))
        s.commit()
    resp, _ = _forgot(TestClient(app), False)
    assert resp.status_code == 503
    with Session() as s:
        tokens = [t.token for t in s.query(PasswordResetToken).filter_by(user_id=1).all()]
    assert tokens == ["previous-token"]


def _register(client, email, password="secret123", username="newbie"):
    return client.post("/register", json={"username": username, "email": email,
                                          "password": password})


def test_register_accepts_valid_email(db, auth_app):
    """Registration accepts an address matching [A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}."""
    app, Session = auth_app
    client = TestClient(app)
    resp = _register(client, "first.last+tag_1%x@sub-domain.example.co")
    assert resp.status_code == 200, resp.text
    with Session() as s:
        assert s.query(User).filter_by(username="newbie").one().email == "first.last+tag_1%x@sub-domain.example.co"


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "a@b.c", "a b@c.com"])
def test_register_rejects_malformed_email_422(db, auth_app, email):
    """Registration rejects email addresses that do not match the strict pattern with 422."""
    app, Session = auth_app
    resp = _register(TestClient(app), email)
    assert resp.status_code == 422
    with Session() as s:
        assert s.query(User).filter_by(username="newbie").count() == 0


@pytest.mark.parametrize("email", ["a@b.com\nc@d.com", "a@b.com\r\nBcc: c@d.com"])
def test_register_rejects_email_with_crlf_422(db, auth_app, email):
    """Registration rejects email addresses containing CR or LF with 422."""
    app, Session = auth_app
    resp = _register(TestClient(app), email)
    assert resp.status_code == 422
    with Session() as s:
        assert s.query(User).filter_by(username="newbie").count() == 0


def _add_reset_token(Session, token="outstanding"):
    with Session() as s:
        s.add(PasswordResetToken(token=token, user_id=1, expires_at=int(time.time()) + 3600))
        s.commit()


def test_change_password_deletes_outstanding_reset_tokens(db, auth_app):
    """PUT /profile/password deletes the user's outstanding reset tokens."""
    app, Session = auth_app
    _add_reset_token(Session)
    client = TestClient(app)
    client.post("/_test/login/1")
    resp = client.put("/profile/password", json={"current_password": "secret123",
                                                  "new_password": "newsecret456"})
    assert resp.status_code == 200, resp.text
    with Session() as s:
        assert s.query(PasswordResetToken).filter_by(user_id=1).count() == 0


def test_change_password_wrong_current_password_keeps_reset_tokens(db, auth_app):
    """A rejected password change (wrong current password) leaves reset tokens untouched."""
    app, Session = auth_app
    _add_reset_token(Session)
    client = TestClient(app)
    client.post("/_test/login/1")
    resp = client.put("/profile/password", json={"current_password": "wrong-password",
                                                  "new_password": "newsecret456"})
    assert resp.status_code == 401
    with Session() as s:
        assert s.query(PasswordResetToken).filter_by(user_id=1).count() == 1


_LONG_PASSWORD = "a" * 73


@pytest.mark.parametrize("endpoint", ["register", "reset-password", "profile/password"])
def test_password_over_72_bytes_rejected_422(db, auth_app, endpoint):
    """New-password fields on register, reset and change-password reject passwords over 72 UTF-8 bytes with 422."""
    app, Session = auth_app
    client = TestClient(app)
    if endpoint == "register":
        resp = _register(client, "newbie@example.com", password=_LONG_PASSWORD)
    elif endpoint == "reset-password":
        _add_reset_token(Session, token="valid-token")
        resp = client.post("/reset-password", json={"token": "valid-token",
                                                    "new_password": _LONG_PASSWORD})
    else:
        client.post("/_test/login/1")
        resp = client.put("/profile/password", json={"current_password": "secret123",
                                                      "new_password": _LONG_PASSWORD})
    assert resp.status_code == 422, resp.text
    with Session() as s:
        user = s.get(User, 1)
        from auth import verify_password
        assert verify_password("secret123", user.password_hash)  # unchanged


def test_login_accepts_existing_password_over_72_bytes(db, auth_app):
    """Login is exempt from the cap: an account whose hash was made from a >72-byte
    password (before the cap) can still log in with it."""
    app, Session = auth_app
    long_pw = "L" * 100
    _add_user(Session, user_id=3, username="legacy", email="legacy@example.com", password=long_pw)
    resp = TestClient(app).post("/login", json={"username": "legacy", "password": long_pw})
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "legacy"


def test_change_password_accepts_current_password_over_72_bytes(db, auth_app):
    """The current password in a change-password request is not capped either."""
    app, Session = auth_app
    long_pw = "C" * 100
    _add_user(Session, user_id=3, username="legacy", email="legacy@example.com", password=long_pw)
    client = TestClient(app)
    client.post("/_test/login/3")
    resp = client.put("/profile/password", json={"current_password": long_pw,
                                                  "new_password": "newsecret456"})
    assert resp.status_code == 200, resp.text


def test_password_byte_cap_counts_utf8_bytes_not_chars():
    """A 40-character password of 2-byte characters (80 bytes) is rejected; exactly 72 ASCII bytes is accepted."""
    from routers.auth import LoginBody, RegisterBody, ResetPasswordBody
    from routers.profile import ChangePasswordBody
    two_byte = "é" * 40
    assert len(two_byte) == 40 and len(two_byte.encode("utf-8")) == 80
    assert LoginBody(username="alice", password=two_byte).password == two_byte  # login exempt
    with pytest.raises(ValidationError):
        RegisterBody(username="alice", email="alice@example.com", password=two_byte)
    with pytest.raises(ValidationError):
        ResetPasswordBody(token="t", new_password=two_byte)
    with pytest.raises(ValidationError):
        ChangePasswordBody(current_password="secret123", new_password=two_byte)
    exact = "a" * 72
    assert LoginBody(username="alice", password=exact).password == exact
    assert RegisterBody(username="alice", email="alice@example.com", password=exact).password == exact
    assert ResetPasswordBody(token="t", new_password=exact).new_password == exact
    assert ChangePasswordBody(current_password=exact, new_password=exact).new_password == exact
    assert ChangePasswordBody(current_password=two_byte, new_password=exact).current_password == two_byte


# ---------------------------------------------------------------------------
# Story 4 — Abuse Limits on Public and Bulk Endpoints
# ---------------------------------------------------------------------------

def _redeem_client():
    app, Session = _build_app(["routers.admin_users"], rate_limited=True)
    _add_user(Session, user_id=1, username="alice", email="alice@example.com")
    _add_user(Session, user_id=2, username="bob", email="bob@example.com")
    client = TestClient(app)
    client.post("/_test/login/1")
    return app, client


def test_redeem_first_five_requests_per_user_not_rate_limited(db):
    """POST /redeem allows 5 requests a minute per user."""
    _, client = _redeem_client()
    for _ in range(5):
        resp = client.post("/redeem", json={"code": "NOPE"})
        assert resp.status_code == 404  # invalid code, not rate limited


def test_redeem_sixth_request_per_user_returns_429(db):
    """The 6th POST /redeem from the same user within a minute returns 429."""
    app, client = _redeem_client()
    for _ in range(5):
        assert client.post("/redeem", json={"code": "NOPE"}).status_code == 404
    blocked = client.post("/redeem", json={"code": "NOPE"})
    assert blocked.status_code == 429
    # Keyed per user, not per IP: another user on the same IP is unaffected.
    bob = TestClient(app)
    bob.post("/_test/login/2")
    assert bob.post("/redeem", json={"code": "NOPE"}).status_code == 404


def test_reset_password_eleventh_request_per_ip_returns_429(db):
    """POST /reset-password is limited to 10 a minute per IP; the 11th returns 429."""
    app, _ = _build_app(["routers.auth"], rate_limited=True)
    client = TestClient(app)
    body = {"token": "guess", "new_password": "newsecret456"}
    for _ in range(10):
        assert client.post("/reset-password", json=body).status_code == 400
    blocked = client.post("/reset-password", json=body)
    assert blocked.status_code == 429
    other_ip = TestClient(app, client=("10.1.2.3", 5555))
    assert other_ip.post("/reset-password", json=body).status_code == 400


class _FakeImage:
    def save(self, buf, **_kwargs):
        buf.write(b"\x89PNG-fake")


@pytest.fixture
def card_image_client(monkeypatch):
    import image
    monkeypatch.setattr(image, "PIL_AVAILABLE", True)
    rendered = []

    def _fake_render(**kwargs):
        rendered.append(kwargs["player_name"])
        return _FakeImage()

    monkeypatch.setattr(image, "generate_card_image", _fake_render)
    app, Session = _build_app(["routers.cards"], rate_limited=True)
    with Session() as s:
        s.add(Player(id=1, name="Imagey"))
        s.add(Card(id=1, player_id=1, owner_id=None, card_type="common", is_active=False))
        s.commit()
    return TestClient(app), rendered


def test_card_image_under_limit_returns_image(db, card_image_client):
    """GET /cards/{card_id}/image serves normally within 60 requests a minute (renderer monkeypatched)."""
    client, rendered = card_image_client
    for _ in range(60):
        resp = client.get("/cards/1/image")
        assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == b"\x89PNG-fake"
    assert len(rendered) == 60 and rendered[0] == "Imagey"


def test_card_image_61st_request_per_ip_returns_429(db, card_image_client):
    """The 61st GET /cards/{card_id}/image from one IP within a minute returns 429."""
    client, rendered = card_image_client
    for _ in range(60):
        assert client.get("/cards/1/image").status_code == 200
    blocked = client.get("/cards/1/image")
    assert blocked.status_code == 429
    assert len(rendered) == 60  # the blocked request rendered nothing


def test_reorder_card_ids_50_items_accepted():
    """ReorderRequest.card_ids accepts 500 items (a whole large bench)."""
    from routers.cards import ReorderRequest
    assert len(ReorderRequest(card_ids=list(range(500))).card_ids) == 500


def test_reorder_card_ids_over_50_returns_422():
    """ReorderRequest.card_ids with 501 items is rejected (422)."""
    from routers.cards import ReorderRequest
    with pytest.raises(ValidationError):
        ReorderRequest(card_ids=list(range(501)))


def test_remove_players_500_ids_accepted():
    """RemovePlayersBody.player_ids accepts 500 items."""
    from routers.admin_players import RemovePlayersBody
    assert len(RemovePlayersBody(player_ids=list(range(500))).player_ids) == 500


def test_remove_players_over_500_returns_422():
    """RemovePlayersBody.player_ids with 501 items is rejected (422)."""
    from routers.admin_players import RemovePlayersBody
    with pytest.raises(ValidationError):
        RemovePlayersBody(player_ids=list(range(501)))
    app, _ = _build_app(["routers.admin_players"], admin_override=True)
    resp = TestClient(app).post("/admin/players/remove", json={"player_ids": list(range(501))})
    assert resp.status_code == 422


def _grant_client():
    app, Session = _build_app(["routers.admin_users"], admin_override=True)
    _add_user(Session, user_id=1, username="admin", email="admin@example.com", tokens=0)
    _add_user(Session, user_id=2, username="target", email="target@example.com", tokens=3)
    return TestClient(app), Session


def test_grant_tokens_10000_accepted(db):
    """POST /grant-tokens accepts an amount of 10,000."""
    client, Session = _grant_client()
    resp = client.post("/grant-tokens", json={"target_user_id": 2, "amount": 10_000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["tokens"] == 10_003


def test_grant_tokens_over_10000_returns_422(db):
    """POST /grant-tokens rejects an amount over 10,000 and grants nothing."""
    client, Session = _grant_client()
    resp = client.post("/grant-tokens", json={"target_user_id": 2, "amount": 10_001})
    assert resp.status_code == 422
    with Session() as s:
        assert s.get(User, 2).tokens == 3
        assert s.query(AuditLog).filter_by(action="admin_grant_tokens").count() == 0


def _audit_client():
    app, Session = _build_app(["routers.admin_season"], admin_override=True)
    with Session() as s:
        s.add(AuditLog(timestamp=1, actor_username="x", action="a", detail="d"))
        s.commit()
    return TestClient(app)


def test_audit_logs_limit_1000_accepted(db):
    """GET /audit-logs accepts limit=1000."""
    resp = _audit_client().get("/audit-logs", params={"limit": 1000})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_audit_logs_limit_over_1000_rejected(db):
    """GET /audit-logs caps limit at 1,000 (limit=1001 is rejected with 422)."""
    client = _audit_client()
    assert client.get("/audit-logs", params={"limit": 1001}).status_code == 422
    assert client.get("/audit-logs").status_code == 200  # default still works


def _profile_client():
    app, Session = _build_app(["routers.profile"])
    _add_user(Session, user_id=1, username="alice", email="alice@example.com")
    _add_user(Session, user_id=2, username="taken", email="taken@example.com")
    client = TestClient(app)
    client.post("/_test/login/1")
    return client, Session


def test_update_username_refreshes_session_username(db):
    """PUT /profile/username takes effect for the same session at once: GET /me reports the new name (the username comes from the DB, not the cookie, since #119/#117)."""
    client, _ = _profile_client()
    assert client.get("/me").json()["username"] == "alice"
    resp = client.put("/profile/username", json={"username": "alice2"})
    assert resp.status_code == 200
    assert client.get("/me").json()["username"] == "alice2"
    # The cookie carries only the session ID, never the username.
    assert set(client.get("/_test/session").json()) == {"sid"}


def test_update_username_writes_username_changed_audit(db):
    """PUT /profile/username writes a username_changed audit entry with old and new names."""
    client, Session = _profile_client()
    assert client.put("/profile/username", json={"username": "alice2"}).status_code == 200
    with Session() as s:
        entry = s.query(AuditLog).filter_by(action="username_changed").one()
    assert entry.actor_id == 1
    assert "old=alice" in entry.detail and "new=alice2" in entry.detail


def test_update_username_taken_name_no_session_change_or_audit(db):
    """A rejected rename (name already taken) leaves the session's username (GET /me) unchanged and writes no audit entry."""
    client, Session = _profile_client()
    resp = client.put("/profile/username", json={"username": "taken"})
    assert resp.status_code == 409
    assert client.get("/me").json()["username"] == "alice"
    with Session() as s:
        assert s.query(AuditLog).filter_by(action="username_changed").count() == 0
        assert s.get(User, 1).username == "alice"


# ---------------------------------------------------------------------------
# Story 5 — Deployment and File Hardening
# ---------------------------------------------------------------------------

class _ScriptTagCollector(HTMLParser):
    """Collects the attributes of every <script> tag (tag names and attribute
    names are case-insensitive, as in browsers)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append({k: (v or "") for k, v in attrs})


def _script_tags(html):
    collector = _ScriptTagCollector()
    collector.feed(html)
    collector.close()
    return collector.scripts


def _external_scripts(html):
    return [a for a in _script_tags(html) if re.match(r"https?://", a.get("src", ""), re.I)]


def _cdn_script_problems(html):
    """Problems with external <script src> tags: floating version, missing SRI or crossorigin."""
    problems = []
    for attrs in _external_scripts(html):
        url = attrs["src"]
        pkg = re.search(r"/(?:npm/)?((?:@[^/]+/)?[^/@]+)@([^/]+)/", url)
        if not pkg or not re.fullmatch(r"\d+\.\d+\.\d+", pkg.group(2)):
            problems.append(f"not pinned to an exact version: {url}")
        if not re.fullmatch(r"sha(256|384|512)-[A-Za-z0-9+/=]{40,}", attrs.get("integrity", "")):
            problems.append(f"missing integrity: {url}")
        if attrs.get("crossorigin") != "anonymous":
            problems.append(f"missing crossorigin: {url}")
    return problems


def _index_html():
    return _read(os.path.join(_FRONTEND_DIR, "index.html"))


def test_index_html_alpine_pinned_to_exact_version():
    """frontend/index.html loads Alpine.js from an exact version (no 3.x.x or other floating range)."""
    html = _index_html()
    m = re.search(r'src="https://cdn\.jsdelivr\.net/npm/alpinejs@([^/"]+)/dist/cdn\.min\.js"', html)
    assert m, "Alpine.js script tag not found"
    assert re.fullmatch(r"\d+\.\d+\.\d+", m.group(1)), m.group(1)
    assert "3.x.x" not in html


def test_index_html_cdn_scripts_have_integrity_and_crossorigin():
    """Both CDN scripts (lucide, alpinejs) carry an integrity sha hash and crossorigin="anonymous"."""
    html = _index_html()
    external = _external_scripts(html)
    assert len(external) == 2
    assert any("lucide@0.453.0" in a["src"] for a in external)
    assert any("alpinejs@" in a["src"] for a in external)
    assert _cdn_script_problems(html) == []


def test_index_html_sri_checker_flags_floating_version_without_integrity():
    """The SRI checker fails on a planted `alpinejs@3.x.x` script tag with no integrity attribute."""
    planted = '<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>'
    problems = _cdn_script_problems(planted)
    assert any("not pinned" in p for p in problems)
    assert any("missing integrity" in p for p in problems)
    assert any("missing crossorigin" in p for p in problems)


def _tags_client():
    app, Session = _build_app(["routers.admin_tags"], admin_override=True)
    return TestClient(app), Session


def test_create_tag_valid_key_accepted(db):
    """Tag keys matching ^[a-z0-9][a-z0-9_-]*$ are accepted when created."""
    from models import TagDefinition
    client, Session = _tags_client()
    for key in ("caster", "0day", "co-host_2"):
        resp = client.post("/admin/tags", json={"key": key, "label": key.title()})
        assert resp.status_code == 200, resp.text
    with Session() as s:
        assert {t.key for t in s.query(TagDefinition).all()} == {"caster", "0day", "co-host_2"}


@pytest.mark.parametrize("key", ["../evil", "a/b", "Upper", "-lead", "_lead", "", "a.b"])
def test_create_tag_invalid_key_returns_422(db, key):
    """Tag keys not matching ^[a-z0-9][a-z0-9_-]*$ are rejected at creation (422)."""
    from models import TagDefinition
    client, Session = _tags_client()
    resp = client.post("/admin/tags", json={"key": key, "label": "Evil"})
    assert resp.status_code == 422
    with Session() as s:
        assert s.query(TagDefinition).count() == 0


def _sticker_setup(tmp_path, monkeypatch):
    image = pytest.importorskip("image")
    if not image.PIL_AVAILABLE:
        pytest.skip("Pillow not installed")
    from PIL import Image
    sticker_dir = tmp_path / "stickers"
    sticker_dir.mkdir()
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(sticker_dir / "good.png")
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(tmp_path / "evil.png")
    monkeypatch.setattr(image, "STICKER_DIR", str(sticker_dir))
    opened = []
    real_open = image.Image.open

    def _spy_open(path, *a, **kw):
        opened.append(os.path.abspath(str(path)))
        return real_open(path, *a, **kw)

    monkeypatch.setattr(image.Image, "open", _spy_open)
    base = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    return image, base, opened


def test_apply_stickers_applies_sticker_inside_sticker_dir(tmp_path, monkeypatch):
    """_apply_stickers still applies a sticker whose file is inside STICKER_DIR."""
    image, base, opened = _sticker_setup(tmp_path, monkeypatch)
    out = image._apply_stickers(base, ["good", "missing"])
    assert out.getpixel((image.STICKER_START_X + 5, image.STICKER_Y + 5)) == (255, 0, 0, 255)
    assert opened == [str(tmp_path / "stickers" / "good.png")]


def test_apply_stickers_skips_path_outside_sticker_dir(tmp_path, monkeypatch):
    """_apply_stickers skips a key whose path resolves outside STICKER_DIR (e.g. '../x') without opening it."""
    image, base, opened = _sticker_setup(tmp_path, monkeypatch)
    assert (tmp_path / "stickers" / ".." / "evil.png").exists()
    out = image._apply_stickers(base, ["../evil"])
    assert opened == []
    assert out.getpixel((image.STICKER_START_X + 5, image.STICKER_Y + 5)) == (0, 0, 0, 0)


def _seed_season(db):
    db.add(Team(id=1, name="T1"))
    db.add(Player(id=1, name="P1"))
    db.add(Match(match_id=1, radiant_team_id=1, dire_team_id=1, start_time=1))
    db.add(PlayerMatchStats(player_id=1, match_id=1, team_id=1, fantasy_points=1.0))
    db.commit()


def test_reset_season_proceeds_when_backup_succeeds(db, tmp_path, monkeypatch):
    """POST /admin/season/reset still resets when backup_sqlite_db() returns a path."""
    import routers.admin_season as admin_season
    backup = str(tmp_path / "fantasy.db.backup-test")
    monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda: backup)
    _seed_season(db)
    result = admin_season.reset_season(admin_season.SeasonResetBody(force=True), db=db, admin=_ADMIN)
    assert result["backup_path"] == backup
    assert db.query(Match).count() == 0
    assert db.query(PlayerMatchStats).count() == 0


def test_reset_season_aborts_500_when_backup_returns_none(db, monkeypatch):
    """POST /admin/season/reset returns 500 and deletes nothing when backup_sqlite_db() returns None."""
    import routers.admin_season as admin_season
    monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda: None)
    _seed_season(db)
    with pytest.raises(HTTPException) as exc:
        admin_season.reset_season(admin_season.SeasonResetBody(force=True), db=db, admin=_ADMIN)
    assert exc.value.status_code == 500
    db.rollback()
    assert db.query(Match).count() == 1
    assert db.query(PlayerMatchStats).count() == 1
    assert db.query(Player).count() == 1
    assert db.query(AuditLog).filter_by(action="admin_season_reset").count() == 0


def test_backup_file_written_with_mode_0600(tmp_path, monkeypatch):
    """backup_sqlite_db() writes the backup file with mode 0600 (DATABASE_URL patched to tmp_path)."""
    db_file = tmp_path / "fantasy.db"
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{db_file}")
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()
    old_umask = os.umask(0o022)  # a typical umask would otherwise give 0644
    try:
        backup_path = database.backup_sqlite_db()
    finally:
        os.umask(old_umask)
    assert backup_path and os.path.dirname(backup_path) == str(tmp_path)
    assert os.stat(backup_path).st_mode & 0o777 == 0o600
    check = sqlite3.connect(backup_path)
    try:
        assert check.execute("SELECT x FROM t").fetchone() == (42,)
    finally:
        check.close()
