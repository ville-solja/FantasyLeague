"""
Tests for plan-issue-157-twitch-extension-policy-compliance.md (resolves GitHub
issue #157, Part 1 of 2; Part 2 is #160).

The Twitch panel becomes a self-contained game: a Live tab for every viewer
(`GET /twitch/panel`), a one-button Join that creates a soft account
(`users.account_type = "twitch"`, no username/email/password), draws, a
collection and a roster inside the panel, MVP drops to soft accounts with
anonymous chat winners and a `TWITCH_DROPS_ENABLED` kill switch, no link-code
UI, soft accounts hidden from every ranking, Leave and a retention purge.
One stub per acceptance criterion, plus the primary failure path per story.

Developer notes
---------------

  Plan vs current code (the plan predates #161, now implemented)
    - Live games come from Steam (`backend/steam_live.py`), polled by a separate
      `main._live_poll_loop`; per-match timings live in the `match_timings`
      table; `GET /twitch/matches/current` returns `live_checked_at` and
      `live_source_configured`. The Live tab must keep using that endpoint
      unchanged; do not break test_issue_161_mvp_selection_delays.py or
      test_issue_139_early_mvp_selection.py.
    - The latest migration in backend/migrate.py is 030
      (`030_weekly_summary_seen_last_prompted`); this plan adds
      `031_users_twitch_soft_accounts`. Plan Step 1 lists only two columns, but
      the Critical Files table and Assumptions list three: `account_type`,
      `last_seen_at`, `twitch_account_id`. Tests here expect all three.

  Existing tests this plan will break (update them in the same change)
    - test_issue_140_twitch_chat_announcement_fix.py asserts winner usernames in
      `_mvp_chat_text` ("Token drop winners (+1 tokens): alice, bob", the
      "and N more" truncation). Chat now reports a winner count only.
    - test_how_to_play_role_subtabs.py asserts "Generate Twitch Code" appears in
      frontend/index.html (How to Play, users sub-tab). Profile hides that text,
      and the How to Play copy (index.html "Token drops on Twitch: linked
      viewers ...") needs rewording too.
    - test_twitch_review_resubmission.py checks package.sh behaviour and the
      review doc; re-check it after the self-check is added.
    - test_issue_85_split_admin_router.py: bump the full-suite pass/skip
      tripwire for this file's new tests.

  Twitch JWT payloads
    - Endpoints are plain functions taking `payload: dict = Depends(verify_twitch_jwt)`.
      Call them directly with a payload dict, as `_call_set_mvp` / `_current` do
      in test_issue_139_early_mvp_selection.py, e.g.
      `twitch.join(payload=_viewer("Uviewer1"), db=db, ...)`.
    - Payload shapes (helpers below): logged-in viewer `{"channel_id",
      "role": "viewer", "opaque_user_id": "U..."}`; after the identity share
      the JWT also carries `"user_id": "<real numeric id>"`; logged-out viewer
      `opaque_user_id` starts with "A".
    - For the real JWT path (401 on a bad token) copy the `twitch_prod_env`
      fixture and `_SECRET_B64` from test_issue_140_twitch_chat_announcement_fix.py
      and sign with `jwt.encode(..., base64.urlsafe_b64decode(secret), "HS256")`.
    - `twitch_env` (below, copied from test_issue_139) sets TWITCH_LOCAL_DEV so
      PubSub and chat short-circuit. Note TWITCH_LOCAL_DEV makes
      `verify_twitch_jwt` return a fixed `Udev123` broadcaster payload, so only
      use it for direct function calls, never to test identity-specific HTTP
      behaviour through TestClient.
    - Patch `twitch._requests.post` with the `post_recorder` pattern from
      test_issue_140 to capture the chat text and PubSub message.

  New model fields
    - `User.account_type`, `User.last_seen_at` and `User.twitch_account_id`
      do not exist yet: import/construct inside each test, never at module
      level, or every stub fails collection.
    - `backend/soft_accounts.py` does not exist yet: import it inside tests.

  Card functions
    - `routers/cards.py` `draw_card`, `draw_booster`, `activate_card`,
      `deactivate_card`, `swap_roster`, `_build_roster_response` take a
      `current_user` dict (see `seed.py` demo seeding calling
      `draw_card(db=db, current_user=...)`). `get_booster_deck(request, db)`
      reads the user from the session cookie via `session_user_or_none`, so
      `GET /twitch/teams` needs a small adapter rather than a direct call;
      compare its output to `get_booster_deck` with a fake request whose
      session resolves to the same user.
    - Rate-limited website routes are `*_route` wrappers; call the plain
      functions to avoid slowapi in direct calls. For the rate-limit test use
      a TestClient (see the `client` fixture in test_draw_panel_redesign.py).

  Hidden accounts
    - Leaderboard SQL lives in routers/leaderboard.py (`WHERE u.is_tester = 0`
      at /leaderboard/roster, compute_season_standings, /leaderboard/weekly);
      the End Season archive is in routers/admin_season.py; admin users list
      is `GET /users` in routers/admin_users.py; tag lists in
      routers/admin_tags.py. There is no dedicated user-search endpoint today:
      the developer should confirm which endpoint the plan means by "user
      search" and record it in the feature doc's `db.query(User)` table.

  Frontend / extension
    - Vanilla JS. Use static source checks (precedent: `_read_js` /
      `_function_source` in test_issue_139) or a Node harness against a fake DOM
      as test_issue_156 does, returning early when Node is missing.
    - "Viewer files" = what viewers load: panel.html, panel.js, extension.js,
      extension.css. live_config.* (broadcaster dashboard) and
      config.html/config.js (broadcaster config page) are broadcaster-only, but
      package.sh ships them too. The plan says
      config.html should carry no viewer call-to-action; it currently mentions
      "kana-cards.com". Decide and document whether the forbidden-text check
      covers config/live_config too.
    - package.sh takes the version as its first argument (no hard-coded
      version); "builds 1.2.0" is read here as: the usage example / review doc
      names 1.2.0 and `bash package.sh 1.2.0` succeeds on the clean tree. Run
      package.sh against a copy in tmp_path (precedent:
      test_twitch_review_resubmission.py).
"""

import pathlib

import pytest

# Registers every existing table on Base before the conftest db fixture runs
# create_all. New columns/modules are imported inside tests.
import models  # noqa: F401

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EXTENSION_DIR = REPO_ROOT / "twitch-extension"
FRONTEND_DIR = REPO_ROOT / "frontend"

_CHANNEL = "test_channel"
_BROADCASTER = {"channel_id": _CHANNEL, "role": "broadcaster", "opaque_user_id": "Utest"}


def _viewer(opaque_id="Uviewer1", user_id=None, role="viewer"):
    """Extension JWT payload for a viewer; pass `user_id` after the identity share."""
    payload = {"channel_id": _CHANNEL, "role": role, "opaque_user_id": opaque_id}
    if user_id is not None:
        payload["user_id"] = user_id
    return payload


_ANON = _viewer("Aanon123")


@pytest.fixture
def twitch_env(monkeypatch):
    """No real Twitch calls: PubSub/chat short-circuit under TWITCH_LOCAL_DEV."""
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)




# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

import base64  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import zipfile  # noqa: E402

from fastapi import HTTPException  # noqa: E402

_SECRET_BYTES = b"issue-157-test-extension-secret!"
_SECRET_B64 = base64.b64encode(_SECRET_BYTES).decode()
_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}
VIEWER_FILES = ["panel.html", "panel.js", "extension.js", "extension.css"]
FORBIDDEN = ["kana-cards.com", "Log into", "Generate Twitch Code", "Link your account"]

# Teams 11 and 12 with three players each, all with stats in match 5001.
_TEAM_PLAYERS = {11: [101, 102, 103], 12: [201, 202, 203]}


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def _ext(name):
    return _read(EXTENSION_DIR / name)


def _js_function(src, name):
    """Source of `function name(...) { ... }` by brace matching."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", src)
    assert m, f"function {name} not found"
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    raise AssertionError(f"unbalanced function {name}")


def _seed_world(db, start_time=None):
    """Teams 11/12, players with stats in match 5001 (one hour ago), and draw weights."""
    from models import Match, Player, PlayerMatchStats, Team, Weight
    start_time = start_time if start_time is not None else int(time.time()) - 3600
    for tid, pids in _TEAM_PLAYERS.items():
        db.add(Team(id=tid, name=f"Team{tid}"))
        for pid in pids:
            db.add(Player(id=pid, name=f"Player{pid}", is_active=True))
    db.add(Match(match_id=5001, radiant_team_id=11, dire_team_id=12, start_time=start_time,
                 radiant_win=True))
    for tid, pids in _TEAM_PLAYERS.items():
        for i, pid in enumerate(pids):
            db.add(PlayerMatchStats(player_id=pid, match_id=5001, team_id=tid,
                                    fantasy_points=10.0 + pid / 100, kills=3, is_mvp=False))
    for key in ("draw_rate_common", "draw_rate_rare", "draw_rate_epic", "draw_rate_legendary"):
        db.add(Weight(key=key, label=key, value=1.0))
    db.add(Weight(key="team_booster_cost", label="Team booster cost", value=3.0))
    db.commit()


def _join(db, opaque_id="Uviewer1", user_id=None, role="viewer"):
    import twitch
    return twitch.join(_viewer(opaque_id, user_id=user_id, role=role), db)


def _user_by_opaque(db, opaque_id):
    from models import User
    return db.query(User).filter(User.twitch_user_id == opaque_id).first()


def _card(db, owner_id, player_id, active=False, slot=None, rarity="common"):
    from models import Card
    card = Card(player_id=player_id, owner_id=owner_id, card_type=rarity, is_active=active,
                generation=1, slot_index=slot)
    db.add(card)
    db.commit()
    return card


def _website_user(db, username="alice", twitch_user_id=None, tokens=5):
    from models import User
    user = User(username=username, email=f"{username}@example.com", password_hash="x",
                tokens=tokens, created_at=int(time.time()), twitch_user_id=twitch_user_id)
    db.add(user)
    db.commit()
    return user


def _raises(fn, status, detail=None):
    with pytest.raises(HTTPException) as exc:
        fn()
    assert exc.value.status_code == status, exc.value.detail
    if detail is not None:
        assert exc.value.detail == detail
    return exc.value


def _schedule_with(monkeypatch, weeks):
    import schedule
    monkeypatch.setattr(schedule, "get_schedule", lambda db: {"weeks": weeks})


_UPCOMING_WEEKS = [{"label": "Week 9", "div1": [
    {"team1": "Team11", "team2": "Team12", "datetime_iso": "2099-01-02T18:00:00", "scheduled": True},
    {"team1": "Later", "team2": "Other", "datetime_iso": "2099-02-02T18:00:00", "scheduled": True},
    {"team1": "Past", "team2": "Game", "datetime_iso": "2000-01-01T18:00:00", "scheduled": True},
], "div2": []}]


def _shared_db():
    """A thread-safe in-memory session for TestClient (endpoints run in a threadpool)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _twitch_app(db):
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    import twitch
    from database import get_db
    app = FastAPI()
    app.state.limiter = twitch.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(twitch.router)
    app.dependency_overrides[get_db] = lambda: db
    return app


def _signed(opaque_id, role="viewer", user_id=None, secret=_SECRET_BYTES):
    import jwt as pyjwt
    claims = {"exp": int(time.time()) + 300, "opaque_user_id": opaque_id, "role": role,
              "channel_id": _CHANNEL}
    if user_id:
        claims["user_id"] = user_id
    return "Bearer " + pyjwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture
def twitch_prod_env(monkeypatch):
    """The real JWT path with a known secret (no TWITCH_LOCAL_DEV bypass)."""
    monkeypatch.delenv("TWITCH_LOCAL_DEV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("TWITCH_EXTENSION_SECRET", _SECRET_B64)


def _seed_series_match(db, match_id=1001, player_ids=(102, 103)):
    """A match in the Twitch MVP series window (teams 11 vs 12, one hour ago)."""
    from models import Match, Player, PlayerMatchStats, Team
    for tid in (11, 12):
        if not db.get(Team, tid):
            db.add(Team(id=tid, name=f"Team{tid}"))
    db.add(Match(match_id=match_id, radiant_team_id=11, dire_team_id=12,
                 start_time=int(time.time()) - 3600, radiant_win=True))
    for i, pid in enumerate(player_ids):
        if not db.get(Player, pid):
            db.add(Player(id=pid, name=f"Player{pid}"))
        db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=11 if i % 2 == 0 else 12,
                                fantasy_points=10.0, kills=3, is_mvp=False))
    db.commit()


def _present(db, opaque_id, seen_at=None):
    from models import TwitchPresence
    db.add(TwitchPresence(twitch_user_id=opaque_id, channel_id=_CHANNEL,
                          seen_at=seen_at if seen_at is not None else int(time.time())))
    db.commit()


def _set_mvp(db, match_id=1001, player_id=102):
    import twitch
    return twitch.set_mvp(twitch.MVPBody(match_id=match_id, player_id=player_id),
                          payload=dict(_BROADCASTER), db=db)


def _chat_recorder(monkeypatch):
    import twitch
    chat = []
    monkeypatch.setattr(twitch, "_post_chat_message", lambda channel_id, message: chat.append(message))
    return chat


def _no_twitch_ids(obj, *values):
    text = json.dumps(obj, default=str)
    assert "twitch_user_id" not in text
    assert "twitch_account_id" not in text
    for v in values:
        assert v not in text, v


# ---------------------------------------------------------------------------
# Story 1 — Live Fantasy for Every Viewer
# ---------------------------------------------------------------------------

class TestLiveFantasyForEveryViewer:

    def test_twitch_panel_returns_top_performers_and_next_match_for_any_role(self, db, monkeypatch):
        """AC Data source: GET /twitch/panel returns the top 3 performers and the next match for viewer, broadcaster and anonymous (A...) payloads."""
        import twitch
        _seed_world(db)
        _schedule_with(monkeypatch, _UPCOMING_WEEKS)
        for payload in (_viewer(), _BROADCASTER, _ANON):
            data = twitch.panel_live(payload=payload, db=db)
            top = data["top_performers"]
            assert [p["player_id"] for p in top] == [203, 202, 201]
            assert [p["fantasy_points"] for p in top] == sorted((p["fantasy_points"] for p in top), reverse=True)
            assert top[0]["player_name"] == "Player203"
            assert data["next_match"]["team1"] == "Team11"
            assert data["next_match"]["team2"] == "Team12"
            assert data["next_match"]["datetime_iso"] == "2099-01-02T18:00:00"

    def test_twitch_panel_reuses_top_and_schedule_queries(self, db, monkeypatch):
        """AC Data source: /twitch/panel calls the existing queries behind GET /top and GET /schedule rather than duplicating them."""
        import schedule
        import twitch
        from routers import leaderboard
        _seed_world(db)
        top_calls, schedule_calls = [], []
        real_top = leaderboard.top_performance_rows

        def spy_top(db_, limit=10, match_ids=None):
            top_calls.append((limit, match_ids))
            return real_top(db_, limit=limit, match_ids=match_ids)

        monkeypatch.setattr(leaderboard, "top_performance_rows", spy_top)
        monkeypatch.setattr(schedule, "get_schedule", lambda db_: schedule_calls.append(1) or {"weeks": _UPCOMING_WEEKS})
        twitch.panel_live(payload=_viewer(), db=db)
        assert top_calls == [(3, [5001])]
        assert schedule_calls == [1]
        # GET /top runs the same helper, and next_scheduled_match reads GET /schedule's cached data.
        leaderboard.top_performances(db=db)
        assert top_calls[-1] == (10, None)
        assert schedule.next_scheduled_match(db)["team1"] == "Team11"

    def test_twitch_panel_returns_public_data_only(self, db, monkeypatch):
        """AC Data source: /twitch/panel returns public data only (no user, email, token or Twitch id fields)."""
        import twitch
        _seed_world(db)
        _join(db, "Uviewer1", user_id="777")
        _schedule_with(monkeypatch, _UPCOMING_WEEKS)
        data = twitch.panel_live(payload=_viewer(), db=db)
        assert set(data) == {"top_performers", "next_match"}
        text = json.dumps(data)
        for field in ("email", "username", "tokens", "user_id", "password", "stream_url"):
            assert field not in text
        _no_twitch_ids(data, "Uviewer1", "777")

    def test_twitch_matches_current_open_to_viewers_and_keeps_live_freshness(self, db):
        """AC Default view: GET /twitch/matches/current works for a viewer payload and still returns "(live)" provisional markers, live_checked_at and live_source_configured (#161)."""
        import twitch
        from models import LiveMatch
        now = int(time.time())
        db.add(LiveMatch(match_id=8100000001, league_id=1, radiant_team_id=11, dire_team_id=12,
                         radiant_name="Radiant Wolves", dire_name="Dire Bears",
                         players_json=json.dumps([{"account_id": 500, "name": "Savu", "side": "radiant"}]),
                         first_seen_at=now - 60, last_seen_at=now, ended_at=None))
        db.commit()
        for payload in (_viewer(), _ANON):
            data = twitch.current_matches(payload=payload, db=db)
            assert "live_checked_at" in data and "live_source_configured" in data
            match = data["series"][0]["matches"][0]
            assert match["provisional"] is True and match["live"] is True
        assert "(live)" in _ext("panel.js")

    def test_panel_opens_on_live_tab_with_mvps_top_performers_and_next_match(self):
        """AC Default view: panel.html/panel.js open on a Live tab with MVP, top-performer and next-match sections for every viewer."""
        html = _ext("panel.html")
        assert re.search(r'id="tab-live"[^>]*aria-selected="true"', html)
        assert re.search(r'id="view-live"[^>]*>', html) and 'id="view-live" class="view" role="tabpanel" aria-labelledby="tab-live" hidden' not in html
        for section in ("live-mvps", "live-top", "live-next"):
            assert f'id="{section}"' in html
        for heading in ("Latest MVPs", "Top performers", "Next match"):
            assert heading in html
        js = _ext("panel.js")
        live = _js_function(js, "loadLive")
        assert "/twitch/matches/current" in live and "/twitch/panel" in live
        # The Live tab loads for everyone: onReady starts it without checking an account.
        ready = _js_function(js, "onReady")
        assert "loadLive" in ready and "isJoined" not in ready

    def test_panel_refreshes_every_60_seconds_and_on_mvp_pubsub(self):
        """AC Refresh: panel.js refreshes the Live data every 60 s and immediately on an MVP PubSub message."""
        js = _ext("panel.js")
        assert re.search(r"LIVE_REFRESH_MS\s*=\s*60000", js)
        assert "setInterval(loadLive, LIVE_REFRESH_MS)" in _js_function(js, "onReady")
        pubsub = _js_function(js, "onPubSub")
        assert 'msg.type !== "mvp"' in pubsub
        assert "loadLive()" in pubsub

    def test_viewer_files_contain_no_login_link_code_or_website_call_to_action(self):
        """AC No outside calls to action: no viewer file contains "kana-cards.com", "Log into", "Generate Twitch Code" or "Link your account"."""
        for name in VIEWER_FILES:
            text = _ext(name).lower()
            for phrase in FORBIDDEN:
                assert phrase.lower() not in text, (name, phrase)
        # config.html is broadcaster-only but carries no viewer call-to-action either.
        assert "kana-cards.com" not in _ext("config.html")

    def test_package_sh_refuses_build_when_viewer_file_contains_forbidden_text(self, tmp_path):
        """AC No outside calls to action: package.sh exits non-zero and writes no zip when a viewer file contains forbidden text."""
        for i, (name, phrase) in enumerate([("panel.html", "Log into kana-cards.com"),
                                            ("panel.js", "Generate Twitch Code"),
                                            ("extension.js", "Link your account"),
                                            ("extension.css", "/* kana-cards.com */")]):
            ext = tmp_path / f"copy{i}"
            shutil.copytree(EXTENSION_DIR, ext, ignore=shutil.ignore_patterns("*.zip"))
            target = ext / name
            target.write_text(target.read_text() + "\n" + phrase + "\n")
            result = subprocess.run(["bash", str(ext / "package.sh"), "9.9.9"],
                                    capture_output=True, text=True, timeout=60)
            assert result.returncode != 0
            assert name in result.stderr and "forbidden text" in result.stderr
            assert list(ext.glob("*.zip")) == []

    def test_twitch_panel_with_no_data_returns_empty_sections_not_error(self, db, monkeypatch):
        """Failure path: with no matches, stats or schedule, /twitch/panel returns 200 with empty sections, not an error."""
        import schedule
        import twitch
        _schedule_with(monkeypatch, [])
        assert twitch.panel_live(payload=_ANON, db=db) == {"top_performers": [], "next_match": None}

        def broken(db_):
            raise RuntimeError("schedule source down")
        monkeypatch.setattr(schedule, "get_schedule", broken)
        assert twitch.panel_live(payload=_viewer(), db=db)["next_match"] is None

    def test_panel_shows_neutral_message_when_ebs_unreachable_or_section_empty(self):
        """Failure path: panel.js shows a short neutral per-section message on fetch failure or empty data, never a blank panel or login prompt."""
        js = _ext("panel.js")
        live = _js_function(js, "loadLive")
        assert ".catch(renderMvpsUnavailable)" in live and ".catch(renderPanelUnavailable)" in live
        for fn in ("renderMvpsUnavailable", "renderPanelUnavailable", "onConfigTimeout"):
            body = _js_function(js, fn)
            assert "unavailable right now" in body or "not available" in body
            assert "log in" not in body.lower()
        assert "No recent games yet." in _js_function(js, "renderMvps")
        assert "No games scored yet." in _js_function(js, "renderTopPerformers")
        assert "No match scheduled." in _js_function(js, "renderNextMatch")

    def test_twitch_panel_rejects_invalid_jwt(self, monkeypatch, twitch_prod_env):
        """Failure path: GET /twitch/panel without a valid extension JWT returns 401."""
        from fastapi.testclient import TestClient
        db = _shared_db()
        client = TestClient(_twitch_app(db))
        assert client.get("/twitch/panel", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
        wrong = _signed("Uviewer1", secret=b"some-other-secret-of-enough-size")
        assert client.get("/twitch/panel", headers={"Authorization": wrong}).status_code == 401
        ok = client.get("/twitch/panel", headers={"Authorization": _signed("Aanon")})
        assert ok.status_code == 200
        db.close()


# ---------------------------------------------------------------------------
# Story 2 — Join Kana Cards on Twitch (Soft Account Creation)
# ---------------------------------------------------------------------------

class TestJoinSoftAccountCreation:

    def test_twitch_join_creates_one_soft_account_with_expected_fields(self, db, monkeypatch):
        """AC POST /twitch/join: creates one users row with account_type="twitch", twitch_user_id=opaque id, NULL username/email/password_hash, tokens=INITIAL_TOKENS, created_at and last_seen_at set."""
        from models import User
        monkeypatch.setenv("INITIAL_TOKENS", "7")
        before = int(time.time())
        data = _join(db, "Uviewer1")
        assert data["joined"] is True and data["created"] is True
        users = db.query(User).all()
        assert len(users) == 1
        u = users[0]
        assert u.account_type == "twitch"
        assert u.twitch_user_id == "Uviewer1"
        assert u.username is None and u.email is None and u.password_hash is None
        assert u.tokens == 7 and data["tokens"] == 7
        assert u.created_at >= before and u.last_seen_at >= before

    def test_twitch_join_returns_403_twitch_login_required_for_anonymous_viewer(self, db):
        """Failure path: an A... opaque id gets 403 twitch_login_required and no row is created."""
        import twitch
        from models import User
        _raises(lambda: twitch.join(_ANON, db), 403, "twitch_login_required")
        _raises(lambda: twitch.join(_viewer(""), db), 403, "twitch_login_required")
        assert db.query(User).count() == 0

    def test_twitch_join_accepts_viewer_and_broadcaster_roles(self, db):
        """AC POST /twitch/join: role viewer or broadcaster may join."""
        import twitch
        from models import User
        assert _join(db, "Uviewer1", role="viewer")["joined"] is True
        assert _join(db, "Ubroad1", role="broadcaster")["joined"] is True
        _raises(lambda: twitch.join(_viewer("Uext1", role="external"), db), 403)
        assert {u.twitch_user_id for u in db.query(User).all()} == {"Uviewer1", "Ubroad1"}

    def test_twitch_join_repeat_press_returns_existing_account(self, db):
        """AC Already joined: a second join with the same opaque id returns that account's state and creates nothing."""
        from models import User
        first = _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        user.tokens = 3
        db.commit()
        second = _join(db, "Uviewer1")
        assert first["created"] is True and second["created"] is False
        assert second["tokens"] == 3
        assert db.query(User).count() == 1

    def test_twitch_join_concurrent_integrity_error_yields_single_account(self, db, monkeypatch):
        """AC Race-safe: a simulated concurrent insert (IntegrityError on twitch_user_id) returns the existing account; exactly one row exists."""
        import soft_accounts
        from models import User
        winner = User(account_type="twitch", twitch_user_id="Urace", tokens=5, created_at=1)
        db.add(winner)
        db.commit()
        real_find = soft_accounts.find_by_opaque_id
        calls = []

        def racing_find(db_, opaque_id):
            calls.append(opaque_id)
            # The first lookup runs before the other request's insert is visible.
            return None if len(calls) == 1 else real_find(db_, opaque_id)

        monkeypatch.setattr(soft_accounts, "find_by_opaque_id", racing_find)
        user, created = soft_accounts.get_or_create_soft_account(db, "Urace", None)
        assert created is False
        assert user.id == winner.id
        assert db.query(User).filter(User.twitch_user_id == "Urace").count() == 1
        assert len(calls) == 2

    def test_twitch_join_rate_limited_per_opaque_id_and_ip(self, monkeypatch, twitch_prod_env):
        """AC Rate limit: POST /twitch/join is limited by the slowapi limiter per opaque id and per IP (429 past the limit)."""
        from fastapi.testclient import TestClient
        import twitch
        from limits import parse
        db = _shared_db()
        was_enabled = twitch.limiter.enabled
        twitch.limiter.enabled = True
        twitch.limiter.reset()
        try:
            client = TestClient(_twitch_app(db))
            per_viewer = parse(twitch.RATE_LIMIT_TWITCH_JOIN).amount
            per_ip = parse(twitch.RATE_LIMIT_TWITCH_JOIN_IP).amount
            assert per_viewer < per_ip
            statuses = [client.post("/twitch/join", headers={"Authorization": _signed("Uone")}).status_code
                        for _ in range(per_viewer + 1)]
            assert statuses[:per_viewer] == [200] * per_viewer
            assert statuses[-1] == 429
            # Another viewer on the same IP is not blocked by the first viewer's limit.
            assert client.post("/twitch/join", headers={"Authorization": _signed("Utwo")}).status_code == 200
            # The per-IP limit stops many viewers from one address.
            codes = [client.post("/twitch/join", headers={"Authorization": _signed(f"Uip{i}")}).status_code
                     for i in range(per_ip)]
            assert 429 in codes
        finally:
            twitch.limiter.reset()
            twitch.limiter.enabled = was_enabled
            db.close()

    def test_twitch_join_writes_audit_without_opaque_id(self, db):
        """AC Audit: join writes twitch_soft_account_created with the new user id and no opaque id in the detail."""
        from models import AuditLog
        _join(db, "Usecretopaque", user_id="424242")
        user = _user_by_opaque(db, "Usecretopaque")
        rows = db.query(AuditLog).filter(AuditLog.action == "twitch_soft_account_created").all()
        assert len(rows) == 1
        assert f"user_id={user.id}" in rows[0].detail
        for row in rows:
            assert "Usecretopaque" not in (row.detail or "") + (row.actor_username or "")
            assert "424242" not in (row.detail or "")

    def test_twitch_join_stores_twitch_account_id_from_jwt_user_id(self, db):
        """AC Identity share: a join JWT carrying user_id stores it in users.twitch_account_id."""
        _join(db, "Uviewer1", user_id="123456")
        assert _user_by_opaque(db, "Uviewer1").twitch_account_id == "123456"

    def test_later_call_with_user_id_records_twitch_account_id(self, db):
        """AC Identity share: any later panel call (e.g. GET /twitch/me) carrying user_id fills an empty twitch_account_id."""
        import twitch
        _join(db, "Uviewer1")
        assert _user_by_opaque(db, "Uviewer1").twitch_account_id is None
        data = twitch.me(payload=_viewer("Uviewer1", user_id="98765"), db=db)
        assert data["identity_shared"] is True
        db.expire_all()
        assert _user_by_opaque(db, "Uviewer1").twitch_account_id == "98765"

    def test_record_twitch_account_id_never_overwrites_different_id(self, db):
        """AC Identity share: an existing twitch_account_id is never overwritten with a different value."""
        import soft_accounts
        import twitch
        _join(db, "Uviewer1", user_id="111")
        user = _user_by_opaque(db, "Uviewer1")
        soft_accounts.record_twitch_account_id(db, user, "222")
        db.commit()
        twitch.me(payload=_viewer("Uviewer1", user_id="333"), db=db)
        db.expire_all()
        assert _user_by_opaque(db, "Uviewer1").twitch_account_id == "111"

    def test_record_twitch_account_id_held_by_another_account_returns_409(self, db):
        """Failure path: a user_id already stored on another account is refused with 409 (unique column)."""
        import soft_accounts
        _join(db, "Ufirst", user_id="555")
        _join(db, "Usecond")
        second = _user_by_opaque(db, "Usecond")
        _raises(lambda: soft_accounts.record_twitch_account_id(db, second, "555"), 409)
        assert second.twitch_account_id is None
        # Issue #160 lookup order: Join with an identity already held elsewhere
        # recognises that account (same Twitch user) instead of refusing with 409;
        # no new account is created.
        from models import User
        count = db.query(User).count()
        data = _join(db, "Uthird", user_id="555")
        assert data["created"] is False
        assert db.query(User).count() == count
        assert _user_by_opaque(db, "Uthird").twitch_account_id == "555"

    def test_twitch_join_without_identity_share_still_creates_account(self, db):
        """AC Identity share: a viewer who declines (no user_id in JWT) still joins, with twitch_account_id NULL."""
        data = _join(db, "Udecliner")
        assert data["joined"] is True and data["identity_shared"] is False
        assert _user_by_opaque(db, "Udecliner").twitch_account_id is None

    def test_panel_join_calls_request_id_share_and_shows_consent_line(self):
        """AC Join button / Identity share: panel.js calls Twitch.ext.actions.requestIdShare() before POST /twitch/join, shows the consent line, and Settings offers "Share your Twitch identity"."""
        js = _ext("panel.js")
        assert "actions.requestIdShare()" in _js_function(js, "requestIdentityShare")
        join = _js_function(js, "doJoin")
        assert join.index("requestIdentityShare()") < join.index('ebsPost("/twitch/join")')
        html = _ext("panel.html")
        assert "Uses your Twitch login. We store your Twitch id and game progress; leave any time in Settings." in html
        assert "Join Kana Cards" in html
        assert "Share your Twitch identity" in html
        assert "requestIdentityShare()" in js.split('el("btn-share").addEventListener', 1)[1].split("});", 1)[0]

    def test_panel_shows_log_in_to_twitch_note_for_anonymous_viewers(self):
        """AC Logged out of Twitch: panel.js replaces the Join button with "Log in to Twitch to join" for A... ids."""
        html = _ext("panel.html")
        login_tpl = re.search(r'<template id="tpl-login">(.*?)</template>', html, re.S).group(1)
        assert "Log in to Twitch to join" in login_tpl
        assert "btn-join" not in login_tpl
        js = _ext("panel.js")
        assert 'charAt(0) === "U"' in _js_function(js, "isLoggedInToTwitch")
        assert 'isLoggedInToTwitch() ? "tpl-join" : "tpl-login"' in _js_function(js, "renderJoinSlots")

    def test_soft_account_cannot_log_in_on_website(self, db, monkeypatch):
        """AC Website safety: POST /login cannot authenticate a soft account (no username or password)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.middleware.sessions import SessionMiddleware
        import auth
        import deps
        import sessions
        from database import get_db
        from routers import auth as auth_router
        shared = _shared_db()
        try:
            _join(shared, "Uviewer1")
            soft = _user_by_opaque(shared, "Uviewer1")
            app = FastAPI()
            app.add_middleware(SessionMiddleware, secret_key="test-secret-157")
            app.include_router(auth_router.router)
            app.dependency_overrides[get_db] = lambda: shared
            monkeypatch.setattr(auth_router.limiter, "enabled", False)
            client = TestClient(app)
            for name in (soft.display_name, "", "None"):
                res = client.post("/login", json={"username": name, "password": "anything"})
                assert res.status_code in (401, 422)
            assert auth.verify_password("anything", None) is False
            # A session row for a soft account (impossible today) would still not authenticate.
            monkeypatch.setattr(sessions, "validate_request", lambda request, db: soft)

            class _Req:
                session = {}
                state = type("S", (), {})()
            assert deps.session_user_or_none(_Req(), shared) is None
            _raises(lambda: deps.get_current_user(_Req(), shared), 401)
        finally:
            shared.close()

    def test_soft_account_not_reachable_by_forgot_password(self, db, monkeypatch):
        """AC Website safety: forgot-password and the username allowlist never match a soft account."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.middleware.sessions import SessionMiddleware
        import auth
        from database import get_db
        from models import PasswordResetToken
        from routers import auth as auth_router
        shared = _shared_db()
        try:
            _join(shared, "Uviewer1")
            soft = _user_by_opaque(shared, "Uviewer1")
            app = FastAPI()
            app.add_middleware(SessionMiddleware, secret_key="test-secret-157")
            app.include_router(auth_router.router)
            app.dependency_overrides[get_db] = lambda: shared
            monkeypatch.setattr(auth_router.limiter, "enabled", False)
            client = TestClient(app)
            res = client.post("/forgot-password", json={"username": soft.display_name})
            assert res.status_code == 200 and res.json() == {"status": "ok"}
            assert shared.query(PasswordResetToken).count() == 0
            # The soft account's admin label is not a valid username (allowlist), so it
            # can never be registered or renamed into.
            with pytest.raises(ValueError):
                auth.check_username(soft.display_name)
        finally:
            shared.close()

    def test_website_registration_creates_full_accounts_only(self, db, monkeypatch):
        """AC Website safety: no website endpoint creates account_type="twitch"; registration yields "full"."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.middleware.sessions import SessionMiddleware
        from database import get_db
        from models import User
        from routers import auth as auth_router
        shared = _shared_db()
        try:
            app = FastAPI()
            app.add_middleware(SessionMiddleware, secret_key="test-secret-157")
            app.include_router(auth_router.router)
            app.dependency_overrides[get_db] = lambda: shared
            monkeypatch.setattr(auth_router.limiter, "enabled", False)
            res = TestClient(app).post("/register", json={"username": "newbie", "email": "n@example.com",
                                                           "password": "secret123"})
            assert res.status_code == 200, res.text
            assert shared.query(User).filter_by(username="newbie").one().account_type == "full"
        finally:
            shared.close()
        # Only soft_accounts.py creates soft accounts; no website router calls it.
        backend = REPO_ROOT / "backend"
        for path in (backend / "routers").glob("*.py"):
            src = path.read_text()
            assert "get_or_create_soft_account" not in src, path.name
            assert not re.search(r"account_type\s*=\s*['\"]twitch['\"]", src), path.name

    def test_twitch_me_returns_joined_false_without_account(self, db):
        """AC GET /twitch/me: a viewer without an account gets {joined: false}."""
        import twitch
        assert twitch.me(payload=_viewer("Unobody"), db=db) == {"joined": False, "can_join": True}
        assert twitch.me(payload=_ANON, db=db) == {"joined": False, "can_join": False}

    def test_twitch_me_returns_joined_shape_with_collection_roster_and_week_points(self, db):
        """AC GET /twitch/me: a joined viewer gets joined, tokens, collection (player, team, rarity, modifiers), roster from _build_roster_response and week_points."""
        import twitch
        from routers.cards import _build_roster_response
        _seed_world(db)
        _join(db, "Uviewer1")
        twitch.draw(_viewer("Uviewer1"), db)
        data = twitch.me(payload=_viewer("Uviewer1"), db=db)
        assert data["joined"] is True
        assert data["tokens"] == 4
        assert len(data["collection"]) == 1
        card = data["collection"][0]
        for key in ("player_name", "team_name", "card_type", "modifiers", "season_points", "is_active"):
            assert key in card
        user = _user_by_opaque(db, "Uviewer1")
        assert data["roster"] == _build_roster_response(db, user.id, None)
        assert "week_points" in data and data["roster_locked"] is False
        assert data["roster_limit"] == 5
        for private in ("email", "password_hash", "username"):
            assert private not in data

    def test_twitch_me_never_returns_another_users_data(self, db):
        """AC GET /twitch/me: the response holds only the caller's cards and roster, never another user's."""
        import twitch
        from models import Card
        _seed_world(db)
        _join(db, "Ua")
        _join(db, "Ub")
        for _ in range(2):
            twitch.draw(_viewer("Ua"), db)
            twitch.draw(_viewer("Ub"), db)
        ua = _user_by_opaque(db, "Ua")
        own = {c.id for c in db.query(Card).filter(Card.owner_id == ua.id).all()}
        data = twitch.me(payload=_viewer("Ua"), db=db)
        assert {c["id"] for c in data["collection"]} == own
        roster_ids = {c["id"] for c in data["roster"]["active"] + data["roster"]["bench"]}
        assert roster_ids <= own

    def test_twitch_me_updates_last_seen_at_at_most_once_an_hour(self, db):
        """AC GET /twitch/me: last_seen_at is refreshed only when older than one hour."""
        import twitch
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        recent = int(time.time()) - 600
        user.last_seen_at = recent
        db.commit()
        twitch.me(payload=_viewer("Uviewer1"), db=db)
        db.expire_all()
        assert _user_by_opaque(db, "Uviewer1").last_seen_at == recent
        old = int(time.time()) - 7200
        user = _user_by_opaque(db, "Uviewer1")
        user.last_seen_at = old
        db.commit()
        twitch.me(payload=_viewer("Uviewer1"), db=db)
        db.expire_all()
        assert _user_by_opaque(db, "Uviewer1").last_seen_at >= int(time.time()) - 5


# ---------------------------------------------------------------------------
# Story 3 — Draw Cards and Set a Roster in the Panel
# ---------------------------------------------------------------------------

def _locked_week_in_progress(db):
    from models import Week
    now = int(time.time())
    db.add(Week(label="Week 5", start_time=now - 3600, end_time=now + 3600, is_locked=True))
    db.commit()


class TestDrawAndRosterInPanel:

    def test_twitch_draw_runs_website_draw_logic_for_soft_account(self, db):
        """AC Draw · 1: POST /twitch/draw costs tokens, rolls rarity, adds modifiers, prefers unowned players and adds to the roster when there is room."""
        import twitch
        from models import AuditLog, Card
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        drawn = [twitch.draw(_viewer("Uviewer1"), db) for _ in range(5)]
        db.refresh(user)
        assert user.tokens == 0 and drawn[-1]["tokens"] == 0
        assert all(c["card_type"] in {"common", "rare", "epic", "legendary"} for c in drawn)
        assert all("modifiers" in c for c in drawn)
        assert len({c["player_id"] for c in drawn}) == 5  # unowned players first
        assert all(c["is_active"] for c in drawn)  # roster had room for all five
        assert db.query(Card).filter(Card.owner_id == user.id).count() == 5
        audit = db.query(AuditLog).filter(AuditLog.action == "token_draw").first()
        assert audit.actor_username == f"Twitch viewer #{user.id}"

    def test_twitch_draw_with_too_few_tokens_returns_website_400(self, db):
        """Failure path: drawing with too few tokens returns the same 400 as the website draw."""
        import twitch
        from routers.cards import draw_card
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        user.tokens = 0
        site = _website_user(db, "broke", tokens=0)
        website = _raises(lambda: draw_card(db=db, current_user={"user_id": site.id, "username": "broke", "is_admin": False}), 409)
        panel = _raises(lambda: twitch.draw(_viewer("Uviewer1"), db), 409)
        assert panel.detail == website.detail == "Not enough tokens"

    def test_twitch_teams_matches_deck_booster_for_same_player(self, db, monkeypatch):
        """AC Team draw: GET /twitch/teams returns the same teams and "left" counts as GET /deck/booster for that player."""
        import twitch
        from routers import cards
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        _card(db, user.id, 101)
        _card(db, user.id, 102)
        monkeypatch.setattr(cards, "session_user_or_none", lambda request, db_: user)
        website = cards.get_booster_deck(request=None, db=db)
        panel = twitch.teams(payload=_viewer("Uviewer1"), db=db)
        assert panel["teams"] == website
        assert {t["team_id"]: t["remaining"] for t in panel["teams"]} == {11: 1, 12: 3}
        assert panel["cost"] == 3

    def test_twitch_draw_booster_draws_unowned_player_from_team(self, db):
        """AC Team draw: POST /twitch/draw/booster/{team_id} costs 3 tokens and gives one of the team's players the player doesn't own."""
        import twitch
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        _card(db, user.id, 101)
        card = twitch.draw_team(11, _viewer("Uviewer1"), db)
        assert card["player_id"] in {102, 103}
        db.refresh(user)
        assert user.tokens == 2 and card["tokens"] == 2

    def test_twitch_draw_booster_for_complete_team_returns_website_error(self, db):
        """Failure path: a stale team draw for a team the player fully owns returns the website's draw_booster error."""
        import twitch
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        for pid in _TEAM_PLAYERS[11]:
            _card(db, user.id, pid)
        _raises(lambda: twitch.draw_team(11, _viewer("Uviewer1"), db), 409, "No players available for this team")
        db.refresh(user)
        assert user.tokens == 5
        # An unknown team gets the website's own 404.
        _raises(lambda: twitch.draw_team(999, _viewer("Uviewer1"), db), 404, "Team not found")

    def test_twitch_roster_activate_places_bench_card_in_empty_slot(self, db):
        """AC Roster tab: POST /twitch/roster/activate/{card_id} puts a bench card in an empty slot via activate_card."""
        import twitch
        from models import Card
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        bench = _card(db, user.id, 101, active=False, slot=7)
        assert twitch.roster_activate(bench.id, _viewer("Uviewer1"), db, slot=3) == {"status": "ok", "card_id": bench.id}
        card = db.get(Card, bench.id)
        assert card.is_active is True and card.slot_index == 3

    def test_twitch_roster_activate_respects_roster_limit(self, db):
        """AC Roster tab: activating beyond the roster limit is refused with the website's error."""
        import twitch
        from models import Card, Player
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        for pid in (101, 102, 103, 201, 202):
            _card(db, user.id, pid, active=True)
        db.add(Player(id=999, name="Extra"))
        db.commit()
        extra = _card(db, user.id, 999, active=False)
        _raises(lambda: twitch.roster_activate(extra.id, _viewer("Uviewer1"), db), 409, "Roster full (5 cards max)")
        assert db.get(Card, extra.id).is_active is False

    def test_twitch_roster_deactivate_benches_card(self, db):
        """AC Roster tab: POST /twitch/roster/deactivate/{card_id} moves the slot's card to the bench (Bench it)."""
        import twitch
        from models import Card
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        card = _card(db, user.id, 101, active=True, slot=0)
        twitch.roster_deactivate(card.id, _viewer("Uviewer1"), db)
        assert db.get(Card, card.id).is_active is False

    def test_twitch_roster_swap_puts_bench_card_in_slot_and_slot_card_on_bench(self, db):
        """AC Roster tab: POST /twitch/roster/swap uses swap_roster; the bench card takes the slot and the replaced card goes to the bench."""
        import twitch
        from models import Card
        from routers.cards import SwapRequest
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        active = _card(db, user.id, 101, active=True, slot=2)
        bench = _card(db, user.id, 102, active=False)
        assert twitch.roster_swap(SwapRequest(bench_card_id=bench.id, active_card_id=active.id, slot_index=2),
                                  _viewer("Uviewer1"), db) == {"ok": True}
        db.expire_all()
        assert db.get(Card, bench.id).is_active is True and db.get(Card, bench.id).slot_index == 2
        assert db.get(Card, active.id).is_active is False

    def test_twitch_roster_changes_refused_for_locked_week(self, db):
        """Failure path: activate, deactivate and swap on a locked week are refused with the website's locked-week error."""
        import twitch
        from models import Card
        from routers.cards import SwapRequest
        _seed_world(db)
        _join(db, "Uviewer1")
        user = _user_by_opaque(db, "Uviewer1")
        active = _card(db, user.id, 101, active=True, slot=0)
        bench = _card(db, user.id, 102, active=False)
        _locked_week_in_progress(db)
        v = _viewer("Uviewer1")
        locked = "Roster locked for this week"
        _raises(lambda: twitch.roster_activate(bench.id, v, db), 409, locked)
        _raises(lambda: twitch.roster_deactivate(active.id, v, db), 409, locked)
        _raises(lambda: twitch.roster_swap(SwapRequest(bench_card_id=bench.id, active_card_id=active.id,
                                                       slot_index=0), v, db), 409, locked)
        db.expire_all()
        assert db.get(Card, active.id).is_active is True and db.get(Card, bench.id).is_active is False
        assert twitch.me(payload=v, db=db)["roster_locked"] is True

    @pytest.mark.parametrize("endpoint", [
        "draw", "draw_booster", "roster_activate", "roster_deactivate", "roster_swap", "teams",
    ])
    def test_twitch_game_endpoints_return_404_not_joined(self, db, endpoint):
        """Failure path: each panel game endpoint returns 404 not_joined for a viewer without an account."""
        import twitch
        from routers.cards import SwapRequest
        _seed_world(db)
        calls = {
            "draw": lambda p: twitch.draw(p, db),
            "draw_booster": lambda p: twitch.draw_team(11, p, db),
            "roster_activate": lambda p: twitch.roster_activate(1, p, db),
            "roster_deactivate": lambda p: twitch.roster_deactivate(1, p, db),
            "roster_swap": lambda p: twitch.roster_swap(SwapRequest(bench_card_id=1, active_card_id=2, slot_index=0), p, db),
            "teams": lambda p: twitch.teams(payload=p, db=db),
        }
        for payload in (_viewer("Unobody"), _ANON):
            _raises(lambda: calls[endpoint](payload), 404, "not_joined")

    def test_twitch_roster_endpoints_refuse_another_users_card(self, db):
        """Failure path: activate/deactivate/swap on another user's card returns 403/404 and changes nothing (owner check)."""
        import twitch
        from models import Card
        from routers.cards import SwapRequest
        _seed_world(db)
        _join(db, "Uowner")
        _join(db, "Uthief")
        owner = _user_by_opaque(db, "Uowner")
        thief = _user_by_opaque(db, "Uthief")
        theirs_bench = _card(db, owner.id, 101, active=False)
        theirs_active = _card(db, owner.id, 102, active=True, slot=0)
        mine = _card(db, thief.id, 103, active=True, slot=0)
        v = _viewer("Uthief")
        _raises(lambda: twitch.roster_activate(theirs_bench.id, v, db), 404)
        _raises(lambda: twitch.roster_deactivate(theirs_active.id, v, db), 404)
        _raises(lambda: twitch.roster_swap(SwapRequest(bench_card_id=theirs_bench.id, active_card_id=mine.id,
                                                       slot_index=0), v, db), 404)
        db.expire_all()
        assert db.get(Card, theirs_bench.id).is_active is False
        assert db.get(Card, theirs_active.id).is_active is True
        assert db.get(Card, mine.id).is_active is True

    def test_twitch_me_cards_carry_season_points_and_rarity_for_40_cards(self, db):
        """AC Collection / bench picker: with 40 cards GET /twitch/me returns every card, each with rarity and season points, no paging."""
        import twitch
        from models import CardMatchPoints, Match, Player
        _join(db, "Ucollector")
        user = _user_by_opaque(db, "Ucollector")
        db.add(Match(match_id=7001, start_time=int(time.time()) - 7200))
        db.add(Match(match_id=7002, start_time=int(time.time()) - 3600, excluded_from_scoring=True))
        rarities = ["common", "rare", "epic", "legendary"]
        cards = []
        for i in range(40):
            db.add(Player(id=3000 + i, name=f"P{i:02d}"))
            db.commit()
            cards.append(_card(db, user.id, 3000 + i, rarity=rarities[i % 4]))
        db.add(CardMatchPoints(card_id=cards[0].id, match_id=7001, player_id=3000, points=12.34))
        db.add(CardMatchPoints(card_id=cards[0].id, match_id=7002, player_id=3000, points=100.0))  # excluded match
        db.commit()
        data = twitch.me(payload=_viewer("Ucollector"), db=db)
        assert len(data["collection"]) == 40
        assert all(c["card_type"] in rarities and "season_points" in c for c in data["collection"])
        by_id = {c["id"]: c for c in data["collection"]}
        assert by_id[cards[0].id]["season_points"] == 12.3
        assert by_id[cards[1].id]["season_points"] == 0
        # Rarest first, then by name.
        order = [rarities.index(c["card_type"]) for c in data["collection"]]
        assert order == sorted(order, reverse=True)

    def test_soft_account_roster_snapshotted_substituted_and_scored_at_weekly_lock(self, db):
        """AC Scoring: soft accounts get the weekly roster snapshot, bench substitution and stored card points (#129, #141) like website accounts."""
        import card_points
        from models import Match, PlayerMatchStats, Week, WeeklyRosterEntry
        from routers.cards import _build_roster_response
        from weeks import auto_lock_weeks, run_substitutions
        _seed_world(db, start_time=int(time.time()) - 10 * 86400)
        _join(db, "Uplayer")
        user = _user_by_opaque(db, "Uplayer")
        sitting = _card(db, user.id, 101, active=True, slot=0)   # does not play this week
        sub = _card(db, user.id, 201, active=False)              # plays this week
        now = int(time.time())
        week = Week(label="Week 1", start_time=now - 60, end_time=now + 86400, is_locked=False)
        db.add(week)
        db.add(Match(match_id=6001, radiant_team_id=12, dire_team_id=11, start_time=now + 600, radiant_win=True))
        db.add(PlayerMatchStats(player_id=201, match_id=6001, team_id=12, fantasy_points=20.0, kills=10))
        db.commit()
        auto_lock_weeks(db)
        entries = db.query(WeeklyRosterEntry).filter_by(week_id=week.id, user_id=user.id).all()
        assert {(e.card_id, bool(e.is_bench)) for e in entries} == {(sitting.id, False), (sub.id, True)}
        assert run_substitutions(db, week) == 1
        db.commit()
        by_card = {e.card_id: e for e in db.query(WeeklyRosterEntry).filter_by(week_id=week.id, user_id=user.id)}
        assert by_card[sitting.id].subbed_out is True and by_card[sub.id].subbed_in is True
        card_points.rebuild_all(db)
        roster = _build_roster_response(db, user.id, week.id)
        assert roster["combined_value"] > 0
        assert [c["id"] for c in roster["active"]] == [sub.id]

    def test_soft_account_receives_weekly_token_grant(self, db):
        """AC Tokens: auto_lock_weeks gives soft accounts the +1 weekly token like every user."""
        from models import Week
        from weeks import auto_lock_weeks
        _join(db, "Usoft")
        site = _website_user(db, "site", tokens=2)
        soft = _user_by_opaque(db, "Usoft")
        before = soft.tokens
        now = int(time.time())
        db.add(Week(label="Week 1", start_time=now - 60, end_time=now + 86400, is_locked=False))
        db.commit()
        auto_lock_weeks(db)
        db.expire_all()
        assert _user_by_opaque(db, "Usoft").tokens == before + 1
        assert db.get(type(site), site.id).tokens == 3

    def test_panel_team_picker_two_column_rows_sorted_with_pinned_draw_button(self):
        """AC Team draw: panel has a Team draw view with Back, the explainer line, two-column 44 px rows (logo or monogram, name, "N left"/"Complete"), available-first sorting, aria-pressed selection and a pinned "Draw from {team} · 3" button disabled under 3 tokens."""
        html = _ext("panel.html")
        teams_view = re.search(r'<section id="view-teams"(.*?)</section>', html, re.S).group(1)
        assert 'id="btn-teams-back"' in teams_view and ">Back<" in teams_view
        assert "Team draw" in teams_view
        assert "Pick a team. You get one of its players you don't own yet. Costs 3 tokens." in teams_view
        assert 'class="pinned"' in teams_view and 'id="btn-team-confirm"' in teams_view
        css = _ext("extension.css")
        assert re.search(r"\.team-list\s*\{[^}]*grid-template-columns:\s*1fr 1fr", css)
        assert re.search(r"\.team-row\s*\{[^}]*height:\s*44px", css)
        assert re.search(r"\.mono,?|, \.mono", css) and "width: 28px; height: 28px" in css
        assert re.search(r'\.team-row\[aria-pressed="true"\]\s*\{[^}]*border-color:\s*var\(--accent\)[^}]*background:\s*var\(--accent-ghost\)', css)
        js = _ext("panel.js")
        sort = _js_function(js, "sortTeams")
        assert "remaining === 0" in sort and "localeCompare" in sort
        teams = _js_function(js, "renderTeams")
        assert '"Complete"' in teams and '" left"' in teams and "monogram(" in teams
        assert "btn.disabled = complete" in teams and 'setAttribute("aria-pressed"' in teams
        confirm = _js_function(js, "renderTeamConfirm")
        assert '"Draw from " + t.team_name + " · " + cost' in confirm
        assert "btn.disabled = !t || tokens < cost" in confirm
        assert '"You need " + cost + " tokens for a team draw"' in confirm

    def test_panel_draw_reveal_and_collection_with_rarity_filters(self):
        """AC Cards tab: panel shows the drawn card reveal (rarity treatment, roster or bench) and a collection with count, rarity filter chips with counts and a five-per-row grid sorted rarest first."""
        js = _ext("panel.js")
        reveal = _js_function(js, "showReveal")
        assert "Added to your roster" in reveal and "Added to your bench" in reveal
        assert 'artHtml(card, "lg")' in reveal
        assert re.search(r'RARITY_SHORT\s*=\s*\{\s*legendary:\s*"Leg",\s*epic:\s*"Epic",\s*rare:\s*"Rare",\s*common:\s*"Com"\s*\}', js)
        chips = _js_function(js, "chipsHtml")
        assert '"All"' in chips and "counts[k]" in chips and "aria-pressed" in chips
        coll = _js_function(js, "renderCollection")
        assert '" cards"' in coll and "sortByRarityThenName" in coll and 'artHtml(c, "sm")' in coll
        assert 'RARITY_ORDER    = ["legendary", "epic", "rare", "common"]' in js
        css = _ext("extension.css")
        assert "grid-template-columns: repeat(5, 48px)" in css
        assert re.search(r"\.art\.sm\s*\{\s*width:\s*48px;\s*height:\s*66px", css)

    def test_panel_roster_changes_start_from_slot_bench_picker(self):
        """AC Roster tab: empty slots show "+ Add a card", filled show "Change"; the slot's bench picker has rarity chips, Points/Rarity sort, "In this slot" with Bench it, and a confirmation line; no drag-and-drop."""
        js = _ext("panel.js")
        roster = _js_function(js, "renderRoster")
        assert "+ Add a card" in roster and ">Change<" in roster and "openPicker(" in roster
        picker = _js_function(js, "renderPicker")
        assert '"Replace in slot "' in picker and '"Pick a card for slot "' in picker
        assert "chipsHtml(" in picker and 'state.pickerSort === "rarity"' in picker and "b.points - a.points" in picker
        html = _ext("panel.html")
        assert "In this slot:" in html and "Bench it" in html
        assert 'data-sort="points"' in html and 'data-sort="rarity"' in html
        assert 'id="btn-picker-back"' in html
        place = _js_function(js, "placeCard")
        assert '"/twitch/roster/swap"' in place and '" in, " + current.player_name + " to the bench."' in place
        assert '"/twitch/roster/activate/"' in place
        assert '"/twitch/roster/deactivate/"' in js
        for name in ("panel.html", "panel.js"):
            text = _ext(name)
            assert "draggable" not in text and "dragstart" not in text

    def test_panel_shows_roster_locked_read_only_message(self):
        """Failure path: a locked week renders the roster read-only with "Roster locked for this week"."""
        html = _ext("panel.html")
        assert re.search(r'id="roster-locked"[^>]*hidden>Roster locked for this week<', html)
        roster = _js_function(_ext("panel.js"), "renderRoster")
        assert "me.roster_locked" in roster
        assert 'el("roster-locked").hidden = !locked' in roster
        assert roster.count('locked ? ""') == 2  # no Add/Change buttons when locked

    def test_panel_follows_design_guide(self):
        """AC Design: extension CSS/HTML use Big Shoulders caps display type, 4 px buttons (no pill radius), 6 px cards, 2 px orange active-tab underline, focus rings, no text under 11 px, tabular numerals, and no emoji in any viewer file."""
        css = _ext("extension.css")
        assert '"Big Shoulders Text"' in css and "fonts/BigShouldersText-VariableFont_wght.ttf" in css
        assert (EXTENSION_DIR / "fonts" / "BigShouldersText-VariableFont_wght.ttf").is_file()
        assert "--r-sm: 4px" in css and "--r-md: 6px" in css
        button = re.search(r"\nbutton\s*\{([^}]*)\}", css).group(1)
        assert "border-radius: var(--r-sm)" in button and "text-transform: uppercase" in button
        assert "font-family: var(--font-display)" in button
        assert "999px" not in css and "--r-pill" not in css and "50%" not in css
        assert re.search(r"\.box\s*\{[^}]*border-radius:\s*var\(--r-md\)", css)
        assert re.search(r"\.p-tab\s*\{[^}]*border-bottom:\s*2px solid transparent", css)
        assert re.search(r'\.p-tab\[aria-selected="true"\]\s*\{[^}]*border-bottom-color:\s*var\(--accent\)', css)
        assert "--accent:       var(--k-orange-500)" in css and "--k-orange-500: #e85d1c" in css
        assert re.search(r"button:focus-visible[^{]*\{\s*outline:\s*2px solid var\(--accent\)", css)
        assert "font-variant-numeric: tabular-nums" in css
        # No left-border accent cards.
        assert "border-left" not in css
        # Readability floor: no font size under 11 px anywhere in the viewer files.
        for name in VIEWER_FILES:
            for size in re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", _ext(name)):
                assert float(size) >= 11, (name, size)
            assert not re.search(r"font-size:\s*0?\.\d+rem", _ext(name)), name
        emoji = re.compile("[\U0001F300-\U0001FAFF☀-⛿✀-➿]")
        for name in VIEWER_FILES:
            assert not emoji.search(_ext(name)), name


# ---------------------------------------------------------------------------
# Story 4 — Token Drops for Players on Twitch
# ---------------------------------------------------------------------------

class TestTokenDropsForTwitchPlayers:

    def test_active_pool_includes_present_soft_and_linked_accounts(self, db):
        """AC Who is eligible: the drop pool is every present viewer with an account (soft or website-linked) via users.twitch_user_id."""
        import twitch
        _join(db, "Usoft")
        _website_user(db, "linked", twitch_user_id="Ulinked")
        _join(db, "Ustale")
        for oid in ("Usoft", "Ulinked", "Unoaccount"):
            _present(db, oid)
        _present(db, "Ustale", seen_at=int(time.time()) - 3600)
        assert sorted(twitch._active_pool(db, _CHANNEL)) == ["Ulinked", "Usoft"]

    def test_set_mvp_drops_to_soft_accounts_respecting_drop_max_and_one_per_match(self, db, twitch_env, monkeypatch):
        """AC Who is eligible: confirming an MVP credits soft accounts, capped by TWITCH_DROP_MAX, once per match."""
        import twitch
        from models import User
        _chat_recorder(monkeypatch)
        monkeypatch.setattr(twitch, "_TWITCH_DROP_MAX", 2)
        _seed_series_match(db)
        for oid in ("Us1", "Us2", "Us3"):
            _join(db, oid)
            _present(db, oid)
        start = {u.id: u.tokens for u in db.query(User).all()}
        result = _set_mvp(db)
        assert result["token_drop"]["winner_count"] == 2 and result["token_drop"]["pool_size"] == 3
        db.expire_all()
        gained = sum(u.tokens - start[u.id] for u in db.query(User).all())
        assert gained == 2
        again = _set_mvp(db, player_id=103)
        assert again["token_drop"]["already_dropped"] is True
        db.expire_all()
        assert sum(u.tokens - start[u.id] for u in db.query(User).all()) == 2

    def test_mvp_chat_text_names_mvp_and_winner_count_without_usernames(self, db, twitch_env, monkeypatch):
        """AC Chat: the announcement names the MVP and says "N viewers received a token", with no usernames."""
        import twitch
        assert twitch._mvp_chat_text("Savu", 3, False) == "Match MVP: Savu! 3 viewers received a token."
        assert twitch._mvp_chat_text("Savu", 1, False) == "Match MVP: Savu! 1 viewer received a token."
        chat = _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _website_user(db, "alice_secret_name", twitch_user_id="Ulinked")
        _present(db, "Ulinked")
        _join(db, "Usoft")
        _present(db, "Usoft")
        _set_mvp(db)
        assert chat == ["Match MVP: Player102! 2 viewers received a token."]
        assert "alice_secret_name" not in chat[0] and "Twitch viewer" not in chat[0]

    def test_set_mvp_pubsub_tells_winners_to_refresh(self, db, monkeypatch):
        """AC In the panel: the PubSub message lets each winner's panel show "+1 token from the MVP drop" and refresh GET /twitch/me."""
        import twitch
        monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
        sent = []
        monkeypatch.setattr(twitch, "_pubsub_broadcast", lambda channel_id, message: sent.append(message))
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _website_user(db, "alice_secret_name", twitch_user_id="Ulinked")
        _present(db, "Ulinked")
        _set_mvp(db)
        assert len(sent) == 1
        msg = sent[0]
        assert msg["type"] == "mvp" and msg["player_name"] == "Player102"
        assert msg["token_drop"] == {"count": 1, "refresh": True}
        text = json.dumps(msg)
        assert "alice_secret_name" not in text and "Ulinked" not in text and "winners" not in text
        pubsub = _js_function(_ext("panel.js"), "onPubSub")
        assert "drop.count > 0" in pubsub and "loadMe()" in pubsub
        assert "+1 token from the MVP drop" in pubsub

    def test_panel_sends_heartbeat_only_when_joined(self):
        """AC Heartbeat: panel.js sends POST /twitch/heartbeat only for joined viewers."""
        js = _ext("panel.js")
        assert "startHeartbeat" not in _js_function(js, "onReady")
        load_me = _js_function(js, "loadMe")
        assert re.search(r"if \(isJoined\(\)\) \{\s*if \(!state\.heartbeatOn\) \{ startHeartbeat", load_me)
        assert "stopHeartbeat()" in load_me
        calls = [m.start() for m in re.finditer(r"startHeartbeat\(", js)]
        assert len(calls) == 2  # loadMe (joined) and doJoin (after a successful join)
        join = _js_function(js, "doJoin")
        assert join.index("data.joined") < join.index("startHeartbeat(")
        assert "startHeartbeat" not in _ext("extension.js").split("function startHeartbeat", 1)[0]

    def test_twitch_drops_disabled_sets_mvp_and_bonus_without_tokens(self, db, twitch_env, monkeypatch):
        """AC Kill switch: with TWITCH_DROPS_ENABLED=false, set_mvp sets the MVP and fantasy bonus but drops no tokens."""
        from models import PlayerMatchStats, TwitchMVP, TwitchTokenDrop, Weight
        monkeypatch.setenv("TWITCH_DROPS_ENABLED", "false")
        chat = _chat_recorder(monkeypatch)
        db.add(Weight(key="mvp_bonus_pct", label="MVP bonus", value=10.0))
        _seed_series_match(db)
        _join(db, "Usoft")
        _present(db, "Usoft")
        result = _set_mvp(db)
        assert result["token_drop"]["enabled"] is False and result["token_drop"]["winner_count"] == 0
        assert db.query(TwitchMVP).filter_by(match_id=1001, player_id=102).count() == 1
        row = db.query(PlayerMatchStats).filter_by(match_id=1001, player_id=102).one()
        other = db.query(PlayerMatchStats).filter_by(match_id=1001, player_id=103).one()
        assert row.is_mvp is True and other.is_mvp is False
        from scoring import fantasy_score, stat_dict_from_row
        weights = {w.key: w.value for w in db.query(Weight).all()}
        base = fantasy_score(stat_dict_from_row(row), weights)
        assert row.fantasy_points == pytest.approx(base * 1.1, abs=1e-3)  # +10 % MVP bonus
        assert db.query(TwitchTokenDrop).count() == 0
        db.expire_all()
        assert _user_by_opaque(db, "Usoft").tokens == 5
        assert chat == ["Match MVP: Player102!"]

    def test_twitch_drops_enabled_defaults_true(self, db, twitch_env, monkeypatch):
        """AC Kill switch: with TWITCH_DROPS_ENABLED unset, drops run."""
        import twitch
        monkeypatch.delenv("TWITCH_DROPS_ENABLED", raising=False)
        assert twitch.drops_enabled() is True
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _join(db, "Usoft")
        _present(db, "Usoft")
        assert _set_mvp(db)["token_drop"]["winner_count"] == 1
        db.expire_all()
        assert _user_by_opaque(db, "Usoft").tokens == 6

    def test_set_mvp_with_no_joined_viewers_sets_mvp_and_chat_says_no_tokens(self, db, twitch_env, monkeypatch):
        """Failure path: with no joined viewers present, the MVP is still set and the chat says no tokens were dropped."""
        from models import TwitchMVP
        chat = _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _present(db, "Unoaccount")
        result = _set_mvp(db)
        assert result["token_drop"]["pool_size"] == 0
        assert db.query(TwitchMVP).filter_by(match_id=1001).count() == 1
        assert chat == ["Match MVP: Player102! No tokens were dropped: no joined viewers were watching."]


# ---------------------------------------------------------------------------
# Story 5 — No Link Codes in the Extension
# ---------------------------------------------------------------------------

class TestNoLinkCodesInExtension:

    def test_panel_has_no_link_code_ui_or_link_call(self):
        """AC Panel: #view-unlinked, #link-code-input, #btn-link and the kana-cards.com steps are gone, and panel.js never calls /twitch/link."""
        html, js = _ext("panel.html"), _ext("panel.js")
        for gone in ('id="view-unlinked"', 'id="link-code-input"', 'id="btn-link"', "kana-cards.com",
                     "Generate Twitch Code", "6-character"):
            assert gone not in html, gone
        assert "/twitch/link" not in js and "/twitch/status" not in js
        assert "doLink" not in js

    def test_code_linked_website_account_treated_as_joined(self, db):
        """AC Players linked before: a website account whose twitch_user_id matches the opaque id is joined in GET /twitch/me, with its own tokens, collection and roster."""
        import twitch
        _seed_world(db)
        alice = _website_user(db, "alice", twitch_user_id="Ulinked", tokens=7)
        card = _card(db, alice.id, 101, active=True, slot=0)
        data = twitch.me(payload=_viewer("Ulinked"), db=db)
        assert data["joined"] is True and data["website_account"] is True
        assert data["tokens"] == 7
        assert [c["id"] for c in data["collection"]] == [card.id]
        assert [c["id"] for c in data["roster"]["active"]] == [card.id]
        assert "alice" not in json.dumps(data)

    def test_code_linked_website_account_still_in_drop_pool(self, db, twitch_env, monkeypatch):
        """AC Players linked before: a code-linked website account still receives drops."""
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        alice = _website_user(db, "alice", twitch_user_id="Ulinked", tokens=7)
        _present(db, "Ulinked")
        result = _set_mvp(db)
        assert result["token_drop"]["winner_count"] == 1
        db.refresh(alice)
        assert alice.tokens == 8

    def test_profile_hides_generate_twitch_code_and_shows_coming_soon(self):
        """AC Website Profile: index.html/app-profile.js no longer offer "Generate Twitch Code". The "coming soon" placeholder was replaced by Connect Twitch in #160."""
        html = _read(FRONTEND_DIR / "index.html")
        profile = _read(FRONTEND_DIR / "app-profile.js")
        assert "Generate Twitch Code" not in html
        assert "Connect Twitch" in html
        assert "generateTwitchCode" not in html + profile
        assert "/twitch/link-code" not in profile

    def test_twitch_join_by_linked_player_returns_existing_account_without_duplicate(self, db):
        """Failure path: a code-linked player pressing Join gets their website account back; no soft account is created."""
        from models import User
        alice = _website_user(db, "alice", twitch_user_id="Ulinked", tokens=7)
        data = _join(db, "Ulinked")
        assert data["created"] is False and data["website_account"] is True and data["tokens"] == 7
        assert db.query(User).count() == 1
        assert db.query(User).filter(User.account_type == "twitch").count() == 0
        db.refresh(alice)
        assert alice.account_type == "full"


# ---------------------------------------------------------------------------
# Story 6 — Hidden, Private and Removable
# ---------------------------------------------------------------------------

def _two_players_with_points(db):
    """A website user and a soft user, each with a card that scored in a locked week."""
    import card_points
    from models import Week, WeeklyRosterEntry
    _seed_world(db, start_time=int(time.time()) - 3600)
    site = _website_user(db, "site")
    _join(db, "Usoft")
    soft = _user_by_opaque(db, "Usoft")
    now = int(time.time())
    week = Week(label="Week 1", start_time=now - 7200, end_time=now + 3600, is_locked=True)
    db.add(week)
    db.commit()
    for user, pid in ((site, 101), (soft, 201)):
        card = _card(db, user.id, pid, active=True, slot=0)
        db.add(WeeklyRosterEntry(week_id=week.id, user_id=user.id, card_id=card.id, is_bench=False))
    db.commit()
    card_points.rebuild_all(db)
    return site, soft, week


class TestHiddenPrivateRemovable:

    def test_soft_accounts_excluded_from_season_and_weekly_leaderboards(self, db):
        """AC Hidden from rankings: /leaderboard/season, /leaderboard/weekly and /leaderboard/roster omit account_type="twitch" users."""
        from routers.leaderboard import roster_leaderboard, season_leaderboard, weekly_leaderboard
        site, soft, week = _two_players_with_points(db)
        season = season_leaderboard(db=db)
        assert [r["id"] for r in season] == [site.id] and season[0]["season_points"] > 0
        weekly = weekly_leaderboard(week_id=week.id, db=db)
        assert [r["id"] for r in weekly] == [site.id]
        roster = roster_leaderboard(db=db)
        assert [r["username"] for r in roster] == ["site"]

    def test_compute_season_standings_and_archive_exclude_soft_accounts(self, db):
        """AC Hidden from rankings: compute_season_standings and the End Season season_archive snapshot omit soft accounts."""
        from models import SeasonArchive
        from routers.admin_season import SeasonEndBody, end_season
        from routers.leaderboard import compute_season_standings
        site, soft, _ = _two_players_with_points(db)
        assert [r["id"] for r in compute_season_standings(db)] == [site.id]
        end_season(body=SeasonEndBody(season_label="S157"), db=db, admin=_ADMIN)
        assert [r.user_id for r in db.query(SeasonArchive).all()] == [site.id]

    def test_user_search_and_tag_lists_exclude_soft_accounts(self, db):
        """AC Hidden from rankings: user search and tag lists omit soft accounts."""
        from models import TagDefinition
        from routers.admin_tags import grant_tag
        from routers.admin_users import list_users
        from routers.profile import get_profile
        site = _website_user(db, "site")
        _join(db, "Usoft")
        soft = _user_by_opaque(db, "Usoft")
        db.add(TagDefinition(key="caster", label="Caster"))
        db.commit()
        tag = db.query(TagDefinition).one()
        # The admin user search filters the default (website accounts) list client-side.
        assert [u["id"] for u in list_users(db=db, _=_ADMIN)] == [site.id]
        _raises(lambda: grant_tag(soft.id, tag.id, db=db, admin=_ADMIN), 404)
        assert grant_tag(site.id, tag.id, db=db, admin=_ADMIN) == {"ok": True}
        _raises(lambda: get_profile(soft.id, db=db, current_user={"user_id": site.id}), 404)

    def test_admin_users_list_twitch_viewers_filter(self, db):
        """AC Admin users list: a Twitch viewers filter lists soft accounts as "Twitch viewer #{id}" with tokens, card count, created and last seen, no password actions."""
        from routers.admin_users import list_users
        _seed_world(db)
        site = _website_user(db, "site")
        _join(db, "Usoft", user_id="31337")
        soft = _user_by_opaque(db, "Usoft")
        _card(db, soft.id, 101)
        _card(db, soft.id, 102)
        rows = list_users(account_type="twitch", db=db, _=_ADMIN)
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == soft.id and row["username"] == f"Twitch viewer #{soft.id}"
        assert row["account_type"] == "twitch" and row["tokens"] == 5 and row["card_count"] == 2
        assert row["created_at"] and row["last_seen_at"]
        assert row["twitch_identity_shared"] is True
        _no_twitch_ids(rows, "Usoft", "31337")
        assert {r["id"] for r in list_users(account_type="all", db=db, _=_ADMIN)} == {site.id, soft.id}
        _raises(lambda: list_users(account_type="bogus", db=db, _=_ADMIN), 422)
        js = _read(FRONTEND_DIR / "app-admin-users.js")
        viewer_row = _js_function(js, "_renderTwitchViewerRow")
        for action in ("password", "toggleAdmin", "toggleTester", "openTagManager", "forceLogout"):
            assert action not in viewer_row
        assert "deleteTwitchViewer" in viewer_row
        html = _read(FRONTEND_DIR / "index.html")
        assert '<option value="twitch">Twitch viewers</option>' in html

    def test_admin_can_delete_soft_account(self, db):
        """AC Admin users list: admin delete removes a soft account and its rows."""
        from models import AuditLog, Card, User
        from routers.admin_users import delete_twitch_viewer
        _seed_world(db)
        site = _website_user(db, "site")
        _join(db, "Usoft")
        soft = _user_by_opaque(db, "Usoft")
        soft_id = soft.id
        _card(db, soft_id, 101)
        assert delete_twitch_viewer(soft_id, admin=_ADMIN, db=db) == {"deleted": True, "user_id": soft_id}
        assert db.get(User, soft_id) is None
        assert db.query(Card).filter(Card.owner_id == soft_id).count() == 0
        assert db.query(AuditLog).filter(AuditLog.action == "twitch_soft_account_deleted").count() == 1
        _raises(lambda: delete_twitch_viewer(site.id, admin=_ADMIN, db=db), 409)
        _raises(lambda: delete_twitch_viewer(99999, admin=_ADMIN, db=db), 404)

    def test_twitch_leave_deletes_soft_account_and_all_rows(self, db):
        """AC Leave: POST /twitch/leave deletes a soft account with its cards, card points, roster entries and per-user state, and audits twitch_soft_account_deleted."""
        import twitch
        from models import (AuditLog, Card, CardMatchPoints, CardModifier, TwitchPresence, User,
                            WeeklyRosterEntry, WeeklySummarySeen)
        site, soft, week = _two_players_with_points(db)
        soft_id = soft.id
        soft_cards = [c.id for c in db.query(Card).filter(Card.owner_id == soft_id)]
        db.add(CardModifier(card_id=soft_cards[0], stat_key="kills", bonus_pct=10.0))
        db.add(WeeklySummarySeen(user_id=soft_id, last_seen_week_id=week.id))
        db.commit()
        _present(db, "Usoft")
        assert db.query(CardMatchPoints).filter(CardMatchPoints.card_id.in_(soft_cards)).count() > 0
        assert twitch.leave(_viewer("Usoft"), db) == {"left": True, "deleted": True}
        assert db.get(User, soft_id) is None
        assert db.query(Card).filter(Card.owner_id == soft_id).count() == 0
        assert db.query(CardModifier).filter(CardModifier.card_id.in_(soft_cards)).count() == 0
        assert db.query(CardMatchPoints).filter(CardMatchPoints.card_id.in_(soft_cards)).count() == 0
        assert db.query(WeeklyRosterEntry).filter_by(user_id=soft_id).count() == 0
        assert db.query(WeeklySummarySeen).filter_by(user_id=soft_id).count() == 0
        assert db.query(TwitchPresence).filter_by(twitch_user_id="Usoft").count() == 0
        audit = db.query(AuditLog).filter(AuditLog.action == "twitch_soft_account_deleted").one()
        assert f"user_id={soft_id}" in audit.detail and "Usoft" not in audit.detail
        # The website user's data is untouched.
        assert db.query(Card).filter(Card.owner_id == site.id).count() == 1
        assert db.query(WeeklyRosterEntry).filter_by(user_id=site.id).count() == 1

    def test_twitch_leave_only_unlinks_website_account(self, db):
        """AC Leave: for a linked website account, leave clears twitch_user_id only and keeps all data."""
        import twitch
        from models import Card, User
        _seed_world(db)
        alice = _website_user(db, "alice", twitch_user_id="Ulinked", tokens=7)
        _card(db, alice.id, 101)
        assert twitch.leave(_viewer("Ulinked"), db) == {"left": True, "deleted": False}
        db.expire_all()
        alice = db.get(User, alice.id)
        assert alice is not None and alice.twitch_user_id is None and alice.tokens == 7
        assert db.query(Card).filter(Card.owner_id == alice.id).count() == 1

    def test_twitch_leave_twice_or_without_account_returns_200_no_change(self, db):
        """Failure path: leaving twice, or leaving without an account, returns 200 with no change."""
        import twitch
        from models import User
        _join(db, "Usoft")
        site = _website_user(db, "site")
        assert twitch.leave(_viewer("Usoft"), db)["left"] is True
        assert twitch.leave(_viewer("Usoft"), db) == {"left": False, "deleted": False}
        assert twitch.leave(_viewer("Unobody"), db) == {"left": False, "deleted": False}
        assert twitch.leave(_ANON, db) == {"left": False, "deleted": False}
        assert [u.id for u in db.query(User).all()] == [site.id]

    def test_purge_inactive_soft_accounts_deletes_only_inactive_soft_accounts(self, db):
        """AC Retention: purge_inactive_soft_accounts deletes soft accounts idle past the retention days, keeps active ones and every website account, and audits each deletion."""
        import soft_accounts
        from models import AuditLog, User
        now = int(time.time())
        day = 86400
        for oid in ("Uidle", "Uactive", "Unever"):
            _join(db, oid)
        _user_by_opaque(db, "Uidle").last_seen_at = now - 400 * day
        _user_by_opaque(db, "Uactive").last_seen_at = now - day
        never = _user_by_opaque(db, "Unever")
        never.last_seen_at = None
        never.created_at = now - 500 * day
        old_site = _website_user(db, "old_site")
        old_site.created_at = now - 900 * day
        db.commit()
        assert soft_accounts.purge_inactive_soft_accounts(db, now, 365) == 2
        remaining = {u.twitch_user_id or u.username for u in db.query(User).all()}
        assert remaining == {"Uactive", "old_site"}
        audits = db.query(AuditLog).filter(AuditLog.action == "twitch_soft_account_deleted").all()
        assert len(audits) == 2 and all("reason=retention" in a.detail for a in audits)
        assert soft_accounts.purge_inactive_soft_accounts(db, now, 365) == 0

    def test_retention_job_registered_with_365_day_default(self, monkeypatch):
        """AC Retention: main runs a daily retention job; TWITCH_SOFT_ACCOUNT_RETENTION_DAYS defaults to 365."""
        import soft_accounts
        src = _read(REPO_ROOT / "backend" / "main.py")
        loop = src[src.index("def _week_maintenance_loop"):src.index("def _profile_enrichment_loop")]
        assert "soft_accounts.purge_inactive_soft_accounts(" in loop
        assert "_SOFT_ACCOUNT_PURGE_INTERVAL" in loop
        assert re.search(r"_SOFT_ACCOUNT_PURGE_INTERVAL\s*=\s*86400", src)
        monkeypatch.delenv("TWITCH_SOFT_ACCOUNT_RETENTION_DAYS", raising=False)
        assert soft_accounts.retention_days() == 365
        monkeypatch.setenv("TWITCH_SOFT_ACCOUNT_RETENTION_DAYS", "30")
        assert soft_accounts.retention_days() == 30
        monkeypatch.setenv("TWITCH_SOFT_ACCOUNT_RETENTION_DAYS", "junk")
        assert soft_accounts.retention_days() == 365

    def test_privacy_and_terms_describe_soft_account_data_and_leaving(self):
        """AC Privacy text: privacy.html and terms.html describe the opaque Twitch id, optional real Twitch user id, game progress, timestamps, why, and how to leave."""
        privacy = _read(FRONTEND_DIR / "privacy.html")
        for phrase in ("soft account", "opaque", "real Twitch user id", "game progress", "timestamps",
                       "to run the game", "Leave Kana Cards", "365 days"):
            assert phrase in privacy, phrase
        assert "We do not request Twitch's\nelevated identity-sharing permission" not in privacy
        terms = _read(FRONTEND_DIR / "terms.html")
        for phrase in ("soft account", "opaque Twitch id", "leave at any time", "365"):
            assert phrase in terms, phrase

    def test_no_public_or_player_route_returns_twitch_ids(self, db, monkeypatch):
        """AC No public Twitch ids: no public or player-facing route (website or EBS), including GET /twitch/me, returns twitch_user_id or twitch_account_id; the admin users list is the only exception."""
        import twitch
        from routers import cards, leaderboard, profile
        _schedule_with(monkeypatch, _UPCOMING_WEEKS)
        site, soft, week = _two_players_with_points(db)
        soft.twitch_account_id = "4815162342"
        site.twitch_user_id = "Usitelinked"
        db.commit()
        v = _viewer("Usoft", user_id="4815162342")
        site_user = {"user_id": site.id, "username": "site", "is_admin": False}
        monkeypatch.setattr(cards, "session_user_or_none", lambda request, db_: site)
        outputs = [
            twitch.me(payload=v, db=db), twitch.join(v, db), twitch.panel_live(payload=v, db=db),
            twitch.teams(payload=v, db=db), twitch.current_matches(payload=v, db=db),
            twitch.draw(v, db),
            leaderboard.season_leaderboard(db=db), leaderboard.weekly_leaderboard(week_id=week.id, db=db),
            leaderboard.roster_leaderboard(db=db), leaderboard.top_performances(db=db),
            leaderboard.list_archived_seasons(db=db),
            profile.me(db=db, current_user=site_user), profile.get_profile(site.id, db=db, current_user=site_user),
            cards.get_roster(site.id, None, db=db, current_user=site_user),
            cards.get_booster_deck(request=None, db=db),
        ]
        for out in outputs:
            _no_twitch_ids(out, "Usoft", "Usitelinked", "4815162342")
        # No response dict in the routers or the EBS names these fields.
        for path in list((REPO_ROOT / "backend" / "routers").glob("*.py")) + [REPO_ROOT / "backend" / "twitch.py"]:
            assert not re.search(r"[\"']twitch_(user|account)_id[\"']\s*:", path.read_text()), path.name

    def test_admin_exports_omit_twitch_ids(self, db):
        """AC No public Twitch ids: admin exports leave out twitch_user_id and twitch_account_id."""
        from routers.admin_season import get_audit_logs
        from routers.admin_users import list_users
        _join(db, "Uexported", user_id="2718281828")
        _website_user(db, "linked", twitch_user_id="Ulinkedsite")
        _join(db, "Ulinkedsite")
        for out in (get_audit_logs(db=db, limit=200, _=_ADMIN),
                    list_users(account_type="all", db=db, _=_ADMIN)):
            _no_twitch_ids(out, "Uexported", "2718281828", "Ulinkedsite")

    def test_no_viewer_password_field_and_listing_never_asks_for_passwords(self):
        """AC No password requests: no viewer file has type="password"; the listing and privacy page say "Kana Cards never asks for your Twitch or website password inside Twitch."."""
        for name in VIEWER_FILES:
            assert not re.search(r'type="?password', _ext(name), re.I), name
        line = "Kana Cards never asks for your Twitch or website password inside Twitch."
        doc = _read(REPO_ROOT / "markdown" / "features" / "reference" / "twitch-extension-review-submission.md")
        description = doc[doc.index("**Description** (full):"):doc.index("This wording is deliberately")]
        assert line in " ".join(l.lstrip("> ").strip() for l in description.splitlines())
        privacy = re.sub(r"<[^>]+>", "", _read(FRONTEND_DIR / "privacy.html"))
        assert line in " ".join(privacy.split())


# ---------------------------------------------------------------------------
# Implementation — migration, packaging, config
# ---------------------------------------------------------------------------

def _legacy_users_engine():
    from sqlalchemy import create_engine, text
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT, email TEXT, password_hash TEXT,
                is_admin BOOLEAN, tokens INTEGER, created_at INTEGER, player_id INTEGER,
                must_change_password BOOLEAN, twitch_user_id TEXT
            )
        """))
        conn.execute(text("INSERT INTO users (id, username, tokens, twitch_user_id) VALUES "
                          "(1, 'old1', 5, 'Ulegacy'), (2, 'old2', 3, NULL)"))
        conn.commit()
    return engine


class TestMigrationAndPackaging:

    def test_migration_031_adds_soft_account_columns_on_legacy_schema(self, tmp_path):
        """Step 1: migration 031 adds account_type, last_seen_at and twitch_account_id to a legacy users table."""
        import migrate
        from sqlalchemy import text
        assert ("031_users_twitch_soft_accounts", migrate._m031_users_twitch_soft_accounts) in migrate.MIGRATIONS
        ids = [m[0] for m in migrate.MIGRATIONS]
        assert ids.index("031_users_twitch_soft_accounts") == ids.index("030_weekly_summary_seen_last_prompted") + 1
        engine = _legacy_users_engine()
        with engine.connect() as conn:
            migrate._m031_users_twitch_soft_accounts(conn)
            cols = {r[1]: r for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
            assert {"account_type", "last_seen_at", "twitch_account_id"} <= set(cols)
            assert cols["account_type"][3] == 1  # NOT NULL
            # Idempotent: a second run is a no-op.
            migrate._m031_users_twitch_soft_accounts(conn)

    def test_migration_031_sets_existing_users_to_full_and_indexes_twitch_account_id(self, tmp_path):
        """Step 1: existing users get account_type="full" and twitch_account_id has a unique index."""
        import migrate
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        engine = _legacy_users_engine()
        with engine.connect() as conn:
            migrate._m031_users_twitch_soft_accounts(conn)
            rows = conn.execute(text("SELECT id, account_type FROM users ORDER BY id")).fetchall()
            assert [tuple(r) for r in rows] == [(1, "full"), (2, "full")]
            indexes = {r[1]: r[2] for r in conn.execute(text("PRAGMA index_list(users)")).fetchall()}
            assert indexes.get("ux_users_twitch_account_id") == 1
            assert indexes.get("ux_users_twitch_user_id") == 1
            conn.execute(text("UPDATE users SET twitch_account_id = '42' WHERE id = 1"))
            with pytest.raises(IntegrityError):
                conn.execute(text("UPDATE users SET twitch_account_id = '42' WHERE id = 2"))
            conn.rollback()
            with pytest.raises(IntegrityError):
                conn.execute(text("UPDATE users SET twitch_user_id = 'Ulegacy' WHERE id = 2"))
            conn.rollback()
            # A new row without account_type gets the default.
            conn.execute(text("INSERT INTO users (id, username) VALUES (3, 'new')"))
            assert conn.execute(text("SELECT account_type FROM users WHERE id = 3")).scalar() == "full"

    def test_package_sh_has_self_check_and_targets_version_1_2_0(self, tmp_path):
        """Step 7: package.sh contains the forbidden-text self-check and `package.sh 1.2.0` builds on the clean tree."""
        src = _ext("package.sh")
        assert "FORBIDDEN_TEXT=" in src and "VIEWER_FILES=" in src
        for phrase in FORBIDDEN:
            assert f'"{phrase}"' in src
        assert "1.2.0" in src
        if shutil.which("zip") is None:
            return  # the static checks above still ran; the build needs zip
        ext = tmp_path / "twitch-extension"
        shutil.copytree(EXTENSION_DIR, ext, ignore=shutil.ignore_patterns("*.zip"))
        result = subprocess.run(["bash", str(ext / "package.sh"), "1.2.0"],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        with zipfile.ZipFile(ext / "twitch-extension-1.2.0.zip") as zf:
            names = zf.namelist()
        for name in VIEWER_FILES + ["config.html", "live_config.js", "fonts/BigShouldersText-VariableFont_wght.ttf"]:
            assert name in names
        assert "dev-harness.html" not in names

    def test_env_example_lists_drops_enabled_and_retention_days(self):
        """Critical Files: .env.example documents TWITCH_DROPS_ENABLED and TWITCH_SOFT_ACCOUNT_RETENTION_DAYS."""
        env = _read(REPO_ROOT / ".env.example")
        assert "# TWITCH_DROPS_ENABLED=true" in env
        assert "# TWITCH_SOFT_ACCOUNT_RETENTION_DAYS=365" in env
        for name in ("RATE_LIMIT_TWITCH_JOIN", "RATE_LIMIT_TWITCH_JOIN_IP", "RATE_LIMIT_TWITCH_ACTION"):
            assert f"# {name}=" in env
