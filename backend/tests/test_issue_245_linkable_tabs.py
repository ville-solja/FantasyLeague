"""
Tests for plan-issue-245-linkable-tabs.md (resolves GitHub issue #245).

Every main tab gets its own address, `/#<readable name>` (`#my-team`,
`#leaderboards`, `#history`, `#players`, `#teams`, `#schedule`, `#finals`,
`#team-finder`, `#how-to-play`, `#profile`, `#admin`; the internal ids `#team`,
`#leaderboard`, `#teamfinder`, `#howtoplay` also work, any letter case), plus
`#how-to-play/<subtab>`. Opening the page with a link opens that tab; switching
tab keeps the address bar in step (push for clicks, replace for code); Back and
Forward move between tabs; links to hidden, login-only or admin tabs land on
Leaderboards (or the login dialog); the Steam, Twitch and password-reset returns
keep working. Frontend only: these tests are source checks and Node harnesses.
One class per user story, one stub per acceptance criterion plus the primary
failure path.

Developer notes
---------------

  Existing code these tests target (verified 2026-11-17)
    - frontend/app-globals.js `switchTab(name)` (line ~177), with
      `const _tabScroll = {};` just above it. Order today: (1) the
      `activeMustChangePassword && name !== "profile"` redirect to "profile"
      (pinned as the FIRST statement by test_issue_159); (2) `current` =
      `.tab-content.active`, `sameTab`; (3) leaving `tab-team` calls
      `flushRosterSave()` (issue 186); (4) `if (!sameTab) { ... }` saves
      `_tabScroll[<old>] = window.scrollY`, toggles `.tab-content` / `.tab`
      `active`, restores `_tabScroll[name] || 0` in `requestAnimationFrame`;
      (5) per-tab loaders, `if (name === "<id>") ...` for profile and team
      (both `return` when `!activeUserId`), leaderboard, history, players,
      teams, schedule, finals, teamfinder, howtoplay (`loadHowToPlay()`), admin
      (returns when `!activeUserId || !activeIsAdmin`, AFTER the tab content
      was already made active). Note: switchTab("admin") for a non-admin still
      shows `#tab-admin` (empty), so the admin fallback must never call
      switchTab("admin").
    - Every `switchTab(` caller in frontend/ (internal ids only):
        index.html:518  `#headerUserLabel` onclick switchTab('profile')
        index.html:525-534  the ten tab buttons `#tab-btn-<id>` onclick
          switchTab('<id>') (team, leaderboard, history, players, teams,
          schedule, finals, teamfinder, howtoplay, admin)
        index.html:723  My Team "How scoring works" inline link,
          switchTab('howtoplay')
        app-auth.js:24   applyAuthState: `if (!loggedIn) switchTab("leaderboard")`
          (runs in init() BEFORE the return handlers, and on logout / 401)
        app-auth.js:113  handleSteamReturn -> switchTab("admin") (admin returns)
        app-auth.js:117  handleSteamReturn -> switchTab("profile")
        app-auth.js:166  submitSteamSignup -> switchTab("team")
        app-auth.js:331  login -> switchTab("profile") (must change password)
        app-auth.js:333  login -> switchTab("team")
        app-auth.js:418  register -> switchTab("team")
        app-profile.js:318  handleTwitchReturn -> switchTab("profile")
        app-profile.js:352  handleTwitchErrorReturn -> switchTab("profile")
        app-tour.js:310  startTourFromHowToPlay -> switchTab("team") (a button
          click in How to Play; decide push vs replace, the stubs don't pin it)
      Nothing passes `switchTab` as a reference. Clicks come from inline
      `onclick="switchTab('x')"` with ONE argument, so either the default is
      "push" and every code caller above passes `{ history: "replace" }`, or the
      markup passes `{history:'push'}` explicitly. Pick one; the stubs only pin
      the resulting pushState/replaceState calls.
    - frontend/app-init.js `init()` (line ~223): `await loadConfig()`,
      `loadAccolades()`, `await loadMe()`, `applyAuthState()`,
      `_handleResetTokenParam()`, then the literal line
      `if (!handleSteamReturn() && !handleTwitchErrorReturn()) handleTwitchReturn();`
      (pinned verbatim by test_twitch_extension_setup_followups), then data
      loads. Address handling today:
        `_handleResetTokenParam` (line ~213): reads `?reset_token=` from
          `location.search`; `history.replaceState(null, "", pathname)` (drops
          search AND hash), then `showResetPassword(token)`.
        `handleSteamReturn` (app-auth.js:94): matches
          `^#(login|welcome|profile|admin)\\?(.*)$` with a `steam` key; then
          `replaceState(null, "", pathname)` (drops search and hash).
        `handleTwitchErrorReturn` (app-profile.js:343): `?error=&state=` in
          `location.search`; replaceState keeping other params AND
          `location.hash`; logged out it returns true without switching.
        `handleTwitchReturn` (app-profile.js:311): `hash.startsWith("#profile")`
          -- matches a PLAIN `#profile` too (no `?`), always replaceState(pathname)
          and, logged out, returns false. So a logged-out `/#profile` link is
          wiped before any routing at the end of init(). Read the hash at the
          START of init() (before applyAuthState and the handlers), or narrow
          handleTwitchReturn to `#profile?` (check test_twitch_* first).
      PITFALL: applyAuthState() runs before handleSteamReturn. If its
      `switchTab("leaderboard")` writes the address, a logged-out
      `#login?steam=failed` / `#welcome?steam=...` return is overwritten with
      `#leaderboards` before handleSteamReturn reads it. During init that call
      must not touch the address (`{ history: "none" }`, or a flag), or the
      Steam return breaks.
    - Tab button visibility: Finals `#tab-btn-finals` has `hidden` in the
      markup; `applyFinalsAvailability(available)` (app-finals.js:11) sets
      `btn.hidden = !available` from `/config` `finals_available` (called in
      `loadConfig`, app-globals.js ~51). Team Finder `#tab-btn-teamfinder`:
      `applyTeamFinderAvailability(open)` (app-team-finder.js:20) sets
      `btn.hidden = !(_tfSignupOpen || activeIsAdmin)` from `/config`
      `team_signup_open` (admins ALWAYS see it; called from loadConfig and
      again from applyAuthState without an argument). My Team and Admin are
      NOT `hidden`: applyAuthState sets `style.display` ("none" when logged out
      / not admin). So "the tab's button is shown" means `!btn.hidden &&
      btn.style.display !== "none"`.
    - Login success paths that call `switchTab("team")` today: `login()`
      (app-auth.js:311, also `switchTab("profile")` when
      `activeMustChangePassword`), `register()` (:341) and
      `submitSteamSignup()` (:144). `showLogin()` (:174) hides the register /
      forgot / reset modals and shows `#loginModal`; `closeLoginModal()` (:251)
      only adds `hidden` (also run by Escape via `data-close`). Steam sign-in
      is a full-page navigation that returns to `/` on success
      (steam_openid._login_or_pending), so a pending tab kept in a module
      variable is lost across it (sessionStorage would keep it; not pinned).
    - How to Play subtabs (index.html ~997): `<div id="tab-howtoplay"
      class="tab-content" x-data="{ howToPlayTab: 'users' }">`, buttons
      `.howtoplay-tab-btn` with `@click="howToPlayTab = '<role>'"`, panels
      `#howtoplay-panel-<role>` with `x-show="howToPlayTab === '<role>'"`.
      Roles: users, players, streamers, developers. Alpine 3.17.4 is loaded with
      `defer`; app-init.js is a classic script at the end of body, so `init()`
      starts BEFORE Alpine has initialised the component: set the subtab from
      the link inside Alpine (`x-init` reading `location.hash`, `$watch` for
      writes) or after `alpine:initialized`, not with `Alpine.$data` from init().
    - Four in-page anchors in the Streamers panel (index.html:1138-1141,
      `href="#htp-streamers-overlay"` etc., issue 246) change the hash and fire
      `popstate` on Back/Forward. The popstate handler must ignore such hashes
      (stay on the current tab), not treat them as an unknown tab.
    - Notice: there is no toast helper. `setStatus(id, msg, ok)`
      (app-globals.js) writes a `.status` element; the closest pattern is My
      Team's `#drawLandedNotice` (role="status"). Add a `role="status"` element
      at the top of `#tab-leaderboard` (suggested id `tabLinkNotice`) and clear
      it on the next tab switch.

  Tests that break if switchTab / the markup change (check before editing)
    - test_issue_186_my_team_save_roster.py `test_flush_on_tab_or_week_change
      [tab_change]` RUNS `switchTab("schedule")` under Node. Its `_HARNESS`
      defines `const _tabScroll = {};`, `globalThis.window = win` (no
      `location`, no `history`), `document` with getElementById/querySelector,
      `requestAnimationFrame`; `_globals_src()` pastes only the functions
      ("renderIfChanged", "forgetRendered", "_escHtml", "switchTab",
      "prefersReducedMotion", "flipMove") plus two constants. A switchTab that
      calls `history.*`, reads `location`, or uses a new module constant /
      helper (`_TAB_LINKS`, `tabLink`) throws ReferenceError there: add the
      stubs / names to that harness (or guard with `typeof history`).
      test_issue_155's `_ROSTER_GLOBALS` also pastes switchTab (not called).
    - test_issue_159: body line 1 must stay the must-change-password `if`;
      no `return` before the end of the `if (!sameTab) {` block; no
      `classList.remove("active")` / `scrollTo` outside it; literal
      `const y = _tabScroll[name] || 0;` and the `_tabScroll` save line;
      `switchTab("leaderboard")`, `switchTab("team")`, `switchTab("profile")`
      literals in app-auth.js and `switchTab("team")` in app-tour.js (a call
      with a second argument, `switchTab("team", {...})`, does NOT contain
      `switchTab("team")`: update the test if you add arguments).
    - test_how_to_play_role_subtabs (2 tests) and
      test_frontend_framework_evaluation pin the exact
      `x-data="{ howToPlayTab: 'users' }"` and `@click="howToPlayTab = '<role>'"`
      and that `loadHowToPlay` doesn't mention `howToPlayTab`. Two of them take
      the FIRST line of app-globals.js containing `"howtoplay"` and require it
      to contain `loadHowToPlay()` and no `activeUserId`: a name map line such
      as `"how-to-play": "howtoplay",` placed above switchTab breaks them.
    - test_issue_144 slices switchTab between `if (name === "team")` and
      `if (name === "leaderboard")`; test_issue_220 / 237 / 50 pin the
      `if (name === "teamfinder")`, `"finals"`, `"history"` loader lines.
    - test_twitch_extension_setup_followups pins init()'s handler line, that
      `_handleResetTokenParam();` comes before it and that `await loadMe();`
      precedes `applyAuthState();`.

  Reusable helpers
    - `_node` (test_issue_159; None without Node, so `pytest.skip`), `_fn_body`
      pattern (`js[start:js.index("\\n}\\n", start)]`, drops `async`: re-add it
      when pasting init()/login(); append "\\n}\\n").
    - `_extract_panel(html, role)` in test_how_to_play_role_subtabs.
    - Harness style: test_issue_213 `_ADMIN_HARNESS` (fake El with
      classList/style, `document.getElementById` creating elements, a fake
      `window.location`, recorded calls). For this issue build one harness
      with: `location = { pathname, search, hash }` and `history = {
      pushState, replaceState }` that RECORD `(state, url)` and update
      `location.hash`/`search` from the url (define both `window.location` and
      a bare `location` / `history`, as the frontend uses both); window
      `scrollY`, `scrollTo`, `addEventListener` (capture `popstate`);
      `requestAnimationFrame = fn => fn()`; tab buttons and `.tab-content`
      elements for all ten ids with `hidden` / `style.display`; recorded stubs
      for every loader (loadSchedule, loadFinals, loadTeamFinder, loadProfile,
      loadDeck, loadWeeks -> Promise, loadRoster, initAdminTabs, every admin
      loader, loadHowToPlay, ...), `fetch` that logs URLs, and async
      `loadConfig` / `loadMe` stubs setting `activeUserId`, `activeIsAdmin` and
      the button flags. Paste the real switchTab, the name map, the routing
      functions, init(), applyAuthState, handleSteamReturn, handleTwitchReturn,
      handleTwitchErrorReturn, _handleResetTokenParam, showLogin,
      closeLoginModal and login().

  Names the stubs assume (rename freely, keep the behaviour)
    - `tabFromLink(hash)` -> `{ tab: "<internal id>", subtab: "<role>" | null }`
      or null (unknown / contains `?` / empty); `tabLink(id[, subtab])` ->
      `"#<readable name>[/<subtab>]"`. The plan names only `tabLink` and "a
      name map".

  Decisions the stubs pin (change in review if needed)
    - A bare `/` load leaves the address as it is (no hash added).
    - `#how-to-play/<unknown>` opens How to Play on Users and the address
      becomes `#how-to-play`.
    - Clicking the tab that is already active adds no history entry.
    - Closing the login dialog drops the pending tab; a later login goes to
      My Team as today.
    - register() and submitSteamSignup() honour the pending tab like login().
    - After a forced password change redirect the address is `#profile`.
"""

import json
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

_FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

_TAB_IDS = ["team", "leaderboard", "history", "players", "teams", "schedule", "finals",
            "teamfinder", "howtoplay", "admin"]
_READABLE = {
    "team": "my-team", "leaderboard": "leaderboards", "history": "history", "players": "players",
    "teams": "teams", "schedule": "schedule", "finals": "finals", "teamfinder": "team-finder",
    "howtoplay": "how-to-play", "profile": "profile", "admin": "admin",
}
_BY_NAME = {v: k for k, v in _READABLE.items()}
_ROLES = ["users", "players", "streamers", "developers"]


def _read(name):
    with open(os.path.join(_FRONTEND, name), encoding="utf-8") as f:
        return f.read()


def _node():
    return shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)


def _fn(js, name):
    m = re.search(r"^(?:async )?function " + re.escape(name) + r"\(", js, re.M)
    assert m, name
    return js[m.start():js.index("\n}\n", m.start()) + 3]


def _const(js, name):
    start = js.index(f"const {name} = ")
    line_end = js.index("\n", start)
    if js[line_end - 1] != "{":
        return js[start:line_end + 1]
    return js[start:js.index("\n};\n", start) + 4]


class _Markup(HTMLParser):
    """Every element with its attributes and the ids of its ancestors."""

    def __init__(self):
        super().__init__()
        self.stack, self.elements = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.elements.append({"tag": tag, "attrs": a, "ancestors": [x.get("id") for x in self.stack]})
        if tag not in ("input", "img", "br", "meta", "link", "hr", "source"):
            self.stack.append(a)

    def handle_endtag(self, tag):
        if self.stack and tag not in ("input", "img", "br", "meta", "link", "hr", "source"):
            self.stack.pop()


def _markup():
    p = _Markup()
    p.feed(_read("index.html"))
    return p.elements


def _by_id(elements, el_id):
    found = [e for e in elements if e["attrs"].get("id") == el_id]
    assert len(found) == 1, el_id
    return found[0]


def _alpine_attrs():
    tab = _by_id(_markup(), "tab-howtoplay")["attrs"]
    return tab["x-init"], tab["@htp-subtab.window"]


def _source():
    g, init_js, auth = _read("app-globals.js"), _read("app-init.js"), _read("app-auth.js")
    prof, fin, tf = _read("app-profile.js"), _read("app-finals.js"), _read("app-team-finder.js")
    links = g[g.index("// Issue #245: every main tab's link"):]
    links = links[:links.index("\n}\n", links.index("function _dropPendingTab(")) + 3]
    routing = init_js[init_js.index("const _TAB_LINK_NOTICES"):]
    routing = routing[:routing.index("\n}\n", routing.index("function scrollToHtpSection(")) + 3]
    parts = [
        "const _tabScroll = {};", _fn(g, "switchTab"), _fn(g, "setStatus"), links,
        _fn(fin, "applyFinalsAvailability"), _fn(tf, "applyTeamFinderAvailability"),
        routing, _fn(init_js, "_handleResetTokenParam"), _fn(init_js, "init"),
        _fn(auth, "applyAuthState"), _const(auth, "_STEAM_RETURN_MESSAGES"),
        _const(auth, "_REAUTH_RESUMABLE"), _fn(auth, "_takeReauthResume"), _fn(auth, "handleSteamReturn"),
        _fn(auth, "showSteamSignup"), _fn(auth, "closeSteamSignup"), _fn(auth, "submitSteamSignup"),
        _fn(auth, "showLogin"), 'let _forgotPasswordUsername = "";', _fn(auth, "showResetPassword"),
        _fn(auth, "closeLoginModal"), _fn(auth, "closeRegisterModal"), _fn(auth, "_regFieldErr"),
        _fn(auth, "_regClearField"), _fn(auth, "_regClearErrors"), _fn(auth, "login"),
        _fn(auth, "register"), _fn(auth, "_switchAfterLogin"),
        _const(prof, "_TWITCH_RETURN_MESSAGES"), _fn(prof, "handleTwitchReturn"),
        _const(prof, "_TWITCH_ERROR_MESSAGES"), _fn(prof, "handleTwitchErrorReturn"),
    ]
    return "\n".join(parts)


_RECORDED = [
    "loadProfile", "loadDeck", "loadRoster", "maybeStartMyTeamTour", "loadSeasonLeaderboard",
    "_populateLbWeekSelect", "loadWeeklyLeaderboard", "loadPastSeasons", "loadHistory", "loadPlayers",
    "loadLeaderboard", "loadTop", "loadTeams", "loadSchedule", "loadFinals", "loadTeamFinder",
    "loadHowToPlay", "initAdminTabs", "loadAdminWeeks", "loadWeights", "loadPointsCheckWeeks", "loadUsers",
    "loadTags", "loadCodes", "loadNotifications", "loadTokenGrantEvents", "loadPlayerPool", "loadLeagues",
    "loadAuditLog", "loadSeasonArchives", "loadAdminFinals", "loadAdminTeamSignup", "loadAccolades",
    "checkNotifications", "checkWeeklySummaryHighlight", "showOwnCardGrant", "flushRosterSave",
    "clearWeeklySummaryCache", "renderDemoModePanel", "refreshTwitchPendingBadge", "connectTwitch", "linkSteam",
]

_HARNESS = r"""
const __opts = __OPTS__;
const __calls = [], __pushes = [], __replaces = [], __fetches = [], __scrolls = [], __errors = [];
const __listeners = {};
class El {
  constructor(id) {
    this.id = id; this.hidden = false; this.textContent = ""; this.value = ""; this.className = "";
    this.dataset = {}; this.style = { display: "" }; this.innerHTML = ""; this._cls = new Set();
    const cls = this._cls;
    this.classList = { add: (...c) => c.forEach(x => cls.add(x)), remove: (...c) => c.forEach(x => cls.delete(x)),
                       contains: c => cls.has(c) };
  }
  scrollIntoView() { __calls.push("scrollIntoView:" + this.id); }
  focus() {}
}
const __els = {};
const document = {
  getElementById: id => __els[id] || (__els[id] = new El(id)),
  querySelector: sel => sel === ".tab-content.active"
    ? Object.values(__els).find(e => e._cls.has("tab-content") && e._cls.has("active")) || null : null,
  querySelectorAll: sel => Object.values(__els).filter(e => e._cls.has(sel.slice(1))),
};
for (const id of __TABS__.concat(["profile"])) document.getElementById("tab-" + id).classList.add("tab-content");
for (const id of __TABS__) document.getElementById("tab-btn-" + id).classList.add("tab");
document.getElementById("tab-leaderboard").classList.add("active");
document.getElementById("tab-btn-leaderboard").classList.add("active");
document.getElementById("tab-btn-finals").hidden = true;
document.getElementById("tab-btn-teamfinder").hidden = true;
document.getElementById("tabLinkNotice").hidden = true;
for (const id of ["loginModal", "registerModal", "forgotModal", "resetPasswordModal", "steamSignupModal"])
  document.getElementById(id).classList.add("hidden");

const location = { pathname: __opts.pathname, search: __opts.search, hash: __opts.hash };
function __setUrl(url) {
  const m = url.match(/^([^?#]*)(\?[^#]*)?(#.*)?$/);
  location.pathname = m[1]; location.search = m[2] || ""; location.hash = m[3] && m[3] !== "#" ? m[3] : "";
}
const history = {
  pushState(s, t, url) { __pushes.push(url); __setUrl(url); },
  replaceState(s, t, url) { __replaces.push(url); __setUrl(url); },
};
const __store = Object.assign({}, __opts.storage);
const sessionStorage = {
  getItem: k => (Object.hasOwn(__store, k) ? __store[k] : null),
  setItem: (k, v) => { __store[k] = String(v); },
  removeItem: k => { delete __store[k]; },
};
const window = globalThis;
window.location = location;
window.scrollY = 0;
window.scrollTo = (x, y) => __scrolls.push(y);
window.addEventListener = (type, fn) => (__listeners[type] = __listeners[type] || []).push(fn);
window.dispatchEvent = ev => { (__listeners[ev.type] || []).forEach(fn => fn(ev)); return true; };
const requestAnimationFrame = fn => fn();

const API = "";
let activeUserId = null, activeUsername = null, activeIsAdmin = false, activeMustChangePassword = false;
let _rosterWeekId = null, _tfSignupOpen = false, _twitchConnectBonusTokens = 0, _twitchMergeDismissed = false;
let __me = __opts.user;
__STUBS__
function loadWeeks() { __calls.push("loadWeeks"); return Promise.resolve(); }
async function claimTokenEvents() { __calls.push("claimTokenEvents"); }
function _promptReauth() { return Promise.resolve(false); }
function prefersReducedMotion() { return false; }
async function fetch(url) {
  __fetches.push(String(url));
  return { ok: true, status: 200, json: async () => ({}) };
}
async function loadMe() {
  __calls.push("loadMe");
  if (!__me) return;
  activeUserId = __me.id; activeUsername = "u" + __me.id; activeIsAdmin = !!__me.admin;
  activeMustChangePassword = !!__me.mcp;
}
async function loadConfig() {
  __calls.push("loadConfig");
  if (__opts.configDelay) await new Promise(r => setTimeout(r, __opts.configDelay));
  applyFinalsAvailability(__opts.finals);
  applyTeamFinderAvailability(__opts.tf);
}

__SOURCE__

const __realSwitchTab = switchTab;
switchTab = function (...args) { __calls.push("switchTab:" + JSON.stringify(args)); return __realSwitchTab(...args); };

const __alpine = { scope: null };
function __startAlpine() {
  const watchers = {};
  let val = "users";
  const scope = {
    get howToPlayTab() { return val; },
    set howToPlayTab(v) { const old = val; val = v; if (old !== v) (watchers.howToPlayTab || []).forEach(f => f(v)); },
    $watch(k, f) { (watchers[k] = watchers[k] || []).push(f); },
  };
  new Function("scope", "with (scope) { " + __XINIT__ + " }")(scope);
  window.addEventListener("htp-subtab", ev => new Function("scope", "$event", "with (scope) { " + __XEVENT__ + " }")(scope, ev));
  __alpine.scope = scope;
}
function __click(onclick) { new Function(onclick)(); }
function __popstate(hash) { location.hash = hash; (__listeners.popstate || []).forEach(f => f({})); }
function __reset() { __calls.length = 0; __pushes.length = 0; __replaces.length = 0; __fetches.length = 0; __scrolls.length = 0; }
const __settle = () => new Promise(r => setTimeout(r, 0));
async function __boot() {
  if (__opts.alpine === "early") { const p = init(); __startAlpine(); await p; }
  else { await init(); if (__opts.alpine === "late") __startAlpine(); }
  await __settle();
}
function __state(extra) {
  const on = cls => Object.values(__els).filter(e => e._cls.has(cls) && e._cls.has("active")).map(e => e.id);
  const notice = document.getElementById("tabLinkNotice");
  const open = id => !document.getElementById(id).classList.contains("hidden");
  return Object.assign({
    active: on("tab-content"), activeBtns: on("tab"), calls: __calls, pushes: __pushes, replaces: __replaces,
    url: location.pathname + location.search + location.hash, hash: location.hash, search: location.search,
    notice: { text: notice.textContent, hidden: notice.hidden }, fetches: __fetches, scrolls: __scrolls,
    loginOpen: open("loginModal"), steamSignupOpen: open("steamSignupModal"), resetOpen: open("resetPasswordModal"),
    loginStatus: document.getElementById("loginStatus").textContent,
    twitchStatus: document.getElementById("twitchStatus").textContent,
    resetToken: document.getElementById("resetToken").value,
    pending: sessionStorage.getItem("pendingTab"), pendingFallback: _pendingTabFallback,
    htp: __alpine.scope ? __alpine.scope.howToPlayTab : null, errors: __errors,
    twitchCancelled: _TWITCH_RETURN_MESSAGES.cancelled[0],
  }, extra || {});
}
(async () => {
  let __extra = {};
  try {
__STEPS__
  } catch (e) { __errors.push(String(e && e.stack || e)); }
  console.log(JSON.stringify(__state(__extra)));
})();
"""


def _run(steps="await __boot();", *, hash="", search="", pathname="/", user=None, finals=True, tf=True,
         config_delay=0, alpine=None, storage=None):
    node = _node()
    if not node:
        pytest.skip("node not available")
    opts = {"hash": hash, "search": search, "pathname": pathname, "user": user, "finals": finals, "tf": tf,
            "configDelay": config_delay, "alpine": alpine, "storage": storage or {}}
    xinit, xevent = _alpine_attrs()
    stubs = "\n".join(f'function {n}() {{ __calls.push("{n}"); }}' for n in _RECORDED)
    script = (_HARNESS.replace("__OPTS__", json.dumps(opts)).replace("__TABS__", json.dumps(_TAB_IDS))
              .replace("__STUBS__", stubs).replace("__XINIT__", json.dumps(xinit))
              .replace("__XEVENT__", json.dumps(xevent)).replace("__STEPS__", steps)
              .replace("__SOURCE__", _source()))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    state = json.loads(out.stdout.strip().splitlines()[-1])
    assert state["errors"] == [], state["errors"]
    return state


_ADMIN = {"id": 1, "admin": True}
_PLAYER = {"id": 2}
_LOGIN = """
  __me = __LOGIN_USER__;
  document.getElementById("loginUsername").value = "u";
  document.getElementById("loginPassword").value = "secret1";
  await login(); await __settle();
"""


def _login(user=_PLAYER):
    return _LOGIN.replace("__LOGIN_USER__", json.dumps(user))


_REGISTER = """
  __me = {"id": 3};
  document.getElementById("regUsername").value = "newbie";
  document.getElementById("regEmail").value = "a@b.cd";
  document.getElementById("regPassword").value = "secret1";
  await register(); await __settle();
"""
_STEAM_SIGNUP = """
  __me = {"id": 4};
  document.getElementById("steamSignupUsername").value = "steamer";
  await submitSteamSignup(); await __settle();
"""


def _switch_calls(state):
    return [json.loads(c[len("switchTab:"):]) for c in state["calls"] if c.startswith("switchTab:")]


# ---------------------------------------------------------------------------
# Story 1: Open a Tab From a Link
# ---------------------------------------------------------------------------

class TestOpenTabFromLink:

    def test_tab_link_map_covers_every_tab_button(self):
        """app-globals.js has one table of tabs: every `id="tab-btn-<id>"` in index.html (team, leaderboard, history, players, teams, schedule, finals, teamfinder, howtoplay, admin) plus profile has exactly one readable name, and the set of readable names is exactly {my-team, leaderboards, history, players, teams, schedule, finals, team-finder, how-to-play, profile, admin}; `tabLink(id)` returns `"#" + <readable name>` for each."""
        buttons = [e["attrs"]["id"][len("tab-btn-"):] for e in _markup()
                   if (e["attrs"].get("id") or "").startswith("tab-btn-")]
        assert sorted(buttons) == sorted(_TAB_IDS)
        out = _run("__extra = { map: _TAB_LINKS, links: Object.fromEntries(Object.keys(_TAB_LINKS).map(k => [k, tabLink(k)])) };")
        assert set(out["map"]) == set(buttons) | {"profile"}
        names = list(out["map"].values())
        assert len(names) == len(set(names))
        assert set(names) == {"my-team", "leaderboards", "history", "players", "teams", "schedule", "finals",
                              "team-finder", "how-to-play", "profile", "admin"}
        assert out["links"] == {k: "#" + v for k, v in _READABLE.items()}

    def test_tab_from_link_resolves_old_ids_and_any_case(self):
        """`tabFromLink` maps `#team`, `#leaderboard`, `#teamfinder`, `#howtoplay` to the same tab ids as `#my-team`, `#leaderboards`, `#team-finder`, `#how-to-play`, and matches regardless of case (`#My-Team`, `#FINALS`, `#HowToPlay` resolve)."""
        hashes = ["#team", "#my-team", "#leaderboard", "#leaderboards", "#teamfinder", "#team-finder",
                  "#howtoplay", "#how-to-play", "#My-Team", "#FINALS", "#HowToPlay"]
        out = _run("__extra = { r: Object.fromEntries(%s.map(h => [h, tabFromLink(h)])) };" % json.dumps(hashes))
        r = {h: (v or {}).get("tab") for h, v in out["r"].items()}
        assert r["#team"] == r["#my-team"] == r["#My-Team"] == "team"
        assert r["#leaderboard"] == r["#leaderboards"] == "leaderboard"
        assert r["#teamfinder"] == r["#team-finder"] == "teamfinder"
        assert r["#howtoplay"] == r["#how-to-play"] == r["#HowToPlay"] == "howtoplay"
        assert r["#FINALS"] == "finals"

    _SIGNATURE = {
        "team": ["loadDeck", "maybeStartMyTeamTour"], "leaderboard": ["loadPastSeasons"],
        "history": ["loadHistory"], "players": ["loadPlayers", "loadLeaderboard", "loadTop"],
        "teams": ["loadTeams"], "schedule": ["loadSchedule"], "finals": ["loadFinals"],
        "teamfinder": ["loadTeamFinder"], "howtoplay": ["loadHowToPlay"], "profile": ["loadProfile"],
        "admin": ["initAdminTabs", "loadUsers", "loadAuditLog"],
    }

    @pytest.mark.parametrize("name", sorted(_BY_NAME))
    def test_init_opens_linked_tab_with_its_loaders(self, name):
        """Node harness, parametrized over the eleven readable names (logged-in admin, Finals and Team Finder open): init() with `location.hash = "#<name>"` ends with `#tab-<id>` the only active `.tab-content`, `#tab-btn-<id>` active, and that tab's loaders called exactly as a click calls them (e.g. `#schedule` -> loadSchedule, `#players` -> loadPlayers + loadLeaderboard + loadTop, `#admin` -> initAdminTabs)."""
        tab = _BY_NAME[name]
        out = _run(hash="#" + name, user=_ADMIN)
        assert out["active"] == [f"tab-{tab}"]
        assert out["activeBtns"] == ([] if tab == "profile" else [f"tab-btn-{tab}"])
        for loader in self._SIGNATURE[tab]:
            assert loader in out["calls"], loader
        start = "schedule" if tab != "schedule" else "teams"
        click = _run(f'await __boot(); switchTab("{start}", {{ history: "none" }}); __reset(); '
                     f'openTab("{tab}"); await __settle();', user=_ADMIN)
        clicked = [c for c in click["calls"] if not c.startswith("switchTab:")]
        assert clicked and set(clicked) <= set(out["calls"])
        assert out["hash"] == "#" + name and out["pushes"] == []

    @pytest.mark.parametrize("alpine", ["early", "late"])
    @pytest.mark.parametrize("link,role", [
        ("#how-to-play/users", "users"), ("#how-to-play/players", "players"),
        ("#how-to-play/streamers", "streamers"), ("#how-to-play/developers", "developers"),
        ("#howtoplay/streamers", "streamers"), ("#How-To-Play/Developers", "developers"),
    ])
    def test_init_opens_how_to_play_subtab_from_link(self, link, role, alpine):
        """`#how-to-play/users`, `/players`, `/streamers`, `/developers` (and `#howtoplay/streamers`, any case) open How to Play with Alpine's `howToPlayTab` set to that role, so only `#howtoplay-panel-<role>` is shown; the initial-state source is wired in index.html (x-init or an Alpine event) since init() runs before deferred Alpine starts."""
        xinit, xevent = _alpine_attrs()
        assert "htpSubtabOnStart()" in xinit and xevent == "howToPlayTab = $event.detail"
        els = _markup()
        for r in _ROLES:
            assert _by_id(els, f"howtoplay-panel-{r}")["attrs"]["x-show"] == f"howToPlayTab === '{r}'"
        out = _run(hash=link, alpine=alpine)
        assert out["active"] == ["tab-howtoplay"]
        assert out["htp"] == role
        assert out["hash"] == f"#how-to-play/{role}"

    @pytest.mark.parametrize("user", [None, _PLAYER])
    def test_init_without_hash_opens_leaderboards_and_keeps_address(self, user):
        """No hash: init() leaves `#tab-leaderboard` active (logged in and logged out), calls no pushState, and the address stays `location.pathname + location.search` with no hash added."""
        out = _run(search="?ref=discord", user=user)
        assert out["active"] == ["tab-leaderboard"]
        assert out["pushes"] == [] and out["replaces"] == []
        assert out["url"] == "/?ref=discord"

    @pytest.mark.parametrize("link", ["#nonsense", "#", "#how-to-play/nonsense", "#../admin", "#constructor"])
    def test_init_unknown_hash_opens_leaderboards_without_error(self, link):
        """Failure path: `#nonsense`, `#`, `#how-to-play/nonsense` and `#../admin` raise nothing; `#nonsense` ends on Leaderboards with no notice shown, and `#how-to-play/nonsense` opens How to Play on the Users subtab with the address `#how-to-play`."""
        out = _run(hash=link, alpine="early")
        assert "initAdminTabs" not in out["calls"]
        if link == "#how-to-play/nonsense":
            assert out["active"] == ["tab-howtoplay"]
            assert out["htp"] == "users"
            assert out["hash"] == "#how-to-play"
        else:
            assert out["active"] == ["tab-leaderboard"]
            assert out["notice"] == {"text": "", "hidden": True}
            assert out["hash"] == "#leaderboards"


# ---------------------------------------------------------------------------
# Story 2: Copy the Address of the Tab I'm On
# ---------------------------------------------------------------------------

class TestAddressFollowsTab:

    def test_tab_button_click_pushes_readable_link(self):
        """Running each tab button's onclick from index.html (and `#headerUserLabel`, the "How scoring works" link) calls `history.pushState` once with url `<pathname><search>#<readable name>` (`#my-team` for team, `#leaderboards` for leaderboard, `#team-finder`, `#how-to-play`) and never replaceState."""
        els = _markup()
        clicks = [(_by_id(els, f"tab-btn-{t}")["attrs"]["onclick"], t) for t in _TAB_IDS]
        clicks.append((_by_id(els, "headerUserLabel")["attrs"]["onclick"], "profile"))
        scoring = [e for e in els if "inline-tab-link" in (e["attrs"].get("class") or "")
                   and "howtoplay" in (e["attrs"].get("onclick") or "")]
        assert len(scoring) == 1
        clicks.append((scoring[0]["attrs"]["onclick"], "howtoplay"))
        steps = ["await __boot(); __extra.clicks = [];"]
        for onclick, tab in clicks:
            start = "schedule" if tab != "schedule" else "teams"
            steps.append(f'switchTab("{start}", {{ history: "none" }}); __reset(); __click({json.dumps(onclick)}); '
                         f'__extra.clicks.push({{ tab: "{tab}", pushes: __pushes.slice(), replaces: __replaces.slice() }});')
        out = _run("\n".join(steps), user=_ADMIN)
        for c in out["clicks"]:
            assert c["pushes"] == [f"/#{_READABLE[c['tab']]}"], c
            assert c["replaces"] == [], c

    @pytest.mark.parametrize("flow", ["login", "register", "steam_signup", "logout", "steam_return",
                                      "twitch_return", "twitch_error"])
    def test_switch_tab_from_code_replaces_address(self, flow):
        """Code callers (login, register, submitSteamSignup, applyAuthState after logout, handleSteamReturn, handleTwitchReturn, handleTwitchErrorReturn) write the address with `history.replaceState`, never pushState: after a successful `login()` there is one replaceState to `#my-team` and zero pushState calls."""
        if flow in ("login", "register", "steam_signup"):
            body = {"login": _login(), "register": _REGISTER, "steam_signup": _STEAM_SIGNUP}[flow]
            out = _run("await __boot(); __reset();" + body)
            assert out["pushes"] == []
            assert out["replaces"] == ["/#my-team"]
            assert out["active"] == ["tab-team"]
            return
        steps = {
            "logout": 'openTab("schedule"); __reset(); activeUserId = null; applyAuthState();',
            "steam_return": '__reset(); location.hash = "#profile?steam=linked"; handleSteamReturn();',
            "twitch_return": '__reset(); location.hash = "#profile?twitch=connected"; handleTwitchReturn();',
            "twitch_error": '__reset(); location.search = "?error=access_denied&state=s"; handleTwitchErrorReturn();',
        }[flow]
        out = _run("await __boot();" + steps, user=_PLAYER)
        assert out["pushes"] == []
        assert out["replaces"] and out["replaces"][-1].endswith("#leaderboards" if flow == "logout" else "#profile")

    def test_switch_tab_keeps_path_and_query(self):
        """With `location.pathname = "/sub/"` and `location.search = "?a=1&b=2"`, switching to Teams writes exactly `"/sub/?a=1&b=2#teams"`; no other part of the url changes."""
        out = _run('await __boot(); __reset(); openTab("teams"); __extra.clicked = __pushes.slice(); '
                   '__reset(); switchTab("schedule"); switchTab("teams");',
                   pathname="/sub/", search="?a=1&b=2")
        assert out["clicked"] == ["/sub/?a=1&b=2#teams"]
        assert out["replaces"] == ["/sub/?a=1&b=2#schedule", "/sub/?a=1&b=2#teams"]
        assert out["url"] == "/sub/?a=1&b=2#teams"

    def test_popstate_switches_tab_without_writing_history(self):
        """app-init.js registers a `popstate` listener; firing it with `location.hash = "#schedule"` (after clicks Players -> Schedule -> Teams, then Back) shows Schedule through switchTab with `{ history: "none" }`: no pushState/replaceState call, and `window.scrollTo` gets Schedule's saved `_tabScroll` value; an empty hash shows Leaderboards."""
        assert 'window.addEventListener("popstate"' in _read("app-init.js")
        out = _run("""
          await __boot();
          openTab("players"); window.scrollY = 111;
          openTab("schedule"); window.scrollY = 222;
          openTab("teams"); window.scrollY = 333;
          __extra.pushed = __pushes.slice();
          __reset(); __popstate("#schedule");
          __extra.back = { active: __state().active.slice(), calls: __calls.slice(), pushes: __pushes.length,
                           replaces: __replaces.length, scrolls: __scrolls.slice() };
          __reset(); __popstate("");
        """)
        assert out["pushed"] == ["/#players", "/#schedule", "/#teams"]
        back = out["back"]
        assert back["active"] == ["tab-schedule"]
        assert 'switchTab:["schedule",{"history":"none"}]' in back["calls"]
        assert back["pushes"] == 0 and back["replaces"] == 0
        assert back["scrolls"] == [222]
        assert out["active"] == ["tab-leaderboard"]
        assert out["pushes"] == [] and out["replaces"] == []

    @pytest.mark.parametrize("link", ["#finals", "#how-to-play/streamers"])
    def test_init_from_link_adds_no_history_entry(self, link):
        """Opening the page with `#finals` (or `#how-to-play/streamers`) makes zero pushState calls during init(); any address write is a replaceState, so one Back leaves the site."""
        out = _run(hash=link, user=_PLAYER, alpine="early")
        assert out["pushes"] == []
        assert out["replaces"] and out["replaces"][-1] == "/" + link

    def test_how_to_play_subtab_change_replaces_address(self):
        """Changing `howToPlayTab` (clicking the Players subtab) writes `#how-to-play/players` with replaceState (never pushState) while How to Play is the active tab; index.html keeps `x-data="{ howToPlayTab: 'users' }"` and `@click="howToPlayTab = '<role>'"` (or the three pinning tests are updated with it)."""
        html = _read("index.html")
        assert 'x-data="{ howToPlayTab: \'users\' }"' in html
        for r in _ROLES:
            assert f"@click=\"howToPlayTab = '{r}'\"" in html
        assert "htpSubtabChanged(v)" in _alpine_attrs()[0]
        click = "howToPlayTab = 'players'"
        out = _run(f"""
          await __boot();
          __reset(); new Function("scope", "with (scope) {{ howToPlayTab = 'streamers' }}")(__alpine.scope);
          __extra.hidden = {{ pushes: __pushes.length, replaces: __replaces.length }};
          openTab("howtoplay"); __reset();
          new Function("scope", "with (scope) {{ " + {json.dumps(click)} + " }}")(__alpine.scope);
        """, alpine="early")
        assert out["hidden"] == {"pushes": 0, "replaces": 0}
        assert out["pushes"] == []
        assert out["replaces"] == ["/#how-to-play/players"]

    def test_switch_tab_history_none_same_tab_and_anchor_hashes_write_nothing(self):
        """Failure path: `switchTab(x, { history: "none" })` writes no history; clicking the already active tab adds no pushState; a popstate whose hash is an in-page anchor (`#htp-streamers-overlay`) keeps the current tab and calls no switchTab; with `activeMustChangePassword` true, a click on Schedule writes `#profile`, the tab actually shown."""
        out = _run("""
          await __boot(); __reset();
          switchTab("schedule", { history: "none" });
          __extra.none = __pushes.length + __replaces.length;
          openTab("schedule");
          __extra.same = __pushes.length;
          __reset(); __popstate("#htp-streamers-overlay");
          __extra.anchor = { active: __state().active.slice(), calls: __calls.slice() };
        """, user=_PLAYER)
        assert out["none"] == 0 and out["same"] == 0
        assert out["anchor"]["active"] == ["tab-schedule"]
        assert not any(c.startswith("switchTab:") for c in out["anchor"]["calls"])
        assert out["replaces"] == [] and out["pushes"] == []
        mcp = _run('await __boot(); __reset(); openTab("schedule");', user={"id": 5, "mcp": True})
        assert mcp["active"] == ["tab-profile"]
        assert mcp["pushes"] == ["/#profile"]


# ---------------------------------------------------------------------------
# Story 3: Links to Tabs That Aren't Available
# ---------------------------------------------------------------------------

class TestLinksToUnavailableTabs:

    def test_hidden_finals_link_falls_back_with_notice(self):
        """`#finals` with `#tab-btn-finals.hidden` true after loadConfig (finals_available false): Leaderboards is active, loadFinals is never called, a role="status" element in `#tab-leaderboard` reads exactly "The Finals tab isn't open yet.", and the address is replaced with `#leaderboards`."""
        notice = _by_id(_markup(), "tabLinkNotice")
        assert notice["attrs"]["role"] == "status" and "tab-leaderboard" in notice["ancestors"]
        out = _run('await __boot(); __extra.first = __state().notice; openTab("schedule");', hash="#finals", finals=False)
        assert out["first"] == {"text": "The Finals tab isn't open yet.", "hidden": False}
        assert "loadFinals" not in out["calls"]
        assert out["replaces"][0] == "/#leaderboards" and out["pushes"] == ["/#schedule"]
        assert out["notice"] == {"text": "", "hidden": True}  # cleared on the next tab switch

    @pytest.mark.parametrize("user", [None, _PLAYER, _ADMIN])
    def test_closed_team_finder_link_falls_back_with_notice(self, user):
        """`#team-finder` with team_signup_open false and a non-admin: Leaderboards, notice exactly "Team Finder isn't open right now.", loadTeamFinder not called, address `#leaderboards`; for an admin (button shown by applyTeamFinderAvailability) the same link opens Team Finder."""
        out = _run(hash="#team-finder", user=user, tf=False)
        if user is _ADMIN:
            assert out["active"] == ["tab-teamfinder"] and "loadTeamFinder" in out["calls"]
            assert out["notice"]["text"] == "" and out["hash"] == "#team-finder"
            return
        assert out["active"] == ["tab-leaderboard"]
        assert out["notice"] == {"text": "Team Finder isn't open right now.", "hidden": False}
        assert "loadTeamFinder" not in out["calls"]
        assert out["hash"] == "#leaderboards"

    def test_available_tab_link_decided_after_config_and_login(self):
        """init() reads the link only after `await loadConfig()`, `await loadMe()`, `applyAuthState()` and the return handlers: with `/config` answering finals_available true after a delay, `#finals` opens Finals (never refused, no notice); the hash is captured before applyAuthState and the handlers can rewrite it."""
        body = _fn(_read("app-init.js"), "init")
        handlers = "if (!handleSteamReturn() && !handleTwitchErrorReturn()) handleTwitchReturn();"
        capture = body.index("const startHash = window.location.hash")
        assert capture < body.index("await loadConfig();") < body.index("await loadMe();")
        assert body.index("applyAuthState();") < body.index(handlers) < body.index("_routeInitialLink(startHash")
        out = _run(hash="#finals", config_delay=30)  # logged out: applyAuthState switches tabs during init
        assert out["active"] == ["tab-finals"] and "loadFinals" in out["calls"]
        assert out["notice"]["text"] == "" and out["hash"] == "#finals"

    @pytest.mark.parametrize("link,tab", [("#my-team", "team"), ("#profile", "profile")])
    @pytest.mark.parametrize("flow", ["login", "register", "steam_signup"])
    def test_logged_out_login_tab_link_opens_login_then_continues(self, link, tab, flow):
        """Logged out, `#my-team` (and separately `#profile`) calls showLogin(), leaves Leaderboards active and loads no My Team / Profile data; a later successful `login()` switches to `team` (resp. `profile`) instead of the default and clears the pending tab, so the next login goes to My Team; register() and submitSteamSignup() honour the pending tab the same way."""
        body = {"login": _login(), "register": _REGISTER, "steam_signup": _STEAM_SIGNUP}[flow]
        out = _run(f"""
          await __boot();
          __extra.before = {{ active: __state().active.slice(), login: __state().loginOpen, calls: __calls.slice() }};
          {body}
          __extra.after = {{ active: __state().active.slice(), pending: sessionStorage.getItem("pendingTab"),
                            fallback: _pendingTabFallback }};
          activeUserId = null; applyAuthState(); openTab("schedule");
          {_login()}
        """, hash=link)
        before = out["before"]
        assert before["login"] is True and before["active"] == ["tab-leaderboard"]
        for loader in ("loadDeck", "loadProfile", "maybeStartMyTeamTour"):
            assert loader not in before["calls"]
        assert out["after"] == {"active": [f"tab-{tab}"], "pending": None, "fallback": None}
        assert out["active"] == ["tab-team"]  # the next login goes to My Team

    def test_pending_tab_survives_steam_sign_in_round_trip(self):
        """The pending tab is kept in sessionStorage: after the Steam sign-in returns to a bare `/` logged in, init() opens it, writes its link and clears it."""
        out = _run(user=_PLAYER, storage={"pendingTab": "profile"})
        assert out["active"] == ["tab-profile"] and out["hash"] == "#profile"
        assert out["pending"] is None and out["pushes"] == []

    def test_logged_out_profile_link_not_swallowed_by_twitch_return(self):
        """Logged out, a plain `#profile` (no `?`) still opens the login dialog and continues to Profile after login: handleTwitchReturn's `startsWith("#profile")` strip does not consume the link before routing reads it."""
        out = _run("""
          await __boot();
          __extra.login = __state().loginOpen;
          __extra.pendingAfterInit = sessionStorage.getItem("pendingTab");
          const r0 = __replaces.length; location.hash = "#profile";
          __extra.twitch = { handled: handleTwitchReturn(), wrote: __replaces.length - r0 };
        """ + _login(), hash="#profile")
        assert out["login"] is True and out["pendingAfterInit"] == "profile"
        assert out["twitch"] == {"handled": False, "wrote": 0}
        assert out["active"] == ["tab-profile"] and "loadProfile" in out["calls"]

    def test_closing_login_dialog_stays_on_leaderboards(self):
        """Failure path: after `#my-team` opened the login dialog, closeLoginModal() (button or Escape) leaves `#tab-leaderboard` active and the address `#leaderboards`, and drops the pending tab (a later login lands on My Team)."""
        assert _by_id(_markup(), "loginModal")["attrs"]["data-close"] == "closeLoginModal"
        out = _run("await __boot(); closeLoginModal();", hash="#my-team")
        assert out["loginOpen"] is False and out["active"] == ["tab-leaderboard"]
        assert out["hash"] == "#leaderboards"
        assert out["pending"] is None and out["pendingFallback"] is None
        later = _run("await __boot(); closeLoginModal(); showLogin();" + _login(), hash="#profile")
        assert later["active"] == ["tab-team"]

    @pytest.mark.parametrize("user", [None, _PLAYER, _ADMIN])
    def test_admin_link_for_non_admin_falls_back_silently(self, user):
        """Failure path: `#admin` for a visitor and for a logged-in non-admin ends on Leaderboards with no notice text, never makes `#tab-admin` active (switchTab("admin") not called), makes no fetch to a `/admin` url, and replaces the address with `#leaderboards`; for an admin it opens Admin."""
        out = _run(hash="#admin", user=user)
        if user is _ADMIN:
            assert out["active"] == ["tab-admin"] and "initAdminTabs" in out["calls"]
            return
        assert out["active"] == ["tab-leaderboard"]
        assert out["notice"]["text"] == "" and out["loginOpen"] is False
        assert all(call[0] != "admin" for call in _switch_calls(out))
        assert not any("/admin" in u for u in out["fetches"])
        assert "initAdminTabs" not in out["calls"]
        assert out["hash"] == "#leaderboards" and out["pushes"] == []


# ---------------------------------------------------------------------------
# Story 4: Sign-in Returns Keep Working
# ---------------------------------------------------------------------------

class TestSignInReturnsKeepWorking:

    def test_tab_routing_ignores_hash_with_query(self):
        """`tabFromLink` returns null for any hash containing `?` (`#profile?twitch=linked`, `#login?steam=failed`, `#welcome?steam=x`, `#admin?steam=reauth_ok`, `#finals?x=1`), and init() leaves those to handleSteamReturn / handleTwitchReturn: the handler line `if (!handleSteamReturn() && !handleTwitchErrorReturn()) handleTwitchReturn();` stays in init() after `_handleResetTokenParam();`."""
        hashes = ["#profile?twitch=linked", "#login?steam=failed", "#welcome?steam=x",
                  "#admin?steam=reauth_ok", "#finals?x=1"]
        out = _run("__extra.r = %s.map(h => tabFromLink(h));" % json.dumps(hashes))
        assert out["r"] == [None] * len(hashes)
        body = _fn(_read("app-init.js"), "init")
        line = "if (!handleSteamReturn() && !handleTwitchErrorReturn()) handleTwitchReturn();"
        assert body.index("_handleResetTokenParam();") < body.index(line)

    def test_logged_out_steam_return_survives_apply_auth_state(self):
        """Failure path: logged out, init() with `#login?steam=failed` still shows the login dialog with loginStatus "Steam sign-in did not complete. Nothing was changed. Try again.", and `#welcome?steam=choose_name` still opens `#steamSignupModal`: applyAuthState's `switchTab("leaderboard")` during init does not overwrite the hash before handleSteamReturn reads it."""
        out = _run(hash="#login?steam=failed")
        assert out["loginOpen"] is True
        assert out["loginStatus"] == "Steam sign-in did not complete. Nothing was changed. Try again."
        welcome = _run(hash="#welcome?steam=choose_name")
        assert welcome["steamSignupOpen"] is True

    def test_reset_token_and_twitch_error_returns_unchanged(self):
        """`?reset_token=abc` still opens the reset modal with the token prefilled and removes `reset_token` from the address; `?error=access_denied&state=s` logged in still opens Profile with the Twitch cancelled message and removes error/state/error_description/error_uri while keeping other query params."""
        out = _run(search="?reset_token=abc")
        assert out["resetOpen"] is True and out["resetToken"] == "abc"
        assert "reset_token" not in out["url"]
        err = _run(search="?error=access_denied&state=s&error_description=x&error_uri=y&keep=1", user=_PLAYER)
        assert err["active"] == ["tab-profile"]
        assert err["twitchStatus"] == err["twitchCancelled"]
        assert err["search"] == "?keep=1"
        assert err["pushes"] == []

    @pytest.mark.parametrize("link,user,final", [
        ("#profile?steam=linked", _PLAYER, "/#profile"),
        ("#admin?steam=reauth_ok", _ADMIN, "/#admin"),
        ("#profile?twitch=linked", _PLAYER, "/#profile"),
        ("#login?steam=failed", None, "/#leaderboards"),
    ])
    def test_return_flows_end_with_readable_tab_link(self, link, user, final):
        """After `#profile?steam=linked` (logged in) the final address is `<pathname>#profile`; after `#admin?steam=reauth_ok` (admin) it is `<pathname>#admin`; after `#profile?twitch=linked` it is `<pathname>#profile`; after a logged-out `#login?steam=failed` it is `<pathname>#leaderboards`; none of these flows calls pushState."""
        out = _run(hash=link, user=user)
        assert out["url"] == final
        assert out["pushes"] == []
