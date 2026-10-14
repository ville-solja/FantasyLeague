"""
Tests for plan-issue-155-my-team-motion.md (resolves GitHub issue #155).

My Team gains motion for the moments that change the player's team while they
weren't looking. Frontend only: no backend, schema or env change.

  Shared: motion helpers and CSS          (TestSharedMotionHelpers)
  Story 1: New Points Count Up            (TestNewPointsCountUp)
  Story 2: Cards Slide Between Bench and Roster -- moved to #186, already
           implemented and covered by test_issue_186_my_team_save_roster.py;
           not stubbed here.
  Story 3: The Week Lock Has a Moment     (TestWeekLockMoment)
  Story 4: Substitutions Play Out Once    (TestSubstitutionsPlayOnce)
  Story 5: Token Gains Are Noticed        (TestTokenGains)

Approach notes for the implementer:

- What #186 already built (frontend/app-globals.js): `prefersReducedMotion()` and
  `flipMove(els, first, opts)` with `FLIP_DURATION_MS = 220`. Note the real
  signature: `first` is a Map element -> rect taken before the DOM change, not the
  plan's `flipMove(elements, mutate)`. Reuse both; don't add a second definition.
  The plan's "FLIP runs only after a successful response" test no longer applies:
  #186 made moves local-first with autosave.
- Still to build (Step 1 of the plan), in app-globals.js: `seenStore(key)`
  (localStorage get/set, every access in try/catch, capped lists) and
  `tweenNumber(el, from, to, ms)` (requestAnimationFrame; returns a finish
  function; ends exactly at `to`). Cancellation with a run id per animation group,
  like `_recapAnimation` in app-weekly-summary.js (#152).
- Behaviour tests: reuse the Node harness `_HARNESS` / `_run(steps, data, reduced)`
  from test_issue_186_my_team_save_roster.py (fake DOM with fixed layout, `fire()`,
  fake timers / frames / fetch, `__REDUCED__` switch). Extend `_globals_src()` with
  `seenStore`, `tweenNumber` and `updateTokenDisplay`, and give the harness a fake
  `localStorage` (plus a variant whose methods throw). Import or copy the helpers;
  skip when Node is missing, as #186 does.
- Static checks: `_read`, `_css_blocks`, `_fn_body`, `_rule(css, selector)` and
  `_before_tour(css)` from test_issue_186 / test_issue_151. New CSS goes before the
  "GUIDED TOUR (issue #144)" section and uses tokens only (no hex).
- Data the page has today (check before pinning): `GET /roster/{user_id}` returns
  per-card `total_points`, `subbed_in`, `subbed_in_for`, `subbed_out`, week
  `is_locked` and a boolean `substitutions_done` (not `substitutions_at`). "A re-run
  that changes the substitutions plays again" therefore needs a signature of the
  result (e.g. sorted subbed_out -> subbed_in card id pairs) stored with the week
  id. The week total is "This week" (`#rosterCombined`, `combined_value`), not
  a `week_total` field; Story 1 counts it up.
- Token chip: `#headerTokenNum` inside `#tokenBalance`; callers of
  `updateTokenDisplay` are in app-auth.js (login / logout with null), app-cards.js
  (draws, MVP), app-roster.js.

Manual-only (plan's Verification section): real timing and smoothness, the visual
glow / stamp / pulse, no console errors after leaving mid-animation.

Run with: cd backend && python3 -m pytest tests/test_issue_155_my_team_motion.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import re
import subprocess

from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _fn_body, _read
from tests.test_issue_159_flicker_free_tab_switching import _node
from tests.test_issue_186_my_team_save_roster import (
    _HARNESS, _NOW_S, _before_tour, _c, _roster, _rule,
)


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
ROSTER_JS = os.path.join(FRONTEND_DIR, "app-roster.js")
GLOBALS_JS = os.path.join(FRONTEND_DIR, "app-globals.js")
STYLE_CSS = os.path.join(FRONTEND_DIR, "style.css")

_MOTION_START = "My Team motion (issue #155)"
_MOTION_END = "End My Team motion"

# Every class of the #155 block that runs a keyframe animation.
_ANIMATED = [
    ".card-slot.roster-pts-glow .card-img",
    ".roster-pts-float",
    "#rosterLockedBanner.roster-lock-stamp",
    ".roster-lock-stamp .roster-lock-shackle",
    ".roster-lock-enter .card-slot .card-img",
    ".card-slot.roster-sub-out",
    ".card-slot.roster-sub-in .card-slot-note",
    ".header-tokens.token-chip-pulse",
    ".token-float",
]


# ---------------------------------------------------------------------------
# Node harnesses
# ---------------------------------------------------------------------------

def _patch(src, old, new):
    assert old in src, f"harness anchor moved: {old[:60]}"
    return src.replace(old, new, 1)


# Fake localStorage: "ok" (a Map, pre-filled from __STORAGE__), "throw" (every method
# throws, as with blocked storage) or "missing" (no localStorage at all).
_STORAGE_JS = r"""
const _store = new Map(Object.entries(__STORAGE__));
const STORAGE_MODE = "__STORAGE_MODE__";
if (STORAGE_MODE === "ok") {
  globalThis.localStorage = { getItem: k => (_store.has(k) ? _store.get(k) : null),
                              setItem: (k, v) => { _store.set(k, String(v)); },
                              removeItem: k => { _store.delete(k); } };
} else if (STORAGE_MODE === "throw") {
  const no = () => { throw new Error("SecurityError: storage blocked"); };
  globalThis.localStorage = { getItem: no, setItem: no, removeItem: no };
}
const stored = k => (_store.has(k) ? JSON.parse(_store.get(k)) : null);
"""

# app-roster.js harness of #186, plus localStorage and card markup that becomes child
# elements (.card-slot-pts, .card-slot-note), so the count-up can find its number.
_ROSTER_HARNESS = _patch(
    _patch(_HARNESS,
           "set innerHTML(v) { this._html = String(v); this.innerHTMLWrites++; }",
           "set innerHTML(v) { this._html = String(v); this.innerHTMLWrites++;"
           " this.children.forEach(c => { c.parentNode = null; }); this.children = [];"
           " for (const m of this._html.matchAll(/<(div|span) class=\"([^\"]+)\"[^>]*>([^<]*)<\\/\\1>/g)) {"
           " const k = new El(m[1]); k.className = m[2]; k.textContent = m[3]; this.appendChild(k); } }"),
    'const API = "";', _STORAGE_JS + '\nconst API = "";')


def _globals_src(names):
    js = _read(GLOBALS_JS)
    lines = [re.search(pat, js, re.M).group(0) for pat in (
        r"^const _lastHtml = new WeakMap\(\);$",
        r"^const FLIP_DURATION_MS = \d+;$",
        r"^const _tokenMotion = .*;$",
        r"^const TOKEN_COUNT_UP_MS = \d+;$",
    )]
    return "\n".join(lines + [_fn_body(js, n) + "\n}\n" for n in names])


_ROSTER_GLOBALS = ("renderIfChanged", "forgetRendered", "_escHtml", "switchTab",
                   "prefersReducedMotion", "flipMove", "seenStore", "tweenNumber")


def _run(steps, data=None, reduced=False, storage=None, storage_mode="ok"):
    """Run `steps` after `await loadRoster(null)` in the roster harness, with
    localStorage pre-filled from `storage` (values JSON-encoded); returns `out`, or
    None when Node is not installed."""
    node = _node()
    if not node:
        return None
    script = (_ROSTER_HARNESS.replace("__NOW__", str(_NOW_S * 1000))
              .replace("__REDUCED__", "true" if reduced else "false")
              .replace("__STORAGE_MODE__", storage_mode)
              .replace("__STORAGE__", json.dumps({k: json.dumps(v) for k, v in (storage or {}).items()}))
              .replace("__DATA__", json.dumps(data if data is not None else _roster()))
              .replace("__GLOBALS__", _globals_src(_ROSTER_GLOBALS))
              .replace("__ROSTER__", _read(ROSTER_JS))
              .replace("__STEPS__", steps))
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-3000:]
    return json.loads(res.stdout)


# Header token chip: updateTokenDisplay and the helpers it uses, a tiny fake DOM,
# fake timers and frames.
_TOKEN_HARNESS = r"""
let NOW = 1000;
Date.now = () => NOW;
const REDUCED = __REDUCED__;
let _timers = [], _tid = 0;
globalThis.setTimeout = (fn, ms) => { const id = ++_tid; _timers.push({ id, at: NOW + (ms || 0), fn }); return id; };
globalThis.clearTimeout = id => { _timers = _timers.filter(t => t.id !== id); };
function advance(ms) {
  const end = NOW + ms;
  for (;;) {
    _timers.sort((a, b) => a.at - b.at || a.id - b.id);
    const t = _timers[0];
    if (!t || t.at > end) break;
    _timers.shift(); NOW = t.at; t.fn();
  }
  NOW = end;
}
let _frames = [], _fid = 0;
globalThis.requestAnimationFrame = fn => { const id = ++_fid; _frames.push({ id, fn }); return id; };
globalThis.cancelAnimationFrame = id => { _frames = _frames.filter(f => f.id !== id); };
function frame() { const fs = _frames; _frames = []; fs.forEach(f => f.fn(NOW)); }
class El {
  constructor(id) { this.id = id || ""; this.children = []; this.parentNode = null; this.textContent = "";
    this.style = {}; this.attrs = {}; this.set = new Set(); const self = this;
    this.classList = { add: c => self.set.add(c), remove: c => self.set.delete(c), contains: c => self.set.has(c) }; }
  get className() { return [...this.set].join(" "); }
  set className(v) { this.set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get offsetWidth() { return 0; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  remove() { if (this.parentNode) { const p = this.parentNode; p.children = p.children.filter(x => x !== this); this.parentNode = null; } }
  setAttribute(k, v) { this.attrs[k] = String(v); }
}
const els = {};
globalThis.window = { matchMedia: q => ({ matches: REDUCED && q.includes("reduce") }) };
globalThis.document = { body: new El("body"), createElement: () => new El(),
  getElementById(id) { if (!els[id]) els[id] = new El(id); return els[id]; } };
""" + _STORAGE_JS + r"""
let activeUserId = 1;
let _tokenBalance = null;
let _tokenName = "Tokens";
__GLOBALS__
const chip = document.getElementById("tokenBalance");
const num = document.getElementById("headerTokenNum");
const state = () => ({ text: String(num.textContent), pulse: chip.classList.contains("token-chip-pulse"),
  floats: chip.children.filter(c => c.className === "token-float").map(c => [c.textContent, c.attrs["aria-hidden"]]),
  frames: _frames.length, display: chip.style.display });
(async () => {
  const out = {};
__STEPS__
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _run_tokens(steps, reduced=False, storage=None):
    node = _node()
    if not node:
        return None
    names = ("prefersReducedMotion", "seenStore", "tweenNumber", "updateTokenDisplay", "_showTokenBalance")
    script = (_TOKEN_HARNESS.replace("__REDUCED__", "true" if reduced else "false")
              .replace("__STORAGE_MODE__", "ok")
              .replace("__STORAGE__", json.dumps({k: json.dumps(v) for k, v in (storage or {}).items()}))
              .replace("__GLOBALS__", _globals_src(names))
              .replace("__STEPS__", steps))
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-3000:]
    return json.loads(res.stdout)


def _css():
    return _read(STYLE_CSS)


def _motion_css():
    css = _css()
    start = css.index(_MOTION_START)
    return css[start:css.index(_MOTION_END, start)]


def _reduced_bodies(css):
    """The bodies of every @media (prefers-reduced-motion: reduce) block."""
    out = []
    for m in re.finditer(r"@media \(prefers-reduced-motion: reduce\)\s*\{", css):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.end():i - 1])
    return out


def _keyframes(css, name):
    m = re.search(r"@keyframes " + re.escape(name) + r"\s*\{", css)
    assert m, name
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        i += 1
    return css[m.end():i - 1]


# Story 1 data: roster cards 1-3 with 10 / 5 / 3 points this week (total 18), and what
# the last visit showed: card 1 had 4 points (a rise of 6), the total 12.
_SEEN_KEY = "rosterSeenPoints:1:5"


def _points_roster(p1=10.0, locked=False):
    active = [_c(1, 101, 0, True), _c(2, 102, 1, True), _c(3, 103, 2, True)]
    for c, p in zip(active, (p1, 5.0, 3.0)):
        c["total_points"] = p
    r = _roster(active=active, locked=locked)
    r["combined_value"] = p1 + 8.0
    return r


_LAST_VISIT = {_SEEN_KEY: {"cards": {"1": 4.0, "2": 5.0, "3": 3.0}, "total": 12.0}}

_PTS_JS = """
const pts = id => node(id).querySelector(".card-slot-pts");
const ptsState = id => { const p = pts(id); return { text: p.textContent, kids: p.children.map(k => [k.textContent, k.attrs["aria-hidden"] || null, k.className]) }; };
const glow = id => node(id).classList.contains("roster-pts-glow");
const floats = id => node(id).children.filter(k => k.className === "roster-pts-float").map(k => [k.textContent, k.attrs["aria-hidden"]]);
const total = () => ({ text: els.rosterCombined.textContent, kids: els.rosterCombined.children.map(k => [k.textContent, k.attrs["aria-hidden"] || null, k.className]) });
"""


# Story 3/4 data: a locked week. Substitutions: card 7 came in for card 2 (P102) in slot
# 1, card 8 for card 4 (P104) in slot 3; card 9 is the saved bench.
def _subs_roster(done=True, subs=True):
    active = [_c(1, 101, 0, True), _c(7, 107, 1, True), _c(3, 103, 2, True), _c(8, 108, 3, True)]
    bench = [_c(2, 102, None), _c(4, 104, None), _c(9, 109, 0)]
    if subs:
        for c, who in ((active[1], "P102"), (active[3], "P104")):
            c["subbed_in"] = True
            c["subbed_in_for"] = who
        bench[0]["subbed_out"] = bench[1]["subbed_out"] = True
    r = _roster(active=active, bench=bench, locked=True, starts_in=-3 * 86400)
    r["substitutions_done"] = done
    r["week"]["substitutions_done"] = done
    return r


_LOCK_SEEN = {"rosterLockSeen:1": [5]}

_SUBS_JS = """
const cls = id => ["roster-sub-pending", "roster-sub-in", "roster-sub-out"].filter(c => node(id).classList.contains(c));
const snap = () => ({ active: ids("rosterActiveGrid"), bench: ids("benchGrid") });
"""

_FINAL = {"active": [1, 7, 3, 8, "empty:4"], "bench": [2, 4, 9]}
_BEFORE = {"active": [1, 2, 3, 4, "empty:4"], "bench": [7, 8, 9]}


# ---------------------------------------------------------------------------
# Shared: motion helpers and CSS (plan Step 1)
# ---------------------------------------------------------------------------

class TestSharedMotionHelpers:
    """
    - One shared helper set in app-globals.js: prefersReducedMotion, flipMove
      (both from #186), seenStore, tweenNumber.
    - localStorage access never throws out of the helpers.
    - Every new keyframe class is switched off under prefers-reduced-motion.
    """

    def test_motion_helpers_defined_once_in_globals(self):
        """prefersReducedMotion, flipMove, seenStore and tweenNumber are each defined exactly once, in app-globals.js (no copies in app-roster.js)."""
        others = [f for f in os.listdir(FRONTEND_DIR) if f.endswith(".js") and f != "app-globals.js"]
        for name in ("prefersReducedMotion", "flipMove", "seenStore", "tweenNumber"):
            pat = re.compile(r"(?<![\w$])function\s+" + name + r"\s*\(")
            assert len(pat.findall(_read(GLOBALS_JS))) == 1, name
            for f in others:
                assert not pat.search(_read(os.path.join(FRONTEND_DIR, f))), (name, f)
        roster = _read(ROSTER_JS)
        assert "seenStore(" in roster and "tweenNumber(" in roster and "flipMove(" in roster

    def test_tween_number_ends_at_target(self):
        """tweenNumber(el, from, to, ms) writes `to` as the element's final text after `ms` of frames."""
        out = _run("""
  const el = document.createElement("span");
  let done = 0;
  tweenNumber(el, 0, 10, 600, { onDone: () => done++ });
  out.start = el.textContent;
  frame();
  await advance(300); frame();
  out.mid = Number(el.textContent);
  await advance(300); frame();
  out.end = el.textContent;
  out.frames = _frames.length;
  out.done = done;
""")
        if out is None:
            return
        assert out["start"] == "0"
        assert 0 < out["mid"] < 10
        assert out["end"] == "10"
        assert out["frames"] == 0
        assert out["done"] == 1

    def test_tween_number_finish_jumps_to_target(self):
        """Calling the finish function tweenNumber returns sets the target value at once and stops further frames."""
        out = _run("""
  const el = document.createElement("span");
  let done = 0;
  const finish = tweenNumber(el, 2, 9, 1000, { onDone: () => done++ });
  frame();
  await advance(100); frame();
  finish();
  out.after = el.textContent;
  out.frames = _frames.length;
  el.textContent = "untouched";
  await advance(2000); frame();
  out.later = el.textContent;
  finish();
  out.done = done;
""")
        if out is None:
            return
        assert out == {"after": "9", "frames": 0, "later": "untouched", "done": 1}

    def test_seen_store_survives_throwing_local_storage(self):
        """seenStore get/set return a safe default and don't throw when localStorage is missing or its methods throw."""
        steps = """
  const s = seenStore("k");
  out.get = s.get(7);
  s.set({ a: 1 });
  s.add(5);
  out.has = s.has(5);
  out.after = s.get("fallback");
  out.status = status();
  out.rendered = ids("rosterActiveGrid");
"""
        for mode in ("throw", "missing"):
            out = _run(steps, storage_mode=mode, data=_points_roster())
            if out is None:
                return
            assert out["get"] == 7
            assert out["has"] is False
            assert out["after"] == "fallback"
            # loadRoster (with every motion store) still renders the roster.
            assert out["rendered"] == [1, 2, 3, "empty:3", "empty:4"]
            assert out["status"] == "3/5 active"
        out = _run('localStorage.setItem("bad", "{not json"); out.bad = seenStore("bad").get(3);')
        assert out["bad"] == 3
        assert "try {" in _fn_body(_read(GLOBALS_JS), "seenStore")

    def test_seen_store_caps_list_length(self):
        """A capped seenStore list keeps only the newest N entries (e.g. 50 week ids)."""
        out = _run("""
  const s = seenStore("weeks");
  for (let i = 0; i < 60; i++) s.add(i, 50);
  out.list = stored("weeks");
  s.add(20, 50);
  out.readd = stored("weeks");
""")
        if out is None:
            return
        assert out["list"] == list(range(10, 60))
        assert len(out["readd"]) == 50
        assert out["readd"][-1] == 20 and out["readd"].count(20) == 1

    def test_motion_css_disabled_under_reduced_motion(self):
        """Every keyframe class added for #155 (points glow/float, lock stamp, substitution slide, token pulse) has animation and transition off inside @media (prefers-reduced-motion: reduce)."""
        block = _motion_css()
        animated = {sel.strip() for sels, body in _css_blocks(block, r".") if "animation:" in body
                    and not sels.strip().startswith(("from", "to", "@")) for sel in sels.split(",")}
        animated = {s for s in animated if not re.fullmatch(r"[\d%\s]+|from|to", s)}
        assert animated == set(_ANIMATED)
        reduced = "\n".join(_reduced_bodies(block))
        for sel in _ANIMATED:
            bodies = _rule(reduced, sel)
            assert any("animation: none" in b and "transition: none" in b for b in bodies), sel
        for sel in (".roster-pts-float", ".token-float"):
            assert any("display: none" in b for b in _rule(reduced, sel)), sel

    def test_motion_css_placed_before_guided_tour_and_uses_tokens(self):
        """The #155 CSS block sits before the GUIDED TOUR (issue #144) section and uses colour tokens, no hex values."""
        css = _css()
        assert _MOTION_START in _before_tour(css)
        assert css.index(_MOTION_END) < css.index("GUIDED TOUR (issue #144)")
        block = _motion_css()
        for _sel, body in _css_blocks(block, r"."):
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), body
            assert "rgb" not in body, body
        assert "var(--accent)" in block and "var(--ease-out)" in block


# ---------------------------------------------------------------------------
# Story 1: New Points Count Up Since Your Last Visit
# ---------------------------------------------------------------------------

class TestNewPointsCountUp:
    """
    - Seen store `rosterSeenPoints:<user id>:<week id>`: points last shown per
      roster card and the week total.
    - Higher points: count-up from old to new (ease-out,
      clamp(600 + delta x 20, 600, 2000) ms), floating "+delta" in the accent
      colour, brief slot glow.
    - Week total counts up in step and ends at the server's value.
    - No animation on first visit, on a locked week shown for the first time, or
      on decreases.
    - Reduced motion: instant. Click on the roster finishes the count-ups.
    - Final numbers are the server's; counting text is aria-hidden.
    """

    def test_roster_seen_points_stored_per_user_and_week(self):
        """After loadRoster renders, localStorage `rosterSeenPoints:<user id>:<week id>` holds each roster card's shown points and the week total."""
        out = _run("""
  out.seen = stored("rosterSeenPoints:1:5");
  activeUserId = 2;
  ROSTER.week.id = 6;
  await loadRoster(null);
  out.other = stored("rosterSeenPoints:2:6");
""", data=_points_roster())
        if out is None:
            return
        assert out["seen"] == {"cards": {"1": 10.0, "2": 5.0, "3": 3.0}, "total": 18.0}
        assert out["other"] == out["seen"]

    def test_roster_points_increase_counts_up_from_old_value(self):
        """A card whose points rose since the stored value counts up from the old to the new value."""
        out = _run(_PTS_JS + """
  out.start = ptsState(1);
  out.unchanged = ptsState(2);
  frame();
  await advance(360); frame();
  out.mid = parseFloat(ptsState(1).kids[0][0]);
  await advance(400); frame();
  out.end = ptsState(1);
""", data=_points_roster(), storage=_LAST_VISIT)
        if out is None:
            return
        assert out["start"]["kids"][0][0] == "4.0 pts"
        assert out["unchanged"]["kids"] == []
        assert 4.0 < out["mid"] < 10.0
        assert out["end"] == {"text": "10.0 pts", "kids": []}

    def test_roster_points_count_up_duration_clamped(self):
        """The count-up lasts clamp(600 + delta * 20, 600, 2000) ms (small delta 600 ms, large delta capped at 2000 ms)."""
        out = _run(_PTS_JS + """
  out.ms = [0, 0.5, 10, 70, 100].map(_rosterCountUpMs);
  frame();
  await advance(719); frame();
  out.running = ptsState(1).kids.length;
  await advance(1); frame();
  out.finished = ptsState(1);
""", data=_points_roster(), storage=_LAST_VISIT)
        if out is None:
            return
        assert out["ms"] == [600, 610, 800, 2000, 2000]
        # Card 1 rose by 6: 600 + 6 * 20 = 720 ms.
        assert out["running"] == 2
        assert out["finished"] == {"text": "10.0 pts", "kids": []}

    def test_roster_points_increase_shows_float_and_glow(self):
        """A rising card gets a floating "+delta" element (accent colour) and a brief glow class on its slot."""
        out = _run(_PTS_JS + """
  out.during = { glow1: glow(1), floats1: floats(1), glow2: glow(2), floats2: floats(2) };
  frame(); await advance(720); frame();
  out.after = { glow1: glow(1), floats1: floats(1) };
""", data=_points_roster(), storage=_LAST_VISIT)
        if out is None:
            return
        assert out["during"] == {"glow1": True, "floats1": [["+6.0", "true"]], "glow2": False, "floats2": []}
        assert out["after"] == {"glow1": False, "floats1": []}
        assert any("color: var(--accent)" in b for b in _rule(_motion_css(), ".roster-pts-float"))
        assert _rule(_motion_css(), ".card-slot.roster-pts-glow .card-img")

    def test_roster_week_total_counts_up_to_server_value(self):
        """The week total counts up in step with the cards and ends at the server's total."""
        out = _run(_PTS_JS + """
  out.start = total();
  frame(); await advance(360); frame();
  out.mid = parseFloat(total().kids[0][0]);
  out.cardMid = parseFloat(ptsState(1).kids[0][0]);
  await advance(360); frame();
  out.end = total();
""", data=_points_roster(), storage=_LAST_VISIT)
        if out is None:
            return
        # From 18 - 6 (the new points) to the server's 18.0, over card 1's 720 ms.
        assert out["start"]["kids"][0][:2] == ["12.0", "true"]
        assert 12.0 < out["mid"] < 18.0
        assert abs((out["mid"] - 12.0) - (out["cardMid"] - 4.0)) < 0.11
        assert out["end"] == {"text": "18.0", "kids": []}

    def test_roster_points_first_visit_no_animation(self):
        """With nothing stored for the user and week, the points show at once with no count-up, float or glow."""
        out = _run(_PTS_JS + """
  out.s = [1, 2, 3].map(id => [ptsState(id), glow(id), floats(id)]);
  out.total = total();
  out.running = _rosterMotion.finishers.size;
""", data=_points_roster())
        if out is None:
            return
        assert out["s"] == [[{"text": t, "kids": []}, False, []] for t in ("10.0 pts", "5.0 pts", "3.0 pts")]
        assert out["total"]["kids"] == []
        assert out["running"] == 0

    def test_roster_points_decrease_updates_without_animation(self):
        """A card whose points fell (a corrected score) shows the new value at once, with no count-up or float."""
        last = {_SEEN_KEY: {"cards": {"1": 12.0, "2": 5.0, "3": 3.0}, "total": 20.0}}
        out = _run(_PTS_JS + """
  out.card = [ptsState(1), glow(1), floats(1)];
  out.total = total();
  out.seen = stored("rosterSeenPoints:1:5");
""", data=_points_roster(), storage=last)
        if out is None:
            return
        assert out["card"] == [{"text": "10.0 pts", "kids": []}, False, []]
        assert out["total"]["kids"] == []
        assert out["seen"]["cards"]["1"] == 10.0

    def test_roster_points_locked_week_first_view_no_animation(self):
        """A locked week shown for the first time (nothing stored) doesn't count up."""
        out = _run(_PTS_JS + """
  out.card = [ptsState(1), glow(1), floats(1)];
  out.total = total();
  out.seen = stored("rosterSeenPoints:1:5");
""", data=_points_roster(locked=True))
        if out is None:
            return
        assert out["card"] == [{"text": "10.0 pts", "kids": []}, False, []]
        assert out["total"]["kids"] == []
        assert out["seen"]["total"] == 18.0

    def test_roster_points_reduced_motion_instant(self):
        """Under prefers-reduced-motion the new values show immediately with no count-up, float or glow."""
        out = _run(_PTS_JS + """
  out.card = [ptsState(1), glow(1), floats(1)];
  out.total = total();
  out.seen = stored("rosterSeenPoints:1:5");
""", data=_points_roster(), storage=_LAST_VISIT, reduced=True)
        if out is None:
            return
        assert out["card"] == [{"text": "10.0 pts", "kids": []}, False, []]
        assert out["total"]["kids"] == []
        assert out["seen"]["cards"]["1"] == 10.0

    def test_roster_points_click_finishes_count_ups(self):
        """A click anywhere on the roster finishes every running count-up at its final value."""
        out = _run(_PTS_JS + """
  frame(); await advance(100); frame();
  fire(node(2), "click");
  out.card = [ptsState(1), glow(1), floats(1)];
  out.total = total();
  out.opened = opened.slice();
  out.frames = _frames.length;
  // A second click opens the card as usual.
  fire(node(2), "click");
  out.openedAfter = opened.slice();
  // Clicking elsewhere on My Team finishes too.
  localStorage.setItem("rosterSeenPoints:1:5", JSON.stringify({ cards: { 1: 4, 2: 5, 3: 3 }, total: 12 }));
  await loadRoster(null);
  out.again = ptsState(1).kids.length;
  fire(els["tab-team"], "click");
  out.tab = ptsState(1);
""", data=_points_roster(), storage=_LAST_VISIT)
        if out is None:
            return
        assert out["card"] == [{"text": "10.0 pts", "kids": []}, False, []]
        assert out["total"] == {"text": "18.0", "kids": []}
        assert out["opened"] == []
        assert out["frames"] == 0
        assert out["openedAfter"] == [2]
        assert out["again"] == 2
        assert out["tab"] == {"text": "10.0 pts", "kids": []}

    def test_roster_points_final_value_server_and_aria_hidden(self):
        """After the animation each card shows the server's points; the counting text is aria-hidden and the final value is exposed to screen readers."""
        out = _run(_PTS_JS + """
  out.during = ptsState(1);
  out.totalDuring = total();
  frame(); await advance(2000); frame();
  out.after = [1, 2, 3].map(ptsState);
  out.totalAfter = total();
""", data=_points_roster(), storage=_LAST_VISIT)
        if out is None:
            return
        assert out["during"]["kids"] == [["4.0 pts", "true", ""], ["10.0 pts", None, "visually-hidden"]]
        assert out["totalDuring"]["kids"] == [["12.0", "true", ""], ["18.0", None, "visually-hidden"]]
        assert out["after"] == [{"text": t, "kids": []} for t in ("10.0 pts", "5.0 pts", "3.0 pts")]
        assert out["totalAfter"] == {"text": "18.0", "kids": []}


# ---------------------------------------------------------------------------
# Story 3: The Week Lock Has a Moment
# ---------------------------------------------------------------------------

_LOCK_JS = """
const banner = () => els.rosterLockedBanner;
const lockState = () => ({
  stamp: banner().classList.contains("roster-lock-stamp"),
  icon: banner().children.length ? banner().children[0].className : null,
  iconParts: banner().children.length ? banner().children[0].children.map(c => c.className) : [],
  label: banner().children.length ? banner().children[1].textContent : banner().textContent,
  enter: ["rosterActiveGrid", "benchGrid"].map(g => grid(g).classList.contains("roster-lock-enter")),
  display: banner().style.display,
});
"""


class TestWeekLockMoment:
    """
    - First open of a locked week: "Roster locked" banner stamps in (scale 1.15 ->
      1, fade, 300 ms) with a closing lock icon; cards dim to locked style over
      400 ms.
    - Once per user and week: localStorage `rosterLockSeen:<user id>`, last 50
      week ids.
    - Later visits and reduced motion show the locked state directly.
    """

    def test_roster_lock_stamp_plays_on_first_locked_view(self):
        """The first time a user opens a locked week, #rosterLockedBanner gets the stamp class (scale 1.15 -> 1, fade, 300 ms) and a lock icon that closes."""
        out = _run(_LOCK_JS + """
  out.first = lockState();
  await advance(450);
  out.after = lockState();
""", data=_roster(locked=True, starts_in=-3600))
        if out is None:
            return
        assert out["first"]["stamp"] is True
        assert out["first"]["icon"] == "roster-lock-icon"
        assert out["first"]["iconParts"] == ["roster-lock-shackle", "roster-lock-body"]
        assert out["first"]["label"] == "Roster locked — Week 5 snapshot"
        assert out["after"]["stamp"] is False
        css = _motion_css()
        stamp = _keyframes(css, "roster-lock-stamp")
        assert re.search(r"from\s*\{[^}]*scale\(1\.15\)[^}]*opacity: 0", stamp)
        assert re.search(r"to\s*\{[^}]*scale\(1\)[^}]*opacity: 1", stamp)
        assert any("roster-lock-stamp 300ms" in b for b in _rule(css, "#rosterLockedBanner.roster-lock-stamp"))
        assert "translateY(-3px)" in _keyframes(css, "roster-lock-close")
        assert any("roster-lock-close 300ms" in b for b in _rule(css, ".roster-lock-stamp .roster-lock-shackle"))

    def test_roster_lock_cards_dim_transition(self):
        """On that first view the roster cards transition to their locked style over 400 ms."""
        out = _run(_LOCK_JS + """
  out.first = lockState().enter;
  out.editable = node(1).classList.contains("card-slot--editable");
  await advance(450);
  out.after = lockState().enter;
""", data=_roster(locked=True, starts_in=-3600))
        if out is None:
            return
        assert out["first"] == [True, True]
        assert out["editable"] is False
        assert out["after"] == [False, False]
        css = _motion_css()
        assert any("roster-lock-dim 400ms" in b for b in _rule(css, ".roster-lock-enter .card-slot .card-img"))
        locked = _rule(css, "#rosterActiveGrid .card-slot:not(.card-slot--editable) .card-img")
        assert locked and "filter: saturate(0.8) brightness(0.92)" in locked[0]
        assert "filter: saturate(0.8) brightness(0.92)" in _keyframes(css, "roster-lock-dim")

    def test_roster_lock_seen_store_key_and_cap(self):
        """The week id is recorded in localStorage `rosterLockSeen:<user id>`, which keeps only the last 50 week ids."""
        out = _run("out.seen = stored(\"rosterLockSeen:1\");",
                   data=_roster(locked=True, starts_in=-3600),
                   storage={"rosterLockSeen:1": list(range(100, 160))})
        if out is None:
            return
        assert len(out["seen"]) == 50
        assert out["seen"][-1] == 5
        assert out["seen"][0] == 111

    def test_roster_lock_stamp_not_replayed_on_later_visit(self):
        """A later visit to a week already in rosterLockSeen shows the locked banner and cards with no stamp animation."""
        out = _run(_LOCK_JS + """
  out.first = lockState();
  out.seen = stored("rosterLockSeen:1");
  await loadRoster(null);
  out.second = lockState();
""", data=_roster(locked=True, starts_in=-3600), storage=_LOCK_SEEN)
        if out is None:
            return
        for s in ("first", "second"):
            assert out[s]["stamp"] is False
            assert out[s]["enter"] == [False, False]
            assert out[s]["icon"] is None
            assert out[s]["label"] == "Roster locked — Week 5 snapshot"
            assert out[s]["display"] == ""
        assert out["seen"] == [5]

    def test_roster_lock_unlocked_week_no_stamp(self):
        """An unlocked week never plays the stamp and records nothing in rosterLockSeen."""
        out = _run(_LOCK_JS + """
  out.s = lockState();
  out.seen = stored("rosterLockSeen:1");
""")
        if out is None:
            return
        assert out["s"]["stamp"] is False
        assert out["s"]["enter"] == [False, False]
        assert out["s"]["display"] == "none"
        assert out["seen"] is None

    def test_roster_lock_reduced_motion_shows_locked_state(self):
        """Under prefers-reduced-motion the locked state shows directly with no stamp or dim transition."""
        out = _run(_LOCK_JS + """
  out.s = lockState();
  out.seen = stored("rosterLockSeen:1");
  out.editable = node(1).classList.contains("card-slot--editable");
""", data=_roster(locked=True, starts_in=-3600), reduced=True)
        if out is None:
            return
        assert out["s"]["stamp"] is False
        assert out["s"]["enter"] == [False, False]
        assert out["s"]["label"] == "Roster locked — Week 5 snapshot"
        assert out["s"]["display"] == ""
        assert out["editable"] is False
        assert out["seen"] == [5]


# ---------------------------------------------------------------------------
# Story 4: Substitutions Play Out Once
# ---------------------------------------------------------------------------

class TestSubstitutionsPlayOnce:
    """
    - First view of a locked week after substitutions ran (done and at least one
      substitution): each plays in roster order -- subbed-out card slides down and
      fades to the bench, substitute rises into its slot, "Subbed in for {player}"
      fades in; about 700 ms each, 300 ms apart.
    - Once per user and week: localStorage `rosterSubsSeen:<user id>`; a re-run
      that changes the substitutions plays the new result once again.
    - Click finishes at once; reduced motion shows the final state.
    """

    def test_roster_subs_play_in_roster_order(self):
        """On the first view after substitutions ran, each substitution plays in roster (slot) order: subbed-out card to the bench, substitute into its slot."""
        out = _run(_SUBS_JS + """
  out.before = snap();
  await advance(0);
  out.step1 = snap();
  out.moves1 = { out: node(2).transformLog.slice(), in: node(7).transformLog.slice() };
  await advance(1000);
  out.step2 = snap();
  out.moves2 = { out: node(4).transformLog.slice(), in: node(8).transformLog.slice() };
  await advance(1000);
  out.end = snap();
  out.layout = layout();
""", data=_subs_roster(), storage=_LOCK_SEEN)
        if out is None:
            return
        assert out["before"] == _BEFORE
        assert out["step1"] == {"active": [1, 7, 3, 4, "empty:4"], "bench": [2, 8, 9]}
        # Card 2 slides down from slot 1 to the bench, card 7 rises from the bench.
        assert out["moves1"] == {"out": ["translate(200px, -400px)"], "in": ["translate(-200px, 400px)"]}
        assert out["step2"] == _FINAL
        assert out["moves2"] == {"out": ["translate(400px, -400px)"], "in": ["translate(-400px, 400px)"]}
        assert out["end"] == _FINAL
        assert out["layout"]["active"] == [1, 7, 3, 8, None]

    def test_roster_subs_timing(self):
        """Each substitution takes about 700 ms and the next starts 300 ms after the previous one ends."""
        out = _run(_SUBS_JS + """
  await advance(0);
  out.transition = node(7).style.transition;
  await advance(999);
  out.at999 = snap();
  await advance(1);
  out.at1000 = snap();
  out.transition2 = node(8).style.transition;
  await advance(999);
  out.running = [cls(7), cls(8)];
  await advance(1);
  out.done = [cls(2), cls(7), cls(4), cls(8)];
""", data=_subs_roster(), storage=_LOCK_SEEN)
        if out is None:
            return
        assert out["transition"] == "transform 700ms var(--ease-out)"
        assert out["at999"]["active"] == [1, 7, 3, 4, "empty:4"]
        assert out["at1000"] == _FINAL
        assert out["transition2"] == "transform 700ms var(--ease-out)"
        assert out["running"] == [["roster-sub-in"], ["roster-sub-in"]]
        assert out["done"] == [[], [], [], []]
        js = _read(ROSTER_JS)
        assert "const ROSTER_SUB_MS = 700;" in js and "const ROSTER_SUB_GAP_MS = 300;" in js

    def test_roster_subs_label_fades_in(self):
        """The "Subbed in for {player}" label fades in as the substitute arrives."""
        out = _run(_SUBS_JS + """
  out.note = node(7).querySelector(".card-slot-note").textContent;
  out.before = [cls(7), cls(8)];
  await advance(0);
  out.step1 = [cls(7), cls(8), cls(2)];
""", data=_subs_roster(), storage=_LOCK_SEEN)
        if out is None:
            return
        assert out["note"] == "Subbed in for P102"
        assert out["before"] == [["roster-sub-pending"], ["roster-sub-pending"]]
        assert out["step1"] == [["roster-sub-in"], ["roster-sub-pending"], ["roster-sub-out"]]
        css = _motion_css()
        assert any("opacity: 0" in b for b in _rule(css, ".card-slot.roster-sub-pending .card-slot-note"))
        assert any("roster-sub-label 400ms" in b for b in _rule(css, ".card-slot.roster-sub-in .card-slot-note"))
        assert re.search(r"from\s*\{[^}]*opacity: 0", _keyframes(css, "roster-sub-label"))

    def test_roster_subs_no_playback_without_substitutions(self):
        """No playback when substitutions haven't run (substitutions_done false) or ran with zero substitutions."""
        steps = _SUBS_JS + """
  out.s = snap();
  out.pending = [cls(7), cls(8)];
  out.seen = stored("rosterSubsSeen:1");
  out.running = _rosterMotion.finishers.size;
"""
        for data, final in ((_subs_roster(done=False), _FINAL),
                            (_subs_roster(subs=False), {"active": [1, 7, 3, 8, "empty:4"], "bench": [2, 4, 9]})):
            out = _run(steps, data=data, storage=_LOCK_SEEN)
            if out is None:
                return
            assert out["s"] == final
            assert out["pending"] == [[], []]
            assert out["seen"] is None
            assert out["running"] == 0

    def test_roster_subs_seen_once_per_user_and_week(self):
        """After playing, the week is recorded in localStorage `rosterSubsSeen:<user id>` and a later view doesn't replay."""
        out = _run(_SUBS_JS + """
  out.seen = stored("rosterSubsSeen:1");
  await advance(3000);
  await loadRoster(null);
  out.second = snap();
  out.pending = [cls(7), cls(8)];
  out.seenAfter = stored("rosterSubsSeen:1");
""", data=_subs_roster(), storage=_LOCK_SEEN)
        if out is None:
            return
        assert out["seen"] == ["5:2>7,4>8"]
        assert out["second"] == _FINAL
        assert out["pending"] == [[], []]
        assert out["seenAfter"] == ["5:2>7,4>8"]

    def test_roster_subs_changed_result_plays_again(self):
        """When a re-run changes the substitutions for a seen week (#193), the new result plays once again."""
        storage = dict(_LOCK_SEEN, **{"rosterSubsSeen:1": ["5:2>7"]})
        out = _run(_SUBS_JS + """
  out.before = snap();
  out.seen = stored("rosterSubsSeen:1");
""", data=_subs_roster(), storage=storage)
        if out is None:
            return
        assert out["before"] == _BEFORE
        assert out["seen"] == ["5:2>7", "5:2>7,4>8"]

    def test_roster_subs_click_finishes(self):
        """A click during playback finishes every substitution at once in its final layout."""
        out = _run(_SUBS_JS + """
  await advance(0);
  fire(node(1), "click");
  out.s = snap();
  out.cls = [cls(2), cls(7), cls(4), cls(8)];
  out.style = [node(7).style.transform, node(7).style.transition];
  out.opened = opened.slice();
  await advance(3000);
  out.later = snap();
""", data=_subs_roster(), storage=_LOCK_SEEN)
        if out is None:
            return
        assert out["s"] == _FINAL
        assert out["cls"] == [[], [], [], []]
        assert out["style"] == ["", "none"]
        assert out["opened"] == []
        assert out["later"] == _FINAL

    def test_roster_subs_reduced_motion_final_state(self):
        """Under prefers-reduced-motion the final substituted layout shows directly with no slide."""
        out = _run(_SUBS_JS + """
  out.s = snap();
  out.cls = [cls(7), cls(8)];
  out.transforms = node(7).transformLog.length;
  out.seen = stored("rosterSubsSeen:1");
  await advance(3000);
  out.later = snap();
""", data=_subs_roster(), storage=_LOCK_SEEN, reduced=True)
        if out is None:
            return
        assert out["s"] == _FINAL
        assert out["cls"] == [[], []]
        assert out["transforms"] == 0
        assert out["seen"] == ["5:2>7,4>8"]
        assert out["later"] == _FINAL


# ---------------------------------------------------------------------------
# Story 5: Token Gains Are Noticed
# ---------------------------------------------------------------------------

class TestTokenGains:
    """
    - updateTokenDisplay with a balance higher than shown: header number counts
      up over 600 ms, chip pulses once with a floating "+N".
    - Spending updates instantly.
    - First display after page load animates only if the balance rose since
      localStorage `tokensSeen:<user id>`.
    - Reduced motion: instant.
    """

    def test_update_token_display_rise_counts_up_and_pulses(self):
        """A higher balance counts #headerTokenNum up over 600 ms to the new balance, pulses the chip once and shows a floating "+N"."""
        out = _run_tokens("""
  updateTokenDisplay(2);
  out.first = state();
  updateTokenDisplay(5);
  out.rise = state();
  frame(); advance(100); frame();
  out.mid = Number(num.textContent);
  advance(499); frame();
  out.at599 = state().pulse;
  advance(1); frame();
  out.at600 = state();
  advance(300);
  out.after = state();
""")
        if out is None:
            return
        assert out["first"] == {"text": "2", "pulse": False, "floats": [], "frames": 0, "display": "flex"}
        assert out["rise"]["text"] == "2" and out["rise"]["pulse"] is True
        assert out["rise"]["floats"] == [["+3", "true"]]
        assert 2 < out["mid"] < 5
        assert out["at599"] is True
        assert out["at600"]["text"] == "5" and out["at600"]["frames"] == 0
        assert out["after"] == {"text": "5", "pulse": False, "floats": [], "frames": 0, "display": "flex"}
        assert "const TOKEN_COUNT_UP_MS = 600;" in _read(GLOBALS_JS)
        assert any("token-chip-pulse 600ms" in b for b in _rule(_motion_css(), ".header-tokens.token-chip-pulse"))

    def test_update_token_display_decrease_is_instant(self):
        """A lower balance (a draw) shows at once with no count-up, pulse or float."""
        out = _run_tokens("""
  updateTokenDisplay(5);
  updateTokenDisplay(2);
  out.s = state();
  out.balance = _tokenBalance;
""", storage={"tokensSeen:1": 5})
        if out is None:
            return
        assert out["s"] == {"text": "2", "pulse": False, "floats": [], "frames": 0, "display": "flex"}
        assert out["balance"] == 2

    def test_update_token_display_stores_tokens_seen_per_user(self):
        """Each displayed balance is stored in localStorage `tokensSeen:<user id>`."""
        out = _run_tokens("""
  updateTokenDisplay(4);
  out.one = stored("tokensSeen:1");
  updateTokenDisplay(null);
  activeUserId = 2;
  updateTokenDisplay(7);
  out.two = stored("tokensSeen:2");
  out.oneAfter = stored("tokensSeen:1");
  out.s = state();
""")
        if out is None:
            return
        assert out["one"] == 4
        assert out["two"] == 7
        assert out["oneAfter"] == 4
        # User 2 had nothing stored: no animation on their first display.
        assert out["s"]["pulse"] is False and out["s"]["text"] == "7"

    def test_update_token_display_first_load_animates_if_risen_since_stored(self):
        """The first display after page load counts up when the balance is higher than tokensSeen for this user."""
        out = _run_tokens("""
  updateTokenDisplay(6);
  out.s = state();
  frame(); advance(600); frame();
  out.end = num.textContent;
""", storage={"tokensSeen:1": 3})
        if out is None:
            return
        assert out["s"]["text"] == "3"
        assert out["s"]["pulse"] is True
        assert out["s"]["floats"] == [["+3", "true"]]
        assert out["end"] == "6"

    def test_update_token_display_first_load_without_rise_no_animation(self):
        """The first display after page load doesn't animate when nothing is stored or the balance hasn't risen."""
        steps = """
  updateTokenDisplay(6);
  out.s = state();
"""
        for storage in ({}, {"tokensSeen:1": 6}, {"tokensSeen:1": 8}):
            out = _run_tokens(steps, storage=storage)
            if out is None:
                return
            assert out["s"] == {"text": "6", "pulse": False, "floats": [], "frames": 0, "display": "flex"}, storage

    def test_update_token_display_null_hides_without_animation(self):
        """updateTokenDisplay(null) (logout) hides the chip with no animation and doesn't overwrite tokensSeen."""
        out = _run_tokens("""
  updateTokenDisplay(2);
  updateTokenDisplay(5);
  updateTokenDisplay(null);
  out.s = state();
  out.seen = stored("tokensSeen:1");
  out.shown = _tokenMotion.shown;
""")
        if out is None:
            return
        assert out["s"]["display"] == "none"
        assert out["s"]["pulse"] is False and out["s"]["floats"] == [] and out["s"]["frames"] == 0
        assert out["seen"] == 5
        assert out["shown"] is None

    def test_update_token_display_reduced_motion_instant(self):
        """Under prefers-reduced-motion a rise shows the new balance immediately with no count-up or pulse."""
        out = _run_tokens("""
  updateTokenDisplay(6);
  out.s = state();
  out.seen = stored("tokensSeen:1");
""", storage={"tokensSeen:1": 3}, reduced=True)
        if out is None:
            return
        assert out["s"] == {"text": "6", "pulse": False, "floats": [], "frames": 0, "display": "flex"}
        assert out["seen"] == 6
