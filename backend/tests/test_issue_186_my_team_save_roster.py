"""
Tests for plan-issue-186-my-team-save-roster.md (resolves GitHub issue #186,
takes over idea 2 of #155).

My Team becomes a fluid roster editor: the page owns the layout
(`_layout = {active, bench, version}` in frontend/app-roster.js), every move
applies locally with a FLIP glide, dragging uses Pointer Events (touch:
250 ms long-press), and the layout autosaves 600 ms after the last move with
one atomic, versioned `PUT /roster`. There is no Save button.

Backend (backend/card_utils.py, backend/routers/cards.py):
  * `roster_version(db, user_id)` -- SHA-256 of `active:<ids>|bench:<ids>`,
    first 16 hex characters; returned as `version` by `GET /roster/{user_id}`.
  * `apply_roster_layout(db, user_id, active, bench, base_version)` -- takes the
    write lock first (no-op UPDATE, pattern from #193), checks ownership,
    duplicates, ROSTER_LIMIT, one active card per player, no removed
    (`Player.is_active == False`) player active, base_version; benches first
    (so the #185 index `ux_cards_owner_player_active` holds), then sets active
    slots and bench order. IntegrityError -> 409.
  * `PUT /roster`: `save_roster` (plain) + `save_roster_route` (decorated with
    RATE_LIMIT_ROSTER_MUTATION keyed by key_by_user_or_ip). Body:
    `active: list[int] = Field(max_length=ROSTER_LIMIT)`,
    `bench: list[int] = Field(max_length=500)`,
    `base_version: str = Field(min_length=1, max_length=64)`.
  * Single-card routes (`/roster/{id}/activate`, `/deactivate`, `/roster/swap`,
    `/roster/reorder`) stay for the Twitch panel.

Frontend (frontend/app-roster.js, frontend/app-globals.js, frontend/style.css):
  * Keyed render `renderRosterLayout()` (reuse nodes by `data-card-id`),
    `flipMove()` and `prefersReducedMotion()` in app-globals.js.
  * Pointer drag controller; HTML5 `draggable` / `dragstart` / `drop` handlers removed.
  * Autosave queue: idle -> waiting (600 ms debounce) -> saving -> idle, plus
    error; single flight; flush on visibilitychange/pagehide (fetch keepalive),
    tab or week change, and lock under 2 minutes.

Stories:
  1. Moves Apply Instantly and Glide Into Place          (TestMovesApplyInstantlyAndGlideIntoPlace)
  2. Drag Follows the Pointer and the Roster Makes Room  (TestDragFollowsPointerAndRosterMakesRoom)
  3. The Layout Saves Itself                             (TestLayoutSavesItself)
  4. Saves Are Atomic and Never Overwrite Changes Made Elsewhere
                                                         (TestSavesAreAtomicAndNeverOverwrite)

Developer notes
---------------
  * Roster helpers / race mechanics: copy `file_db_sessionmaker`,
    `_run_concurrently`, `_make_user`, `_make_player`, `_make_card` from
    tests/test_issue_185_atomic_roster_and_token_operations.py. Run the race
    test against code without the write-lock-first step and confirm it fails
    (lessons-learned 2026-10-13).
  * Rate limit: follow tests/test_issue_184_action_throttling.py
    (`_route_limits`, `_find_route`, `_limit_shape`, `_limit_amount`, the small
    FastAPI app with `app.state.limiter = routers.cards.limiter`). The #184
    test `test_every_non_admin_write_route_has_explicit_limit` must keep passing
    with the new PUT route.
  * Node harness: follow tests/test_issue_156_schedule_visuals.py (`_node()` from
    test_issue_159, `_fn_body`/`_read` from test_issue_151): run app-roster.js
    with app-globals.js helpers against a fake DOM, fake fetch (recording
    method/url/body/keepalive), fake timers (to step the 600 ms debounce and
    the 2 s "Saved" status) and a stubbed `matchMedia` for reduced motion.
    Without Node only the static checks should run, with no skip, so the #85
    suite-size tripwire stays exact. Bump test_issue_85's baseline from the
    real "N passed".
  * Existing tests pin the old behaviour and will need updating: grep
    backend/tests for `_rosterBusy`, `draggable`, `dragstart` and `loadRoster`
    (e.g. #185 story 5 in-flight guard, #93 drop-zone highlights).
  * New CSS goes before the "GUIDED TOUR (issue #144)" section of style.css
    (lessons-learned 2026-10-14).

Run with: cd backend && python -m pytest tests/test_issue_186_my_team_save_roster.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hashlib
import json
import re
import subprocess
import time

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import models  # noqa: F401  (registers every table before the db fixture runs)
from models import Card, Player, User, Week
from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _fn_body, _media_body, _read
from tests.test_issue_159_flicker_free_tab_switching import _node
from tests.test_issue_184_action_throttling import (
    _app, _find_route, _limit_amount, _limit_shape, _register, _route_limits,
)
from tests.test_issue_185_atomic_roster_and_token_operations import (
    _make_card, _make_player, _make_user, _run_concurrently, file_db_sessionmaker,  # noqa: F401
)


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
ROSTER_JS = os.path.join(FRONTEND_DIR, "app-roster.js")
GLOBALS_JS = os.path.join(FRONTEND_DIR, "app-globals.js")
STYLE_CSS = os.path.join(FRONTEND_DIR, "style.css")
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------

def _uid(user):
    return {"user_id": user.id}


def _seed(db, active=3, bench=2):
    """A user with `active` roster cards (slots 0..) and `bench` bench cards, one
    player each. Returns (user, roster card ids, bench card ids)."""
    u = _make_user(db)
    act, ben = [], []
    for i in range(active):
        p = _make_player(db, player_id=100 + i, name=f"A{i}")
        act.append(_make_card(db, u.id, p.id, is_active=True, slot_index=i).id)
    for i in range(bench):
        p = _make_player(db, player_id=200 + i, name=f"B{i}")
        ben.append(_make_card(db, u.id, p.id, is_active=False, slot_index=i).id)
    db.commit()
    return u, act, ben


def _stored(db, user_id):
    """{card id: (is_active, slot_index)} straight from the cards table."""
    db.expire_all()
    return {c.id: (bool(c.is_active), c.slot_index)
            for c in db.query(Card).filter(Card.owner_id == user_id).all()}


def _save(db, user, active, bench, base_version):
    from routers.cards import RosterLayoutRequest, save_roster
    return save_roster(RosterLayoutRequest(active=active, bench=bench, base_version=base_version),
                       _uid(user), db)


def _version(db, user):
    from card_utils import roster_version
    return roster_version(db, user.id, 5)


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Frontend Node harness: app-roster.js with the app-globals.js helpers it uses,
# a small fake DOM with a fixed layout (roster slots 200 px apart at y 0..255, the
# bench at y 400..655), fake timers and animation frames, and a fake fetch.
# ---------------------------------------------------------------------------

_HARNESS = r"""
let NOW = __NOW__;
Date.now = () => NOW;
const REDUCED = __REDUCED__;
let ROSTER = __DATA__;
const NEXT_WEEK = { id: 6, label: "Week 6", is_locked: false, start_time: ROSTER.week ? ROSTER.week.start_time + 604800 : 0, end_time: 0 };

let _timers = [], _tid = 0;
globalThis.setTimeout = (fn, ms) => { const id = ++_tid; _timers.push({ id, at: NOW + (ms || 0), fn }); return id; };
globalThis.clearTimeout = id => { _timers = _timers.filter(t => t.id !== id); };
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(r => setImmediate(r)); };
async function advance(ms) {
  const end = NOW + ms;
  for (;;) {
    _timers.sort((a, b) => a.at - b.at || a.id - b.id);
    const t = _timers[0];
    if (!t || t.at > end) break;
    _timers.shift();
    NOW = t.at;
    t.fn();
    await settle();
  }
  NOW = end;
  await settle();
}
let _frames = [], _fid = 0;
globalThis.requestAnimationFrame = fn => { const id = ++_fid; _frames.push({ id, fn }); return id; };
globalThis.cancelAnimationFrame = id => { _frames = _frames.filter(f => f.id !== id); };
function frame() { const fs = _frames; _frames = []; fs.forEach(f => f.fn(NOW)); }

class ClassList {
  constructor() { this.set = new Set(); }
  add(...c) { c.forEach(x => this.set.add(x)); }
  remove(...c) { c.forEach(x => this.set.delete(x)); }
  contains(c) { return this.set.has(c); }
  toggle(c, force) { const on = force === undefined ? !this.set.has(c) : !!force; if (on) this.set.add(c); else this.set.delete(c); return on; }
}
const GRID_TOP = { rosterActiveGrid: 0, benchGrid: 400 };
class El {
  constructor(tag, id) {
    this.tagName = String(tag).toUpperCase(); this.id = id || ""; this.children = []; this.parentNode = null;
    this.classList = new ClassList(); this.dataset = {}; this.attrs = {}; this.listeners = {};
    this._html = ""; this.textContent = ""; this.innerHTMLWrites = 0; this.transformLog = []; this.value = "";
    const self = this;
    this.style = new Proxy({}, { set(o, k, v) { if (k === "transform" && v) self.transformLog.push(v); o[k] = v; return true; } });
  }
  get className() { return [...this.classList.set].join(" "); }
  set className(v) { this.classList.set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); this.innerHTMLWrites++; }
  get isConnected() { let n = this; while (n) { if (n === document.body) return true; n = n.parentNode; } return false; }
  get offsetWidth() { return 0; }
  appendChild(c) { if (c.parentNode) c.parentNode._drop(c); c.parentNode = this; this.children.push(c); return c; }
  _drop(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; }
  replaceChildren(...nodes) { this.children.slice().forEach(c => { c.parentNode = null; }); this.children = []; nodes.forEach(n => this.appendChild(n)); }
  remove() { if (this.parentNode) this.parentNode._drop(this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  removeEventListener(t, f) { if (this.listeners[t]) this.listeners[t] = this.listeners[t].filter(x => x !== f); }
  focus() { document.activeElement = this; }
  matches(sel) {
    return sel.split(",").some(part => {
      const m = part.trim().match(/^([a-z]+)?(#[\w-]+)?((?:\.[\w-]+)*)((?:\[[\w-]+\])*)$/);
      if (!m) throw new Error("unsupported selector " + part);
      if (m[1] && this.tagName !== m[1].toUpperCase()) return false;
      if (m[2] && this.id !== m[2].slice(1)) return false;
      for (const c of (m[3].match(/\.[\w-]+/g) || [])) if (!this.classList.contains(c.slice(1))) return false;
      for (const a of (m[4].match(/\[[\w-]+\]/g) || [])) {
        const name = a.slice(1, -1);
        const key = name.slice(5).replace(/-(\w)/g, (_, ch) => ch.toUpperCase());
        if (this.dataset[key] === undefined) return false;
      }
      return true;
    });
  }
  closest(sel) { let n = this; while (n && n.matches) { if (n.matches(sel)) return n; n = n.parentNode; } return null; }
  querySelectorAll(sel) { const out = []; const walk = n => n.children.forEach(c => { if (c.matches(sel)) out.push(c); walk(c); }); walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getBoundingClientRect() {
    let left = 0, top = 0, width = 0, height = 0;
    const p = this.parentNode;
    if (this.id in GRID_TOP) { top = GRID_TOP[this.id]; width = 1000; height = 260; }
    else if (p && p.id in GRID_TOP) { left = p.children.indexOf(this) * 200; top = GRID_TOP[p.id]; width = 180; height = 255; }
    else if (this.style.left !== undefined) { left = parseFloat(this.style.left); top = parseFloat(this.style.top); width = 180; height = 255; }
    const t = /translate\(([-\d.]+)px, ([-\d.]+)px\)/.exec(this.style.transform || "");
    if (t) { left += parseFloat(t[1]); top += parseFloat(t[2]); }
    return { left, top, width, height, right: left + width, bottom: top + height };
  }
}
const els = {};
const listenersOf = o => o.listeners;
const win = { listeners: {}, innerHeight: 800, scrollY: 0, scrolls: [],
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
  removeEventListener(t, f) { if (this.listeners[t]) this.listeners[t] = this.listeners[t].filter(x => x !== f); },
  matchMedia: q => ({ matches: REDUCED && q.includes("reduce") }),
  scrollBy(x, y) { this.scrolls.push(y); }, scrollTo() {} };
globalThis.window = win;
const document = {
  listeners: {}, activeElement: null, visibilityState: "visible",
  body: new El("body"),
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
  removeEventListener(t, f) { if (this.listeners[t]) this.listeners[t] = this.listeners[t].filter(x => x !== f); },
  createElement: tag => new El(tag),
  getElementById(id) { if (!els[id]) els[id] = new El("div", id); return els[id]; },
  querySelector(sel) { return this.body.querySelector(sel); },
  querySelectorAll(sel) { return this.body.querySelectorAll(sel); },
  elementFromPoint(x, y) {
    for (const gid of ["rosterActiveGrid", "benchGrid"]) {
      const g = els[gid];
      for (const c of g.children) {
        const r = c.getBoundingClientRect();
        if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) return c;
      }
      const r = g.getBoundingClientRect();
      if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) return g;
    }
    return null;
  },
};
globalThis.document = document;
for (const id of ["rosterActiveGrid", "benchGrid", "rosterStatus", "rosterRetryBtn", "rosterCombined", "benchSection", "rosterWeekSelect"]) {
  document.body.appendChild(document.getElementById(id));
}
const tabTeam = document.getElementById("tab-team"); tabTeam.className = "tab-content active"; document.body.appendChild(tabTeam);
const tabSchedule = document.getElementById("tab-schedule"); tabSchedule.className = "tab-content"; document.body.appendChild(tabSchedule);

function fire(target, type, props = {}) {
  const ev = { type, target, cancelable: true, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; },
               pointerId: 1, pointerType: "mouse", button: 0, clientX: 0, clientY: 0, ...props };
  const path = [];
  for (let n = target; n; n = n.parentNode) path.push(n);
  if (target !== win && target !== document) path.push(document, win);
  for (const n of path) for (const f of (n.listeners[type] || []).slice()) f(ev);
  return ev;
}

const fetchLog = [];
let PUT_MODE = "ok";
let RETRY_AFTER = null;
let putSeq = 1;
const heldPuts = [];
const resp = (status, data, headers = {}) => ({ ok: status >= 200 && status < 300, status, json: async () => data,
                                                headers: { get: k => headers[k] ?? null } });
function cardsById() { const m = new Map(); [...ROSTER.active, ...ROSTER.bench].forEach(c => m.set(c.id, c)); return m; }
function echoRoster(body) {
  const m = cardsById();
  const active = [];
  body.active.forEach((id, i) => { if (id != null) active.push({ ...m.get(id), is_active: true, slot_index: i }); });
  const bench = body.bench.map((id, i) => ({ ...m.get(id), is_active: false, slot_index: i }));
  return { ...JSON.parse(JSON.stringify(ROSTER)), active, bench, version: "v" + (++putSeq) };
}
globalThis.fetch = (url, opts = {}) => {
  const method = opts.method || "GET";
  const body = opts.body ? JSON.parse(opts.body) : null;
  fetchLog.push({ url, method, body, keepalive: !!opts.keepalive });
  if (method === "GET" && url.startsWith("/roster/")) return Promise.resolve(resp(200, JSON.parse(JSON.stringify(ROSTER))));
  if (method === "PUT" && url === "/roster") {
    if (PUT_MODE === "ok") return Promise.resolve(resp(200, echoRoster(body)));
    if (PUT_MODE === "hold") return new Promise(res => heldPuts.push(() => res(resp(200, echoRoster(body)))));
    if (PUT_MODE === "holdconflict") return new Promise(res => heldPuts.push(() => res(resp(409, { detail: "Your roster changed elsewhere" }, { "X-Roster-Conflict": "version" }))));
    if (PUT_MODE === "neterr") return Promise.reject(new TypeError("Failed to fetch"));
    if (PUT_MODE === "conflict") return Promise.resolve(resp(409, { detail: "Your roster changed elsewhere" }, { "X-Roster-Conflict": "version" }));
    if (PUT_MODE === "rule") return Promise.resolve(resp(409, { detail: "A card for this player is already active" }));
    if (PUT_MODE === "422") return Promise.resolve(resp(422, { detail: [{ msg: "Field required" }] }));
    if (PUT_MODE === "429") return Promise.resolve(resp(429, { detail: "Too many requests. Wait a moment and try again." }, RETRY_AFTER ? { "Retry-After": RETRY_AFTER } : {}));
    if (PUT_MODE === "nextweek") { const r = echoRoster(body); r.week = NEXT_WEEK; return Promise.resolve(resp(200, r)); }
  }
  return Promise.reject(new Error("unexpected fetch " + method + " " + url));
};

const API = "";
let activeUserId = 1;
let activeMustChangePassword = false;
let _weeks = [];
let _tokenName = "Tokens";
const opened = [];
function updateTokenDisplay() {}
function cardImageUrl(id) { return `/cards/${id}/image`; }
function showCard(c) { opened.push(c.id); }
function setStatus(id, msg) { document.getElementById(id).textContent = msg; }
async function withBusy(btn, fn) { return fn(); }
function loadSchedule() {}
const _tabScroll = {};
__GLOBALS__
__ROSTER__

const node = id => _rosterNodes.get(id);
const grid = id => els[id];
const ids = gid => grid(gid).children.map(c => c.dataset.cardId ? Number(c.dataset.cardId) : (c.dataset.slotIndex !== undefined ? "empty:" + c.dataset.slotIndex : "text"));
function center(el) { const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }
const puts = () => fetchLog.filter(f => f.method === "PUT");
const gets = () => fetchLog.filter(f => f.method === "GET");
const status = () => els.rosterStatus.textContent;
const layout = () => ({ active: _layout.active.slice(), bench: _layout.bench.slice(), version: _layout.version });
function img(cardId) { const i = new El("img"); i.className = "card-img"; i.parentNode = node(cardId); return i; }
async function press(cardId, type = "mouse") {
  const [x, y] = center(node(cardId));
  fire(node(cardId), "pointerdown", { pointerType: type, clientX: x, clientY: y });
  if (type === "touch") await advance(250);
  return [x, y];
}
function moveTo(x, y, type = "mouse") { fire(win, "pointermove", { pointerType: type, clientX: x, clientY: y }); frame(); }
async function drag(cardId, to, type = "mouse") {
  const [sx, sy] = await press(cardId, type);
  moveTo(sx + 10, sy + 10, type);
  const [x, y] = Array.isArray(to) ? to : center(to);
  moveTo(x, y, type);
  fire(win, "pointerup", { pointerType: type, clientX: x, clientY: y });
}
(async () => {
  const out = {};
  await loadRoster(null);
__STEPS__
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

_NOW_S = 1_760_000_000


def _c(cid, pid, slot=None, active=False, removed=False):
    c = {"id": cid, "card_type": "common", "is_active": active, "slot_index": slot,
         "player_id": pid, "player_name": f"P{pid}", "total_points": 1.0,
         "subbed_in": False, "subbed_out": False, "subbed_in_for": None, "modifiers": []}
    if removed:
        c["player_is_active"] = False
    return c


def _roster(active=None, bench=None, locked=False, starts_in=3 * 86400):
    """Default: roster 1, 2, 3 in slots 0-2; bench 4, then 5 (same player as card 1),
    then 6 (a removed player)."""
    if active is None:
        active = [_c(1, 101, 0, True), _c(2, 102, 1, True), _c(3, 103, 2, True)]
    if bench is None:
        bench = [_c(4, 104, 0), _c(5, 101, 1), _c(6, 106, 2, removed=True)]
    start = _NOW_S + starts_in
    return {"active": active, "bench": bench, "combined_value": 3.0, "tokens": 2, "season_points": 0,
            "week": {"id": 5, "label": "Week 5", "is_locked": locked, "start_time": start,
                     "end_time": start + 86400, "substitutions_done": False},
            "substitutions_done": False, "substitution_delay_hours": 24, "version": "v1"}


def _full_roster():
    return _roster(active=[_c(i, 100 + i, i - 1, True) for i in range(1, 6)], bench=[_c(6, 106, 0)])


def _globals_src():
    js = _read(GLOBALS_JS)
    decl = re.search(r"^const _lastHtml = new WeakMap\(\);$", js, re.M).group(0)
    flip = re.search(r"^const FLIP_DURATION_MS = \d+;$", js, re.M).group(0)
    names = ("renderIfChanged", "forgetRendered", "_escHtml", "switchTab", "prefersReducedMotion", "flipMove")
    return "\n".join([decl, flip] + [_fn_body(js, n) + "\n}\n" for n in names])


def _run(steps, data=None, reduced=False):
    """Run `steps` (JS in an async function after `await loadRoster(null)`, filling
    `out`); returns `out`, or None when Node is not installed."""
    node = _node()
    if not node:
        return None
    script = (_HARNESS.replace("__NOW__", str(_NOW_S * 1000))
              .replace("__REDUCED__", "true" if reduced else "false")
              .replace("__DATA__", json.dumps(data if data is not None else _roster()))
              .replace("__GLOBALS__", _globals_src())
              .replace("__ROSTER__", _read(ROSTER_JS))
              .replace("__STEPS__", steps))
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-3000:]
    return json.loads(res.stdout)


def _js():
    return _read(ROSTER_JS)


def _css():
    return _read(STYLE_CSS)


def _rule(css, selector):
    """Bodies of the rules whose selector list contains exactly `selector`."""
    return [body for sel, body in _css_blocks(css, re.escape(selector))
            if selector in [x.strip() for x in sel.split(",")]]


def _before_tour(css):
    return css[:css.index("GUIDED TOUR (issue #144)")]


# ---------------------------------------------------------------------------
# Story 1: Moves Apply Instantly and Glide Into Place
# ---------------------------------------------------------------------------

class TestMovesApplyInstantlyAndGlideIntoPlace:
    """
    - Local first: dropping a card (reorder within a zone, bench -> roster,
      roster -> bench, swap) changes the page's layout at once, with no network wait.
    - Glide: the dropped card glides from where it was released to its slot, and
      every card that changes position glides from its old place (FLIP, about
      220 ms, `--ease-out`).
    - No refetch: the page doesn't re-fetch or redraw the roster after a move. It
      renders from its local layout, keyed by card id, so the DOM nodes move
      rather than being rebuilt.
    - Rules checked locally: a move that would break a rule is refused locally with
      the cards gliding back: more than ROSTER_LIMIT active cards; two active cards
      of the same player; an inactive (removed) player on the roster. The status
      line names the rule.
    - Keyboard and touch: the keyboard toggle (Enter/Space on a focused card) and
      tapping go through the same local layout and animation.
    - Reduced motion: cards jump to their places with no glide.
    """

    _DROPS = {
        # (drag card, target, expected active, expected bench)
        "reorder_within_zone": ("1", "node(3)", [2, 3, 1, None, None], [4, 5, 6]),
        "bench_to_roster": ("4", "grid('rosterActiveGrid').children[3]", [1, 2, 3, 4, None], [5, 6]),
        "roster_to_bench": ("3", "[900, 527]", [1, 2, None, None, None], [4, 5, 6, 3]),
        "swap": ("4", "node(2)", [1, 4, 3, None, None], [2, 5, 6]),
    }

    @pytest.mark.parametrize("move", ["reorder_within_zone", "bench_to_roster", "roster_to_bench", "swap"])
    def test_drop_applies_layout_locally_before_any_network_response(self, move):
        """Local first: each kind of drop updates `_layout` and the DOM synchronously, before any fetch resolves (Node harness)."""
        card, target, active, bench = self._DROPS[move]
        assert "_layout = { active: next.active.slice()" in _fn_body(_js(), "_commitRosterLayout")
        out = _run(f"""
  PUT_MODE = "hold";
  const fetchesBefore = fetchLog.length;
  await drag({card}, {target});
  out.layout = layout();
  out.active = ids("rosterActiveGrid");
  out.bench = ids("benchGrid");
  out.fetchesAfterDrop = fetchLog.length - fetchesBefore;
""")
        if out is None:
            return
        assert out["layout"]["active"] == active
        assert out["layout"]["bench"] == bench
        assert out["active"] == [a if a is not None else f"empty:{i}" for i, a in enumerate(active)]
        assert out["bench"] == bench
        assert out["fetchesAfterDrop"] == 0

    def test_flip_move_glides_changed_cards_about_220ms_ease_out(self):
        """Glide: `flipMove()` in app-globals.js animates every moved card from its old rect with ~220 ms and `var(--ease-out)`; the dropped card starts from its release point."""
        flip = _fn_body(_read(GLOBALS_JS), "flipMove")
        assert re.search(r"^const FLIP_DURATION_MS = 220;$", _read(GLOBALS_JS), re.M)
        assert "el.style.transition = `transform ${duration}ms var(--ease-out)`;" in flip
        assert "opts.from && opts.from.el === el ? opts.from.rect" in flip
        out = _run("""
  // Bench card 4 to the empty slot 3, released 10 px right of and 12.5 px below its centre.
  const [sx, sy] = await press(4);
  moveTo(sx + 10, sy + 10);
  moveTo(700, 140);
  node(4).transformLog.length = 0;
  fire(win, "pointerup", { clientX: 700, clientY: 140 });
  out.dropped = node(4).transformLog;
  out.droppedTransition = node(4).style.transition;
  // Roster card 1 onto card 3: cards 2 and 3 slide one slot left.
  await drag(1, node(3));
  out.slid = node(2).transformLog;
  out.slidTransition = node(2).style.transition;
""")
        if out is None:
            return
        assert out["dropped"][0] == "translate(10px, 12.5px)"
        assert out["droppedTransition"] == "transform 220ms var(--ease-out)"
        assert "translate(200px, 0px)" in out["slid"]
        assert out["slidTransition"] == "transform 220ms var(--ease-out)"

    def test_move_does_not_refetch_and_reuses_card_nodes(self):
        """No refetch: after a move `loadRoster()` and `GET /roster/...` are not called, and the same DOM node (by `data-card-id`) is moved, not rebuilt (Node harness)."""
        assert "loadRoster(" not in _fn_body(_js(), "_commitRosterLayout")
        out = _run("""
  const before = node(1);
  const writes = before.innerHTMLWrites;
  await drag(1, node(3));
  await advance(3000);
  out.gets = gets().length;
  out.puts = puts().length;
  out.same = grid("rosterActiveGrid").children[2] === before;
  out.rewrites = before.innerHTMLWrites - writes;
""")
        if out is None:
            return
        assert out == {"gets": 1, "puts": 1, "same": True, "rewrites": 0}

    def test_keyed_render_keeps_empty_slot_placeholders_and_slot_gaps(self):
        """No refetch: `renderRosterLayout()` keeps empty slots as placeholders with the `slot_index` gaps kept."""
        data = _roster(active=[_c(1, 101, 0, True), _c(2, 102, 3, True)], bench=[_c(4, 104, 0)])
        out = _run("""
  out.active = ids("rosterActiveGrid");
  const empty = grid("rosterActiveGrid").children[1];
  await drag(4, grid("rosterActiveGrid").children[2]);
  out.after = ids("rosterActiveGrid");
  out.emptyKept = grid("rosterActiveGrid").children[1] === empty;
""", data=data)
        if out is None:
            return
        assert out["active"] == [1, "empty:1", "empty:2", 2, "empty:4"]
        assert out["after"] == [1, "empty:1", 4, 2, "empty:4"]
        assert out["emptyKept"] is True

    def test_local_rule_check_refuses_more_than_roster_limit_active(self):
        """Rules checked locally (failure path): moving a bench card into a full roster with no swap target is refused, the layout is unchanged and the status line names the roster limit."""
        out = _run("""
  const before = layout();
  await drag(6, [990, 100]);
  out.same = JSON.stringify(layout()) === JSON.stringify(before);
  out.status = status();
  toggleCardZone(6);
  out.sameAfterKey = JSON.stringify(layout()) === JSON.stringify(before);
  out.statusAfterKey = status();
""", data=_full_roster())
        if out is None:
            return
        assert out == {"same": True, "status": "Roster full (5 cards max)",
                       "sameAfterKey": True, "statusAfterKey": "Roster full (5 cards max)"}

    def test_local_rule_check_refuses_two_active_cards_of_same_player(self):
        """Rules checked locally (failure path): activating a second card of an already active player is refused and the status line names the rule."""
        out = _run("""
  const before = layout();
  await drag(5, grid("rosterActiveGrid").children[3]);
  out.same = JSON.stringify(layout()) === JSON.stringify(before);
  out.status = status();
  // A swap with the same player's roster card is allowed: the outgoing card is benched.
  await drag(5, node(1));
  out.swapped = layout().active;
""")
        if out is None:
            return
        assert out["same"] is True
        assert out["status"] == "A card for this player is already active"
        assert out["swapped"] == [5, 2, 3, None, None]

    def test_local_rule_check_refuses_removed_player_on_roster(self):
        """Rules checked locally (failure path): moving a card of an inactive (removed) player onto the roster is refused and the status line names the rule."""
        out = _run("""
  const before = layout();
  await drag(6, grid("rosterActiveGrid").children[4]);
  out.same = JSON.stringify(layout()) === JSON.stringify(before);
  out.status = status();
""")
        if out is None:
            return
        assert out == {"same": True, "status": "A removed player can't be on the roster"}

    def test_refused_move_glides_cards_back_and_sends_no_save(self):
        """Rules checked locally: a refused move restores the previous layout through flipMove and never schedules a `PUT /roster`."""
        out = _run("""
  const [sx, sy] = await press(5);
  moveTo(sx + 10, sy + 10);
  moveTo(700, 140);
  node(5).transformLog.length = 0;
  fire(win, "pointerup", { clientX: 700, clientY: 140 });
  out.glide = node(5).transformLog;
  out.bench = ids("benchGrid");
  await advance(5000);
  out.puts = puts().length;
""")
        if out is None:
            return
        assert out["glide"] and out["glide"][0].startswith("translate(")
        assert out["bench"] == [4, 5, 6]
        assert out["puts"] == 0

    def test_keyboard_toggle_and_tap_use_local_layout_path(self):
        """Keyboard and touch: Enter/Space on a focused card and a tap edit `_layout` and animate through the same path as a drop, with no single-card route call."""
        out = _run("""
  const ev = fire(img(1), "keydown", { key: "Enter" });
  out.prevented = ev.defaultPrevented;
  out.afterEnter = layout();
  out.slid = node(1).transformLog.length > 0;
  fire(img(4), "keydown", { key: " " });
  out.afterSpace = layout();
  await drag(5, node(2), "touch");
  out.afterTouch = layout();
  await advance(600);
  out.urls = fetchLog.map(f => f.method + " " + f.url);
""")
        if out is None:
            return
        assert out["prevented"] is True
        assert out["afterEnter"]["active"] == [None, 2, 3, None, None]
        assert out["afterEnter"]["bench"] == [1, 4, 5, 6]
        assert out["slid"] is True
        assert out["afterSpace"]["active"] == [4, 2, 3, None, None]
        assert out["afterTouch"]["active"] == [4, 5, 3, None, None]
        assert out["afterTouch"]["bench"] == [1, 2, 6]
        assert out["urls"] == ["GET /roster/1", "PUT /roster"]

    def test_reduced_motion_moves_apply_without_glide(self):
        """Reduced motion: with `prefersReducedMotion()` true, moves apply instantly and `flipMove()` plays no animation (Node harness with stubbed matchMedia)."""
        assert "if (prefersReducedMotion()) return;" in _fn_body(_read(GLOBALS_JS), "flipMove")
        out = _run("""
  await drag(1, node(3));
  toggleCardZone(2);
  out.layout = layout().active;
  out.glides = [1, 2, 3, 4, 5, 6].map(id => node(id).transformLog.length);
""", reduced=True)
        if out is None:
            return
        assert out["layout"] == [None, 3, 1, None, None]
        assert out["glides"] == [0, 0, 0, 0, 0, 0]

    def test_reduced_motion_css_turns_roster_transitions_off(self):
        """Reduced motion (static): style.css has a `prefers-reduced-motion: reduce` block disabling transitions on lifted card, live gap and swap preview, placed before the GUIDED TOUR section."""
        css = _before_tour(_css())
        blocks = []
        pos = 0
        while True:
            i = css.find("@media (prefers-reduced-motion: reduce)", pos)
            if i == -1:
                break
            blocks.append(_media_body(css[i:], "prefers-reduced-motion: reduce"))
            pos = i + 1
        roster = [b for b in blocks if ".roster-drag-clone" in b]
        assert len(roster) == 1
        body = roster[0]
        for sel in (".roster-drag-clone", ".card-slot.drag-placeholder", ".card-slot.swap-preview .card-img"):
            assert sel in body
        assert "transition: none !important;" in body and "animation: none !important;" in body


# ---------------------------------------------------------------------------
# Story 2: Drag Follows the Pointer and the Roster Makes Room
# ---------------------------------------------------------------------------

class TestDragFollowsPointerAndRosterMakesRoom:
    """
    - Pointer drag: dragging uses Pointer Events instead of HTML5 drag-and-drop.
      The picked-up card lifts (scale 1.04, shadow) and follows the pointer.
    - Live preview: the slot under the pointer previews the result. In a zone, the
      other cards slide aside; over an occupied roster slot, a swap preview shows
      the replaced card dimmed with an arrow to the bench.
    - Touch: a press of 250 ms picks a card up; moving before that scrolls the page
      as usual; the page doesn't scroll while a card is held, except near the top
      or bottom edge, where it auto-scrolls.
    - Cancel: releasing outside any zone, pressing Escape, or a cancelled pointer
      returns the card to its place with a glide.
    - Unchanged behaviour: the existing drop-zone highlights (#93) stay, and a
      click without movement still opens the card viewer.
    - Locked weeks: cards can't be picked up, as today.
    """

    def test_roster_drag_wires_pointer_events(self):
        """Pointer drag (static): app-roster.js registers pointerdown, pointermove, pointerup and pointercancel handlers for roster cards."""
        js = _js()
        assert 'grid.addEventListener("pointerdown", _onRosterPointerDown);' in js
        down = _fn_body(js, "_onRosterPointerDown")
        assert 'window.addEventListener("pointermove", _onRosterPointerMove);' in down
        assert 'window.addEventListener("pointerup", _onRosterPointerUp);' in down
        assert 'window.addEventListener("pointercancel", _onRosterPointerCancel);' in down
        end = _fn_body(js, "_endRosterPointer")
        for t in ("pointermove", "pointerup", "pointercancel"):
            assert f'window.removeEventListener("{t}",' in end

    def test_no_html5_draggable_handlers_left(self):
        """Pointer drag (static, failure path): app-roster.js has no `draggable="true"` markup and no dragstart/dragover/drop/dragend listeners."""
        js = _js()
        assert 'draggable="true"' not in js
        assert not re.search(r'addEventListener\("(dragstart|dragover|dragleave|drop|dragend)"', js)
        assert "dataTransfer" not in js and "_initDragAndDrop" not in js
        assert 'draggable="true"' not in _css() and '[draggable="true"]' not in _css()

    def test_pointer_drag_starts_after_6px_mouse_move_and_clone_follows(self):
        """Pointer drag: a mouse drag starts after >6 px movement and a fixed-position clone follows pointermove (Node harness)."""
        out = _run("""
  const [x, y] = await press(2);
  fire(win, "pointermove", { clientX: x + 5, clientY: y });
  out.beforeThreshold = !!(_drag && _drag.active);
  out.clonesBefore = document.body.querySelectorAll(".roster-drag-clone").length;
  fire(win, "pointermove", { clientX: x + 7, clientY: y });
  out.afterThreshold = _drag.active;
  const clone = document.body.querySelector(".roster-drag-clone");
  out.cloneStart = [clone.style.left, clone.style.top];
  fire(win, "pointermove", { clientX: x + 57, clientY: y + 30 });
  out.cloneMoved = [clone.style.left, clone.style.top];
  out.placeholder = node(2).classList.contains("drag-placeholder");
  fire(document, "keydown", { key: "Escape" });
  out.clonesAfter = document.body.querySelectorAll(".roster-drag-clone").length;
""")
        if out is None:
            return
        assert out["beforeThreshold"] is False and out["clonesBefore"] == 0
        assert out["afterThreshold"] is True
        # Card 2's rect starts at (200, 0); the clone keeps the grab offset.
        assert out["cloneStart"] == ["207px", "0px"]
        assert out["cloneMoved"] == ["257px", "30px"]
        assert out["placeholder"] is True
        assert out["clonesAfter"] == 0

    def test_lifted_card_css_scale_and_shadow(self):
        """Pointer drag (static): style.css gives the lifted card `scale(1.04)` and a box-shadow."""
        css = _before_tour(_css())
        clone = _rule(css, ".roster-drag-clone")
        assert clone and "transform: scale(1.04);" in clone[0] and "position: fixed;" in clone[0]
        assert "pointer-events: none;" in clone[0]
        shadow = _rule(css, ".roster-drag-clone .card-img")
        assert shadow and "box-shadow:" in shadow[0]

    def test_live_preview_reorders_preview_copy_not_layout(self):
        """Live preview: hovering a slot renders a preview from a copy of `_layout` (other cards slide aside); `_layout` itself is unchanged until pointerup."""
        out = _run("""
  const [x, y] = await press(1);
  moveTo(x + 10, y);
  moveTo(...center(node(3)));
  out.dom = ids("rosterActiveGrid");
  out.layout = layout().active;
  out.preview = _drag.preview.active;
  out.slid = node(2).transformLog.length > 0;
  fire(win, "pointerup", { clientX: 490, clientY: 127 });
  out.dropped = layout().active;
""")
        if out is None:
            return
        assert out["dom"] == [2, 3, 1, "empty:3", "empty:4"]
        assert out["layout"] == [1, 2, 3, None, None]
        assert out["preview"] == [2, 3, 1, None, None]
        assert out["slid"] is True
        assert out["dropped"] == [2, 3, 1, None, None]

    def test_swap_preview_dims_replaced_card_with_arrow_to_bench(self):
        """Live preview: over an occupied roster slot, the replaced card gets the swap-preview class (dimmed, arrow to the bench)."""
        css = _before_tour(_css())
        dim = _rule(css, ".card-slot.swap-preview .card-img")
        assert dim and "opacity: 0.4;" in dim[0]
        arrow = _rule(css, ".card-slot.swap-preview::after")
        assert arrow and 'content: "↓";' in arrow[0]
        out = _run("""
  const [x, y] = await press(4);
  moveTo(x + 10, y);
  moveTo(...center(node(2)));
  out.swap = node(2).classList.contains("swap-preview");
  out.dom = ids("rosterActiveGrid");
  moveTo(...center(node(3)));
  out.movedOn = [node(2).classList.contains("swap-preview"), node(3).classList.contains("swap-preview")];
  fire(document, "keydown", { key: "Escape" });
  out.cleared = node(3).classList.contains("swap-preview");
""")
        if out is None:
            return
        assert out["swap"] is True
        assert out["dom"] == [1, 2, 3, "empty:3", "empty:4"]
        assert out["movedOn"] == [False, True]
        assert out["cleared"] is False

    def test_touch_long_press_250ms_picks_card_up(self):
        """Touch: a touch pointerdown held 250 ms without moving starts the drag and sets `touch-action: none` only on the held card."""
        out = _run("""
  const [x, y] = center(node(2));
  fire(node(2), "pointerdown", { pointerType: "touch", clientX: x, clientY: y });
  await advance(249);
  out.early = _drag.active;
  await advance(1);
  out.held = _drag.active;
  out.touchAction = [1, 2, 3].map(id => node(id).style.touchAction || "");
  fire(win, "pointerup", { pointerType: "touch", clientX: x, clientY: y });
  out.released = node(2).style.touchAction || "";
""")
        if out is None:
            return
        assert out["early"] is False
        assert out["held"] is True
        assert out["touchAction"] == ["", "none", ""]
        assert out["released"] == ""

    def test_touch_move_before_long_press_does_not_start_drag(self):
        """Touch (failure path): moving before 250 ms cancels the pending drag so the page scrolls as usual; no card is lifted."""
        out = _run("""
  const [x, y] = center(node(2));
  fire(node(2), "pointerdown", { pointerType: "touch", clientX: x, clientY: y });
  await advance(100);
  const scroll = fire(document, "touchmove", {});
  out.scrollPrevented = scroll.defaultPrevented;
  fire(win, "pointermove", { pointerType: "touch", clientX: x, clientY: y + 30 });
  out.drag = _drag;
  await advance(300);
  out.clones = document.body.querySelectorAll(".roster-drag-clone").length;
  out.placeholder = node(2).classList.contains("drag-placeholder");
""")
        if out is None:
            return
        assert out == {"scrollPrevented": False, "drag": None, "clones": 0, "placeholder": False}

    def test_held_card_near_viewport_edge_auto_scrolls(self):
        """Touch: while a card is held, a pointer near the top or bottom edge auto-scrolls the page; elsewhere the page does not scroll."""
        out = _run("""
  const [x, y] = await press(2, "touch");
  out.scrollBlocked = fire(document, "touchmove", {}).defaultPrevented;
  moveTo(x, 300, "touch");
  frame(); frame();
  out.middle = win.scrolls.slice();
  moveTo(x, 790, "touch");
  frame(); frame();
  out.bottom = win.scrolls.slice();
  win.scrolls.length = 0;
  moveTo(x, 4, "touch");
  frame();
  out.top = win.scrolls.slice();
  win.scrolls.length = 0;
  moveTo(x, 300, "touch");
  frame(); frame();
  out.stopped = win.scrolls.slice();
""")
        if out is None:
            return
        assert out["scrollBlocked"] is True
        assert out["middle"] == []
        assert out["bottom"] and all(v > 0 for v in out["bottom"])
        assert out["top"] and all(v < 0 for v in out["top"])
        assert out["stopped"] == []

    @pytest.mark.parametrize("cancel", ["release_outside_zone", "escape_key", "pointercancel"])
    def test_cancel_returns_card_to_its_place(self, cancel):
        """Cancel: releasing outside any zone, Escape or pointercancel restores the layout with a glide and schedules no save."""
        action = {
            "release_outside_zone": 'fire(win, "pointerup", { clientX: 500, clientY: 330 });',
            "escape_key": 'fire(document, "keydown", { key: "Escape" });',
            "pointercancel": 'fire(win, "pointercancel", {});',
        }[cancel]
        out = _run(f"""
  const [x, y] = await press(1);
  moveTo(x + 10, y);
  moveTo(...center(node(3)));
  out.preview = ids("rosterActiveGrid");
  node(1).transformLog.length = 0;
  moveTo(500, 330);
  {action}
  out.dom = ids("rosterActiveGrid");
  out.layout = layout().active;
  out.glide = node(1).transformLog.length > 0;
  out.drag = _drag;
  out.clones = document.body.querySelectorAll(".roster-drag-clone").length;
  await advance(3000);
  out.puts = puts().length;
""")
        if out is None:
            return
        assert out["preview"] == [2, 3, 1, "empty:3", "empty:4"]
        assert out["dom"] == [1, 2, 3, "empty:3", "empty:4"]
        assert out["layout"] == [1, 2, 3, None, None]
        assert out["glide"] is True
        assert out["drag"] is None and out["clones"] == 0
        assert out["puts"] == 0

    def test_drop_zone_highlights_from_93_kept(self):
        """Unchanged behaviour: the #93 drop-zone highlight classes are still applied to the target zone during a pointer drag."""
        css = _before_tour(_css())
        assert _rule(css, ".drop-targets-active .card-slot-empty")
        assert _rule(css, "#benchGrid.drop-targets-active")
        out = _run("""
  const [x, y] = await press(4);
  moveTo(x + 10, y);
  out.zones = ["rosterActiveGrid", "benchGrid"].map(id => grid(id).classList.contains("drop-targets-active"));
  out.body = document.body.classList.contains("roster-dragging");
  const empty = grid("rosterActiveGrid").children[4];
  moveTo(...center(empty));
  out.over = node(4).parentNode === grid("rosterActiveGrid") || empty.classList.contains("drag-over");
  fire(document, "keydown", { key: "Escape" });
  out.after = ["rosterActiveGrid", "benchGrid"].map(id => grid(id).classList.contains("drop-targets-active"));
  out.bodyAfter = document.body.classList.contains("roster-dragging");
  out.overAfter = empty.classList.contains("drag-over");
""")
        if out is None:
            return
        assert out == {"zones": [True, True], "body": True, "over": True,
                       "after": [False, False], "bodyAfter": False, "overAfter": False}

    def test_click_without_movement_opens_card_viewer(self):
        """Unchanged behaviour: pointerdown + pointerup with no movement opens the card viewer and starts no drag."""
        out = _run("""
  const [x, y] = await press(3);
  fire(win, "pointerup", { clientX: x, clientY: y });
  fire(node(3), "click", {});
  await settle();
  out.opened = opened.slice();
  out.drag = _drag;
  out.clones = document.body.querySelectorAll(".roster-drag-clone").length;
  // The click that ends a real drag doesn't open the card.
  await drag(1, node(3));
  fire(node(1), "click", {});
  await settle();
  out.openedAfterDrag = opened.slice();
""")
        if out is None:
            return
        assert out["opened"] == [3]
        assert out["drag"] is None and out["clones"] == 0
        assert out["openedAfterDrag"] == [3]

    def test_locked_week_cards_cannot_be_picked_up(self):
        """Locked weeks (failure path): on a locked week pointerdown starts no drag and no move or save happens."""
        out = _run("""
  const [x, y] = center(node(1));
  fire(node(1), "pointerdown", { clientX: x, clientY: y });
  out.drag = _drag;
  fire(win, "pointermove", { clientX: 490, clientY: 127 });
  fire(win, "pointerup", { clientX: 490, clientY: 127 });
  fire(img(1), "keydown", { key: "Enter" });
  out.layout = layout().active;
  out.editable = node(1).classList.contains("card-slot--editable");
  fire(node(1), "click", {});
  await advance(3000);
  out.puts = puts().length;
  out.opened = opened.slice();
""", data=_roster(locked=True))
        if out is None:
            return
        assert out == {"drag": None, "layout": [1, 2, 3, None, None], "editable": False,
                       "puts": 0, "opened": [1]}


# ---------------------------------------------------------------------------
# Story 3: The Layout Saves Itself
# ---------------------------------------------------------------------------

class TestLayoutSavesItself:
    """
    - Debounced save: 600 ms after the last move, the page sends `PUT /roster` with
      the whole layout and the version it is based on:
      {"active": [card ids in slot order], "bench": [card ids in order], "base_version": "..."}
    - One save at a time: a move during a save is applied locally, and the next save
      sends the newest layout. Saves never overlap, and moves are never blocked, so
      `_rosterBusy` no longer ignores drops.
    - Status line: "Saving..." while a save runs; "Saved" for 2 seconds after it
      succeeds; "Couldn't save. Retry" on a network error, with a Retry button. The
      layout stays as the player arranged it.
    - Flush instead of waiting: when the page becomes hidden (visibilitychange /
      pagehide, with a fetch keepalive request), when the player switches tab or
      week, or when the selected week locks in under 2 minutes. Leaving My Team
      shows no prompt.
    - Rate limit: `PUT /roster` has the per-user RATE_LIMIT_ROSTER_MUTATION limit.
      A burst of moves sends one save, not one per move.
    """

    def test_debounce_collapses_burst_of_moves_into_one_put(self):
        """Debounced save: five moves within 600 ms of each other send exactly one `PUT /roster`, 600 ms after the last move (Node harness, fake timers)."""
        out = _run("""
  for (const id of [1, 2, 1, 4, 2]) { toggleCardZone(id); await advance(100); }
  out.afterBurst = puts().length;
  await advance(499);
  out.justBefore = puts().length;
  await advance(1);
  out.after = puts().length;
  await advance(5000);
  out.final = puts().length;
""")
        if out is None:
            return
        assert out == {"afterBurst": 0, "justBefore": 0, "after": 1, "final": 1}

    def test_put_body_has_active_bench_and_base_version(self):
        """Debounced save: the PUT body is `{"active": [...slot order], "bench": [...in order], "base_version": <version from GET>}`."""
        out = _run("""
  await drag(4, node(2));
  await advance(600);
  out.put = puts()[0];
""")
        if out is None:
            return
        assert out["put"]["url"] == "/roster"
        assert out["put"]["body"] == {"active": [1, 4, 3, None, None], "bench": [2, 5, 6], "base_version": "v1"}
        assert out["put"]["keepalive"] is False

    def test_single_flight_sends_newest_layout_after_running_save(self):
        """One save at a time: a move during a running save is applied locally; a second PUT with the newest layout follows only after the first resolves (never overlapping)."""
        out = _run("""
  PUT_MODE = "hold";
  toggleCardZone(1);
  await advance(600);
  out.first = puts().length;
  toggleCardZone(4);
  await advance(600);
  out.whileRunning = puts().length;
  out.layoutDuring = layout().active;
  PUT_MODE = "ok";
  heldPuts.shift()();
  await settle();
  out.after = puts().length;
  out.second = puts()[1].body;
  out.version = layout().version;
""")
        if out is None:
            return
        assert out["first"] == 1
        assert out["whileRunning"] == 1
        assert out["layoutDuring"] == [4, 2, 3, None, None]
        assert out["after"] == 2
        assert out["second"] == {"active": [4, 2, 3, None, None], "bench": [1, 5, 6], "base_version": "v2"}
        assert out["version"] == "v3"

    def test_moves_not_blocked_during_save(self):
        """One save at a time (failure path of the old guard): a drop while a save is in flight is applied, not ignored; `_rosterBusy` no longer gates drops."""
        assert "_rosterBusy" not in _js()
        out = _run("""
  PUT_MODE = "hold";
  toggleCardZone(1);
  await advance(600);
  out.state = _saveState;
  await drag(4, grid("rosterActiveGrid").children[3]);
  out.layout = layout().active;
  out.dom = ids("rosterActiveGrid");
""")
        if out is None:
            return
        assert out["state"] == "saving"
        assert out["layout"] == [None, 2, 3, 4, None]
        assert out["dom"] == ["empty:0", 2, 3, 4, "empty:4"]

    def test_status_line_saving_then_saved_for_two_seconds(self):
        """Status line: shows "Saving..." while the PUT runs and "Saved" for 2 s after a 200, then clears."""
        out = _run("""
  PUT_MODE = "hold";
  toggleCardZone(4);
  out.waiting = status();
  await advance(600);
  out.saving = status();
  heldPuts.shift()();
  await settle();
  out.saved = status();
  await advance(1999);
  out.stillSaved = status();
  await advance(1);
  out.after = status();
""")
        if out is None:
            return
        assert out == {"waiting": "4/5 active", "saving": "Saving…", "saved": "Saved",
                       "stillSaved": "Saved", "after": "4/5 active"}

    def test_network_error_shows_retry_and_keeps_layout(self):
        """Status line (failure path): a rejected fetch shows "Couldn't save. Retry" with a Retry button; the local layout stays as arranged."""
        html = _read(INDEX_HTML)
        assert '<button id="rosterRetryBtn" class="secondary roster-retry-btn" style="display:none;" onclick="retryRosterSave()">Retry</button>' in html
        out = _run("""
  out.retryBefore = els.rosterRetryBtn.style.display;
  PUT_MODE = "neterr";
  toggleCardZone(4);
  await advance(600);
  out.status = status();
  out.retry = els.rosterRetryBtn.style.display;
  out.layout = layout().active;
  out.dom = ids("rosterActiveGrid");
  out.gets = gets().length;
""")
        if out is None:
            return
        assert out["status"] == "Couldn't save."
        assert out["retry"] == ""
        assert out["layout"] == [1, 2, 3, 4, None]
        assert out["dom"] == [1, 2, 3, 4, "empty:4"]
        assert out["gets"] == 1

    def test_retry_button_resends_current_layout(self):
        """Status line: clicking Retry sends a PUT with the current layout and, on 200, shows "Saved"."""
        out = _run("""
  PUT_MODE = "neterr";
  toggleCardZone(4);
  await advance(600);
  PUT_MODE = "ok";
  await retryRosterSave();
  await settle();
  out.puts = puts().map(p => p.body);
  out.status = status();
  out.retry = els.rosterRetryBtn.style.display;
""")
        if out is None:
            return
        layout = {"active": [1, 2, 3, 4, None], "bench": [5, 6], "base_version": "v1"}
        assert out["puts"] == [layout, layout]
        assert out["status"] == "Saved"
        assert out["retry"] == "none"

    @pytest.mark.parametrize("event", ["visibilitychange", "pagehide"])
    def test_flush_on_page_hidden_uses_keepalive(self, event):
        """Flush: a pending save is sent at once on visibilitychange (hidden) / pagehide, with `keepalive: true` on the fetch."""
        fire = ('document.visibilityState = "hidden"; fire(document, "visibilitychange", {});'
                if event == "visibilitychange" else 'fire(win, "pagehide", {});')
        out = _run(f"""
  toggleCardZone(4);
  await advance(100);
  {fire}
  out.puts = puts().map(p => p.keepalive);
  await advance(2000);
  out.total = puts().length;
""")
        if out is None:
            return
        assert out == {"puts": [True], "total": 1}

    @pytest.mark.parametrize("trigger", ["tab_change", "week_change"])
    def test_flush_on_tab_or_week_change(self, trigger):
        """Flush: switching tab or week sends the pending save immediately instead of waiting for the debounce."""
        assert 'current.id === "tab-team" && typeof flushRosterSave === "function") flushRosterSave();' in \
            _fn_body(_read(GLOBALS_JS), "switchTab")
        action = ('switchTab("schedule");' if trigger == "tab_change"
                  else 'els.rosterWeekSelect.value = "6"; const p = onRosterWeekChange();')
        out = _run(f"""
  toggleCardZone(4);
  await advance(100);
  {action}
  out.puts = puts().length;
  await settle();
  out.order = fetchLog.map(f => f.method + " " + f.url);
""")
        if out is None:
            return
        assert out["puts"] == 1
        if trigger == "week_change":
            assert out["order"] == ["GET /roster/1", "PUT /roster", "GET /roster/1?week_id=6"]

    def test_flush_immediately_when_week_locks_in_under_two_minutes(self):
        """Flush: when the selected week locks in under 2 minutes, a move saves at once with no 600 ms wait."""
        out = _run("""
  toggleCardZone(4);
  out.puts = puts().length;
""", data=_roster(starts_in=90))
        if out is None:
            return
        assert out["puts"] == 1
        out = _run("""
  toggleCardZone(4);
  out.puts = puts().length;
""", data=_roster(starts_in=130))
        assert out["puts"] == 0

    def test_leaving_my_team_shows_no_prompt(self):
        """Flush (static): app-roster.js registers no `beforeunload` handler and no unsaved-changes confirm()."""
        js = _js()
        assert "beforeunload" not in js
        assert "confirm(" not in js
        assert "beforeunload" not in _fn_body(_read(GLOBALS_JS), "switchTab")

    @pytest.mark.parametrize("retry_after,wait_ms", [("3", 3000), (None, 10000)])
    def test_rate_limited_save_waits_and_retries_once_showing_saving(self, retry_after, wait_ms):
        """Rate limit (review note): on a 429 the autosave waits for Retry-After (or 10 s) and retries once by itself with the newest layout, showing "Saving..." rather than an error; moves meanwhile don't send early saves."""
        ra = json.dumps(retry_after)
        out = _run(f"""
  PUT_MODE = "429"; RETRY_AFTER = {ra};
  toggleCardZone(4);
  await advance(600);
  out.first = puts().length;
  out.status = status();
  out.retry = els.rosterRetryBtn.style.display;
  toggleCardZone(1);              // a move while waiting: no early save
  await advance(600);
  out.duringWait = puts().length;
  out.statusDuring = status();
  PUT_MODE = "ok";
  await advance({wait_ms} - 700);
  out.justBefore = puts().length;
  await advance(200);
  out.after = puts().length;
  out.sent = puts()[1].body.active;
  out.final = status();
""")
        if out is None:
            return
        assert out["first"] == 1
        assert out["status"] == "Saving…" and out["retry"] in ("none", None)
        assert out["duringWait"] == 1 and out["statusDuring"] == "Saving…"
        assert out["justBefore"] == 1 and out["after"] == 2
        assert out["sent"] == [None, 2, 3, 4, None]
        assert out["final"] == "Saved"

    def test_rate_limited_retry_that_fails_again_shows_couldnt_save(self):
        """Rate limit (failure path): when the one automatic retry is refused too, the status line says "Couldn't save." with the Retry button."""
        out = _run("""
  PUT_MODE = "429"; RETRY_AFTER = "2";
  toggleCardZone(4);
  await advance(600);
  await advance(2000);
  out.puts = puts().length;
  out.status = status();
  out.retry = els.rosterRetryBtn.style.display;
  await advance(60000);
  out.later = puts().length;
""")
        if out is None:
            return
        assert out["puts"] == 2
        assert out["status"] == "Couldn't save. Too many requests. Wait a moment and try again."
        assert out["retry"] == ""
        assert out["later"] == 2

    def test_put_roster_declares_roster_mutation_limit_per_user(self):
        """Rate limit: the PUT /roster endpoint carries RATE_LIMIT_ROSTER_MUTATION keyed by key_by_user_or_ip (as #184's `_route_limits`)."""
        import routers.cards as cards
        route = _find_route("PUT", "/roster")
        limits = _route_limits(route.endpoint)
        assert route.endpoint.__name__ == "save_roster_route"
        assert [_limit_shape(lim) for lim in limits] == [_limit_amount(cards.RATE_LIMIT_ROSTER_MUTATION)]
        assert limits[0].key_func.__name__ == "key_by_user_or_ip"

    def test_put_roster_exceeding_limit_returns_429(self, monkeypatch):
        """Rate limit (failure path): with a small RATE_LIMIT_ROSTER_MUTATION, the next PUT /roster answers 429 with the plain #184 message and the roster is unchanged."""
        with _app(monkeypatch, RATE_LIMIT_ROSTER_MUTATION="2/minute") as (main_module, client):
            uid = _register(main_module, client, "burst186")
            with main_module.SessionLocal() as db:
                for i in range(3):
                    db.add(Player(id=900 + i, name=f"R{i}"))
                    db.flush()
                    db.add(Card(owner_id=uid, player_id=900 + i, card_type="common", league_id=None,
                                is_active=False, generation=1, slot_index=i))
                db.commit()
                ids = [c.id for c in db.query(Card).filter(Card.owner_id == uid).order_by(Card.id)]
            version = client.get(f"/roster/{uid}").json()["version"]
            r1 = client.put("/roster", json={"active": [ids[0]], "bench": ids[1:], "base_version": version})
            assert r1.status_code == 200
            r2 = client.put("/roster", json={"active": [ids[0]], "bench": ids[1:],
                                              "base_version": r1.json()["version"]})
            assert r2.status_code == 200
            blocked = client.put("/roster", json={"active": [ids[1]], "bench": [ids[0], ids[2]],
                                                   "base_version": r2.json()["version"]})
            assert blocked.status_code == 429
            assert blocked.json() == {"detail": "Too many requests. Wait a moment and try again."}
            with main_module.SessionLocal() as db:
                active = [c.id for c in db.query(Card).filter(Card.owner_id == uid, Card.is_active == True)]  # noqa: E712
            assert active == [ids[0]]


# ---------------------------------------------------------------------------
# Story 4: Saves Are Atomic and Never Overwrite Changes Made Elsewhere
# ---------------------------------------------------------------------------

class TestSavesAreAtomicAndNeverOverwrite:
    """
    - Version on read: `GET /roster/{user_id}` returns `version` for the current
      week: a hash of the active card ids in slot order and the bench card ids in order.
    - Checks: `PUT /roster` checks in one transaction: the cards are the user's own;
      no card is listed twice; at most ROSTER_LIMIT are active; there are no two
      active cards of the same player; no removed player is active; `base_version`
      still matches.
    - Write: it then benches every card not in `active` and sets the active slots
      and the bench order. It answers with the saved roster and its new `version`.
    - Failures: a failed check answers 409 (version or rule) or 422 (bad body), and
      nothing changes.
    - On a version mismatch the page: fetches the roster; animates the cards to the
      server's layout; shows "Your roster changed elsewhere. Showing the latest."
      Moves made after the failed save are dropped.
    - Unchanged layout: saving a layout identical to the stored one is a no-op that
      still answers 200.
    - Week lock: a save for a week whose lock has passed applies to the next week,
      as the single-card routes do today. The response names the week, and the page
      says "Week N locked; this change counts from Week N+1" when they differ.
    """

    def test_roster_version_is_16_hex_sha256_of_active_and_bench_order(self, db):
        """Version on read: `roster_version` equals sha256("active:<ids>|bench:<ids>")[:16] for the stored order."""
        u, act, ben = _seed(db)
        assert _version(db, u) == _sha(f"active:{act[0]},{act[1]},{act[2]}|bench:{ben[0]},{ben[1]}")
        assert re.fullmatch(r"[0-9a-f]{16}", _version(db, u))
        # An empty slot between roster cards is part of the layout ("-").
        db.query(Card).filter(Card.id == act[2]).update({"slot_index": 3})
        db.commit()
        assert _version(db, u) == _sha(f"active:{act[0]},{act[1]},-,{act[2]}|bench:{ben[0]},{ben[1]}")

    def test_get_roster_returns_version(self, db):
        """Version on read: `GET /roster/{user_id}` includes `version` equal to `roster_version(db, user_id)`."""
        from routers.cards import get_roster
        u, act, ben = _seed(db)
        data = get_roster(u.id, None, db, _uid(u))
        assert data["version"] == _version(db, u)
        assert [c["id"] for c in data["active"]] == act and [c["id"] for c in data["bench"]] == ben

    def test_roster_version_changes_with_slot_or_bench_order(self, db):
        """Version on read: reordering active slots or the bench changes the version; the same layout gives the same version."""
        u, act, ben = _seed(db)
        v1 = _version(db, u)
        assert _version(db, u) == v1
        db.query(Card).filter(Card.id == act[0]).update({"slot_index": 1})
        db.query(Card).filter(Card.id == act[1]).update({"slot_index": 0})
        db.commit()
        v2 = _version(db, u)
        assert v2 != v1
        db.query(Card).filter(Card.id == ben[0]).update({"slot_index": 1})
        db.query(Card).filter(Card.id == ben[1]).update({"slot_index": 0})
        db.commit()
        assert _version(db, u) not in (v1, v2)

    def test_save_roster_applies_layout_and_returns_new_version(self, db):
        """Write: `save_roster` sets active slots in the given order, benches the rest in the given order and returns the roster with a new `version`."""
        u, act, ben = _seed(db)
        v1 = _version(db, u)
        data = _save(db, u, [ben[0], None, act[2], act[0]], [ben[1], act[1]], v1)
        assert _stored(db, u.id) == {
            ben[0]: (True, 0), act[2]: (True, 2), act[0]: (True, 3),
            ben[1]: (False, 0), act[1]: (False, 1),
        }
        assert data["version"] != v1
        assert data["version"] == _sha(f"active:{ben[0]},-,{act[2]},{act[0]}|bench:{ben[1]},{act[1]}")
        assert [c["id"] for c in data["active"]] == [ben[0], act[2], act[0]]
        assert [c["id"] for c in data["bench"]] == [ben[1], act[1]]

    def test_save_roster_response_version_matches_get(self, db):
        """Write: the `version` in the save response equals the one a following `GET /roster/{user_id}` returns."""
        from routers.cards import get_roster
        u, act, ben = _seed(db)
        data = _save(db, u, [act[1], act[0]], [ben[1], ben[0], act[2]], _version(db, u))
        assert get_roster(u.id, None, db, _uid(u))["version"] == data["version"]

    def test_save_roster_benches_cards_not_listed_active(self, db):
        """Write: every owned card not in `active` ends with is_active False and slot_index NULL, without tripping the #185 one-active-per-player index."""
        u, act, ben = _seed(db)
        # A bench card of the same player as roster card act[0] replaces it in the
        # same save: the outgoing card must be benched before the new one is activated.
        same = _make_card(db, u.id, 100, is_active=False, slot_index=5).id
        db.commit()
        _save(db, u, [same], [], _version(db, u))
        stored = _stored(db, u.id)
        assert stored[same] == (True, 0)
        for cid in act + ben:
            assert stored[cid] == (False, None)

    def test_save_roster_refuses_another_users_card(self, db):
        """Checks (failure path): a layout containing another user's card is refused and nothing changes."""
        u, act, ben = _seed(db)
        other = _make_user(db, username="other", email="o@o.com")
        p = _make_player(db, player_id=999, name="Theirs")
        theirs = _make_card(db, other.id, p.id).id
        db.commit()
        before, v = _stored(db, u.id), _version(db, u)
        with pytest.raises(HTTPException) as exc:
            _save(db, u, act + [theirs], ben, v)
        assert exc.value.status_code == 404 and exc.value.detail == "Card not found"
        assert _stored(db, u.id) == before
        assert _stored(db, other.id) == {theirs: (False, None)}

    def test_save_roster_refuses_card_listed_twice(self, db):
        """Checks (failure path): a card id appearing twice (in active, in bench, or in both) is refused with 409 and nothing changes."""
        u, act, ben = _seed(db)
        before, v = _stored(db, u.id), _version(db, u)
        for active, bench in (([act[0], act[0]], ben), (act, [ben[0], ben[0], ben[1]]), (act, ben + [act[1]])):
            with pytest.raises(HTTPException) as exc:
                _save(db, u, active, bench, v)
            assert exc.value.status_code == 409
            assert exc.value.detail == "A card is listed more than once"
            assert _stored(db, u.id) == before

    def test_save_roster_refuses_more_than_roster_limit_active(self, db, monkeypatch):
        """Checks (failure path): more than ROSTER_LIMIT active ids is refused (422 at the route via Field max_length, 409 from the plain function) and nothing changes."""
        from pydantic import ValidationError
        from card_utils import RosterLayoutError, apply_roster_layout
        from routers.cards import RosterLayoutRequest
        u, act, ben = _seed(db, active=3, bench=3)
        six = act + ben
        before, v = _stored(db, u.id), _version(db, u)
        with pytest.raises(RosterLayoutError) as exc:
            apply_roster_layout(db, u.id, six, [], v, 5)
        db.rollback()
        assert exc.value.status_code == 409 and exc.value.detail == "Roster full (5 cards max)"
        assert _stored(db, u.id) == before
        with pytest.raises(ValidationError):
            RosterLayoutRequest(active=six, bench=[], base_version=v)
        with _app(monkeypatch) as (main_module, client):
            _register(main_module, client, "limit186")
            resp = client.put("/roster", json={"active": [1, 2, 3, 4, 5, 6], "bench": [], "base_version": "x"})
            assert resp.status_code == 422

    def test_save_roster_refuses_two_active_cards_of_same_player(self, db):
        """Checks (failure path): two active cards of the same player are refused with 409 and nothing changes."""
        u, act, ben = _seed(db)
        dup = _make_card(db, u.id, 100, is_active=False, slot_index=2).id
        db.commit()
        before, v = _stored(db, u.id), _version(db, u)
        with pytest.raises(HTTPException) as exc:
            _save(db, u, act + [dup], ben, v)
        assert exc.value.status_code == 409
        assert exc.value.detail == "A card for this player is already active"
        assert _stored(db, u.id) == before

    def test_save_roster_refuses_removed_player_active(self, db):
        """Checks (failure path): a card whose Player.is_active is False in `active` is refused with 409 and nothing changes."""
        u, act, ben = _seed(db)
        p = _make_player(db, player_id=777, name="Gone")
        gone = _make_card(db, u.id, p.id, is_active=False).id
        p.is_active = False
        db.commit()
        before, v = _stored(db, u.id), _version(db, u)
        with pytest.raises(HTTPException) as exc:
            _save(db, u, act + [gone], ben, v)
        assert exc.value.status_code == 409
        assert exc.value.detail == "A removed player can't be on the roster"
        assert _stored(db, u.id) == before

    def test_save_roster_version_mismatch_returns_409_and_changes_nothing(self, db):
        """Failures: a stale `base_version` answers 409 (distinguishable as a version conflict) and the stored roster is untouched."""
        u, act, ben = _seed(db)
        stale = _version(db, u)
        _save(db, u, [act[1], act[0], act[2]], ben, stale)
        before = _stored(db, u.id)
        with pytest.raises(HTTPException) as exc:
            _save(db, u, act, ben, stale)
        assert exc.value.status_code == 409
        assert exc.value.headers == {"X-Roster-Conflict": "version"}
        assert _stored(db, u.id) == before
        # A rule refusal has no such header.
        with pytest.raises(HTTPException) as rule:
            _save(db, u, [act[0], act[0]], ben, _version(db, u))
        assert rule.value.status_code == 409 and not rule.value.headers

    @pytest.mark.parametrize("body", [
        {},
        {"active": [], "bench": []},
        {"active": [], "bench": [], "base_version": ""},
        {"active": [], "bench": [], "base_version": "x" * 65},
        {"active": "1,2", "bench": [], "base_version": "abc"},
    ])
    def test_put_roster_bad_body_returns_422(self, body, monkeypatch):
        """Failures: a malformed body (missing field, empty or over-long base_version, non-list ids) answers 422 and nothing changes."""
        with _app(monkeypatch) as (main_module, client):
            uid = _register(main_module, client, "body186")
            with main_module.SessionLocal() as db:
                db.add(Player(id=950, name="Kept"))
                db.flush()
                db.add(Card(owner_id=uid, player_id=950, card_type="common", league_id=None,
                            is_active=True, generation=1, slot_index=0))
                db.commit()
            before = client.get(f"/roster/{uid}").json()["version"]
            resp = client.put("/roster", json=body)
            assert resp.status_code == 422
            assert client.get(f"/roster/{uid}").json()["version"] == before

    def test_put_roster_oversized_card_id_returns_422_not_500(self, monkeypatch):
        """Security review: a card id above SQLite's 2**63-1 answers 422 (not an OverflowError 500), in PUT /roster and the older swap/reorder bodies."""
        from pydantic import ValidationError
        from routers.cards import ReorderRequest, RosterLayoutRequest, SwapRequest
        big = 2 ** 63
        for make in (lambda: RosterLayoutRequest(active=[big], bench=[], base_version="x"),
                     lambda: RosterLayoutRequest(active=[], bench=[big], base_version="x"),
                     lambda: RosterLayoutRequest(active=[0], bench=[], base_version="x"),
                     lambda: ReorderRequest(card_ids=[big]),
                     lambda: SwapRequest(bench_card_id=big, active_card_id=1, slot_index=0)):
            with pytest.raises(ValidationError):
                make()
        assert RosterLayoutRequest(active=[None, 2 ** 63 - 1], bench=[], base_version="x").active[0] is None
        with _app(monkeypatch) as (main_module, client):
            _register(main_module, client, "big186")
            for path, method, body in (
                ("/roster", "put", {"active": [big], "bench": [], "base_version": "x"}),
                ("/roster", "put", {"active": [], "bench": [big], "base_version": "x"}),
                ("/roster/reorder", "post", {"card_ids": [big]}),
                ("/roster/swap", "post", {"bench_card_id": big, "active_card_id": 1, "slot_index": 0}),
            ):
                assert getattr(client, method)(path, json=body).status_code == 422, path

    def test_put_roster_saves_a_bench_over_500_cards(self, db):
        """Security review: the bench cap is a ceiling no user reaches (5000), so a bench of 600 cards saves; 5001 entries are refused (422)."""
        from pydantic import ValidationError
        from routers.cards import ROSTER_BENCH_MAX, RosterLayoutRequest
        assert ROSTER_BENCH_MAX == 5000
        u = _make_user(db)
        ids = []
        for i in range(600):
            p = _make_player(db, player_id=3000 + i, name=f"Bench{i}")
            ids.append(_make_card(db, u.id, p.id, slot_index=i).id)
        db.commit()
        new_bench = list(reversed(ids[1:]))
        data = _save(db, u, [ids[0]], new_bench, _version(db, u))
        assert [c["id"] for c in data["bench"]] == new_bench
        with pytest.raises(ValidationError):
            RosterLayoutRequest(active=[], bench=list(range(1, 5002)), base_version="x")

    def test_put_roster_requires_auth(self, monkeypatch):
        """Failures: PUT /roster without a session answers 401."""
        with _app(monkeypatch) as (main_module, client):
            resp = client.put("/roster", json={"active": [], "bench": [], "base_version": "abc"})
            assert resp.status_code == 401

    def test_save_roster_integrity_error_returns_409_not_500(self, db, monkeypatch):
        """Failures: an IntegrityError during the write becomes 409 and the transaction is rolled back."""
        import routers.cards as cards
        u, act, ben = _seed(db)
        before, v = _stored(db, u.id), _version(db, u)

        def _boom(db_, user_id, active, bench, base_version, roster_limit):
            db_.execute(models.Card.__table__.update().where(models.Card.id == act[0]).values(slot_index=4))
            raise IntegrityError("UPDATE cards", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(cards, "apply_roster_layout", _boom)
        with pytest.raises(HTTPException) as exc:
            _save(db, u, act, ben, v)
        assert exc.value.status_code == 409
        assert exc.value.detail == "A card for this player is already active"
        assert _stored(db, u.id) == before

    def test_concurrent_saves_from_same_base_one_wins_other_409(self, file_db_sessionmaker, monkeypatch):
        """Checks: two threads saving different layouts from the same base_version (file_db_sessionmaker + barrier): exactly one succeeds, the other gets 409, and the stored roster is the winner's."""
        import card_utils
        from routers.cards import RosterLayoutRequest, save_roster
        Factory = file_db_sessionmaker
        with Factory() as s:
            u, act, ben = _seed(s)
            uid, base = u.id, _version(s, u)
        # Hold each save between its version check and its writes, so without the
        # write lock taken first both would pass the check (verified against code
        # without the lock step: both saves succeed).
        real = card_utils.roster_version

        def _slow_version(db, user_id, roster_limit=5):
            v = real(db, user_id, roster_limit)
            time.sleep(0.3)
            return v

        monkeypatch.setattr(card_utils, "roster_version", _slow_version)
        layouts = {
            "a": ([act[2], act[1], act[0]], ben),
            "b": ([ben[0], act[1]], [act[0], act[2], ben[1]]),
        }

        def _worker(name):
            with Factory() as s:
                active, bench = layouts[name]
                save_roster(RosterLayoutRequest(active=active, bench=bench, base_version=base),
                            {"user_id": uid}, s)
                return name

        results = _run_concurrently(_worker, [("a",), ("b",)])
        wins = [r for r, e in results if e is None]
        errors = [e for r, e in results if e is not None]
        assert len(wins) == 1 and len(errors) == 1
        assert isinstance(errors[0], HTTPException) and errors[0].status_code == 409
        assert errors[0].headers == {"X-Roster-Conflict": "version"}
        with Factory() as s:
            monkeypatch.setattr(card_utils, "roster_version", real)
            active, bench = layouts[wins[0]]
            assert card_utils.roster_layout(s, uid, 5) == (active + [None] * (5 - len(active)), bench)

    def test_save_roster_identical_layout_is_noop_200(self, db, monkeypatch):
        """Unchanged layout: saving the stored layout answers 200 with the same version and writes nothing."""
        u, act, ben = _seed(db)
        v = _version(db, u)
        writes = []
        from sqlalchemy import event

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def _log(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().upper().startswith("UPDATE CARDS"):
                writes.append(statement)

        data = _save(db, u, act, ben, v)
        event.remove(db.get_bind(), "before_cursor_execute", _log)
        assert data["version"] == v
        assert writes == []

    def test_save_roster_after_lock_applies_to_next_week_and_names_week(self, db):
        """Week lock: a save after the current week's lock applies to the next week, as the single-card routes do, and the response names that week."""
        now = int(time.time())
        db.add(Week(label="Week 5", start_time=now - 3600, end_time=now + 86400, is_locked=True))
        db.add(Week(label="Week 6", start_time=now + 7 * 86400, end_time=now + 8 * 86400, is_locked=False))
        u, act, ben = _seed(db)
        data = _save(db, u, [ben[0]] + act[1:], [act[0], ben[1]], _version(db, u))
        assert data["week"]["label"] == "Week 6" and data["week"]["is_locked"] is False
        assert _stored(db, u.id)[ben[0]] == (True, 0)

    def test_page_version_conflict_reloads_animates_and_drops_later_moves(self):
        """On a version mismatch: the page fetches the roster, renders the server layout with flipMove, shows "Your roster changed elsewhere. Showing the latest." and drops moves made after the failed save (Node harness)."""
        out = _run("""
  PUT_MODE = "holdconflict";
  toggleCardZone(4);
  await advance(600);
  toggleCardZone(1);           // made while the save runs; dropped by the conflict
  // Elsewhere: card 2 went to the bench.
  ROSTER = { ...ROSTER, active: ROSTER.active.filter(c => c.id !== 2),
             bench: [{ ...ROSTER.active[1], is_active: false, slot_index: 3 }, ...ROSTER.bench], version: "v9" };
  for (const n of [1, 2, 3, 4]) node(n).transformLog.length = 0;
  heldPuts.shift()();
  await settle();
  out.gets = gets().length;
  out.layout = layout();
  out.dom = ids("rosterActiveGrid");
  out.status = status();
  out.glided = node(2).transformLog.length > 0;
  await advance(3000);
  out.puts = puts().length;
""")
        if out is None:
            return
        assert out["gets"] == 2
        assert out["layout"] == {"active": [1, None, 3, None, None], "bench": [2, 4, 5, 6], "version": "v9"}
        assert out["dom"] == [1, "empty:1", 3, "empty:3", "empty:4"]
        assert out["status"] == "Your roster changed elsewhere. Showing the latest."
        assert out["glided"] is True
        assert out["puts"] == 1

    def test_page_rule_409_or_422_shows_message_and_reloads_server_layout(self):
        """Failures (page): a 409 rule refusal or 422 shows the server's message and reloads the server layout."""
        for mode, msg in (("rule", "A card for this player is already active"), ("422", "Field required")):
            out = _run(f"""
  PUT_MODE = "{mode}";
  toggleCardZone(4);
  await advance(600);
  out.status = status();
  out.layout = layout().active;
  out.gets = gets().length;
  out.retry = els.rosterRetryBtn.style.display;
""")
            if out is None:
                return
            assert out == {"status": msg, "layout": [1, 2, 3, None, None], "gets": 2, "retry": "none"}

    def test_page_shows_week_locked_message_when_response_week_differs(self):
        """Week lock (page): when the response week differs from the selected one, the status line says "Week N locked; this change counts from Week N+1"."""
        out = _run("""
  PUT_MODE = "nextweek";
  toggleCardZone(4);
  await advance(600);
  out.status = status();
  await advance(3000);
  out.later = status();
""")
        if out is None:
            return
        assert out["status"] == "Week 5 locked; this change counts from Week 6"
        assert out["later"] == "Week 5 locked; this change counts from Week 6"

    @pytest.mark.parametrize("method,path", [
        ("POST", "/roster/{card_id}/activate"),
        ("POST", "/roster/{card_id}/deactivate"),
        ("POST", "/roster/swap"),
        ("POST", "/roster/reorder"),
    ])
    def test_single_card_routes_still_exist_for_twitch_panel(self, method, path):
        """The single-card routes stay for the Twitch panel and older clients."""
        route = _find_route(method, path)
        assert _route_limits(route.endpoint)
