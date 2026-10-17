"""
Tests for plan-issue-205-card-draw-animations.md (resolves GitHub issue #205).

A draw lifts the top card off a visible deck in the Draw panel, flies it to the
centre, flips it face up with the rarity burst and then fades in the rest of the
reveal. On Continue the card flies to where it was added (open roster slot or
bench front) and glows once. Frontend only: no backend, schema or env change.

  Story 1: Draw From the Deck              (TestDrawFromTheDeck)
  Story 2: Deck in My Team                 (TestDeckInMyTeam)
  Story 3: Flip a Card to Its Back         -- *(not yet implemented)*, not stubbed
  Story 4: Card Back Ready for More        -- *(not yet implemented)*, not stubbed

Approach notes:

- Static checks of frontend/index.html, app-cards.js, app-roster.js and style.css:
  reuse `_read`, `_css_blocks`, `_fn_body` from
  test_issue_151_weekly_report_aesthetics.py and `_rule(css, selector)` /
  `_before_tour(css)` from test_issue_186_my_team_save_roster.py (see also `_rule`
  in test_issue_156_schedule_visuals.py). New CSS goes before the
  "GUIDED TOUR (issue #144)" section and uses tokens only (no hex).
- Node harness for the draw sequence: no harness runs app-cards.js `drawCard()`
  yet. Build one on the pattern of `_HARNESS` / `_run(steps, data, reduced)` in
  test_issue_186_my_team_save_roster.py (fake DOM with fixed layout rectangles,
  `fire()`, fake timers / frames / fetch, `__REDUCED__` switch) and
  `_run_schedule` in test_issue_156_schedule_visuals.py. Add: a stubbed `fetch`
  for `POST /draw` and `POST /draw/booster/{team}` (ok and error bodies), a fake
  `window.Image` whose load / error / `decode()` the test resolves by hand, and
  an `Element.prototype.animate` stub that records (element, keyframes, options)
  and returns an object with a controllable `finished` promise. Load
  `withBusy` etc. via `_globals_src` (re-add `async` when pasting extracted
  functions -- see lessons-learned 2026-10-14). Skip when Node is missing
  (`_node()` from test_issue_159_flicker_free_tab_switching.py).
- Code facts checked against today's app-cards.js: `drawCard()` uses
  `withBusy(btn, ...)`, posts `/draw`, then calls `showReveal(data)`, `loadDeck()`
  and `loadRoster(_rosterWeekId)` right away; the team draw is
  `_drawBoosterForTeam(teamId)` guarded by `_boosterDrawInFlight`; `revealAction()`
  handles both Continue and "Draw another card"; `closeReveal()` handles X /
  Escape / backdrop; `DRAW_REVEAL_MIN_MS` exists. The chances come from
  `GET /config` -> `draw_rates` (backed by the `draw_rate_*` settings), filling
  `#deck-common`, `#deck-rare`, `#deck-epic`, `#deck-legendary`.
  Roster ids: `#rosterActiveGrid` (roster) and `#benchGrid` (bench). The
  backdrop click is `modal.onclick` set by `showCard()` (hides the modal without
  `closeReveal()`); X and Escape (`data-close`) call `closeReveal()`.

Harness (`_run`): loads app-cards.js in full, `withBusy` from app-globals.js and
`rosterArrivalSlot` / `markArrived` from app-roster.js. `loadRoster` is a stub
that re-renders the grids 300 ms after it is called. Images load and decode by
`IMG_MODE` ("auto", "hold" for `loadImages()` / `decodeImages()` by hand,
"never", "error"). `ANIMS` records every `animate()` call with the element's
class, its keyframes and options, and whether the burst was on at that moment.

Manual-only (plan's Verification section): real timing and smoothness, Slow 3G,
the OS reduced-motion setting, 360 px width, keyboard-only use.

Run with: cd backend && python -m pytest tests/test_issue_205_card_draw_animations.py -v
"""


import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _fn_body, _read
from tests.test_issue_159_flicker_free_tab_switching import _node

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
CARDS_JS = os.path.join(FRONTEND_DIR, "app-cards.js")
ROSTER_JS = os.path.join(FRONTEND_DIR, "app-roster.js")
GLOBALS_JS = os.path.join(FRONTEND_DIR, "app-globals.js")
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")
STYLE_CSS = os.path.join(FRONTEND_DIR, "style.css")

_RARITIES = ("common", "rare", "epic", "legendary")


def _rule(css, selector):
    """Bodies of the rules whose selector list contains exactly `selector`."""
    return [body for sel, body in _css_blocks(css, re.escape(selector))
            if selector in [x.strip() for x in sel.split(",")]]


def _before_tour(css):
    return css[:css.index("GUIDED TOUR (issue #144)")]


def _reduced_motion_css(css):
    """The text of every `@media (prefers-reduced-motion: reduce)` block."""
    out = []
    for m in re.finditer(r"@media \(prefers-reduced-motion: reduce\)\s*\{", css):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.end():i - 1])
    return "\n".join(out)


def _deck_markup(html):
    start = html.rindex("<div", 0, html.index('id="drawDeck"'))
    return html[start:html.index('<div class="draw-chances">', start)]


def _draw_panel(html):
    start = html.index("<h2>Draw</h2>")
    return html[start:html.index('id="deckStatus"', start)]


# ---------------------------------------------------------------------------
# Node harness: app-cards.js in a fake DOM with fake timers, fetch, Image and
# Element.animate
# ---------------------------------------------------------------------------

_HARNESS = r"""
let NOW = 1000000;
const REDUCED = __REDUCED__;
const NO_ANIMATE = __NO_ANIMATE__;
let IMG_MODE = "__IMG_MODE__";
let DRAW = __DRAW__;
let ROSTER = __ROSTER_BEFORE__;
const ROSTER_AFTER = __ROSTER_AFTER__;

let _timers = [], _tid = 0;
globalThis.setTimeout = (fn, ms) => { const id = ++_tid; _timers.push({ id, at: NOW + (ms || 0), fn }); return id; };
globalThis.clearTimeout = id => { _timers = _timers.filter(t => t.id !== id); };
globalThis.requestAnimationFrame = fn => setTimeout(() => fn(NOW), 16);
Object.defineProperty(globalThis, "performance", { value: { now: () => NOW }, configurable: true, writable: true });
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise(r => setImmediate(r)); };
async function advance(ms) {
  const end = NOW + ms;
  await settle();
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

class ClassList {
  constructor() { this.set = new Set(); this.log = []; }
  add(...c) { c.forEach(x => { this.set.add(x); this.log.push(x); }); }
  remove(...c) { c.forEach(x => this.set.delete(x)); }
  contains(c) { return this.set.has(c); }
  toggle(c, force) { const on = force === undefined ? !this.set.has(c) : !!force; if (on) this.add(c); else this.remove(c); return on; }
}
const RECTS = {
  drawDeck: { left: 1000, top: 150, width: 88, height: 125 },
  drawBtn: { left: 1000, top: 300, width: 120, height: 40 },
  revealImgWrap: { left: 540, top: 200, width: 200, height: 283 },
};
const GRID_TOP = { rosterActiveGrid: 100, benchGrid: 450 };
const box = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height });
class El {
  constructor(tag, id) {
    this.tagName = String(tag).toUpperCase(); this.id = id || ""; this.children = []; this.parentNode = null;
    this.classList = new ClassList(); this.dataset = {}; this.attrs = {}; this.listeners = {};
    this.style = {}; this._text = ""; this._html = ""; this.disabled = false; this.scrolled = null;
  }
  get className() { return [...this.classList.set].join(" "); }
  set className(v) { this.classList.set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); }
  get isConnected() { let n = this; while (n) { if (n === document.body) return true; n = n.parentNode; } return false; }
  get offsetWidth() { return 0; }
  appendChild(c) { if (c.parentNode) c.parentNode._drop(c); c.parentNode = this; this.children.push(c); return c; }
  _drop(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; }
  replaceChildren(...nodes) { this.children.slice().forEach(c => { c.parentNode = null; }); this.children = []; nodes.forEach(n => this.appendChild(n)); }
  remove() { if (this.parentNode) this.parentNode._drop(this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  removeEventListener(t, f) { if (this.listeners[t]) this.listeners[t] = this.listeners[t].filter(x => x !== f); }
  scrollIntoView(opts) { this.scrolled = opts || {}; }
  matches(sel) {
    return sel.split(",").some(part => {
      const m = part.trim().match(/^([a-z]+)?(#[\w-]+)?((?:\.[\w-]+)*)((?:\[[\w-]+\])*)$/);
      if (!m) throw new Error("unsupported selector " + part);
      if (m[1] && this.tagName !== m[1].toUpperCase()) return false;
      if (m[2] && this.id !== m[2].slice(1)) return false;
      for (const c of (m[3].match(/\.[\w-]+/g) || [])) if (!this.classList.contains(c.slice(1))) return false;
      for (const a of (m[4].match(/\[[\w-]+\]/g) || [])) {
        const key = a.slice(1, -1).slice(5).replace(/-(\w)/g, (_, ch) => ch.toUpperCase());
        if (this.dataset[key] === undefined) return false;
      }
      return true;
    });
  }
  querySelectorAll(sel) { const out = []; const walk = n => n.children.forEach(c => { if (c.matches(sel)) out.push(c); walk(c); }); walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getBoundingClientRect() {
    if (RECTS[this.id]) { const r = RECTS[this.id]; return box(r.left, r.top, r.width, r.height); }
    const p = this.parentNode;
    if (p && p.id in GRID_TOP) return box(p.children.indexOf(this) * 160, GRID_TOP[p.id], 150, 212);
    return box(0, 0, 0, 0);
  }
}
const ANIMS = [];
if (!NO_ANIMATE) {
  El.prototype.animate = function (keyframes, opts) {
    const burst = document.getElementById("revealDrawBurst").classList.contains("reveal-draw-burst--active");
    const rec = { cls: this.className, keyframes, opts, at: NOW, burst,
                  style: { left: this.style.left, top: this.style.top, width: this.style.width, height: this.style.height } };
    ANIMS.push(rec);
    const anim = { finished: new Promise(r => setTimeout(r, opts.duration || 0)) };
    return anim;
  };
}

const els = {};
const win = { innerWidth: __WIDTH__, innerHeight: __INNER_HEIGHT__,
  matchMedia: q => ({ matches: REDUCED && q.includes("reduce") }) };
globalThis.window = win;
const document = {
  listeners: {}, body: new El("body"),
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
  removeEventListener(t, f) { if (this.listeners[t]) this.listeners[t] = this.listeners[t].filter(x => x !== f); },
  createElement: tag => new El(tag),
  getElementById(id) { if (!els[id]) els[id] = new El("div", id); return els[id]; },
  querySelector(sel) { return this.body.querySelector(sel); },
  querySelectorAll(sel) { return this.body.querySelectorAll(sel); },
};
globalThis.document = document;
for (const id of ["rosterActiveGrid", "benchGrid", "drawDeck", "drawBtn", "revealModal", "boosterModal", "drawLandedNotice"]) {
  document.body.appendChild(document.getElementById(id));
}
els.revealModal.className = "reveal-overlay hidden";
els.boosterModal.className = "modal-overlay";
els.drawLandedNotice.style.display = "none";
els.revealModal.appendChild(document.getElementById("revealDrawBurst"));
els.revealModal.appendChild(document.getElementById("revealCard"));
els.revealCard.appendChild(document.getElementById("revealImgWrap"));
els.revealImgWrap.appendChild(document.getElementById("revealImgPlaceholder"));
els.revealImgWrap.appendChild(document.getElementById("revealCardImg"));
els.revealCardImg.style.display = "none";

const IMAGES = [];
class FakeImage {
  constructor() { IMAGES.push(this); this.onload = null; this.onerror = null; this._src = ""; this.loaded = false; this.decoded = false; }
  get src() { return this._src; }
  set src(v) {
    this._src = v;
    if (IMG_MODE === "auto") setTimeout(() => this.load(), 100);
    if (IMG_MODE === "error") setTimeout(() => { if (this.onerror) this.onerror(); }, 100);
  }
  load() { if (this.loaded) return; this.loaded = true; if (this.onload) this.onload(); }
  decode() {
    return new Promise(r => {
      this._decode = () => { this.decoded = true; r(); };
      if (IMG_MODE === "auto") setTimeout(this._decode, 50);
    });
  }
}
win.Image = FakeImage;
function loadImages() { IMAGES.forEach(i => i.load()); }
function decodeImages() { IMAGES.forEach(i => { if (i._decode) i._decode(); }); }

const fetchLog = [];
const heldDraws = [];
const resp = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
globalThis.fetch = (url, opts = {}) => {
  const method = opts.method || "GET";
  fetchLog.push(method + " " + url);
  if (method === "POST" && (url === "/draw" || url.startsWith("/draw/booster/"))) {
    if (DRAW.reject) return Promise.reject(new TypeError("Failed to fetch"));
    if (DRAW.hold) return new Promise(res => heldDraws.push(() => res(resp(DRAW.status, DRAW.body))));
    return Promise.resolve(resp(DRAW.status, DRAW.body));
  }
  if (url === "/config") return Promise.resolve(resp(200, { draw_rates: { common: 60, rare: 25, epic: 10, legendary: 5 } }));
  return Promise.reject(new Error("unexpected fetch " + method + " " + url));
};

const API = "";
let activeUserId = 1;
let _tokenBalance = 5;
let _teamBoosterCost = 3;
let _tokenName = "Tokens";
let _rosterWeekId = null;
let _rosterCards = [];
const _lastHtml = new WeakMap();
function renderIfChanged(el, html) { if (!el) return false; el.innerHTML = html; return true; }
function _escHtml(s) { return String(s ?? ""); }
function _imgSrc(u) { return u; }
function cardImageUrl(id) { return `/cards/${id}/image`; }
function updateTokenDisplay(balance) { _tokenBalance = balance; }
function setStatus(id, msg, ok = true) { const el = document.getElementById(id); el.textContent = msg ?? "Unknown error"; el.className = "status " + (ok ? "ok" : "err"); }
function openPlayerModal() {}
function bumpCardImageCacheBust() {}
__WITHBUSY__

const _rosterNodes = new Map();
let rosterLoads = 0;
function slotNode(id) {
  let n = _rosterNodes.get(id);
  if (!n) { n = new El("div"); n.className = "card-slot"; n.dataset.cardId = String(id); n.dataset.rarity = "epic"; _rosterNodes.set(id, n); }
  return n;
}
function emptyNode(i) { const n = new El("div"); n.className = "card-slot-empty"; n.dataset.slotIndex = String(i); return n; }
function renderRoster() {
  els.rosterActiveGrid.replaceChildren(...ROSTER.active.map((id, i) => id == null ? emptyNode(i) : slotNode(id)));
  els.benchGrid.replaceChildren(...ROSTER.bench.map(slotNode));
}
function loadRoster() {
  rosterLoads++;
  return new Promise(r => setTimeout(() => { ROSTER = ROSTER_AFTER; renderRoster(); r(); }, 300));
}
renderRoster();
__ROSTER_FNS__
__CARDS__

const modal = () => els.revealModal;
const anims = cls => ANIMS.filter(a => a.cls.split(" ").includes(cls));
const flights = () => document.body.children.filter(c => c.classList.contains("draw-flight") || c.classList.contains("draw-landing"));
const posts = () => fetchLog.filter(f => f.startsWith("POST"));
const stirring = () => els.drawDeck.classList.contains("draw-deck--stirring");
const shown = () => !modal().classList.contains("hidden");
const burstEver = () => els.revealDrawBurst.classList.log.includes("reveal-draw-burst--active");
async function drawAndReveal() { drawCard(); await advance(3000); }
(async () => {
  const out = {};
__STEPS__
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _card(**kw):
    card = {"id": 9, "card_type": "epic", "is_active": True, "player_id": 109,
            "player_name": "P9", "team_name": "T9", "tokens": 0}
    card.update(kw)
    return card


_ROSTER_BEFORE = {"active": [1, 2, 3, 4, None], "bench": [7, 8]}
_ROSTER_ACTIVE = {"active": [1, 2, 3, 4, 9], "bench": [7, 8]}
_FULL_BEFORE = {"active": [1, 2, 3, 4, 5], "bench": [7, 8]}
_ROSTER_BENCH = {"active": [1, 2, 3, 4, 5], "bench": [9, 7, 8]}


def _withbusy_src():
    return "async " + _fn_body(_read(GLOBALS_JS), "withBusy") + "\n}\n"


def _roster_fns_src():
    js = _read(ROSTER_JS)
    const = re.search(r"^const ROSTER_ARRIVED_MS = \d+;$", js, re.M).group(0)
    return "\n".join([const] + [_fn_body(js, n) + "\n}\n" for n in ("rosterArrivalSlot", "markArrived")])


def _run(steps, *, draw=None, reduced=False, no_animate=False, img="auto", width=1280,
         inner_height=900, before=None, after=None):
    """Run `steps` (JS in an async function filling `out`) against app-cards.js;
    returns `out`. Skips the test when Node is not installed."""
    node = _node()
    if not node:
        pytest.skip("node not installed")
    if draw is None:
        draw = {"status": 200, "body": _card()}
    script = (_HARNESS
              .replace("__REDUCED__", "true" if reduced else "false")
              .replace("__NO_ANIMATE__", "true" if no_animate else "false")
              .replace("__IMG_MODE__", img)
              .replace("__DRAW__", json.dumps(draw))
              .replace("__ROSTER_BEFORE__", json.dumps(before or _ROSTER_BEFORE))
              .replace("__ROSTER_AFTER__", json.dumps(after or _ROSTER_ACTIVE))
              .replace("__WIDTH__", str(width))
              .replace("__INNER_HEIGHT__", str(inner_height))
              .replace("__WITHBUSY__", _withbusy_src())
              .replace("__ROSTER_FNS__", _roster_fns_src())
              .replace("__CARDS__", _read(CARDS_JS))
              .replace("__STEPS__", steps))
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-3000:]
    return json.loads(res.stdout.strip().splitlines()[-1])


# Continue as soon as the draw reveal is shown (the roster reload, 300 ms, still
# running), then let the landing finish.
_CONTINUE = """
  drawCard();
  await advance(1400);
  out.label = els.revealActionBtn.textContent;
  const before = ANIMS.length;
  revealAction();
  out.hiddenAtOnce = modal().classList.contains("hidden");
  await advance(100);
  out.landingBeforeRoster = ANIMS.length - before;
  await advance(3000);
  const land = anims("draw-landing");
  out.landing = land.map(a => ({ style: a.style, first: a.keyframes[0].transform,
                                 last: a.keyframes[a.keyframes.length - 1].transform, duration: a.opts.duration }));
  out.rosterLoads = rosterLoads;
"""


# ---------------------------------------------------------------------------
# Story 1: Draw From the Deck
# ---------------------------------------------------------------------------

class TestDrawFromTheDeck:

    def test_index_html_draw_deck_is_decorative_card_back_stack(self):
        """The Draw panel shows a deck (#drawDeck): a small stack of .card-back layers next to the Draw buttons, aria-hidden="true"."""
        html = _read(INDEX_HTML)
        deck = _deck_markup(html)
        assert re.search(r'<div class="draw-deck" id="drawDeck" aria-hidden="true">', deck)
        assert deck.count('class="card-back draw-deck-layer"') == 3
        # Decorative only: no text, image or control inside the stack.
        assert re.sub(r"<[^>]*>", "", deck).strip() == ""
        assert "<img" not in deck and "<button" not in deck
        panel = _draw_panel(html)
        assert panel.index('id="drawDeck"') < panel.index('id="drawBtn"')

    def test_style_css_card_back_has_no_league_name_or_image_file(self):
        """The deck's .card-back is CSS only (brand pattern + emblem, tokens): no url() image file and no league name in its rules or markup."""
        css = _read(STYLE_CSS)
        blocks = [(sel, body) for sel, body in _css_blocks(css, r"\.card-back\b")]
        assert _rule(css, ".card-back"), "no .card-back rule"
        assert _rule(css, ".card-back::before") and _rule(css, ".card-back::after")
        base = _rule(css, ".card-back")[0]
        assert "repeating-linear-gradient" in base and "var(--accent-ghost)" in base
        for sel, body in blocks:
            assert "url(" not in body, sel
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), f"hex colour in {sel}"
            assert "content: \"\"" in body or "content" not in body, sel
            assert not re.search(r"kana|liiga", body, re.I), sel
        deck = _deck_markup(_read(INDEX_HTML))
        assert not re.search(r"kana|liiga", deck, re.I)
        assert css.index(".card-back {") < css.index("GUIDED TOUR (issue #144)")

    def test_draw_card_deck_stirs_until_result_and_image_decoded(self):
        """Node harness: pressing Draw adds .draw-deck--stirring to #drawDeck and keeps it until the draw result has arrived and its image is loaded and decoded."""
        out = _run("""
  out.before = stirring();
  DRAW.hold = true;
  drawCard();
  await advance(10);
  out.waitingForResult = stirring();
  heldDraws.forEach(f => f());
  await advance(10);
  out.resultArrived = stirring();
  loadImages();
  await advance(10);
  out.imageLoaded = stirring();
  decodeImages();
  await advance(10);
  out.imageDecoded = stirring();
  out.revealOpen = shown();
""", img="hold")
        assert out == {"before": False, "waitingForResult": True, "resultArrived": True,
                       "imageLoaded": True, "imageDecoded": False, "revealOpen": True}

    def test_draw_card_flight_starts_only_after_image_decoded(self):
        """Node harness: no animate() call happens before the stubbed Image has loaded and decode() resolved."""
        out = _run("""
  drawCard();
  await advance(500);
  out.beforeLoad = ANIMS.length;
  loadImages();
  await advance(20);
  out.afterLoad = ANIMS.length;
  out.revealBeforeDecode = shown();
  decodeImages();
  await advance(20);
  out.afterDecode = ANIMS.length;
  out.firstCls = ANIMS.length ? ANIMS[0].cls : null;
""", img="hold")
        assert out["beforeLoad"] == 0 and out["afterLoad"] == 0
        assert out["revealBeforeDecode"] is False
        assert out["afterDecode"] == 1 and out["firstCls"] == "draw-flight"

    def test_draw_card_flight_lifts_travels_flips_from_deck_to_modal_card(self):
        """Node harness: _playDrawFlight runs three animate() calls (lift, travel, flip) on a .draw-flight clone starting at #drawDeck's rect and ending at the modal card's rect; the clone is removed afterwards and the rarity burst starts at flip time."""
        out = _run("""
  drawCard();
  await advance(160);
  out.inFlight = flights().length;
  out.frontFace = flights().length ? flights()[0].children[0].children[0].children[0].className : null;
  out.backFace = flights().length ? flights()[0].children[0].children[1].className : null;
  await advance(3000);
  out.anims = ANIMS.map(a => ({ cls: a.cls, duration: a.opts.duration, burst: a.burst, style: a.style,
                                first: a.keyframes[0].transform, last: a.keyframes[a.keyframes.length - 1].transform }));
  out.afterFlight = flights().length;
  out.burstClasses = els.revealDrawBurst.className;
""")
        assert out["inFlight"] == 1
        assert out["frontFace"] == "draw-flight-img"
        assert "card-back" in out["backFace"].split()
        lift, travel, flip = out["anims"]
        assert [a["cls"] for a in out["anims"]] == ["draw-flight", "draw-flight", "draw-flight-inner"]
        assert [a["duration"] for a in out["anims"]] == [220, 460, 520]
        # The clone sits at the modal card's rect; the lift starts at the deck's rect.
        assert lift["style"] == {"left": "540px", "top": "200px", "width": "200px", "height": "283px"}
        assert lift["first"].startswith("translate(460px, -50px) scale(0.44, 0.44")
        assert "rotate(-3deg)" in lift["last"] and lift["last"] == travel["first"]
        assert travel["last"] == "none"
        assert flip["first"] == "rotateY(180deg)" and flip["last"].startswith("rotateY(0deg)")
        # The burst starts at the flip, not before.
        assert [a["burst"] for a in out["anims"]] == [False, False, True]
        assert "reveal-draw-burst--rarity-epic" in out["burstClasses"] or out["burstClasses"] == ""
        assert out["afterFlight"] == 0

    def test_draw_card_reveal_details_fade_in_after_flip(self):
        """Node harness: after the flip, showReveal shows rarity label, destination ("Added to active roster" / "Added to bench"), Reroll and Continue with the entering fade-in; the finished modal matches today's reveal."""
        steps = """
  drawCard();
  await advance(160);
  out.duringFlight = modal().className;
  await advance(1250);
  out.after = modal().className;
  out.rarity = els.revealRarity.textContent;
  out.destination = els.revealDestination.textContent;
  out.reroll = els.rerollBtn.style.display;
  out.action = [els.revealActionBtn.style.display, els.revealActionBtn.textContent];
  out.imgShown = [els.revealCardImg.style.display, els.revealImgPlaceholder.style.display];
  out.flights = flights().length;
  out.anims = ANIMS.length;
  await advance(1000);
  out.settled = modal().className;
"""
        out = _run(steps)
        assert set(out["duringFlight"].split()) >= {"reveal-overlay", "reveal-overlay--entering"}
        assert "hidden" not in out["duringFlight"].split()
        assert set(out["after"].split()) == {"reveal-overlay", "reveal-overlay--details-in"}
        assert out["settled"] == "reveal-overlay"
        assert out["rarity"] == "epic"
        assert out["destination"] == "Added to active roster"
        assert out["reroll"] == ""
        assert out["action"] == ["", "Continue"]
        assert out["imgShown"] == ["", "none"]
        bench = _run(steps, draw={"status": 200, "body": _card(is_active=False, card_type="common")})
        assert bench["destination"] == "Added to bench"
        assert bench["reroll"] == "none"  # a common card has no reroll, as today
        # No Web Animations API: no clone, no error, the same reveal shows at once.
        plain = _run(steps, no_animate=True)
        assert plain["anims"] == 0 and plain["flights"] == 0
        assert set(plain["duringFlight"].split()) == {"reveal-overlay", "reveal-overlay--details-in"}
        assert plain["destination"] == "Added to active roster" and plain["imgShown"] == ["", "none"]

    def test_booster_draw_flies_from_deck(self):
        """Node harness: confirming a team draw (_drawBoosterForTeam) stirs the deck and plays the same flight before the reveal."""
        out = _run("""
  _drawBoosterForTeam(4);
  out.stirAtStart = stirring();
  await advance(120);
  out.pickerHidden = els.boosterModal.classList.contains("hidden");
  await advance(3000);
  out.posts = posts();
  out.anims = ANIMS.map(a => a.cls);
  out.stirAfter = stirring();
  out.teamId = _revealBoosterTeamId;
  out.shown = shown() && !modal().classList.contains("reveal-overlay--entering");
  out.inFlight = _boosterDrawInFlight;
""")
        assert out["stirAtStart"] is True and out["stirAfter"] is False
        assert out["pickerHidden"] is True
        assert out["posts"] == ["POST /draw/booster/4"]
        assert out["anims"] == ["draw-flight", "draw-flight", "draw-flight-inner"]
        assert out["teamId"] == 4 and out["shown"] is True and out["inFlight"] is False

    @pytest.mark.parametrize("draw, message", [
        ({"status": 409, "body": {"detail": "Not enough Tokens"}}, "Not enough Tokens"),
        ({"status": 500, "body": {"detail": "Internal error"}}, "Internal error"),
        ({"reject": True}, "Failed to fetch"),
    ])
    def test_draw_card_failed_draw_plays_no_animation(self, draw, message):
        """Node harness: a failed draw (no tokens / roster full / 500) calls no animate(), does not stir past the response, opens no reveal and shows the error in #deckStatus as today."""
        out = _run("""
  drawCard();
  await advance(3000);
  out.anims = ANIMS.length;
  out.stirring = stirring();
  out.shown = shown();
  out.status = [els.deckStatus.textContent, els.deckStatus.className];
  out.images = IMAGES.length;
  out.btn = els.drawBtn.disabled;
""", draw=draw)
        assert out == {"anims": 0, "stirring": False, "shown": False, "status": [message, "status err"],
                       "images": 0, "btn": False}

    def test_draw_card_slow_image_starts_flight_at_three_seconds(self):
        """Node harness: when the image has not loaded after 3 s, the flight still runs and flips to the rarity face; the PNG appears in the modal when it loads."""
        out = _run("""
  drawCard();
  await advance(2990);
  out.at2990 = [ANIMS.length, stirring()];
  await advance(20);
  out.at3010 = [ANIMS.length, stirring()];
  const face = flights()[0].children[0].children[0].children[0];
  out.face = [face.className, face.textContent];
  await advance(2000);
  out.anims = ANIMS.map(a => a.cls);
  out.placeholder = [els.revealImgPlaceholder.style.display, els.revealImgPlaceholder.textContent];
  out.img = els.revealCardImg.style.display;
  loadImages();
  await advance(500);
  out.loaded = [els.revealCardImg.style.display, els.revealCardImg.style.visibility, els.revealImgPlaceholder.style.display];
""", img="never")
        assert out["at2990"] == [0, True]
        assert out["at3010"] == [1, False]
        assert out["face"] == ["draw-flight-rarity draw-flight-rarity--epic", "EPIC"]
        assert out["anims"] == ["draw-flight", "draw-flight", "draw-flight-inner"]
        assert out["placeholder"] == ["flex", "EPIC"] and out["img"] == "none"
        assert out["loaded"] == ["", "visible", "none"]

    def test_draw_card_image_error_shows_rarity_fallback(self):
        """Node harness: an image error still plays the flight and the reveal shows today's rarity fallback text instead of the PNG."""
        out = _run("""
  drawCard();
  await advance(150);
  out.face = flights().length ? flights()[0].children[0].children[0].children[0].className : null;
  await advance(3000);
  out.anims = ANIMS.map(a => a.cls);
  out.placeholder = [els.revealImgPlaceholder.style.display, els.revealImgPlaceholder.textContent];
  out.img = els.revealCardImg.style.display;
  out.shown = shown();
""", img="error")
        assert out["face"] == "draw-flight-rarity draw-flight-rarity--epic"
        assert out["anims"] == ["draw-flight", "draw-flight", "draw-flight-inner"]
        assert out["placeholder"] == ["flex", "EPIC"] and out["img"] == "none"
        assert out["shown"] is True

    def test_draw_card_button_stays_busy_until_reveal_shown(self):
        """Node harness: #drawBtn stays busy through stir and flight; a second Draw press during the animation sends no second POST /draw."""
        out = _run("""
  drawCard();
  await advance(10);
  out.stir = els.drawBtn.disabled;
  drawCard();
  await advance(10);
  loadImages(); decodeImages();
  await advance(400);
  out.flight = [els.drawBtn.disabled, flights().length];
  drawCard();
  revealAction();
  await advance(10);
  out.stillEntering = modal().classList.contains("reveal-overlay--entering");
  await advance(3000);
  out.after = els.drawBtn.disabled;
  out.posts = posts();
""", img="hold")
        assert out["stir"] is True
        assert out["flight"] == [True, 1]
        assert out["stillEntering"] is True  # Enter/Continue does nothing mid-flight
        assert out["after"] is False
        assert out["posts"] == ["POST /draw"]

    def test_draw_card_reduced_motion_skips_flight_and_burst(self):
        """Node harness with reduced motion: no animate() call and no burst; the finished reveal fades in after the result and image are ready."""
        out = _run("""
  drawCard();
  await advance(10);
  loadImages();
  await advance(10);
  out.beforeDecode = shown();
  decodeImages();
  await advance(10);
  out.afterDecode = [shown(), modal().className];
  await advance(3000);
  out.anims = ANIMS.length;
  out.flights = flights().length;
  out.burst = burstEver();
  out.btn = els.drawBtn.disabled;
""", img="hold", reduced=True)
        assert out["beforeDecode"] is False
        assert out["afterDecode"][0] is True
        assert set(out["afterDecode"][1].split()) == {"reveal-overlay", "reveal-overlay--fade-in"}
        assert out["anims"] == 0 and out["flights"] == 0 and out["burst"] is False
        assert out["btn"] is False

    def test_style_css_reduced_motion_covers_flight_flip_stir_and_landing(self):
        """style.css has prefers-reduced-motion: reduce rules covering .draw-flight, the flip faces, .draw-deck--stirring and the landing."""
        css = _read(STYLE_CSS)
        reduced = _reduced_motion_css(_before_tour(css))
        for sel in (".draw-flight", ".draw-flight-inner", ".draw-flight-face", ".draw-deck--stirring",
                    ".draw-landing", ".card-slot--arrived"):
            assert sel in reduced, sel
        assert re.search(r"\.draw-flight,\s*\.draw-landing\s*\{\s*display: none;", reduced)
        # The flip faces exist outside the media query: back face turned, hidden backface.
        face = _rule(css, ".draw-flight-face")[0]
        assert "backface-visibility: hidden" in face
        assert "rotateY(180deg)" in _rule(css, ".draw-flight-face--back")[0]
        stir = [b for s, b in _css_blocks(css, r"\.draw-deck--stirring") if "animation:" in b and "none" not in b]
        assert stir and all("draw-deck-stir" in b for b in stir)
        # New #205 rules sit before the guided tour section and use tokens, not hex.
        start = css.index("DRAW PANEL: DECK AND CHANCES (issue #205)")
        assert start < css.index("GUIDED TOUR (issue #144)")
        for header in ("DRAW PANEL: DECK AND CHANCES (issue #205)", "DRAW FROM THE DECK (issue #205)"):
            i = css.index(header) + len(header)
            section = css[i:css.index("/* ====", i)]
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", section), header


# ---------------------------------------------------------------------------
# Story 2: Deck in My Team
# ---------------------------------------------------------------------------

class TestDeckInMyTeam:

    def test_index_html_deck_beside_compact_chances_strip(self):
        """The Draw sidebar starts with the deck (three stacked card backs) beside a compact "Chance per draw" strip that keeps .rarity-grid and the #deck-common/-rare/-epic/-legendary ids."""
        html = _read(INDEX_HTML)
        panel = _draw_panel(html)
        top = panel[panel.index('<div class="draw-top">'):panel.index('id="drawBtn"')]
        assert top.index('id="drawDeck"') < top.index('class="draw-chances"')
        assert _deck_markup(html).count("card-back") == 3
        assert '<h3 class="draw-chances-title">Chance per draw</h3>' in top
        assert top.count('<div class="rarity-grid">') == 1
        for r in _RARITIES:
            assert f'id="deck-{r}"' in top
        # The old thumbnails are gone; the guided tour still targets .rarity-grid.
        assert "rarity-card-thumb" not in html and "Card_Template_" not in panel
        assert 'target: ".rarity-grid"' in _read(os.path.join(FRONTEND_DIR, "app-tour.js"))
        css = _read(STYLE_CSS)
        assert "repeat(2, minmax(0, 1fr))" in _rule(css, ".rarity-grid")[0]
        assert "display: flex" in _rule(css, ".draw-top")[0]

    def test_chances_strip_shows_dot_name_and_percentage_from_draw_rates(self):
        """Each of the four strip entries shows a rarity-coloured dot, the rarity name and the percentage loaded from /config draw_rates (draw_rate_* weights) as today."""
        html = _read(INDEX_HTML)
        css = _read(STYLE_CSS)
        for r in _RARITIES:
            m = re.search(rf'<div class="rarity-chance rarity-chance--{r}">(.*?)</div>', html)
            assert m, r
            entry = m.group(1)
            assert '<span class="rarity-dot" aria-hidden="true"></span>' in entry
            assert f'<span class="rarity-chance-name">{r.capitalize()}</span>' in entry
            assert f'<span class="count" id="deck-{r}">—</span>' in entry
            assert f"var(--k-rarity-{r})" in _rule(css, f".rarity-chance--{r}")[0]
        assert "var(--rarity-color" in _rule(css, ".rarity-dot")[0]
        assert "tabular-nums" in _rule(css, ".rarity-chance .count")[0]
        body = _fn_body(_read(CARDS_JS), "loadDeck")
        assert "cfg.draw_rates" in body and '`${rates[r]}%`' in body
        out = _run("""
  await loadDeck();
  out.rates = ["common", "rare", "epic", "legendary"].map(r => els["deck-" + r].innerHTML);
  out.fetches = fetchLog;
""")
        assert out["rates"] == ["60%", "25%", "10%", "5%"]
        assert out["fetches"] == ["GET /config"]

    def test_index_html_draw_buttons_hint_promo_and_status_below_deck_unchanged(self):
        """The Draw buttons, hint, promo code and #deckStatus line stay below the deck and strip, with their ids and handlers unchanged."""
        html = _read(INDEX_HTML)
        start = html.index("<h2>Draw</h2>")
        order = ['<div class="draw-top">', '<button id="drawBtn" onclick="drawCard()">Draw a card</button>',
                 '<button id="boosterBtn" class="secondary" onclick="openBoosterModal()">',
                 '<span id="drawCounter"', '<div id="boosterHint"', '<input id="redeemCodeInput"',
                 '<button id="redeemBtn" class="secondary" onclick="redeemCode()">Redeem</button>',
                 '<div class="status" id="deckStatus"></div>']
        positions = [html.index(s, start) for s in order]
        assert positions == sorted(positions)

    def test_reveal_continue_lands_on_roster_slot_when_active(self):
        """Node harness: Continue after an is_active draw closes the modal and, after loadRoster renders, animates a clone to that card's roster slot rect (about 520 ms)."""
        out = _run(_CONTINUE + """
  out.slotVisible = _rosterNodes.get(9).style.visibility;
  out.arrived = _rosterNodes.get(9).classList.log.includes("card-slot--arrived");
  out.flights = flights().length;
""")
        assert out["label"] == "Continue"
        assert out["hiddenAtOnce"] is True
        assert out["landingBeforeRoster"] == 0  # waits for loadRoster to re-render
        assert len(out["landing"]) == 1
        land = out["landing"][0]
        # Card 9 is the fifth roster slot: x = 4 * 160, roster top 100, slot 150 x 212.
        assert land["style"] == {"left": "640px", "top": "100px", "width": "150px", "height": "212px"}
        assert land["first"].startswith("translate(-100px, 100px) scale(1.33")
        assert land["last"] == "none" and land["duration"] == 520
        assert out["slotVisible"] == "" and out["arrived"] is True and out["flights"] == 0
        assert out["rosterLoads"] == 1

    def test_reveal_continue_lands_on_bench_front_when_not_active(self):
        """Node harness: Continue after a bench draw ("Added to bench") animates the clone to the first bench card's rect."""
        out = _run(_CONTINUE + """
  out.destination = els.revealDestination.textContent;
  out.benchFront = els.benchGrid.children[0].dataset.cardId;
""", draw={"status": 200, "body": _card(is_active=False)}, before=_FULL_BEFORE, after=_ROSTER_BENCH)
        assert out["benchFront"] == "9"
        assert len(out["landing"]) == 1
        assert out["landing"][0]["style"] == {"left": "0px", "top": "450px", "width": "150px", "height": "212px"}

    def test_roster_mark_arrived_glows_card_once(self):
        """app-roster.js markArrived(cardId) adds a one-time rarity glow (about 1.2 s) to the arrived card and removes it afterwards; roster count and bench update as today."""
        js = _read(ROSTER_JS)
        assert re.search(r"^const ROSTER_ARRIVED_MS = 1200;$", js, re.M)
        body = _fn_body(js, "markArrived")
        assert 'node.classList.add("card-slot--arrived");' in body
        assert 'setTimeout(() => node.classList.remove("card-slot--arrived"), ROSTER_ARRIVED_MS)' in body
        css = _read(STYLE_CSS)
        glow = _rule(css, ".card-slot.card-slot--arrived .card-img")[0]
        assert "card-arrived-glow 1200ms" in glow and " 1;" in glow
        for r in _RARITIES:
            assert f"var(--k-rarity-{r})" in _rule(css, f'.card-slot[data-rarity="{r}"]')[-1]
        out = _run("""
  await drawAndReveal();
  revealAction();
  await advance(520 + 50);
  out.during = _rosterNodes.get(9).classList.contains("card-slot--arrived");
  await advance(1200);
  out.after = _rosterNodes.get(9).classList.contains("card-slot--arrived");
  out.others = [..._rosterNodes.values()].filter(n => n.classList.log.includes("card-slot--arrived")).map(n => n.dataset.cardId);
  out.roster = els.rosterActiveGrid.children.map(c => c.dataset.cardId || "empty");
  out.loads = rosterLoads;
""")
        assert out["during"] is True and out["after"] is False
        assert out["others"] == ["9"]
        assert out["roster"] == ["1", "2", "3", "4", "9"] and out["loads"] == 1

    @pytest.mark.parametrize("after, inner_height", [
        ({"active": [1, 2, 3, 4, 5], "bench": [7, 8]}, 900),   # the card's slot is not in the grids
        (_ROSTER_ACTIVE, 90),                                     # the slot is below the viewport
    ])
    def test_reveal_landing_slot_missing_falls_back_above_viewport(self, after, inner_height):
        """Node harness: when the target slot is not found or is off screen, the landing flies to a point above the viewport and raises no error."""
        out = _run(_CONTINUE + """
  out.flights = flights().length;
  out.status = els.deckStatus.textContent;
""", before=_FULL_BEFORE if after["active"][4] == 5 else None, after=after, inner_height=inner_height)
        assert len(out["landing"]) == 1
        style = out["landing"][0]["style"]
        assert float(style["top"].rstrip("px")) + float(style["height"].rstrip("px")) < 0
        assert out["flights"] == 0 and out["status"] == ""

    def test_reveal_draw_another_card_skips_landing(self):
        """Node harness: "Draw another card" calls no landing animate() and starts the next draw from the deck."""
        out = _run("""
  await drawAndReveal();
  out.label = els.revealActionBtn.textContent;
  const first = ANIMS.length;
  revealAction();
  await advance(10);
  out.stirring = stirring();
  await advance(3000);
  out.landing = anims("draw-landing").length;
  out.nextFlight = ANIMS.slice(first).map(a => a.cls);
  out.posts = posts();
  out.shown = shown();
""", draw={"status": 200, "body": _card(tokens=4)})
        assert out["label"] == "Draw another card"
        assert out["stirring"] is True
        assert out["landing"] == 0
        assert out["nextFlight"] == ["draw-flight", "draw-flight", "draw-flight-inner"]
        assert out["posts"] == ["POST /draw", "POST /draw"]
        assert out["shown"] is True

    @pytest.mark.parametrize("close", ["closeReveal()", "modal().onclick({ target: modal() })"])
    def test_reveal_close_x_escape_backdrop_skip_landing(self, close):
        """Node harness: closing the reveal by X, Escape or backdrop plays no landing flight; the roster still reloads as today."""
        out = _run("""
  await drawAndReveal();
  __CLOSE__;
  out.hidden = modal().classList.contains("hidden");
  await advance(3000);
  out.landing = anims("draw-landing").length;
  out.arrived = _rosterNodes.get(9).classList.log.includes("card-slot--arrived");
  out.loads = rosterLoads;
  out.roster = els.rosterActiveGrid.children.map(c => c.dataset.cardId || "empty");
""".replace("__CLOSE__", close))
        assert out == {"hidden": True, "landing": 0, "arrived": False, "loads": 1,
                       "roster": ["1", "2", "3", "4", "9"]}
        # X and Escape both call closeReveal (the reveal declares data-close="closeReveal").
        html = _read(INDEX_HTML)
        reveal = html[html.index('id="revealModal"') - 40:html.index('id="revealDrawBurst"')]
        assert 'data-close="closeReveal"' in reveal

    @pytest.mark.parametrize("active, text", [(True, "Added to active roster"), (False, "Added to bench")])
    def test_reveal_continue_phone_width_shows_landed_notice(self, active, text):
        """Node harness below 768 px: the card flies up off the top edge and #drawLandedNotice shows "Added to active roster" / "Added to bench" for 5 seconds."""
        out = _run(_CONTINUE + """
  out.notice = [els.drawLandedNotice.style.display, els.drawLandedNoticeText.textContent];
  out.glowNow = _rosterNodes.get(9).classList.log.includes("card-slot--arrived");
  await advance(5000);
  out.noticeLater = els.drawLandedNotice.style.display;
""", width=375, draw={"status": 200, "body": _card(is_active=active)},
            before=None if active else _FULL_BEFORE, after=_ROSTER_ACTIVE if active else _ROSTER_BENCH)
        assert len(out["landing"]) == 1
        style = out["landing"][0]["style"]
        assert float(style["top"].rstrip("px")) + float(style["height"].rstrip("px")) < 0
        assert out["notice"] == ["", text]
        assert out["glowNow"] is False  # the glow waits for See roster
        assert out["noticeLater"] == "none"
        html = _read(INDEX_HTML)
        assert re.search(r'<div class="draw-landed-notice" id="drawLandedNotice" role="status" '
                         r'aria-live="polite" style="display:none;">', html)

    def test_landed_notice_see_roster_scrolls_to_roster_and_glows(self):
        """Node harness: "See roster" in #drawLandedNotice scrolls #rosterActiveGrid into view and the new card glows once."""
        html = _read(INDEX_HTML)
        assert '<button type="button" class="draw-landed-notice-link" onclick="seeLandedCard()">See roster &uarr;</button>' in html
        out = _run(_CONTINUE + """
  out.before = els.rosterActiveGrid.scrolled;
  seeLandedCard();
  out.scrolled = els.rosterActiveGrid.scrolled;
  out.glow = _rosterNodes.get(9).classList.contains("card-slot--arrived");
  out.notice = els.drawLandedNotice.style.display;
  await advance(1300);
  out.glowAfter = _rosterNodes.get(9).classList.contains("card-slot--arrived");
""", width=375)
        assert out["before"] is None
        assert out["scrolled"] == {"block": "start", "behavior": "smooth"}
        assert out["glow"] is True and out["glowAfter"] is False
        assert out["notice"] == "none"

    def test_reveal_continue_reduced_motion_no_landing_flight_but_glow(self):
        """Node harness with reduced motion: Continue calls no landing animate(); the card appears in its slot with the markArrived glow."""
        out = _run(_CONTINUE + """
  out.arrived = _rosterNodes.get(9).classList.log.includes("card-slot--arrived");
  out.anims = ANIMS.length;
  out.inSlot = els.rosterActiveGrid.children[4].dataset.cardId;
""", reduced=True)
        assert out["landing"] == [] and out["anims"] == 0
        assert out["arrived"] is True and out["inSlot"] == "9"
