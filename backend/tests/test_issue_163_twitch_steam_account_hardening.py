"""Tests for issue #163: Twitch, Steam and account hardening (sub-issues #164-#168).

#169 and #171 shipped with PR 174 and are covered by test_issue_169_* and
test_issue_171_*.

Plan: markdown/plans/plan-issue-163-twitch-steam-account-hardening.md

One class per sub-issue. Static checks cover the Twitch extension files and
shell scripts; the backend is exercised through direct function calls and small
TestClient apps, following tests/test_issue_157_* and tests/test_issue_123_*.
"""
import base64
import importlib
import logging
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import zipfile
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
EXT_DIR = REPO_ROOT / "twitch-extension"

_SECRET_BYTES = b"issue-163-test-extension-secret!"
_SECRET_B64 = base64.b64encode(_SECRET_BYTES).decode()
_CHANNEL = "chan-163"


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def _engine():
    from database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _session(engine):
    return sessionmaker(bind=engine)()


def _signed(claims, secret=_SECRET_BYTES):
    import jwt as pyjwt
    return "Bearer " + pyjwt.encode(claims, secret, algorithm="HS256")


def _viewer_claims(opaque_id="Uviewer", role="viewer", user_id=None, exp=True):
    claims = {"opaque_user_id": opaque_id, "role": role, "channel_id": _CHANNEL}
    if exp:
        claims["exp"] = int(time.time()) + 300
    if user_id:
        claims["user_id"] = user_id
    return claims


@pytest.fixture
def twitch_env(monkeypatch):
    monkeypatch.delenv("TWITCH_LOCAL_DEV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("TWITCH_EXTENSION_SECRET", _SECRET_B64)


def _route(router, path, method):
    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return r
    raise AssertionError(f"route {method} {path} not found")


def _needs_reauth(route):
    from deps import require_recent_reauth
    return any(d.call is require_recent_reauth for d in route.dependant.dependencies)


# ---------------------------------------------------------------------------
# #165 — Twitch defaults fail closed
# ---------------------------------------------------------------------------

class TestFailClosedDefaults:
    def test_empty_allowlist_refuses_every_channel_in_production(self, monkeypatch):
        import twitch
        monkeypatch.setenv("ENV", "production")
        monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
        assert twitch.mvp_channel_allowed("123") is False

    def test_empty_allowlist_allows_any_channel_outside_production(self, monkeypatch):
        import twitch
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
        assert twitch.mvp_channel_allowed("123") is True

    def test_listed_channel_allowed_and_other_refused_in_production(self, monkeypatch):
        import twitch
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "111, 222")
        assert twitch.mvp_channel_allowed("222") is True
        assert twitch.mvp_channel_allowed("333") is False

    def test_set_mvp_returns_403_in_production_without_list(self, monkeypatch, db):
        import twitch
        monkeypatch.setenv("ENV", "production")
        monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
        payload = {"role": "broadcaster", "channel_id": _CHANNEL, "opaque_user_id": "Ub"}
        with pytest.raises(HTTPException) as exc:
            twitch.set_mvp(twitch.MVPBody(match_id=1, player_id=2), payload, db)
        assert exc.value.status_code == 403

    def test_startup_warning_when_production_list_is_empty(self, monkeypatch, caplog):
        import twitch
        monkeypatch.setenv("ENV", "production")
        monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
        with caplog.at_level(logging.WARNING, logger="twitch"):
            twitch.warn_if_mvp_channels_unset()
        assert any("TWITCH_MVP_CHANNEL_IDS" in r.getMessage() for r in caplog.records)

    def test_token_without_exp_is_refused(self, twitch_env):
        import twitch
        with pytest.raises(HTTPException) as exc:
            twitch.verify_twitch_jwt(None, _signed(_viewer_claims(exp=False)))
        assert exc.value.status_code == 401

    def test_external_role_is_refused(self, twitch_env):
        import twitch
        with pytest.raises(HTTPException) as exc:
            twitch.verify_twitch_jwt(None, _signed(_viewer_claims(role="external")))
        assert exc.value.status_code == 403

    def test_valid_viewer_token_still_accepted(self, twitch_env):
        import twitch
        payload = twitch.verify_twitch_jwt(None, _signed(_viewer_claims()))
        assert payload["opaque_user_id"] == "Uviewer"

    def test_invalid_token_log_has_no_secret_length(self, twitch_env, caplog):
        import twitch
        with caplog.at_level(logging.ERROR, logger="twitch"):
            with pytest.raises(HTTPException):
                twitch.verify_twitch_jwt(None, _signed(_viewer_claims(), secret=b"wrong-secret-xxxxxxxxxxxxxxxxxxxx"))
        text_ = " ".join(r.getMessage() for r in caplog.records)
        assert "secret len" not in text_ and "decoded_bytes" not in text_

    def test_local_dev_refused_with_https_only(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DEBUG", "SECRET_KEY", "ENV")}
        env.update({"TWITCH_LOCAL_DEV": "true", "HTTPS_ONLY": "true",
                    "BACKGROUND_TASKS_ENABLED": "false"})
        result = subprocess.run([sys.executable, "-c", "import main"], cwd=BACKEND_DIR, env=env,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode != 0
        assert "TWITCH_LOCAL_DEV=true is not allowed with HTTPS_ONLY=true" in result.stderr


# ---------------------------------------------------------------------------
# #164 — the panel talks only to the approved backend
# ---------------------------------------------------------------------------

def _copy_ext(tmp_path):
    dest = tmp_path / "twitch-extension"
    shutil.copytree(EXT_DIR, dest, ignore=shutil.ignore_patterns("*.zip"))
    return dest


def _package(ext, *args):
    return subprocess.run(["bash", str(ext / "package.sh"), *args],
                          capture_output=True, text=True, timeout=60)


class TestPinnedBackendOrigins:
    def test_repository_origins_file_is_an_empty_list(self):
        src = _read(EXT_DIR / "ebs-origins.js")
        assert re.search(r"var EBS_ALLOWED_ORIGINS = \[\];", src)

    def test_every_page_loads_origins_before_extension_js(self):
        for page in ("panel.html", "config.html", "live_config.html"):
            src = _read(EXT_DIR / page)
            assert src.index('src="ebs-origins.js"') < src.index('src="extension.js"'), page

    def test_config_handler_checks_the_url_before_using_it(self):
        src = _read(EXT_DIR / "extension.js")
        handler = src[src.index("function _onCfgChanged"):src.index("function _onAuth")]
        assert handler.index("_ebsUrlAllowed(cfg.ebs_url)") < handler.index("ext.ebsUrl = cfg.ebs_url")

    def test_dev_harness_sets_its_flag(self):
        assert "window.__EXT_DEV_HARNESS = true;" in _read(EXT_DIR / "dev-harness.html")

    @pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
    @pytest.mark.parametrize("origins,harness,url,expected", [
        (["https://league.example"], False, "https://league.example", True),
        (["https://league.example"], False, "https://league.example/api", True),
        (["https://league.example"], False, "https://evil.example", False),
        (["https://league.example"], False, "http://league.example", False),
        (["https://league.example"], False, "https://league.example.evil.example", False),
        (["https://league.example"], True, "https://evil.example", False),
        ([], False, "https://league.example", False),
        ([], True, "http://localhost:8000", True),
    ])
    def test_url_check_logic(self, origins, harness, url, expected):
        import json
        src = _read(EXT_DIR / "extension.js")
        fn = src[src.index("function _ebsUrlAllowed"):src.index("function _onCfgChanged")]
        script = (f"var window = {{__EXT_DEV_HARNESS: {json.dumps(harness)}}};"
                  f"var EBS_ALLOWED_ORIGINS = {json.dumps(origins)};{fn}"
                  f"process.stdout.write(String(_ebsUrlAllowed({json.dumps(url)})));")
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        assert out.stdout == str(expected).lower(), out.stderr

    @pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not installed")
    def test_package_refuses_without_origin(self, tmp_path):
        ext = _copy_ext(tmp_path)
        result = _package(ext, "9.9.9")
        assert result.returncode != 0
        assert "--ebs-origin" in result.stderr
        assert not (ext / "twitch-extension-9.9.9.zip").exists()

    @pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not installed")
    @pytest.mark.parametrize("bad", ["http://league.example", "https://league.example/",
                                     "https://league.example/api", "league.example", ""])
    def test_package_refuses_bad_origin(self, tmp_path, bad):
        ext = _copy_ext(tmp_path)
        result = _package(ext, "9.9.9", "--ebs-origin", bad)
        assert result.returncode != 0
        assert not (ext / "twitch-extension-9.9.9.zip").exists()

    @pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not installed")
    def test_package_bakes_given_origins_and_keeps_repo_file(self, tmp_path):
        ext = _copy_ext(tmp_path)
        result = _package(ext, "9.9.9", "--ebs-origin", "https://league.example",
                          "--ebs-origin", "https://test.league.example")
        assert result.returncode == 0, result.stdout + result.stderr
        with zipfile.ZipFile(ext / "twitch-extension-9.9.9.zip") as zf:
            baked = zf.read("ebs-origins.js").decode()
            assert "dev-harness.html" not in zf.namelist()
        assert '["https://league.example", "https://test.league.example"]' in baked
        assert re.search(r"var EBS_ALLOWED_ORIGINS = \[\];", _read(ext / "ebs-origins.js"))

    def test_set_ebs_url_never_puts_the_secret_on_a_command_line_or_screen(self):
        src = _read(EXT_DIR / "set-ebs-url.sh")
        assert 'python3 - "$secret"' not in src
        assert "sys.argv" not in src
        assert "secret.hex()" not in src
        assert 'TWITCH_EXT_SECRET=""' not in src
        assert 'TWITCH_EXT_SECRET="${TWITCH_EXT_SECRET:-}"' in src
        assert "read -rsp" in src


# ---------------------------------------------------------------------------
# #166 — no phishing text in trusted channels
# ---------------------------------------------------------------------------

class TestTrustedChannelText:
    @pytest.mark.parametrize("name,expected", [
        ("Miracle-", "Miracle-"),
        ("free skins at steam-gift.example", "Player 7"),
        ("visit www.example", "Player 7"),
        ("https://x", "Player 7"),
        ("cheap.GG items", "Player 7"),
        ("Ana​‮Topson", "AnaTopson"),
        ("", "Player 7"),
        ("x" * 40, "x" * 32),
        ("v1.2 Dendi", "v1.2 Dendi"),
    ])
    def test_chat_safe_name(self, name, expected):
        import twitch
        assert twitch.chat_safe_name(name, 7) == expected

    def test_mvp_chat_uses_the_cleaned_name(self, monkeypatch, db):
        import twitch
        from models import Match, Player, PlayerMatchStats, Team
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
        db.add_all([Team(id=11, name="A"), Team(id=12, name="B"),
                    Player(id=101, name="claim skins at steam-gift.example"),
                    Match(match_id=901, radiant_team_id=11, dire_team_id=12,
                          start_time=int(time.time()) - 3600, radiant_win=True)])
        db.add(PlayerMatchStats(player_id=101, match_id=901, team_id=11, fantasy_points=5.0, kills=1))
        db.commit()
        sent, broadcast = [], []
        monkeypatch.setattr(twitch, "_post_chat_message", lambda ch, msg: sent.append(msg))
        monkeypatch.setattr(twitch, "_pubsub_broadcast", lambda ch, msg: broadcast.append(msg))
        payload = {"role": "broadcaster", "channel_id": _CHANNEL, "opaque_user_id": "Ub"}
        twitch.set_mvp(twitch.MVPBody(match_id=901, player_id=101), payload, db)
        assert sent and sent[0].startswith("Match MVP: Player 101!")
        assert "steam-gift" not in sent[0]
        assert broadcast[0]["player_name"] == "Player 101"

    def test_picker_shows_chat_preview(self):
        js = _read(EXT_DIR / "live_config.js")
        assert "function showChatPreview" in js and "player.chat_name" in js
        assert 'id="chat-preview"' in _read(EXT_DIR / "live_config.html")

    def _create(self, db, message):
        from routers import admin_notifications
        now = int(time.time())
        return admin_notifications.create_notification(
            admin_notifications.NotificationBody(message=message, start_time=now, end_time=now + 60),
            db, {"user_id": 1, "username": "admin", "is_admin": True})

    def test_notification_with_outside_link_is_refused(self, monkeypatch, db):
        monkeypatch.setenv("APP_BASE_URL", "https://league.example")
        for msg in ("Link your Steam at steam-verify.example", "See https://evil.example/x",
                    "Go to https://league.example.evil.example"):
            with pytest.raises(HTTPException) as exc:
                self._create(db, msg)
            assert exc.value.status_code == 422, msg

    def test_notification_with_own_link_or_no_link_is_accepted(self, monkeypatch, db):
        monkeypatch.setenv("APP_BASE_URL", "https://league.example")
        assert self._create(db, "Rosters lock Sunday.\nSee https://league.example/#rules")["id"]
        assert self._create(db, "Week 3 starts now")["id"]

    def test_notification_strips_invisible_characters(self, monkeypatch, db):
        from models import Notification
        monkeypatch.setenv("APP_BASE_URL", "https://league.example")
        nid = self._create(db, "Hello‮ there\nline two")["id"]
        assert db.get(Notification, nid).message == "Hello there\nline two"


# ---------------------------------------------------------------------------
# #167 — admin token actions need a fresh password check; promo code limits
# ---------------------------------------------------------------------------

class TestAdminReauthAndPromoCodes:
    @pytest.mark.parametrize("path,method", [
        ("/admin/notifications", "POST"),
        ("/admin/notifications/{notification_id}", "DELETE"),
        ("/grant-tokens", "POST"),
        ("/codes", "POST"),
        ("/codes/{code_id}", "DELETE"),
        ("/admin/token-grant-events", "POST"),
        ("/admin/token-grant-events/{event_id}", "DELETE"),
        ("/users/{user_id}/toggle-tester", "POST"),
    ])
    def test_route_requires_recent_reauth(self, path, method):
        from routers import admin_notifications, admin_users
        module = admin_notifications if "notifications" in path else admin_users
        assert _needs_reauth(_route(module.router, path, method))

    @pytest.mark.parametrize("fn", ["grantTokens", "createCode", "_confirmDeleteCode", "toggleTester"])
    def test_admin_users_frontend_uses_admin_fetch(self, fn):
        src = _read(REPO_ROOT / "frontend" / "app-admin-users.js")
        m = re.search(r"function\s+" + fn + r"\s*\([^)]*\)\s*\{", src)
        assert m, fn
        body = src[m.end():m.end() + 2500]
        assert "adminFetch(" in body.split("\nasync function")[0].split("\nfunction")[0], fn

    def test_notification_frontend_uses_admin_fetch_for_writes(self):
        src = _read(REPO_ROOT / "frontend" / "app-admin-notifications.js")
        assert re.search(r'adminFetch\(`\$\{API\}/admin/notifications`, \{', src)
        assert re.search(r'adminFetch\(`\$\{API\}/admin/token-grant-events`, \{', src)

    def _admin(self):
        return {"user_id": 1, "username": "admin", "is_admin": True}

    def _user(self, db, name):
        from models import User
        u = User(username=name, email=f"{name}@example.com", password_hash="x", tokens=0,
                 created_at=int(time.time()))
        db.add(u)
        db.commit()
        return u

    def _redeem(self, db, user, code):
        from routers import admin_users
        return admin_users.redeem_code(admin_users.RedeemCodeBody(code=code), db,
                                       {"user_id": user.id, "username": user.username})

    def test_unknown_expired_and_used_up_codes_get_the_same_answer(self, db):
        from models import PromoCode
        from routers import admin_users
        db.add_all([PromoCode(code="OLD", token_amount=1, expires_at=int(time.time()) - 10),
                    PromoCode(code="ONCE", token_amount=1, max_redemptions=1)])
        db.commit()
        first, second = self._user(db, "p1"), self._user(db, "p2")
        assert self._redeem(db, first, "ONCE")["granted"] == 1
        details = set()
        for code, user in (("NOPE", second), ("OLD", second), ("ONCE", second)):
            with pytest.raises(HTTPException) as exc:
                self._redeem(db, user, code)
            assert exc.value.status_code == 404
            details.add(exc.value.detail)
        assert details == {admin_users.INVALID_CODE_DETAIL}

    def test_code_under_its_limits_still_redeems(self, db):
        from models import PromoCode
        db.add(PromoCode(code="OPEN", token_amount=2, max_redemptions=5,
                         expires_at=int(time.time()) + 3600))
        db.commit()
        assert self._redeem(db, self._user(db, "p3"), "OPEN")["tokens"] == 2

    def test_create_code_stores_limits_and_rejects_past_expiry(self, db):
        from routers import admin_users
        future = int(time.time()) + 3600
        out = admin_users.create_code(admin_users.CreateCodeBody(
            code="lim", token_amount=1, expires_at=future, max_redemptions=3), db, self._admin())
        assert (out["expires_at"], out["max_redemptions"]) == (future, 3)
        listed = admin_users.list_codes(db, self._admin())
        assert listed[0]["max_redemptions"] == 3 and listed[0]["expires_at"] == future
        with pytest.raises(HTTPException) as exc:
            admin_users.create_code(admin_users.CreateCodeBody(
                code="past", token_amount=1, expires_at=int(time.time()) - 1), db, self._admin())
        assert exc.value.status_code == 422

    def test_migration_036_adds_columns_to_legacy_table(self):
        import migrate
        engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE promo_codes (id INTEGER PRIMARY KEY, code TEXT, "
                              "token_amount INTEGER, created_by_id INTEGER)"))
            conn.commit()
            migrate._m036_promo_codes_limits(conn)
            migrate._m036_promo_codes_limits(conn)  # idempotent
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(promo_codes)")).fetchall()}
        assert {"expires_at", "max_redemptions"} <= cols
        assert ("036_promo_codes_limits", migrate._m036_promo_codes_limits) in migrate.MIGRATIONS


# ---------------------------------------------------------------------------
# #168 — reset codes and lockouts resist abuse
# ---------------------------------------------------------------------------

def _auth_app(engine):
    import rate_limit
    import routers.auth as auth_router
    import routers.profile as profile_router
    from database import get_db
    importlib.reload(rate_limit)
    importlib.reload(auth_router)
    rate_limit.limiter.enabled = False
    Session = sessionmaker(bind=engine)

    def _get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-163")
    app.include_router(auth_router.router)
    app.include_router(profile_router.router)
    app.dependency_overrides[get_db] = _get_db
    return app, auth_router


def _make_user(db, username="alice", password="secret123", email=None, is_admin=False, player_id=None):
    from auth import hash_password
    from models import User
    u = User(username=username, email=email or f"{username}@example.com",
             password_hash=hash_password(password), tokens=5, created_at=int(time.time()),
             is_admin=is_admin, player_id=player_id)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class _Mail:
    def __init__(self):
        self.calls = []

    def __call__(self, to_address, subject, body):
        self.calls.append({"to": to_address, "subject": subject, "body": body})
        return True


class TestResetAndLockout:
    @pytest.fixture
    def setup(self):
        engine = _engine()
        app, auth_router = _auth_app(engine)
        return TestClient(app), _session(engine), auth_router

    def test_reset_token_is_stored_hashed_and_still_works(self, setup):
        from models import PasswordResetToken
        client, db, auth_router = setup
        _make_user(db)
        mail = _Mail()
        with patch("routers.auth.send_email", side_effect=mail):
            assert client.post("/forgot-password", json={"username": "alice"}).status_code == 200
        raw = re.search(r"Reset code: (\S+)", mail.calls[0]["body"]).group(1)
        stored = db.query(PasswordResetToken).one().token
        assert stored != raw and stored == auth_router.hash_reset_token(raw)
        assert client.post("/reset-password", json={"token": stored, "new_password": "newpass1"}).status_code == 400
        with patch("routers.auth.send_email", side_effect=mail):
            assert client.post("/reset-password", json={"token": raw, "new_password": "newpass1"}).status_code == 200

    def test_reset_email_starts_with_the_warning(self, setup):
        client, db, _ = setup
        _make_user(db)
        mail = _Mail()
        with patch("routers.auth.send_email", side_effect=mail):
            client.post("/forgot-password", json={"username": "alice"})
        assert mail.calls[0]["body"].startswith("Never share this code or link with anyone.")

    def test_completed_reset_sends_password_changed_notice(self, setup):
        from models import PasswordResetToken
        client, db, auth_router = setup
        user = _make_user(db)
        db.add(PasswordResetToken(token=auth_router.hash_reset_token("tok-163"), user_id=user.id,
                                  expires_at=int(time.time()) + 3600))
        db.commit()
        mail = _Mail()
        with patch("routers.auth.send_email", side_effect=mail):
            assert client.post("/reset-password", json={"token": "tok-163", "new_password": "newpass1"}).status_code == 200
        assert [c["subject"] for c in mail.calls] == ["[Kana Cards] Your password was changed"]
        assert mail.calls[0]["to"] == "alice@example.com"

    def test_password_change_sends_notice(self, setup):
        client, db, _ = setup
        _make_user(db)
        assert client.post("/login", json={"username": "alice", "password": "secret123"}).status_code == 200
        mail = _Mail()
        with patch("routers.auth.send_email", side_effect=mail):
            resp = client.put("/profile/password", json={"current_password": "secret123", "new_password": "newpass1"})
        assert resp.status_code == 200, resp.text
        assert len(mail.calls) == 1 and "password was changed" in mail.calls[0]["subject"]

    def test_failed_notice_never_blocks_the_change(self, setup):
        from models import PasswordResetToken
        client, db, auth_router = setup
        user = _make_user(db)
        db.add(PasswordResetToken(token=auth_router.hash_reset_token("tok-x"), user_id=user.id,
                                  expires_at=int(time.time()) + 3600))
        db.commit()
        with patch("routers.auth.send_email", side_effect=RuntimeError("smtp down")):
            assert client.post("/reset-password", json={"token": "tok-x", "new_password": "newpass1"}).status_code == 200

    def test_lockout_is_per_ip(self, setup):
        _, _, auth_router = setup
        for _ in range(auth_router._LOGIN_LOCKOUT_THRESHOLD):
            auth_router._record_failed_login("victim", "10.0.0.1")
        assert auth_router._is_locked_out("victim", "10.0.0.1") is True
        assert auth_router._is_locked_out("victim", "10.0.0.2") is False

    def test_username_ceiling_applies_across_ips(self, setup):
        _, _, auth_router = setup
        for i in range(auth_router._LOGIN_LOCKOUT_USERNAME_THRESHOLD):
            auth_router._record_failed_login("victim", f"10.0.{i // 250}.{i % 250}")
        assert auth_router._is_locked_out("victim", "192.168.1.1") is True

    def test_failed_logins_from_one_ip_do_not_block_the_owner(self, setup):
        client, db, auth_router = setup
        _make_user(db)
        for _ in range(auth_router._LOGIN_LOCKOUT_THRESHOLD):
            auth_router._record_failed_login("alice", "203.0.113.9")
        # TestClient connects as "testclient", a different source.
        assert client.post("/login", json={"username": "alice", "password": "secret123"}).status_code == 200

    def test_completed_reset_clears_the_lockout(self, setup):
        from models import PasswordResetToken
        client, db, auth_router = setup
        user = _make_user(db)
        for _ in range(auth_router._LOGIN_LOCKOUT_THRESHOLD):
            auth_router._record_failed_login("alice", "testclient")
        assert auth_router._is_locked_out("alice", "testclient")
        db.add(PasswordResetToken(token=auth_router.hash_reset_token("tok-y"), user_id=user.id,
                                  expires_at=int(time.time()) + 3600))
        db.commit()
        with patch("routers.auth.send_email", side_effect=_Mail()):
            client.post("/reset-password", json={"token": "tok-y", "new_password": "newpass1"})
        assert not auth_router._is_locked_out("alice", "testclient")
