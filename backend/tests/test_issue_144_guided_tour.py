"""
Tests for plan-issue-144-guided-tour (resolves GitHub issue #144).

First-time guided tour on My Team, built in plain JavaScript
(`frontend/app-tour.js`). Decision (2026-10-01): the tour is started only from
the How to Play tab's "Show the tour" button; automatic first-visit start is
built but gated behind `GUIDED_TOUR_AUTOSTART` (default false), exposed to the
frontend as `tour_autostart` in `GET /config`.

Most criteria are frontend behaviour, so they are checked statically against
`frontend/app-tour.js`, `frontend/index.html`, `frontend/app-globals.js` and
`frontend/style.css`. Backend criteria call `main.get_config(db=db)` directly
with `monkeypatch.setenv` (the `demo_mode` approach in
test_issue_83_demo_mode.py), which requires `get_config` to read
`GUIDED_TOUR_AUTOSTART` at request time. Never reload `main` here.

Manual-only (need a real browser, see the plan's Verification section):
  - at 400 px wide the tour box stays fully on screen, below or above the target
  - the target is scrolled into view before its step shows (runtime behaviour)
  - the highlight follows the element on resize/rotation (runtime behaviour)
  - focus moves into the box on open and returns to the page on close (runtime)
  - the tour waits for open popups and gives up after 10 seconds (runtime)
  - a blocked localStorage (private window) leaves the page working (runtime)

Stories:
  1. Start the Tour from How to Play
  2. Control the Tour
  3. Automatic Start for New Players (switched off at first)
  4. Works on Every Screen
"""
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import models  # noqa: F401  (registers every table on Base before the db fixture runs)

_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
_REPO_DIR = os.path.join(_BACKEND_DIR, "..")
_FRONTEND_DIR = os.path.join(_REPO_DIR, "frontend")

TOUR_JS_PATH = os.path.join(_FRONTEND_DIR, "app-tour.js")
INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
GLOBALS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-globals.js")
STYLE_CSS_PATH = os.path.join(_FRONTEND_DIR, "style.css")
ENV_EXAMPLE_PATH = os.path.join(_REPO_DIR, ".env.example")

TOUR_STORAGE_KEY = "fantasy.tourSeen.v1"

# The six step targets, in order (plan Story 1). The Points step highlights the
# shared container of the This week / Season totals (#rosterTotals), which holds
# #rosterCombined and #rosterSeasonPoints.
STEP_TARGETS = [
    "#drawBtn",
    ".rarity-grid",
    "#rosterActiveGrid",
    "#rosterWeekSelect",
    "#rosterTotals",
    "#tab-btn-leaderboard",
]

STEP_TITLES = ["Draw a card", "Chances", "Your roster", "Weekly lock", "Points", "Leaderboards"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _js_function(js, name):
    """Body of a top-level JS function (2-space-indented body ending in a bare `\n}`)."""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", js)
    assert m, f"function {name} not found"
    end = js.index("\n}\n", m.start())
    return js[m.start():end + 2]


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _tags(html):
    p = _Tags()
    p.feed(html)
    return p.tags


def _users_panel(html):
    start = html.index('id="howtoplay-panel-users"')
    end = html.index('id="howtoplay-panel-players"')
    return html[start:end]


def _step_objects(js):
    """(target, title, body-source) for each step literal in myTeamTourSteps()."""
    fn = _js_function(js, "myTeamTourSteps")
    return re.findall(
        r'target:\s*"([^"]+)",\s*title:\s*"([^"]+)",\s*body:\s*([^\n]+),', fn
    )


def _selector_in_html(html, selector):
    tags = _tags(html)
    if selector.startswith("#"):
        return any(a.get("id") == selector[1:] for _, a in tags)
    if selector.startswith("."):
        cls = selector[1:]
        return any(cls in (a.get("class") or "").split() for _, a in tags)
    raise AssertionError(f"unsupported selector {selector}")


# ---------------------------------------------------------------------------
# Story 1 — Start the Tour from How to Play
# ---------------------------------------------------------------------------

class TestStartTourFromHowToPlay:

    def test_howtoplay_users_subtab_has_show_the_tour_button(self):
        """The How to Play Users subtab (#howtoplay-panel-users) has a "Show the tour" button near the top."""
        panel = _users_panel(_read(INDEX_HTML_PATH))
        m = re.search(r'<button[^>]*id="htpTourBtn"[^>]*>Show the tour</button>', panel)
        assert m, "Show the tour button missing from the Users subtab"
        assert 'onclick="startTourFromHowToPlay()"' in m.group(0)
        # Near the top: before the first section list (Cards & Drawing).
        assert m.start() < panel.index("Cards &amp; Drawing")

    def test_show_the_tour_button_switches_to_team_and_forces_start(self):
        """For a logged-in user the button switches to My Team (switchTab('team')) and calls startTour(steps, {force: true}) from step 1."""
        fn = _js_function(_read(TOUR_JS_PATH), "startTourFromHowToPlay")
        assert 'switchTab("team")' in fn
        assert "startTour(myTeamTourSteps(), { force: true })" in fn
        assert fn.index('switchTab("team")') < fn.index("startTour(")

    def test_show_the_tour_button_logged_out_opens_login_popup(self):
        """For a logged-out visitor the button opens the login popup (showLogin()) instead of starting the tour."""
        fn = _js_function(_read(TOUR_JS_PATH), "startTourFromHowToPlay")
        m = re.search(r"if \(!activeUserId\) \{\s*showLogin\(\);\s*return;\s*\}", fn)
        assert m, "logged-out branch must call showLogin() and return"
        assert m.start() < fn.index('switchTab("team")')

    def test_index_html_loads_app_tour_js_before_app_init_js(self):
        """index.html loads /app-tour.js with a local <script> tag before /app-init.js (no new CDN script)."""
        srcs = [a.get("src") for t, a in _tags(_read(INDEX_HTML_PATH)) if t == "script" and a.get("src")]
        assert "/app-tour.js" in srcs
        assert srcs.index("/app-tour.js") < srcs.index("/app-init.js")
        assert not any("app-tour" in s and s.startswith("http") for s in srcs)

    def test_tour_steps_six_targets_in_order(self):
        """app-tour.js defines the six My Team steps in order: #drawBtn, .rarity-grid, #rosterActiveGrid, #rosterWeekSelect, points totals, #tab-btn-leaderboard."""
        steps = _step_objects(_read(TOUR_JS_PATH))
        assert [t for t, _, _ in steps] == STEP_TARGETS

    def test_tour_step_targets_exist_in_index_html(self):
        """Every step target selector used by the tour exists in index.html (failure case: a renamed id silently empties a step)."""
        html = _read(INDEX_HTML_PATH)
        for target in STEP_TARGETS:
            assert _selector_in_html(html, target), f"{target} missing from index.html"
        # The Points container holds both totals.
        start = html.index('id="rosterTotals"')
        end = html.index("</div>", start)
        assert 'id="rosterCombined"' in html[start:end]
        assert 'id="rosterSeasonPoints"' in html[start:end]

    def test_tour_step_titles_and_copy_present(self):
        """Steps carry the titles Draw a card, Chances, Your roster, Weekly lock, Points, Leaderboards with one or two sentences each."""
        steps = _step_objects(_read(TOUR_JS_PATH))
        assert [title for _, title, _ in steps] == STEP_TITLES
        js = _read(TOUR_JS_PATH)
        for _, title, body_src in steps:
            if body_src == "rosterText":
                fn = _js_function(js, "myTeamTourSteps")
                bodies = re.findall(r'(?:`|")(Put [^`"]+)(?:`|")', fn)
                assert len(bodies) == 2
            else:
                bodies = [body_src.strip('`"')]
            for b in bodies:
                sentences = [x for x in re.split(r"(?<=\.)\s+", b.strip()) if x]
                assert 1 <= len(sentences) <= 2, f"{title}: {b!r}"

    def test_tour_copy_uses_live_values_not_fixed_numbers(self):
        """Step text is built from live values (_tokenName / _teamBoosterCost / roster limit), not hard-coded numbers or token names that can go stale."""
        fn = _js_function(_read(TOUR_JS_PATH), "myTeamTourSteps")
        draw_body = _step_objects(_read(TOUR_JS_PATH))[0][2]
        assert "${_tokenName}" in draw_body
        assert "${_teamBoosterCost}" in draw_body
        assert not re.search(r"\btokens?\b", draw_body, re.IGNORECASE)
        assert "1 token" not in fn
        assert "${rosterLimit}" in fn
        assert 'getElementById("rosterActiveGrid")' in fn
        assert "up to 5" not in fn and "5 cards" not in fn
        assert "3 tokens" not in fn

    def test_tour_skips_missing_or_hidden_targets_and_adjusts_count(self):
        """A step whose element is missing or hidden is filtered out before the tour starts, and the step count uses the filtered list."""
        js = _read(TOUR_JS_PATH)
        visible = _js_function(js, "_tourTargetVisible")
        assert "!el" in visible and "getClientRects().length === 0" in visible
        start = _js_function(js, "startTour")
        assert "filter(s => _tourTargetVisible(document.querySelector(s.target)))" in start
        assert "if (!visibleSteps.length) return false;" in start
        assert "steps: visibleSteps" in start
        show = _js_function(js, "_tourShow")
        assert "_tour.steps.length" in show
        assert "${index + 1} / ${total}" in show

    def test_tour_not_started_automatically_when_autostart_false(self):
        """With tour_autostart false (default) nothing in app-globals.js / app-tour.js starts the tour without the button (failure case: unconditional startTour on load)."""
        js = _read(TOUR_JS_PATH)
        globals_js = _read(GLOBALS_JS_PATH)
        assert "let _tourAutostart    = false;" in globals_js
        assert "startTour(" not in globals_js
        # Only two callers of startTour: the gated autostart and the button.
        callers = [m.start() for m in re.finditer(r"\bstartTour\(", js)]
        fn_start = js.index("function startTour(")
        calls = [c for c in callers if c != fn_start + len("function ")]
        maybe = _js_function(js, "maybeStartMyTeamTour")
        button = _js_function(js, "startTourFromHowToPlay")
        assert len(calls) == 2
        assert all(js.find(maybe) <= c < js.find(maybe) + len(maybe)
                   or js.find(button) <= c < js.find(button) + len(button) for c in calls)
        assert maybe.split("\n")[1].strip() == "if (!_tourAutostart) return;"
        # No top-level call that would run on script load.
        assert not re.search(r"^(maybeStartMyTeamTour|startTour)\(", js, re.M)


# ---------------------------------------------------------------------------
# Story 2 — Control the Tour
# ---------------------------------------------------------------------------

class TestControlTheTour:

    def test_tour_has_skip_next_done_buttons_and_step_counter(self):
        """The tour box has Skip and Next buttons, Done on the last step, and an "N / M" step counter."""
        js = _read(TOUR_JS_PATH)
        start = _js_function(js, "startTour")
        assert '_tourEl("button", "ghost tour-skip", "Skip")' in start
        assert '_tourEl("button", "tour-next", "Next")' in start
        show = _js_function(js, "_tourShow")
        assert 'isLast ? "Done" : "Next"' in show
        assert "_tour.counter.textContent = `${index + 1} / ${total}`" in show

    def test_tour_keyboard_esc_enter_and_arrow_keys(self):
        """Esc skips; Enter or ArrowRight goes next; ArrowLeft goes back."""
        fn = _js_function(_read(TOUR_JS_PATH), "_tourOnKey")
        assert re.search(r'e\.key === "Escape"\)\s*\{[^}]*endTour\(\)', fn)
        assert re.search(r'e\.key === "Enter" \|\| e\.key === "ArrowRight"\)\s*\{[^}]*_tourNext\(\)', fn)
        assert re.search(r'e\.key === "ArrowLeft"\)\s*\{[^}]*_tourBack\(\)', fn)
        start = _js_function(_read(TOUR_JS_PATH), "startTour")
        assert 'document.addEventListener("keydown", _tour.onKey, true)' in start

    def test_tour_backdrop_click_skips(self):
        """Clicking the dark backdrop skips the tour."""
        start = _js_function(_read(TOUR_JS_PATH), "startTour")
        assert 'backdrop.addEventListener("click", () => endTour())' in start
        assert 'skipBtn.addEventListener("click", () => endTour())' in start

    def test_tour_dialog_has_role_aria_modal_and_label(self):
        """The tour box has role="dialog", aria-modal="true" and an aria-label or aria-labelledby."""
        start = _js_function(_read(TOUR_JS_PATH), "startTour")
        assert 'box.setAttribute("role", "dialog")' in start
        assert 'box.setAttribute("aria-modal", "true")' in start
        assert 'box.setAttribute("aria-labelledby", "tourTitle")' in start
        assert 'title.id = "tourTitle"' in start

    def test_tour_moves_focus_into_box_and_restores_it(self):
        """app-tour.js focuses the box on open and restores the previously focused element on close (static check; runtime focus is manual)."""
        js = _read(TOUR_JS_PATH)
        assert "prevFocus: document.activeElement" in _js_function(js, "startTour")
        assert "box.tabIndex = -1" in _js_function(js, "startTour")
        assert "_tour.box.focus(" in _js_function(js, "_tourShow")
        end = _js_function(js, "endTour")
        assert "const prev = t.prevFocus;" in end and "prev.focus(" in end

    def test_tour_storage_key_written_on_skip_and_done(self):
        """Skip and Done write fantasy.tourSeen.v1 to localStorage."""
        js = _read(TOUR_JS_PATH)
        assert f'const TOUR_STORAGE_KEY = "{TOUR_STORAGE_KEY}";' in js
        assert "localStorage.setItem(TOUR_STORAGE_KEY" in _js_function(js, "_markTourSeen")
        assert "_markTourSeen();" in _js_function(js, "endTour")
        # Skip and Done both close through endTour().
        assert "skipBtn.addEventListener(\"click\", () => endTour())" in _js_function(js, "startTour")
        assert "return endTour();" in _js_function(js, "_tourNext")

    def test_tour_localstorage_access_wrapped_in_try_catch(self):
        """Every localStorage read and write in app-tour.js is inside try/catch, so blocked storage doesn't break the page."""
        js = _read(TOUR_JS_PATH)
        uses = [m.start() for m in re.finditer(r"localStorage\.", js)]
        assert len(uses) == 2
        for pos in uses:
            before = js[:pos]
            try_pos = before.rfind("try {")
            assert try_pos != -1
            between = js[try_pos:pos]
            assert "catch" not in between and "\n}\n" not in between
            assert "catch (_)" in js[pos:pos + 200]

    def test_tour_text_set_with_textcontent_not_innerhtml(self):
        """Tour text is set with textContent only; app-tour.js has no innerHTML/insertAdjacentHTML/outerHTML assignment."""
        js = _read(TOUR_JS_PATH)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write"):
            assert bad not in js
        show = _js_function(js, "_tourShow")
        assert "_tour.title.textContent = step.title" in show
        assert "_tour.body.textContent = step.body" in show

    def test_tour_has_no_confirm_or_prompt(self):
        """app-tour.js uses no native confirm( or prompt( (or alert()) dialogs."""
        js = _read(TOUR_JS_PATH)
        assert not re.search(r"\b(confirm|prompt|alert)\(", js)

    def test_tour_reduced_motion_disables_animation(self):
        """style.css has a prefers-reduced-motion rule that turns off the tour highlight transition/animation."""
        css = _read(STYLE_CSS_PATH)
        blocks = re.findall(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
        assert any(re.search(r"\.tour-spotlight\s*\{[^}]*transition:\s*none", b) for b in blocks)
        assert "transition:" in re.search(r"\.tour-spotlight \{(.*?)\}", css, re.S).group(1)
        assert '"auto" : "smooth"' in _js_function(_read(TOUR_JS_PATH), "_tourShow")

    def test_tour_css_follows_brand_rules(self):
        """Tour styles use existing tokens, square corners (no pill radius) and Big Shoulders for the title (failure case: border-radius: 999px or hard-coded colours)."""
        css = _read(STYLE_CSS_PATH)
        start = css.index("GUIDED TOUR (issue #144)")
        tour_css = css[start:]
        assert "--r-pill" not in tour_css
        assert not re.search(r":[^;{}]*#[0-9a-fA-F]{3,8}\b", tour_css)
        assert not re.search(r"\brgba?\(", tour_css)
        for radius in re.findall(r"border-radius:\s*([^;]+);", tour_css):
            assert radius.strip() in ("var(--r-sm)", "var(--r-xs)", "0")
        title = re.search(r"\.tour-title \{(.*?)\}", tour_css, re.S).group(1)
        assert "font-family: var(--font-display)" in title
        assert "text-transform: uppercase" in title
        assert "var(--accent)" in re.search(r"\.tour-spotlight \{(.*?)\}", tour_css, re.S).group(1)


# ---------------------------------------------------------------------------
# Story 3 — Automatic Start for New Players (switched off at first)
# ---------------------------------------------------------------------------

class TestAutomaticStart:

    def test_config_tour_autostart_false_by_default(self, db, monkeypatch):
        """GET /config returns tour_autostart: False when GUIDED_TOUR_AUTOSTART is unset."""
        monkeypatch.delenv("GUIDED_TOUR_AUTOSTART", raising=False)
        monkeypatch.setenv("DEBUG", "true")
        from main import get_config
        assert get_config(db=db)["tour_autostart"] is False

    def test_config_tour_autostart_true_when_env_true(self, db, monkeypatch):
        """GET /config returns tour_autostart: True when GUIDED_TOUR_AUTOSTART=true (read at request time)."""
        monkeypatch.setenv("DEBUG", "true")
        from main import get_config
        for value in ("true", "TRUE", "True"):
            monkeypatch.setenv("GUIDED_TOUR_AUTOSTART", value)
            assert get_config(db=db)["tour_autostart"] is True, value
        monkeypatch.setenv("GUIDED_TOUR_AUTOSTART", "false")
        assert get_config(db=db)["tour_autostart"] is False

    def test_config_tour_autostart_false_for_non_true_values(self, db, monkeypatch):
        """GUIDED_TOUR_AUTOSTART values other than "true" (e.g. "1", "yes", "") yield tour_autostart: False (failure path)."""
        monkeypatch.setenv("DEBUG", "true")
        from main import get_config
        for value in ("1", "yes", "", "false", "on", "truthy"):
            monkeypatch.setenv("GUIDED_TOUR_AUTOSTART", value)
            assert get_config(db=db)["tour_autostart"] is False, value

    def test_env_example_documents_guided_tour_autostart(self):
        """.env.example documents GUIDED_TOUR_AUTOSTART=false."""
        env = _read(ENV_EXAMPLE_PATH)
        lines = env.splitlines()
        idx = lines.index("GUIDED_TOUR_AUTOSTART=false")
        assert lines[idx - 1].startswith("#"), "GUIDED_TOUR_AUTOSTART needs a comment"

    def test_globals_reads_tour_autostart_from_config(self):
        """app-globals.js reads cfg.tour_autostart from /config and calls maybeStartMyTeamTour() after the roster loads on the team tab."""
        js = _read(GLOBALS_JS_PATH)
        assert "_tourAutostart = cfg.tour_autostart === true;" in _js_function(js, "loadConfig")
        switch = _js_function(js, "switchTab")
        team = switch[switch.index('if (name === "team")'):switch.index('if (name === "leaderboard")')]
        assert ".then(() => loadRoster(_rosterWeekId))" in team
        assert "maybeStartMyTeamTour()" in team
        assert team.index("loadRoster(") < team.index("maybeStartMyTeamTour()")

    def test_maybe_start_my_team_tour_returns_early_unless_autostart(self):
        """maybeStartMyTeamTour() returns immediately unless tour_autostart is true, then checks login state and the storage key."""
        fn = _js_function(_read(TOUR_JS_PATH), "maybeStartMyTeamTour")
        auto = fn.index("if (!_tourAutostart) return;")
        login = fn.index("if (!activeUserId) return;")
        seen = fn.index("_tourSeen()")
        assert auto < login < seen

    def test_maybe_start_my_team_tour_skips_when_seen(self):
        """maybeStartMyTeamTour() does not start the tour when fantasy.tourSeen.v1 is set (failure path: re-shows to people who took it)."""
        js = _read(TOUR_JS_PATH)
        fn = _js_function(js, "maybeStartMyTeamTour")
        assert "if (_tour || _tourSeen()) return;" in fn
        assert "startTour(myTeamTourSteps())" in fn
        assert "force" not in fn
        seen = _js_function(js, "_tourSeen")
        assert 'localStorage.getItem(TOUR_STORAGE_KEY) === "1"' in seen
        assert "if (!opts.force && _tourSeen()) return false;" in _js_function(js, "startTour")

    def test_maybe_start_my_team_tour_waits_for_open_modals(self):
        """maybeStartMyTeamTour() waits until no .modal-overlay without .hidden is open, giving up after 10 seconds."""
        js = _read(TOUR_JS_PATH)
        assert "const TOUR_MODAL_WAIT_MS = 10000;" in js
        assert '".modal-overlay:not(.hidden)"' in _js_function(js, "_tourModalOpen")
        fn = _js_function(js, "maybeStartMyTeamTour")
        assert "await _tourWaitFor(() => !_tourModalOpen(), TOUR_MODAL_WAIT_MS)" in fn
        assert "if (!noModal) return;" in fn
        wait = _js_function(js, "_tourWaitFor")
        assert "Date.now() >= deadline" in wait and "resolve(false)" in wait

    def test_show_the_tour_button_forces_start_even_when_seen(self):
        """The How to Play button always starts the tour (force: true bypasses the seen check)."""
        js = _read(TOUR_JS_PATH)
        fn = _js_function(js, "startTourFromHowToPlay")
        assert "{ force: true }" in fn
        assert "_tourSeen" not in fn and "_tourAutostart" not in fn

    def test_howtoplay_pinned_phrases_unchanged(self):
        """Pinned How to Play phrases stay intact: "Getting Started", "Draw a card", "5 cards", "locks automatically" (test_how_to_play_role_subtabs.py) and the team-draw bullet (test_issue_103)."""
        panel = _users_panel(_read(INDEX_HTML_PATH))
        for phrase in ("Getting Started", "Draw a card", "5 cards", "locks automatically"):
            assert phrase in panel, phrase
        assert ('A <strong>team draw</strong> costs <strong><span id="htpTeamDrawCost">3</span> tokens</strong>'
                in panel)
        # The tour button sits outside the Cards & Drawing list.
        heading = panel.index("Cards &amp; Drawing")
        ul = panel[panel.index("<ul", heading):panel.index("</ul>", heading)]
        assert "htpTourBtn" not in ul


# ---------------------------------------------------------------------------
# Story 4 — Works on Every Screen
# (positioning at 400 px, scrolling and resize following need a browser; manual)
# ---------------------------------------------------------------------------

class TestWorksOnEveryScreen:

    def test_tour_positions_box_below_or_above_and_clamps_to_viewport(self):
        """app-tour.js places the box below the target or above when there's no room, and clamps it inside the viewport with a 16 px margin (static check)."""
        js = _read(TOUR_JS_PATH)
        assert "const TOUR_MARGIN = 16;" in js
        fn = _js_function(js, "_tourPosition")
        assert "const below = rect.bottom" in fn
        assert "const above = rect.top" in fn
        assert "if (below + bh <= vh - TOUR_MARGIN) top = below;" in fn
        assert "else if (above >= TOUR_MARGIN) top = above;" in fn
        assert "Math.max(TOUR_MARGIN, Math.min(top, vh - bh - TOUR_MARGIN))" in fn
        assert "Math.max(TOUR_MARGIN, Math.min(left, vw - bw - TOUR_MARGIN))" in fn
        css = _read(STYLE_CSS_PATH)
        assert "width: min(340px, calc(100vw - 32px));" in re.search(r"\.tour-box \{(.*?)\}", css, re.S).group(1)

    def test_tour_scrolls_target_into_view_before_step(self):
        """app-tour.js calls scrollIntoView({block: "center"}) on the target before showing each step."""
        fn = _js_function(_read(TOUR_JS_PATH), "_tourShow")
        assert 'target.scrollIntoView({ block: "center"' in fn
        assert fn.index("scrollIntoView(") < fn.index("_tourPosition();")

    def test_tour_recomputes_on_resize_and_scroll(self):
        """app-tour.js listens for resize and scroll and recomputes via requestAnimationFrame, removing the listeners when the tour closes (failure path: leaked listeners)."""
        js = _read(TOUR_JS_PATH)
        start = _js_function(js, "startTour")
        assert 'window.addEventListener("resize", _tour.onResize)' in start
        assert 'window.addEventListener("scroll", _tour.onScroll, true)' in start
        sched = _js_function(js, "_tourSchedulePosition")
        assert "requestAnimationFrame(" in sched and "_tourPosition()" in sched
        end = _js_function(js, "endTour")
        assert 'window.removeEventListener("resize", t.onResize)' in end
        assert 'window.removeEventListener("scroll", t.onScroll, true)' in end
        assert 'document.removeEventListener("keydown", t.onKey, true)' in end
        assert "cancelAnimationFrame(t.raf)" in end
