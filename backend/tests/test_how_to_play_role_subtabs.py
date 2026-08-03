"""
Tests for plan-how-to-play-role-subtabs.

Covers the five user stories from markdown/plans/plan-how-to-play-role-subtabs.md.
This is a frontend-only restructuring (no new backend endpoints) of the existing
How to Play tab (`frontend/index.html` `#tab-howtoplay`, `frontend/app-init.js`
`loadHowToPlay()`) into four role-based subtabs — Users, Players, Streamers,
Developers — following the same pattern as the Admin panel's `.admin-tab-btn` /
`switchAdminTab()` (`frontend/app-admin.js:859-889`). Every stub below fails with
"not yet implemented" until the developer implements the plan; several stubs are
still real pytest functions that will assert against `frontend/index.html` /
`frontend/app-init.js` / `frontend/style.css` file contents once implemented (a
frontend-only feature is still string/regex-checkable via pytest, it just has no
DB or endpoint surface):

  Story: Role-Based How to Play Subtabs
    - The How to Play tab shows a row of four subtab buttons: Users, Players,
      Streamers, Developers
    - Exactly one subtab panel is visible at a time; clicking a button shows its
      panel and hides the others
    - The Users subtab is shown by default when the How to Play tab is first opened
    - Subtab switching is client-side only — no additional network request is made
      when switching
    - All four subtabs are visible regardless of login state (the tab remains
      public)
    - Existing content is preserved and reviewed for accuracy (failure case:
      subtab markup present but review left stale/incorrect statements in place)

  Story: Users Subtab
    - Contains the existing Getting Started content (drawing cards, roster/weekly
      lock, earning tokens)
    - Contains the existing Scoring & Modifiers content (live stat weight table,
      rarity bonus table, modifier table, MVP bonus value, loaded from GET /weights)
    - Contains the viewer half of the existing Twitch & MVP content (linking via
      Profile → Generate Twitch Code, token drops for linked viewers)
    - Renders correctly with no active session, since GET /weights is public
      (failure case: Users panel content gated behind an auth check)

  Story: Players Subtab
    - Explains linking a Dota 2 (OpenDota) player ID via the Profile tab
    - Explains what linking unlocks (tags as card stickers and leaderboard chips)
    - Explains that linking is optional and can be changed later from Profile
    - Clarifies that a player's real match performance counts toward other users'
      rosters without needing a Fantasy account (failure case: Players panel
      wrongly implies a Fantasy account is required for match stats to count)

  Story: Streamers Subtab
    - Explains how to apply during Twitch's "Local Test" status (developer-provided
      test install link)
    - Explains how to install (Twitch Extension Manager / test install link, no
      broadcaster-side URL configuration)
    - Explains how to use it (Quick Actions → Select match MVP → series → match →
      player → confirm)
    - Explains the effects of confirming an MVP (token drop to linked viewers,
      configurable fantasy score bonus)
    - Content matches markdown/features/core/twitch-extension.md, with no stale
      EBS URL configuration step presented as a broadcaster task (failure case:
      Streamers panel still tells broadcasters to set an EBS URL)

  Story: Developers Subtab
    - Summarises 4-6 notable, currently-accurate design decisions
    - Links out to README.md, markdown/features/README.md, and
      markdown/process-diagrams.md instead of duplicating their content
    - Does not restate implementation details already covered by other subtabs
      (failure case: Developers panel duplicates Users/Players/Streamers content
      instead of linking out)
"""

import os
import re

import pytest

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
INDEX_HTML_PATH = os.path.join(FRONTEND_DIR, "index.html")
APP_INIT_JS_PATH = os.path.join(FRONTEND_DIR, "app-init.js")
APP_GLOBALS_JS_PATH = os.path.join(FRONTEND_DIR, "app-globals.js")
STYLE_CSS_PATH = os.path.join(FRONTEND_DIR, "style.css")

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
README_PATH = os.path.join(REPO_ROOT, "README.md")
FEATURES_README_PATH = os.path.join(REPO_ROOT, "markdown", "features", "README.md")
PROCESS_DIAGRAMS_PATH = os.path.join(REPO_ROOT, "markdown", "process-diagrams.md")
TWITCH_EXTENSION_DOC_PATH = os.path.join(
    REPO_ROOT, "markdown", "features", "core", "twitch-extension.md"
)

ROLE_ORDER = ["users", "players", "streamers", "developers"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_panel(html, role):
    """Return the HTML slice for #howtoplay-panel-{role}, up to the next
    subtab panel (or the end of the How to Play tab if it's the last one)."""
    start = html.index(f'id="howtoplay-panel-{role}"')
    idx = ROLE_ORDER.index(role)
    if idx + 1 < len(ROLE_ORDER):
        end = html.index(f'id="howtoplay-panel-{ROLE_ORDER[idx + 1]}"')
    else:
        end = html.index("<!-- TAB: ADMIN -->")
    return html[start:end]


def _extract_js_function(js, name):
    """Return the body of a top-level JS function, relying on this codebase's
    convention of 2-space-indented function bodies (so a bare `\n}` with no
    leading whitespace only ever occurs at the function's true closing brace)."""
    match = re.search(rf"function {name}\([^)]*\)\s*{{(.*?)\n}}", js, re.S)
    assert match, f"{name}() not found in JS source"
    return match.group(1)


# ---------------------------------------------------------------------------
# Story: Role-Based How to Play Subtabs
# ---------------------------------------------------------------------------

class TestRoleBasedHowToPlaySubtabs:

    def test_howtoplay_tab_shows_four_role_subtab_buttons(self):
        """The How to Play tab shows a row of four subtab buttons: Users, Players,
        Streamers, Developers (e.g. `.howtoplay-tab-btn` elements in
        frontend/index.html with data-tab values users/players/streamers/developers)."""
        html = _read(INDEX_HTML_PATH)
        buttons = re.findall(r'<button class="howtoplay-tab-btn" data-tab="(\w+)">', html)
        assert len(buttons) == 4
        assert set(buttons) == set(ROLE_ORDER)

    def test_clicking_subtab_button_shows_only_that_panel(self):
        """Clicking a `.howtoplay-tab-btn` shows its matching `#howtoplay-panel-*`
        panel and hides the other three — exactly one panel visible at a time,
        mirroring switchAdminTab()'s [data-admin-tab] show/hide logic."""
        html = _read(INDEX_HTML_PATH)
        panel_roles = re.findall(r'id="howtoplay-panel-(\w+)"\s+data-howtoplay-tab="(\w+)"', html)
        assert len(panel_roles) == 4
        for panel_id_role, data_role in panel_roles:
            assert panel_id_role == data_role
        assert sorted(r for r, _ in panel_roles) == sorted(ROLE_ORDER)

        js = _read(APP_INIT_JS_PATH)
        body = _extract_js_function(js, "switchHowToPlayTab")
        # Toggles panels via the shared data-howtoplay-tab attribute and hides
        # non-matching ones (mirrors switchAdminTab's data-admin-tab pattern)
        assert "data-howtoplay-tab" in body
        assert "'none'" in body

    def test_users_subtab_shown_by_default_on_tab_open(self):
        """The Users subtab panel is visible by default the first time the How to
        Play tab is opened (switchHowToPlayTab('users') called on tab init,
        mirroring switchTab('howtoplay') always defaulting to the Users panel)."""
        js = _read(APP_INIT_JS_PATH)
        init_body = _extract_js_function(js, "initHowToPlayTabs")
        assert "switchHowToPlayTab('users')" in init_body

        load_body = _extract_js_function(js, "loadHowToPlay")
        assert "initHowToPlayTabs()" in load_body

        globals_js = _read(APP_GLOBALS_JS_PATH)
        howtoplay_lines = [l for l in globals_js.splitlines() if '"howtoplay"' in l]
        assert howtoplay_lines, "switchTab('howtoplay') dispatch not found"
        assert "loadHowToPlay()" in howtoplay_lines[0]

    def test_subtab_switching_is_client_side_only_no_network_request(self):
        """Switching between How to Play subtabs does not trigger any additional
        fetch()/XHR call — subtab switching only toggles panel visibility and
        button active state in frontend/app-init.js, it does not re-call
        loadHowToPlay() or hit any endpoint."""
        js = _read(APP_INIT_JS_PATH)
        body = _extract_js_function(js, "switchHowToPlayTab")
        assert "fetch(" not in body
        assert "XMLHttpRequest" not in body
        assert "loadHowToPlay(" not in body

    def test_all_four_subtabs_visible_regardless_of_login_state(self):
        """All four How to Play subtab buttons and panels render whether or not a
        session/auth token is present — the tab remains fully public, matching
        current behaviour (no auth-gated markup around #tab-howtoplay)."""
        globals_js = _read(APP_GLOBALS_JS_PATH)
        howtoplay_lines = [l for l in globals_js.splitlines() if '"howtoplay"' in l]
        assert howtoplay_lines
        # Unlike the admin dispatch (which early-returns for non-admins), the
        # howtoplay dispatch must carry no auth guard
        assert "activeUserId" not in howtoplay_lines[0]
        assert "activeIsAdmin" not in howtoplay_lines[0]

        html = _read(INDEX_HTML_PATH)
        assert 'id="tab-howtoplay"' in html
        for role in ROLE_ORDER:
            assert f'id="howtoplay-panel-{role}"' in html

    def test_existing_content_preserved_and_accurate_after_restructure(self):
        """Existing content (Getting Started, Twitch & MVP viewer/broadcaster
        split, Scoring & Modifiers with live GET /weights values) is preserved
        across the four new subtabs and factually matches the current codebase
        (e.g. roster size of 5, no stale claims) rather than being dropped or
        left outdated during the restructure."""
        html = _read(INDEX_HTML_PATH)
        assert "Getting Started" in html
        assert "5 cards" in html
        assert "howtoplay-stats-tbody" in html
        assert "howtoplay-rarity-tbody" in html
        assert "howtoplay-mods-tbody" in html
        assert "howtoplay-mvp-bonus" in html
        assert "Generate Twitch Code" in html
        assert "Select match MVP" in html
        # Corrected during the content audit: cards are generated per-draw, not
        # pulled from a shared pre-built deck (see reference/dynamic-card-creation.md)
        assert "shared seasonal deck" not in html


# ---------------------------------------------------------------------------
# Story: Users Subtab
# ---------------------------------------------------------------------------

class TestUsersSubtab:

    def test_users_subtab_contains_getting_started_content(self):
        """#howtoplay-panel-users contains the existing Getting Started content:
        drawing cards, roster/weekly lock, earning tokens."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "users")
        assert "Getting Started" in panel
        assert "Draw a card" in panel
        assert "5 cards" in panel
        assert "locks automatically" in panel
        assert "token" in panel.lower()

    def test_users_subtab_contains_scoring_and_modifiers_content(self):
        """#howtoplay-panel-users contains the Scoring & Modifiers content: the
        live stat weight table (#howtoplay-stats-tbody), rarity bonus table
        (#howtoplay-rarity-tbody), modifier table (#howtoplay-mods-tbody), and MVP
        bonus value (#howtoplay-mvp-bonus), all populated from GET /weights via
        loadHowToPlay()."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "users")
        assert 'id="howtoplay-stats-tbody"' in panel
        assert 'id="howtoplay-rarity-tbody"' in panel
        assert 'id="howtoplay-mods-tbody"' in panel
        assert 'id="howtoplay-mvp-bonus"' in panel

        js = _read(APP_INIT_JS_PATH)
        load_body = _extract_js_function(js, "loadHowToPlay")
        assert "/weights" in load_body
        assert "howtoplay-stats-tbody" in load_body
        assert "howtoplay-rarity-tbody" in load_body
        assert "howtoplay-mods-tbody" in load_body
        assert "howtoplay-mvp-bonus" in load_body

    def test_users_subtab_contains_viewer_linking_content(self):
        """#howtoplay-panel-users contains the viewer half of the existing Twitch
        & MVP content: linking a Fantasy account via Profile → Generate Twitch
        Code, and that watching linked streams makes a viewer eligible for token
        drops."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "users")
        assert "Generate Twitch Code" in panel
        assert "Profile" in panel
        assert "token drop" in panel.lower() or "eligible" in panel.lower()

    def test_users_subtab_renders_with_no_active_session(self):
        """The Users subtab renders correctly (including populated weight tables)
        with no active session, since loadHowToPlay()'s GET /weights call is a
        public endpoint requiring no auth header."""
        js = _read(APP_INIT_JS_PATH)
        load_body = _extract_js_function(js, "loadHowToPlay")
        assert "${API}/weights" in load_body
        assert "activeUserId" not in load_body
        assert "Authorization" not in load_body
        assert "headers" not in load_body


# ---------------------------------------------------------------------------
# Story: Players Subtab
# ---------------------------------------------------------------------------

class TestPlayersSubtab:

    def test_players_subtab_explains_dota2_player_id_linking(self):
        """#howtoplay-panel-players explains that a Kanaliiga player who also
        wants a Fantasy account can link the two via Profile tab → enter Dota 2
        (OpenDota) player ID."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "players")
        assert "Profile" in panel
        assert "OpenDota" in panel
        assert "player ID" in panel or "player id" in panel.lower()

    def test_players_subtab_explains_what_linking_unlocks(self):
        """#howtoplay-panel-players explains that linking unlocks admin-granted
        tags appearing as card stickers and leaderboard chips, per
        reference/player-linking-and-tag-visibility.md."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "players")
        assert "sticker" in panel.lower()
        assert "chip" in panel.lower()
        assert "tag" in panel.lower()
        assert "leaderboard" in panel.lower()

    def test_players_subtab_explains_linking_is_optional_and_changeable(self):
        """#howtoplay-panel-players explains that linking is optional and can be
        changed later from the Profile tab."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "players")
        assert "optional" in panel.lower()
        assert "changed" in panel.lower() or "change" in panel.lower()

    def test_players_subtab_clarifies_match_performance_counts_without_linking(self):
        """#howtoplay-panel-players clarifies that a player does not need a
        Fantasy account for their real match performance to count toward other
        users' rosters — only linking affects their own tags/stickers (failure
        case: content wrongly implies a Fantasy account is required for match
        stats to count toward other users)."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "players")
        assert "match performance to count" in panel.lower()
        assert "fantasy account" in panel.lower()
        assert "don't need" in panel.lower() or "do not need" in panel.lower() or "doesn't need" in panel.lower() or "does not need" in panel.lower()


# ---------------------------------------------------------------------------
# Story: Streamers Subtab
# ---------------------------------------------------------------------------

class TestStreamersSubtab:

    def test_streamers_subtab_explains_local_test_application_process(self):
        """#howtoplay-panel-streamers explains that while the extension is in
        Twitch's "Local Test" status, a broadcaster needs a developer-provided
        test install link to whitelist their channel, and that this step is not
        needed once publicly released."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "streamers")
        assert "Local Test" in panel
        assert "test install link" in panel
        assert "publicly released" in panel.lower()

    def test_streamers_subtab_explains_installation_steps(self):
        """#howtoplay-panel-streamers explains how to install: add the extension
        from the Twitch Extension Manager (or via the test install link), with no
        URL configuration required on the broadcaster's side."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "streamers")
        assert "Extension Manager" in panel
        assert "no url configuration" in panel.lower()

    def test_streamers_subtab_explains_mvp_selection_flow(self):
        """#howtoplay-panel-streamers explains how to use it: Quick Actions (Live
        Config view in Twitch Stream Manager) → Select match MVP → series →
        match → player → confirm."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "streamers")
        assert "Quick Actions" in panel
        assert "Select match MVP" in panel
        assert "series" in panel.lower()
        assert "confirm" in panel.lower()

    def test_streamers_subtab_explains_mvp_confirmation_effects(self):
        """#howtoplay-panel-streamers explains the effects of confirming an MVP:
        automatic one-time token drop to eligible linked viewers, and a
        configurable fantasy score bonus applied to that player for that match."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "streamers")
        assert "token drop" in panel.lower()
        assert "one-time" in panel.lower()
        assert "fantasy score bonus" in panel.lower()

    def test_streamers_subtab_content_matches_twitch_extension_doc_no_stale_ebs_step(self):
        """#howtoplay-panel-streamers content matches
        markdown/features/core/twitch-extension.md with no stale steps — in
        particular no mention of manually setting an EBS URL, which is a
        one-time operator task, not a broadcaster task (failure case: panel
        still instructs broadcasters to configure an EBS URL)."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "streamers")
        assert "EBS" not in panel
        assert "set-ebs-url" not in panel

        doc = _read(TWITCH_EXTENSION_DOC_PATH)
        assert "Broadcasters do **not** configure the EBS URL" in doc
        # Sanity: the doc's broadcaster-facing flow matches what the panel says
        assert "Select match MVP" in doc
        assert "Quick Actions" in doc


# ---------------------------------------------------------------------------
# Story: Developers Subtab
# ---------------------------------------------------------------------------

class TestDevelopersSubtab:

    def test_developers_subtab_summarises_design_decisions(self):
        """#howtoplay-panel-developers summarises 4-6 notable, currently-accurate
        design decisions (e.g. dynamic per-draw card generation instead of a
        shared static pool, SQLite with an online-backup safety net, admin-driven
        season lifecycle instead of env-var season boundaries, demo mode for
        reproducing the season lifecycle on demand)."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "developers")
        decisions = re.findall(r"<li><strong>(.*?)</strong>", panel)
        assert 4 <= len(decisions) <= 6

    def test_developers_subtab_links_to_readme_docs_and_process_diagrams(self):
        """#howtoplay-panel-developers links out to README.md,
        markdown/features/README.md, and markdown/process-diagrams.md rather
        than duplicating their content."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "developers")
        assert "README.md" in panel
        assert "markdown/features/README.md" in panel
        assert "markdown/process-diagrams.md" in panel
        assert "<a href=" in panel

        # The linked files must actually exist in the repo
        assert os.path.exists(README_PATH)
        assert os.path.exists(FEATURES_README_PATH)
        assert os.path.exists(PROCESS_DIAGRAMS_PATH)

    def test_developers_subtab_does_not_duplicate_other_subtab_content(self):
        """#howtoplay-panel-developers does not restate implementation details
        already covered by Users/Players/Streamers subtabs — it stays scoped to
        high-level rationale (failure case: Developers panel re-explains e.g. the
        MVP selection flow verbatim instead of linking to the Streamers subtab
        or twitch-extension.md)."""
        panel = _extract_panel(_read(INDEX_HTML_PATH), "developers")
        assert "Quick Actions" not in panel
        assert "Select match MVP" not in panel
        assert "OpenDota" not in panel
        assert "howtoplay-stats-tbody" not in panel
        assert "Generate Twitch Code" not in panel
