"""Readability floor for the Weekly Report and its recap popup.

Static checks on frontend/style.css and frontend/colors_and_type.css, so small or
low-contrast text doesn't drift back into the report:

- no font size below --fs-xs (11px) in any Weekly Report rule;
- Big Shoulders (--font-display) only at --fs-sm (13px) and up;
- --fg-dim (3.2:1 on cards, below WCAG AA for small text) is never a text colour,
  except for the transient pending-chip placeholder;
- points use tabular numerals;
- the --fs-* tokens are rem, so the browser's font-size setting applies.
"""
import os
import re

import pytest

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

# Rules that belong to the Weekly Report popup, its roster panel, the reveal
# animation and the "recap is ready" prompt.
_REPORT_SELECTOR = re.compile(r"weekly-summary|weekly-recap|recap-")

# --fs-* token sizes in px at the default 16px root.
_TOKEN_PX = {"xs": 11, "sm": 13, "base": 15, "md": 17, "lg": 20, "xl": 26,
             "2xl": 36, "3xl": 52, "4xl": 72, "hero": 112}

# --fg-dim as a text colour is allowed only for this placeholder state.
_FG_DIM_TEXT_ALLOWED = {".recap-chip.pending"}


def _read(name):
    with open(os.path.join(FRONTEND, name), encoding="utf-8") as fh:
        return fh.read()


def _report_rules():
    """[(selector, body)] for every rule whose selector names a report class,
    including rules inside @media blocks."""
    css = re.sub(r"/\*.*?\*/", "", _read("style.css"), flags=re.S)
    rules = []
    for m in re.finditer(r"([^{}@;]+)\{([^{}]*)\}", css):
        selector = " ".join(m.group(1).split())
        if _REPORT_SELECTOR.search(selector):
            rules.append((selector, m.group(2)))
    return rules


def _font_size_px(value):
    """Font size in px for a CSS value, or None when it isn't a fixed size
    (inherit, a calc, a percentage)."""
    value = value.strip()
    m = re.fullmatch(r"var\(--fs-([a-z0-9]+)\)", value)
    if m:
        return _TOKEN_PX.get(m.group(1))
    m = re.fullmatch(r"([0-9.]+)(px|rem|em)", value)
    if m:
        n = float(m.group(1))
        return n if m.group(2) == "px" else n * 16
    return None


def _decls(body):
    return {k.strip(): v.strip()
            for k, v in (d.split(":", 1) for d in body.split(";") if ":" in d)}


class TestWeeklyReportReadability:
    def test_report_rules_found(self):
        """The selector filter finds the report's rules (guards the other tests
        against passing vacuously)."""
        selectors = [s for s, _ in _report_rules()]
        assert any(".weekly-summary-game" in s for s in selectors)
        assert any(".recap-chip" in s for s in selectors)
        assert any(".weekly-recap-prompt" in s for s in selectors)

    def test_no_font_size_below_11px(self):
        """Every fixed font size in a Weekly Report rule is at least 11px."""
        too_small = []
        for selector, body in _report_rules():
            size = _decls(body).get("font-size")
            if size is None:
                continue
            px = _font_size_px(size)
            if px is not None and px < 11:
                too_small.append(f"{selector}: {size}")
        assert not too_small, too_small

    def test_display_font_only_at_13px_and_up(self):
        """A rule that sets Big Shoulders (--font-display) uses at least --fs-sm."""
        offenders = []
        for selector, body in _report_rules():
            decls = _decls(body)
            if "var(--font-display)" not in decls.get("font-family", ""):
                continue
            px = _font_size_px(decls.get("font-size", ""))
            if px is not None and px < 13:
                offenders.append(f"{selector}: {decls.get('font-size')}")
        assert not offenders, offenders

    def test_fg_dim_is_not_a_text_colour(self):
        """--fg-dim is used for borders and placeholders, not readable text
        (border-color and the like are fine)."""
        offenders = []
        for selector, body in _report_rules():
            if selector in _FG_DIM_TEXT_ALLOWED:
                continue
            if re.search(r"(^|[;\s])color\s*:\s*var\(--fg-dim\)", body):
                offenders.append(selector)
        assert not offenders, offenders

    @pytest.mark.parametrize("selector", [
        ".weekly-summary-game-pts",
        ".weekly-summary-roster-pts",
        ".weekly-summary-points-neutral",
        ".weekly-summary-points-rostered",
        ".recap-chip",
    ])
    def test_points_use_tabular_numerals(self, selector):
        """Points line up: their rules set tabular numerals."""
        bodies = [b for s, b in _report_rules() if s == selector]
        assert bodies, f"no rule for {selector}"
        assert any("tabular-nums" in b for b in bodies)

    def test_subbed_out_card_is_not_faded(self):
        """The "did not play" card isn't faded with opacity on top of muted text."""
        bodies = [b for s, b in _report_rules()
                  if s == ".weekly-summary-roster-card.subbed-out"]
        assert bodies
        assert all("opacity" not in b for b in bodies)

    def test_font_size_tokens_are_rem(self):
        """--fs-* tokens are rem (equal to their px sizes at a 16px root), so the
        browser's font-size setting scales the text."""
        css = _read("colors_and_type.css")
        for name, px in _TOKEN_PX.items():
            m = re.search(rf"--fs-{re.escape(name)}:\s*([0-9.]+)rem\s*;", css)
            assert m, f"--fs-{name} is not in rem"
            assert float(m.group(1)) * 16 == pytest.approx(px)

    def test_design_tokens_copy_matches_frontend(self):
        """design/colors_and_type.css (read by the design tooling) stays in step
        with the frontend copy."""
        design = os.path.join(FRONTEND, "..", "design", "colors_and_type.css")
        if not os.path.exists(design):
            pytest.skip("design/ not present")
        with open(design, encoding="utf-8") as fh:
            assert fh.read() == _read("colors_and_type.css")
