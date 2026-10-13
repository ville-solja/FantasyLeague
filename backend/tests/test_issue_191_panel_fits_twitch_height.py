"""Tests for issue #191: the Twitch panel fits the height Twitch gives it.

Plan: markdown/plans/plan-issue-191-panel-fits-twitch-height.md

Frontend-only change in twitch-extension/: `body.panel` uses `height: 100vh`
instead of a fixed 500 px, every view scrolls inside it with a thin themed
scrollbar, panel.js keeps scroll position across the Live refresh and roster
re-renders, the dev harness gains 300 / 400 / 500 px height presets, package.sh
prints a Panel Height reminder, and the docs describe the panel as
"318 px wide, up to 500 px tall (the version's Panel Height)".

All checks are static (file contents). Real rendering at 300 / 400 / 500 px and in
the pop-out cannot be measured here; those criteria are checked structurally:
no fixed pixel height on `html` / `body.panel`, and every scroll area is
`flex: 1; min-height: 0; overflow-y: auto` (or the absolutely-positioned `.view`
with `overflow-y: auto`) rather than a pixel height. Visual confirmation stays
manual (see the plan's Verification section).

Patterns to reuse (do not reinvent):
- `_read(path)` for file contents, as in tests/test_issue_180_twitch_integration_status.py.
- `_js_function(src, name)` from tests/test_issue_157_twitch_extension_policy_compliance.py
  to extract `loadLive`, `renderRoster`, etc. from panel.js by brace matching.
  Import helpers by underscore name only so pytest does not collect another
  module's tests twice (see markdown/lessons-learned.md).
- package.sh is exercised in tests/test_twitch_review_resubmission.py via subprocess
  against a copy of twitch-extension/ in tmp_path; reuse that approach if the
  Panel Height reminder is checked from real output rather than source text.
- A small CSS rule extractor (selector -> declaration block) is worth adding here
  as a private helper; strip /* comments */ first.

Notes for the developer:
- Keep the policy 4.5 viewer-text check (test_issue_157) passing.
- Bump test_issue_85's suite-size baseline from the actual "N passed" count
  (lessons-learned 2026-10-11), not by adding this file's count to the old number.

Manual verification (not automated):
- Dev harness at 300, 400 and 500 px: scroll each view to its last element
  (Live: next match; Roster: last slot; Cards: last collection row; Team draw:
  last team with the footer visible).
- Hosted Test with Panel Height 500: Live shows all three sections, Roster
  reaches every slot without popping out; the pop-out still works.
- Wait for the 60 s Live refresh while scrolled down; the view stays put.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

from tests.test_issue_157_twitch_extension_policy_compliance import _js_function  # noqa: F401

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXT_DIR = REPO_ROOT / "twitch-extension"
EXT_CSS = EXT_DIR / "extension.css"
PANEL_HTML = EXT_DIR / "panel.html"
PANEL_JS = EXT_DIR / "panel.js"
DEV_HARNESS = EXT_DIR / "dev-harness.html"
PACKAGE_SH = EXT_DIR / "package.sh"
EXT_DOC = REPO_ROOT / "markdown" / "features" / "core" / "twitch-extension.md"
POLICY_DOC = REPO_ROOT / "markdown" / "features" / "reference" / "twitch-extension-policy-compliance.md"
UI_DOC = REPO_ROOT / "markdown" / "ui_description" / "twitch-panel.md"
PANEL_VIEWS = ("view-live", "view-cards", "view-teams", "view-roster", "view-picker")


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def _strip_at_blocks(css):
    """`css` without its @media / @font-face blocks (brace matched)."""
    out, i = [], 0
    for m in re.finditer(r"@[\w-]+[^{;]*\{", css):
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


def _media_block(css, query):
    """Body of the `@media <query>` block."""
    start = css.index("@media " + query)
    i = css.index("{", start) + 1
    depth, j = 1, i
    while depth:
        depth += {"{": 1, "}": -1}.get(css[j], 0)
        j += 1
    return css[i:j - 1]


def _css_rules(css):
    """List of (selector, declarations) for every top-level rule, comments and @-blocks stripped."""
    css = _strip_at_blocks(re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    rules = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = m.group(1).strip()
        if sel.startswith("@"):
            continue
        rules.append((" ".join(sel.split()), m.group(2)))
    return rules


def _decls(block):
    """Declarations of one rule as {property: value}."""
    out = {}
    for part in block.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _rules_for(css, selector):
    """Merged declarations of every rule whose selector list contains `selector` exactly."""
    merged = {}
    for sel, block in _css_rules(css):
        if selector in [x.strip() for x in sel.split(",")]:
            merged.update(_decls(block))
    return merged


def _panel_css():
    """The viewer-panel part of extension.css."""
    css = _read(EXT_CSS)
    return css[css.index("Viewer panel"):]


def _section(html, view_id):
    m = re.search(r'<section id="' + view_id + r'"[^>]*>.*?</section>', html, re.S)
    assert m, view_id
    return m.group(0)


def _section_tag(html, view_id):
    m = re.search(r'<section id="' + view_id + r'"[^>]*>', html)
    assert m, view_id
    return m.group(0)


_PX = re.compile(r"^\d+(\.\d+)?px$")
_SCROLL_SELECTORS = (".view", ".team-list", ".pin-scroll")
_HARD_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")


# ---------------------------------------------------------------------------
# Story 1 — Panel Uses the Height Twitch Gives It
# ---------------------------------------------------------------------------

def test_body_panel_height_is_100vh():
    """AC: `body.panel` takes the iframe's height (`height: 100vh`; `html` gets `height: 100%`) and keeps `overflow: hidden`; header and tab bar stay fixed at the top (flex column, only views scroll)."""
    css = _read(EXT_CSS)
    body = _rules_for(css, "body.panel")
    assert body.get("height") == "100vh"
    assert body.get("overflow") == "hidden"
    assert body.get("display") == "flex" and body.get("flex-direction") == "column"
    assert _rules_for(css, "html").get("height") == "100%"
    for sel in (".p-head", ".p-tabs"):
        assert _rules_for(css, sel).get("flex") == "none", sel


def test_views_scroll_without_pixel_height():
    """AC: the last element of every view (Live, Cards, Team draw, Roster, Card picker) is reachable by scrolling at 300/400/500 px and in the pop-out.

    Structural check only (real rendering cannot be measured): `.p-main` is
    `flex: 1; min-height: 0`, `.view` has `overflow-y: auto`, and no view or scroll
    area rule sets a fixed pixel `height` / `max-height`.
    """
    css = _read(EXT_CSS)
    main = _rules_for(css, ".p-main")
    assert main.get("flex") == "1" and main.get("min-height") == "0"
    view = _rules_for(css, ".view")
    assert view.get("overflow-y") == "auto"
    assert view.get("position") == "absolute" and view.get("inset") == "0"
    html = _read(PANEL_HTML)
    for vid in PANEL_VIEWS:
        assert 'class="view' in _section_tag(html, vid), vid
    scroll_prefixes = (".view", ".team-list", ".pin-scroll", ".p-main", ".slots", ".coll-grid", ".pick-list")
    for sel, block in _css_rules(_panel_css()):
        if any(n.strip().startswith(scroll_prefixes) for n in sel.split(",")):
            d = _decls(block)
            for prop in ("height", "max-height"):
                assert not _PX.match(d.get(prop, "")), (sel, prop, d.get(prop))


def test_panel_no_horizontal_overflow_at_318px():
    """AC: nothing is cut off at the right edge at 318 px width; no horizontal scrolling.

    Structural check: views set `overflow-x: hidden` (or equivalent) and no panel
    rule sets a fixed width larger than 318 px.
    """
    css = _read(EXT_CSS)
    assert _rules_for(css, ".view").get("overflow-x") == "hidden"
    assert _rules_for(css, ".team-list").get("overflow-x") == "hidden"
    assert _rules_for(css, ".view.with-pinned > .pin-scroll").get("overflow-x") == "hidden"
    for sel, block in _css_rules(_panel_css()):
        for prop in ("width", "min-width"):
            m = re.match(r"^(\d+)px$", _decls(block).get(prop, ""))
            assert not (m and int(m.group(1)) > 318), (sel, prop)


def test_pinned_footer_views_scroll_only_list():
    """AC: Team draw and picker keep the pinned footer visible and scroll only the list above it.

    Structural check: `.view.with-pinned` is a flex column with `overflow: hidden`,
    its list (`.team-list` and the picker list) is `flex: 1; min-height: 0;
    overflow-y: auto`, and the picker view uses the same pinned layout.
    """
    css = _read(EXT_CSS)
    pinned = _rules_for(css, ".view.with-pinned")
    assert pinned.get("display") == "flex" and pinned.get("flex-direction") == "column"
    assert pinned.get("overflow") == "hidden"
    for d in (_rules_for(css, ".team-list"), _rules_for(css, ".view.with-pinned > .pin-scroll")):
        assert d.get("flex") == "1" and d.get("min-height") == "0" and d.get("overflow-y") == "auto", d
    assert _rules_for(css, ".pinned").get("flex") == "none"
    html = _read(PANEL_HTML)
    for vid in ("view-teams", "view-picker"):
        assert "with-pinned" in _section_tag(html, vid), vid
    teams = _section(html, "view-teams")
    assert teams.index('class="team-list"') < teams.index('class="pinned"') < teams.index('id="btn-team-confirm"')
    picker = _section(html, "view-picker")
    assert picker.index('class="pin-scroll"') < picker.index('id="picker-list"') < picker.index('class="pinned"')
    assert picker.index('class="pinned"') < picker.index('id="btn-bench-it"')
    # Short panels: the whole view scrolls instead, with the footer kept visible (sticky).
    short = _media_block(re.sub(r"/\*.*?\*/", "", css, flags=re.S), "(max-height: 420px)")
    assert _rules_for(short, ".view.with-pinned").get("overflow-y") == "auto"
    sticky = _rules_for(short, ".view.with-pinned > .pinned")
    assert sticky.get("position") == "sticky" and sticky.get("bottom") == "0"


def test_body_panel_fixed_500px_height_removed():
    """Failure path: no `height: 500px` (or any fixed pixel height) remains on `html`, `body` or `body.panel`, which is what clipped the panel below a shorter iframe."""
    css = _read(EXT_CSS)
    for sel in ("html", "body", "body.panel"):
        d = _rules_for(css, sel)
        assert not _PX.match(d.get("height", "")), (sel, d.get("height"))
    assert not re.search(r"body\.panel\s*\{[^}]*height:\s*500px", css)


# ---------------------------------------------------------------------------
# Story 2 — Live Tab Shows Everything
# ---------------------------------------------------------------------------

def test_live_view_sections_in_scrollable_view():
    """AC: at 500 px all three Live sections (latest MVPs, top performers, next match) are visible or reachable by scrolling; at 300 px reachable by scrolling.

    Structural check: all three sections live inside `#view-live`, which is a
    `.view` with `overflow-y: auto` and no fixed pixel height.
    """
    html = _read(PANEL_HTML)
    live = _section(html, "view-live")
    for sid, heading in (("live-mvps", "Latest MVPs"), ("live-top", "Top performers"), ("live-next", "Next match")):
        assert 'id="' + sid + '"' in live and heading in live, sid
    assert 'class="view"' in _section_tag(html, "view-live")
    view = _rules_for(_read(EXT_CSS), ".view")
    assert view.get("overflow-y") == "auto" and "height" not in view


def test_load_live_preserves_scroll_position():
    """AC: the Live view keeps its scroll position when the 60 s refresh re-renders it — `loadLive` (or its render helper) saves `scrollTop` before replacing content and restores it after."""
    js = _read(PANEL_JS)
    keep = _js_function(js, "keepScroll")
    assert re.search(r"var top = view\.scrollTop;\s*render\(\);\s*view\.scrollTop = top;", keep)
    live = _js_function(js, "loadLive")
    assert live.count('keepScroll("view-live"') == 2
    for render in ("renderMvps(", "renderTopPerformers(", "renderNextMatch("):
        assert live.rfind('keepScroll("view-live"', 0, live.index(render)) != -1, render
    assert "setInterval(loadLive, LIVE_REFRESH_MS)" in _js_function(js, "onReady")


def test_live_sections_keep_loading_and_empty_states():
    """AC: loading and empty states still show in each Live section (the existing loading/empty strings remain in panel.html / panel.js)."""
    live = _section(_read(PANEL_HTML), "view-live")
    for sid in ("live-mvps", "live-top", "live-next"):
        assert '<div id="' + sid + '"><p class="note">Loading…</p></div>' in live, sid
    js = _read(PANEL_JS)
    assert "No match scheduled." in _js_function(js, "renderNextMatch")
    assert "unavailable right now" in _js_function(js, "renderMvpsUnavailable")
    assert "unavailable right now" in _js_function(js, "renderPanelUnavailable")
    live_fn = _js_function(js, "loadLive")
    assert ".catch(renderMvpsUnavailable)" in live_fn and ".catch(renderPanelUnavailable)" in live_fn


def test_load_live_does_not_reset_scroll_to_top():
    """Failure path: the Live refresh never forces the view back to the top (no unconditional `scrollTop = 0` / `scrollTo(0, 0)` in the refresh path)."""
    js = _read(PANEL_JS)
    for fn in ("loadLive", "keepScroll", "renderMvps", "renderTopPerformers", "renderNextMatch",
               "renderMvpsUnavailable", "renderPanelUnavailable", "onPubSub"):
        body = _js_function(js, fn)
        assert not re.search(r"scrollTop\s*=\s*0\b", body), fn
        assert "scrollTo(" not in body and "scrollIntoView" not in body, fn


# ---------------------------------------------------------------------------
# Story 3 — Roster Shows Every Slot
# ---------------------------------------------------------------------------

def test_roster_view_scrolls_all_slots():
    """AC: all `ROSTER_LIMIT` slots (and the bench, if shown) are reachable by scrolling the Roster view at 300/400/500 px.

    Structural check: the slot list and bench live inside `#view-roster`, a
    `.view` with `overflow-y: auto`, and no slot/list rule caps height in pixels.
    """
    html = _read(PANEL_HTML)
    roster = _section(html, "view-roster")
    assert 'id="roster-slots"' in roster and 'id="bench-count"' in roster
    assert 'class="view"' in _section_tag(html, "view-roster")
    css = _read(EXT_CSS)
    assert _rules_for(css, ".view").get("overflow-y") == "auto"
    for sel in (".slots", ".slot"):
        d = _rules_for(css, sel)
        assert "height" not in d and "max-height" not in d, sel
        assert "overflow" not in d and "overflow-y" not in d, sel


def test_roster_slot_buttons_fit_318px():
    """AC: a slot's action buttons stay inside the 318 px width (slot row wraps or shrinks: no fixed widths summing past the view, `min-width: 0` on flexible children)."""
    css = _read(EXT_CSS)
    assert _rules_for(css, ".slot").get("display") == "flex"
    assert _rules_for(css, ".slot button").get("width") == "auto"
    assert _rules_for(css, ".slot .empty").get("flex") == "1"
    assert _rules_for(css, ".slot .num").get("width") == "14px"
    assert "flex:1;min-width:0" in _js_function(_read(PANEL_JS), "renderRoster")


def test_render_roster_preserves_scroll_position():
    """AC: after activating, deactivating or swapping, the Roster view keeps its scroll position — `renderRoster` saves and restores `scrollTop` around the re-render."""
    js = _read(PANEL_JS)
    body = _js_function(js, "renderRoster")
    save = body.index("var top = view.scrollTop;")
    assert body.index('var view = el("view-roster");') < save
    assert save < body.index("list.innerHTML") < body.rindex("view.scrollTop = top;")
    show = _js_function(js, "showView")
    assert 'state.scrollTops[prev] = el("view-" + prev).scrollTop' in show
    assert 'el("view-" + name).scrollTop = state.scrollTops[name] || 0' in show
    assert 'TAB_VIEWS = ["live", "cards", "roster"]' in js
    assert 'showView("roster")' in _js_function(js, "finishRosterChange")


def test_render_roster_does_not_reset_scroll_to_top():
    """Failure path: roster re-renders after an action do not jump to the top (no unconditional `scrollTop = 0` / `scrollTo(0, 0)` in `renderRoster` or the action handlers)."""
    js = _read(PANEL_JS)
    for fn in ("renderRoster", "finishRosterChange", "placeCard", "renderAll", "loadMe"):
        body = _js_function(js, fn)
        assert not re.search(r"scrollTop\s*=\s*0\b", body), fn
        assert "scrollTo(" not in body and "scrollIntoView" not in body, fn
    bench = js[js.index('el("btn-bench-it").addEventListener'):]
    bench = bench[:bench.index("});") + 3]
    assert "scrollTop" not in bench and "scrollTo(" not in bench


# ---------------------------------------------------------------------------
# Story 4 — Viewers Can See There Is More
# ---------------------------------------------------------------------------

def test_scroll_areas_have_thin_themed_scrollbar():
    """AC: `.view` and `.team-list` (and other scroll areas) set `scrollbar-width: thin`, `scrollbar-color` using `var(--…)` tokens, and `::-webkit-scrollbar` / `::-webkit-scrollbar-thumb` rules using the extension's colour tokens."""
    css = _read(EXT_CSS)
    for sel in _SCROLL_SELECTORS:
        d = _rules_for(css, sel)
        assert d.get("scrollbar-width") == "thin", sel
        assert re.match(r"^var\(--k-ink-\d+\) transparent$", d.get("scrollbar-color", "")), sel
        assert _rules_for(css, sel + "::-webkit-scrollbar").get("width") == "8px", sel
        assert _rules_for(css, sel + "::-webkit-scrollbar-thumb").get("background", "").startswith("var(--k-ink-"), sel


def test_scrollable_views_are_keyboard_focusable():
    """AC: scrolling works with mouse wheel, touch and keyboard — each scrollable view in panel.html has `tabindex="0"` or contains focusable content."""
    html = _read(PANEL_HTML)
    for vid in ("view-live", "view-cards", "view-roster", "view-settings"):
        assert 'tabindex="0"' in _section_tag(html, vid), vid
    for vid in ("view-teams", "view-picker"):
        assert "<button" in _section(html, vid), vid
    js = _read(PANEL_JS)
    assert 'document.createElement("button")' in _js_function(js, "renderTeams")
    assert '<button type="button" class="pick"' in _js_function(js, "renderPicker")


def test_views_keep_right_padding_for_scrollbar():
    """AC: no text sits under the scrollbar — `.view` keeps a right padding at least as wide as the scrollbar (or uses `scrollbar-gutter: stable`)."""
    css = _read(EXT_CSS)
    pad = _rules_for(css, ".view").get("padding", "").split()
    assert len(pad) == 3, pad
    right = int(pad[1].rstrip("px"))
    bar = int(_rules_for(css, ".view::-webkit-scrollbar")["width"].rstrip("px"))
    assert right >= bar


def test_scrollbar_colours_not_hardcoded():
    """Failure path: scrollbar rules use the extension's colour tokens, not hard-coded hex/rgb values, and the scrollbar is not hidden (`scrollbar-width: none` / `display: none` on `::-webkit-scrollbar` absent)."""
    css = _read(EXT_CSS)
    found = 0
    for sel, block in _css_rules(css):
        if "scrollbar" not in sel and "scrollbar" not in block:
            continue
        found += 1
        d = _decls(block)
        for prop in ("scrollbar-color", "background", "background-color"):
            assert not _HARD_COLOUR.search(d.get(prop, "")), (sel, prop)
        assert d.get("scrollbar-width") != "none", sel
        assert d.get("display") != "none", sel
        assert d.get("width") not in ("0", "0px"), sel
    assert found >= 4


# ---------------------------------------------------------------------------
# Story 5 — Operators Set and Test the Panel Height
# ---------------------------------------------------------------------------

def test_extension_doc_prerequisites_has_panel_height_row():
    """AC: markdown/features/core/twitch-extension.md Prerequisites table has a Panel Height row: 500, the largest Twitch allows, with the panel still working at smaller heights."""
    doc = _read(EXT_DOC)
    table = doc[doc.index("### Prerequisites"):doc.index("### Step 1")]
    row = next(line for line in table.splitlines() if line.startswith("| **Panel Height**"))
    assert "**500**" in row and "largest Twitch allows" in row and "smaller heights" in row


def test_dev_harness_has_height_presets():
    """AC: twitch-extension/dev-harness.html offers panel-height presets 300, 400 and 500 px and keeps the 318 px width."""
    html = _read(DEV_HARNESS)
    for h in ("300", "400", "500"):
        assert 'data-panel-height="' + h + '"' in html and "setPanelHeight(" + h + ")" in html, h
    assert "var PANEL_WIDTH = 318;" in html
    assert re.search(r"#frame-panel\s*\{[^}]*width:\s*318px", html)
    m = re.search(r"function setPanelHeight\(h\)\s*\{(.*?)\n\}", html, re.S)
    assert m and 'frame.style.width  = PANEL_WIDTH + "px"' in m.group(1) and 'h + "px"' in m.group(1)


def test_docs_describe_up_to_500px_tall():
    """AC: the docs say "318 px wide, up to 500 px tall (the version's Panel Height)" (twitch-extension.md, policy-compliance doc, ui_description/twitch-panel.md as applicable)."""
    phrase = "318 px wide, up to 500 px tall (the version's Panel Height)"
    for path in (EXT_DOC, POLICY_DOC, UI_DOC):
        assert phrase in _read(path), path
    assert "twitch-extension-policy-compliance.md#panel)" in _read(EXT_DOC)
    assert re.search(r"^## Panel$", _read(POLICY_DOC), re.M)


def test_package_sh_prints_panel_height_reminder(tmp_path):
    """AC: package.sh output reminds the operator of "Panel Height: 500" alongside the Asset Hosting paths."""
    src = _read(PACKAGE_SH)
    assert src.index("Live Config Path:") < src.index("Panel Height: 500")
    if shutil.which("zip") is None:
        pytest.skip("zip is not installed")
    ext = tmp_path / "twitch-extension"
    shutil.copytree(EXT_DIR, ext, ignore=shutil.ignore_patterns("*.zip"))
    result = subprocess.run(["bash", str(ext / "package.sh"), "9.9.9", "--ebs-origin", "https://fantasy.example.org"],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert out.index("Asset Hosting:") < out.index("Panel Viewer Path:") < out.index("Panel Height: 500")


def test_docs_no_longer_say_318_x_500():
    """Failure path: no doc under markdown/features/ or markdown/ui_description/ still describes the panel as a fixed "318 × 500" (or "318x500") frame."""
    bad = re.compile(r"318\s*[×xX]\s*500")
    hits = []
    for root in (REPO_ROOT / "markdown" / "features", REPO_ROOT / "markdown" / "ui_description"):
        for path in root.rglob("*.md"):
            for n, line in enumerate(_read(path).splitlines(), 1):
                if bad.search(line):
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{n}")
    assert hits == []
    assert "panel-318--500" not in _read(EXT_DOC)
