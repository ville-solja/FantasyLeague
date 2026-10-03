"""
Tests for plan-issue-153-tour-weekly-report (resolves GitHub issue #153).

The guided tour of My Team (#144, `frontend/app-tour.js`) gains one step on the
header's Weekly Report button (`#weeklyReportBtn`), between the "Points" step
(`#rosterTotals`) and the "Leaderboards" step (`#tab-btn-leaderboard`), so the
full tour has 7 steps. When the tour closes, `endTour()` calls
`checkWeeklySummaryHighlight()` (from `frontend/app-weekly-summary.js`) so the
"recap is ready" popup appears right away if a recap is waiting.

Frontend only: every criterion is checked statically against
`frontend/app-tour.js`, `frontend/app-weekly-summary.js` and
`frontend/index.html`, in the style of test_issue_144_guided_tour.py (helpers
`_read`, `_js_function`, `_step_objects`, `_selector_in_html` are reused from
that module when implemented).

Needs a real browser, so covered statically or listed as manual (see the
plan's Verification section):
  - step counter shows "6 / 7" on this step: covered statically by the step's
    index (5) in a 7-step list; the rendered counter is manual. (The plan
    first said "5 / 7"; counting the list, Weekly Report is the sixth step.)
  - box positioned below the header button and kept inside the viewport (16 px
    margin) at desktop and 375 px: manual (existing positioning logic, no new
    code).
  - the step highlights the button and does not open the report: covered
    statically (the step literal has no action/onShow hook and app-tour.js never
    calls the report opener); the visual spotlight is manual.
  - a hidden/missing `#weeklyReportBtn` drops the step: covered statically by
    `startTour` still filtering with `_tourTargetVisible`; runtime is manual.
  - focus returns to the page on close, or moves to the popup's "Open recap"
    button when the popup appears: covered statically by the call order in
    `endTour()`; actual focus is manual.

Stories:
  1. Weekly Report Step in the Tour
  2. Recap Popup After the Tour
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re

import pytest

from tests.test_issue_144_guided_tour import (
    _js_function,
    _read,
    _selector_in_html,
    _step_objects,
)

_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
_REPO_DIR = os.path.join(_BACKEND_DIR, "..")
_FRONTEND_DIR = os.path.join(_REPO_DIR, "frontend")

TOUR_JS_PATH = os.path.join(_FRONTEND_DIR, "app-tour.js")
WEEKLY_SUMMARY_JS_PATH = os.path.join(_FRONTEND_DIR, "app-weekly-summary.js")
INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")

WEEKLY_REPORT_TARGET = "#weeklyReportBtn"
WEEKLY_REPORT_TITLE = "Weekly Report"
WEEKLY_REPORT_BODY = (
    "After each week ends, your recap is here: what each card scored, game by "
    "game, and every match result. A popup tells you when a new one is ready."
)

SEVEN_TARGETS = [
    "#drawBtn",
    ".rarity-grid",
    "#rosterActiveGrid",
    "#rosterWeekSelect",
    "#rosterTotals",
    "#weeklyReportBtn",
    "#tab-btn-leaderboard",
]


def _steps():
    return _step_objects(_read(TOUR_JS_PATH))


def _targets():
    return [t for t, _, _ in _steps()]


def _weekly_step():
    matches = [s for s in _steps() if s[0] == WEEKLY_REPORT_TARGET]
    assert len(matches) == 1, matches
    return matches[0]


def _end_tour():
    return _js_function(_read(TOUR_JS_PATH), "endTour")


RECAP_GUARD = 'if (activeUserId && typeof checkWeeklySummaryHighlight === "function") {'


# ---------------------------------------------------------------------------
# Story 1 — Weekly Report Step in the Tour
# ---------------------------------------------------------------------------

class TestWeeklyReportStepInTour:

    def test_my_team_tour_steps_has_weekly_report_step(self):
        """myTeamTourSteps() in frontend/app-tour.js has a step with target "#weeklyReportBtn" (via _step_objects)."""
        assert WEEKLY_REPORT_TARGET in _targets()

    def test_weekly_report_step_title_and_exact_body_copy(self):
        """The #weeklyReportBtn step's title is "Weekly Report" and its body is exactly "After each week ends, your recap is here: what each card scored, game by game, and every match result. A popup tells you when a new one is ready." """
        _, title, body_src = _weekly_step()
        assert title == WEEKLY_REPORT_TITLE
        assert body_src == '"' + WEEKLY_REPORT_BODY + '"'

    def test_weekly_report_step_between_points_and_leaderboards(self):
        """The #weeklyReportBtn step comes directly after the "Points" step (#rosterTotals) and directly before the "Leaderboards" step (#tab-btn-leaderboard)."""
        targets = _targets()
        titles = [title for _, title, _ in _steps()]
        i = targets.index(WEEKLY_REPORT_TARGET)
        assert targets[i - 1] == "#rosterTotals" and titles[i - 1] == "Points"
        assert targets[i + 1] == "#tab-btn-leaderboard" and titles[i + 1] == "Leaderboards"

    def test_my_team_tour_has_seven_steps_in_order(self):
        """The full step list has 7 targets in order: #drawBtn, .rarity-grid, #rosterActiveGrid, #rosterWeekSelect, #rosterTotals, #weeklyReportBtn, #tab-btn-leaderboard; #weeklyReportBtn is at index 5, so the counter reads "6 / 7" when every step is visible."""
        targets = _targets()
        assert targets == SEVEN_TARGETS
        assert len(targets) == 7
        # Sixth step: the counter reads "6 / 7" when every step is visible.
        assert targets.index(WEEKLY_REPORT_TARGET) == 5

    def test_weekly_report_btn_exists_in_index_html(self):
        """`#weeklyReportBtn` exists as an element id in frontend/index.html (via _selector_in_html)."""
        assert _selector_in_html(_read(INDEX_HTML_PATH), WEEKLY_REPORT_TARGET)

    def test_weekly_report_step_highlights_without_opening_report(self):
        """The #weeklyReportBtn step literal is a plain {target, title, body} object with no action/onShow hook, and app-tour.js never calls the Weekly Report opener (the step highlights the button; it doesn't open the report)."""
        js = _read(TOUR_JS_PATH)
        fn = _js_function(js, "myTeamTourSteps")
        m = re.search(r'\{\s*target:\s*"#weeklyReportBtn",.*?\n    \}', fn, re.S)
        assert m, "Weekly Report step literal not found"
        literal = m.group(0)
        assert set(re.findall(r"^\s+(\w+):", literal, re.M)) == {"target", "title", "body"}
        assert "openWeeklySummary" not in js

    def test_start_tour_filters_hidden_targets_with_tour_target_visible(self):
        """Failure path: startTour still filters steps with _tourTargetVisible, so a missing or hidden #weeklyReportBtn drops the step and the counter counts only the remaining steps."""
        fn = _js_function(_read(TOUR_JS_PATH), "startTour")
        assert ".filter(s => _tourTargetVisible(document.querySelector(s.target)))" in fn


# ---------------------------------------------------------------------------
# Story 2 — Recap Popup After the Tour
# ---------------------------------------------------------------------------

class TestRecapPopupAfterTour:

    def test_end_tour_calls_check_weekly_summary_highlight(self):
        """endTour() in frontend/app-tour.js calls checkWeeklySummaryHighlight() so the "recap is ready" popup can appear when the tour closes (Done, Skip, Esc or backdrop click all route through endTour)."""
        assert "checkWeeklySummaryHighlight();" in _end_tour()

    def test_end_tour_recap_check_guarded_by_active_user_and_typeof(self):
        """The call sits inside `if (activeUserId && typeof checkWeeklySummaryHighlight === "function")`, so a logged-out user makes no GET /weekly-summary request (failure path)."""
        fn = _end_tour()
        guard = fn.index(RECAP_GUARD)
        call = fn.index("checkWeeklySummaryHighlight();")
        assert guard < call
        # The call is the only statement inside the guard.
        assert fn[guard + len(RECAP_GUARD):call].strip() == ""
        assert fn.count("checkWeeklySummaryHighlight();") == 1

    def test_end_tour_recap_check_after_tour_cleared_and_marked_seen(self):
        """In endTour(), the checkWeeklySummaryHighlight() call comes after `_tour = null` and `_markTourSeen()` (and after focus is restored), so the tour no longer counts as open and fantasy.tourSeen.v1 is still written."""
        fn = _end_tour()
        call = fn.index("checkWeeklySummaryHighlight();")
        assert fn.index("_tour = null;") < call
        assert fn.index("_markTourSeen();") < call
        assert fn.index("prev.focus(") < call

    def test_check_weekly_summary_highlight_fetches_and_calls_prompt(self):
        """checkWeeklySummaryHighlight() in frontend/app-weekly-summary.js fetches GET /weekly-summary and passes the result to maybeShowWeeklyRecapPrompt(data)."""
        fn = _js_function(_read(WEEKLY_SUMMARY_JS_PATH), "checkWeeklySummaryHighlight")
        assert "fetch(`${API}/weekly-summary`)" in fn
        assert "maybeShowWeeklyRecapPrompt(data);" in fn

    def test_maybe_show_weekly_recap_prompt_still_checks_tour(self):
        """maybeShowWeeklyRecapPrompt still checks `_tour`, so the popup doesn't open while a tour is running."""
        fn = _js_function(_read(WEEKLY_SUMMARY_JS_PATH), "maybeShowWeeklyRecapPrompt")
        assert "if (typeof _tour !== 'undefined' && _tour) return;" in fn

    def test_maybe_show_weekly_recap_prompt_keeps_existing_guards(self):
        """Failure path: maybeShowWeeklyRecapPrompt still returns early when show_prompt is false, another popup is open, or a password change is required, so nothing appears when no recap is waiting."""
        fn = _js_function(_read(WEEKLY_SUMMARY_JS_PATH), "maybeShowWeeklyRecapPrompt")
        assert "if (!data || !data.show_prompt || !data.latest_week) return;" in fn
        assert "if (_weeklyRecapOtherOverlayOpen()) return;" in fn
        assert "if (activeMustChangePassword) return;" in fn
        # Every guard returns before the popup is shown.
        assert fn.index("activeMustChangePassword") < fn.index("classList.remove('hidden')")
