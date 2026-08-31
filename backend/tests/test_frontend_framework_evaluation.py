"""
Tests for plan-frontend-framework-evaluation.md (resolves GitHub issue #95).

Unlike most plans in this repo, the deliverable here is a decision document, not backend
behavior — so every test is a plain file-content assertion against
markdown/features/reference/frontend-framework-evaluation.md, with no `db` fixture and no
API/router imports involved. This mirrors the frontend-file-content-assertion pattern already
established in this repo (e.g. test_issue_89_fix_available_draws_count.py,
test_mvp_visibility.py's frontend-only stubs) applied to a markdown deliverable instead of a
JS one.

Covers both user stories from markdown/plans/plan-frontend-framework-evaluation.md:

  Story: Produce a Framework Evaluation Document
  Story: Validate the Recommendation with a Minimal Spike — approved and implemented:
    the How to Play tab's subtab switching was rebuilt in Alpine.js, loaded via CDN
    script tag (no build step), alongside the untouched vanilla-JS admin/main-nav tabs.

Run with: cd backend && python -m pytest tests/test_frontend_framework_evaluation.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DOC_PATH = os.path.join(_REPO_ROOT, "markdown", "features", "reference",
                          "frontend-framework-evaluation.md")
_FRONTEND_DIR = os.path.join(_REPO_ROOT, "frontend")
_INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
_APP_INIT_PATH = os.path.join(_FRONTEND_DIR, "app-init.js")
_STYLE_CSS_PATH = os.path.join(_FRONTEND_DIR, "style.css")


def _read_doc() -> str:
    with open(_DOC_PATH) as f:
        return f.read()


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


# ===========================================================================
# Story: Produce a Framework Evaluation Document
# ===========================================================================

class TestFrameworkEvaluationDocument:
    def test_evaluation_doc_exists_at_expected_path(self):
        """The document lives at markdown/features/reference/frontend-framework-evaluation.md."""
        assert os.path.isfile(_DOC_PATH)

    def test_evaluation_doc_inventories_current_frontend_shape(self):
        """The doc inventories the current frontend's actual shape: file split pattern,
        global state management, build tooling (none), and FastAPI StaticFiles serving —
        not a generic/abstract description."""
        doc = _read_doc()
        assert "app-globals.js" in doc
        assert "StaticFiles" in doc
        assert "No " in doc and ("build" in doc.lower())
        assert "activeUserId" in doc or "global" in doc.lower()

    def test_evaluation_doc_covers_all_three_options(self):
        """The doc evaluates all three required options: (a) stay vanilla JS with
        incremental improvements, (b) full-rewrite migration to one concrete named
        framework, (c) incremental/hybrid adoption alongside the existing vanilla JS."""
        doc = _read_doc()
        assert "Stay vanilla" in doc or "stay vanilla" in doc
        assert "Full-rewrite" in doc or "full-rewrite" in doc
        assert "Incremental" in doc or "incremental" in doc
        # A concrete framework must be named for option (b), not left abstract.
        assert "React" in doc or "Vue" in doc or "Svelte" in doc

    def test_evaluation_doc_scores_options_against_actual_constraints(self):
        """Each option is scored against this codebase's actual constraints: no build step
        today, FastAPI serving static files directly, the existing multi-file split-by-tab
        pattern, and team size/velocity implications — not generic framework pros/cons."""
        doc = _read_doc()
        for marker in ("Build step", "FastAPI static serving", "split pattern", "Team size"):
            assert marker in doc, f"missing constraint dimension: {marker}"

    def test_evaluation_doc_references_bracket_tree_scrap_as_worked_example(self):
        """The doc references the scrapped single-elimination bracket-tree visualization
        as a concrete worked example of the current approach's ceiling, not just an
        abstract claim."""
        doc = _read_doc()
        assert "bracket" in doc.lower()
        assert "scrap" in doc.lower()

    def test_evaluation_doc_ends_with_single_clear_recommendation(self):
        """The doc contains one clear, unambiguous recommendation section — not a
        balanced "it depends" non-answer."""
        doc = _read_doc()
        assert "## Recommendation" in doc
        assert "it depends" not in doc.lower()

    def test_evaluation_doc_gates_migration_behind_approval_if_not_staying_vanilla(self):
        """If the doc's recommendation is anything other than "stay vanilla JS," it
        explicitly states that no migration work begins until the user reviews and
        approves the document."""
        doc = _read_doc()
        recommendation_section = doc.split("## Recommendation", 1)[1]
        stays_vanilla_only = (
            "adopt option (a)" in recommendation_section.lower()
            or "recommend staying vanilla" in recommendation_section.lower()
        )
        if not stays_vanilla_only:
            assert "approv" in recommendation_section.lower()
            assert "no migration" in recommendation_section.lower() or \
                   "no new-dependency work" in recommendation_section.lower() or \
                   "before any" in recommendation_section.lower()

    def test_evaluation_doc_is_documentation_only_no_frontend_or_backend_code_changed(self):
        """Producing the evaluation document does not modify any frontend/*.js,
        frontend/index.html, or backend/ file — this story is documentation-only.
        Checked here by asserting no framework-adoption markers (e.g. package.json,
        a bundler config) exist in frontend/, which would indicate code changes crept in."""
        assert not os.path.isfile(os.path.join(_FRONTEND_DIR, "package.json"))
        for name in os.listdir(_FRONTEND_DIR):
            assert "vite.config" not in name
            assert "webpack.config" not in name


# ===========================================================================
# Story: Validate the Recommendation with a Minimal Spike
# ===========================================================================

class TestSpikeImplementation:
    def test_alpine_loaded_via_cdn_script_tag_no_build_tooling(self):
        """Alpine.js is added the same way as the existing lucide.min.js tag — a plain
        <script> tag pointing at a CDN — not via package.json/npm/a bundler. This is the
        core cost claim from the evaluation's option (c): build-tooling cost stays zero."""
        html = _read(_INDEX_HTML_PATH)
        assert "alpinejs@" in html
        assert '<script defer src="https://cdn.jsdelivr.net/npm/alpinejs' in html
        assert not os.path.isfile(os.path.join(_FRONTEND_DIR, "package.json"))
        assert "node_modules" not in os.listdir(_FRONTEND_DIR)

    def test_howtoplay_tab_uses_alpine_directives_for_subtab_state(self):
        """The How to Play tab's subtab switching is declarative Alpine state
        (x-data/x-show/@click), not the imperative data-attribute matching used by the
        admin/main-nav tab bars — this is the spiked surface."""
        html = _read(_INDEX_HTML_PATH)
        assert 'x-data="{ howToPlayTab: \'users\' }"' in html
        for role in ("users", "players", "streamers", "developers"):
            assert f"howToPlayTab === '{role}'" in html

    def test_howtoplay_panels_use_x_cloak_to_avoid_flash_of_unstyled_content(self):
        """x-show alone would flash all four subtab panels visible simultaneously before
        Alpine initializes — x-cloak plus the [x-cloak] CSS rule prevents that, a real
        integration detail this spike surfaced (documented in the evaluation doc's
        "Spike Results" section)."""
        html = _read(_INDEX_HTML_PATH)
        assert html.count("x-cloak") >= 4
        css = _read(_STYLE_CSS_PATH)
        assert "[x-cloak]" in css and "display: none !important" in css

    def test_old_vanilla_howtoplay_tab_functions_removed(self):
        """switchHowToPlayTab()/initHowToPlayTabs() are removed from app-init.js, not left
        alongside the Alpine version as dead code — the spike replaces this one surface
        cleanly rather than running two competing implementations."""
        source = _read(_APP_INIT_PATH)
        assert "function switchHowToPlayTab" not in source
        assert "function initHowToPlayTabs" not in source
        assert "async function loadHowToPlay" in source  # unrelated logic (weights fetch) stays

    def test_other_tab_bars_remain_vanilla_js_unaffected(self):
        """The admin tab bar and main-nav tab switching are untouched vanilla JS —
        confirms hybrid coexistence rather than a wholesale rewrite triggered by the spike."""
        html = _read(_INDEX_HTML_PATH)
        assert 'class="admin-tab-btn" data-tab=' in html
        globals_js = _read(os.path.join(_FRONTEND_DIR, "app-globals.js"))
        assert "function switchTab(" in globals_js
        admin_init_js = _read(os.path.join(_FRONTEND_DIR, "app-admin.js"))
        assert "function initAdminTabs" in admin_init_js
        assert "x-data" not in admin_init_js and "x-show" not in admin_init_js
