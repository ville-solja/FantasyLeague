"""
Tests for plan-issue-213-steam-reauth-without-leaving-the-page.md (resolves GitHub issue #213).

Steam re-auth in a popup window: `GET /auth/steam/start?purpose=reauth&return_tab=popup`
(reauth only; login and link never accept `popup`), the callback redirecting popup
attempts to `/steam-reauth-done.html?steam=<key>`, a static done page
(`frontend/steam-reauth-done.html` + `frontend/steam-reauth-done.js`, no inline script)
that posts `{type: "steam-reauth", result}` to `window.opener` with `location.origin` as
target and closes itself, and `adminFetch` retrying the original request once on `ok`.
The re-auth modal offers both methods to accounts with a password and a linked Steam id.

Developer notes
---------------

  Kinds of test (each docstring says which)
    - Backend: TestClient on the `web` fixture from tests/test_issue_150 (Steam, auth,
      profile and admin routers, in-memory SQLite). Every call to steamcommunity.com is
      mocked: reuse `_round_trip`, `_start`, `_callback`, `_plant`, `_mock_steam`,
      `_id_res_params`, `_signup`, `_location` from that module (underscore names only,
      so pytest doesn't collect its tests twice).
    - Source-reading: static checks on frontend files (`_read`, `_function_source`).
    - Node harness: run the frontend function(s) under Node with a fake DOM, fake
      `window.open` / popup object (`closed`, `close()`), fake `postMessage` / `message`
      events (`origin`, `data`, `source`) and fake `fetch`. Skip when Node is missing.
      See lessons-learned: stub only globals the loaded modules don't define; filter
      `fetch` calls by URL/method instead of reading the last one; re-add `async` when
      pasting an extracted function.

  Open point for the developer
    - The plan's AC says the success message is `result: "ok"`, while Step 2's allowlist
      uses the server keys (`reauth_ok`, `reauth_failed`, `no_session`, `not_linked`).
      Pick one mapping, document it in steam-login.md, and keep the done-page and
      adminFetch harnesses consistent with it.

  Existing tests to keep green
    - tests/test_issue_117_longer_sessions.py pins adminFetch: `_promptReauth()` call,
      exactly two `fetch(url, options)`, no loops; and the reauthModal markup regex.
    - tests/test_twitch_connect_steam_reauth_resume.py pins startSteamReauth storing
      `reauthResume` before `window.location.href` (the full-page fallback keeps that).
    - tests/test_issue_150_steam_login.py pins `/#admin?steam=reauth_ok` and the
      return_tab allowlist falling back to profile.
"""

import json
import re
import shutil
import subprocess
from urllib.parse import urlsplit

import pytest

# Registers every existing table on Base before the conftest db fixture runs create_all.
import models  # noqa: F401

# Reuse the Steam app fixture and LOGIN_METHOD setter (fixtures only, no tests).
from tests.test_issue_150_steam_login import mode, web  # noqa: F401,E402
from tests.test_issue_150_steam_login import (  # noqa: E402
    _OTHER_STEAM64, _STATE_COOKIE, _STEAM64, _add, _callback, _function_source,
    _id_res_params, _location, _main_client, _mock_steam, _plant, _read, _round_trip,
    _signup, _start, _state_from,
)

_DONE = "/steam-reauth-done.html"
# Every key a redirect can carry (steam_openid: start, callback, _reauth).
_FIXED_KEYS = {"login_required", "not_linked", "no_session", "cancelled", "failed",
               "unavailable", "reauth_ok", "reauth_failed"}
# Done page mapping (steam-login.md): server key -> posted result; anything else "failed".
_RESULTS = {"reauth_ok": "ok", "reauth_failed": "reauth_failed", "no_session": "no_session",
            "not_linked": "not_linked"}
_ORIGIN = "https://cards.example"


def _done_key(resp):
    """The key of a popup redirect, after checking it is exactly the done page plus ?steam=<key>."""
    location = _location(resp)
    parts = urlsplit(location)
    assert parts.path == _DONE and not parts.scheme and not parts.netloc, location
    assert parts.query.startswith("steam=") and "&" not in parts.query, location
    key = parts.query[len("steam="):]
    assert key in _FIXED_KEYS, location
    assert location == f"{_DONE}?steam={key}"
    return key


def _steam_admin(web, client, monkeypatch, username="steamchief"):
    """A Steam-only admin (no password) signed in on `client`."""
    monkeypatch.setenv("SEED_ADMIN_STEAM_IDS", _STEAM64)
    _signup(web, client, monkeypatch, username=username)


def _audits(web, action):
    from models import AuditLog
    return [r.detail for r in web.rows(AuditLog, action=action)]


# ---------------------------------------------------------------------------
# Node harnesses
# ---------------------------------------------------------------------------

def _node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    return node


def _run_node(script):
    res = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _done_page(search, opener=True, opener_closed=False):
    """Run frontend/steam-reauth-done.js with a fake window. Returns what it did."""
    script = r"""
const __posts = [];
let __closed = false;
const __el = { textContent: "" };
const document = { getElementById: id => id === "steamReauthDoneText" ? __el : null };
const window = {
  location: { search: %s, origin: %s },
  opener: %s ? { closed: %s, postMessage: (data, target) => __posts.push({ data, target }) } : null,
  close: () => { __closed = true; },
};
""" % (json.dumps(search), json.dumps(_ORIGIN), "true" if opener else "false",
       "true" if opener_closed else "false")
    script += _read("steam-reauth-done.js")
    script += "\nconsole.log(JSON.stringify({ posts: __posts, closed: __closed, text: __el.textContent }));"
    return _run_node(script)


def _reauth_region():
    """app-admin.js from the re-auth state to the typed-confirmation section: adminFetch,
    the modal helpers, the Steam popup flow and the full-page fallback."""
    src = _read("app-admin.js")
    start = src.index("let _reauthResolve = null;")
    end = src.index("// Typed confirmation")
    return src[start:end]


# Fake DOM, window (open / location / message listeners), storage, fetch and timers.
_ADMIN_HARNESS = r"""
const __realSetTimeout = setTimeout;
const __tick = async (n = 3) => { for (let i = 0; i < n; i++) await new Promise(r => __realSetTimeout(r, 0)); };
let __timers = [], __now = 0, __timerId = 0;
globalThis.setInterval = (fn, ms) => { const t = { id: ++__timerId, fn, ms, at: __now + ms, repeat: true }; __timers.push(t); return t.id; };
globalThis.setTimeout = (fn, ms) => { const t = { id: ++__timerId, fn, ms: ms || 0, at: __now + (ms || 0), repeat: false }; __timers.push(t); return t.id; };
globalThis.clearInterval = globalThis.clearTimeout = id => { __timers = __timers.filter(t => t.id !== id); };
function __advance(ms) {
  const end = __now + ms;
  for (;;) {
    const due = __timers.filter(t => t.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!due) break;
    __now = due.at;
    if (due.repeat) due.at += due.ms; else __timers = __timers.filter(t => t !== due);
    due.fn();
  }
  __now = end;
}
const __els = {};
class El {
  constructor(id) {
    this.id = id; this.style = {}; this.textContent = ""; this.value = ""; this.listeners = {};
    const cls = new Set(); this.cls = cls;
    this.classList = { add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c) };
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
}
let __activeTab = new El("tab-admin");
const document = {
  getElementById: id => __els[id] || (__els[id] = new El(id)),
  querySelector: sel => sel === ".tab-content.active" ? __activeTab : null,
};
document.getElementById("reauthModal").classList.add("hidden");
const __opened = [], __hrefSets = [], __msgListeners = [];
let __blockPopup = false, __lastPopup = null;
const window = {
  location: {
    origin: "%(origin)s",
    get href() { return "%(origin)s/"; },
    set href(v) { __hrefSets.push(v); },
  },
  open(url, name, features) {
    __opened.push({ url, name, features });
    if (__blockPopup) return null;
    __lastPopup = { closed: false, closeCalls: 0, close() { this.closed = true; this.closeCalls++; } };
    return __lastPopup;
  },
  addEventListener(type, fn) { if (type === "message") __msgListeners.push(fn); },
};
function __post(data, origin, source) {
  const ev = { data, origin: origin === undefined ? window.location.origin : origin,
               source: source === undefined ? __lastPopup : source };
  __msgListeners.forEach(fn => fn(ev));
}
let __store = {};
const sessionStorage = {
  getItem: k => (k in __store ? __store[k] : null),
  setItem: (k, v) => { __store[k] = String(v); },
  removeItem: k => { delete __store[k]; },
};
const __routes = [], __fetchCalls = [];
function __resp(status, body) {
  return { ok: status < 400, status, json: async () => body, clone() { return this; } };
}
function fetch(url, opts) {
  __fetchCalls.push({ url, method: (opts && opts.method) || "GET" });
  for (const [prefix, handler] of __routes) {
    if (url.startsWith(prefix)) return Promise.resolve(handler(url, opts));
  }
  return Promise.reject(new Error("no route for " + url));
}
/** A route answering 403 reauth_required first, then 200 {done: true}. */
function __reauthRoute(prefix) {
  let n = 0;
  __routes.push([prefix, () => (++n === 1 ? __resp(403, { detail: "reauth_required" }) : __resp(200, { done: true }))]);
}
const __calls = prefix => __fetchCalls.filter(c => c.url.startsWith(prefix)).length;
const __shown = id => document.getElementById(id).style.display !== "none";
const __modalOpen = () => !document.getElementById("reauthModal").classList.contains("hidden");
const API = "";
let activeUsername = "boss";
let activeHasPassword = %(has_password)s;
let activeSteamLinked = %(steam_linked)s;
let _loginMethod = %(login_method)s;
let _steamReauthAvailable = %(available)s;
"""


def _admin(body, *, has_password=False, steam_linked=True, login_method="both", available=True):
    """Run `body` (async; sets `out`) with app-admin.js's re-auth code under the fake DOM."""
    src = _ADMIN_HARNESS % {
        "origin": _ORIGIN, "has_password": json.dumps(has_password),
        "steam_linked": json.dumps(steam_linked), "login_method": json.dumps(login_method),
        "available": json.dumps(available),
    } + _reauth_region()
    script = src + "\nlet out = null;\n(async () => {\n" + body + \
        "\nconsole.log(JSON.stringify(out));\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });"
    return _run_node(script)


def _popup_flow(message_js, after_js="", url="/admin/season/end"):
    """adminFetch on a reauth_required route, Confirm with Steam, then `message_js`."""
    return _admin(f"""
        __reauthRoute({json.dumps(url)});
        let settled = null;
        const p = adminFetch({json.dumps(url)}, {{ method: "POST" }}).then(r => {{ settled = r; return r; }});
        await __tick();
        const openBefore = __modalOpen();
        startSteamReauth();
        {message_js}
        await __tick();
        {after_js}
        out = {{
          openBefore, settled: settled ? settled.status : null, calls: __calls({json.dumps(url)}),
          modalOpen: __modalOpen(), status: document.getElementById("reauthStatus").textContent,
          opened: __opened, hrefSets: __hrefSets,
        }};
    """)




# ---------------------------------------------------------------------------
# Story 1: Steam-Only Admins Confirm Without Losing Their Work — server
# ---------------------------------------------------------------------------

class TestPopupServer:

    def test_steam_start_reauth_accepts_return_tab_popup(self, web, mode):
        """AC (backend): GET /auth/steam/start?purpose=reauth&return_tab=popup is accepted: 303 to Steam and the SteamLoginState row stores return_tab='popup'."""
        from models import SteamLoginState
        mode("both")
        web.add_user("alice", steam_id=_STEAM64)
        client = web.login("alice", reauth=False)
        _state_from(_start(client, "reauth", return_tab="popup"))
        rows = web.rows(SteamLoginState, purpose="reauth")
        assert len(rows) == 1 and rows[0].return_tab == "popup"

    def test_steam_start_login_never_accepts_return_tab_popup(self, web, mode, monkeypatch):
        """AC failure path (backend): purpose=login with return_tab=popup never stores or redirects to popup (row return_tab stays None; no /steam-reauth-done.html redirect)."""
        from models import SteamLoginState
        mode("both")
        client = web.client()
        resp, _ = _round_trip(client, monkeypatch, purpose="login", return_tab="popup")
        assert _location(resp) == "/#welcome?steam=choose_name"
        rows = web.rows(SteamLoginState)
        assert len(rows) == 1 and rows[0].purpose == "login" and rows[0].return_tab is None

    def test_steam_start_link_never_accepts_return_tab_popup(self, web, mode):
        """AC failure path (backend): purpose=link with return_tab=popup never uses popup; its early redirects (reauth_required, linked, not_allowed) still go to /#profile?steam=<key>."""
        from models import SteamLoginState
        mode("both")
        anon = web.client()
        assert _location(_start(anon, "link", return_tab="popup")) == "/#profile?steam=login_required"
        web.add_user("alice")
        stale = web.login("alice", reauth=False)
        assert _location(_start(stale, "link", return_tab="popup")) == "/#profile?steam=reauth_required"
        web.add_user("linked", steam_id=_STEAM64)
        linked = web.login("linked")
        assert _location(_start(linked, "link", return_tab="popup")) == "/#profile?steam=linked"
        web.add_user("demo1", is_demo=True)
        demo = web.login("demo1")
        assert _location(_start(demo, "link", return_tab="popup")) == "/#profile?steam=not_allowed"
        fresh = web.login("alice")
        _state_from(_start(fresh, "link", return_tab="popup"))
        assert [r.return_tab for r in web.rows(SteamLoginState, purpose="link")] == [None]

    def test_steam_start_popup_without_app_base_url_answers_503(self, web, mode, monkeypatch):
        """AC (backend): without APP_BASE_URL, purpose=reauth&return_tab=popup answers 503 {"detail": "steam_unavailable"} and stores no state."""
        from models import SteamLoginState
        mode("both")
        web.add_user("alice", steam_id=_STEAM64)
        client = web.login("alice", reauth=False)
        monkeypatch.delenv("APP_BASE_URL", raising=False)
        resp = _start(client, "reauth", return_tab="popup")
        assert resp.status_code == 503 and resp.json() == {"detail": "steam_unavailable"}
        assert web.rows(SteamLoginState) == []

    def test_steam_callback_popup_reauth_ok_redirects_to_done_page(self, web, mode, monkeypatch):
        """AC (backend): a matching Steam id on a popup attempt redirects to exactly /steam-reauth-done.html?steam=reauth_ok, marks the same session (reauth_at set) and audits admin_reauth 'ok (method=steam)'."""
        from models import UserSession
        mode("both")
        client = web.client()
        _steam_admin(web, client, monkeypatch)
        sessions_before = [r.id for r in web.rows(UserSession)]
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth", return_tab="popup")
        assert _location(resp) == "/steam-reauth-done.html?steam=reauth_ok"
        rows = web.rows(UserSession)
        assert [r.id for r in rows] == sessions_before and rows[0].reauth_at is not None
        assert _audits(web, "admin_reauth") == ["ok (method=steam)"]

    def test_steam_callback_popup_identity_mismatch_refused_and_audited(self, web, mode, monkeypatch):
        """AC failure path (backend): a different Steam id on a popup attempt redirects to /steam-reauth-done.html?steam=reauth_failed, leaves reauth_at None and audits 'failed: different Steam account (method=steam)'."""
        from models import UserSession
        mode("both")
        client = web.client()
        _steam_admin(web, client, monkeypatch)
        resp, _ = _round_trip(client, monkeypatch, _OTHER_STEAM64, purpose="reauth", return_tab="popup")
        assert _location(resp) == "/steam-reauth-done.html?steam=reauth_failed"
        assert web.rows(UserSession)[0].reauth_at is None
        assert _audits(web, "admin_reauth") == ["failed: different Steam account (method=steam)"]

    def test_steam_popup_redirect_keys_come_from_fixed_set(self, web, mode, monkeypatch):
        """AC (backend): every popup redirect (start: login_required, not_linked; callback: no_session, cancelled, failed, unavailable, reauth_ok, reauth_failed) is exactly /steam-reauth-done.html?steam=<key> with a key from the fixed set and no request data."""
        mode("both")
        seen = set()
        # start
        assert _done_key(_start(web.client(), "reauth", return_tab="popup")) == "login_required"
        web.add_user("nolink")
        assert _done_key(_start(web.login("nolink", reauth=False), "reauth", return_tab="popup")) == "not_linked"
        seen |= {"login_required", "not_linked"}
        uid = web.add_user("alice", steam_id=_STEAM64)

        def planted(state, *, signed_in=True, **assertion):
            client = web.login("alice", reauth=False) if signed_in else web.client()
            _plant(web, client, purpose="reauth", user_id=uid, state=state, return_tab="popup")
            return client, _id_res_params(_STEAM64, state, **assertion)

        # callback
        client, params = planted("st-no-session", signed_in=False)
        _mock_steam(monkeypatch)
        seen.add(_done_key(_callback(client, params)))
        client, params = planted("st-cancel", overrides={"openid.mode": "cancel"})
        seen.add(_done_key(_callback(client, params)))
        client, params = planted("st-failed", overrides={"openid.op_endpoint": "https://evil.example/openid"})
        seen.add(_done_key(_callback(client, params)))
        client, params = planted("st-unavailable")
        _mock_steam(monkeypatch, raises=ConnectionError("down"))
        seen.add(_done_key(_callback(client, params)))
        _mock_steam(monkeypatch)
        client, params = planted("st-ok")
        seen.add(_done_key(_callback(client, params)))
        client = web.login("alice", reauth=False)
        _plant(web, client, purpose="reauth", user_id=uid, state="st-other", return_tab="popup")
        seen.add(_done_key(_callback(client, _id_res_params(_OTHER_STEAM64, "st-other"))))
        assert seen == _FIXED_KEYS

    def test_steam_callback_popup_state_is_one_time(self, web, mode, monkeypatch):
        """AC failure path (backend): replaying a used popup state is refused (used_at set on first use, second callback marks nothing), as for the full-page path."""
        from models import SteamLoginState, UserSession
        mode("both")
        web.add_user("alice", steam_id=_STEAM64)
        client = web.login("alice", reauth=False)
        state = _state_from(_start(client, "reauth", return_tab="popup"))
        _mock_steam(monkeypatch)
        params = _id_res_params(_STEAM64, state)
        assert _done_key(_callback(client, params)) == "reauth_ok"
        assert web.rows(SteamLoginState)[0].used_at is not None
        db = web.Session()
        try:
            db.query(UserSession).update({UserSession.reauth_at: None})
            db.commit()
        finally:
            db.close()
        client.cookies.set(_STATE_COOKIE, state)
        assert _done_key(_callback(client, params)) == "failed"
        assert web.rows(UserSession)[0].reauth_at is None
        assert _audits(web, "player_reauth") == ["ok (method=steam)"]

    def test_steam_popup_player_reauth_audited_as_player_reauth(self, web, mode, monkeypatch):
        """AC (backend): a non-admin's popup re-auth is audited as player_reauth (method=steam) and satisfies require_recent_player_reauth (Unlink Steam)."""
        mode("both")
        web.add_user("alice", steam_id=_STEAM64)
        client = web.login("alice", reauth=False)
        before = client.post("/profile/steam/unlink")
        assert before.status_code == 403 and before.json()["detail"] == "reauth_required"
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth", return_tab="popup")
        assert _done_key(resp) == "reauth_ok"
        assert _audits(web, "player_reauth") == ["ok (method=steam)"]
        assert _audits(web, "admin_reauth") == []
        after = client.post("/profile/steam/unlink")
        assert after.status_code == 200 and after.json()["changed"] is True

    def test_steam_full_page_reauth_redirect_unchanged(self, web, mode, monkeypatch):
        """AC (backend): return_tab=admin still redirects to /#admin?steam=reauth_ok and an unknown return_tab still falls back to /#profile (full-page path unchanged)."""
        mode("both")
        client = web.client()
        _steam_admin(web, client, monkeypatch)
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth", return_tab="admin")
        assert _location(resp) == "/#admin?steam=reauth_ok"
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth", return_tab="https://evil.example/")
        assert _location(resp) == "/#profile?steam=reauth_ok"
        resp, _ = _round_trip(client, monkeypatch, purpose="reauth")
        assert _location(resp) == "/#profile?steam=reauth_ok"


# ---------------------------------------------------------------------------
# Story 1 — done page (frontend/steam-reauth-done.html + steam-reauth-done.js)
# ---------------------------------------------------------------------------

class TestDonePage:

    def test_done_page_has_no_inline_script(self):
        """AC (source-reading): steam-reauth-done.html exists, loads only the local steam-reauth-done.js, and has no inline <script> body, inline event handlers or external scripts."""
        from html.parser import HTMLParser

        class _Scan(HTMLParser):
            def __init__(self):
                super().__init__()
                self.scripts, self.handlers, self._in_script, self.script_text = [], [], False, ""

            def handle_starttag(self, tag, attrs):
                self.handlers += [name for name, _ in attrs if name.lower().startswith("on")]
                if tag == "script":
                    self.scripts.append(dict(attrs))
                    self._in_script = True

            def handle_endtag(self, tag):
                if tag == "script":
                    self._in_script = False

            def handle_data(self, data):
                if self._in_script:
                    self.script_text += data

        html = _read("steam-reauth-done.html")
        scan = _Scan()
        scan.feed(html)
        assert scan.scripts == [{"src": "/steam-reauth-done.js"}]
        assert scan.script_text.strip() == ""
        assert scan.handlers == []
        assert "http://" not in html and "https://" not in html
        js = _read("steam-reauth-done.js")
        assert "import " not in js and "fetch(" not in js and "innerHTML" not in js

    def test_done_page_served_by_static_mount(self):
        """AC (backend, main app): GET /steam-reauth-done.html and /steam-reauth-done.js answer 200 from the frontend static mount with the usual security headers (CSP compatible)."""
        client = _main_client()
        for path, kind in (("/steam-reauth-done.html", "text/html"),
                           ("/steam-reauth-done.js", "javascript")):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert kind in resp.headers["content-type"]
            assert resp.headers["x-content-type-options"] == "nosniff"
            assert "frame-ancestors" in resp.headers["content-security-policy"]
            assert resp.headers["cache-control"] == "no-cache"

    def test_done_page_posts_result_to_opener_with_own_origin(self):
        """AC (Node harness): with ?steam=reauth_ok the page calls window.opener.postMessage({type: "steam-reauth", result: "ok"}, location.origin), never with '*'."""
        out = _done_page("?steam=reauth_ok")
        assert out["posts"] == [{"data": {"type": "steam-reauth", "result": "ok"}, "target": _ORIGIN}]
        for key, result in _RESULTS.items():
            assert _done_page(f"?steam={key}")["posts"][0]["data"]["result"] == result
        calls = re.findall(r"postMessage\(([^;]*)\);", _read("steam-reauth-done.js"))
        assert calls and all(c.endswith("window.location.origin") and "*" not in c for c in calls)

    def test_done_page_maps_unknown_key_to_failed(self):
        """AC failure path (Node harness): a key outside reauth_ok/reauth_failed/no_session/not_linked (or a missing key) posts result 'failed'; the raw query value is never posted."""
        for search in ("", "?steam=", "?steam=cancelled", "?steam=unavailable", "?steam=login_required",
                       "?steam=<b>x</b>", "?steam=__proto__", "?steam=toString", "?other=reauth_ok"):
            out = _done_page(search)
            assert out["posts"] == [{"data": {"type": "steam-reauth", "result": "failed"}, "target": _ORIGIN}], search

    def test_done_page_closes_itself_after_posting(self):
        """AC (Node harness): after posting to the opener the page calls window.close()."""
        assert _done_page("?steam=reauth_ok")["closed"] is True
        assert _done_page("?steam=reauth_failed")["closed"] is True
        js = _read("steam-reauth-done.js")
        assert js.index("postMessage(") < js.index("window.close()")

    def test_done_page_without_opener_shows_message(self):
        """AC failure path (Node harness): with no window.opener the page posts nothing and shows a short message telling the user to return to the site."""
        for kwargs in ({"opener": False}, {"opener": True, "opener_closed": True}):
            out = _done_page("?steam=reauth_ok", **kwargs)
            assert out["posts"] == [] and out["closed"] is False
            assert "return to the site" in out["text"]
        assert "return to the site" in _done_page("?steam=reauth_failed", opener=False)["text"]


# ---------------------------------------------------------------------------
# Story 1 — adminFetch popup flow (frontend/app-admin.js)
# ---------------------------------------------------------------------------

class TestAdminFetchPopup:

    def test_start_steam_reauth_opens_named_popup_from_click(self):
        """AC (Node harness): Confirm with Steam calls window.open synchronously in the click handler with /auth/steam/start?purpose=reauth&return_tab=popup, a window name and ~800x700 features."""
        out = _admin("""
            _promptReauth();
            startSteamReauth();
            out = __opened.slice();
        """)
        assert len(out) == 1
        assert out[0]["url"] == "/auth/steam/start?purpose=reauth&return_tab=popup"
        assert out[0]["name"] and out[0]["name"] != "_blank"
        assert "width=800" in out[0]["features"] and "height=700" in out[0]["features"]
        start = _function_source(_read("app-admin.js"), "startSteamReauth")
        assert "async function startSteamReauth" not in _read("app-admin.js")
        assert "await" not in start[:start.index("window.open(")]
        assert 'onclick="startSteamReauth()"' in _read("index.html")

    def test_admin_fetch_popup_ok_message_retries_once(self):
        """AC (Node harness): a {type: "steam-reauth", result: ok} message from location.origin resolves the prompt, adminFetch retries the original request exactly once and returns the retry's response."""
        out = _popup_flow('__post({ type: "steam-reauth", result: "ok" });')
        assert out["openBefore"] is True
        assert out["settled"] == 200 and out["calls"] == 2
        assert out["modalOpen"] is False

    def test_admin_fetch_popup_keeps_page_and_dialog(self):
        """AC (Node harness): during the popup flow window.location.href is never assigned and an open dialog's input value is unchanged after the retry."""
        out = _admin("""
            const field = document.getElementById("seasonEndNote");
            field.value = "typed before the check";
            __reauthRoute("/admin/season/end");
            const p = adminFetch("/admin/season/end", { method: "POST" });
            await __tick();
            startSteamReauth();
            __post({ type: "steam-reauth", result: "ok" });
            const res = await p;
            out = { status: res.status, hrefSets: __hrefSets, value: field.value, store: __store };
        """)
        assert out == {"status": 200, "hrefSets": [], "value": "typed before the check", "store": {}}

    def test_admin_fetch_popup_ignores_wrong_origin_message(self):
        """AC failure path (Node harness): an ok-shaped message from another origin is ignored: no retry, the prompt stays open."""
        out = _popup_flow("""
            __post({ type: "steam-reauth", result: "ok" }, "https://evil.example");
            __post({ type: "steam-reauth", result: "ok" }, "null");
            __post({ type: "steam-reauth", result: "ok" }, undefined, { closed: false });
        """)
        assert out["settled"] is None and out["calls"] == 1 and out["modalOpen"] is True

    def test_admin_fetch_popup_ignores_wrong_shape_message(self):
        """AC failure path (Node harness): a same-origin message with the wrong type, a non-object payload or an unknown result is ignored: no retry."""
        out = _popup_flow("""
            __post({ type: "other", result: "ok" });
            __post("ok");
            __post(null);
            __post(["steam-reauth", "ok"]);
            __post({ type: "steam-reauth" });
            __post({ type: "steam-reauth", result: "maybe" });
            __post({ type: "steam-reauth", result: "__proto__" });
            __post({ type: "steam-reauth", result: "toString" });
        """)
        assert out["settled"] is None and out["calls"] == 1 and out["modalOpen"] is True
        assert out["status"] == ""

    def test_admin_fetch_popup_reauth_failed_shows_message_no_retry(self):
        """AC failure path (Node harness): result reauth_failed shows "That Steam account is not the one linked to this account. Nothing was confirmed" in the modal and nothing is retried."""
        out = _popup_flow('__post({ type: "steam-reauth", result: "reauth_failed" });',
                          after_js="__advance(5000); await __tick();")
        assert out["status"].startswith(
            "That Steam account is not the one linked to this account. Nothing was confirmed")
        assert out["modalOpen"] is True and out["settled"] is None and out["calls"] == 1
        # Cancelling afterwards hands the original 403 back, still without a retry.
        out = _popup_flow('__post({ type: "steam-reauth", result: "reauth_failed" });',
                          after_js="closeReauthModal(); await __tick();")
        assert out["settled"] == 403 and out["calls"] == 1
        for result, text in (("no_session", "Log in to Kana Cards first"),
                             ("not_linked", "no Steam link"), ("failed", "did not complete")):
            out = _popup_flow(f'__post({{ type: "steam-reauth", result: "{result}" }});')
            assert text in out["status"] and out["calls"] == 1, result

    def test_admin_fetch_popup_closed_resolves_not_confirmed(self):
        """AC failure path (Node harness): closing the popup without a message resolves as not confirmed; adminFetch returns the original 403 and does not retry."""
        out = _popup_flow("__lastPopup.closed = true; __advance(2000);")
        assert out["settled"] == 403 and out["calls"] == 1 and out["modalOpen"] is False
        # A result that arrives within the grace period after the close still counts.
        out = _popup_flow("""
            __lastPopup.closed = true;
            __advance(500);
            __post({ type: "steam-reauth", result: "ok" });
            __advance(2000);
        """)
        assert out["settled"] == 200 and out["calls"] == 2

    def test_admin_fetch_popup_blocked_offers_continue_on_this_page(self):
        """AC failure path (Node harness): window.open returning null shows "Your browser blocked the Steam window" and a Continue on this page button."""
        out = _admin("""
            __blockPopup = true;
            __reauthRoute("/admin/season/end");
            const p = adminFetch("/admin/season/end", { method: "POST" });
            await __tick();
            startSteamReauth();
            await __tick();
            out = { blocked: __shown("reauthPopupBlocked"), unavailable: __shown("reauthSteamUnavailable"),
                    modalOpen: __modalOpen(), calls: __calls("/admin/season/end"), hrefSets: __hrefSets,
                    opened: __opened.length };
        """)
        assert out == {"blocked": True, "unavailable": False, "modalOpen": True, "calls": 1,
                       "hrefSets": [], "opened": 1}
        html = _read("index.html")
        block = html[html.index('id="reauthPopupBlocked"'):]
        block = block[:block.index("</div>")]
        assert "Your browser blocked the Steam window" in block
        assert re.search(r'onclick="startSteamReauthFullPage\(\)">Continue on this page</button>', block)

    def test_continue_on_this_page_runs_full_page_path(self):
        """AC (Node harness): Continue on this page stores reauthResume and navigates to /auth/steam/start?purpose=reauth&return_tab=admin|profile, exactly as today's full-page path."""
        out = _admin("""
            __blockPopup = true;
            _promptReauth("connectTwitch");
            startSteamReauth();
            __activeTab = new El("tab-profile");
            startSteamReauthFullPage();
            const profile = { href: __hrefSets.slice(), store: Object.assign({}, __store) };
            _promptReauth();
            __activeTab = new El("tab-admin");
            startSteamReauthFullPage();
            out = { profile, admin: __hrefSets[1], store: __store };
        """)
        assert out["profile"] == {"href": ["/auth/steam/start?purpose=reauth&return_tab=profile"],
                                  "store": {"reauthResume": "connectTwitch"}}
        assert out["admin"] == "/auth/steam/start?purpose=reauth&return_tab=admin"
        assert out["store"] == {}

    def test_full_page_return_messages_unchanged(self):
        """AC (source-reading): handleSteamReturn and _STEAM_RETURN_MESSAGES keep the full-page texts (e.g. 'Confirmed with Steam. Repeat the action to continue.') and the connectTwitch resume."""
        auth = _read("app-auth.js")
        assert 'reauth_ok:     ["Confirmed with Steam. Repeat the action to continue.", true]' in auth
        assert ('reauth_failed: ["That Steam account is not the one linked to this account. '
                'Nothing was confirmed.", false]') in auth
        assert re.search(r"_REAUTH_RESUMABLE\s*=\s*\{\s*connectTwitch:", auth)
        handler = _function_source(auth, "handleSteamReturn")
        assert "_takeReauthResume()" in handler and "adminSteamStatus" in handler
        assert re.search(r'key === "reauth_ok" && resume\)\s*\{[^}]*resume\(\);', handler)

    def test_unlink_steam_uses_popup_path(self):
        """AC (Node harness or source-reading): Unlink Steam (POST /profile/steam/unlink via adminFetch) on a 403 reauth_required uses the same popup and retries once on ok."""
        unlink = _function_source(_read("app-profile.js"), "unlinkSteam")
        assert "adminFetch(`${API}/profile/steam/unlink`" in unlink
        out = _popup_flow('__post({ type: "steam-reauth", result: "ok" });', url="/profile/steam/unlink")
        assert out["opened"][0]["url"] == "/auth/steam/start?purpose=reauth&return_tab=popup"
        assert out["settled"] == 200 and out["calls"] == 2 and out["hrefSets"] == []

    def test_twitch_connection_actions_use_popup_path(self):
        """AC (source-reading): Twitch disconnect and merge confirm go through adminFetch, and Connect Twitch's _promptReauth("connectTwitch") continues to connectTwitch() after a popup ok without leaving the page."""
        profile = _read("app-profile.js")
        assert "adminFetch(`${API}/twitch/disconnect`" in _function_source(profile, "disconnectTwitch")
        assert "adminFetch(`${API}/twitch/merge/confirm`" in _function_source(profile, "confirmTwitchMerge")
        assert re.search(r'_promptReauth\("connectTwitch"\)\.then\(ok => \{\s*if \(ok\) connectTwitch\(\);',
                         _function_source(profile, "handleTwitchReturn"))
        out = _admin("""
            let resumed = null;
            _promptReauth("connectTwitch").then(ok => { resumed = ok; });
            startSteamReauth();
            __post({ type: "steam-reauth", result: "ok" });
            await __tick();
            out = { resumed, hrefSets: __hrefSets, store: __store };
        """)
        assert out == {"resumed": True, "hrefSets": [], "store": {}}


# ---------------------------------------------------------------------------
# Story 2: Admins With a Password Can Use Steam Too
# ---------------------------------------------------------------------------

_MODAL_STATE = """
    _promptReauth();
    out = { form: __shown("reauthForm"), password: __shown("reauthPasswordText"),
            steamBlock: __shown("reauthSteamBlock"), steamInstead: __shown("reauthSteamInstead"),
            title: document.getElementById("reauthTitle").textContent };
"""


class TestBothMethods:

    def test_reauth_modal_shows_password_and_steam_instead_when_both(self):
        """AC (Node harness): with activeHasPassword, activeSteamLinked and Steam enabled, the modal shows the password form plus a "Confirm with Steam instead" button."""
        for method in ("both", "steam_signup"):
            out = _admin(_MODAL_STATE, has_password=True, steam_linked=True, login_method=method)
            assert out == {"form": True, "password": True, "steamBlock": False, "steamInstead": True,
                           "title": "Confirm your password"}, method
        out = _admin("""
            _promptReauth();
            startSteamReauth();
            out = __opened.map(o => o.url);
        """, has_password=True, steam_linked=True)
        assert out == ["/auth/steam/start?purpose=reauth&return_tab=popup"]

    def test_reauth_modal_password_only_without_steam_link(self):
        """AC failure path (Node harness): with a password but no linked Steam id, the modal shows only the password form (no Steam button), as today."""
        out = _admin(_MODAL_STATE, has_password=True, steam_linked=False)
        assert out == {"form": True, "password": True, "steamBlock": False, "steamInstead": False,
                       "title": "Confirm your password"}

    def test_reauth_modal_password_only_when_steam_disabled(self):
        """AC failure path (Node harness): with a password and a linked Steam id but Steam not enabled (LOGIN_METHOD=password), the modal shows only the password form."""
        out = _admin(_MODAL_STATE, has_password=True, steam_linked=True, login_method="password",
                     available=False)
        assert out["form"] is True and out["steamInstead"] is False and out["steamBlock"] is False

    def test_reauth_modal_steam_only_for_passwordless_account(self):
        """AC (Node harness): an account without a password sees only Confirm with Steam (no password form)."""
        out = _admin(_MODAL_STATE, has_password=False, steam_linked=True)
        assert out == {"form": False, "password": False, "steamBlock": True, "steamInstead": False,
                       "title": "Confirm with Steam"}

    def test_reauth_modal_steam_unavailable_shows_message(self, monkeypatch, db):
        """AC failure path (Node harness): /auth/steam/start answering 503 steam_unavailable shows "Steam confirmation is unavailable on this server", leaves no dead popup open and keeps the password form where the account has one."""
        # The page learns it from GET /config: false without APP_BASE_URL (where start answers 503).
        # Called directly with the in-memory db fixture: the app's own database has no
        # tables in a fresh CI checkout.
        import main
        monkeypatch.setenv("LOGIN_METHOD", "both")
        monkeypatch.delenv("APP_BASE_URL", raising=False)
        assert main.get_config(db)["steam_reauth_available"] is False
        monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
        assert main.get_config(db)["steam_reauth_available"] is True
        monkeypatch.setenv("LOGIN_METHOD", "password")
        assert main.get_config(db)["steam_reauth_available"] is False
        assert "cfg.steam_reauth_available === true" in _read("app-globals.js")

        body = """
            _promptReauth();
            startSteamReauth();
            out = { opened: __opened.length, unavailable: __shown("reauthSteamUnavailable"),
                    blocked: __shown("reauthPopupBlocked"), form: __shown("reauthForm"),
                    modalOpen: __modalOpen(), hrefSets: __hrefSets };
        """
        out = _admin(body, has_password=True, steam_linked=True, available=False)
        assert out == {"opened": 0, "unavailable": True, "blocked": False, "form": True,
                       "modalOpen": True, "hrefSets": []}
        out = _admin(body, has_password=False, steam_linked=True, available=False)
        assert out["opened"] == 0 and out["unavailable"] is True and out["form"] is False
        html = _read("index.html")
        assert re.search(r'id="reauthSteamUnavailable"[^>]*>Steam confirmation is unavailable on this server\.<', html)

    def test_index_html_reauth_modal_markup(self):
        """AC (source-reading): index.html's reauthModal has the "Confirm with Steam instead" button and slots for the blocked-popup and unavailable messages, after the reauthPassword input that older regexes look for."""
        html = _read("index.html")
        modal = html[html.index('id="reauthModal"'):]
        modal = modal[:modal.index('id="reauthStatus"')]
        password = modal.index('<input id="reauthPassword" type="password"')
        assert modal.index('<form id="reauthForm"') < password
        for marker in ('id="reauthSteamInstead"', 'id="reauthPopupBlocked"', 'id="reauthSteamUnavailable"'):
            assert marker in modal and modal.index(marker) > password, marker
        assert re.search(r'id="reauthSteamInstead"[^>]*onclick="startSteamReauth\(\)">Confirm with Steam instead</button>', modal)
        assert "window.open" not in html
