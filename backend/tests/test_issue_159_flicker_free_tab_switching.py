"""
Tests for plan-issue-159-flicker-free-tab-switching.md (resolves GitHub issue #159).

Switching tabs must not flash. A new helper `renderIfChanged(el, html)` in
`frontend/app-globals.js` (backed by a `WeakMap` of the last markup it set per element)
skips DOM writes when the markup is unchanged; the main loaders use it, placeholders
show only on an empty container, errors keep existing content and week selects keep
their value. `switchTab(name)` gets a same-tab branch (quiet refresh, no class toggling
or scrolling) and per-tab scroll memory (`_tabScroll`), keeping the forced password
change redirect first. The Weekly Report popup gets a fixed frame
(`.weekly-summary-modal { height: 85vh }`, `92vh` at 600 px), a keep-and-dim week
switch (`.weekly-summary-col-body.is-loading`, `aria-busy`), a request counter
(`_weeklySummaryReq`), a per-opening week cache (`_weeklySummaryCache`) and an in-place
tab bar in `renderWeeklySummaryTabs()`.

  Story 1: No Flicker When Switching Tabs      (TestNoFlickerWhenSwitchingTabs)
  Story 2: Same Tab or a Different Tab         (TestSameTabOrDifferentTab)
  Story 3: Weekly Report Keeps Its Frame       (TestWeeklyReportKeepsItsFrame)

Approach notes for the implementer:

- Frontend only: every criterion is a static text check of `frontend/*.js` and
  `frontend/style.css`. Reuse `_read`, `_css_blocks`, `_css_rule`, `_media_body` and
  `_fn_body` from test_issue_151_weekly_report_aesthetics.py, e.g.
  `from tests.test_issue_151_weekly_report_aesthetics import _read, _css_rule, ...`
  (import only underscore names so pytest does not collect #151 twice;
  lessons-learned 2026-10-03). `_fn_body` matches `function name(`, so it also finds
  `async function name(`.
- Loader locations: app-roster.js (loadRoster, loadWeeks), app-cards.js (loadDeck,
  loadBoosterTeams), app-leaderboard.js (loadSeasonLeaderboard, loadWeeklyLeaderboard,
  loadPastSeasons, _populateLbWeekSelect, loadLeaderboard, loadTop), app-players.js
  (loadPlayers, loadTeams, loadSchedule).
- Media queries in style.css: `max-width: 1100px`, `max-width: 600px`,
  `prefers-reduced-motion: reduce` (there are several reduced-motion blocks; search all
  of them, not only the first `_media_body` match).
- Update the #151 / #152 tests if they pin `max-height: 85vh` as the only height or the
  old unconditional "Loading…" write in `selectWeeklySummaryTab`, and bump the
  suite-size check in tests/test_issue_85_split_admin_router.py once these pass.
- Optional: if `node` is on PATH (`shutil.which("node")`), a small behaviour test can
  extract `renderIfChanged` (and the `_lastHtml` WeakMap) from app-globals.js, run it
  under Node with a fake element object (`{innerHTML: ""}` plus a setter counter) and
  assert: first call writes and returns true, an identical second call returns false
  without touching `innerHTML`, changed html writes again, a cleared element
  (`innerHTML = ""`) is rewritten, and `null` returns false. Skip with
  `pytest.skip` when node is missing. Not required; the static checks below suffice.

Manual-only (need a real browser, see the plan's Verification section): no visible
flash when switching tabs, card images not reloaded on an unchanged refresh (DevTools
Network tab), scroll position restored per tab, Weekly Report frame not moving and the
last-clicked week winning during rapid week switching, revealed week showing fresh
data with the recap animation playing once, narrow-screen (375 px) behaviour.

Run with: cd backend && python3 -m pytest tests/test_issue_159_flicker_free_tab_switching.py -v
"""

import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _css_rule, _fn_body, _read

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_APP_GLOBALS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-globals.js")
_APP_ROSTER_JS_PATH = os.path.join(_FRONTEND_DIR, "app-roster.js")
_APP_CARDS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-cards.js")
_APP_LEADERBOARD_JS_PATH = os.path.join(_FRONTEND_DIR, "app-leaderboard.js")
_APP_PLAYERS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-players.js")
_APP_WEEKLY_SUMMARY_JS_PATH = os.path.join(_FRONTEND_DIR, "app-weekly-summary.js")
_STYLE_CSS_PATH = os.path.join(_FRONTEND_DIR, "style.css")

# (file, loader) pairs that must render their main blocks through renderIfChanged.
_LOADERS = [
    (_APP_ROSTER_JS_PATH, "loadRoster"),
    (_APP_ROSTER_JS_PATH, "loadWeeks"),
    (_APP_CARDS_JS_PATH, "loadDeck"),
    (_APP_CARDS_JS_PATH, "loadBoosterTeams"),
    (_APP_LEADERBOARD_JS_PATH, "loadSeasonLeaderboard"),
    (_APP_LEADERBOARD_JS_PATH, "loadWeeklyLeaderboard"),
    (_APP_LEADERBOARD_JS_PATH, "loadPastSeasons"),
    (_APP_LEADERBOARD_JS_PATH, "_populateLbWeekSelect"),
    (_APP_LEADERBOARD_JS_PATH, "loadLeaderboard"),
    (_APP_LEADERBOARD_JS_PATH, "loadTop"),
    (_APP_PLAYERS_JS_PATH, "loadPlayers"),
    (_APP_PLAYERS_JS_PATH, "loadTeams"),
    (_APP_PLAYERS_JS_PATH, "loadSchedule"),
]


# Render helpers a loader delegates its main block to (checked together with the loader).
_RENDER_HELPERS = {
    "loadWeeks": ["_renderWeekSelector"],
    "loadPlayers": ["renderPlayers", "_renderMvpLeaderboard"],
    "loadLeaderboard": ["_renderLeaderboard"],
    "loadPastSeasons": ["loadPastSeasonStandings"],
}

_INNERHTML_WRITE = re.compile(r"\.innerHTML\s*=(?!=)")


def _loader_src(path, loader):
    js = _read(path)
    return "\n".join(_fn_body(js, name) for name in [loader] + _RENDER_HELPERS.get(loader, []))


def _globals():
    return _read(_APP_GLOBALS_JS_PATH)


def _wsjs():
    return _read(_APP_WEEKLY_SUMMARY_JS_PATH)


def _css():
    return _read(_STYLE_CSS_PATH)


def _media_bodies(css, query):
    """Body of every `@media (query)` block (there can be several)."""
    bodies = []
    for m in re.finditer(re.escape(f"@media ({query})"), css):
        depth, i = 0, css.index("{", m.start())
        for j in range(i, len(css)):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    bodies.append(css[i + 1:j])
                    break
    assert bodies, query
    return bodies


def _rule_in(body, selector):
    """Body of the first rule in `body` whose selector list contains `selector`."""
    for sel, rule in _css_blocks(body, re.escape(selector)):
        if selector in [x.strip() for x in sel.split(",")]:
            return rule
    return None


def _node():
    return shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)


def _run_render_if_changed(steps_js):
    """Runs renderIfChanged (and its WeakMap) from app-globals.js under Node with a fake
    element that counts innerHTML writes; returns the printed JSON, or None without Node."""
    node = _node()
    if not node:
        return None
    js = _globals()
    decl = re.search(r"^const _lastHtml = new WeakMap\(\);$", js, re.M).group(0)
    script = decl + "\n" + _fn_body(js, "renderIfChanged") + "\n}\n" + """
function fakeEl() {
  let html = "";
  return { writes: 0, get innerHTML() { return html; }, set innerHTML(v) { this.writes++; html = v; } };
}
""" + steps_js
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _switch_tab():
    return _fn_body(_globals(), "switchTab")


# ---------------------------------------------------------------------------
# Story 1: No Flicker When Switching Tabs
# ---------------------------------------------------------------------------

class TestNoFlickerWhenSwitchingTabs:

    def test_render_if_changed_defined_in_app_globals_with_weakmap(self):
        """app-globals.js defines `function renderIfChanged(el, html)` and keeps the last markup per element in a module-level `new WeakMap()`."""
        js = _globals()
        assert "function renderIfChanged(el, html)" in js
        assert re.search(r"^const _lastHtml = new WeakMap\(\);$", js, re.M)
        body = _fn_body(js, "renderIfChanged")
        assert "_lastHtml.get(el)" in body and "_lastHtml.set(el, html)" in body

    def test_render_if_changed_writes_first_time_and_returns_flag(self):
        """renderIfChanged sets `el.innerHTML` and stores html in the WeakMap when it differs (always on first sight of an element) and returns true; returns false when unchanged."""
        body = _fn_body(_globals(), "renderIfChanged")
        assert "el.innerHTML = html;" in body
        assert "return true;" in body and "return false;" in body
        assert body.index("_lastHtml.get(el) === html") < body.index("el.innerHTML = html;")
        result = _run_render_if_changed("""
const el = fakeEl();
const r = [renderIfChanged(el, "<b>a</b>"), el.writes,
           renderIfChanged(el, "<b>a</b>"), el.writes,
           renderIfChanged(el, "<b>b</b>"), el.writes, el.innerHTML];
console.log(JSON.stringify(r));
""")
        if result is not None:
            assert result == [True, 1, False, 1, True, 2, "<b>b</b>"]

    def test_render_if_changed_rewrites_cleared_element_and_ignores_null(self):
        """Failure path: renderIfChanged returns false for a missing element (`if (!el) return false`) and still writes when the stored html matches but `el.innerHTML === ""` (cleared elsewhere)."""
        body = _fn_body(_globals(), "renderIfChanged")
        assert "if (!el) return false;" in body
        assert 'el.innerHTML !== ""' in body
        result = _run_render_if_changed("""
const el = fakeEl();
renderIfChanged(el, "x");
el.innerHTML = "";
const before = el.writes;
const r = [renderIfChanged(el, "x"), el.writes - before, el.innerHTML,
           renderIfChanged(null, "x"), renderIfChanged(undefined, "x")];
console.log(JSON.stringify(r));
""")
        if result is not None:
            assert result == [True, 1, "x", False, False]

    @pytest.mark.parametrize("path,loader", _LOADERS, ids=[name for _, name in _LOADERS])
    def test_loader_uses_render_if_changed(self, path, loader):
        """Each loader (loadRoster, loadDeck, loadBoosterTeams, loadSeasonLeaderboard, loadWeeklyLeaderboard, loadPastSeasons, loadPlayers, loadLeaderboard, loadTop, loadTeams, loadSchedule, loadWeeks, _populateLbWeekSelect) calls `renderIfChanged(` for its main block instead of a bare `.innerHTML =` write."""
        src = _loader_src(path, loader)
        assert "renderIfChanged(" in src or "renderSelectIfChanged(" in src, loader
        assert not _INNERHTML_WRITE.search(src), loader

    def test_load_roster_renders_active_grid_bench_and_totals_with_render_if_changed(self):
        """loadRoster renders `#rosterActiveGrid`, `#benchGrid` and the totals through renderIfChanged, and listeners it attaches (e.g. drag-and-drop) still work when the DOM was not rewritten (re-attached unconditionally or delegated to a stable parent)."""
        js = _read(_APP_ROSTER_JS_PATH)
        body = _fn_body(js, "loadRoster")
        assert "const activeWrote = renderIfChanged(activeGrid," in body
        assert body.count("benchWrote = renderIfChanged(benchGrid,") == 3
        assert 'renderIfChanged(document.getElementById("rosterCombined"),' in body
        assert not _INNERHTML_WRITE.search(body)
        # Drag-and-drop is wired after every unlocked render, whether or not it wrote,
        # and the wiring is idempotent: kept slot nodes and the stable grids are bound once.
        assert "if (!isLocked) _initDragAndDrop();" in body
        dnd = _fn_body(js, "_initDragAndDrop")
        assert dnd.count("if (slot._dndBound) return;") == 2
        assert "if (activeGrid._dndBound) return;" in dnd
        # Handlers read the latest cards, not the ones captured at bind time.
        assert "const activeCards = _rosterActive;" in dnd and "const benchCards = _rosterBench;" in dnd
        assert "_rosterActive = active;" in body and "_rosterBench = bench;" in body
        # A locked view never reuses draggable nodes: draggable is part of the markup.
        slot = _fn_body(js, "_cardSlotHTML")
        assert "function _cardSlotHTML(c, action, draggable = false)" in slot
        assert 'draggable="true"' in slot
        assert 'slot.setAttribute("draggable", "true")' not in dnd
        # The settle animation runs only on grids that were redrawn.
        assert "activeWrote && activeGrid, benchWrote && benchGrid" in body

    def test_load_schedule_placeholder_only_when_container_empty(self):
        """loadSchedule writes its "Loading" text into `#scheduleContent` only behind an empty-content check; otherwise the old content stays until new data replaces it."""
        body = _fn_body(_read(_APP_PLAYERS_JS_PATH), "loadSchedule")
        assert 'const firstLoad = content.innerHTML.trim() === "";' in body
        assert "if (firstLoad) renderIfChanged(content, \"<span class='schedule-empty'>Loading...</span>\");" in body
        assert body.count("Loading") == 1

    def test_load_booster_teams_placeholder_only_when_container_empty(self):
        """loadBoosterTeams writes its "Loading" text into `#boosterTeamGrid` only behind an empty-content check; otherwise the old content stays until new data replaces it."""
        body = _fn_body(_read(_APP_CARDS_JS_PATH), "loadBoosterTeams")
        assert 'const firstLoad = grid.innerHTML.trim() === "";' in body
        assert "if (firstLoad) renderIfChanged(grid, '<span style=\"color:#555;font-size:0.85rem;\">Loading…</span>');" in body
        assert body.count("Loading") == 1
        # A kept tile loses the previous selection, matching the reset _selectedBoosterTeamId.
        assert 'grid.querySelectorAll(".booster-team-tile--selected")' in body

    def test_week_selects_preserve_selected_value(self):
        """loadWeeks and _populateLbWeekSelect remember `sel.value` before renderIfChanged and restore it afterwards when that option still exists."""
        g = _fn_body(_globals(), "renderSelectIfChanged")
        assert "const prev = sel.value;" in g
        assert "[...sel.options].some(o => o.value === prev)" in g and "sel.value = prev;" in g
        assert g.index("const prev = sel.value;") < g.index("renderIfChanged(sel, html)") < g.index("sel.value = prev;")
        lb = _read(_APP_LEADERBOARD_JS_PATH)
        assert "renderSelectIfChanged(sel," in _fn_body(lb, "_populateLbWeekSelect")
        assert "renderSelectIfChanged(sel," in _fn_body(lb, "loadPastSeasons")
        roster_js = _read(_APP_ROSTER_JS_PATH)
        roster = _fn_body(roster_js, "_renderWeekSelector")
        assert 'const prev = _rosterWeekId !== null ? sel.value : "";' in roster
        assert "renderIfChanged(sel, html) && prev && [...sel.options].some(o => o.value === prev)" in roster
        assert "sel.value = prev;" in roster
        assert "_renderWeekSelector();" in _fn_body(roster_js, "loadWeeks")

    def test_loaders_keep_content_on_refresh_error(self):
        """Failure path: on a network error or non-OK response the loaders set the tab's existing status line and do not overwrite content already on screen with the error."""
        # Non-OK responses throw into the catch, which only sets the status line.
        checks = [
            (_APP_LEADERBOARD_JS_PATH, "loadSeasonLeaderboard", 'setStatus("seasonStandingsStatus", e.message, false)'),
            (_APP_LEADERBOARD_JS_PATH, "loadWeeklyLeaderboard", 'setStatus("weeklyStandingsStatus", e.message, false)'),
            (_APP_LEADERBOARD_JS_PATH, "loadLeaderboard", 'setStatus("leaderboardStatus", e.message, false)'),
            (_APP_LEADERBOARD_JS_PATH, "loadTop", 'setStatus("topStatus", e.message, false)'),
            (_APP_PLAYERS_JS_PATH, "loadPlayers", 'setStatus("playersStatus", e.message, false)'),
            (_APP_PLAYERS_JS_PATH, "loadTeams", 'setStatus("teamsStatus", e.message, false)'),
            (_APP_CARDS_JS_PATH, "loadDeck", 'setStatus("deckStatus", e.message, false)'),
            (_APP_ROSTER_JS_PATH, "loadRoster", "statusEl.textContent = e.message"),
        ]
        for path, loader, status in checks:
            body = _fn_body(_read(path), loader)
            assert "if (!res.ok) throw new Error(" in body, loader
            catch = body[body.rindex("} catch (e) {"):]
            assert status in catch, loader
            assert "renderIfChanged" not in catch and "innerHTML" not in catch, loader
        sched = _fn_body(_read(_APP_PLAYERS_JS_PATH), "loadSchedule")
        catch = sched[sched.rindex("} catch (e) {"):]
        # Issue #156 UX review: a readable message with a way forward; the raw error goes to the console.
        assert 'setStatus("scheduleStatus", "Couldn\'t load the schedule. Refresh to try again.", false);' in catch
        assert 'if (firstLoad) renderIfChanged(content, "");' in catch
        assert ('if (!res.ok) { setStatus("scheduleStatus", data.detail || "Failed to load", false); '
                'if (firstLoad) renderIfChanged(content, ""); return; }') in sched
        booster = _fn_body(_read(_APP_CARDS_JS_PATH), "loadBoosterTeams")
        assert 'else setStatus("boosterStatus", msg, false);' in booster
        assert "showError(e.message);" in booster and 'showError(teams.detail ?? "Error")' in booster

    def test_loaders_show_error_when_block_never_loaded(self):
        """Failure path: a block that had never loaded (empty container) still shows the error as before."""
        booster = _fn_body(_read(_APP_CARDS_JS_PATH), "loadBoosterTeams")
        assert "if (firstLoad) renderIfChanged(grid, `<span style=\"color:#c44;\">${_escHtml(msg)}</span>`);" in booster
        # Schedule: as before, an empty block plus the error in the status line.
        sched = _fn_body(_read(_APP_PLAYERS_JS_PATH), "loadSchedule")
        assert sched.count('if (firstLoad) renderIfChanged(content, "");') == 2
        # Tables never had inline errors; the status line still carries them.
        assert 'setStatus("seasonStandingsStatus", e.message, false)' in _fn_body(
            _read(_APP_LEADERBOARD_JS_PATH), "loadSeasonLeaderboard")


# ---------------------------------------------------------------------------
# Story 2: Same Tab or a Different Tab
# ---------------------------------------------------------------------------

class TestSameTabOrDifferentTab:

    def test_switch_tab_same_tab_skips_class_toggle_and_scroll(self):
        """switchTab has a same-tab branch: when `name` is already the active tab it skips the `.tab-content` / `.tab` class toggling and leaves the scroll position as it is."""
        body = _switch_tab()
        assert 'const current = document.querySelector(".tab-content.active");' in body
        assert "const sameTab = !!current && current.id === `tab-${name}`;" in body
        start = body.index("if (!sameTab) {")
        branch = body[start:body.index("\n  }\n", start)]
        assert 'classList.remove("active")' in branch and 'classList.add("active")' in branch
        assert "scrollTo" in branch
        outside = body.replace(branch, "")
        assert 'classList.remove("active")' not in outside and "scrollTo" not in outside

    def test_switch_tab_same_tab_still_runs_loaders(self):
        """On the same-tab branch switchTab still runs the tab's loaders as a quiet refresh (it does not return early before the loader calls)."""
        body = _switch_tab()
        end_of_branch = body.index("\n  }\n", body.index("if (!sameTab) {"))
        assert "return" not in body[:end_of_branch]
        for call in ("loadDeck();", "loadSeasonLeaderboard();", "loadPlayers();", "loadSchedule();"):
            assert body.index(call) > end_of_branch, call

    def test_switch_tab_different_tab_saves_and_restores_scroll(self):
        """Switching to a different tab saves `window.scrollY` for the outgoing tab in a `_tabScroll` map, switches classes, then restores the incoming tab's saved scroll inside `requestAnimationFrame`."""
        js = _globals()
        assert re.search(r"^const _tabScroll = \{\};$", js, re.M)
        body = _switch_tab()
        save = 'if (current) _tabScroll[current.id.replace(/^tab-/, "")] = window.scrollY;'
        assert save in body
        assert body.index(save) < body.index('document.getElementById(`tab-${name}`).classList.add("active");')
        assert "requestAnimationFrame(() => window.scrollTo(0, y));" in body

    def test_switch_tab_first_visit_scrolls_to_top(self):
        """A tab with no `_tabScroll` entry yet is restored to 0 (e.g. `_tabScroll[name] || 0`)."""
        assert "const y = _tabScroll[name] || 0;" in _switch_tab()

    def test_switch_tab_existing_callers_still_call_switch_tab(self):
        """Login, logout (app-auth.js), the forced password change and the tour (app-tour.js) still call `switchTab(` with their tab names, so they land on the tab with fresh data."""
        auth = _read(os.path.join(_FRONTEND_DIR, "app-auth.js"))
        assert 'switchTab("leaderboard")' in auth  # logout
        assert 'switchTab("team")' in auth        # login
        assert 'switchTab("profile")' in auth     # forced password change
        assert 'switchTab("team")' in _read(os.path.join(_FRONTEND_DIR, "app-tour.js"))

    def test_switch_tab_forced_password_change_redirects_to_profile_first(self):
        """Failure path: the `activeMustChangePassword && name !== "profile"` redirect to "profile" stays the first statement in switchTab, before the same-tab check."""
        body = _switch_tab()
        assert body.split("\n")[1].strip() == 'if (activeMustChangePassword && name !== "profile") {'
        assert body.index('name = "profile";') < body.index("const sameTab")


# ---------------------------------------------------------------------------
# Story 3: Weekly Report Keeps Its Frame
# ---------------------------------------------------------------------------

class TestWeeklyReportKeepsItsFrame:

    def test_weekly_summary_modal_fixed_height_85vh(self):
        """`.weekly-summary-modal` has `height: 85vh` (not only `max-height`); `max-height` may stay for very short screens."""
        body = _css_rule(_css(), ".weekly-summary-modal")
        assert re.search(r"(?<!-)height:\s*85vh", body)
        assert re.search(r"max-height:\s*85vh", body)

    def test_weekly_summary_modal_height_92vh_at_600px(self):
        """Inside `@media (max-width: 600px)` `.weekly-summary-modal` has `height: 92vh`."""
        rules = [_rule_in(b, ".weekly-summary-modal") for b in _media_bodies(_css(), "max-width: 600px")]
        assert any(r and re.search(r"(?<!-)height:\s*92vh", r) for r in rules)

    def test_weekly_summary_stacked_layout_still_scrolls_at_1100px(self):
        """In `@media (max-width: 1100px)` the stacked popup still scrolls as one page (overflow on the modal/body as today), unaffected by the fixed height."""
        bodies = _media_bodies(_css(), "max-width: 1100px")
        modal = [r for r in (_rule_in(b, ".weekly-summary-modal") for b in bodies) if r]
        assert any("overflow-y: auto" in r for r in modal)
        cols = [r for r in (_rule_in(b, ".weekly-summary-col-body") for b in bodies) if r]
        assert any("overflow: visible" in r for r in cols)

    def test_weekly_summary_col_body_is_loading_dims(self):
        """`.weekly-summary-col-body.is-loading` sets `opacity: .6` (about 0.6) with `transition: opacity 150ms`, using tokens only (no hex)."""
        body = _css_rule(_css(), ".weekly-summary-col-body.is-loading")
        assert re.search(r"opacity:\s*0?\.6;", body)
        assert "transition: opacity 150ms" in body
        assert "#" not in body

    def test_weekly_summary_is_loading_transition_off_under_reduced_motion(self):
        """A `@media (prefers-reduced-motion: reduce)` block contains a `.weekly-summary-col-body.is-loading` rule that turns the transition off (`transition: none`)."""
        rules = [_rule_in(b, ".weekly-summary-col-body.is-loading")
                 for b in _media_bodies(_css(), "prefers-reduced-motion: reduce")]
        assert any(r and "transition: none" in r for r in rules)

    def test_select_weekly_summary_tab_no_unconditional_loading_write(self):
        """selectWeeklySummaryTab no longer writes "Loading…" over existing content: any Loading write is behind an empty-columns check."""
        body = _fn_body(_wsjs(), "selectWeeklySummaryTab")
        assert body.count("'Loading…'") == 2  # one call, both columns
        guard = "} else if (rosterBody.innerHTML.trim() === '' && resultsBody.innerHTML.trim() === '') {"
        assert guard in body
        after_guard = body[body.index(guard):]
        assert after_guard.index("_weeklySummaryMessage('Loading…')") < after_guard.index("} else {")

    def test_select_weekly_summary_tab_sets_is_loading_and_aria_busy(self):
        """While fetching, selectWeeklySummaryTab adds `.is-loading` and `aria-busy="true"` to both column bodies, and removes both when done."""
        js = _wsjs()
        helper = _fn_body(js, "_setWeeklySummaryLoading")
        assert "['weeklySummaryRoster', 'weeklySummaryContent']" in helper
        assert "el.classList.toggle('is-loading', on);" in helper
        assert "el.setAttribute('aria-busy', 'true');" in helper
        assert "el.removeAttribute('aria-busy');" in helper
        body = _fn_body(js, "selectWeeklySummaryTab")
        assert "_setWeeklySummaryLoading(true);" in body
        fetched = body[body.index("fetch("):]
        assert fetched.count("_setWeeklySummaryLoading(false);") == 2  # after the response, and in catch

    def test_select_weekly_summary_tab_ignores_stale_response(self):
        """selectWeeklySummaryTab bumps a `_weeklySummaryReq` request counter and ignores a response when the counter has moved on, so an out-of-order reply can't overwrite the week now shown."""
        js = _wsjs()
        assert re.search(r"^let _weeklySummaryReq = 0;$", js, re.M)
        body = _fn_body(js, "selectWeeklySummaryTab")
        assert body.split("\n")[1].strip() == "const req = ++_weeklySummaryReq;"
        fetched = body[body.index("fetch("):]
        assert fetched.count("if (req !== _weeklySummaryReq) return;") == 2
        assert fetched.index("if (req !== _weeklySummaryReq) return;") < fetched.index("renderWeeklySummaryContent(")
        assert "_weeklySummaryReq += 1;" in _fn_body(js, "closeWeeklySummary")

    def test_select_weekly_summary_tab_swaps_both_columns_and_scrolls_top(self):
        """When data arrives both columns and their headers are rendered in one update via renderIfChanged, and both bodies scroll to the top only when the week changed."""
        js = _wsjs()
        render = _fn_body(js, "renderWeeklySummaryContent")
        assert ("renderIfChanged(document.getElementById('weeklySummaryRoster'), "
                "_weeklySummaryRosterHtml(roster, data.revealed));") in render
        assert "renderIfChanged(content, html);" in render
        assert "_renderWeeklySummaryRosterHeader(data);" in render and "weeklySummaryResultsMeta" in render
        assert not _INNERHTML_WRITE.search(render)
        assert "await" not in render  # one synchronous update
        body = _fn_body(js, "selectWeeklySummaryTab")
        assert "if (weekChanged && !cached) _scrollWeeklySummaryColumnsTop();" in body
        assert "if (weekChanged) _scrollWeeklySummaryColumnsTop();" in body
        scroll = _fn_body(js, "_scrollWeeklySummaryColumnsTop")
        assert "getElementById('weeklySummaryRoster').scrollTop = 0;" in scroll
        assert "getElementById('weeklySummaryContent').scrollTop = 0;" in scroll
        cols = _fn_body(js, "_setWeeklySummaryColumns")
        assert not _INNERHTML_WRITE.search(cols) and cols.count("renderIfChanged(") == 2

    def test_select_weekly_summary_tab_renders_from_cache(self):
        """Weeks fetched while the popup is open are stored in `_weeklySummaryCache` keyed by week id; a cached week renders at once, then refreshes quietly with renderIfChanged."""
        js = _wsjs()
        assert re.search(r"^const _weeklySummaryCache = new Map\(\);$", js, re.M)
        body = _fn_body(js, "selectWeeklySummaryTab")
        assert "const cached = _weeklySummaryCache.get(weekId);" in body
        cache_branch = body[body.index("if (cached) {"):body.index("} else if (rosterBody")]
        assert "renderWeeklySummaryContent(cached, {playRecap: false});" in cache_branch
        assert body.index("renderWeeklySummaryContent(cached") < body.index("fetch(")
        assert "_weeklySummaryCache.set(weekId, data);" in body
        # The quiet refresh goes through renderIfChanged inside renderWeeklySummaryContent.
        assert "renderIfChanged(content, html);" in _fn_body(js, "renderWeeklySummaryContent")

    def test_close_weekly_summary_clears_cache(self):
        """closeWeeklySummary clears the whole `_weeklySummaryCache`."""
        assert "_weeklySummaryCache.clear();" in _fn_body(_wsjs(), "closeWeeklySummary")

    def test_reveal_functions_clear_cache_for_revealed_weeks(self):
        """revealAllWeeklySummaries and the single-week reveal path delete the revealed weeks from `_weeklySummaryCache`, so revealed data is never stale."""
        js = _wsjs()
        # revealAllWeeklySummaries is the only reveal path in the frontend (there is no
        # single-week reveal): it deletes every listed week before re-selecting.
        body = _fn_body(js, "revealAllWeeklySummaries")
        assert ("_weeklySummaryWeeks.forEach(w => { _weeklySummaryCache.delete(w.week_id); "
                "w.revealed = true; });") in body
        assert body.index("_weeklySummaryCache.delete") < body.index("selectWeeklySummaryTab(")
        assert len(re.findall(r"weekly-summary/[^`'\"]*reveal", js)) == 1

    def test_render_weekly_summary_tabs_rebuilds_only_on_signature_change(self):
        """renderWeeklySummaryTabs compares a signature of the week list (`week_id:label:revealed`) with the last one, rebuilds buttons only when it differs, and otherwise only calls `_markActiveWeeklySummaryTab`."""
        js = _wsjs()
        assert re.search(r"^let _weeklySummaryTabsSig = null;$", js, re.M)
        body = _fn_body(js, "renderWeeklySummaryTabs")
        assert "_weeklySummaryWeeks.map(w => `${w.week_id}:${w.label}:${w.revealed}`).join('|')" in body
        guard = "if (sig !== _weeklySummaryTabsSig || bar.children.length !== _weeklySummaryWeeks.length) {"
        assert guard in body
        start = body.index(guard)
        rebuild = body[start:body.index("\n  }\n", start)]
        assert "bar.innerHTML = '';" in rebuild and "bar.appendChild(btn);" in rebuild
        assert body.count("bar.innerHTML") == 1
        assert body.index("_markActiveWeeklySummaryTab(_weeklySummaryActiveWeekId);") > start + len(rebuild)

    def test_select_weekly_summary_tab_first_open_shows_loading_in_empty_columns(self):
        """On first open the popup frame shows at once with "Loading…" in the empty columns (only when the columns are empty)."""
        body = _fn_body(_wsjs(), "selectWeeklySummaryTab")
        assert "_setWeeklySummaryColumns(_weeklySummaryMessage('Loading…'), _weeklySummaryMessage('Loading…'));" in body
        # Not a cached week, and both columns are empty.
        assert body.index("if (cached) {") < body.index("_weeklySummaryMessage('Loading…')")

    def test_select_weekly_summary_tab_error_replaces_columns_and_removes_dimming(self):
        """Failure path: when loading a week fails the error replaces that week's columns, `.is-loading` and `aria-busy` are removed, and the frame size is unchanged."""
        body = _fn_body(_wsjs(), "selectWeeklySummaryTab")
        fetched = body[body.index("fetch("):]
        assert "if (!cached) _setWeeklySummaryColumns('', _weeklySummaryMessage(data.detail, true));" in fetched
        assert fetched.index("_setWeeklySummaryLoading(false);") < fetched.index("if (!res.ok) {")
        catch = fetched[fetched.index("} catch (e) {"):]
        assert catch.index("_setWeeklySummaryLoading(false);") < catch.index(
            "if (!cached) _setWeeklySummaryColumns('', _weeklySummaryMessage(e.message, true));")
        # The frame size comes from CSS, not content.
        assert re.search(r"(?<!-)height:\s*85vh", _css_rule(_css(), ".weekly-summary-modal"))

    def test_recap_animation_not_replayed_from_cache(self):
        """The #152 recap still plays only on a week's first revealed view and `_stopRecap()` runs on a week switch (after bumping `_weeklySummaryReq`); rendering a week from `_weeklySummaryCache` does not call `_maybePlayRecap` again."""
        js = _wsjs()
        body = _fn_body(js, "selectWeeklySummaryTab")
        assert body.index("const req = ++_weeklySummaryReq;") < body.index("_stopRecap();") < body.index("fetch(")
        assert "renderWeeklySummaryContent(cached, {playRecap: false});" in body
        assert "renderWeeklySummaryContent(data, {playRecap: !cached});" in body
        render = _fn_body(js, "renderWeeklySummaryContent")
        assert "function renderWeeklySummaryContent(data, {playRecap = true} = {})" in render
        assert "if (playRecap) _maybePlayRecap(data.week_id, data);" in render
        assert "else _updateRecapButtons();" in render
        # The animation rebuilds the roster column by hand; the next render must write it.
        play = _fn_body(js, "_playRecap")
        assert play.index("forgetRendered(body);") < play.index("body.innerHTML = '';")
        assert "function forgetRendered(el)" in _globals()
