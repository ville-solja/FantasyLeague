"""
Tests for plan-issue-202-ui-feedback-polish.md (resolves GitHub issue #202).

The design system gains a "States and emphasis" section (`.claude/skills/README.md`)
backed by semantic tokens in `colors_and_type.css` (both copies) and a "Shared states"
section in `frontend/style.css` (before GUIDED TOUR). Surfaces then use the shared
classes: selected + hover inverts on all seven selected controls, role/status badges
become one family (`.role-badge`, `.status-badge`, helpers in app-globals.js), the
signed-in user's ranking rows get `.row-self`, the Weekly Report winner/MVP lose their
rings and use `--mark-winner` / `--mark-mvp`, images are unselectable, My roster game
rows become a fixed-column grid, and `_weeklySummaryCache` lives for the page session.

  Story 1: The Design System Defines States and Emphasis   (TestDesignSystemStatesAndEmphasis)
  Story 2: Selected Controls Respond to Hover Everywhere    (TestSelectedControlsHover)
  Story 3: Badges Look Like One Family and Explain Themselves (TestBadgeFamily)
  Story 4: Your Own Row Stands Out Wherever You Appear      (TestOwnRow)
  Story 5: Weekly Report Emphasis Follows the Rules         (TestWeeklyReportEmphasis)
  Story 6: Reopening the Weekly Report Doesn't Flash        (TestWeeklyReportCache)

Approach notes for the implementer:

- Frontend + docs only; no `db` fixture is needed. Static checks reuse the helpers in
  test_issue_151_weekly_report_aesthetics.py (`_read`, `_css_blocks`, `_css_rule`,
  `_fn_body`) and `_rule` / `_before_tour` from test_issue_186_my_team_save_roster.py.
  Import only underscore names so pytest does not collect those modules twice.
  `_css_blocks` keeps the newline before a selector: match by exact selector with
  `_rule(css, selector)`, not a `^...$` regex (lessons-learned 2026-10-14).
- The seven selected controls as they exist today (style.css):
    `.tab.active`, `.weekly-summary-tab-btn.active`, `.howtoplay-tab-btn.active`,
    `.admin-tab-btn.active`, `.schedule-div-chip.active`,
    `.schedule-week-chip.selected` (NOT `.active`), `.schedule-hide-toggle[aria-pressed="true"]`.
- Node harness tests: skip with `pytest.skip` when `node` is missing (see `_node()` in
  test_issue_159 / test_issue_186). For the badge/self-row helpers, extract
  `_escHtml`, `adminBadgeHtml`, `tagBadgeHtml`, `statusBadgeHtml` from app-globals.js
  and `_lbStandingsRow` from app-leaderboard.js with `_fn_body`, set `activeUserId`,
  call them and return the markup as JSON (parse it with `html.parser`, never a regex
  over tags; lessons-learned security entry). For the cache, load app-weekly-summary.js
  with a fake DOM (getElementById map of `{innerHTML, classList, children, ...}`), a fake
  `fetch` that records URLs and returns queued JSON, a controllable `Date.now`, and stubs
  for `renderIfChanged`, `withBusy`, `_stopRecap`-dependent globals. `logout` /
  `login` / `_clearLocalAuthState` live in app-auth.js; either load the relevant
  functions too or assert the clear hook they call.
- Older tests that pin the behaviour this plan changes must be updated in the same
  change (grep before editing):
    test_issue_159::test_close_weekly_summary_clears_cache (`_weeklySummaryCache.clear();`
      in closeWeeklySummary), and the cache-branch assertions in the
      selectWeeklySummaryTab test above it;
    test_issue_151::test_owned_tile_uses_filled_accent_ghost
      (`outline: 2px solid var(--accent)` on `.weekly-summary-mvp`);
    test_issue_169 (around line 611-639) pins `class="admin-badge"` in
      adminBadgeHtml, the `.admin-badge` CSS block and the exact
      `_escHtml(r.username)}${adminBadgeHtml(r.is_admin)}` sequence;
    test_issue_144_guided_tour checks every rule after "GUIDED TOUR".
- Readability rule (ui-design.md core rules, test_weekly_report_readability.py): Big
  Shoulders only at `--fs-sm` and up, so `.role-badge` / `.status-badge` use the display
  font at `--fs-sm` (resolved in review; the design-system section says so).

Manual-only (see the plan's Verification section): hover/focus visuals in a browser,
drag-select behaviour, column alignment by eye, no flicker on reopen, 375 px width.

Run with: cd backend && python3 -m pytest tests/test_issue_202_ui_feedback_polish.py -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _css_rule, _fn_body, _read
from tests.test_issue_186_my_team_save_roster import _before_tour, _rule

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_FRONTEND = os.path.join(_ROOT, "frontend")


def _f(name):
    return _read(os.path.join(_FRONTEND, name))


def _css():
    return _f("style.css")


def _tokens():
    return _f("colors_and_type.css")


def _readme():
    return _read(os.path.join(_ROOT, ".claude", "skills", "README.md"))


def _states_section():
    md = _readme()
    start = md.index("### States and emphasis")
    return md[start:md.index("\n### ", start + 1)]


def _section_bounds(css):
    """(start, end) of the "Shared states" section, from its header comment to the
    GUIDED TOUR header comment (both cut at the `/*`, so comments stay whole)."""
    start = css.rindex("/*", 0, css.index("SHARED STATES (issue #202)"))
    end = css.rindex("/*", 0, css.index("GUIDED TOUR (issue #144)"))
    return start, end


def _shared_states():
    css = _css()
    start, end = _section_bounds(css)
    return css[start:end]


def _token(name):
    m = re.search(rf"{re.escape(name)}:\s*([^;]+);", _tokens())
    assert m, name
    return m.group(1).strip()


def _strip_js_comments(js):
    return re.sub(r"(?m)^\s*//.*$", "", js)


_HEX = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b")

# The seven selected controls (style.css), as they exist in the code.
_SELECTED = [
    ".tab.active",
    ".weekly-summary-tab-btn.active",
    ".howtoplay-tab-btn.active",
    ".admin-tab-btn.active",
    ".schedule-div-chip.active",
    ".schedule-week-chip.selected",
    '.schedule-hide-toggle[aria-pressed="true"]',
]
_UNSELECTED = [s.split(".active")[0].split(".selected")[0].split("[aria-pressed")[0] for s in _SELECTED]

_STATE_TOKENS = ["--state-selected-hover-bg", "--state-selected-hover-fg", "--badge-admin",
                 "--badge-winner", "--badge-caster", "--badge-tag", "--badge-status",
                 "--row-self-bg", "--mark-winner", "--mark-mvp"]


def _selected_hover_rule():
    """(selectors, body) of the shared rule that lists `.tab.active:hover`."""
    for sel, body in _css_blocks(_shared_states(), re.escape(".tab.active:hover")):
        return [x.strip() for x in sel.split(",")], body
    raise AssertionError("no shared selected + hover rule")


def _node():
    return shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)


def _run_node(script):
    node = _node()
    if not node:
        pytest.skip("node not available")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def _globals_src(*names):
    js = _f("app-globals.js")
    parts = [re.search(r"^const _lastHtml = new WeakMap\(\);$", js, re.M).group(0),
             js[js.index("const _TAG_BADGE_VARIANTS"):js.index("function _ownValue")]]
    for n in names:
        body = _fn_body(js, n)
        start = js.index(f"function {n}(")
        parts.append(("async " if js[start - 6:start] == "async " else "") + body + "\n}\n")
    return "\n".join(parts)


_BADGE_NAMES = ("_escHtml", "_ownValue", "adminBadgeHtml", "tagBadgeHtml", "statusBadgeHtml")


def _badges(steps, active_user="null"):
    lb = _f("app-leaderboard.js")
    script = (_globals_src(*_BADGE_NAMES)
              + f"\nvar activeUserId = {active_user};\n"
              + _fn_body(lb, "_lbIsSelf") + "\n}\n" + _fn_body(lb, "_lbStandingsRow") + "\n}\n"
              + "var out = {};\n" + steps + "\nconsole.log(JSON.stringify(out));")
    return _run_node(script)


class _Elements(HTMLParser):
    """Every start tag as (tag, attrs dict, text directly inside it)."""

    def __init__(self, html):
        super().__init__()
        self.items, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        item = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self.items.append(item)
        if tag not in ("img", "br", "input"):
            self._stack.append(item)

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._stack:
            self._stack[-1]["text"] += data


def _classes(item):
    return (item["attrs"].get("class") or "").split()


def _rows(html):
    return [i for i in _Elements(html).items if i["tag"] == "tr"]


_ROW = {"id": 7, "username": "alice", "is_admin": False, "week_points": 12.34,
        "tags": [{"key": "caster", "label": "Caster"}],
        "cards": [{"card_type": "rare", "player_name": "P", "points": 3.0}]}


# ---------------------------------------------------------------------------
# Weekly Report harness (app-weekly-summary.js under Node with a fake DOM)
# ---------------------------------------------------------------------------

_WS_HARNESS = r"""
var NOW = 1700000000000;
Date.now = function () { return NOW; };
var els = {};
function makeEl(id) {
  var html = "";
  var classes = new Set();
  var e = {
    id: id, writes: 0, textContent: "", children: [], dataset: {}, style: {}, attrs: {},
    scrollTop: 0, everLoading: false, disabled: false,
    get innerHTML() { return html; },
    set innerHTML(v) { this.writes++; html = String(v); if (html === "") this.children = []; },
    classList: {
      add: function (c) { classes.add(c); if (c === "is-loading") e.everLoading = true; },
      remove: function (c) { classes.delete(c); },
      contains: function (c) { return classes.has(c); },
      toggle: function (c, on) {
        if (on === undefined) on = !classes.has(c);
        if (on) this.add(c); else this.remove(c);
        return on;
      },
    },
    setAttribute: function (k, v) { this.attrs[k] = String(v); },
    removeAttribute: function (k) { delete this.attrs[k]; },
    appendChild: function (c) { this.children.push(c); return c; },
    addEventListener: function () {},
  };
  return e;
}
var document = {
  getElementById: function (id) { return els[id] || (els[id] = makeEl(id)); },
  createElement: function () { return makeEl(null); },
  querySelectorAll: function () { return []; },
};
var localStorage = { _s: {}, getItem: function (k) { return this._s[k] ?? null; },
                     setItem: function (k, v) { this._s[k] = String(v); } };
var API = "";
var activeUserId = 1;
var activeMustChangePassword = false;
function _prefersReducedMotion() { return true; }
function showCard() {}
function week(id, revealed, teamName) {
  return {week_id: id, revealed: revealed, roster: {cards: []}, substitutions_pending: false,
          series: teamName ? [{matches: [{match_id: 1, radiant_team_id: 1, dire_team_id: 2,
            radiant_team: {id: 1, name: teamName}, dire_team: {id: 2, name: "Other"}}]}] : []};
}
var LIST = {weeks: [{week_id: 1, label: "Week 1", revealed: false}], has_unseen: false, show_prompt: false};
var WEEK = {};
var FAIL = null;  // null | "throw" | "status"
var HOLD = false;  // true: week fetches wait until release() is called
var HELD = [];
function release() { var h = HELD; HELD = []; h.forEach(function (f) { f(); }); }
var calls = [];
function fetch(url, opts) {
  var method = (opts && opts.method) || "GET";
  calls.push(method + " " + url);
  if (HOLD && /^\/weekly-summary\/\d+$/.test(url)) {
    var held = WEEK[+url.split("/").pop()];
    return new Promise(function (resolve) {
      HELD.push(function () {
        resolve({ok: true, status: 200, json: function () { return Promise.resolve(JSON.parse(JSON.stringify(held))); }});
      });
    });
  }
  if (FAIL === "throw") return Promise.reject(new Error("offline"));
  var ok = FAIL !== "status";
  var body;
  if (!ok) body = {detail: "Server error"};
  else if (url === "/weekly-summary") body = LIST;
  else if (/^\/weekly-summary\/\d+$/.test(url)) {
    var id = +url.split("/").pop();
    body = WEEK[id] || week(id, false);
  } else body = {ok: true};
  return Promise.resolve({ok: ok, status: ok ? 200 : 500,
                          json: function () { return Promise.resolve(JSON.parse(JSON.stringify(body))); }});
}
__GLOBALS__
__WS__
var renderCalls = [];
var _origRender = renderWeeklySummaryContent;
renderWeeklySummaryContent = function (d, o) { renderCalls.push(o || {}); return _origRender(d, o); };
var ricCalls = 0;
var _origRic = renderIfChanged;
renderIfChanged = function (el, html) { ricCalls++; return _origRic(el, html); };
function el(id) { return document.getElementById(id); }
function tick() { return new Promise(function (r) { setTimeout(r, 0); }); }
function count(c) { return calls.filter(function (x) { return x === c; }).length; }
function loadingEver() { return el("weeklySummaryRoster").everLoading || el("weeklySummaryContent").everLoading; }
function resetLoading() { el("weeklySummaryRoster").everLoading = false; el("weeklySummaryContent").everLoading = false; }
(async function () { var out = {}; __STEPS__ console.log(JSON.stringify(out)); })()
  .catch(function (e) { console.error(e && e.stack || e); process.exit(1); });
"""


def _ws(steps):
    script = (_WS_HARNESS
              .replace("__GLOBALS__", _globals_src("renderIfChanged", "forgetRendered", "_escHtml", "_safeUrl",
                                                   "playerLink", "teamLink", "withBusy"))
              .replace("__WS__", _f("app-weekly-summary.js"))
              .replace("__STEPS__", steps))
    return _run_node(script)


# ---------------------------------------------------------------------------
# Story 1: The Design System Defines States and Emphasis
# ---------------------------------------------------------------------------

class TestDesignSystemStatesAndEmphasis:

    def test_design_readme_has_states_and_emphasis_section_under_visual_foundations(self):
        """`.claude/skills/README.md` has a "States and emphasis" heading inside VISUAL FOUNDATIONS (after `## VISUAL FOUNDATIONS`, before `## ICONOGRAPHY`)."""
        md = _readme()
        heading = md.index("### States and emphasis")
        assert md.index("## VISUAL FOUNDATIONS") < heading < md.index("## ICONOGRAPHY")

    def test_design_readme_states_section_covers_every_rule(self):
        """The section covers Selected, Selected + hover / focus-visible, Role badges, Status badges, Self, Emphasis inside data, Selection and Data rows, each naming its tokens and shared class (`.role-badge`, `.status-badge`, `.row-self`, `--row-self-bg`, `--mark-winner`, `--mark-mvp`, `user-select: none`, `tabular-nums`)."""
        sec = _states_section()
        for rule in ("Selected", "Selected + hover / focus-visible", "Role badges", "Status badges",
                     "Self", "Emphasis inside data", "Selection", "Data rows"):
            assert re.search(rf"^- \*\*{re.escape(rule)}(:\*\*| \(|\*\*)", sec, re.M), rule
        for name in [".role-badge", ".status-badge", ".row-self", "user-select: none", "tabular-nums",
                     "--fs-sm"] + _STATE_TOKENS:
            assert name in sec, name

    def test_design_readme_states_section_keeps_existing_brand_rules(self):
        """The section states no left bars on the self row, no rarity colours for roles, and no rings/outlines around floating elements."""
        sec = _states_section().lower()
        assert "no left bar" in sec
        assert "rarity colours are never used for roles" in sec
        assert "no rings or outlines around floating elements" in sec

    def test_state_tokens_defined_in_both_css_copies(self):
        """`--state-selected-hover-bg`, `--state-selected-hover-fg`, `--badge-admin`, `--badge-winner`, `--badge-caster`, `--badge-tag`, `--badge-status`, `--row-self-bg`, `--mark-winner`, `--mark-mvp` are defined in both `frontend/colors_and_type.css` and `design/colors_and_type.css`, and the two files stay identical."""
        frontend = _tokens()
        design = _read(os.path.join(_ROOT, "design", "colors_and_type.css"))
        for name in _STATE_TOKENS:
            assert re.search(rf"^\s*{re.escape(name)}:", frontend, re.M), name
        assert design == frontend

    def test_role_badge_tokens_resolve_to_flame_amber_or_neutral(self):
        """`--badge-admin` -> `--accent`, `--badge-winner` -> `--k-amber-500`, `--badge-caster` -> `--fg`, `--badge-tag` -> `--fg-muted`, `--badge-status` neutral; none of the role/status/mark tokens reference a rarity token (`--k-rare*`, `--k-epic*`, `--rarity-*`, blue/purple)."""
        assert _token("--badge-admin") == "var(--accent)"
        assert _token("--badge-winner") == "var(--k-amber-500)"
        assert _token("--badge-caster") == "var(--fg)"
        assert _token("--badge-tag") == "var(--fg-muted)"
        assert _token("--badge-status") in ("var(--fg-muted)", "var(--fg)")
        for name in _STATE_TOKENS:
            value = _token(name)
            assert not re.search(r"rarity|rare|epic|legendary|info|twitch|blue|purple", value), (name, value)
            assert not _HEX.search(value), (name, value)

    def test_ui_design_core_rules_point_to_states_and_emphasis(self):
        """`.claude/commands/ui-design.md` "Core brand rules" list gains one line that names "States and emphasis"."""
        md = _read(os.path.join(_ROOT, ".claude", "commands", "ui-design.md"))
        rules = md[md.index("## Core brand rules"):md.index("## Output modes")]
        lines = [l for l in rules.splitlines() if l.startswith("- ") and "States and emphasis" in l]
        assert len(lines) == 1

    def test_style_css_shared_states_section_before_guided_tour(self):
        """`frontend/style.css` has a "Shared states" section header, placed before "GUIDED TOUR (issue #144)", holding the selected + hover selector list, `.role-badge`, `.status-badge`, `.row-self` and the mark classes."""
        css = _css()
        assert "SHARED STATES (issue #202)" in _before_tour(css)
        section = _shared_states()
        selectors = [x.strip() for sel, _ in _css_blocks(section, r".") for x in sel.split(",")]
        for sel in (".tab.active:hover", ".role-badge", ".status-badge", ".row-self", ".mark-winner", ".mark-mvp"):
            assert sel in selectors, sel
        assert "var(--mark-winner)" in section and "var(--mark-mvp)" in section

    def test_ui_descriptions_point_to_design_rules(self):
        """`markdown/ui_description/` leaderboards, weekly-report, profile, schedule and admin specs reference "States and emphasis" instead of describing one-off badge/highlight styles."""
        for name in ("leaderboards", "weekly-report", "profile", "schedule", "admin"):
            md = _read(os.path.join(_ROOT, "markdown", "ui_description", f"{name}.md"))
            assert "States and emphasis" in md, name
            assert "#f0b429" not in md and "gold" not in md.lower(), name

    def test_shared_states_section_uses_no_hex_colours(self):
        """Failure path: no rule in the "Shared states" section contains a hex colour (`#abc` / `#aabbcc`); colours come only from tokens."""
        bodies = [body for _, body in _css_blocks(_shared_states(), r".")]
        assert bodies
        for body in bodies:
            assert not _HEX.search(body), body
            assert "rgba(" not in body


# ---------------------------------------------------------------------------
# Story 2: Selected Controls Respond to Hover Everywhere
# ---------------------------------------------------------------------------

class TestSelectedControlsHover:

    def test_selected_hover_selector_list_covers_all_seven_controls(self):
        """One shared rule's selector list contains `:hover` for `.tab.active`, `.weekly-summary-tab-btn.active`, `.howtoplay-tab-btn.active`, `.admin-tab-btn.active`, `.schedule-div-chip.active`, `.schedule-week-chip.selected` and `.schedule-hide-toggle[aria-pressed="true"]`."""
        selectors, _ = _selected_hover_rule()
        for sel in _SELECTED:
            assert f"{sel}:hover" in selectors, sel

    def test_selected_hover_inverts_with_state_tokens(self):
        """The shared selected + hover rule sets `background: var(--state-selected-hover-bg)` and `color: var(--state-selected-hover-fg)` (accent fill, `--accent-fg` text)."""
        _, body = _selected_hover_rule()
        assert "background: var(--state-selected-hover-bg);" in body
        assert "color: var(--state-selected-hover-fg);" in body
        assert _token("--state-selected-hover-bg") == "var(--accent)"
        assert _token("--state-selected-hover-fg") == "var(--accent-fg)"

    def test_selected_focus_visible_shares_inverted_style_and_keeps_outline(self):
        """The same shared rule lists `:focus-visible` for all seven selected controls and does not set `outline: none` / `outline: 0`."""
        selectors, body = _selected_hover_rule()
        for sel in _SELECTED:
            assert f"{sel}:focus-visible" in selectors, sel
        assert not re.search(r"outline:\s*(none|0)\b", body)
        for sel in _SELECTED:
            outlines = [b for b in _rule(_shared_states(), f"{sel}:focus-visible") if "outline" in b]
            assert outlines and all(not re.search(r"outline:\s*(none|0)\b", b) for b in outlines), sel
            assert any("solid var(--accent)" in b for b in outlines), sel

    def test_selected_hover_rule_wins_over_surface_rules(self):
        """No later surface rule for these seven controls redefines `background`/`color` on `.active:hover` / `.selected:hover` / `[aria-pressed="true"]:hover`, so the shared inverted style is what applies."""
        css = _css()
        start, end = _section_bounds(css)
        outside = css[:start] + css[end:]
        for sel in _SELECTED:
            assert not _rule(outside, f"{sel}:hover"), sel
        after = css[end:]
        for sel in _SELECTED:
            assert not _rule(after, f"{sel}:focus-visible"), sel

    def test_unselected_hover_rules_unchanged(self):
        """Failure path: plain `:hover` (unselected) rules for the seven controls still go muted -> `--fg` and do not use the inverted state tokens."""
        css = _css()
        for base in _UNSELECTED:
            bodies = _rule(css, f"{base}:hover")
            assert bodies, base
            assert any("color: var(--fg)" in b for b in bodies), base
            assert all("--state-selected-hover" not in b for b in bodies), base


# ---------------------------------------------------------------------------
# Story 3: Badges Look Like One Family and Explain Themselves
# ---------------------------------------------------------------------------

class TestBadgeFamily:

    def test_role_badge_css_shape(self):
        """`.role-badge`: bold, uppercase, `--tr-wider`, transparent background, `1px`/`--bw-hair` border in `currentColor`, `border-radius: var(--r-xs)`; font family/size obey the readability rule (Big Shoulders only at `--fs-sm`+)."""
        bodies = _rule(_shared_states(), ".role-badge")
        shape = next(b for b in bodies if "border-radius" in b)
        for decl in ("font-weight: var(--w-bold)", "text-transform: uppercase",
                     "letter-spacing: var(--tr-wider)", "background: transparent",
                     "border: var(--bw-hair) solid currentColor", "border-radius: var(--r-xs)",
                     "font-family: var(--font-display)", "font-size: var(--fs-sm)"):
            assert decl in shape, decl
        assert "border-left" not in shape

    def test_role_badge_variants_use_badge_tokens(self):
        """Role badge variants (admin, winner, caster, tag) set `color` from `--badge-admin`, `--badge-winner`, `--badge-caster`, `--badge-tag`; `.status-badge` uses `--badge-status` text with a `--border` outline in the same shape."""
        section = _shared_states()
        for variant, token in (("admin", "--badge-admin"), ("winner", "--badge-winner"),
                               ("caster", "--badge-caster"), ("tag", "--badge-tag")):
            assert any(f"color: var({token})" in b for b in _rule(section, f".role-badge-{variant}")), variant
        status = _rule(section, ".status-badge")
        assert any("color: var(--badge-status)" in b and "border-color: var(--border)" in b for b in status)
        assert any("border-radius: var(--r-xs)" in b for b in status)  # same shape rule as .role-badge

    def test_admin_badge_html_uses_role_badge_with_title(self):
        """Node harness: `adminBadgeHtml(true)` returns a `.role-badge` (admin variant) span with text ADMIN and `title="Kana Cards admin"`; `adminBadgeHtml(false)` and `adminBadgeHtml("true")` return ""."""
        out = _badges('out.t = adminBadgeHtml(true); out.f = adminBadgeHtml(false); out.s = adminBadgeHtml("true");')
        span = _Elements(out["t"]).items[0]
        assert span["tag"] == "span" and _classes(span) == ["role-badge", "role-badge-admin"]
        assert span["text"] == "ADMIN" and span["attrs"]["title"] == "Kana Cards admin"
        assert out["f"] == "" and out["s"] == ""

    def test_tag_badge_html_reason_titles(self):
        """Node harness: `tagBadgeHtml({key:"caster"})` has title "Verified caster: an approved tournament streamer" and the caster variant; `season_winner` has "Won a previous season" and the winner variant; any other key uses the tag variant with its label as title."""
        out = _badges('out.c = tagBadgeHtml({key: "caster", label: "Caster"});'
                      'out.w = tagBadgeHtml({key: "season_winner", label: "Season Winner"});'
                      'out.o = tagBadgeHtml({key: "veteran", label: "Veteran"});'
                      'out.p = tagBadgeHtml({key: "constructor", label: "Proto"});')
        c, w, o, p = (_Elements(out[k]).items[0] for k in ("c", "w", "o", "p"))
        assert "role-badge-caster" in _classes(c)
        assert c["attrs"]["title"] == "Verified caster: an approved tournament streamer"
        assert "role-badge-winner" in _classes(w) and w["attrs"]["title"] == "Won a previous season"
        assert "role-badge-tag" in _classes(o) and o["attrs"]["title"] == "Veteran" and o["text"] == "Veteran"
        # Keys are looked up as own properties only (no Object.prototype members).
        assert _classes(p) == ["role-badge", "role-badge-tag"] and p["attrs"]["title"] == "Proto"

    def test_role_badge_helpers_used_on_every_surface(self):
        """`_lbStandingsRow` and `loadPastSeasonStandings` (app-leaderboard.js), app-profile.js (`.profile-tags`), and `_renderUsers` (app-admin-users.js) render tags via `tagBadgeHtml` and ADMIN via `adminBadgeHtml`; User Management's inline ADMIN `<span class="badge" ...>` is gone."""
        lb = _f("app-leaderboard.js")
        row = _fn_body(lb, "_lbStandingsRow")
        assert "tagBadgeHtml(t)" in row and "adminBadgeHtml(r.is_admin)" in row
        assert "adminBadgeHtml(r.is_admin)" in _fn_body(lb, "loadPastSeasonStandings")
        profile = _fn_body(_f("app-profile.js"), "loadProfile")
        assert "tagBadgeHtml(t)" in profile and "adminBadgeHtml(data.is_admin)" in profile
        users_js = _f("app-admin-users.js")
        users = _fn_body(users_js, "_renderUsers")
        assert "tagBadgeHtml(t" in users and "adminBadgeHtml(u.is_admin)" in users
        assert ">ADMIN</span>" not in users_js and 'class="badge"' not in users_js

    def test_status_badges_use_neutral_status_style(self):
        """TESTER, ID SHARED and the Steam/Twitch link badges (app-admin-users.js), LIVE `.live-tag` and `.league-week-tag` (app-players.js) render through `statusBadgeHtml` / `.status-badge`; `_LINK_BADGE_STYLE` is removed."""
        users_js = _f("app-admin-users.js")
        assert "_LINK_BADGE_STYLE" not in users_js
        for call in ('statusBadgeHtml("TESTER"', 'statusBadgeHtml("ID SHARED"', 'statusBadgeHtml("Steam"',
                     'statusBadgeHtml("Twitch"'):
            assert call in users_js, call
        players = _f("app-players.js")
        assert '<span class="league-week-tag">' in players and '<span class="live-tag">' in players
        # The schedule tags share the status badge rule (same shape, neutral outline).
        section = _shared_states()
        for sel in (".league-week-tag", ".live-tag"):
            assert any("border-radius: var(--r-xs)" in b for b in _rule(section, sel)), sel
            assert any("border-color: var(--border)" in b for b in _rule(section, sel)), sel
        css = _css()
        outside = css[:_section_bounds(css)[0]]
        assert not any("font-family" in b or "color:" in b for b in _rule(outside, ".league-week-tag"))
        assert not _rule(outside, ".live-tag")

    def test_card_rarity_version_and_demo_badges_unchanged(self):
        """Card stickers on card art, rarity badges (`.lb-chip-rarity`, rarity chips) and the version and demo-mode badges are not converted to `.role-badge` / `.status-badge`."""
        assert '<span class="lb-chip-rarity"' in _f("app-leaderboard.js")
        css = _css()
        for sel in (".lb-chip-rarity", ".version-badge", ".demo-mode-badge", ".legendary"):
            assert _rule(css, sel), sel
        for sel, _ in _css_blocks(_shared_states(), r"."):
            for x in sel.split(","):
                assert not re.search(r"rarity|version-badge|demo-mode|sticker|\.badge(?![-\w])", x), x
        assert "role-badge" not in _f("app-cards.js") and "status-badge" not in _f("app-cards.js")

    def test_badge_markup_has_no_inline_style(self):
        """Failure path: no badge or tag markup in `frontend/app-*.js` (adminBadgeHtml, tagBadgeHtml, statusBadgeHtml and their callers, `_renderUsers`, `_lbStandingsRow`) carries a `style="` attribute or a hex colour."""
        glob = _f("app-globals.js")
        bodies = [_fn_body(glob, n) for n in ("adminBadgeHtml", "tagBadgeHtml", "statusBadgeHtml")]
        bodies.append(_fn_body(_f("app-leaderboard.js"), "_lbStandingsRow"))
        users_js = _f("app-admin-users.js")
        bodies += [_fn_body(users_js, n) for n in ("_renderUsers", "_linkBadges", "_renderTwitchViewerRow")]
        for body in bodies:
            body = _strip_js_comments(body)
            badge_lines = [l for l in body.splitlines() if "badge" in l.lower() or "<span" in l]
            for line in badge_lines:
                assert 'style="' not in line and "style='" not in line, line
                assert not _HEX.search(line), line
        assert "tag-chip" not in _f("app-profile.js")

    def test_tag_badge_html_escapes_label_and_title(self):
        """Failure path, Node harness: a tag with label `<img src=x onerror=1>"` and an unknown key renders escaped text and an escaped `title` (no raw `<`, `>` or `"` inside the attribute)."""
        out = _badges('out.h = tagBadgeHtml({key: "x\\"><b>", label: "<img src=x onerror=1>\\""});'
                      'out.s = statusBadgeHtml("<i>", "\\"><b>");')
        html = out["h"]
        assert "<img" not in html and "<b>" not in html
        items = _Elements(html).items
        assert [i["tag"] for i in items] == ["span"]
        assert items[0]["attrs"]["title"] == '<img src=x onerror=1>"'
        assert items[0]["text"] == '<img src=x onerror=1>"'
        assert _classes(items[0]) == ["role-badge", "role-badge-tag"]
        status = _Elements(out["s"]).items
        assert [i["tag"] for i in status] == ["span"] and status[0]["attrs"]["title"] == '"><b>'


# ---------------------------------------------------------------------------
# Story 4: Your Own Row Stands Out Wherever You Appear
# ---------------------------------------------------------------------------

class TestOwnRow:

    def test_lb_standings_row_marks_self_with_row_self(self):
        """Node harness: with `activeUserId` equal to the row's id, `_lbStandingsRow` returns a main `<tr>` with class `row-self` and a "(You)" label in the badge style."""
        out = _badges(f"out.h = _lbStandingsRow({json.dumps(_ROW)}, 0, 'week_points');", active_user="7")
        main = _rows(out["h"])[0]
        assert "row-self" in _classes(main)
        you = [i for i in _Elements(out["h"]).items if i["text"] == "(You)"]
        assert len(you) == 1 and _classes(you[0]) == ["status-badge"]

    def test_lb_standings_detail_row_gets_self_tint(self):
        """Node harness: for the signed-in user's row with cards, the `lb-card-detail` row also carries `row-self`."""
        out = _badges(f"out.h = _lbStandingsRow({json.dumps(_ROW)}, 0, 'week_points');", active_user="7")
        rows = _rows(out["h"])
        assert len(rows) == 2
        assert {"lb-card-detail", "hidden", "row-self"} <= set(_classes(rows[1]))

    def test_row_self_css_full_row_tint_bold_no_left_border(self):
        """`.row-self` (and its cells) use `background: var(--row-self-bg)` and bold weight; no `border-left`, `box-shadow: inset` bar or hex colour."""
        css = _css()
        bodies = _rule(css, ".row-self") + _rule(css, ".row-self > td")
        assert any("background: var(--row-self-bg)" in b and "font-weight: var(--w-bold)" in b for b in bodies)
        assert _rule(css, ".row-self > td")
        for sel, body in _css_blocks(css, r"row-self"):
            assert "border-left" not in body and "inset" not in body and not _HEX.search(body), sel

    def test_past_season_standings_marks_self_row(self):
        """`loadPastSeasonStandings` adds `row-self` when `r.user_id` matches `activeUserId` (the archive payload uses `user_id`, not `id`)."""
        body = _fn_body(_f("app-leaderboard.js"), "loadPastSeasonStandings")
        assert """<tr${_lbIsSelf(r.user_id) ? ' class="row-self"' : ""}>""" in body
        out = _badges("out.a = _lbIsSelf(7); out.b = _lbIsSelf('7'); out.c = _lbIsSelf(8); out.d = _lbIsSelf(undefined);",
                      active_user="7")
        assert out == {"a": True, "b": True, "c": False, "d": False}
        from routers import leaderboard
        import inspect
        assert "user_id" in inspect.getsource(leaderboard)

    def test_lb_standings_row_has_no_inline_colour(self):
        """`_lbStandingsRow` contains no `style="` attribute for colour/weight, no `#f0b429` and app-leaderboard.js has no hex colours; the "(You)" label has no inline style."""
        js = _f("app-leaderboard.js")
        row = _fn_body(js, "_lbStandingsRow")
        assert "style=" not in row and "#f0b429" not in js
        assert not _HEX.search(_strip_js_comments(js))
        assert "#f0b429" not in _f("app-roster.js")
        out = _badges(f"out.h = _lbStandingsRow({json.dumps(_ROW)}, 0, 'week_points');", active_user="7")
        assert all("style" not in i["attrs"] for i in _Elements(out["h"]).items)

    def test_lb_standings_row_logged_out_no_self_row(self):
        """Failure path, Node harness: with `activeUserId = null`, no row from `_lbStandingsRow` has `row-self` and none shows "(You)"."""
        out = _badges(f"out.h = _lbStandingsRow({json.dumps(_ROW)}, 0, 'week_points');"
                      f"out.n = _lbStandingsRow({json.dumps({**_ROW, 'id': None})}, 1, 'week_points');")
        for html in (out["h"], out["n"]):
            assert all("row-self" not in _classes(r) for r in _rows(html))
            assert "(You)" not in html


# ---------------------------------------------------------------------------
# Story 5: Weekly Report Emphasis Follows the Rules
# ---------------------------------------------------------------------------

class TestWeeklyReportEmphasis:

    def test_winner_and_mvp_draw_no_border_outline_or_ring(self):
        """`.weekly-summary-winner` and `.weekly-summary-mvp` set no `border`, `outline` or ring `box-shadow` (base rules and any @media overrides)."""
        css = _css()
        for cls in ("weekly-summary-winner", "weekly-summary-mvp"):
            for sel, body in _css_blocks(css, rf"\.{cls}(?![-\w])"):
                for x in sel.split(","):
                    if re.search(rf"\.{cls}(?![-\w])\s*$", x.strip()):
                        assert not re.search(r"\b(border|outline|box-shadow)\s*:", body), (x, body)

    def test_winner_team_name_uses_mark_winner_bold_under_label(self):
        """The winning team name is `color: var(--mark-winner)` and bold, and `_weeklySummaryTeamColHtml` keeps the "Winner" label above it. Issue #202 review: the markup uses the shared `.mark-winner` class (label and name block), also when `teamLink()` returns plain text (no team id); the surface rules copy no colours."""
        section = _shared_states()
        mark = _rule(section, ".mark-winner")
        assert any("color: var(--mark-winner)" in b and "font-weight: var(--w-bold)" in b for b in mark)
        assert not _css_blocks(_css(), r"\.weekly-summary-winner\s+\.weekly-summary-match-team-inner")
        assert "color" not in _css_rule(_css(), ".weekly-summary-winner-label")
        col = _fn_body(_f("app-weekly-summary.js"), "_weeklySummaryTeamColHtml")
        assert col.index("${winnerLabel}") < col.index("weekly-summary-match-team-inner")
        out = _ws("out.link = _weeklySummaryTeamColHtml({id: 4, name: 'Reaktor'}, true, false);"
                  "out.plain = _weeklySummaryTeamColHtml({id: null, name: 'Nameless'}, true, true);"
                  "out.loser = _weeklySummaryTeamColHtml({id: 5, name: 'Other'}, false, false);")
        for key, name in (("link", "Reaktor"), ("plain", "Nameless")):
            items = _Elements(out[key]).items
            label = next(i for i in items if "weekly-summary-winner-label" in _classes(i))
            assert "mark-winner" in _classes(label) and label["text"] == "Winner"
            inner = next(i for i in items if "weekly-summary-match-team-inner" in _classes(i))
            assert "mark-winner" in _classes(inner), key
            marked = out[key][out[key].index("weekly-summary-match-team-inner"):]
            assert name in marked, key
        assert "mark-winner" not in out["loser"] and "Winner" not in out["loser"]

    def test_mvp_label_uses_mark_mvp_before_name_on_own_line(self):
        """The MVP label is block-level, carries the shared `.mark-mvp` class (`var(--mark-mvp)`) and is emitted before the player name in `_weeklySummaryPlayerHtml`."""
        label = _css_rule(_css(), ".weekly-summary-mvp-label")
        assert "display: block" in label and "color" not in label
        assert any("color: var(--mark-mvp)" in b for b in _rule(_shared_states(), ".mark-mvp"))
        fn = _fn_body(_f("app-weekly-summary.js"), "_weeklySummaryPlayerHtml")
        assert "'<div class=\"weekly-summary-mvp-label mark-mvp\">MVP</div>'" in fn
        assert fn.index("${mvpLabel}") < fn.index("playerLink(p.player_id, p.name)")

    def test_roster_game_mvp_chip_uses_mark_mvp(self):
        """The My roster MVP chip carries the shared `.mark-mvp` class (`var(--mark-mvp)`, not `--accent`), matching the results column, and its own rule sets no colour."""
        assert "color" not in _css_rule(_css(), ".weekly-summary-game-mvp")
        game = _fn_body(_f("app-weekly-summary.js"), "_weeklySummaryGameHtml")
        assert '<span class="weekly-summary-game-mvp mark-mvp${' in game
        mark = _rule(_shared_states(), ".mark-mvp")
        assert any("color: var(--mark-mvp)" in b and "var(--accent)" not in b for b in mark)

    def test_mark_winner_and_mark_mvp_differ(self):
        """`--mark-winner` and `--mark-mvp` resolve to different values, and the winner (bold name) and MVP (label chip) use different forms."""
        assert _token("--mark-winner") != _token("--mark-mvp")
        # Winner: the team name itself, bold. MVP: a separate label; the player name stays plain.
        css = _css()
        assert not any("--mark-mvp" in b for b in _rule(css, ".weekly-summary-player"))
        js = _f("app-weekly-summary.js")
        assert "mark-winner" not in _fn_body(js, "_weeklySummaryPlayerHtml")
        assert "mark-mvp" not in _fn_body(js, "_weeklySummaryTeamColHtml")

    def test_weekly_report_images_not_draggable(self):
        """Every `<img` emitted by app-weekly-summary.js (avatars, team logos, hero icons, roster thumbnails) has `draggable="false"`, and controls/images in the report get `user-select: none` via the shared selection rule."""
        js = _f("app-weekly-summary.js")
        imgs = re.findall(r"<img\b[^`]*?>", js)
        assert len(imgs) >= 3
        assert all('draggable="false"' in tag for tag in imgs), imgs
        section = _shared_states()
        assert any("user-select: none" in b for b in _rule(section, "img"))
        assert any("user-select: none" in b for b in _rule(section, "button"))

    def test_weekly_report_thumbnails_keep_viewer_and_focus(self):
        """Roster thumbnails still open the card viewer (their click/keyboard handler is unchanged) and no new rule removes their focus outline."""
        card = _fn_body(_f("app-weekly-summary.js"), "_weeklySummaryRosterCardHtml")
        assert '<button type="button" class="weekly-summary-roster-thumb"' in card
        assert 'onclick="_weeklySummaryShowCard(${Number(c.card_id)})"' in card
        css = _css()
        assert "outline: 2px solid var(--accent)" in _css_rule(css, ".weekly-summary-roster-thumb:focus-visible")
        for sel, body in _css_blocks(_shared_states(), r"."):
            assert not re.search(r"outline:\s*(none|0)\b", body), sel

    def test_weekly_summary_game_is_fixed_column_grid(self):
        """`.weekly-summary-game` is `display: grid` with a fixed `grid-template-columns` for date | opponent | game | result | MVP | points, no `flex-wrap`, numbers `tabular-nums`, and the opponent column wraps (`min-width: 0`, `overflow-wrap: anywhere`)."""
        css = _css()
        game = _css_rule(css, ".weekly-summary-game")
        assert "display: grid" in game and "flex-wrap" not in game
        cols = re.findall(r"minmax\([^)]*\)|\S+", re.search(r"grid-template-columns:\s*([^;]+);", game).group(1))
        assert len(cols) == 6 and cols[1] == "minmax(0, 1fr)"  # date | opponent (flexible) | ...
        fixed = cols[:1] + cols[2:]
        assert all(re.fullmatch(r"[0-9.]+rem", c) for c in fixed), cols
        opp = _css_rule(css, ".weekly-summary-game-opp")
        assert "min-width: 0" in opp and "overflow-wrap: anywhere" in opp
        for sel in (".weekly-summary-game-date", ".weekly-summary-game-pts", ".weekly-summary-game-num"):
            assert "tabular-nums" in _css_rule(css, sel), sel

    def test_weekly_summary_game_mvp_row_not_taller(self):
        """The MVP chip in a game row adds no vertical padding/border height beyond the row's line box (line-height and vertical padding match the other cells), so MVP rows are not taller."""
        css = _css()
        bodies = _rule(css, ".weekly-summary-game-mvp")
        assert len(bodies) >= 2  # its own rule and the shared result/MVP type rule
        for body in bodies:
            assert not re.search(r"(?<![-\w])(border|padding|line-height|font-size|margin)\s*:", body), body
        assert "line-height" in _css_rule(css, ".weekly-summary-game")

    def test_weekly_summary_game_columns_present_without_mvp(self):
        """`_weeklySummaryGameHtml` (the `.weekly-summary-game` builder) always emits the MVP cell (empty when not MVP), so columns line up across rows and cards."""
        game = _fn_body(_f("app-weekly-summary.js"), "_weeklySummaryGameHtml")
        assert ": '<span class=\"weekly-summary-game-mvp-none\"></span>';" in game
        assert "const result = g.won == null ? '<span class=\"weekly-summary-game-result\"></span>'" in game
        # The narrow layout places the empty cell where the MVP chip would be.
        assert any("grid-area: mvp" in b for b in _rule(_css(), ".weekly-summary-game-mvp-none"))

    def test_roster_card_header_name_and_total_share_baseline(self):
        """The My roster card header aligns player name and total with `align-items: baseline`."""
        assert "align-items: baseline" in _css_rule(_css(), ".weekly-summary-roster-top")

    def test_base_img_user_select_none_and_card_art_keeps_hover_lift(self):
        """The shared base styles set `user-select: none` (and `-webkit-user-drag: none`) on `img`; the `.card-img` hover transform still exists."""
        img = _rule(_shared_states(), "img")
        assert any("user-select: none" in b and "-webkit-user-drag: none" in b for b in img)
        assert "transform" in _css_rule(_css(), ".card-img:hover")

    def test_names_dates_and_numbers_stay_selectable(self):
        """Failure path: no `user-select: none` rule targets text elements (player names, dates, points, prose) such as `.weekly-summary-player`, `.weekly-summary-game-date`, `.weekly-summary-game-pts`, `body`, `td`."""
        text = {".weekly-summary-player", ".weekly-summary-game-date", ".weekly-summary-game-pts",
                ".weekly-summary-game-opp", ".weekly-summary-roster-player", ".entity-link", "body", "td",
                "p", "span", "*"}
        for sel, body in _css_blocks(_css(), r"."):
            if not re.search(r"(?<![-\w])user-select:\s*none", body):
                continue
            for x in sel.split(","):
                assert x.strip() not in text, x


# ---------------------------------------------------------------------------
# Story 6: Reopening the Weekly Report Doesn't Flash
# ---------------------------------------------------------------------------

class TestWeeklyReportCache:

    def test_close_weekly_summary_keeps_cache(self):
        """Node harness: after opening week A and calling `closeWeeklySummary()`, `_weeklySummaryCache` still holds A."""
        out = _ws("await openWeeklySummary(1); closeWeeklySummary();"
                  "out.has = _weeklySummaryCache.has(1); out.hidden = el('weeklySummaryModal').classList.contains('hidden');")
        assert out == {"has": True, "hidden": True}

    def test_cache_entries_store_data_and_fetch_time(self):
        """Node harness: a cache entry is `{data, at}` with `at` equal to the (faked) `Date.now()` of the fetch."""
        out = _ws("await openWeeklySummary(1); var e = _weeklySummaryCache.get(1);"
                  "out.keys = Object.keys(e).sort(); out.at = e.at === NOW; out.week = e.data.week_id;")
        assert out == {"keys": ["at", "data"], "at": True, "week": 1}

    def test_reopen_fresh_week_renders_without_fetch_or_dim(self):
        """Node harness: reopening within 60 s renders the cached week at once, makes no `/weekly-summary/{id}` fetch and never adds `is-loading`."""
        out = _ws("WEEK[1] = week(1, false, 'Alpha'); await openWeeklySummary(1); closeWeeklySummary();"
                  "resetLoading(); NOW += 30000; var before = count('GET /weekly-summary/1'); var n = renderCalls.length;"
                  "await openWeeklySummary(1);"
                  "out.fetches = count('GET /weekly-summary/1') - before; out.loading = loadingEver();"
                  "out.rendered = renderCalls.slice(n); out.content = el('weeklySummaryContent').innerHTML.includes('Alpha');")
        assert out == {"fetches": 0, "loading": False, "rendered": [{"playRecap": False}], "content": True}

    def test_reopen_stale_week_refreshes_quietly(self):
        """Node harness: reopening after more than 60 s renders the cached week, fetches it once, never adds `is-loading`, and re-renders through `renderIfChanged`."""
        out = _ws("WEEK[1] = week(1, false, 'Alpha'); await openWeeklySummary(1); closeWeeklySummary();"
                  "resetLoading(); NOW += 61000; WEEK[1] = week(1, false, 'Beta');"
                  "var before = count('GET /weekly-summary/1'); var w = el('weeklySummaryContent').writes; var r = ricCalls;"
                  "await openWeeklySummary(1);"
                  "out.fetches = count('GET /weekly-summary/1') - before; out.loading = loadingEver();"
                  "out.writes = el('weeklySummaryContent').writes - w; out.ric = ricCalls > r;"
                  "out.beta = el('weeklySummaryContent').innerHTML.includes('Beta');"
                  "out.at = _weeklySummaryCache.get(1).at === NOW;")
        # One write: the cached week was already on screen (no write), the refresh changed it.
        assert out == {"fetches": 1, "loading": False, "writes": 1, "ric": True, "beta": True, "at": True}

    def test_quiet_refresh_never_replays_recap(self):
        """Node harness: a refresh of a cached revealed week calls `renderWeeklySummaryContent` with `playRecap: false`."""
        out = _ws("LIST.weeks[0].revealed = true; WEEK[1] = week(1, true, 'Alpha'); await openWeeklySummary(1);"
                  "out.first = renderCalls.slice(); closeWeeklySummary(); NOW += 61000; var n = renderCalls.length;"
                  "await openWeeklySummary(1); out.after = renderCalls.slice(n);")
        assert out["first"] == [{"playRecap": True}]
        assert out["after"] == [{"playRecap": False}, {"playRecap": False}]

    def test_week_list_reused_when_fresh(self):
        """Node harness: reopening within 60 s of the last list fetch does not call `GET /weekly-summary` again."""
        out = _ws("await openWeeklySummary(1); closeWeeklySummary(); NOW += 59000;"
                  "await openWeeklySummary(1); out.lists = count('GET /weekly-summary');")
        assert out == {"lists": 1}

    def test_week_list_refetched_once_when_stale(self):
        """Node harness: reopening after more than 60 s fetches `GET /weekly-summary` exactly once."""
        out = _ws("await openWeeklySummary(1); closeWeeklySummary(); NOW += 61000; var before = count('GET /weekly-summary');"
                  "await openWeeklySummary(1); out.lists = count('GET /weekly-summary') - before;")
        assert out == {"lists": 1}

    def test_week_list_signature_change_clears_cache(self):
        """Node harness: when the fetched week list's signature (`week_id:label:revealed`) changes, `_weeklySummaryCache` is cleared."""
        out = _ws("await openWeeklySummary(1); out.cached = _weeklySummaryCache.size;"
                  "_setWeeklySummaryList({weeks: [{week_id: 1, label: 'Week 1', revealed: false}]}); out.same = _weeklySummaryCache.size;"
                  "_setWeeklySummaryList({weeks: [{week_id: 2, label: 'Week 2', revealed: false}, {week_id: 1, label: 'Week 1', revealed: false}]});"
                  "out.changed = _weeklySummaryCache.size;")
        assert out == {"cached": 1, "same": 1, "changed": 0}

    def test_active_week_tab_click_is_noop(self):
        """Node harness: `selectWeeklySummaryTab(activeId)` with the popup open makes no fetch, no render and does not bump `_weeklySummaryReq`."""
        out = _ws("await openWeeklySummary(1); var c = calls.length, r = renderCalls.length, q = _weeklySummaryReq;"
                  "var w = el('weeklySummaryContent').writes;"
                  "await selectWeeklySummaryTab(1);"
                  "out.fetches = calls.length - c; out.renders = renderCalls.length - r; out.req = _weeklySummaryReq - q;"
                  "out.writes = el('weeklySummaryContent').writes - w;"
                  "out.open = !el('weeklySummaryModal').classList.contains('hidden');")
        assert out == {"fetches": 0, "renders": 0, "req": 0, "writes": 0, "open": True}

    def test_reveal_clears_cache(self):
        """Node harness: `revealAllWeeklySummaries()` after a successful `POST /weekly-summary/reveal-all` removes the revealed weeks from `_weeklySummaryCache`."""
        out = _ws("await openWeeklySummary(1); var before = count('GET /weekly-summary/1');"
                  "WEEK[1] = week(1, true, 'Alpha');"
                  "var origDel = _weeklySummaryCache.delete.bind(_weeklySummaryCache); var deleted = [];"
                  "_weeklySummaryCache.delete = function (k) { deleted.push(k); return origDel(k); };"
                  "await revealAllWeeklySummaries();"
                  "out.posted = count('POST /weekly-summary/reveal-all'); out.deleted = deleted;"
                  "out.refetched = count('GET /weekly-summary/1') - before;"
                  "out.revealed = _weeklySummaryCache.get(1).data.revealed; out.active = _weeklySummaryActiveWeekId;")
        assert out == {"posted": 1, "deleted": [1], "refetched": 1, "revealed": True, "active": 1}

    def test_logout_and_user_switch_clear_cache(self):
        """`_clearLocalAuthState` (used by `logout()` and the 401 path in `loadMe`) and `login()` in app-auth.js clear the Weekly Report cache (and its week-list fetch time)."""
        auth = _f("app-auth.js")
        hook = 'if (typeof clearWeeklySummaryCache === "function") clearWeeklySummaryCache();'
        assert hook in _fn_body(auth, "_clearLocalAuthState")
        assert "_clearLocalAuthState();" in _fn_body(auth, "logout")
        login = _fn_body(auth, "login")
        assert hook in login and login.index(hook) < login.index("await loadMe();")
        out = _ws("await openWeeklySummary(1); closeWeeklySummary(); clearWeeklySummaryCache();"
                  "out.size = _weeklySummaryCache.size; out.listAt = _weeklySummaryListAt; out.sig = _weeklySummaryListSig;"
                  "out.roster = el('weeklySummaryRoster').innerHTML; out.content = el('weeklySummaryContent').innerHTML;"
                  "var before = count('GET /weekly-summary'); await openWeeklySummary(1);"
                  "out.lists = count('GET /weekly-summary') - before;")
        assert out == {"size": 0, "listAt": 0, "sig": None, "roster": "", "content": "", "lists": 1}

    def test_seen_posted_only_when_unseen(self):
        """Node harness: `openWeeklySummary` posts `POST /weekly-summary/seen` when the list reports `has_unseen: true`."""
        out = _ws("LIST.has_unseen = true; await openWeeklySummary(1); out.seen = count('POST /weekly-summary/seen');"
                  "closeWeeklySummary(); await openWeeklySummary(1); out.again = count('POST /weekly-summary/seen');")
        assert out == {"seen": 1, "again": 1}

    def test_seen_not_posted_without_unseen(self):
        """Failure path, Node harness: with `has_unseen: false`, opening the report sends no `POST /weekly-summary/seen`."""
        out = _ws("await openWeeklySummary(1); out.seen = count('POST /weekly-summary/seen');")
        assert out == {"seen": 0}

    @pytest.mark.parametrize("mode", ["throw", "status"])
    def test_stale_refresh_error_keeps_cached_content(self, mode):
        """Failure path, Node harness: a failed quiet refresh (non-OK or thrown fetch) leaves the cached week on screen with no error message and no `is-loading`."""
        out = _ws("WEEK[1] = week(1, false, 'Alpha'); await openWeeklySummary(1); closeWeeklySummary();"
                  f"resetLoading(); NOW += 61000; _weeklySummaryListAt = NOW; FAIL = '{mode}';"
                  "await openWeeklySummary(1);"
                  "out.alpha = el('weeklySummaryContent').innerHTML.includes('Alpha');"
                  "out.err = el('weeklySummaryContent').innerHTML.includes('err');"
                  "out.loading = loadingEver(); out.tried = count('GET /weekly-summary/1');")
        assert out == {"alpha": True, "err": False, "loading": False, "tried": 2}

    def test_clear_drops_week_fetch_in_flight(self):
        """Security review (Low): a week fetch started for user A that answers after A logs out and B signs in never lands in the cache or on screen; `clearWeeklySummaryCache` bumps `_weeklySummaryReq`, stops the recap and removes the dim."""
        out = _ws("WEEK[1] = week(1, false, 'AliceTeam'); HOLD = true;"
                  "var p = openWeeklySummary(1); await tick(); await tick();"
                  "out.pending = HELD.length; var q = _weeklySummaryReq;"
                  "clearWeeklySummaryCache(); activeUserId = 2;"
                  "out.bumped = _weeklySummaryReq > q; release(); await p;"
                  "out.size = _weeklySummaryCache.size;"
                  "out.shown = el('weeklySummaryContent').innerHTML.includes('AliceTeam');"
                  "out.loading = el('weeklySummaryContent').classList.contains('is-loading');")
        assert out == {"pending": 1, "bumped": True, "size": 0, "shown": False, "loading": False}
        body = _fn_body(_f("app-weekly-summary.js"), "clearWeeklySummaryCache")
        for call in ("_weeklySummaryReq += 1;", "_stopRecap();", "_setWeeklySummaryLoading(false);"):
            assert call in body, call

    def test_cache_dropped_when_signed_in_user_changes(self):
        """Security review (Low): the cache records its owner (`activeUserId`); when another user is signed in (e.g. from another tab sharing the cookie), reopening refetches the list and the week instead of showing the previous user's data."""
        out = _ws("WEEK[1] = week(1, false, 'AliceTeam'); await openWeeklySummary(1); closeWeeklySummary();"
                  "out.owner = _weeklySummaryCacheUser; NOW += 10000; activeUserId = 2; WEEK[1] = week(1, false, 'BobTeam');"
                  "var lists = count('GET /weekly-summary'), weeks = count('GET /weekly-summary/1');"
                  "await openWeeklySummary(1);"
                  "out.lists = count('GET /weekly-summary') - lists; out.weeks = count('GET /weekly-summary/1') - weeks;"
                  "out.bob = el('weeklySummaryContent').innerHTML.includes('BobTeam');"
                  "out.alice = el('weeklySummaryContent').innerHTML.includes('AliceTeam');"
                  "out.newOwner = _weeklySummaryCacheUser;")
        assert out == {"owner": "1", "lists": 1, "weeks": 1, "bob": True, "alice": False, "newOwner": "2"}
        js = _f("app-weekly-summary.js")
        for fn in ("selectWeeklySummaryTab", "_setWeeklySummaryList", "loadWeeklySummaryList"):
            assert "_ensureWeeklySummaryOwner();" in _fn_body(js, fn), fn

    def test_load_me_clears_cache_when_user_id_changes(self):
        """Security review (Low): `loadMe()` clears the Weekly Report cache when `/me` returns a different user id than the one signed in before, and before `activeUserId` is replaced."""
        body = _fn_body(_f("app-auth.js"), "loadMe")
        guard = ('if (activeUserId != null && String(activeUserId) !== String(data.user_id)\n'
                 '        && typeof clearWeeklySummaryCache === "function") clearWeeklySummaryCache();')
        assert guard in body
        assert body.index(guard) < body.index("activeUserId             = data.user_id;")

    def test_every_generated_img_is_not_draggable(self):
        """Issue #202 review (Selection rule, site-wide): every `<img` in the template strings of `frontend/app-*.js` carries `draggable="false"`."""
        found = 0
        for name in sorted(os.listdir(_FRONTEND)):
            if not (name.startswith("app-") and name.endswith(".js")):
                continue
            js = re.sub(r"/\*.*?\*/", "", _strip_js_comments(_f(name)), flags=re.S)
            for tag in re.findall(r"<img\b[^>]*>", js):
                found += 1
                assert 'draggable="false"' in tag, (name, tag)
        assert found >= 10


class TestSelectedWeekChipDetails:

    def test_current_week_details_stay_visible_when_selected_chip_inverts(self):
        """Issue #202 review: on a selected week chip that is hovered or focused (accent fill), the accent "This week" label and the hidden-results marker switch to `--state-selected-hover-fg`, so they don't vanish."""
        section = _shared_states()
        for state in (":hover", ":focus-visible"):
            tag = _rule(section, f".schedule-week-chip.selected{state} .schedule-week-chip-tag")
            assert any("color: var(--state-selected-hover-fg)" in b for b in tag), state
            marker = _rule(section, f".schedule-week-chip.selected{state} .schedule-week-chip-marker")
            assert any("background: var(--state-selected-hover-fg)" in b for b in marker), state
        css = _css()
        assert "color: var(--accent)" in _css_rule(css, ".schedule-week-chip-tag")
        assert "background: var(--accent)" in _css_rule(css, ".schedule-week-chip-marker")

    def test_readme_exempts_transient_motion_highlights_from_no_rings(self):
        """Issue #202 review: the "no rings" rule names its exemption for transient motion highlights (the recap's `.weekly-summary-game-mvp.hl` glow), which still exists."""
        sec = _states_section()
        assert "transient motion highlights" in sec and ".weekly-summary-game-mvp.hl" in sec
        assert "box-shadow" in _css_rule(_css(), ".weekly-summary-game-mvp.hl")
