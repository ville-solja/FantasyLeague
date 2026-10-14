"""
Tests for plan-my-team-remove-move-buttons.md (resolves GitHub issue #93).

This is a frontend-only change to `_cardSlotHTML()` in `frontend/app-roster.js`:
removes the ◀/▶ move-left/move-right buttons and the Bench/Activate text
buttons from every My Team card slot, removes the now-dead
`moveCardInZone()` helper, and repurposes the card image's Enter/Space
keyboard handler to call a new `toggleCardZone(cardId, isActiveCard)`
function (toggling bench/active via the existing `activateCard()` /
`deactivateCard()`) instead of opening the detail modal. Mouse click on the
card image is unchanged and still opens the modal via `showRosterCard()`.
`markdown/features/reference/my-team-drag-and-drop.md` already documents the
finished design in a "Button Removal (issue #93) *(planned)*" section.

Every stub below fails with "not yet implemented" until the developer
implements the plan. All stubs are file-content assertions against
`frontend/app-roster.js` (there is no backend endpoint or DB surface for
this change) plus one doc-content stub, mirroring the pattern used in
`test_issue_89_fix_available_draws_count.py` and the frontend-stub section
of `test_multi_admin_support.py`.

  Story: Decluttered Card Slot Controls
    - The ◀/▶ move-left/move-right buttons are removed from every card slot
      (active and bench)
    - The now-dead `moveCardInZone()` helper is removed entirely (nothing
      calls it once the buttons are gone)
    - The Bench/Activate text buttons are removed from every card slot
    - Card slots show only the card image, points value, and modifier
      pills; the `.card-slot-actions` wrapper is gone
    - Locked-week card slots are unaffected (they never showed these
      buttons — `_cardSlotHTML()` renders no action buttons regardless of
      lock state, before or after this change)
    - The feature doc's "Button Removal (issue #93)" section is updated to
      reflect the finished state (no longer marked `*(planned)*`)

  Story: Keyboard Fallback for Bench/Active Toggle
    - Focusing a card slot's image and pressing Enter or Space calls the new
      `toggleCardZone(cardId, isActiveCard)` instead of `showRosterCard()`
    - `toggleCardZone()` reuses the existing `activateCard()` /
      `deactivateCard()` functions (and therefore their existing error
      handling) rather than introducing new error copy
    - The toggle does nothing when `_rosterLocked` is true, matching
      drag-and-drop's existing lock gating
    - Mouse click on the card image is unchanged and still calls
      `showRosterCard(cardId)` via `onclick`

Run with: cd backend && python -m pytest tests/test_my_team_remove_move_buttons.py -v
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
APP_ROSTER_JS_PATH = os.path.join(FRONTEND_DIR, "app-roster.js")
DRAG_AND_DROP_DOC_PATH = os.path.join(
    REPO_ROOT, "markdown", "features", "reference", "my-team-drag-and-drop.md"
)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_function(js, name):
    """Return the full source of a top-level `async function {name}() { ... }`
    or `function {name}() { ... }` block, matched by brace-depth counting so
    nested braces inside the function body don't truncate the match."""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", js)
    assert m, f"{name}() not found in source"
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
        i += 1
    return js[start:i - 1]


# ---------------------------------------------------------------------------
# Story: Decluttered Card Slot Controls
# ---------------------------------------------------------------------------

class TestDeclutteredCardSlotControls:

    def test_move_left_right_buttons_removed_from_card_slot_html(self):
        """The ◀/▶ move-left/move-right buttons (`card-slot-btn--move`,
        `moveCardInZone(...)` onclick handlers) are removed from every card
        slot rendered by `_cardSlotHTML()`, active and bench alike."""
        js = _read(APP_ROSTER_JS_PATH)
        fn = _extract_function(js, "_cardSlotHTML")
        assert "card-slot-btn--move" not in fn
        assert "moveCardInZone" not in fn
        assert "&#x25C0;" not in fn and "&#x25B6;" not in fn

    def test_move_card_in_zone_function_no_longer_defined(self):
        """`moveCardInZone(cardId, direction)` is removed entirely from
        `frontend/app-roster.js` — no function definition and no remaining
        caller, since it becomes dead code once the ◀/▶ buttons are gone."""
        js = _read(APP_ROSTER_JS_PATH)
        assert re.search(r"function\s+moveCardInZone\s*\(", js) is None
        assert "moveCardInZone" not in js

    def test_bench_activate_buttons_removed_from_card_slot_html(self):
        """The Bench/Activate text buttons (`card-slot-btn` with
        `deactivateCard(...)` / `activateCard(...)` onclick handlers) are
        removed from every card slot rendered by `_cardSlotHTML()`."""
        js = _read(APP_ROSTER_JS_PATH)
        fn = _extract_function(js, "_cardSlotHTML")
        assert re.search(r'class="[^"]*card-slot-btn[^"]*"', fn) is None
        assert "deactivateCard(" not in fn
        assert "activateCard(" not in fn
        assert "<button" not in fn

    def test_card_slot_html_retains_image_and_points_only(self):
        """`_cardSlotHTML()`'s output still includes the card image
        (`card-img`) and points value (`card-slot-pts`), no longer includes a
        `.card-slot-actions` wrapper div, and no longer renders modifier pills
        (`card-slot-mods`) either — modifier values are already readable on
        the card image itself, so a separate text rendering is duplicate
        information."""
        js = _read(APP_ROSTER_JS_PATH)
        fn = _extract_function(js, "_cardSlotHTML")
        assert "card-img" in fn
        assert "card-slot-pts" in fn
        assert "card-slot-mods" not in fn
        assert "card-slot-actions" not in fn

    def test_locked_week_card_slot_has_no_action_buttons(self):
        """`_cardSlotHTML()` called with `action=null` (the locked-week /
        no-action case) renders no Bench/Activate button and no ◀/▶ move
        buttons, matching the pre-change behavior where locked slots never
        showed these controls — i.e. this change does not alter behavior
        for the already-correct locked case."""
        js = _read(APP_ROSTER_JS_PATH)
        fn = _extract_function(js, "_cardSlotHTML")
        # No buttons are ever emitted now, regardless of the `action` value,
        # so the locked (action=null) case trivially has none either.
        assert "<button" not in fn
        assert "card-slot-actions" not in fn

    def test_doc_button_removal_section_no_longer_marked_planned(self):
        """`markdown/features/reference/my-team-drag-and-drop.md`'s "Button
        Removal (issue #93)" section reflects the finished implementation
        (the `*(planned)*` marker is removed) once the change is shipped."""
        doc = _read(DRAG_AND_DROP_DOC_PATH)
        m = re.search(r"## Button Removal \(issue #93\)([^\n]*)", doc)
        assert m, "Button Removal (issue #93) section heading not found"
        assert "(planned)" not in m.group(1)


# ---------------------------------------------------------------------------
# Story: Keyboard Fallback for Bench/Active Toggle
# ---------------------------------------------------------------------------

class TestKeyboardFallbackForBenchActiveToggle:

    def test_card_image_onkeydown_calls_toggle_card_zone(self):
        """Enter/Space on a focused card image calls `toggleCardZone(cardId)`
        instead of `showRosterCard(cardId)`. Issue #186: the handler is delegated
        to the grids (`_onRosterKeyDown`), so it is no longer an inline
        `onkeydown` in `_cardSlotHTML()`; the image stays focusable."""
        js = _read(APP_ROSTER_JS_PATH)
        fn = _extract_function(js, "_onRosterKeyDown")
        assert 'e.key !== "Enter" && e.key !== " "' in fn
        assert "toggleCardZone(" in fn
        assert "showRosterCard(" not in fn
        assert 'grid.addEventListener("keydown", _onRosterKeyDown);' in js
        slot = _extract_function(js, "_cardSlotHTML")
        assert 'tabindex="0" role="button"' in slot
        assert re.search(r"(?:async\s+)?function\s+toggleCardZone\s*\(", js), \
            "toggleCardZone() not defined top-level"

    def test_toggle_card_zone_calls_activate_or_deactivate_card(self):
        """Issue #186: `toggleCardZone(cardId)` moves a roster card to the front of
        the bench and a bench card to the first free roster slot through the
        local layout (`_rosterMove` + `_commitRosterLayout`), the same path as a
        drop, with no single-card route call. The rule messages come from the
        shared rule check, not new copy in the function."""
        js = _read(APP_ROSTER_JS_PATH)
        fn = _extract_function(js, "toggleCardZone")
        assert "_rosterMove(_layout, cardId, target)" in fn
        assert "_commitRosterLayout(res && res.layout)" in fn
        assert "/roster/" not in fn and "fetch(" not in fn
        assert "className" not in fn
        assert "textContent" not in fn

    def test_toggle_card_zone_gated_on_roster_locked(self):
        """Pressing Enter/Space on a card image does nothing when
        `_rosterLocked` is true, matching the drag's lock gating."""
        js = _read(APP_ROSTER_JS_PATH)
        fn = _extract_function(js, "toggleCardZone")
        assert "if (_rosterLocked || _drag) return;" in fn
        guard_idx = fn.index("_rosterLocked")
        assert guard_idx < fn.index("_rosterMove(")
        assert "if (_rosterLocked || _drag) return;" in _extract_function(js, "_onRosterPointerDown")

    def test_card_image_onclick_still_calls_show_roster_card_unchanged(self):
        """A click on a card still opens the card detail modal with
        `showRosterCard(cardId)`; the click that ends a drag doesn't. Issue #186:
        delegated to the grids (`_onRosterClick`) instead of an inline onclick."""
        js = _read(APP_ROSTER_JS_PATH)
        fn = _extract_function(js, "_onRosterClick")
        assert "if (_rosterSuppressClick) return;" in fn
        assert "showRosterCard(parseInt(node.dataset.cardId, 10))" in fn
        assert 'grid.addEventListener("click", _onRosterClick);' in js
        assert "onclick=" not in _extract_function(js, "_cardSlotHTML")

