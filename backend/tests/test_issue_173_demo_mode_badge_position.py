"""
Tests for plan-issue-173-demo-mode-badge-position (resolves GitHub issue #173).

With DEMO_MODE=true the "DEMO MODE" notice (`#demo-mode-badge`,
`.demo-mode-badge`) moves from a full-width strip fixed to the top of the window
to a compact chip in the bottom-right corner, stacked directly above the build
`.version-badge` (bottom: 6px; right: 10px; z-index: 9999). Only position and
shape change: the text, `GET /config` `demo_mode` and the toggle in
`loadConfig()` (`frontend/app-globals.js`) stay as they are.

The feature is CSS-only, so criteria are checked statically against
`frontend/style.css`, `frontend/index.html` and `frontend/app-globals.js`, using
the helpers of test_issue_144_guided_tour.py:

    _BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
    _REPO_DIR = os.path.join(_BACKEND_DIR, "..")
    _FRONTEND_DIR = os.path.join(_REPO_DIR, "frontend")

    def _read(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    # One CSS rule body (no nested braces), as in test_issue_144:
    #   re.search(r"\\.tour-box \\{(.*?)\\}", css, re.S).group(1)
    # Anchor on a line start (r"^\\.demo-mode-badge \\{") so a later
    # `@media` override or a compound selector isn't picked up by mistake.

    # Markup: parse index.html with html.parser.HTMLParser (the `_Tags` /
    # `_tags` helper in test_issue_144) rather than a tag regex — CodeQL
    # py/bad-tag-filter flags regexes that match HTML tags (lessons-learned).

The backend `demo_mode` flag itself is already covered by
test_issue_83_demo_mode.py (`main.get_config(db=db)` with monkeypatch.setenv);
the failure-path stub here only pins the frontend hide/show toggle.

Notes for the developer:
  - `--r-xs` is defined in `frontend/colors_and_type.css` (2px), not style.css.
  - "Directly above the version badge, no overlap": the version badge sits at
    bottom: 6px with font-size: 10px (~14px line box), so the chip's `bottom`
    must be > 6px + that line height (the plan uses 28px) and its `right`
    should match the version badge's (10px).
  - Check any `@media` block in style.css that touches `.demo-mode-badge`
    does not reintroduce `top`/`left` or drop `white-space: nowrap`.

Manual-only (need a real browser, see the plan's Verification section):
  - the header, tab bar and their buttons are visibly uncovered and clickable
  - at 360 px wide the chip fits on one line with a gap from the edges
  - the chip shows above an open modal and the guided tour

Stories:
  1. Demo Notice Out of the Way
"""
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: F401

_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
_REPO_DIR = os.path.join(_BACKEND_DIR, "..")
_FRONTEND_DIR = os.path.join(_REPO_DIR, "frontend")

INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
GLOBALS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-globals.js")
STYLE_CSS_PATH = os.path.join(_FRONTEND_DIR, "style.css")
TOKENS_CSS_PATH = os.path.join(_FRONTEND_DIR, "colors_and_type.css")

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _rule(css, selector):
    """Body of the top-level rule for `selector` (anchored on a line start)."""
    m = re.search(r"^" + re.escape(selector) + r" \{(.*?)\}", css, re.S | re.M)
    assert m, f"{selector} rule not found"
    return m.group(1)


def _decls(body):
    """Declarations of a rule body as {property: value}, comments stripped."""
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    out = {}
    for part in body.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _px(value):
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)px", value.strip())
    assert m, f"expected a px value, got {value!r}"
    return float(m.group(1))


def _badge():
    return _decls(_rule(_read(STYLE_CSS_PATH), ".demo-mode-badge"))


def _version():
    return _decls(_rule(_read(STYLE_CSS_PATH), ".version-badge"))


class _Badges(HTMLParser):
    """Records each #demo-mode-badge with its ancestor classes and text."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.found = []
        self._cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id") == "demo-mode-badge":
            ancestors = [c for _, cls in self.stack for c in cls]
            self._cur = {"attrs": a, "ancestors": ancestors, "text": "", "depth": len(self.stack)}
            self.found.append(self._cur)
        if tag not in _VOID:
            self.stack.append((tag, (a.get("class") or "").split()))

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break
        if self._cur is not None and len(self.stack) <= self._cur["depth"]:
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"] += data


def _media_blocks(css):
    """Bodies of every @media block (brace-balanced)."""
    blocks = []
    for m in re.finditer(r"@media[^{]*\{", css):
        depth, i = 1, m.end()
        while depth and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        blocks.append(css[m.end():i - 1])
    return blocks


# ---------------------------------------------------------------------------
# Story 1 — Demo Notice Out of the Way
# ---------------------------------------------------------------------------

class TestDemoNoticeOutOfTheWay:

    def test_demo_mode_badge_markup_reads_demo_mode_and_is_hidden_by_default(self):
        """index.html keeps a single #demo-mode-badge.demo-mode-badge outside the tab panels (shown on every tab), text "DEMO MODE", starting hidden (style="display:none")."""
        p = _Badges()
        p.feed(_read(INDEX_HTML_PATH))
        assert len(p.found) == 1
        badge = p.found[0]
        assert "demo-mode-badge" in (badge["attrs"].get("class") or "").split()
        assert badge["text"].strip() == "DEMO MODE"
        assert re.fullmatch(r"\s*display\s*:\s*none\s*;?\s*", badge["attrs"].get("style") or "")
        assert "tab-content" not in badge["ancestors"]
        assert "modal-overlay" not in badge["ancestors"]

    def test_demo_mode_badge_css_fixed_bottom_right_above_version_badge(self):
        """.demo-mode-badge is position: fixed with `bottom` and `right` set, right equal to .version-badge's right, and bottom greater than .version-badge's bottom (directly above it)."""
        b, v = _badge(), _version()
        assert b.get("position") == "fixed"
        assert "bottom" in b and "right" in b
        assert _px(b["right"]) == _px(v["right"])
        assert _px(b["bottom"]) > _px(v["bottom"])

    def test_demo_mode_badge_css_has_no_top_or_left_full_width_strip(self):
        """Failure path: the .demo-mode-badge rule has no `top` or `left` declaration (and no width: 100%), so it no longer spans the top of the page over the header and tab bar."""
        b = _badge()
        assert "top" not in b
        assert "left" not in b
        assert "inset" not in b
        assert b.get("width") not in ("100%", "100vw")

    def test_demo_mode_badge_css_never_takes_clicks_or_selection(self):
        """.demo-mode-badge keeps `pointer-events: none` and `user-select: none`, so nothing under it is blocked."""
        b = _badge()
        assert b.get("pointer-events") == "none"
        assert b.get("user-select") == "none"

    def test_demo_mode_badge_css_z_index_at_least_version_badge_and_modals(self):
        """.demo-mode-badge z-index is >= .version-badge's z-index and >= the highest z-index used by modal/tour overlays in style.css, so it stays above page content and open modals."""
        css = _read(STYLE_CSS_PATH)
        z = int(_badge()["z-index"])
        assert z >= int(_version()["z-index"])
        overlay_z = []
        for m in re.finditer(r"^([^{}\n]*(?:modal|overlay|tour)[^{}\n]*)\{([^{}]*)\}", css, re.M):
            d = _decls(m.group(2))
            if "z-index" in d and re.fullmatch(r"-?\d+", d["z-index"]):
                overlay_z.append(int(d["z-index"]))
        assert overlay_z, "expected modal/tour overlay z-index rules in style.css"
        assert z >= max(overlay_z)

    def test_demo_mode_badge_css_fits_one_line_at_phone_width(self):
        """At 360px the chip fits on one line with a gap from the edges: `white-space: nowrap`, right > 0, bottom > 0, no fixed width, and no @media rule re-adds top/left or removes nowrap."""
        b = _badge()
        assert b.get("white-space") == "nowrap"
        assert _px(b["right"]) > 0
        assert _px(b["bottom"]) > 0
        assert "width" not in b
        assert "min-width" not in b
        for block in _media_blocks(_read(STYLE_CSS_PATH)):
            for m in re.finditer(r"([^{}]*\.demo-mode-badge[^{}]*)\{([^{}]*)\}", block):
                d = _decls(m.group(2))
                assert "top" not in d and "left" not in d
                assert d.get("white-space", "nowrap") == "nowrap"
                assert "width" not in d

    def test_demo_mode_badge_css_does_not_overlap_version_badge(self):
        """The chip's bottom offset clears the version badge: bottom >= .version-badge bottom + its line box (font-size 10px, ~14px), i.e. at least 20px."""
        b, v = _badge(), _version()
        line_box = _px(v["font-size"]) * 1.4
        assert _px(b["bottom"]) >= _px(v["bottom"]) + line_box
        assert _px(b["bottom"]) >= 20

    def test_demo_mode_badge_css_uses_brand_radius_token(self):
        """.demo-mode-badge uses `border-radius: var(--r-xs)` (brand radius rule from test_issue_144), never --r-pill; --r-xs is defined in colors_and_type.css."""
        body = _rule(_read(STYLE_CSS_PATH), ".demo-mode-badge")
        assert _decls(body).get("border-radius") == "var(--r-xs)"
        assert "--r-pill" not in body
        assert "999px" not in body
        assert re.search(r"--r-xs:\s*\d+px;", _read(TOKENS_CSS_PATH))

    def test_load_config_hides_demo_badge_when_demo_mode_false_or_unset(self):
        """Failure path: with demo_mode false or unset the notice is not shown — loadConfig() in app-globals.js sets window.demoMode = cfg.demo_mode === true and sets #demo-mode-badge display to "none" when it is false."""
        js = _read(GLOBALS_JS_PATH)
        m = re.search(r"(?:async\s+)?function\s+loadConfig\s*\(", js)
        assert m, "loadConfig not found"
        fn = js[m.start():js.index("\n}\n", m.start())]
        assert "window.demoMode = cfg.demo_mode === true;" in fn
        assert 'document.getElementById("demo-mode-badge")' in fn
        assert re.search(r'demoBadge\.style\.display\s*=\s*window\.demoMode\s*\?\s*""\s*:\s*"none"', fn)
