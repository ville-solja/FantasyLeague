"""Tests for issue #180: Twitch integration status.

Plan: markdown/plans/plan-issue-180-twitch-integration-status.md

Every failure between the Twitch iframe and the backend gets a reason code
(E-ORIGIN, E-CONFIG, E-REACH, E-TOKEN, E-SERVER); the broadcaster's configuration
page runs a step-by-step Connection check against GET /twitch/ping and
GET /twitch/check; admins get GET /admin/twitch/status (built by the new
`twitch_status` module from env, the approvals table and in-memory traffic
counters); package.sh stamps EXT_BUILD = {version, origins} into ebs-origins.js.

Patterns to reuse (do not reinvent):
- Twitch JWT payloads and env: `twitch_env`, `_signed`, `_viewer_claims`, `_SECRET_B64`,
  `_SECRET_BYTES`, `_engine` / `_session` in tests/test_issue_163_twitch_steam_account_hardening.py.
- Admin endpoints over HTTP: `_build_app(["routers.admin_twitch"], admin_override=True)` and
  `_add_user` in tests/test_issue_135_security_review_fixes.py; the `env` fixture and
  `_admin_client` in tests/test_issue_175_approved_streamers_admin.py. The status route
  needs `require_admin` only (no reauth), so a non-admin client must get 403.
- Import helpers from other test modules by underscore name only, so pytest does not
  collect their tests twice (see markdown/lessons-learned.md).
- Static file checks: `_read(REPO_ROOT / "twitch-extension" / ...)`.

Notes for the developer:
- Traffic counters are process-local; reset them between tests (expose a reset helper
  in `twitch` / `twitch_status`, or monkeypatch the counter object) so test order does
  not matter.
- `verify_twitch_jwt` is called directly by many existing tests; recording counters
  there must not change its signature or its exceptions.
- If `/twitch/ping` gets a slowapi limit, split it like `heartbeat` / `heartbeat_route`
  (see lessons-learned 2026-10-07 developer/testing) or test it via TestClient only.
- Refused-origin middleware: any test client that builds the main app must clear
  `TWITCH_EXTENSION_CLIENT_ID` / `CORS_EXTRA_ORIGINS` before applying its own env.
"""
import base64
import json
import pathlib
import re
import shutil
import subprocess
import time
import zipfile

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from tests.test_issue_135_security_review_fixes import _add_user, _build_app
from tests.test_issue_157_twitch_extension_policy_compliance import _js_function
from tests.test_issue_163_twitch_steam_account_hardening import (
    _SECRET_B64, _SECRET_BYTES, _engine, _session, _signed, _viewer_claims)


def _urls(text: str) -> list[str]:
    """Every http(s) URL in text, without trailing punctuation, for exact comparison."""
    return [u.rstrip(".,;)") for u in re.findall(r"https?://[^\s\"']+", text)]


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXT_DIR = REPO_ROOT / "twitch-extension"
FRONTEND_DIR = REPO_ROOT / "frontend"
_ADMIN = {"user_id": 1, "username": "admin"}
_CODES = ("E-ORIGIN", "E-CONFIG", "E-REACH", "E-TOKEN", "E-SERVER")
_CLIENT_ID = "abc123clientid"
_APPROVAL_CH = "4242"


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _fresh_traffic():
    """Traffic counters are process-local: start and end every test with them empty."""
    import twitch
    twitch.reset_traffic()
    yield
    twitch.reset_traffic()


@pytest.fixture
def jwt_env(monkeypatch):
    """The real JWT path with a known secret (no TWITCH_LOCAL_DEV bypass)."""
    monkeypatch.delenv("TWITCH_LOCAL_DEV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    monkeypatch.setenv("TWITCH_EXTENSION_SECRET", _SECRET_B64)


@pytest.fixture
def status_env(monkeypatch):
    """A fully configured server: every status row ok."""
    import steam_live
    monkeypatch.setenv("TWITCH_EXTENSION_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("TWITCH_EXTENSION_SECRET", _SECRET_B64)
    monkeypatch.setenv("TWITCH_EXTENSION_VERSION", "1.2.1")
    monkeypatch.delenv("TWITCH_LOCAL_DEV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "111")
    monkeypatch.setenv("TWITCH_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TWITCH_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("TWITCH_OAUTH_REDIRECT_URI", "https://league.example/auth/twitch/callback")
    monkeypatch.setenv("APP_BASE_URL", "https://league.example/")
    monkeypatch.setattr(steam_live, "STEAM_API_KEY", "steam-key")


def _status(db=None):
    import twitch_status
    if db is not None:
        return twitch_status.build_status(db)
    session = _session(_engine())
    try:
        return twitch_status.build_status(session)
    finally:
        session.close()


def _row(status, key):
    rows = [c for c in status["checks"] if c["key"] == key]
    assert len(rows) == 1, (key, status["checks"])
    return rows[0]


def _admin_client():
    app, Session = _build_app(["routers.admin_twitch"], admin_override=True)
    return TestClient(app), Session


def _claims(role="broadcaster", channel=_APPROVAL_CH, opaque_id="Ubroadcaster"):
    return {"opaque_user_id": opaque_id, "role": role, "channel_id": channel,
            "exp": int(time.time()) + 300}


def _node_available():
    return shutil.which("node") is not None


def _run_node(script, tmp_path):
    """Run a JS harness under Node and return its JSON output (None without Node)."""
    if not _node_available():
        return None
    path = tmp_path / "harness.js"
    path.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# extension.js under Node with a stubbed Twitch helper, fetch and console.
_EXT_HARNESS = r"""
var warns = [];
console.warn = function () { warns.push(Array.prototype.join.call(arguments, " ")); };
var timeouts = 0;
function onConfigTimeout() { timeouts++; }
var timers = [];
setTimeout = function (f) { timers.push(f); };
var window = { Twitch: { ext: {
    configuration: { onChanged: function () {}, global: %(global)s },
    onAuthorized: function () {}, listen: function () {} } } };
var document = { getElementById: function () { return null; } };
var nextFetch = null;
function fetch() { return nextFetch(); }
function resp(status, body) { return function () { return Promise.resolve({ ok: status >= 200 && status < 300,
    status: status, text: function () { return Promise.resolve(JSON.stringify(body || {})); } }); }; }
var EBS_ALLOWED_ORIGINS = ["https://league.example"];
%(src)s
(async function () { var out = {}; %(steps)s console.log(JSON.stringify(out)); })()
    .catch(function (e) { console.error(e && e.stack || e); process.exit(1); });
"""


def _run_extension(tmp_path, steps, global_cfg="null"):
    return _run_node(_EXT_HARNESS % {"global": global_cfg, "src": _read(EXT_DIR / "extension.js"),
                                     "steps": steps}, tmp_path)


# extension.js + config.js under Node with a fake DOM (connection check).
_CONFIG_HARNESS = r"""
function mk(tag) {
    return { tag: tag, children: [], textContent: "", hidden: false, className: "", listeners: {},
        get firstChild() { return this.children[0] || null; },
        removeChild: function (c) { this.children.splice(this.children.indexOf(c), 1); },
        appendChild: function (c) { this.children.push(c); return c; },
        addEventListener: function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); } };
}
var els = {};
var document = { getElementById: function (id) { return els[id] || (els[id] = mk(id)); },
                 createElement: function (t) { return mk(t); } };
var window = { Twitch: { ext: { configuration: { onChanged: function () {}, global: null },
                                onAuthorized: function () {}, listen: function () {} } } };
setTimeout = function () {};
console.warn = function () {};
var fetchCalls = [];
var pingResult = null, checkResult = null;
function fetch(url, opts) {
    fetchCalls.push({ url: url, auth: !!(opts && opts.headers && opts.headers.Authorization) });
    return (url.indexOf("/twitch/ping") !== -1 ? pingResult : checkResult)();
}
function resp(status, body) { return function () { return Promise.resolve({ ok: status >= 200 && status < 300,
    status: status, text: function () { return Promise.resolve(JSON.stringify(body || {})); } }); }; }
function refused() { return Promise.reject(new TypeError("Failed to fetch")); }
var EBS_ALLOWED_ORIGINS = ["https://league.example"];
%(build)s
%(ext)s
%(config)s
function rows() { return els["conn-check"].children.map(function (li) {
    return { state: li.children[0].textContent, label: li.children[1].textContent, detail: li.children[2].textContent }; }); }
function good() { ext.configuredUrl = "https://league.example"; ext.ebsUrl = "https://league.example"; ext.token = "tok"; }
(async function () { var out = {}; %(steps)s console.log(JSON.stringify(out)); })()
    .catch(function (e) { console.error(e && e.stack || e); process.exit(1); });
"""

_BUILD = 'var EXT_BUILD = {version: "1.3.0", origins: ["https://league.example"]};'


def _run_config(tmp_path, steps, build=_BUILD):
    return _run_node(_CONFIG_HARNESS % {"build": build, "ext": _read(EXT_DIR / "extension.js"),
                                        "config": _read(EXT_DIR / "config.js"), "steps": steps}, tmp_path)


def _states(rows):
    return [(r["label"], r["state"]) for r in rows]


def _refused_origin_app():
    """A bare app behind RefusedOriginMiddleware with a CORS-like allow list."""
    import twitch_status
    app = FastAPI()

    @app.get("/twitch/ping")
    def _ping():
        return {"ok": True}

    @app.get("/other")
    def _other():
        return {"ok": True}

    app.add_middleware(twitch_status.RefusedOriginMiddleware,
                       allow_origins=["http://localhost:8080"],
                       allow_origin_regex=rf"^https://{re.escape(_CLIENT_ID)}\.ext-twitch\.tv$")
    return app


# ---------------------------------------------------------------------------
# Story 1 — See Why the Panel Is Not Available
# ---------------------------------------------------------------------------

class TestPanelReasonCodes:
    def test_extension_js_defines_all_five_reason_codes(self, tmp_path):
        """extension.js defines E-ORIGIN, E-CONFIG, E-REACH, E-TOKEN and E-SERVER."""
        src = _read(EXT_DIR / "extension.js")
        block = src[src.index("var EXT_REASON"):src.index("};", src.index("var EXT_REASON"))]
        for code in _CODES:
            assert f'"{code}"' in block, code
        out = _run_extension(tmp_path, "out.codes = Object.keys(EXT_REASON).map(function (k) { return EXT_REASON[k]; });")
        if out is not None:
            assert sorted(out["codes"]) == sorted(_CODES)

    def test_extension_js_refused_origin_sets_e_origin_and_calls_on_config_timeout_at_once(self, tmp_path):
        """When the configured ebs_url is refused, _onCfgChanged sets ext.failReason = "E-ORIGIN" and calls onConfigTimeout() immediately."""
        src = _read(EXT_DIR / "extension.js")
        handler = _js_function(src, "_onCfgChanged")
        refused = handler[handler.index("!_ebsUrlAllowed(cfg.ebs_url)"):handler.index("return;")]
        assert "setFailReason(EXT_REASON.ORIGIN)" in refused
        assert "_configTimeout()" in refused
        assert "onConfigTimeout()" in _js_function(src, "_configTimeout")
        out = _run_extension(tmp_path, """
            _onCfgChanged();
            out.reason = ext.failReason; out.timeouts = timeouts; out.ebsUrl = ext.ebsUrl;
            timers.forEach(function (f) { f(); });
            out.timeoutsAfterTimer = timeouts; out.reasonAfterTimer = ext.failReason;
        """, global_cfg='{content: JSON.stringify({ebs_url: "https://other.example/api"})}')
        if out is not None:
            assert out == {"reason": "E-ORIGIN", "timeouts": 1, "ebsUrl": None,
                           "timeoutsAfterTimer": 1, "reasonAfterTimer": "E-ORIGIN"}

    def test_extension_js_config_timeout_sets_e_config(self, tmp_path):
        """The 8-second timeout without configuration sets failReason E-CONFIG."""
        init_src = _js_function(_read(EXT_DIR / "extension.js"), "init")
        assert "setFailReason(EXT_REASON.CONFIG)" in init_src and "8000" in init_src
        out = _run_extension(tmp_path, """
            init();
            out.before = ext.failReason;
            timers.forEach(function (f) { f(); });
            out.reason = ext.failReason; out.timeouts = timeouts;
        """)
        if out is not None:
            assert out == {"before": None, "reason": "E-CONFIG", "timeouts": 1}

    def test_extension_js_response_handling_sets_token_server_and_reach_codes(self, tmp_path):
        """401 sets E-TOKEN, 5xx sets E-SERVER, and a rejected fetch sets E-REACH."""
        src = _read(EXT_DIR / "extension.js")
        parse = _js_function(src, "_parseResponse")
        assert "EXT_REASON.TOKEN" in parse and "EXT_REASON.SERVER" in parse
        assert "EXT_REASON.REACH" in _js_function(src, "_unreachable")
        for helper in ("ebsGet", "ebsPost"):
            assert ".then(_parseResponse, _unreachable)" in _js_function(src, helper), helper
        out = _run_extension(tmp_path, """
            ext.ebsUrl = "https://league.example"; ext.token = "t";
            nextFetch = resp(401); var d401 = await ebsGet("/twitch/panel"); out.r401 = [ext.failReason, d401._status];
            nextFetch = resp(503); await ebsPost("/twitch/join"); out.r503 = ext.failReason;
            nextFetch = function () { return Promise.reject(new TypeError("Failed to fetch")); };
            try { await ebsGet("/twitch/panel"); out.rejected = false; } catch (e) { out.rejected = true; }
            out.reach = ext.failReason;
            ext.failReason = null; nextFetch = resp(200, {ok: true}); await ebsGet("/twitch/panel");
            out.okLeavesNone = ext.failReason;
        """)
        if out is not None:
            assert out == {"r401": ["E-TOKEN", 401], "r503": "E-SERVER", "rejected": True,
                           "reach": "E-REACH", "okLeavesNone": None}

    def test_panel_and_live_config_append_reason_code_to_not_available_message(self, tmp_path):
        """panel.js and live_config.js append " (code: {failReason})" to the not-available message when set."""
        panel = _read(EXT_DIR / "panel.js")
        assert "failReasonSuffix()" in _js_function(panel, "_unavailableNote")
        for fn in ("onConfigTimeout", "renderMvpsUnavailable", "renderPanelUnavailable"):
            assert "_unavailableNote(" in _js_function(panel, fn), fn
        live = _read(EXT_DIR / "live_config.js")
        assert "failReasonSuffix()" in _js_function(live, "onConfigTimeout")
        assert live.count("failReasonSuffix()") >= 3  # timeout, both load failures, confirm failure
        assert 'id="mvp-unavailable"' in _read(EXT_DIR / "live_config.html")
        out = _run_extension(tmp_path, """
            out.none = failReasonSuffix();
            ext.failReason = EXT_REASON.TOKEN; out.set = failReasonSuffix();
        """)
        if out is not None:
            assert out == {"none": "", "set": " (code: E-TOKEN)"}

    def test_extension_console_warning_logs_code_and_origin_never_token(self, tmp_path):
        """console.warn logs "[ext] " + code with the configured origin only, never the token."""
        fn = _js_function(_read(EXT_DIR / "extension.js"), "setFailReason")
        assert 'console.warn("[ext] " + code' in fn
        assert "ext.token" not in fn
        out = _run_extension(tmp_path, """
            ext.configuredUrl = "https://league.example/api/v1"; ext.ebsUrl = ext.configuredUrl;
            ext.token = "secret-jwt-token-value";
            nextFetch = resp(401); await ebsGet("/twitch/panel");
            out.warns = warns;
        """)
        if out is not None:
            coded = [w for w in out["warns"] if w.startswith("[ext] E-TOKEN")]
            assert coded and coded[0].split("backend origin: ", 1)[1] == "https://league.example"
            assert "/api/v1" not in coded[0]
            assert not any("secret-jwt-token-value" in w for w in out["warns"])

    def test_panel_and_live_config_viewer_message_has_no_url_id_or_setting_name(self):
        """Failure path: viewer-facing messages show only the generic text and code (no URL, id or env/setting name)."""
        panel = _read(EXT_DIR / "panel.js")
        live = _read(EXT_DIR / "live_config.js")
        bodies = [_js_function(panel, n) for n in
                  ("_unavailableNote", "onConfigTimeout", "renderMvpsUnavailable", "renderPanelUnavailable")]
        bodies += [_js_function(live, "onConfigTimeout"),
                   _js_function(_read(EXT_DIR / "extension.js"), "failReasonSuffix")]
        forbidden = ("http", "ebsUrl", "configuredUrl", "ebs_url", "TWITCH_", "channelId", "userId",
                     "ext.token", "EBS_ALLOWED_ORIGINS", "EXT_BUILD")
        for body in bodies:
            for word in forbidden:
                assert word not in body, (word, body[:60])


# ---------------------------------------------------------------------------
# Story 2 — Connection Check for the Broadcaster
# ---------------------------------------------------------------------------

class TestTwitchPingAndCheck:
    def test_twitch_ping_needs_no_token_and_returns_ok(self, monkeypatch):
        """GET /twitch/ping answers {"ok": true} without an Authorization header and without a database."""
        import twitch
        assert twitch.ping() == {"ok": True}
        app = FastAPI()
        app.state.limiter = twitch.limiter
        app.include_router(twitch.router)  # no get_db override: ping must not touch the database
        resp = TestClient(app).get("/twitch/ping")
        assert resp.status_code == 200 and resp.json() == {"ok": True}
        from tests.test_issue_163_twitch_steam_account_hardening import _route
        route = _route(twitch.router, "/twitch/ping", "GET")
        assert not route.dependant.dependencies  # no token, no database

    def test_twitch_check_good_broadcaster_token_returns_role_and_approval(self, db, jwt_env, monkeypatch):
        """GET /twitch/check with a valid broadcaster token returns ok, role, mvp_allowed and approval."""
        import twitch
        from models import TwitchChannelApproval
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "111")
        payload = twitch.verify_twitch_jwt(None, _signed(_claims()))
        assert twitch.check(payload, db) == {"ok": True, "role": "broadcaster",
                                             "mvp_allowed": False, "approval": "pending"}
        db.add(TwitchChannelApproval(channel_id=_APPROVAL_CH, status="approved",
                                     first_seen_at=1, last_seen_at=1))
        db.commit()
        assert twitch.check(payload, db) == {"ok": True, "role": "broadcaster",
                                             "mvp_allowed": True, "approval": "approved"}

    def test_twitch_check_viewer_token_returns_no_approval(self, db, jwt_env):
        """GET /twitch/check returns approval / mvp_allowed for broadcasters only, not for viewers."""
        import twitch
        for role in ("viewer", "moderator"):
            payload = twitch.verify_twitch_jwt(None, _signed(_claims(role=role)))
            assert twitch.check(payload, db) == {"ok": True, "role": role}

    def test_twitch_check_does_not_record_channel_request(self, db, jwt_env, monkeypatch):
        """GET /twitch/check does not create or bump a twitch_channel_approvals row."""
        import twitch
        from models import TwitchChannelApproval
        monkeypatch.setenv("ENV", "production")
        payload = twitch.verify_twitch_jwt(None, _signed(_claims()))
        twitch.check(payload, db)
        db.commit()
        assert db.query(TwitchChannelApproval).count() == 0
        db.add(TwitchChannelApproval(channel_id=_APPROVAL_CH, status="pending",
                                     first_seen_at=100, last_seen_at=100))
        db.commit()
        twitch.check(payload, db)
        db.commit()
        db.expire_all()
        assert db.get(TwitchChannelApproval, _APPROVAL_CH).last_seen_at == 100

    def test_twitch_check_bad_token_returns_401(self, db, jwt_env):
        """Failure path: GET /twitch/check with a token signed by the wrong secret returns 401."""
        import twitch
        from database import get_db
        engine = _engine()
        session = _session(engine)
        app = FastAPI()
        app.state.limiter = twitch.limiter
        app.include_router(twitch.router)
        app.dependency_overrides[get_db] = lambda: session
        client = TestClient(app)
        wrong = _signed(_claims(), secret=b"another-extension-secret-value!!")
        resp = client.get("/twitch/check", headers={"Authorization": wrong})
        assert resp.status_code == 401
        assert twitch.traffic_snapshot()["failures"]["invalid"] == 1
        good = client.get("/twitch/check", headers={"Authorization": _signed(_claims())})
        assert good.status_code == 200 and good.json()["role"] == "broadcaster"
        session.close()


class TestConnectionCheckPage:
    def test_config_page_has_connection_check_with_five_steps(self, tmp_path):
        """config.html/config.js list Package, Backend address, Backend reachable, Twitch token accepted and MVP selection."""
        html = _read(EXT_DIR / "config.html")
        assert 'id="conn-check"' in html and "Connection check" in html
        js = _read(EXT_DIR / "config.js")
        labels = ["Package", "Backend address", "Backend reachable", "Twitch token accepted", "MVP selection"]
        positions = [js.index(f'label: "{l}"') for l in labels]
        assert positions == sorted(positions)
        out = _run_config(tmp_path, "out.rows = rows();")
        if out is not None:
            assert [r["label"] for r in out["rows"]] == labels

    def test_config_page_steps_marked_ok_failed_or_not_checked(self, tmp_path):
        """Each step is marked OK, Failed or Not checked; later steps after a failure show Not checked."""
        js = _read(EXT_DIR / "config.js")
        for text in ('"OK"', '"Failed"', '"Not checked"'):
            assert text in js
        out = _run_config(tmp_path, """
            good();
            pingResult = refused;
            await runConnectionCheck(); out.unreachable = rows();
            pingResult = resp(200, {ok: true});
            checkResult = resp(200, {ok: true, role: "broadcaster", mvp_allowed: false, approval: "pending"});
            await runConnectionCheck(); out.pending = rows();
            checkResult = resp(200, {ok: true, role: "broadcaster", mvp_allowed: true, approval: "approved"});
            await runConnectionCheck(); out.approved = rows();
        """)
        if out is not None:
            assert _states(out["unreachable"]) == [
                ("Package", "OK"), ("Backend address", "OK"), ("Backend reachable", "Failed"),
                ("Twitch token accepted", "Not checked"), ("MVP selection", "Not checked")]
            assert [s for _, s in _states(out["pending"])] == ["OK", "OK", "OK", "OK", "Failed"]
            assert "pending" in out["pending"][4]["detail"]
            assert [s for _, s in _states(out["approved"])] == ["OK"] * 5

    def test_config_page_calls_ping_and_check_endpoints(self, tmp_path):
        """config.js calls /twitch/ping and /twitch/check for the reachable and token steps."""
        js = _read(EXT_DIR / "config.js")
        assert '"/twitch/ping"' in _js_function(js, "checkReachable")
        assert 'ebsGet("/twitch/check")' in _js_function(js, "checkToken")
        out = _run_config(tmp_path, """
            good();
            pingResult = resp(200, {ok: true});
            checkResult = resp(200, {ok: true, role: "broadcaster", approval: "approved"});
            await runConnectionCheck(); out.calls = fetchCalls;
        """)
        if out is not None:
            assert out["calls"] == [{"url": "https://league.example/twitch/ping", "auth": False},
                                    {"url": "https://league.example/twitch/check", "auth": True}]

    def test_config_page_has_check_again_button_that_reruns_steps(self, tmp_path):
        """A Check again button reruns the connection check."""
        assert 'id="btn-check-again"' in _read(EXT_DIR / "config.html")
        assert 'el("btn-check-again").addEventListener("click", runConnectionCheck)' in _read(EXT_DIR / "config.js")
        out = _run_config(tmp_path, """
            good();
            pingResult = refused;
            await runConnectionCheck();
            out.first = rows()[2].state;
            pingResult = resp(200, {ok: true});
            checkResult = resp(200, {ok: true, role: "broadcaster", approval: "approved"});
            await els["btn-check-again"].listeners.click[0]();
            out.second = rows()[2].state; out.calls = fetchCalls.length;
        """)
        if out is not None:
            assert out == {"first": "Failed", "second": "OK", "calls": 3}

    def test_config_page_shows_reason_code_of_first_failed_step(self, tmp_path):
        """The configuration page shows the same reason code as the panel for the first failed step."""
        assert 'id="conn-code"' in _read(EXT_DIR / "config.html")
        out = _run_config(tmp_path, """
            ext.configuredUrl = "https://other.example/api";
            await runConnectionCheck(); out.origin = [els["conn-code"].textContent, ext.failReason];
            ext.configuredUrl = null; onConfigTimeout(); out.config = els["conn-code"].textContent;
            good(); pingResult = refused;
            await runConnectionCheck(); out.reach = els["conn-code"].textContent;
            pingResult = resp(503);
            await runConnectionCheck(); out.server = els["conn-code"].textContent;
            pingResult = resp(200, {ok: true}); checkResult = resp(401, {detail: "Invalid Twitch token"});
            await runConnectionCheck(); out.token = els["conn-code"].textContent;
            checkResult = resp(200, {ok: true, role: "broadcaster", approval: "approved"});
            await runConnectionCheck(); out.none = [els["conn-code"].textContent, els["conn-code"].hidden];
        """)
        if out is not None:
            assert out["origin"] == ["Reason code: E-ORIGIN", "E-ORIGIN"]
            assert out["config"] == "Reason code: E-CONFIG"
            assert out["reach"] == "Reason code: E-REACH"
            assert out["server"] == "Reason code: E-SERVER"
            assert out["token"] == "Reason code: E-TOKEN"
            assert out["none"] == ["", True]

    def test_config_js_uses_text_content_not_inner_html_for_values(self, tmp_path):
        """Failure path: config.js renders values with textContent, never innerHTML (no injection from ebs_url)."""
        js = _read(EXT_DIR / "config.js")
        assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js
        assert "textContent" in _js_function(js, "renderConnectionCheck")
        out = _run_config(tmp_path, """
            ext.configuredUrl = "https://other.example/<img src=x onerror=alert(1)>";
            await runConnectionCheck(); out.detail = rows()[1].detail;
        """)
        if out is not None:
            assert "<img src=x onerror=alert(1)>" in out["detail"]  # shown as text, not markup


# ---------------------------------------------------------------------------
# Story 3 — Twitch Status in the Admin Portal
# ---------------------------------------------------------------------------

class TestTrafficCounters:
    def test_verify_twitch_jwt_success_records_last_ok_at(self, jwt_env):
        """A valid token sets last_ok_at in the traffic counters."""
        import twitch
        assert twitch.traffic_snapshot()["last_ok_at"] is None
        before = int(time.time())
        payload = twitch.verify_twitch_jwt(None, _signed(_viewer_claims()))
        assert payload["opaque_user_id"] == "Uviewer"
        snap = twitch.traffic_snapshot()
        assert snap["last_ok_at"] >= before
        assert snap["failures"] == {"expired": 0, "invalid": 0, "not_configured": 0}

    def test_verify_twitch_jwt_bad_token_records_invalid_failure(self, jwt_env):
        """Failure path: a bad token raises 401 and increments failures["invalid"] and last_failure_at."""
        import twitch
        for token in ("Bearer not-a-jwt", _signed(_viewer_claims(), secret=b"another-extension-secret-value!!")):
            with pytest.raises(HTTPException) as exc:
                twitch.verify_twitch_jwt(None, token)
            assert exc.value.status_code == 401
        snap = twitch.traffic_snapshot()
        assert snap["failures"]["invalid"] == 2
        assert snap["last_failure_at"] is not None and snap["last_ok_at"] is None

    def test_verify_twitch_jwt_expired_token_records_expired_failure(self, jwt_env):
        """An expired token increments failures["expired"]."""
        import twitch
        claims = _viewer_claims()
        claims["exp"] = int(time.time()) - 60
        with pytest.raises(HTTPException) as exc:
            twitch.verify_twitch_jwt(None, _signed(claims))
        assert exc.value.status_code == 401
        assert twitch.traffic_snapshot()["failures"] == {"expired": 1, "invalid": 0, "not_configured": 0}

    def test_verify_twitch_jwt_missing_secret_records_not_configured_failure(self, jwt_env, monkeypatch):
        """An empty TWITCH_EXTENSION_SECRET increments failures["not_configured"]."""
        import twitch
        monkeypatch.setenv("TWITCH_EXTENSION_SECRET", "")
        with pytest.raises(HTTPException) as exc:
            twitch.verify_twitch_jwt(None, _signed(_viewer_claims()))
        assert exc.value.status_code == 500
        snap = twitch.traffic_snapshot()
        assert snap["failures"]["not_configured"] == 1 and snap["last_failure_at"] is not None

    def test_refused_origins_keep_at_most_five_hosts(self):
        """Cross-origin requests to /twitch/* from unknown origins record the host only, last five kept."""
        import twitch
        client = TestClient(_refused_origin_app())
        for i in range(7):
            client.get("/twitch/ping", headers={"Origin": f"https://host{i}.example:8443"})
        client.get("/twitch/ping", headers={"Origin": "https://host4.example:8443"})  # seen again: moves first
        refused = twitch.traffic_snapshot()["refused_origins"]
        assert refused == ["host4.example:8443", "host6.example:8443", "host5.example:8443",
                           "host3.example:8443", "host2.example:8443"]
        assert all("://" not in h and "/" not in h for h in refused)
        twitch.record_refused_origin("https://" + "a" * 300 + ".example")
        assert len(twitch.traffic_snapshot()["refused_origins"][0]) <= 100

    def test_refused_origins_ignore_extension_origin_and_non_twitch_paths(self, monkeypatch):
        """Failure path: the extension origin, CORS_EXTRA_ORIGINS and paths outside /twitch/ are not recorded."""
        import twitch
        monkeypatch.delenv("APP_BASE_URL", raising=False)
        client = TestClient(_refused_origin_app())
        resp = client.get("/twitch/ping", headers={"Origin": f"https://{_CLIENT_ID}.ext-twitch.tv"})
        assert resp.status_code == 200
        client.get("/twitch/ping", headers={"Origin": "http://localhost:8080"})       # CORS_EXTRA_ORIGINS
        client.get("/other", headers={"Origin": "https://evil.example"})               # not /twitch/*
        client.get("/twitch/ping", headers={"Origin": "http://testserver"})            # same origin
        client.get("/twitch/ping")                                                     # no Origin
        assert twitch.traffic_snapshot()["refused_origins"] == []
        # A refused origin is recorded but never blocked: CORS stays the gate.
        resp = client.get("/twitch/ping", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 200
        assert twitch.traffic_snapshot()["refused_origins"] == ["evil.example"]
        # main.py gives the middleware CORS's own allow list.
        import main
        from fastapi.middleware.cors import CORSMiddleware
        import twitch_status
        mws = {m.cls: m.kwargs for m in main.app.user_middleware}
        assert mws[twitch_status.RefusedOriginMiddleware]["allow_origins"] == mws[CORSMiddleware]["allow_origins"]
        assert (mws[twitch_status.RefusedOriginMiddleware]["allow_origin_regex"]
                == mws[CORSMiddleware]["allow_origin_regex"])


class TestAdminTwitchStatus:
    def test_admin_twitch_status_returns_checks_traffic_and_console(self, monkeypatch, status_env):
        """GET /admin/twitch/status returns checks (key/state/label/detail), traffic and console blocks."""
        client, _ = _admin_client()
        resp = client.get("/admin/twitch/status")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"checks", "traffic", "console"}
        assert [c["key"] for c in data["checks"]] == [
            "extension_client_id", "extension_secret", "extension_version", "local_dev",
            "mvp_channels", "connect_twitch", "app_base_url", "steam_api_key"]
        for c in data["checks"]:
            assert set(c) == {"key", "state", "label", "detail"}
            assert c["state"] == "ok", c
            assert c["label"] and c["detail"]
        assert set(data["traffic"]) == {"last_ok_at", "failures", "last_failure_at", "refused_origins"}
        assert data["console"] and all(set(c) == {"label", "expected"} for c in data["console"])
        from tests.test_issue_163_twitch_steam_account_hardening import _needs_reauth, _route
        from routers import admin_twitch
        assert not _needs_reauth(_route(admin_twitch.router, "/admin/twitch/status", "GET"))

    def test_admin_twitch_status_non_admin_gets_403(self, monkeypatch, status_env):
        """Failure path: a non-admin user gets 403 from GET /admin/twitch/status."""
        app, Session = _build_app(["routers.admin_twitch"])
        _add_user(Session, user_id=2, username="bob", email="bob@example.com")
        client = TestClient(app)
        assert client.get("/admin/twitch/status").status_code in (401, 403)  # no session
        assert client.post("/_test/login/2").status_code == 200
        assert client.get("/admin/twitch/status").status_code == 403

    def test_admin_twitch_status_client_id_row_shows_cors_extension_origin(self, monkeypatch, status_env):
        """The client id row is ok when set and names https://{id}.ext-twitch.tv; problem when empty."""
        row = _row(_status(), "extension_client_id")
        assert row["state"] == "ok"
        assert any(u == f"https://{_CLIENT_ID}.ext-twitch.tv" for u in _urls(row["detail"]))
        monkeypatch.setenv("TWITCH_EXTENSION_CLIENT_ID", "")
        row = _row(_status(), "extension_client_id")
        assert row["state"] == "problem" and "ext-twitch.tv" not in row["detail"]

    def test_admin_twitch_status_empty_secret_is_problem(self, monkeypatch, status_env):
        """An empty TWITCH_EXTENSION_SECRET makes the secret row a problem."""
        assert _row(_status(), "extension_secret")["state"] == "ok"
        for empty in ("", "   ", '""'):
            monkeypatch.setenv("TWITCH_EXTENSION_SECRET", empty)
            assert _row(_status(), "extension_secret")["state"] == "problem", repr(empty)

    def test_admin_twitch_status_secret_not_base64_is_problem(self, monkeypatch, status_env):
        """A TWITCH_EXTENSION_SECRET that does not decode as base64 makes the secret row a problem."""
        monkeypatch.setenv("TWITCH_EXTENSION_SECRET", "not base64!!")
        assert _row(_status(), "extension_secret")["state"] == "problem"
        # Twitch secrets are URL-safe base64, as verify_twitch_jwt decodes them.
        urlsafe = base64.urlsafe_b64encode(b"\xfb\xff\xfe-secret-bytes").decode().rstrip("=")
        monkeypatch.setenv("TWITCH_EXTENSION_SECRET", urlsafe)
        assert _row(_status(), "extension_secret")["state"] == "ok"

    def test_admin_twitch_status_never_returns_secret_its_length_or_token(self, monkeypatch, status_env):
        """The response contains neither the secret, its length, a token nor a viewer's Twitch id."""
        import twitch
        token = _signed(_viewer_claims(opaque_id="Uopaque-viewer-77", user_id="real-twitch-id-88"))
        twitch.verify_twitch_jwt(None, token)
        with pytest.raises(HTTPException):
            twitch.verify_twitch_jwt(None, _signed(_viewer_claims(), secret=b"another-extension-secret-value!!"))
        twitch.record_refused_origin("https://evil.example")
        client, _ = _admin_client()
        data = client.get("/admin/twitch/status").json()
        body = json.dumps(data)
        for leaked in (_SECRET_B64, _SECRET_B64.rstrip("="), _SECRET_BYTES.decode(),
                       token.removeprefix("Bearer "), "Uopaque-viewer-77", "real-twitch-id-88"):
            assert leaked not in body
        texts = json.dumps([data["checks"], data["console"]])
        assert not re.search(rf"\b{len(_SECRET_B64)}\b", texts)
        assert not re.search(rf"\b{len(_SECRET_BYTES)}\b", texts)

        def ints(v):
            if isinstance(v, dict):
                return [i for x in v.values() for i in ints(x)]
            if isinstance(v, list):
                return [i for x in v for i in ints(x)]
            return [v] if isinstance(v, int) and not isinstance(v, bool) else []
        assert len(_SECRET_B64) not in ints(data) and len(_SECRET_BYTES) not in ints(data)

    def test_admin_twitch_status_empty_extension_version_is_warning(self, monkeypatch, status_env):
        """An empty TWITCH_EXTENSION_VERSION makes that row a warning."""
        assert _row(_status(), "extension_version")["state"] == "ok"
        monkeypatch.setenv("TWITCH_EXTENSION_VERSION", "")
        row = _row(_status(), "extension_version")
        assert row["state"] == "warning" and "chat" in row["detail"].lower()

    def test_admin_twitch_status_local_dev_on_is_flagged(self, monkeypatch, status_env):
        """TWITCH_LOCAL_DEV turned on is not ok."""
        assert _row(_status(), "local_dev")["state"] == "ok"
        monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
        assert _row(_status(), "local_dev")["state"] == "warning"
        monkeypatch.setenv("ENV", "production")
        assert _row(_status(), "local_dev")["state"] == "problem"

    def test_admin_twitch_status_mvp_channels_counts_env_approved_and_pending(self, db, monkeypatch, status_env):
        """The MVP channels row counts TWITCH_MVP_CHANNEL_IDS, portal-approved and pending channels."""
        from models import TwitchChannelApproval
        monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "111, 222")
        for cid, st in (("301", "approved"), ("302", "pending"), ("303", "pending"), ("304", "rejected")):
            db.add(TwitchChannelApproval(channel_id=cid, status=st, first_seen_at=1, last_seen_at=1))
        db.commit()
        row = _row(_status(db), "mvp_channels")
        assert row["state"] == "ok"
        assert "2 from TWITCH_MVP_CHANNEL_IDS" in row["detail"]
        assert "1 approved" in row["detail"] and "2 waiting" in row["detail"]

    def test_admin_twitch_status_production_with_no_mvp_channels_is_problem(self, db, monkeypatch, status_env):
        """With ENV=production and zero env, approved and pending channels the MVP row is a problem."""
        from models import TwitchChannelApproval
        monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "")
        assert _row(_status(db), "mvp_channels")["state"] == "ok"  # outside production any channel may
        monkeypatch.setenv("ENV", "production")
        assert _row(_status(db), "mvp_channels")["state"] == "problem"
        db.add(TwitchChannelApproval(channel_id="302", status="pending", first_seen_at=1, last_seen_at=1))
        db.commit()
        assert _row(_status(db), "mvp_channels")["state"] == "warning"  # one waiting to be approved
        db.get(TwitchChannelApproval, "302").status = "approved"
        db.commit()
        assert _row(_status(db), "mvp_channels")["state"] == "ok"

    def test_admin_twitch_status_oauth_set_without_cryptography_is_problem(self, monkeypatch, status_env):
        """All three TWITCH_OAUTH_* set and find_spec("cryptography") returning None makes Connect Twitch a problem."""
        import importlib.util
        assert _row(_status(), "connect_twitch")["state"] == "ok"
        real = importlib.util.find_spec
        monkeypatch.setattr(importlib.util, "find_spec",
                            lambda name, *a, **kw: None if name == "cryptography" else real(name, *a, **kw))
        row = _row(_status(), "connect_twitch")
        assert row["state"] == "problem" and "cryptography" in row["detail"]
        monkeypatch.delenv("TWITCH_OAUTH_CLIENT_SECRET")
        assert _row(_status(), "connect_twitch")["state"] == "warning"  # OAuth not fully set: off

    def test_admin_twitch_status_app_base_url_and_steam_key_rows(self, monkeypatch, status_env):
        """APP_BASE_URL unset is flagged; an empty STEAM_API_KEY is a warning."""
        import steam_live
        status = _status()
        assert _row(status, "app_base_url")["state"] == "ok"
        assert _row(status, "steam_api_key")["state"] == "ok"
        monkeypatch.delenv("APP_BASE_URL")
        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "")
        status = _status()
        assert _row(status, "app_base_url")["state"] != "ok"
        row = _row(status, "steam_api_key")
        assert row["state"] == "warning" and "live games" in row["detail"].lower()

    def test_admin_twitch_status_traffic_reports_counters_and_refused_origins(self, monkeypatch, status_env):
        """traffic carries last_ok_at, failures by kind, last_failure_at and refused_origins."""
        import twitch
        client, _ = _admin_client()
        assert client.get("/admin/twitch/status").json()["traffic"] == {
            "last_ok_at": None, "failures": {"expired": 0, "invalid": 0, "not_configured": 0},
            "last_failure_at": None, "refused_origins": []}
        twitch.verify_twitch_jwt(None, _signed(_viewer_claims()))
        with pytest.raises(HTTPException):
            twitch.verify_twitch_jwt(None, "Bearer junk")
        expired = _viewer_claims()
        expired["exp"] = int(time.time()) - 10
        with pytest.raises(HTTPException):
            twitch.verify_twitch_jwt(None, _signed(expired))
        twitch.record_refused_origin("https://other-ext.ext-twitch.tv")
        traffic = client.get("/admin/twitch/status").json()["traffic"]
        assert isinstance(traffic["last_ok_at"], int) and isinstance(traffic["last_failure_at"], int)
        assert traffic["failures"] == {"expired": 1, "invalid": 1, "not_configured": 0}
        assert traffic["refused_origins"] == ["other-ext.ext-twitch.tv"]

    def test_admin_twitch_status_console_expected_values_use_app_base_url(self, monkeypatch, status_env):
        """console lists URL Fetching Domains, ebs_url and packaged origin checks with expected values from APP_BASE_URL."""
        monkeypatch.setenv("APP_BASE_URL", "https://league.example:8443/")
        console = _status()["console"]
        labels = " ".join(c["label"] for c in console)
        assert "URL Fetching Domains" in labels and "ebs_url" in labels and "packaged" in labels
        assert len(console) == 3
        for c in console:
            assert any(u == "https://league.example:8443" for u in _urls(c["expected"])), c
        assert not any(c["expected"].endswith("/") for c in console)
        monkeypatch.delenv("APP_BASE_URL")
        console = _status()["console"]
        assert all("APP_BASE_URL" in c["expected"] or "origin" in c["expected"] for c in console)

    def test_admin_ui_has_twitch_status_section_above_approved_streamers(self):
        """frontend/index.html has a Twitch status section with a Refresh button above Approved streamers."""
        html = _read(FRONTEND_DIR / "index.html")
        status_at = html.index('<div class="twitch-merges-title">Twitch status</div>')
        assert status_at < html.index('<div class="twitch-merges-title">Approved streamers</div>')
        section = html[status_at:html.index("Approved streamers")]
        assert 'onclick="loadTwitchStatus()"' in section and ">Refresh</button>" in section
        assert 'id="adminTwitchStatus"' in section
        js = _read(FRONTEND_DIR / "app-admin-users.js")
        assert "`${API}/admin/twitch/status`" in js
        assert "loadTwitchStatus();" in _js_function(js, "loadUsers")

    def test_admin_twitch_status_renders_into_its_own_container(self):
        """Failure path: the status table renders into #adminTwitchStatus, and index.html has no duplicate ids.
        A shared id (the Profile tab's #twitchStatus) made Refresh render into the hidden Profile tab."""
        html = _read(FRONTEND_DIR / "index.html")
        ids = re.findall(r'\sid="([^"]+)"', html)
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        assert dupes == [], dupes
        render = _js_function(_read(FRONTEND_DIR / "app-admin-users.js"), "_renderTwitchStatus")
        assert 'getElementById("adminTwitchStatus")' in render
        assert 'getElementById("twitchStatus")' not in render

    def test_admin_ui_escapes_twitch_status_values(self):
        """Failure path: app-admin-users.js renders every status value through _escHtml."""
        js = _read(FRONTEND_DIR / "app-admin-users.js")
        row = _js_function(js, "_twitchStatusRow")
        assert "${_escHtml(label)}" in row and "${_escHtml(detail)}" in row
        render = _js_function(js, "_renderTwitchStatus")
        assert "${_escHtml(c.label)}" in render and "${_escHtml(c.expected)}" in render
        # Every interpolation in the HTML templates is escaped or is markup built from escaped rows
        # (traffic details are plain strings that _twitchStatusRow escapes).
        html_part = render[render.index(".innerHTML ="):]
        for expr in re.findall(r"\$\{([^}]*)\}", row + html_part):
            assert expr.startswith("_escHtml(") or expr in ("cls", "head", "checks", "consoleRows",
                                                             'traffic.join("")'), expr


# ---------------------------------------------------------------------------
# Story 4 — Know What a Package Can Call
# ---------------------------------------------------------------------------

class TestPackageStamp:
    def test_package_sh_writes_ext_build_with_version_and_origins(self, tmp_path):
        """package.sh writes var EXT_BUILD = {version, origins} into the staged ebs-origins.js alongside EBS_ALLOWED_ORIGINS."""
        src = _read(EXT_DIR / "package.sh")
        assert 'EXT_BUILD_JS="var EXT_BUILD = {version: ' in src
        if shutil.which("zip") is None:
            return
        ext = tmp_path / "twitch-extension"
        shutil.copytree(EXT_DIR, ext, ignore=shutil.ignore_patterns("*.zip"))
        result = subprocess.run(["bash", str(ext / "package.sh"), "7.7.7", "--ebs-origin", "https://league.example",
                                 "--ebs-origin", "https://test.league.example"],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        with zipfile.ZipFile(ext / "twitch-extension-7.7.7.zip") as zf:
            baked = zf.read("ebs-origins.js").decode()
        assert 'var EBS_ALLOWED_ORIGINS = ["https://league.example", "https://test.league.example"];' in baked
        assert ('var EXT_BUILD = {version: "7.7.7", origins: ["https://league.example", '
                '"https://test.league.example"]};') in baked
        bad = subprocess.run(["bash", str(ext / "package.sh"), '7.7.8"; alert(1); "', "--ebs-origin",
                              "https://league.example"], capture_output=True, text=True, timeout=60)
        assert bad.returncode != 0

    def test_package_sh_prints_ext_build_at_end_of_build(self, tmp_path):
        """package.sh prints the version and packaged origins at the end of the build."""
        src = _read(EXT_DIR / "package.sh")
        assert src.rstrip().endswith('echo "  $EXT_BUILD_JS"')
        if shutil.which("zip") is None:
            return
        ext = tmp_path / "twitch-extension"
        shutil.copytree(EXT_DIR, ext, ignore=shutil.ignore_patterns("*.zip"))
        result = subprocess.run(["bash", str(ext / "package.sh"), "7.7.7", "--ebs-origin", "https://league.example"],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        last = result.stdout.strip().splitlines()[-1].strip()
        assert last == 'var EXT_BUILD = {version: "7.7.7", origins: ["https://league.example"]};'

    def test_repository_ebs_origins_js_has_dev_stamp(self):
        """The repository ebs-origins.js has EXT_BUILD = {version: "dev", origins: []} and an empty EBS_ALLOWED_ORIGINS."""
        src = _read(EXT_DIR / "ebs-origins.js")
        assert re.search(r"var EBS_ALLOWED_ORIGINS = \[\];", src)
        assert 'var EXT_BUILD = {version: "dev", origins: []};' in src

    def test_config_page_package_row_reads_ext_build(self, tmp_path):
        """The configuration page's Package row shows EXT_BUILD.version and EXT_BUILD.origins."""
        fn = _js_function(_read(EXT_DIR / "config.js"), "checkPackage")
        assert "EXT_BUILD.version" in fn and "EXT_BUILD.origins" in fn
        out = _run_config(tmp_path, "await runConnectionCheck(); out.row = rows()[0];")
        if out is not None:
            assert out["row"]["state"] == "OK"
            assert "1.3.0" in out["row"]["detail"] and any(u == "https://league.example" for u in _urls(out["row"]["detail"]))

    def test_config_page_package_row_handles_missing_ext_build(self, tmp_path):
        """Failure path: config.js does not crash when EXT_BUILD is undefined (older package) and marks Package as failed."""
        fn = _js_function(_read(EXT_DIR / "config.js"), "checkPackage")
        assert 'typeof EXT_BUILD === "undefined"' in fn
        out = _run_config(tmp_path, """
            good(); pingResult = resp(200, {ok: true});
            checkResult = resp(200, {ok: true, role: "broadcaster", approval: "approved"});
            await runConnectionCheck(); out.rows = rows();
        """, build="")
        if out is not None:
            assert _states(out["rows"])[0] == ("Package", "Failed")
            # The other steps still run: they don't depend on the stamp.
            assert [s for _, s in _states(out["rows"])[1:]] == ["OK", "OK", "OK", "OK"]
