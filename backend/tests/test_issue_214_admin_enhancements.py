"""
Tests for plan-issue-214-admin-enhancements.md (resolves GitHub issue #214).

The Admin tab is reorganised around its most frequent jobs: a Twitch sub-tab
with pending streamer approvals first and a count badge, spinner-free id inputs
with a name preview (`GET /admin/players/lookup`), a simpler Mark champions
roster editor, a Matches table grouped by series around the MVP job (new
series fields on `GET /admin/matches`), and Settings grouped into six sections.

  Story 1: Streamer Approvals Come First
  Story 2: Ids Are Typed, and Names Show Before Saving
  Story 3: Mark Champions and Add Accolade Are Simpler
  Story 4: Matches Are Organised for Setting MVPs
  Story 5: Settings Grouped by Purpose

Approach notes (for the developer filling these in):

- Backend: use a shared-connection in-memory `db` (StaticPool, as in
  test_issue_208_player_popup_visualizations.py) plus a small FastAPI app with
  the router under test (`routers.admin_players` / `routers.admin_matches`)
  and `get_db` overridden. Sessions via `{"sid": sessions.create_session(db,
  user)}`; `require_admin` checks `is_admin` fresh from the database.
- Lookup: mock the OpenDota client (`admin_players.opendota_get_json`, imported
  from `opendota_client.get_json`) and count calls; never hit the network.
  Clear the lookup cache between tests (expose a clear helper or monkeypatch
  the cache dict).
- `GET /admin/matches`: monkeypatch `schedule.get_schedule` (or the name
  `routers.admin_matches` imports) to return a hand-built schedule, so the
  feed is never fetched. Keep the existing response keys (grep
  tests/test_issue_79_*, test_issue_193_*, test_unparseable_match_handling.py
  for key-set assertions).
- Frontend "source-reading" stubs read frontend/index.html, app-admin*.js and
  style.css with `_read` / `_fn_body` / `_css_blocks` / `_rule` (copy them
  from test_issue_208_player_popup_visualizations.py). Slice a tab's markup
  from its `data-admin-tab="..."` opening to the next `data-admin-tab=`.
  New CSS goes before the "GUIDED TOUR (issue #144)" section.
- Frontend "Node harness" stubs extract functions with `_fn_body` and run them
  in Node via `_node()` / `_run_node()` (skip when Node is missing). Re-add
  `async ` when pasting an extracted async function. Use a fake DOM like
  `_FAKE_DOM` in test_issue_208 or `_HARNESS` in test_issue_186.
- `_parsePlayerLines` in app-admin-players.js is also used by Add accolade's
  bulk Played box (which stays), so only the Mark champions paste box,
  `champPaste` and `champApplyPaste` go; the shared parser may stay.
- `.champ-id` roster inputs are already `type="text" inputmode="numeric"`.

Run with: cd backend && python -m pytest tests/test_issue_214_admin_enhancements.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import models  # noqa: F401  (registers every table for the db fixture)


# Every element id inside `<div data-admin-tab="settings">` in frontend/index.html,
# captured before the #214 change. The Settings regroup must keep all of them.
SETTINGS_TAB_IDS_BEFORE_214 = (
    "leagueManagementPanel", "leagueTable", "leagueTableBody", "leaguesStatus",
    "tagKeyInput", "tagLabelInput", "tagsBody", "tagsStatus",
    "newCodeInput", "newCodeAmount", "newCodeMaxUses", "newCodeExpires", "codesBody", "codesStatus",
    "weightsBody", "weightsStatus",
    "notifMsgInput", "notifStart", "notifEnd", "notifBody", "notifAdminStatus",
    "grantAmount", "grantStart", "grantEnd", "tokenGrantBody", "tokenGrantStatus",
    "scheduleRefreshBtn", "scheduleRefreshStatus",
    "recalculateBtn", "recalcStatus",
    "enrichBtn", "enrichStatus",
    "endSeasonLabel", "seasonArchivesBody", "seasonLifecycleStatus",
    "dbBackupsRetention", "createBackupBtn", "dbBackupsBody", "dbBackupsStatus",
    "demoModePanelContainer",
)

# Element ids of the three Twitch panels that move from User Management to the Twitch sub-tab.
TWITCH_PANEL_IDS_BEFORE_214 = (
    "twitchChannels", "twitchChannelsStatus",                       # Approved streamers (#175)
    "adminTwitchStatus", "twitchStatusStatus",                      # Twitch status (#180)
    "twitchMergesTable", "twitchMergesBody", "twitchMergesStatus",  # Twitch collection merges (#160)
)




import json
import re
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


@pytest.fixture
def db():
    """In-memory database on one shared connection so a TestClient's request
    thread sees the same data (overrides conftest's `db`)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _fe(name):
    return _read("frontend", name)


def _css_blocks(css, selector_re):
    """(selector, body) for every rule whose selector matches selector_re."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
            if re.search(selector_re, m.group(1))]


def _rule(css, selector):
    """Bodies of the rules whose selector list contains exactly `selector`."""
    return [body for sel, body in _css_blocks(css, re.escape(selector))
            if selector in [x.strip() for x in sel.split(",")]]


def _fn_body(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start)]


def _media_blocks(css, query):
    """Inner text of every `@media <query> { ... }` block (one level of nesting)."""
    out = []
    for m in re.finditer(r"@media\s*" + re.escape(query) + r"\s*\{", css):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.end():i - 1])
    return out


def _strip_media(css):
    """css without its @media blocks (the rules that apply at every width)."""
    out, i = [], 0
    for m in re.finditer(r"@media[^{]*\{", css):
        if m.start() < i:
            continue
        out.append(css[i:m.start()])
        depth, j = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        i = j
    out.append(css[i:])
    return "".join(out)


def _admin_tab(html, name):
    """Markup of one admin sub-tab, from its data-admin-tab opening to the next one."""
    start = html.index(f'data-admin-tab="{name}"')
    nxt = html.find("data-admin-tab=", start + 10)
    end = nxt if nxt != -1 else html.index("<!-- MVP Selection Modal -->", start)
    return html[start:end]


def _modal(html, modal_id):
    start = html.index(f'id="{modal_id}"')
    return html[start:html.index("<!-- ", start)]


def _input_tag(html, el_id):
    return re.search(r'<input[^>]*\bid="' + re.escape(el_id) + r'"[^>]*>', html).group(0)


def _node():
    return shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)


def _run_node(script):
    node = _node()
    if not node:
        pytest.skip("node not available")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _fn_source(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start) + 2]


# A small fake DOM: getElementById makes elements on demand, rows built with
# innerHTML get one child element per <td>/<th> in `cells`, and fetch answers
# from __routes (url prefix -> handler).
_FAKE_DOM = r"""
const __els = {};
const __all = {};
const __routes = [];
const __fetchCalls = [];
let __store = {};
let __storageThrows = false;
class El {
  constructor(id, tag) {
    this.id = id; this.tag = tag || null; this.attrs = {}; this.cls = new Set(); this.hidden = false;
    this.innerHTML = ""; this.textContent = ""; this.value = ""; this.checked = false; this.disabled = false;
    this.style = {}; this.dataset = {}; this.className = ""; this.children = []; this.scrolled = null;
    this.type = ""; this.listeners = {};
    const self = this;
    this.classList = {
      add: c => self.cls.add(c), remove: c => self.cls.delete(c), contains: c => self.cls.has(c),
      toggle: (c, on) => { if (on === undefined ? !self.cls.has(c) : on) self.cls.add(c); else self.cls.delete(c); },
    };
  }
  get cells() {
    if (!this._cells || this._cellsFor !== this.innerHTML) {
      const n = (this.innerHTML.match(/<t[dh][\s>]/g) || []).length;
      this._cells = Array.from({ length: n }, () => new El(null, "td"));
      this._cellsFor = this.innerHTML;
    }
    return this._cells;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  scrollIntoView(o) { this.scrolled = o || {}; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  click() { (this.listeners.click || []).forEach(fn => fn({})); }
  appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...c) { this.children = c; }
  querySelector() { return null; }
  closest() { return null; }
  remove() {}
}
const document = {
  getElementById: id => __els[id] || (__els[id] = new El(id)),
  createElement: tag => new El(null, tag),
  createTextNode: t => ({ textContent: t }),
  querySelectorAll: sel => __all[sel] || [],
  querySelector: () => null,
};
const window = { matchMedia: () => ({ matches: true }), addEventListener: () => {} };
const localStorage = {
  getItem: k => { if (__storageThrows) throw new Error("blocked"); return k in __store ? __store[k] : null; },
  setItem: (k, v) => { if (__storageThrows) throw new Error("blocked"); __store[k] = String(v); },
};
const sessionStorage = { getItem: () => null, setItem: () => {} };
function __resp(status, body) {
  return { ok: status < 400, status, json: async () => body, clone() { return this; } };
}
function fetch(url, opts) {
  __fetchCalls.push({ url, method: (opts && opts.method) || "GET", body: opts && opts.body });
  for (const [prefix, handler] of __routes) {
    if (url.startsWith(prefix)) return Promise.resolve(handler(url, opts));
  }
  return Promise.reject(new Error("no route for " + url));
}
const API = "";
const __status = {};
function setStatus(id, msg, ok = true) { __status[id] = { msg: msg, ok: ok }; }
let activeUserId = 1;
let activeIsAdmin = true;
function prefersReducedMotion() { return true; }
async function withBusy(btn, fn) { return fn(); }
async function adminFetch(url, opts) { return fetch(url, opts); }
function loadPlayerPool() {}
function loadSeasonAccolades() {}
function loadAccolades() { return Promise.resolve(); }
function refreshAccoladeIcons() {}
function openTeamModal() {}
const __tick = () => new Promise(r => setTimeout(r, 0));
"""


def _globals_helpers():
    g = _fe("app-globals.js")
    return "\n".join(_fn_source(g, n) for n in ("_escHtml", "_safeUrl", "teamLink"))


def _js(modules, body):
    """Run `body` (async; sets `out`) after loading the fake DOM, a few globals and the given modules."""
    src = _FAKE_DOM + _globals_helpers() + "\n" + "\n".join(_fe(m) for m in modules)
    script = src + "\nlet out = null;\n(async () => {\n" + body + \
        "\nconsole.log(JSON.stringify(out));\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });"
    return _run_node(script)


def _client(db, *routers):
    import rate_limit
    from starlette.middleware.sessions import SessionMiddleware
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key")
    app.state.limiter = rate_limit.limiter
    for r in routers:
        app.include_router(r)

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _user(db, username="admin", admin=True):
    from models import User
    u = User(username=username, email=f"{username}@example.com", password_hash="x", is_admin=admin)
    db.add(u)
    db.commit()
    return u


def _signed_in(db, client, admin=True, username=None):
    """Signs `client` in as a new user. The session cookie is a signed Starlette
    session, so the signed-in user comes from a get_current_user override;
    require_admin still checks is_admin fresh from the database."""
    from deps import get_current_user
    user = _user(db, username or ("admin" if admin else "viewer"), admin=admin)
    identity = {"user_id": user.id, "username": user.username, "is_admin": admin}
    client.app.dependency_overrides[get_current_user] = lambda: identity
    return user


# ---------------------------------------------------------------------------
# Story 1: Streamer Approvals Come First
# ---------------------------------------------------------------------------

def test_admin_tab_bar_twitch_subtab_after_user_management():
    """Source-reading: #admin-tab-bar has a Twitch button (data-tab="twitch") right after User Management, with a data-admin-tab="twitch" panel."""
    html = _fe("index.html")
    bar = html[html.index('id="admin-tab-bar"'):]
    bar = bar[:bar.index("</div>")]
    tabs = re.findall(r'<button class="admin-tab-btn" data-tab="([^"]+)"', bar)
    assert tabs[:2] == ["user-management", "twitch"]
    assert 'data-admin-tab="twitch"' in html
    assert html.index('data-admin-tab="user-management"') < html.index('data-admin-tab="twitch"') \
        < html.index('data-admin-tab="week-management"')


def test_twitch_subtab_panel_order_approved_status_merges():
    """Source-reading: the Twitch sub-tab holds Approved streamers first, then Twitch status, then Twitch collection merges (all TWITCH_PANEL_IDS_BEFORE_214 present, in that order)."""
    tab = _admin_tab(_fe("index.html"), "twitch")
    titles = re.findall(r'<h3 class="admin-panel-title">([^<]+)</h3>', tab)
    assert titles == ["Approved streamers", "Twitch status", "Twitch collection merges"]
    positions = [tab.index(f'id="{i}"') for i in TWITCH_PANEL_IDS_BEFORE_214]
    assert positions == sorted(positions)


def test_user_management_keeps_superseded_claims_and_drops_twitch_panels():
    """Source-reading: User Management still holds Superseded player id claims (playerIdClaimsTable) and no longer holds twitchChannels, adminTwitchStatus or twitchMergesTable."""
    html = _fe("index.html")
    users = _admin_tab(html, "user-management")
    assert 'id="playerIdClaimsTable"' in users and "Superseded player id claims" in users
    for el_id in TWITCH_PANEL_IDS_BEFORE_214:
        assert f'id="{el_id}"' not in users
        assert html.count(f'id="{el_id}"') == 1


_BADGE_IDS = ("adminTwitchPendingBadge", "adminTabPendingBadge")


def _badge_state(channels_handler):
    return _js(["app-admin.js"], f"""
        __routes.push(["/admin/twitch/channels", {channels_handler}]);
        await refreshTwitchPendingBadge();
        out = {{}};
        for (const id of {json.dumps(list(_BADGE_IDS))}) {{
          const el = document.getElementById(id);
          out[id] = {{ hidden: el.hidden, text: el.textContent, label: el.getAttribute("aria-label") }};
        }}
        out.calls = __fetchCalls.map(c => c.url);
    """)


def test_twitch_pending_badge_shows_count_and_aria_label():
    """Node harness: with 2 channels waiting, the Twitch sub-tab button and the top-level Admin tab button show a badge "2" with aria-label "2 streamers waiting for approval"."""
    html = _fe("index.html")
    assert re.search(r'data-tab="twitch">Twitch<span [^>]*id="adminTwitchPendingBadge"', html)
    assert re.search(r'id="tab-btn-admin"[^>]*>Admin<span [^>]*id="adminTabPendingBadge"', html)
    out = _badge_state('() => __resp(200, {pending: [{channel_id: "1"}, {channel_id: "2"}], approved: [], env: [], rejected: []})')
    for el_id in _BADGE_IDS:
        assert out[el_id] == {"hidden": False, "text": "2", "label": "2 streamers waiting for approval"}
    assert out["calls"] == ["/admin/twitch/channels"]


def test_twitch_pending_badge_hidden_when_zero():
    """Node harness: with no channels waiting (or a failed fetch), neither the Twitch sub-tab nor the Admin tab button shows a badge."""
    for handler in ('() => __resp(200, {pending: [], approved: [{channel_id: "9"}]})',
                    '() => __resp(403, {detail: "Admin access required"})',
                    '() => { throw new Error("offline"); }'):
        out = _badge_state(handler)
        for el_id in _BADGE_IDS:
            assert out[el_id]["hidden"] is True and out[el_id]["text"] == "" and out[el_id]["label"] is None
    html = _fe("index.html")
    for el_id in _BADGE_IDS:
        assert re.search(r'<span [^>]*id="' + el_id + r'"[^>]*\bhidden\b', html)


def test_twitch_pending_badge_fetched_on_admin_page_load():
    """Source-reading: the admin page-load path (app-admin.js) fetches the pending-approvals count from the existing channels endpoint when the user is an admin."""
    fn = _fn_body(_fe("app-admin.js"), "refreshTwitchPendingBadge")
    assert "activeIsAdmin" in fn and "`${API}/admin/twitch/channels`" in fn
    assert fn.index("activeIsAdmin") < fn.index("fetch(")
    auth = _fn_body(_fe("app-auth.js"), "applyAuthState")
    assert "refreshTwitchPendingBadge()" in auth
    # A signed-out or non-admin page makes no request.
    out = _js(["app-admin.js"], """
        activeIsAdmin = false;
        await refreshTwitchPendingBadge();
        out = __fetchCalls.length;
    """)
    assert out == 0


def test_twitch_pending_badge_refreshed_after_approve_and_reject():
    """Source-reading/Node harness: the Approve and Reject handlers in app-admin-users.js refresh the badge count after a successful call."""
    users = _fe("app-admin-users.js")
    action = _fn_body(users, "twitchChannelAction")
    assert action.index("if (!res.ok)") < action.index("loadTwitchChannels()")
    assert "setTwitchPendingBadge(pending.length)" in _fn_body(users, "_renderTwitchChannels")
    out = _js(["app-admin.js", "app-admin-users.js"], """
        globalThis.confirm = () => true;
        let pending = [{channel_id: "1", display_name: "A"}, {channel_id: "2", display_name: "B"}];
        __routes.push(["/admin/twitch/channels/", (url) => {
          const id = decodeURIComponent(url.split("/")[4]);
          pending = pending.filter(c => c.channel_id !== id);
          return __resp(200, {channel_id: id});
        }]);
        __routes.push(["/admin/twitch/channels", () => __resp(200, {pending, approved: [], rejected: []})]);
        await loadTwitchChannels();
        const before = document.getElementById("adminTabPendingBadge").textContent;
        await twitchChannelAction("1", "approve");
        await __tick();
        const afterApprove = document.getElementById("adminTabPendingBadge").textContent;
        await twitchChannelAction("2", "reject");
        await __tick();
        const el = document.getElementById("adminTwitchPendingBadge");
        out = {before, afterApprove, afterReject: el.textContent, hidden: el.hidden};
    """)
    assert out == {"before": "2", "afterApprove": "1", "afterReject": "", "hidden": True}


def test_twitch_channel_actions_still_require_reauth():
    """Source-reading: Approve, Reject and Remove still go through the password re-check (reauth) as before."""
    from deps import require_recent_reauth
    from routers import admin_twitch
    action = _fn_body(_fe("app-admin-users.js"), "twitchChannelAction")
    assert "adminFetch(`${API}/admin/twitch/channels/" in action
    for verb in ("approve", "reject", "remove"):
        path = "/admin/twitch/channels/{channel_id}/" + verb
        route = next(r for r in admin_twitch.router.routes if getattr(r, "path", "") == path)
        assert require_recent_reauth in [d.call for d in route.dependant.dependencies], verb


# ---------------------------------------------------------------------------
# Story 2: Ids Are Typed, and Names Show Before Saving
# ---------------------------------------------------------------------------

# --- GET /admin/players/lookup -------------------------------------------

@pytest.fixture
def lookup(db, monkeypatch):
    """(client signed in as admin, OpenDota call log); OpenDota knows ids 111 and 222."""
    from routers import admin_players
    admin_players.clear_lookup_cache()
    calls = []
    known = {111: "Glete", 222: "Miracle"}

    def fake_get_json(url, **kwargs):
        pid = int(url.rsplit("/", 1)[1])
        calls.append(pid)
        if pid in known:
            return {"profile": {"personaname": known[pid], "avatarfull": ""}}
        return {"rank_tier": None}  # OpenDota's answer for an unknown account: no profile

    monkeypatch.setattr(admin_players, "opendota_get_json", fake_get_json)
    client = _client(db, admin_players.router)
    _signed_in(db, client)
    yield client, calls
    admin_players.clear_lookup_cache()


def _pool(db, *players):
    from models import Player
    for pid, name, active in players:
        db.add(Player(id=pid, name=name, avatar_url="", is_active=active))
    db.commit()


def test_admin_players_lookup_pool_name_before_opendota(db, lookup):
    """Lookup returns {id, name, source: "pool", in_pool: true} for a pool player without calling OpenDota."""
    client, calls = lookup
    _pool(db, (111, "Glete in pool", True))
    res = client.get("/admin/players/lookup?ids=111")
    assert res.status_code == 200
    assert res.json() == [{"id": 111, "name": "Glete in pool", "source": "pool", "in_pool": True}]
    assert calls == []


def test_admin_players_lookup_opendota_name_for_unknown_id(db, lookup):
    """Lookup returns the OpenDota personaname with source "opendota" and in_pool false for an id not in the pool (OpenDota client mocked)."""
    client, calls = lookup
    res = client.get("/admin/players/lookup?ids=222")
    assert res.json() == [{"id": 222, "name": "Miracle", "source": "opendota", "in_pool": False}]
    assert calls == [222]


def test_admin_players_lookup_not_found_returns_null_name(db, lookup):
    """Lookup returns name null, source null, in_pool false when OpenDota has no player with the id."""
    client, _ = lookup
    res = client.get("/admin/players/lookup?ids=999")
    assert res.json() == [{"id": 999, "name": None, "source": None, "in_pool": False}]


def test_admin_players_lookup_preserves_request_order_for_mixed_ids(db, lookup):
    """Lookup of a mix of pool, OpenDota and unknown ids returns one entry per id in request order."""
    client, _ = lookup
    _pool(db, (333, "Pooled", True))
    res = client.get("/admin/players/lookup", params={"ids": "999, 333,222"})
    assert [(e["id"], e["source"]) for e in res.json()] == [(999, None), (333, "pool"), (222, "opendota")]


def test_admin_players_lookup_opendota_answers_cached(db, lookup):
    """A second lookup of the same non-pool id within 10 minutes does not call OpenDota again."""
    client, calls = lookup
    first = client.get("/admin/players/lookup?ids=222,999").json()
    second = client.get("/admin/players/lookup?ids=222,999").json()
    assert first == second
    assert calls == [222, 999]  # "not found" answers are cached too


def test_admin_players_lookup_cache_expires_after_ten_minutes(db, lookup, monkeypatch):
    """After the 10-minute cache lifetime (patched clock), the next lookup calls OpenDota again."""
    from routers import admin_players
    client, calls = lookup
    now = [1000.0]
    monkeypatch.setattr(admin_players, "_lookup_now", lambda: now[0])
    client.get("/admin/players/lookup?ids=222")
    now[0] += 599
    client.get("/admin/players/lookup?ids=222")
    assert calls == [222]
    now[0] += 2
    client.get("/admin/players/lookup?ids=222")
    assert calls == [222, 222]


def test_admin_players_lookup_non_admin_forbidden(db, monkeypatch):
    """A signed-in non-admin gets 403, and an anonymous request is rejected (401/403); OpenDota is not called."""
    from routers import admin_players
    calls = []
    monkeypatch.setattr(admin_players, "opendota_get_json", lambda url, **k: calls.append(url))
    client = _client(db, admin_players.router)
    assert client.get("/admin/players/lookup?ids=222").status_code in (401, 403)
    _signed_in(db, client, admin=False)
    assert client.get("/admin/players/lookup?ids=222").status_code == 403
    assert calls == []


def test_admin_players_lookup_non_numeric_id_422(db, lookup):
    """ids containing a non-numeric, zero or negative value answers 422."""
    client, calls = lookup
    for ids in ("12a3", "111,abc", "0", "-5", "1.5", "111,,222"):
        assert client.get("/admin/players/lookup", params={"ids": ids}).status_code == 422, ids
    assert calls == []


def test_admin_players_lookup_more_than_50_ids_422(db, lookup):
    """51 ids answers 422; 50 ids is accepted."""
    client, _ = lookup
    ids = [str(1000 + i) for i in range(51)]
    assert client.get("/admin/players/lookup", params={"ids": ",".join(ids)}).status_code == 422
    res = client.get("/admin/players/lookup", params={"ids": ",".join(ids[:50])})
    assert res.status_code == 200 and len(res.json()) == 50


def test_admin_players_lookup_empty_ids_422(db, lookup):
    """A missing or empty ids parameter answers 422."""
    client, _ = lookup
    assert client.get("/admin/players/lookup").status_code == 422
    assert client.get("/admin/players/lookup?ids=").status_code == 422
    assert client.get("/admin/players/lookup?ids=%20").status_code == 422


def test_admin_players_lookup_oversized_id_422(db, lookup):
    """An id above 2**63-1 answers 422, not a 500 (lessons-learned: bound ids)."""
    client, calls = lookup
    assert client.get(f"/admin/players/lookup?ids={2**63}").status_code == 422
    assert client.get(f"/admin/players/lookup?ids={'9' * 40}").status_code == 422
    assert calls == []


# --- Spinner-free id inputs ---------------------------------------------

def _assert_text_numeric(tag):
    assert 'type="text"' in tag and 'inputmode="numeric"' in tag, tag
    assert 'type="number"' not in tag, tag


def test_add_player_id_input_is_text_numeric():
    """Source-reading: #addPlayerIdInput is type="text" with inputmode="numeric" and a digits-only pattern, not type="number"."""
    tag = _input_tag(_fe("index.html"), "addPlayerIdInput")
    _assert_text_numeric(tag)
    assert 'pattern="[0-9]*"' in tag


def test_bulk_add_ids_input_has_no_number_type():
    """Source-reading: #bulkAddIdsInput is a text input (no type="number")."""
    tag = _input_tag(_fe("index.html"), "bulkAddIdsInput")
    assert 'type="text"' in tag and 'type="number"' not in tag


def test_champion_roster_id_input_is_text_numeric():
    """Source-reading: `_champRowHtml` renders the id input as type="text" inputmode="numeric", never type="number"."""
    row = _fn_body(_fe("app-admin-players.js"), "_champRowHtml")
    _assert_text_numeric(re.search(r'<input class="champ-id"[^>]*>', row).group(0))
    assert 'type="number"' not in row


def test_add_accolade_player_id_input_is_text_numeric():
    """Source-reading: #accPlayerId is type="text" inputmode="numeric", not type="number"."""
    _assert_text_numeric(_input_tag(_fe("index.html"), "accPlayerId"))


def test_add_accolade_value_input_is_decimal_without_spinner():
    """Source-reading: #accValue uses inputmode="decimal" and is not type="number"."""
    tag = _input_tag(_fe("index.html"), "accValue")
    assert 'inputmode="decimal"' in tag and 'type="number"' not in tag


def test_end_season_add_by_id_inputs_are_text_numeric():
    """Source-reading: #endSeasonAdd_div1 and #endSeasonAdd_div2 are type="text" inputmode="numeric", not type="number"."""
    html = _fe("index.html")
    for div in ("div1", "div2"):
        _assert_text_numeric(_input_tag(html, f"endSeasonAdd_{div}"))
    # No OpenDota id input anywhere in the admin modals is a number spinner.
    # No id input anywhere is a number spinner (the design rule covers league ids too).
    for m in re.finditer(r'<input[^>]*type="number"[^>]*>', html):
        assert not re.search(r'id="[^"]*(PlayerId|IdInput|Add_div)', m.group(0)), m.group(0)


def test_id_inputs_reject_non_digits_with_message():
    """Node harness: entering "12a3" in Add player (and Add accolade) shows a digits-only message and sends no request."""
    out = _js(["app-admin-players.js"], """
        document.getElementById("addPlayerIdInput").value = "12a3";
        await addPlayer();
        const add = __status.addPlayerStatus;
        await previewAddPlayer();
        const preview = document.getElementById("addPlayerPreview").textContent;
        document.getElementById("accSeason").value = "Season 15";
        document.getElementById("accKind").value = "most_points";
        document.getElementById("accPlayerId").value = "12a3";
        document.getElementById("accPlayerName").value = "Glete";
        await saveAccolade();
        out = {add, preview, acc: __status.accStatus, calls: __fetchCalls.length};
    """)
    assert out["add"] == {"msg": "OpenDota ids are digits only", "ok": False}
    assert out["preview"] == "OpenDota ids are digits only"
    assert out["acc"] == {"msg": "OpenDota ids are digits only", "ok": False}
    assert out["calls"] == 0


# --- Add player preview ---------------------------------------------------

def _preview(entry_js, key="Enter"):
    return _js(["app-admin-players.js"], f"""
        __routes.push(["/admin/players/lookup", () => __resp(200, [{entry_js}])]);
        document.getElementById("addPlayerIdInput").value = " 111 ";
        await previewAddPlayer();
        const el = document.getElementById("addPlayerPreview");
        out = {{text: el.textContent, cls: el.className, calls: __fetchCalls.map(c => c.url)}};
    """)


def test_add_player_preview_not_in_pool_on_blur():
    """Node harness: blur (or Enter) on #addPlayerIdInput calls /admin/players/lookup and shows "Glete · not in the pool"."""
    tag = _input_tag(_fe("index.html"), "addPlayerIdInput")
    assert 'onblur="previewAddPlayer()"' in tag and "event.key==='Enter'" in tag
    out = _preview('{id: 111, name: "Glete", source: "opendota", in_pool: false}')
    assert out["text"] == "Glete · not in the pool"
    assert out["calls"] == ["/admin/players/lookup?ids=111"]


def test_add_player_preview_already_in_pool():
    """Node harness: a lookup with in_pool true shows the name and "already in the pool"."""
    out = _preview('{id: 111, name: "Glete", source: "pool", in_pool: true}')
    assert out["text"] == "Glete · already in the pool"


def test_add_player_preview_not_found():
    """Node harness: a lookup with name null shows "No OpenDota player with this id"."""
    out = _preview('{id: 111, name: null, source: null, in_pool: false}')
    assert out["text"] == "No OpenDota player with this id"
    assert "id-preview-err" in out["cls"]


def test_add_player_confirm_still_posts_admin_players():
    """Source-reading/Node harness: Confirm still POSTs /admin/players as today, whatever the preview says."""
    out = _js(["app-admin-players.js"], """
        __routes.push(["/admin/players/lookup", () => __resp(200, [{id: 111, name: null, source: null, in_pool: false}])]);
        __routes.push(["/admin/players", () => __resp(200, {id: 111, name: "Glete"})]);
        document.getElementById("addPlayerIdInput").value = "111";
        await previewAddPlayer();
        await addPlayer();
        out = {calls: __fetchCalls.filter(c => c.method === "POST").map(c => [c.url, c.body]), status: __status.addPlayerStatus};
    """)
    assert out["calls"] == [["/admin/players", json.dumps({"player_id": 111}, separators=(",", ":"))]]
    assert out["status"] == {"msg": "Added: Glete (111)", "ok": True}
    html = _fe("index.html")
    assert 'id="addPlayerConfirmBtn"' in html and 'onclick="addPlayer()"' in html


# --- Bulk add preview -----------------------------------------------------

_BULK_LOOKUP = """__routes.push(["/admin/players/lookup", () => __resp(200, [
    {id: 1, name: "New One", source: "opendota", in_pool: false},
    {id: 2, name: "Pooled", source: "pool", in_pool: true},
    {id: 3, name: null, source: null, in_pool: false},
    {id: 4, name: "New Two", source: "opendota", in_pool: false},
])]);"""


def _stream_route(lines):
    return """__routes.push(["/admin/players/bulk", (url, opts) => {
        const chunks = %s.map(l => new TextEncoder().encode(JSON.stringify(l) + "\\n"));
        return { ok: true, status: 200, body: { getReader: () => ({
          read: async () => chunks.length ? { done: false, value: chunks.shift() } : { done: true } }) } };
    }]);""" % json.dumps(lines)


def test_bulk_add_preview_lists_new_in_pool_and_not_found():
    """Node harness: after ids are entered, the preview list shows each id with its name and status new / already in pool / not found."""
    out = _js(["app-admin-players.js"], _BULK_LOOKUP + """
        document.getElementById("bulkAddIdsInput").value = "1, 2\\n3 4,1";
        await previewBulkAdd();
        const list = document.getElementById("bulkAddPreviewList");
        out = {html: list.innerHTML, hidden: list.hidden, url: __fetchCalls[0].url};
    """)
    assert out["url"] == "/admin/players/lookup?ids=1,2,3,4"  # split on commas/spaces/lines, each id once
    assert out["hidden"] is False
    rows = re.findall(r'<li class="bulk-preview-row bulk-preview-(\w+)"><span class="bulk-preview-id">(\d+)</span>'
                      r'<span class="bulk-preview-name">([^<]*)</span><span class="bulk-preview-status">([^<]*)</span></li>',
                      out["html"])
    assert rows == [("new", "1", "New One", "new"), ("in_pool", "2", "Pooled", "already in pool"),
                    ("not_found", "3", "—", "not found"), ("new", "4", "New Two", "new")]


def test_bulk_add_confirm_submits_only_new_ids_with_count_label():
    """Node harness: the confirm button reads "Add N players" (N = new ids) and POST /admin/players/bulk receives only the new ids."""
    out = _js(["app-admin-players.js"], _BULK_LOOKUP + _stream_route([
        {"id": 1, "status": "added", "index": 1, "total": 2},
        {"id": 4, "status": "added", "index": 2, "total": 2},
        {"done": True, "added": 2, "skipped": []}]) + """
        document.getElementById("bulkAddIdsInput").value = "1,2,3,4";
        await previewBulkAdd();
        const btn = document.getElementById("bulkAddConfirmBtn");
        const label = btn.textContent, disabled = btn.disabled;
        await bulkAddPlayers();
        const post = __fetchCalls.find(c => c.url === "/admin/players/bulk");
        out = {label, disabled, body: JSON.parse(post.body), status: __status.bulkAddPlayersStatus};
    """)
    assert out["label"] == "Add 2 players" and out["disabled"] is False
    assert out["body"] == {"player_ids": "1,4"}
    assert out["status"] == {"msg": "Added: 2. Skipped: 0.", "ok": True}
    html = _fe("index.html")
    assert re.search(r'id="bulkAddConfirmBtn"[^>]*onclick="bulkAddPlayers\(\)"', html)


def test_bulk_add_confirm_disabled_when_no_new_ids():
    """Node harness: when every id is already in the pool or not found, nothing is submitted (button disabled or a message)."""
    out = _js(["app-admin-players.js"], """
        __routes.push(["/admin/players/lookup", () => __resp(200, [
          {id: 2, name: "Pooled", source: "pool", in_pool: true},
          {id: 3, name: null, source: null, in_pool: false}])]);
        document.getElementById("bulkAddIdsInput").value = "2,3";
        await previewBulkAdd();
        const btn = document.getElementById("bulkAddConfirmBtn");
        const state = {label: btn.textContent, disabled: btn.disabled, status: __status.bulkAddPlayersStatus};
        await bulkAddPlayers();
        state.posted = __fetchCalls.some(c => c.url === "/admin/players/bulk");
        out = state;
    """)
    assert out["label"] == "Add 0 players" and out["disabled"] is True
    assert out["status"] == {"msg": "No new players to add", "ok": False}
    assert out["posted"] is False


def test_bulk_add_progress_panel_still_runs():
    """Source-reading: bulk add still drives #bulkAddProgressPanel / #bulkAddProgressList from the streaming response."""
    js = _fe("app-admin-players.js")
    run = _fn_body(js, "bulkAddPlayers")
    assert 'getElementById("bulkAddProgressPanel")' in run and "res.body.getReader()" in run
    assert "renderBulkAddProgress(evt)" in run
    assert 'getElementById("bulkAddProgressList")' in _fn_body(js, "renderBulkAddProgress")
    html = _fe("index.html")
    assert 'id="bulkAddProgressPanel"' in html and 'id="bulkAddProgressList"' in html
    out = _js(["app-admin-players.js"], """
        __routes.push(["/admin/players/lookup", () => __resp(200, [{id: 1, name: "A", source: "opendota", in_pool: false}])]);
    """ + _stream_route([{"id": 1, "status": "added", "index": 1, "total": 1},
                         {"done": True, "added": 1, "skipped": []}]) + """
        document.getElementById("bulkAddIdsInput").value = "1";
        await previewBulkAdd();
        await bulkAddPlayers();
        out = {panelHidden: document.getElementById("bulkAddProgressPanel").cls.has("hidden"),
               counter: document.getElementById("bulkAddProgressCounter").textContent};
    """)
    assert out == {"panelHidden": False, "counter": "1 of 1 processed"}


# ---------------------------------------------------------------------------
# Story 3: Mark Champions and Add Accolade Are Simpler
# ---------------------------------------------------------------------------

def test_mark_champions_paste_box_removed():
    """Source-reading: index.html has no #champPaste and no "Add pasted players" button; app-admin-players.js has no champPaste / champApplyPaste."""
    html = _fe("index.html")
    js = _fe("app-admin-players.js")
    assert 'id="champPaste"' not in html and "Add pasted players" not in html
    assert "champPaste" not in js and "champApplyPaste" not in js
    assert ".champ-paste" not in _fe("style.css")


def test_mark_champions_add_player_row_button_stays():
    """Source-reading: the Mark champions modal still has "+ Add player" calling champAddRow()."""
    modal = _modal(_fe("index.html"), "markChampionsModal")
    assert 'onclick="champAddRow()">+ Add player</button>' in modal
    assert "function champAddRow(" in _fe("app-admin-players.js")


def _px(value):
    m = re.search(r"min\((\d+)px", value) or re.search(r"(\d+)px", value)
    return int(m.group(1))


def test_mark_champions_roster_row_one_line_layout():
    """Source-reading (style.css): .champ-row lays out id (fixed width), name (remaining width, min ~12ch) and Remove on one line; the modal is at least 640px wide."""
    top = _strip_media(_fe("style.css"))
    row = " ".join(_rule(top, ".champ-row"))
    # id: fixed width · name: the rest, never under 12ch · Remove: its own width
    assert re.search(r"grid-template-columns:\s*\d+(?:ch|em|px)\s+minmax\(12ch,\s*1fr\)\s+auto;", row)
    modal = " ".join(_rule(top, ".champ-modal"))
    width = re.search(r"(?<!-)width:\s*([^;]+);", modal).group(1)
    assert _px(width) >= 640
    assert "max-width: none" in modal or _px(re.search(r"max-width:\s*([^;]+);", modal).group(1)) >= 640
    assert 'class="modal champ-modal"' in _modal(_fe("index.html"), "markChampionsModal")


def test_mark_champions_roster_row_stacks_below_640px():
    """Source-reading (style.css): below 640px a media query stacks the .champ-row fields."""
    blocks = _media_blocks(_fe("style.css"), "(max-width: 640px)")
    stacked = [b for blk in blocks for b in _rule(blk, ".champ-row")]
    assert any(re.search(r"grid-template-columns:\s*1fr;", b) for b in stacked)


def test_add_accolade_bulk_played_box_stays():
    """Source-reading: #accBulk (bulk Played box) still exists and still feeds `_parsePlayerLines`."""
    html = _fe("index.html")
    js = _fe("app-admin-players.js")
    assert 'id="accBulk"' in _modal(html, "addAccoladeModal")
    assert '_parsePlayerLines(document.getElementById("accBulk").value)' in _fn_body(js, "saveAccolade")
    assert "function _parsePlayerLines(" in js


# ---------------------------------------------------------------------------
# Story 4: Matches Are Organised for Setting MVPs
# ---------------------------------------------------------------------------

# --- GET /admin/matches ---------------------------------------------------

_KEYS_BEFORE_214 = {
    "match_id", "league_id", "radiant_team_id", "dire_team_id", "team1", "team2", "start_time",
    "mvp_player_name", "mvp_player_id", "vod_url", "parse_status", "excluded_from_scoring",
    "live_first_seen_at", "ingested_at", "mvp_confirmed_at", "week_override_id",
    "scoring_week_id", "scoring_week_label", "scoring_week_source", "time_week_id", "time_week_label",
}
_SERIES_KEYS = {"series_key", "series_team1_id", "series_team2_id", "division", "league_name", "stream_url"}


def _seed_matches(db):
    """Reds (10) v Blues (20) in Div 1: game 1 Reds radiant, game 2 Blues radiant; plus
    match 503 (Golds v Greens, Lower league) that the feed doesn't know."""
    from models import League, Match, Player, Team, TwitchMVP
    db.add_all([League(id=1, name="Kanaliiga Season 16", is_monitored=True),
                League(id=2, name="Kanaliiga Season 16 Lower", is_monitored=True)])
    db.add_all([Team(id=10, name="Reds"), Team(id=20, name="Blues"),
                Team(id=30, name="Golds"), Team(id=40, name="Greens")])
    db.add_all([
        Match(match_id=501, radiant_team_id=10, dire_team_id=20, league_id=1, start_time=1_000, vod_url="https://v/1"),
        Match(match_id=502, radiant_team_id=20, dire_team_id=10, league_id=1, start_time=4_000, parse_status="parsed"),
        Match(match_id=503, radiant_team_id=30, dire_team_id=40, league_id=2, start_time=9_000),
    ])
    db.add(Player(id=7, name="Glete", avatar_url="", is_active=True))
    db.commit()
    db.add(TwitchMVP(match_id=501, player_id=7, channel_id="admin", selected_at=1))
    db.commit()


def _feed(*series_by_div):
    return {"weeks": [{"label": "Week 1", "div1": list(series_by_div[0]), "div2": list(series_by_div[1])}],
            "extra_results": []}


_REDS_BLUES = {"team1": "Reds", "team2": "Blues", "team1_id": 10, "team2_id": 20,
               "stream_url": "https://twitch.tv/kanaliiga",
               "series_result": {"match_ids": [501, 502]}}


@pytest.fixture
def feed(monkeypatch):
    """Patches schedule.get_schedule; returns the call log. Set `.data` to change the feed."""
    import schedule

    class Feed:
        data = _feed([_REDS_BLUES], [])
        calls = 0

    def fake(db):
        Feed.calls += 1
        if isinstance(Feed.data, Exception):
            raise Feed.data
        return Feed.data

    monkeypatch.setattr(schedule, "get_schedule", fake)
    return Feed


def _rows(db):
    from routers import admin_matches
    return {r["match_id"]: r for r in admin_matches.list_matches(db=db, _={})}


def test_admin_matches_series_fields_present(db, feed):
    """GET /admin/matches returns series_key, series_team1_id, series_team2_id, division, league_name and stream_url for a match in the (mocked) schedule feed."""
    from routers import admin_matches
    _seed_matches(db)
    client = _client(db, admin_matches.router)
    _signed_in(db, client)
    res = client.get("/admin/matches")
    assert res.status_code == 200
    row = {r["match_id"]: r for r in res.json()}[501]
    assert _SERIES_KEYS <= set(row)
    assert row["series_key"]
    assert (row["series_team1_id"], row["series_team2_id"]) == (10, 20)
    assert row["division"] == "div1"
    assert row["league_name"] == "Kanaliiga Season 16"
    assert row["stream_url"] == "https://twitch.tv/kanaliiga"


def test_admin_matches_team_order_stable_across_series_games(db, feed):
    """Two games of one series with radiant/dire swapped both report the same series_team1_id / series_team2_id (feed order)."""
    _seed_matches(db)
    rows = _rows(db)
    assert (rows[501]["radiant_team_id"], rows[502]["radiant_team_id"]) == (10, 20)
    for mid in (501, 502):
        assert (rows[mid]["series_team1_id"], rows[mid]["series_team2_id"]) == (10, 20)
    assert rows[501]["series_key"] == rows[502]["series_key"]


def test_admin_matches_division_from_series_list_or_league_name(db, feed):
    """division is "div1"/"div2" from the series' division list, falling back to `accolades.league_division(league name)`; league_name is the league's name."""
    _seed_matches(db)
    # The feed lists Reds v Blues under div2, although their league name says Div 1.
    feed.data = _feed([], [_REDS_BLUES])
    rows = _rows(db)
    assert rows[501]["division"] == "div2" and rows[501]["league_name"] == "Kanaliiga Season 16"
    # Match 503 isn't in the feed: its league's name ("... Lower") gives Div 2.
    assert rows[503]["division"] == "div2" and rows[503]["league_name"] == "Kanaliiga Season 16 Lower"
    feed.data = _feed([], [])
    assert _rows(db)[501]["division"] == "div1"


def test_admin_matches_series_fields_null_outside_feed(db, feed):
    """A match not in any series of the mocked feed has series_key, series_team1_id, series_team2_id and stream_url null."""
    _seed_matches(db)
    row = _rows(db)[503]
    for key in ("series_key", "series_team1_id", "series_team2_id", "stream_url"):
        assert row[key] is None, key
    # Feed down: the endpoint still answers, with the series fields null.
    feed.data = RuntimeError("feed down")
    rows = _rows(db)
    assert rows[501]["series_key"] is None and rows[501]["stream_url"] is None
    assert rows[501]["division"] == "div1"


def test_admin_matches_existing_fields_unchanged(db, feed):
    """Every key GET /admin/matches returned before #214 is still present with the same value."""
    _seed_matches(db)
    with_feed = _rows(db)
    feed.data = {"weeks": [], "extra_results": []}
    without = _rows(db)
    for mid, row in with_feed.items():
        assert _KEYS_BEFORE_214 <= set(row)
        # Issue 224 added source, added_by and added_at (matches added outside the league).
        assert set(row) == _KEYS_BEFORE_214 | _SERIES_KEYS | {"source", "added_by", "added_at"}
        assert {k: row[k] for k in _KEYS_BEFORE_214} == {k: without[mid][k] for k in _KEYS_BEFORE_214}
    r = with_feed[501]
    assert (r["team1"], r["team2"], r["league_id"], r["vod_url"]) == ("Reds", "Blues", 1, "https://v/1")
    assert (r["mvp_player_name"], r["mvp_player_id"]) == ("Glete", 7)
    assert list(with_feed) == [503, 502, 501]  # newest first, as before


def test_admin_matches_calls_get_schedule_once(db, feed):
    """One request makes a single `get_schedule` pass, however many matches there are."""
    _seed_matches(db)
    _rows(db)
    assert feed.calls == 1


def test_admin_matches_non_admin_forbidden(db, feed):
    """A non-admin still gets 403 from GET /admin/matches."""
    from routers import admin_matches
    client = _client(db, admin_matches.router)
    _signed_in(db, client, admin=False)
    assert client.get("/admin/matches").status_code == 403
    assert feed.calls == 0


# --- Matches table (frontend) ---------------------------------------------

def _m(mid, start, *, key="s1", t1=10, t2=20, radiant=10, mvp=None, div="div1", parse="parsed",
       stream="https://twitch.tv/kana", week="Week 4"):
    names = {10: "Reds", 20: "Blues", 30: "Golds", 40: "Greens"}
    dire = t2 if radiant == t1 else t1
    return {"match_id": mid, "league_id": 1, "league_name": "Kanaliiga Season 16",
            "radiant_team_id": radiant, "dire_team_id": dire, "team1": names[radiant], "team2": names[dire],
            "start_time": start, "mvp_player_id": mvp, "mvp_player_name": "Glete" if mvp else None,
            "vod_url": None, "parse_status": parse, "excluded_from_scoring": False,
            "live_first_seen_at": None, "ingested_at": None, "mvp_confirmed_at": None,
            "week_override_id": None, "scoring_week_id": 4, "scoring_week_label": week,
            "scoring_week_source": "time", "time_week_id": 4, "time_week_label": week,
            "series_key": key, "series_team1_id": t1 if key else None, "series_team2_id": t2 if key else None,
            "division": div, "stream_url": stream if key else None}


def _render(rows, setup=""):
    """Renders the Matches table for `rows`; returns the tbody's rows as
    {cls, html, cells:[text of appended controls]} plus the empty-state text."""
    return _js(["app-admin-matches.js"], f"""
        _adminMatchesRows = {json.dumps(rows)};
        {setup}
        renderAdminMatches();
        const body = document.getElementById("adminMatchesBody");
        out = {{
          rows: body.children.map(r => ({{cls: r.className, html: r.innerHTML, hidden: r.hidden,
                 controls: r.cells.map(c => c.children.map(x => x.textContent || x.className || ""))}})),
          empty: body.children.length ? null : body.innerHTML,
        }};
    """)


def _game_rows(out):
    return [r for r in out["rows"] if r["cls"] == "admin-match-row"]


def test_admin_matches_grouped_by_series_newest_first():
    """Node harness: rows render under series header rows (Team A vs Team B · Div · week · stream link), newest series first."""
    rows = [_m(3, 9000, key="s2", t1=30, t2=40, radiant=30, div="div2", week="Week 5"),
            _m(2, 4000, radiant=20), _m(1, 1000)]
    out = _render(rows)
    kinds = [r["cls"] for r in out["rows"] if r["cls"] != "admin-match-more"]
    assert kinds == ["admin-series-row", "admin-match-row", "admin-series-row", "admin-match-row", "admin-match-row"]
    heads = [r["html"] for r in out["rows"] if r["cls"] == "admin-series-row"]
    assert heads[0].startswith('<th colspan="13" scope="colgroup">Golds vs Greens · Div 2 · Week 5 · ')
    assert heads[1].startswith('<th colspan="13" scope="colgroup">Reds vs Blues · Div 1 · Week 4 · ')
    assert 'href="https://twitch.tv/kana"' in heads[1]
    games = [re.search(r"matches/(\d+)", r["html"]).group(1) for r in _game_rows(out)]
    assert games == ["3", "1", "2"]  # a series' games in play order


def test_admin_matches_unscheduled_group_not_in_the_schedule():
    """Node harness: matches with series_key null render under a "Not in the schedule" group."""
    out = _render([_m(9, 9000, key=None), _m(2, 4000), _m(1, 1000)])
    kinds = [(r["cls"], r["html"]) for r in out["rows"] if r["cls"] != "admin-match-more"]
    assert kinds[-2][1] == '<th colspan="13" scope="colgroup">Not in the schedule</th>'
    assert "matches/9" in kinds[-1][1]
    assert sum(1 for c, _ in kinds if c == "admin-series-row") == 2


def test_admin_matches_games_use_series_team_order():
    """Node harness: each game shows the series' team 1 vs team 2 (series_team1_id/series_team2_id), not radiant/dire."""
    out = _render([_m(2, 4000, radiant=20), _m(1, 1000, radiant=10)])
    for r in _game_rows(out):
        teams = re.search(r'<td class="admin-match-teams">(.*?)</td>', r["html"], re.S).group(1)
        assert teams.index("openTeamModal(10)") < teams.index("openTeamModal(20)")
        assert teams.index(">Reds<") < teams.index(">vs<") < teams.index(">Blues<")


def test_admin_matches_column_order():
    """Source-reading/Node harness: columns are Match id (OpenDota link), Teams, League, Start, MVP (with Set MVP), Stream, then Week, Scoring, Parse and the timing columns."""
    html = _fe("index.html")
    head = re.search(r'<table id="admin-matches-table">\s*<thead><tr>(.*?)</tr></thead>', html).group(1)
    assert re.findall(r"<th>([^<]*)</th>", head) == [
        "Match", "Teams", "League", "Start", "MVP", "Stream", "Week", "Scoring", "Parse",
        "Live seen", "Stats in", "MVP picked", "More"]
    out = _render([_m(1, 1000)])
    game = _game_rows(out)[0]
    cells = re.findall(r"<td[^>]*>(.*?)</td>", game["html"], re.S)
    assert len(cells) == 13
    assert "https://www.opendota.com/matches/1" in cells[0]
    assert "Reds" in cells[1] and "Kanaliiga Season 16" in cells[2] and "Div 1" in cells[2]
    assert 'class="mvp-cell"' in cells[4] and "Stream ↗" in cells[5]
    controls = game["controls"]
    assert controls[4] == ["Set MVP"]
    assert controls[6] and controls[7] == ["admin-scoring-grid"] and controls[8] and controls[12] == ["More"]


def test_admin_matches_mvp_missing_filter_default_on_when_any_missing():
    """Node harness: the MVP missing filter is checked by default when any match lacks an MVP, and shows only those matches."""
    out = _js(["app-admin-matches.js"], f"""
        const rows = {json.dumps([_m(2, 4000, mvp=None), _m(1, 1000, mvp=7)])};
        __routes.push(["/admin/matches/out-of-week", () => __resp(200, [])]);
        __routes.push(["/admin/matches", () => __resp(200, rows)]);
        __routes.push(["/admin/weeks", () => __resp(200, [])]);
        await loadAdminMatches();
        const body = document.getElementById("adminMatchesBody");
        out = {{checked: document.getElementById("adminMatchesMvpMissing").checked,
               games: body.children.filter(r => r.className === "admin-match-row").map(r => /matches\\/(\\d+)/.exec(r.innerHTML)[1]),
               count: document.getElementById("adminMatchesCount").textContent}};
    """)
    assert out == {"checked": True, "games": ["2"], "count": "1 of 2 matches"}
    assert re.search(r'<input type="checkbox" id="adminMatchesMvpMissing"[^>]*>MVP missing</label>', _fe("index.html"))


def test_admin_matches_mvp_missing_filter_default_off_when_none_missing():
    """Node harness: with every match having an MVP, the MVP missing filter starts unchecked and all matches show."""
    out = _js(["app-admin-matches.js"], f"""
        const rows = {json.dumps([_m(2, 4000, mvp=7), _m(1, 1000, mvp=7)])};
        __routes.push(["/admin/matches/out-of-week", () => __resp(200, [])]);
        __routes.push(["/admin/matches", () => __resp(200, rows)]);
        __routes.push(["/admin/weeks", () => __resp(200, [])]);
        await loadAdminMatches();
        const body = document.getElementById("adminMatchesBody");
        out = {{checked: document.getElementById("adminMatchesMvpMissing").checked,
               games: body.children.filter(r => r.className === "admin-match-row").length}};
    """)
    assert out == {"checked": False, "games": 2}


def test_admin_matches_league_filter_all_div1_div2():
    """Node harness: the League filter offers All, Div 1 and Div 2 and narrows rows by division."""
    html = _fe("index.html")
    select = html[html.index('id="adminMatchesLeague"'):]
    select = select[:select.index("</select>")]
    assert re.findall(r'<option value="([^"]*)">([^<]+)</option>', select) == [("", "All"), ("div1", "Div 1"), ("div2", "Div 2")]
    rows = [_m(1, 1000, div="div1"), _m(2, 2000, key="s2", div="div2"), _m(3, 3000, key=None, div=None)]
    out = _js(["app-admin-matches.js"], f"""
        const rows = {json.dumps(rows)};
        const pick = v => filterAdminMatches(rows, {{mvpMissing: false, league: v, unparseable: false}}).map(m => m.match_id);
        document.getElementById("adminMatchesLeague").value = "div2";
        out = {{all: pick(""), div1: pick("div1"), div2: pick("div2"), fromDom: adminMatchesFilters().league}};
    """)
    assert out == {"all": [1, 2, 3], "div1": [1], "div2": [2], "fromDom": "div2"}


def test_admin_matches_filters_combine():
    """Node harness: MVP missing + Div 2 + Unparseable together show only matches meeting all three (adminMatchesUnparseableOnly kept)."""
    rows = [_m(1, 1000, div="div2", parse="unparseable", mvp=None),
            _m(2, 2000, div="div2", parse="unparseable", mvp=7),
            _m(3, 3000, div="div1", parse="unparseable", mvp=None),
            _m(4, 4000, div="div2", parse="parsed", mvp=None)]
    out = _render(rows, setup="""
        document.getElementById("adminMatchesMvpMissing").checked = true;
        document.getElementById("adminMatchesLeague").value = "div2";
        document.getElementById("adminMatchesUnparseableOnly").checked = true;
    """)
    assert [re.search(r"matches/(\d+)", r["html"]).group(1) for r in _game_rows(out)] == ["1"]
    assert 'id="adminMatchesUnparseableOnly"' in _fe("index.html")
    assert 'getElementById(\'adminMatchesUnparseableOnly\')' in _fn_body(_fe("app-admin-matches.js"), "adminMatchesFilters")


def test_admin_matches_empty_state_names_active_filters():
    """Node harness: when no match passes the filters, the empty state names the active filters."""
    out = _render([_m(1, 1000, mvp=7)], setup="""
        document.getElementById("adminMatchesMvpMissing").checked = true;
        document.getElementById("adminMatchesLeague").value = "div2";
    """)
    assert out["empty"] == "<tr><td colspan='13' class='admin-matches-empty'>No matches for the filters: MVP missing, Div 2</td></tr>"
    assert "No matches</td>" in _render([])["empty"]


def test_admin_matches_stream_link_new_tab_or_dash():
    """Node harness: the Stream cell links to stream_url with target="_blank" rel="noopener", and shows "—" when stream_url is null."""
    out = _js(["app-admin-matches.js"], """
        out = [_streamLinkHtml("https://twitch.tv/kana"), _streamLinkHtml(null), _streamLinkHtml("javascript:alert(1)")];
    """)
    assert out[0] == '<a class="stream-link" href="https://twitch.tv/kana" target="_blank" rel="noopener noreferrer">Stream ↗</a>'
    assert out[1] == "—" and out[2] == "—"
    game = _game_rows(_render([_m(1, 1000, key=None)]))[0]
    assert re.findall(r"<td[^>]*>(.*?)</td>", game["html"], re.S)[5] == "—"


def test_admin_matches_vod_editor_under_more_details():
    """Source-reading/Node harness: the VOD link editor (PATCH /admin/matches/{id}/vod) is inside each match's More details, not a top-level column."""
    js = _fe("app-admin-matches.js")
    assert "_buildVodCell(m.match_id, m.vod_url)" in _fn_body(js, "_buildMoreDetails")
    assert "_buildVodCell" not in _fn_body(js, "renderAdminMatches")
    assert "/vod`" in _fn_body(js, "saveMatchVod")
    assert "<th>VOD</th>" not in _fe("index.html")
    out = _render([_m(1, 1000)])
    more = [r for r in out["rows"] if r["cls"] == "admin-match-more"]
    assert len(more) == 1 and more[0]["hidden"] is True
    assert more[0]["controls"] == [["admin-match-details"]]


def test_admin_matches_scoring_checkboxes_grid():
    """Source-reading: scoring checkboxes render with labels in a fixed two-column grid class defined in style.css."""
    cell = _fn_body(_fe("app-admin-matches.js"), "_buildScoringCell")
    assert "wrap.className = 'admin-scoring-grid'" in cell
    assert "document.createElement('label')" in cell and "'Unparseable'" in cell and "'Not scored'" in cell
    grid = " ".join(_rule(_fe("style.css"), ".admin-scoring-grid"))
    assert "display: grid" in grid and re.search(r"grid-template-columns:\s*auto auto;", grid)
    assert "display: contents" in " ".join(_rule(_fe("style.css"), ".admin-scoring-toggle"))


# ---------------------------------------------------------------------------
# Story 5: Settings Grouped by Purpose
# ---------------------------------------------------------------------------

_SECTIONS = [("season", "Season"), ("scoring", "Scoring"), ("tokens", "Tokens and rewards"),
             ("announcements", "Announcements"), ("players", "Players and tags"), ("maintenance", "Maintenance")]


def _settings():
    return _admin_tab(_fe("index.html"), "settings")


def _section(name):
    tab = _settings()
    start = tab.index(f'data-settings-section="{name}"')
    end = tab.find("<section ", start)
    return tab[start:end if end != -1 else len(tab)]


def test_settings_six_sections_in_order():
    """Source-reading: the Settings tab has six sections in order: Season, Scoring, Tokens and rewards, Announcements, Players and tags, Maintenance."""
    tab = _settings()
    found = re.findall(r'<section class="settings-section" id="settings-section-(\w+)" data-settings-section="\1"[^>]*>\s*'
                       r'<h2 class="settings-section-title"[^>]*>([^<]+)</h2>', tab)
    assert found == _SECTIONS


def test_settings_sections_hold_listed_panels():
    """Source-reading: Season = League Management, Season Lifecycle, Refresh Schedule Cache; Scoring = Scoring Weights, Recalculate; Tokens and rewards = Promo Codes, Token Grant Events; Announcements = Notifications; Players and tags = Tag Definitions, Re-enrich; Maintenance = Database Backups, Demo Mode."""
    expected = {
        "season": {"League Management", "Season Lifecycle", "Refresh Schedule Cache"},
        "scoring": {"Scoring Weights", "Recalculate Fantasy Points"},
        "tokens": {"Promo Codes", "Token Grant Events"},
        "announcements": {"Notifications"},
        "players": {"Tag Definitions", "Re-enrich Player Profiles"},
        "maintenance": {"Database Backups"},
    }
    for name, titles in expected.items():
        assert set(re.findall(r'<h3 class="admin-panel-title">([^<]+)</h3>', _section(name))) == titles, name
    assert 'id="demoModePanelContainer"' in _section("maintenance")  # Demo Mode is injected here


def test_settings_section_nav_lists_sections():
    """Source-reading: a section nav links to each of the six sections; style.css makes it sticky on desktop and a chip row at phone width."""
    tab = _settings()
    nav = tab[tab.index('<nav class="settings-nav"'):tab.index("</nav>")]
    buttons = re.findall(r'data-settings-target="(\w+)" onclick="selectSettingsSection\(\'\1\'\)">([^<]+)</button>', nav)
    assert buttons == _SECTIONS
    assert 'aria-label="Settings sections"' in nav
    css = _fe("style.css")
    nav_rule = " ".join(_rule(_strip_media(css), ".settings-nav"))
    assert "position: sticky" in nav_rule
    phone = [b for blk in _media_blocks(css, "(max-width: 760px)") for b in _rule(blk, ".settings-nav")]
    assert any("flex-direction: row" in b and "position: static" in b for b in phone)
    assert any("grid-template-columns: minmax(0, 1fr)" in b for blk in _media_blocks(css, "(max-width: 760px)")
               for b in _rule(blk, ".settings-layout"))


def test_settings_nav_remembers_last_section():
    """Source-reading/Node harness: selecting a section scrolls to it and stores it per browser (localStorage in try/catch)."""
    js = _fe("app-admin.js")
    for fn in ("selectSettingsSection", "restoreSettingsSection"):
        body = _fn_body(js, fn)
        assert "localStorage" in body and "try {" in body and "catch (e)" in body
    assert "restoreSettingsSection()" in _fn_body(js, "switchAdminTab")
    out = _js(["app-admin.js"], """
        const btns = ["season", "scoring", "tokens"].map(k => { const b = new El(null); b.dataset.settingsTarget = k; return b; });
        __all[".settings-nav-btn"] = btns;
        selectSettingsSection("scoring");
        const picked = {stored: __store.adminSettingsSection,
                        scrolled: document.getElementById("settings-section-scoring").scrolled,
                        active: btns.map(b => b.cls.has("active")), current: btns[1].getAttribute("aria-current")};
        document.getElementById("settings-section-scoring").scrolled = null;
        restoreSettingsSection();
        picked.restored = !!document.getElementById("settings-section-scoring").scrolled;
        __storageThrows = true;
        selectSettingsSection("tokens");
        restoreSettingsSection();
        picked.blockedActive = btns.map(b => b.cls.has("active"));
        out = picked;
    """)
    assert out["stored"] == "scoring"
    assert out["scrolled"] == {"behavior": "auto", "block": "start"}
    assert out["active"] == [False, True, False] and out["current"] == "true"
    assert out["restored"] is True
    assert out["blockedActive"] == [True, False, False]  # storage blocked: falls back to Season, no error


def test_settings_panels_have_consistent_header():
    """Source-reading: every Settings panel has a title, a one-line description and its primary action in a shared header element."""
    tab = _settings()
    panels = re.split(r'<div class="panel admin-panel"', tab)[1:]
    assert len(panels) == 11
    for p in panels:
        head = p[p.index('<div class="admin-panel-head">'):p.index('<div class="admin-panel-head">') + 1500]
        assert re.search(r'<h3 class="admin-panel-title">[^<]+</h3>\s*<p class="admin-panel-desc">[^\n]+</p>', head), p[:200]
        assert '<div class="admin-panel-actions">' in head, p[:200]
    demo = _fn_body(_fe("app-admin-demo.js"), "renderDemoModePanel")
    assert '<div class="admin-panel-head">' in demo and '<h3 class="admin-panel-title">Demo Mode</h3>' in demo
    for title in ("admin-panel-head", "admin-panel-title", "admin-panel-desc", "admin-panel-actions"):
        assert _rule(_fe("style.css"), "." + title), title


def test_settings_danger_actions_last_in_section():
    """Source-reading: Reset Season and Recalculate (recalculateBtn) are danger-styled and are the last panels/actions in their sections."""
    season = _section("season")
    scoring = _section("scoring")
    reset = season.index('<button class="danger" onclick="openSeasonResetConfirm()">Reset Season…</button>')
    assert all(m.start() <= reset for m in re.finditer(r"<button", season))
    assert re.findall(r'<h3 class="admin-panel-title">([^<]+)</h3>', season)[-1] == "Season Lifecycle"
    recalc = re.search(r'<button id="recalculateBtn" class="danger" onclick="recalculate\(\)">', scoring)
    assert recalc and all(m.start() <= recalc.start() for m in re.finditer(r"<button", scoring))
    assert re.findall(r'<h3 class="admin-panel-title">([^<]+)</h3>', scoring)[-1] == "Recalculate Fantasy Points"


def test_settings_all_prior_element_ids_present():
    """Source-reading: every id in SETTINGS_TAB_IDS_BEFORE_214 still exists exactly once inside the Settings tab."""
    tab = _settings()
    html = _fe("index.html")
    for el_id in SETTINGS_TAB_IDS_BEFORE_214:
        assert tab.count(f'id="{el_id}"') == 1, el_id
        assert html.count(f'id="{el_id}"') == 1, el_id


def test_admin_players_lookup_cache_is_bounded(monkeypatch):
    """The lookup cache drops expired entries, then the oldest, beyond its cap."""
    from routers import admin_players as ap
    ap.clear_lookup_cache()
    monkeypatch.setattr(ap, "_LOOKUP_CACHE_MAX", 3)
    now = [1000.0]
    monkeypatch.setattr(ap, "_lookup_now", lambda: now[0])
    monkeypatch.setattr(ap, "opendota_get_json", lambda *a, **k: {"profile": {"personaname": "P"}})
    for pid in (1, 2, 3, 4, 5):
        ap._opendota_name(pid)
    assert len(ap._lookup_cache) == 3
    assert list(ap._lookup_cache) == [3, 4, 5]
    now[0] += ap._LOOKUP_TTL_SECONDS + 1   # all expired
    ap._opendota_name(6)
    assert list(ap._lookup_cache) == [6]
    ap.clear_lookup_cache()
