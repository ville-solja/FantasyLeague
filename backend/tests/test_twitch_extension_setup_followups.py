"""Tests for the Twitch extension setup follow-ups.

Plan: markdown/plans/plan-twitch-extension-setup-followups.md

Setting up the test extension surfaced silent failures. This plan makes them visible:
Twitch's error return (`?error=&state=`) shows a message on Profile; the demo clock is
requested only by admins; the admin Twitch status console checklist lists the OAuth
redirect URL and the image-domain allowlist; `GET /twitch/panel` is served from a short
in-memory cache with the panel rate limits; frontend `.html`/`.js`/`.css` responses carry
`Cache-Control: no-cache`.

Patterns to reuse (do not reinvent):
- Static JS checks: `_js_function` in tests/test_issue_157_twitch_extension_policy_compliance.py
  and `FRONTEND_DIR` file reads as in tests/test_issue_180_twitch_integration_status.py.
- `build_status` / admin status endpoint: tests/test_issue_180_twitch_integration_status.py
  (`_build_app(["routers.admin_twitch"], admin_override=True)`, `_add_user`).
- Twitch JWT env and panel app: `_signed`, `_viewer_claims`, `_SECRET_B64` in
  tests/test_issue_163_twitch_steam_account_hardening.py; rate-limit tests via
  `_twitch_app` + TestClient in tests/test_issue_171_twitch_panel_abuse_limits.py.
- Import helpers from other test modules by underscore name only, so pytest does not
  collect their tests twice (see markdown/lessons-learned.md).

Notes for the developer:
- When `/twitch/panel` gains `@limiter.limit(...)`, split it like `heartbeat` /
  `heartbeat_route` (lessons-learned 2026-10-07): unit tests call the plain function,
  rate-limit tests go through TestClient.
- The panel cache is process-local; reset it (`bust_panel_cache()`) between tests so
  test order does not matter.
- Any test client building the main app must clear `TWITCH_EXTENSION_CLIENT_ID` /
  `CORS_EXTRA_ORIGINS` before applying its own env.
- Keep `test_issue_85_split_admin_router.py`'s suite-size check in step.
"""
import json
import pathlib
import re
import time

import pytest
from fastapi.testclient import TestClient

import models  # noqa: F401  (registers every table before the db fixture's create_all)

from tests.test_issue_135_security_review_fixes import _add_user, _build_app
from tests.test_issue_136_security_audit_3 import _build_main_client
from tests.test_issue_157_twitch_extension_policy_compliance import (  # noqa: F401
    twitch_env, twitch_prod_env)
from tests.test_issue_157_twitch_extension_policy_compliance import (
    _js_function, _seed_series_match, _seed_world, _set_mvp, _shared_db, _signed, _twitch_app,
    _viewer)
from tests.test_issue_163_twitch_steam_account_hardening import _SECRET_B64, _engine, _session

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"

_REDIRECT_URI = "https://league.example/auth/twitch/callback"
_OAUTH_SECRET = "oauth-client-secret-value-xyz"
_OAUTH_KEYS = ("TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET", "TWITCH_OAUTH_REDIRECT_URI")


def _read(name):
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


def _error_handler():
    return _js_function(_read("app-profile.js"), "handleTwitchErrorReturn")


@pytest.fixture(autouse=True)
def _fresh_panel_cache(monkeypatch):
    """The panel cache is process-local: every test starts and ends with it empty."""
    import twitch
    monkeypatch.delenv("TWITCH_PANEL_CACHE_SECONDS", raising=False)
    twitch.bust_panel_cache()
    yield
    twitch.bust_panel_cache()


# ---------------------------------------------------------------------------
# Story 1 — See Why Twitch Sign-in Failed
# ---------------------------------------------------------------------------

class TestTwitchErrorReturn:
    def test_handle_twitch_error_return_logged_in_opens_profile_and_sets_twitch_status(self):
        """With ?error= and state= in the query, a logged-in player is taken to Profile and the Twitch section shows a message."""
        fn = _error_handler()
        assert "new URLSearchParams(window.location.search)" in fn
        assert 'q.has("error")' in fn and 'q.has("state")' in fn
        logged_out = fn.index("if (!activeUserId) return true;")
        assert logged_out < fn.index('switchTab("profile")') < fn.index('setStatus("twitchStatus"')

    def test_handle_twitch_error_return_maps_redirect_mismatch_access_denied_and_other_codes(self):
        """redirect_mismatch shows the 'redirect URL isn't registered' message, access_denied the existing 'cancelled' message, any other code the 'did not complete … Try again.' message followed by the code."""
        js = _read("app-profile.js")
        m = re.search(r"const _TWITCH_ERROR_MESSAGES = \{(.*?)\};", js, re.S)
        assert m, "_TWITCH_ERROR_MESSAGES not found"
        table = m.group(1)
        assert ("redirect_mismatch: \"Twitch sign-in failed: this site's Twitch redirect URL isn't "
                "registered with Twitch. Tell the league admins.\"") in table
        assert re.search(r"access_denied:\s*_TWITCH_RETURN_MESSAGES\.cancelled\[0\]", table)
        assert ('"Twitch sign-in was cancelled. Nothing was changed."' in js)
        fn = _error_handler()
        # Own keys only: "constructor" / "__proto__" pass the code check but must get the fallback.
        assert "Object.hasOwn(_TWITCH_ERROR_MESSAGES, code) && _TWITCH_ERROR_MESSAGES[code]) ||" in fn
        assert "`Twitch sign-in did not complete. Nothing was changed. Try again. (${code})`" in fn

    def test_handle_twitch_error_return_never_inserts_error_description_as_html(self):
        """error_description is never inserted as HTML; only the error code, matched against [a-z_]{1,64} (else 'unknown'), appears in the text."""
        fn = _error_handler()
        assert 'const code = /^[a-z_]{1,64}$/.test(raw) ? raw : "unknown";' in fn
        assert "innerHTML" not in fn and "insertAdjacentHTML" not in fn
        assert 'get("error_description")' not in fn
        # The message goes through setStatus, which writes textContent.
        set_status = _js_function(_read("app-globals.js"), "setStatus")
        assert "el.textContent =" in set_status and "innerHTML" not in set_status
        # raw is only ever tested, never shown.
        assert fn.count("raw") == 3

    def test_handle_twitch_error_return_strips_error_and_state_keeps_reset_token_handling(self):
        """error, error_description and state are removed from the address bar; other parameters such as reset_token keep their current handling."""
        fn = _error_handler()
        assert re.search(r'\["error", "error_description", "error_uri", "state"\]\.forEach\(k => q\.delete\(k\)\)', fn)
        assert ("history.replaceState(null, \"\", window.location.pathname + (rest ? `?${rest}` : \"\") "
                "+ window.location.hash);") in fn
        # Stripped before any return that follows a match, including the logged-out one.
        assert fn.index("history.replaceState") < fn.index("if (!activeUserId)")
        init = _js_function(_read("app-init.js"), "init")
        assert init.index("_handleResetTokenParam();") < init.index("handleTwitchErrorReturn()")
        reset = _js_function(_read("app-init.js"), "_handleResetTokenParam")
        assert 'params.get("reset_token")' in reset and "showResetPassword(token)" in reset

    def test_handle_twitch_error_return_logged_out_strips_params_without_login_prompt(self):
        """Logged out, the parameters are removed and the login prompt is not opened."""
        fn = _error_handler()
        assert "if (!activeUserId) return true;" in fn
        assert "showLogin" not in fn and "loginStatus" not in fn
        # Returning true keeps init() from handing the URL to handleTwitchReturn.
        init = _js_function(_read("app-init.js"), "init")
        assert "if (!handleSteamReturn() && !handleTwitchErrorReturn()) handleTwitchReturn();" in init

    def test_handle_twitch_error_return_ignores_error_without_state(self):
        """Failure path: ?error= without state= is not treated as a Twitch error return (handler returns false, nothing is stripped)."""
        fn = _error_handler()
        guard = 'if (!q.has("error") || !q.has("state")) return false;'
        assert guard in fn
        assert fn.index(guard) < fn.index("history.replaceState")
        assert fn.index(guard) < fn.index("q.delete")

    def test_init_calls_twitch_error_return_next_to_steam_and_twitch_returns(self):
        """init() in app-init.js calls handleTwitchErrorReturn() alongside handleSteamReturn() / handleTwitchReturn()."""
        init = _js_function(_read("app-init.js"), "init")
        line = "if (!handleSteamReturn() && !handleTwitchErrorReturn()) handleTwitchReturn();"
        assert init.count("handleTwitchErrorReturn()") == 1 and line in init
        # After the user is known, so the handler can tell logged in from logged out.
        assert init.index("await loadMe();") < init.index(line)


# ---------------------------------------------------------------------------
# Story 2 — Demo Clock Only for Admins
# ---------------------------------------------------------------------------

class TestDemoClockAdminOnly:
    def test_load_demo_clock_requested_only_when_demo_mode_and_active_is_admin(self):
        """With demo mode on, GET /admin/demo/clock is requested only when the logged-in user is an admin (gated on activeIsAdmin)."""
        fn = _js_function(_read("app-admin-demo.js"), "loadDemoClock")
        guard = "if (!window.demoMode || !activeIsAdmin) return;"
        assert guard in fn
        assert fn.index(guard) < fn.index("/admin/demo/clock")

    def test_render_demo_mode_panel_renders_and_loads_clock_for_admin(self):
        """The Demo Mode panel still renders in the admin tab for admins and loads the clock there."""
        fn = _js_function(_read("app-admin-demo.js"), "renderDemoModePanel")
        guard = "if (!window.demoMode || !activeIsAdmin) {"
        assert guard in fn
        empty = fn.index('container.innerHTML = "";')
        assert fn.index(guard) < empty < fn.index('id="demoModePanel"') < fn.index("loadDemoClock();")
        # Called on every sign-in state change, after loadMe() has set activeIsAdmin.
        auth = _js_function(_read("app-auth.js"), "applyAuthState")
        assert 'if (typeof renderDemoModePanel === "function") renderDemoModePanel();' in auth
        init = _js_function(_read("app-init.js"), "init")
        assert init.index("await loadMe();") < init.index("applyAuthState();")
        assert 'id="demoModePanelContainer"' in _read("index.html")

    def test_load_config_makes_no_admin_demo_request_for_non_admin_or_logged_out(self):
        """Failure path: for non-admins and logged-out visitors no /admin/demo/* request is made on page load (renderDemoModePanel no longer called from loadConfig for everyone)."""
        cfg = _js_function(_read("app-globals.js"), "loadConfig")
        assert "renderDemoModePanel" not in cfg and "loadDemoClock" not in cfg
        assert "/admin/demo" not in cfg
        assert "window.demoMode = cfg.demo_mode === true;" in cfg
        # The only page-load path to a demo request is renderDemoModePanel → loadDemoClock,
        # and both are gated on activeIsAdmin.
        js = _read("app-admin-demo.js")
        for name in ("renderDemoModePanel", "loadDemoClock"):
            assert "!activeIsAdmin" in _js_function(js, name)
        callers = [f for f in sorted(FRONTEND_DIR.glob("*.js"))
                   if "renderDemoModePanel();" in f.read_text(encoding="utf-8")]
        assert [f.name for f in callers] == ["app-auth.js"]


# ---------------------------------------------------------------------------
# Story 3 — Twitch Console Checklist Covers Sign-in and Images
# ---------------------------------------------------------------------------

def _status():
    import twitch_status
    session = _session(_engine())
    try:
        return twitch_status.build_status(session)
    finally:
        session.close()


def _console_entry(status, needle):
    found = [c for c in status["console"] if needle in c["label"]]
    return found[0] if found else None


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("TWITCH_OAUTH_CLIENT_ID", "cid123")
    monkeypatch.setenv("TWITCH_OAUTH_CLIENT_SECRET", _OAUTH_SECRET)
    monkeypatch.setenv("TWITCH_OAUTH_REDIRECT_URI", _REDIRECT_URI)
    monkeypatch.setenv("TWITCH_EXTENSION_SECRET", _SECRET_B64)
    monkeypatch.setenv("APP_BASE_URL", "https://league.example/")
    monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)


class TestTwitchStatusConsoleChecklist:
    def test_build_status_console_includes_oauth_redirect_url_when_connect_twitch_configured(self, oauth_env):
        """console adds the 'OAuth Redirect URL has this exact entry (click Add, then Save Changes)' entry with TWITCH_OAUTH_REDIRECT_URI as expected when all TWITCH_OAUTH_* are set."""
        entry = _console_entry(_status(), "OAuth Redirect URL")
        assert entry == {
            "label": ("Extension Settings › Twitch API Client Configuration › OAuth Redirect URL has "
                      "this exact entry (click Add, then Save Changes)"),
            "expected": _REDIRECT_URI,
        }

    @pytest.mark.parametrize("missing", _OAUTH_KEYS)
    def test_build_status_console_omits_oauth_redirect_url_when_connect_twitch_unconfigured(
            self, oauth_env, monkeypatch, missing):
        """Failure path: with any TWITCH_OAUTH_* value missing, the OAuth Redirect URL console entry is not shown."""
        monkeypatch.delenv(missing)
        status = _status()
        assert _console_entry(status, "OAuth Redirect URL") is None
        assert _console_entry(status, "Image Domains") is not None

    def test_build_status_console_includes_image_domain_allowlist_with_https_logo_hosts(self, oauth_env, monkeypatch):
        """console adds 'Version › Capabilities › Allowlist for Image Domains contains the team logo hosts' with the https:// origins of logo_hosts() as expected."""
        import logo_hosts
        entry = _console_entry(_status(), "Image Domains")
        assert entry["label"] == "Version › Capabilities › Allowlist for Image Domains contains the team logo hosts"
        expected = entry["expected"].split(", ")
        assert sorted(expected) == sorted(f"https://{h}" for h in logo_hosts.DEFAULT_LOGO_HOSTS)
        monkeypatch.setenv("LOGO_HOST_ALLOWLIST", "img.example.com, CDN.Example.org")
        entry = _console_entry(_status(), "Image Domains")
        assert entry["expected"] == "https://cdn.example.org, https://img.example.com"

    def test_build_status_connect_twitch_detail_names_twitch_api_client_secret(self, oauth_env, monkeypatch):
        """The connect_twitch check's detail names the Twitch API Client Secret of the client whose ID is TWITCH_OAUTH_CLIENT_ID, never the Extension Secret."""
        row = [c for c in _status()["checks"] if c["key"] == "connect_twitch"][0]
        assert row["state"] == "ok"
        assert "Twitch API Client Secret" in row["detail"]
        assert "whose Client ID is TWITCH_OAUTH_CLIENT_ID" in row["detail"]
        assert "never the Extension Secret" in row["detail"]
        monkeypatch.delenv("TWITCH_OAUTH_CLIENT_SECRET")
        row = [c for c in _status()["checks"] if c["key"] == "connect_twitch"][0]
        assert row["state"] == "warning"
        assert "Twitch API Client Secret" in row["detail"] and "never the Extension Secret" in row["detail"]

    def test_build_status_adds_no_secret_token_or_secret_length(self, oauth_env):
        """No secret, token or secret length appears anywhere in the status response."""
        status = _status()
        body = json.dumps(status)
        for leaked in (_OAUTH_SECRET, _SECRET_B64, _SECRET_B64.rstrip("=")):
            assert leaked not in body
        texts = json.dumps([status["checks"], status["console"]])
        for length in (len(_OAUTH_SECRET), len(_SECRET_B64)):
            assert not re.search(rf"\b{length}\b", texts)

    def test_admin_twitch_status_non_admin_gets_403(self, db, oauth_env):
        """Failure path: GET /admin/twitch/status with the new console entries still answers 403 to a non-admin."""
        app, Session = _build_app(["routers.admin_twitch"])
        _add_user(Session, user_id=2, username="bob", email="bob@example.com")
        client = TestClient(app)
        assert client.get("/admin/twitch/status").status_code in (401, 403)
        assert client.post("/_test/login/2").status_code == 200
        resp = client.get("/admin/twitch/status")
        assert resp.status_code == 403
        assert _REDIRECT_URI not in resp.text


# ---------------------------------------------------------------------------
# Story 4 — Panel Live Data Under Audience Load
# ---------------------------------------------------------------------------

def _count_panel_work(monkeypatch):
    """Wrap twitch.panel_live (the uncached query work) and count its calls."""
    import twitch
    calls = []
    real = twitch.panel_live

    def counted(payload, db):
        calls.append(1)
        return real(payload=payload, db=db)

    monkeypatch.setattr(twitch, "panel_live", counted)
    return calls


class TestTwitchPanelCache:
    def test_panel_live_second_call_within_window_serves_cached_body(self, db, monkeypatch):
        """GET /twitch/panel returns a cached body shared by all viewers for up to TWITCH_PANEL_CACHE_SECONDS; a second call in the window does no query work."""
        import twitch
        _seed_world(db)
        calls = _count_panel_work(monkeypatch)
        first = twitch.cached_panel_live(_viewer("Uone"), db)
        second = twitch.cached_panel_live(_viewer("Utwo"), db)
        assert calls == [1]
        assert second == first
        # Past the window the body is computed again.
        monkeypatch.setenv("TWITCH_PANEL_CACHE_SECONDS", "0.05")
        time.sleep(0.1)
        twitch.cached_panel_live(_viewer("Uone"), db)
        assert calls == [1, 1]

    def test_panel_live_cache_seconds_zero_disables_cache(self, db, monkeypatch):
        """TWITCH_PANEL_CACHE_SECONDS=0 turns the cache off: every call queries."""
        import twitch
        monkeypatch.setenv("TWITCH_PANEL_CACHE_SECONDS", "0")
        assert twitch.panel_cache_seconds() == 0
        calls = _count_panel_work(monkeypatch)
        for _ in range(3):
            twitch.cached_panel_live(_viewer(), db)
        assert calls == [1, 1, 1]

    @pytest.mark.parametrize("raw", ["abc", "-5", "inf", "nan", "", "  "])
    def test_panel_live_cache_seconds_invalid_falls_back_to_30(self, db, monkeypatch, raw):
        """Failure path: an invalid TWITCH_PANEL_CACHE_SECONDS value falls back to the 30-second default."""
        import twitch
        monkeypatch.setenv("TWITCH_PANEL_CACHE_SECONDS", raw)
        assert twitch.panel_cache_seconds() == 30
        calls = _count_panel_work(monkeypatch)
        twitch.cached_panel_live(_viewer(), db)
        twitch.cached_panel_live(_viewer(), db)
        assert calls == [1]
        monkeypatch.setenv("TWITCH_PANEL_CACHE_SECONDS", "12.5")
        assert twitch.panel_cache_seconds() == 12.5

    def test_bust_panel_cache_forces_refresh(self, db, monkeypatch):
        """bust_panel_cache() clears the cache, so the next call recomputes the body."""
        import twitch
        calls = _count_panel_work(monkeypatch)
        empty = twitch.cached_panel_live(_viewer(), db)
        assert empty["top_performers"] == []
        _seed_world(db)
        assert twitch.cached_panel_live(_viewer(), db) == empty  # still cached
        twitch.bust_panel_cache()
        fresh = twitch.cached_panel_live(_viewer(), db)
        assert calls == [1, 1]
        assert [p["player_id"] for p in fresh["top_performers"]] == [203, 202, 201]

    def test_ingest_busts_panel_cache_when_new_matches_stored(self, db, monkeypatch):
        """The cache is cleared when ingest stores new matches (where schedule.bust_cache() is called)."""
        import ingest
        import twitch
        twitch.cached_panel_live(_viewer(), db)
        assert twitch._panel_cache["body"] is not None
        payload = {"duration": 2000, "version": 21, "start_time": int(time.time()) - 3600,
                   "radiant_team_id": None, "dire_team_id": None, "radiant_win": True,
                   "players": [], "picks_bans": []}
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, label=None: payload)
        ingest.ingest_match(db, 9100000001, 1, set(), set(), {})
        assert twitch._panel_cache["body"] is None
        # A skipped (unavailable) match stores nothing and leaves the cache alone.
        twitch.cached_panel_live(_viewer(), db)
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, label=None: None)
        ingest.ingest_match(db, 9100000002, 1, set(), set(), {})
        assert twitch._panel_cache["body"] is not None

    def test_set_mvp_busts_panel_cache(self, db, twitch_env):
        """The cache is cleared when an MVP is confirmed, so the new MVP appears on the next poll."""
        import twitch
        _seed_series_match(db)
        twitch.cached_panel_live(_viewer(), db)
        assert twitch._panel_cache["body"] is not None
        _set_mvp(db)
        assert twitch._panel_cache["body"] is None

    def _limited_client(self):
        import twitch
        db = _shared_db()
        was_enabled = twitch.limiter.enabled
        twitch.limiter.enabled = True
        twitch.limiter.reset()
        return db, was_enabled, TestClient(_twitch_app(db))

    def _restore(self, db, was_enabled):
        import twitch
        twitch.limiter.reset()
        twitch.limiter.enabled = was_enabled
        db.close()

    def test_twitch_panel_route_rate_limited_per_viewer_returns_429(self, twitch_prod_env):
        """Failure path: past RATE_LIMIT_TWITCH_ACTION keyed by key_by_twitch_viewer_or_ip, GET /twitch/panel answers 429."""
        from limits import parse
        import twitch
        db, was_enabled, client = self._limited_client()
        try:
            per_viewer = parse(twitch.RATE_LIMIT_TWITCH_ACTION).amount
            assert per_viewer < parse(twitch.RATE_LIMIT_TWITCH_JOIN_IP).amount
            statuses = [client.get("/twitch/panel", headers={"Authorization": _signed("Uone")}).status_code
                        for _ in range(per_viewer + 1)]
            assert statuses[:per_viewer] == [200] * per_viewer
            assert statuses[-1] == 429
            assert client.get("/twitch/panel", headers={"Authorization": _signed("Utwo")}).status_code == 200
        finally:
            self._restore(db, was_enabled)

    def test_twitch_panel_route_rate_limited_per_ip_returns_429(self, twitch_prod_env):
        """Failure path: past RATE_LIMIT_TWITCH_JOIN_IP per IP, GET /twitch/panel answers 429."""
        from limits import parse
        import twitch
        db, was_enabled, client = self._limited_client()
        try:
            per_ip = parse(twitch.RATE_LIMIT_TWITCH_JOIN_IP).amount
            per_viewer = parse(twitch.RATE_LIMIT_TWITCH_ACTION).amount
            statuses = []
            for i in range(per_ip + 1):
                opaque = f"Uviewer{i // per_viewer}"   # stay under each viewer's own limit
                statuses.append(client.get("/twitch/panel",
                                           headers={"Authorization": _signed(opaque)}).status_code)
            assert statuses[:per_ip] == [200] * per_ip
            assert statuses[-1] == 429
        finally:
            self._restore(db, was_enabled)

    def test_twitch_panel_response_body_unchanged(self, db, twitch_prod_env, monkeypatch):
        """The response body (keys and values) is unchanged by the cache."""
        import twitch
        from tests.test_issue_157_twitch_extension_policy_compliance import _UPCOMING_WEEKS, _schedule_with
        _schedule_with(monkeypatch, _UPCOMING_WEEKS)
        shared = _shared_db()
        try:
            _seed_world(shared)
            expected = twitch.panel_live(payload=_viewer(), db=shared)
            assert set(expected) == {"top_performers", "next_match"}
            client = TestClient(_twitch_app(shared))
            for opaque in ("Uone", "Aanon"):
                resp = client.get("/twitch/panel", headers={"Authorization": _signed(opaque)})
                assert resp.status_code == 200
                assert resp.json() == json.loads(json.dumps(expected))
        finally:
            shared.close()


# ---------------------------------------------------------------------------
# Story 5 — Fresh Scripts After a Deploy
# ---------------------------------------------------------------------------

@pytest.fixture
def main_client(monkeypatch):
    return _build_main_client(monkeypatch)


class TestFrontendCacheControl:
    def test_frontend_root_html_has_cache_control_no_cache(self, main_client):
        """GET / (index.html) carries Cache-Control: no-cache."""
        for path in ("/", "/index.html", "/privacy.html"):
            resp = main_client.get(path)
            assert resp.status_code == 200, path
            assert resp.headers.get("cache-control") == "no-cache", path

    def test_frontend_js_and_css_have_cache_control_no_cache(self, main_client):
        """GET /app-auth.js and /style.css carry Cache-Control: no-cache."""
        for path in ("/app-auth.js", "/app-profile.js", "/style.css"):
            resp = main_client.get(path)
            assert resp.status_code == 200, path
            assert resp.headers.get("cache-control") == "no-cache", path
            assert resp.headers.get("etag"), path

    def test_frontend_js_revalidation_with_etag_returns_304(self, main_client):
        """A second request with If-None-Match set to the existing ETag answers 304."""
        first = main_client.get("/app-auth.js")
        etag = first.headers["etag"]
        again = main_client.get("/app-auth.js", headers={"If-None-Match": etag})
        assert again.status_code == 304
        assert again.headers.get("cache-control") == "no-cache"

    def test_frontend_image_has_no_no_cache_header(self, main_client):
        """Failure path: images, fonts and /assets/* keep their current caching (no Cache-Control: no-cache added)."""
        font = main_client.get("/fonts/BigShouldersText-VariableFont_wght.ttf")
        assert font.status_code == 200
        assert "no-cache" not in font.headers.get("cache-control", "")
        from image import _ASSETS_DIR
        assets = sorted(pathlib.Path(_ASSETS_DIR).glob("*.png"))
        if assets:
            img = main_client.get(f"/assets/{assets[0].name}")
            assert img.status_code == 200
            assert "no-cache" not in img.headers.get("cache-control", "")

    def test_twitch_ext_dev_harness_unaffected(self, main_client):
        """/twitch-ext/* (local dev harness) responses are unaffected by the no-cache rule."""
        for path in ("/twitch-ext/panel.js", "/twitch-ext/panel.html"):
            resp = main_client.get(path)
            assert resp.status_code == 200, path
            assert "no-cache" not in resp.headers.get("cache-control", ""), path
