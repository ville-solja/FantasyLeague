"""
Tests for plan-issue-108-kana-hub-integration-feasibility.md (resolves GitHub issue #108).

The deliverable is a decision document, not backend behaviour, so every test is a static
file-content assertion against
markdown/features/reference/kana-hub-integration-feasibility.md, with no `db` fixture and no
API/router imports. This follows the pattern in test_frontend_framework_evaluation.py.

The tests also check the product owner's clarifications (2026-10-02) recorded in the plan:
  - the hub's CS2 fantasy league is a separate product, not a competitor; Kana Cards would
    be the Dota fantasy next to it,
  - licensing is not a concern (both are hobby projects),
  - the Dota schedule is likely to move to the hub, which makes it a dependency,
  - the linked-account count is not decisive, so the document states that instead of a count,
  - the document explains the hub's per-game structure and where Dota fits in it,
  - moving to Steam login (Option A, or a Steam-only Option B) removes Kana Cards' password,
    reset-email (SMTP) and lockout handling, and the document lists what becomes removable.

Covers the four user stories:
  Story: Feasibility Document
  Story: Integration Options and Recommendation
  Story: Questions for the Hub Team
  Story: Account Bridging Check

Criteria left for manual review (not statically checkable): the quality and reasoning of the
recommendation, whether the first step fits in one sprint, whether the document is
understandable without reading either codebase, whether every hub claim is backed by the cited
file.

Run with: cd backend && python -m pytest tests/test_issue_108_kana_hub_integration_feasibility.py -v
"""

import glob
import os
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DOC_PATH = os.path.join(_REPO_ROOT, "markdown", "features", "reference",
                         "kana-hub-integration-feasibility.md")

# Steam64 = Steam32 (OpenDota account id) + this offset. It is the only 17-digit number
# allowed in the document.
STEAM64_OFFSET = "76561197960265728"


def _read_doc() -> str:
    with open(_DOC_PATH) as f:
        return f.read()


def _section(doc: str, heading_pattern: str) -> str:
    """Body of the first markdown heading (any level) matching `heading_pattern`,
    up to the next heading of the same or a higher level."""
    m = re.search(r"^(#{1,6}) +" + heading_pattern + r".*$", doc, re.MULTILINE | re.IGNORECASE)
    assert m, f"heading matching {heading_pattern!r} not found"
    level = len(m.group(1))
    nxt = re.compile(r"^#{1,%d} " % level, re.MULTILINE)
    end = nxt.search(doc, m.end())
    return doc[m.end():end.start() if end else len(doc)]


def _option(doc: str, letter: str) -> str:
    return _section(doc, r"Option " + letter + r" \u2014")


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or re.match(r"^\|[\s|:-]+\|$", line):
            continue
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def _local_db_paths() -> list[str]:
    data_dir = os.path.join(_REPO_ROOT, "data")
    paths = [os.path.join(data_dir, "fantasy.db")]
    paths += sorted(glob.glob(os.path.join(data_dir, "fantasy.db.backup-*")), reverse=True)
    return [p for p in paths if os.path.isfile(p)]


def _read_usernames_readonly() -> list[str] | None:
    """Usernames from the first readable local database copy, opened read-only.
    None when no local database copy can be read."""
    for path in _local_db_paths():
        try:
            conn = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
            try:
                return [r[0] for r in conn.execute("SELECT username FROM users") if r[0]]
            finally:
                conn.close()
        except sqlite3.Error:
            continue
    return None


# ===========================================================================
# Story: Feasibility Document
# ===========================================================================

class TestFeasibilityDocument:
    def test_feasibility_doc_exists_at_expected_path(self):
        """The document lives at markdown/features/reference/kana-hub-integration-feasibility.md."""
        assert os.path.isfile(_DOC_PATH)
        assert _read_doc().startswith("# Kana Hub Integration Feasibility")

    def test_feasibility_doc_stub_markers_removed(self):
        """The stub is filled in: no '*(planned)*' markers and no 'This document is a stub
        created at feature planning time' footer remain."""
        doc = _read_doc()
        assert "*(planned)*" not in doc
        assert "This document is a stub created at feature planning time" not in doc

    def test_feasibility_doc_compares_systems_by_area(self):
        """The document compares the two systems area by area: stack, data model (database),
        identity, game data, fantasy design, background jobs, Twitch, hosting and licence."""
        comparison = _section(_read_doc(), r"1\. How the two systems compare")
        areas = {row[0].strip("* ").lower() for row in _table_rows(comparison)}
        for area in ("stack", "data model (database)", "identity", "game data",
                     "fantasy design", "background jobs", "twitch", "hosting", "licence"):
            assert area in areas, f"comparison table has no {area!r} row"

    def test_feasibility_doc_cites_hub_commit_sha_and_branch(self):
        """The document names the hub commit it was checked against (a 40-hex SHA) and the
        branch (`development`) and date."""
        sources = _section(_read_doc(), r"Sources checked")
        assert re.search(r"\b[0-9a-f]{40}\b", sources)
        assert "`development`" in sources
        assert re.search(r"\b20\d\d-\d\d-\d\d\b", sources)

    def test_feasibility_doc_cites_hub_file_paths(self):
        """Hub claims cite concrete file paths in the eggosystem repository (e.g. paths under
        `apps/backend/` or `apps/frontend/`, migrations, auth middleware)."""
        doc = _read_doc()
        for path in ("apps/backend/src/routes/index.ts",
                     "apps/backend/src/middlewares/auth.middleware.ts",
                     "apps/backend/migrations/20251124000001_create_fantasy_league_tables.ts",
                     "apps/backend/migrations/20250623152817_add_more_steam_games.ts",
                     "apps/frontend/src/app/(embed)/calendar/page.tsx",
                     "docker-compose.prod.yml"):
            assert f"`{path}`" in doc, path
        assert len(set(re.findall(r"`(apps/(?:backend|frontend)/[^`]+)`", doc))) >= 15

    def test_feasibility_doc_cites_kana_cards_files(self):
        """Kana Cards claims cite concrete files or docs from this repository (e.g.
        `backend/` modules or `markdown/features/` docs)."""
        doc = _read_doc()
        for path in ("backend/schedule.py", "backend/ingest.py", "backend/card_points.py",
                     "backend/sessions.py", "backend/twitch.py", "backend/match_scoring.py",
                     "backend/card_draw.py"):
            assert f"`{path}`" in doc, path
            assert os.path.isfile(os.path.join(_REPO_ROOT, path)), path
        for ref in re.findall(r"`(markdown/features/[^`]+\.md)`", doc):
            assert os.path.isfile(os.path.join(_REPO_ROOT, ref)), ref

    def test_feasibility_doc_lists_blockers_with_severity(self):
        """There is an architectural blockers section, and blockers carry severity labels
        from the set blocker / major / minor, each with what would remove it."""
        blockers = _section(_read_doc(), r"4\. Architectural blockers")
        rows = [r for r in _table_rows(blockers) if r[0].isdigit()]
        assert len(rows) >= 5
        header = _table_rows(blockers)[0]
        sev = header.index("Severity")
        fix = header.index("What removes it")
        for row in rows:
            assert re.match(r"(blocker|major|minor)\b", row[sev]), row
            assert len(row[fix]) > 20, row

    def test_feasibility_doc_blockers_cover_required_items(self):
        """The blockers list covers at least: stack rewrite, Dota seasons and match data not
        yet in the hub, identity (account) migration, and the Twitch EBS move."""
        blockers = _section(_read_doc(), r"4\. Architectural blockers").lower()
        assert "stack rewrite" in blockers
        assert "dota seasons, teams and schedule are not in the hub" in blockers
        assert "dota match data is not in the hub" in blockers
        assert "identity (account) migration" in blockers
        assert "twitch ebs move" in blockers

    def test_feasibility_doc_lists_hub_dota_schedule_dependency(self):
        """The document lists the dependency on the hub's Dota schedule work (the Dota
        schedule moving to the hub), per the product owner's clarification."""
        doc = _read_doc()
        blockers = _section(doc, r"4\. Architectural blockers").lower()
        assert "dependency on the hub's dota schedule work" in blockers
        ordering = _section(doc, r"8\. Toward a single tournament site").lower()
        assert "dota season, teams and schedule in the hub" in ordering

    def test_feasibility_doc_states_whether_hub_ingests_dota_data(self):
        """The document confirms or corrects whether the hub ingests any Dota data
        (`Games` id 4 / app 570) and describes how the hub's fantasy league scores."""
        doc = _read_doc()
        findings = _section(doc, r"3\. Preliminary findings").lower()
        assert "id 4" in findings and "570" in findings
        assert "the hub ingests no dota data" in findings
        scoring = _section(doc, r"How the hub's fantasy league scores").lower()
        for term in ("kanarating", "team result", "role", "budget"):
            assert term in scoring, term

    def test_feasibility_doc_cs2_fantasy_described_as_separate(self):
        """Per the clarification, the hub's CS2 fantasy league is described as a separate
        product that Kana Cards does not compete with; Kana Cards is the Dota fantasy."""
        doc = _read_doc()
        placement = _section(doc, r"7\. Kana Cards next to the CS2 fantasy").lower()
        assert "separate products" in placement
        assert "kana cards is the dota fantasy game" in placement
        assert "do not compete" in doc.lower()

    def test_feasibility_doc_explains_hub_per_game_structure(self):
        """The document explains how the hub is organised per game (registry, per-game backend
        domains, per-game fantasy namespace, season routes), citing hub files, and is listed
        in the Contents."""
        doc = _read_doc()
        assert "(#2-how-the-hub-is-organised-per-game-and-where-dota-fits)" in _section(doc, r"Contents")
        structure = _section(doc, r"2\. How the hub is organised per game, and where Dota fits")
        for path in ("PUBG-WORKFLOW.md",
                     "apps/frontend/src/lib/games/registry.ts",
                     "apps/frontend/src/lib/games/game-hub-path.ts",
                     "apps/backend/src/games/domain-boundaries.test.ts",
                     "apps/backend/src/games/fantasy/cs/",
                     "apps/frontend/src/app/(main)/(content-container)/seasons/[season]/"):
            assert f"`{path}`" in structure, path
        for term in ("`OrganizerGames`", "`is_default`", "`x-organizer-slug`", "`x-game-slug`",
                     "`GameCapabilities`", "`LinkedAccounts`"):
            assert term in structure, term

    def test_feasibility_doc_aligns_dota_with_hub_structure(self):
        """The document says where Dota fits: a `dota` registry entry (gameId 4, appId 570,
        h2h, caps.fantasy true), a `games/dota/` domain, the fantasy as `games/fantasy/dota/`
        (A) or an external link (C), the Dota schedule URL, and no extra account link."""
        structure = _section(_read_doc(), r"2\. How the hub is organised per game, and where Dota fits")
        assert "gameId 4, appId 570, matchModel `h2h`, `caps.fantasy: true`" in structure
        assert "`apps/backend/src/games/dota/`" in structure
        assert "`apps/backend/src/games/fantasy/dota/`" in structure
        assert "`/{organizer}/dota/seasons/{id}/schedule`" in structure
        assert "Simpler than PUBG" in structure

    def test_feasibility_doc_maps_kana_cards_parts_to_hub_layers(self):
        """Kana Cards parts map to hub layers: ingest/teams/players/schedule to games/dota,
        cards/rosters/scoring/tokens/Twitch to games/fantasy/dota, accounts/login to hub core."""
        mapping = _section(_read_doc(), r"Which Kana Cards part belongs to which hub layer")
        rows = _table_rows(mapping)
        layer = {path: row[-1] for row in rows[1:]
                 for path in re.findall(r"`(backend/[^`]+)`", row[1])}
        for path in ("backend/ingest.py", "backend/schedule.py", "backend/enrich.py"):
            assert layer[path].startswith("`games/dota/`"), path
        for path in ("backend/card_draw.py", "backend/match_scoring.py", "backend/card_points.py",
                     "backend/weeks.py", "backend/twitch.py"):
            assert layer[path].startswith("`games/fantasy/dota/`"), path
        for path in ("backend/auth.py", "backend/sessions.py", "backend/email_utils.py"):
            assert layer[path].startswith("Hub core"), path

    def test_feasibility_doc_licence_not_a_blocker(self):
        """Failure path: per the clarification, licensing is not a concern. The licence row
        says so, and no blocker entry is about the licence (GPL-3.0 / licensing)."""
        doc = _read_doc()
        comparison = _section(doc, r"1\. How the two systems compare")
        licence_row = next(r for r in _table_rows(comparison) if r[0].strip("* ").lower() == "licence")
        assert "not a concern" in " ".join(licence_row).lower()
        blockers = _section(doc, r"4\. Architectural blockers").lower()
        assert "gpl" not in blockers
        assert "licen" not in blockers


# ===========================================================================
# Story: Integration Options and Recommendation
# ===========================================================================

class TestIntegrationOptions:
    def test_options_a_to_d_present(self):
        """At least four options are compared: (A) full port into the eggosystem, (B) shared
        hub (Steam) login and identity, (C) link/embed plus API data exchange, (D) no
        integration."""
        doc = _read_doc()
        assert re.search(r"^### Option A \u2014 Full port into the Eggosystem", doc, re.MULTILINE)
        assert re.search(r"^### Option B \u2014 .*Steam login", doc, re.MULTILINE)
        assert re.search(r"^### Option C \u2014 Link or embed .*APIs", doc, re.MULTILINE)
        assert re.search(r"^### Option D \u2014 No integration", doc, re.MULTILINE)

    def test_each_option_lists_user_visible_result(self):
        """Each of options A-D states what users see."""
        doc = _read_doc()
        for letter in "ABCD":
            assert "**What users see:**" in _option(doc, letter), letter

    def test_each_option_has_tshirt_effort_sizes(self):
        """Each option gives work in t-shirt sizes per area, using only S / M / L / XL."""
        doc = _read_doc()
        for letter in "ABCD":
            rows = _table_rows(_option(doc, letter))
            header = rows[0]
            assert header[:2] == ["Area", "Size"], (letter, header)
            sizes = [r[1] for r in rows[1:]]
            assert sizes, letter
            assert all(size in {"S", "M", "L", "XL"} for size in sizes), (letter, sizes)

    def test_each_option_lists_risks(self):
        """Each of options A-D lists its risks."""
        doc = _read_doc()
        for letter in "ABCD":
            assert "**Risks:**" in _option(doc, letter), letter

    def test_each_option_describes_data_and_twitch_impact(self):
        """Each option states what happens to existing data (accounts, cards, history) and
        the effect on the Twitch extension."""
        doc = _read_doc()
        for letter in "ABCD":
            body = _option(doc, letter)
            assert "**Existing data (accounts, cards, history):**" in body, letter
            assert "**Twitch extension:**" in body, letter

    def test_option_c_includes_reading_hub_schedule(self):
        """Option C includes Kana Cards reading the Dota schedule, teams and results from the
        hub once they move there (e.g. via the existing `SCHEDULE_FIXTURES_URL` feed)."""
        body = _option(_read_doc(), "C")
        assert "SCHEDULE_FIXTURES_URL" in body
        assert "reads the Dota schedule, teams and results from the hub" in body

    def test_doc_lists_login_code_removable_with_steam_login(self):
        """The document lists what Steam login removes from Kana Cards (files, endpoints, env
        vars), checked against this repository: cited files exist and cited env vars are in
        .env.example."""
        removable = _section(_read_doc(), r"What Steam login removes from Kana Cards")
        for item in ("`backend/email_utils.py`", "`POST /register`", "`POST /forgot-password`",
                     "`POST /reset-password`", "`PUT /profile/password`", "`SMTP_HOST`",
                     "`LOGIN_LOCKOUT_THRESHOLD`", "`FORGOT_PASSWORD_COOLDOWN_SECONDS`",
                     "`password_reset_tokens`", "`bcrypt`"):
            assert item in removable, item
        for path in re.findall(r"`((?:backend|frontend|markdown)/[^`*]+)`", removable):
            assert os.path.exists(os.path.join(_REPO_ROOT, path)), path
        for name in re.findall(r"`(test_[a-z0-9_]+\.py)`", removable):
            assert os.path.isfile(os.path.join(_REPO_ROOT, "backend", "tests", name)), name
        with open(os.path.join(_REPO_ROOT, ".env.example")) as f:
            env_example = f.read()
        table = "\n".join(l for l in removable.splitlines() if l.startswith("| Env vars"))
        for var in re.findall(r"`([A-Z][A-Z0-9_]+)`", table):
            assert var in env_example, var

    def test_doc_states_steam_login_scope_and_tradeoff(self):
        """Under Option A the session layer (`backend/sessions.py`) is replaced too, under a
        Steam-only Option B it stays; the trade-off (every player needs a Steam account,
        existing accounts claimed between seasons) is stated."""
        removable = _section(_read_doc(), r"What Steam login removes from Kana Cards")
        assert "**What stays under Option B1:**" in removable
        assert "**Under Option A**" in removable
        assert "`backend/sessions.py`" in removable
        assert "needs a Steam account" in removable
        assert "claim between seasons" in removable

    def test_options_a_and_c_place_dota_in_hub_layers(self):
        """Option A ports into `games/dota/` and `games/fantasy/dota/`; Option C keeps the
        fantasy external, with the hub owning the Dota registry entry and `games/dota/`.
        Option B is offered as Steam-only."""
        doc = _read_doc()
        a = _option(doc, "A")
        assert "`games/dota/`" in a and "`games/fantasy/dota/`" in a
        c = _option(doc, "C")
        assert "`caps.fantasy: true`" in c and "`games/dota/`" in c
        assert "no `games/fantasy/dota/` in the hub" in c
        assert "**Steam-only**" in _option(doc, "B")

    def test_recommendation_includes_steam_only_login_between_seasons(self):
        """The recommendation pairs Option C with a Steam-only Option B1 between seasons and
        keeps the earlier decisions (between seasons, visual alignment)."""
        doc = _read_doc()
        rec = _section(doc, r"6\. Recommendation")
        assert "Choose Option C, switch Kana Cards to Steam-only login (Option B1)" in rec
        timing = _section(doc, r"Timing: between seasons")
        assert "switching off password login" in timing
        assert "visual alignment" in timing

    def test_recommendation_names_option_and_first_step(self):
        """There is a recommendation section that names one of options A-D, gives reasons,
        and names a concrete first step."""
        rec = _section(_read_doc(), r"6\. Recommendation")
        assert re.search(r"Choose Option [ABCD]\b", rec)
        assert "Reasons:" in rec
        first_step = _section(_read_doc(), r"First step")
        assert re.search(r"^1\. ", first_step, re.MULTILINE)

    def test_doc_describes_placement_next_to_cs2_fantasy(self):
        """The document describes how Kana Cards sits next to the hub's CS2 fantasy league as
        the Dota game (navigation, account, leaderboard presentation), both staying separate
        products."""
        placement = _section(_read_doc(), r"7\. Kana Cards next to the CS2 fantasy")
        aspects = {r[0].strip("* ").lower() for r in _table_rows(placement)}
        for aspect in ("navigation", "account", "leaderboards"):
            assert aspect in aspects, aspect
        assert "separate products" in placement.lower()

    def test_doc_describes_single_tournament_site_ordering(self):
        """The document describes what a single tournament site needs, in order: Dota season,
        teams and schedule in the hub first, then fantasy linked or embedded."""
        ordering = _section(_read_doc(), r"8\. Toward a single tournament site")
        steps = re.findall(r"^(\d+)\. (.*)$", ordering, re.MULTILINE)
        assert len(steps) >= 3
        texts = [t.lower() for _, t in steps]
        schedule_idx = next(i for i, t in enumerate(texts) if "dota season, teams and schedule in the hub" in t)
        fantasy_idx = next(i for i, t in enumerate(texts) if "links the dota fantasy" in t or "embed" in t)
        assert schedule_idx == 0
        assert schedule_idx < fantasy_idx


# ===========================================================================
# Story: Questions for the Hub Team
# ===========================================================================

class TestHubTeamQuestions:
    def test_questions_section_present(self):
        """There is a 'Questions for the hub team' section with a list of questions."""
        questions = _section(_read_doc(), r"9\. Questions for the hub team")
        rows = [r for r in _table_rows(questions) if r[0].isdigit()]
        assert len(rows) >= 4

    def test_questions_cover_schedule_api_dota_data_and_hosting(self):
        """The questions cover: when Dota seasons/teams/schedule arrive in the hub, a public
        API (`/api/v2`) Kana Cards could read, whether Dota match data is wanted in the hub,
        and hosting / SSO / link-or-embed options for external services."""
        questions = _section(_read_doc(), r"9\. Questions for the hub team").lower()
        assert "dota seasons, teams and the schedule" in questions
        assert "`/api/v2`" in questions
        assert "dota match data" in questions
        assert "hosting" in questions and "sso" in questions
        assert "link to, or embed" in questions

    def test_each_question_names_affected_option_or_blocker(self):
        """Each question says which option (A-D) or blocker it affects."""
        questions = _section(_read_doc(), r"9\. Questions for the hub team")
        header = _table_rows(questions)[0]
        assert header[-1] == "Affects"
        rows = [r for r in _table_rows(questions) if r[0].isdigit()]
        for row in rows:
            assert re.search(r"(Option|Options) [ABCD]|Blockers? \d", row[-1]), row


# ===========================================================================
# Story: Account Bridging Check
# ===========================================================================

class TestAccountBridging:
    def test_account_bridging_section_explains_steam_offset(self):
        """An account bridging section explains Steam32 <-> Steam64: OpenDota account id +
        76561197960265728 = Steam64."""
        bridging = _section(_read_doc(), r"10\. Account bridging")
        assert "Steam64 = Steam32 + " + STEAM64_OFFSET in bridging
        assert "OpenDota account ID" in bridging

    def test_account_bridging_states_count_not_decisive(self):
        """Per the product owner, the linked-ID count does not matter: the section says the
        count is not decisive because the architecture is the same either way, and the
        document no longer asks for a count to be run on a production backup."""
        doc = _read_doc()
        bridging = _section(doc, r"10\. Account bridging")
        note = _section(bridging, r"The linked-ID count is not decisive").lower()
        assert "does not change any decision" in note
        assert "the same whatever the count" in note
        assert not re.search(r"Users with a linked player ID[^|]*\| \d+ \|", doc)
        assert "mode=ro" not in doc
        assert "production backup" not in doc.lower()

    def test_account_bridging_covers_unlinked_users_and_twitch_links(self):
        """The section describes what happens to users without a linked ID (e.g. a one-time
        Steam link step) and to Twitch links."""
        bridging = _section(_read_doc(), r"10\. Account bridging")
        unlinked = _section(bridging, r"Users without a linked ID")
        assert "Link Steam" in unlinked
        twitch = _section(bridging, r"Twitch links")
        assert "twitch_user_id" in twitch

    def test_doc_contains_no_email_addresses(self):
        """Failure path: no personal data. The document contains no email addresses."""
        assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", _read_doc())

    def test_doc_contains_no_steam64_ids_except_offset(self):
        """Failure path: no personal data. The only 17-digit number in the document is the
        Steam64 offset constant 76561197960265728."""
        numbers = set(re.findall(r"(?<!\d)\d{17}(?!\d)", _read_doc()))
        assert numbers <= {STEAM64_OFFSET}, "unexpected 17-digit number in the document"

    def test_doc_contains_no_database_usernames(self):
        """Failure path: no personal data. No username from the Kana Cards database appears
        in the document (check against usernames in a local DB if one is available,
        otherwise skip)."""
        usernames = _read_usernames_readonly()
        if usernames is None:
            pytest.skip("no readable local Kana Cards database copy")
        doc = _read_doc()
        leaked = [u for u in usernames
                  if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(u) + r"(?![A-Za-z0-9_-])", doc)]
        # Report only the count, never the names.
        assert not leaked, f"{len(leaked)} database username(s) appear in the document"


# ===========================================================================
# Story: Integration Options and Recommendation — Option A in depth
# (product-owner request, 2026-10-02: a much deeper evaluation of the full port)
# ===========================================================================

# A hub claim cites a path in the Eggosystem repository: an app or package path, CI or
# compose file, ops config, hub doc or one of the hub READMEs.
_HUB_PATH_RE = re.compile(
    r"`((?:apps|packages|conf|docs)/[^`]+|\.gitlab-ci\.yml|docker-compose[a-z.]*\.yml"
    r"|README\.[a-z]+\.md|PUBG-WORKFLOW\.md|biome\.json|knip\.json)`"
)


def _deep_dive() -> str:
    return _section(_read_doc(), r"11\. Option A in depth")


def _sub(title_pattern: str) -> str:
    return _section(_deep_dive(), r"11\.\d+ " + title_pattern)


def _hub_paths(text: str) -> set[str]:
    return set(_HUB_PATH_RE.findall(text))


class TestOptionADeepDive:
    def test_deep_dive_section_listed_in_contents_and_linked(self):
        """The 'Option A in depth' section exists, is in the Contents, and is linked from
        the intro, the Summary and the Option A option."""
        doc = _read_doc()
        assert re.search(r"^## 11\. Option A in depth$", doc, re.MULTILINE)
        assert "(#11-option-a-in-depth)" in _section(doc, r"Contents")
        assert "(#11-option-a-in-depth)" in doc.split("## Contents")[0]
        assert "(#11-option-a-in-depth)" in _section(doc, r"Summary")
        assert "(#11-option-a-in-depth)" in _option(doc, "A")

    def test_deep_dive_has_required_parts(self):
        """The section covers: target architecture, data model mapping, background work,
        frontend, Twitch, testing, effort and phases, risks and gains, decision criteria,
        and whether the recommendation changes."""
        for title in ("Target architecture in the hub", "Data model mapping",
                      "Background work", "Frontend", "Twitch extension",
                      "Testing and quality gates", "Effort and phased migration",
                      "Risks and gains", "Decision criteria",
                      "Does the deep dive change the recommendation"):
            assert _sub(title).strip(), title

    def test_target_architecture_places_modules_routes_and_pages(self):
        """Target architecture: Kana Cards modules land in games/dota/, games/fantasy/dota/
        or hub core; the hub's CS2 fantasy structure and its event-driven scoring are
        described; routes split /api/v2/internal vs public /api/v2; frontend pages under
        seasons/[season]/fantasy with the registry capabilities."""
        arch = _sub(r"Target architecture in the hub")
        rows = _table_rows(arch)
        targets = " ".join(r[1] for r in rows[1:] if len(r) > 1)
        assert "`apps/backend/src/games/dota/services/`" in targets
        assert "`apps/backend/src/games/fantasy/dota/utils/`" in targets
        assert "Hub core" in targets
        for module in ("backend/ingest.py", "backend/enrich.py", "backend/card_points.py",
                       "backend/card_draw.py", "backend/weeks.py", "backend/twitch.py",
                       "backend/sessions.py"):
            assert f"`{module}`" in arch, module
        for part in ("controllers/", "models/", "routes/", "services/", "utils/"):
            assert f"`{part}`" in arch, part
        for path in ("apps/backend/src/games/fantasy/cs/services/fantasy-points.service.ts",
                     "apps/backend/src/games/fantasy/cs/models/fantasy-leaderboard.models.ts",
                     "apps/backend/src/games/cs/services/parsed-queue-consumer.ts",
                     "apps/backend/src/db/mysqlRunQuery.ts",
                     "apps/backend/src/routes/index.ts",
                     "apps/frontend/src/lib/games/registry.ts",
                     "apps/frontend/src/app/(main)/(content-container)/seasons/[season]/fantasy/"):
            assert f"`{path}`" in arch, path
        assert "`/api/v2/internal`" in arch and "`/api/v2`" in arch
        assert "event-driven" in arch
        assert "`caps.fantasy: true`" in arch

    def test_data_model_mapping_covers_tables_and_conventions(self):
        """Data model mapping: hub conventions (PascalCase tables, CHECK constraints and
        triggers, Steam ID keys, table comments), how the hub models matches (Matches vs
        MatchGames) and whether Dota fits, and a table mapping Kana Cards tables to existing
        hub tables or new Dota / FantasyDota tables."""
        mapping = _sub(r"Data model mapping")
        for term in ("PascalCase", "`CHECK`", "triggers", "`steam_id`", "table comment",
                     "`Matches`", "`MatchGames`", "`DotaMatchGames`"):
            assert term in mapping, term
        rows = _table_rows(mapping)
        header = rows[0]
        assert header[0].startswith("Kana Cards table")
        mapped = {re.sub(r"[`*]", "", r[0]).split(" ")[0].rstrip(","): r[1] for r in rows[1:]}
        for table in ("users", "players", "teams", "leagues", "matches", "player_match_stats",
                      "cards", "weeks", "card_match_points", "audit_logs"):
            assert table in mapped, table
        assert "`SteamPlayers`" in mapped["players"]
        assert "`SeasonLeagueExternalIds`" in mapped["leagues"]
        assert "`TeamGameParticipations`" in mapped["teams"]
        assert "`AuditLog`" in mapped["audit_logs"]
        assert "FantasyDota" in mapped["card_match_points"]
        for table in re.findall(r"^\| `([a-z_]+)`", mapping, re.MULTILINE):
            assert f'__tablename__ = "{table}"' in _models_source(), table

    def test_background_work_maps_all_four_threads(self):
        """Background work: Kana Cards' four threads (ingest poll with live-aware
        intervals, week maintenance, enrichment with Anthropic, backups) each get a hub
        equivalent (node-cron, BullMQ, the PUBG poller pattern, the backup container)."""
        bg = _sub(r"Background work")
        for thread in ("_ingest_poll_loop", "_week_maintenance_loop",
                       "_profile_enrichment_loop", "_backup_loop"):
            assert f"`{thread}`" in bg, thread
            with open(os.path.join(_REPO_ROOT, "backend", "main.py")) as f:
                assert f"def {thread}(" in f.read(), thread
        for term in ("`INGEST_LIVE_MATCH_POLL_INTERVAL`", "Anthropic", "`node-cron`", "BullMQ",
                     "`apps/backend/src/games/pubg/services/pubg-poller.services.ts`",
                     "`conf/mariadb/backup.sh`", "`apps/backend/server.ts`", "Grafana"):
            assert term in bg, term

    def test_frontend_section_covers_surfaces_to_rebuild(self):
        """Frontend: My Team with drag-and-drop, the draw reveal animation, card image
        rendering (server-side Pillow in backend/image.py vs what the hub offers, next/og),
        the guided tour and admin panels, each with a size."""
        fe = _sub(r"Frontend")
        for term in ("drag-and-drop", "reveal animation", "Pillow", "`backend/image.py`",
                     "`next/og`", "Guided tour", "Admin panels", "Next.js", "shadcn"):
            assert term in fe, term
        rows = _table_rows(fe)
        assert rows[0][-1] == "Size"
        assert all(r[-1] in {"S", "M", "L", "XL"} for r in rows[1:]), rows

    def test_twitch_section_covers_ebs_move(self):
        """Twitch: EBS on the hub backend (public /api/v2), JWT verification secrets, chat
        and PubSub calls, the URL fetching allowlist change with a new version and Twitch
        review, and a mitigation for review downtime."""
        tw = _sub(r"Twitch extension")
        for term in ("`TWITCH_EXTENSION_SECRET`", "`/api/v2`", "allowlist", "review",
                     "chat", "PubSub", "`twitch-extension/set-ebs-url.sh`", "reverse proxy"):
            assert term in tw, term
        assert os.path.isfile(os.path.join(_REPO_ROOT, "twitch-extension", "set-ebs-url.sh"))

    def test_testing_section_covers_port_vs_rewrite_and_hub_gates(self):
        """Testing: Kana Cards' pytest suite (port vs rewrite as Jest/Playwright, a golden
        parity suite) and the hub's quality gates (.gitlab-ci.yml, Biome, knip, the
        domain-boundaries test, coverage thresholds)."""
        testing = _sub(r"Testing and quality gates")
        for term in ("pytest", "Jest", "Playwright", "golden parity suite", "`.gitlab-ci.yml`",
                     "Biome", "`knip`", "`apps/backend/src/games/domain-boundaries.test.ts`",
                     "coverage thresholds"):
            assert term in testing, term
        for name in re.findall(r"`(test_[a-z0-9_]+\.py)`", testing):
            assert os.path.isfile(os.path.join(_REPO_ROOT, "backend", "tests", name)), name

    def test_effort_table_has_sizes_person_weeks_and_total(self):
        """Effort: a table per area with t-shirt size and a person-week range, a total row
        whose range equals the sum of the rows, stated assumptions (hobby developers,
        evenings) and the critical path."""
        effort = _sub(r"Effort and phased migration")
        assert "hobby developers" in effort and "evenings" in effort
        assert "**Critical path.**" in effort
        table = next(t for t in re.split(r"\n\s*\n", effort) if t.lstrip().startswith("| Area"))
        rows = _table_rows(table)
        assert rows[0][:3] == ["Area", "Size", "Person-weeks"]
        lows = highs = 0.0
        total = None
        for row in rows[1:]:
            size = row[1].strip("*")
            assert size in {"S", "M", "L", "XL"}, row
            m = re.match(r"\**(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)", row[2])
            assert m, row
            if row[0].strip("*") == "Total":
                total = (float(m.group(1)), float(m.group(2)))
            else:
                lows += float(m.group(1))
                highs += float(m.group(2))
        assert len(rows) >= 12
        assert total == (lows, highs), (total, lows, highs)

    def test_phased_plan_aligned_to_season_breaks(self):
        """Phased plan: phases 0 to 4 (Dota season in the hub, games/dota ingestion,
        fantasy core read-only, full fantasy and Twitch, retire Kana Cards), each tied to a
        season break, and the total number of season breaks stated."""
        effort = _sub(r"Effort and phased migration")
        table = next(t for t in re.split(r"\n\s*\n", effort) if t.lstrip().startswith("| Phase"))
        rows = _table_rows(table)
        assert rows[0][-1] == "Season break"
        phases = [r[0] for r in rows[1:]]
        assert [p.split(" ")[0] for p in phases] == ["0", "1", "2", "3", "4"]
        assert "read-only" in phases[2]
        assert "Twitch" in phases[3]
        assert "Retire Kana Cards" in phases[4]
        assert all(re.search(r"[Bb]reak \d", r[-1]) for r in rows[1:]), rows
        assert "**at least five season breaks**" in effort

    def test_risks_and_gains_cover_required_items(self):
        """Risks specific to A (feature parity, ownership/review, release cadence, MariaDB
        performance, data migration/claim, Twitch review downtime) each with a mitigation,
        and what A gains (one codebase/site/login, hub ops and Grafana, no login code,
        shared admin and permissions, Discord)."""
        rg = _sub(r"Risks and gains")
        rows = _table_rows(rg)
        assert rows[0] == ["Risk", "Why it matters", "Mitigation"]
        risks = " ".join(r[0] for r in rows[1:]).lower()
        for risk in ("feature parity", "scoring parity", "ownership", "release cadence",
                     "performance", "data migration", "twitch review"):
            assert risk in risks, risk
        assert all(len(r[2]) > 20 for r in rows[1:]), rows
        gains = rg.split("**What Option A gains:**")[1]
        for gain in ("One codebase, one site, one login", "Grafana", "No login code",
                     "Shared admin and permissions", "Discord"):
            assert gain in gains, gain

    def test_decision_criteria_listed(self):
        """Decision criteria: numbered conditions under which A becomes the right choice."""
        criteria = _sub(r"Decision criteria")
        items = re.findall(r"^(\d+)\. \*\*", criteria, re.MULTILINE)
        assert len(items) >= 4
        assert "the hub runs dota" in criteria.lower()

    def test_recommendation_reevaluated_and_unchanged(self):
        """The deep dive re-evaluates the recommendation: it is unchanged (Option C with
        Steam-only login), says why, and describes the staged path (C now, A later) with
        trigger conditions; the Recommendation section links to it."""
        doc = _read_doc()
        verdict = _sub(r"Does the deep dive change the recommendation")
        assert verdict.lstrip().startswith("**No.**")
        assert "Option C with Steam-only login (B1)" in verdict
        assert "**C now, A as a possible later target.**" in verdict
        assert "(#1110-decision-criteria)" in verdict
        rec = _section(doc, r"6\. Recommendation")
        assert "Choose Option C, switch Kana Cards to Steam-only login (Option B1)" in rec
        assert "(#1111-does-the-deep-dive-change-the-recommendation)" in rec
        assert "(#1110-decision-criteria)" in rec

    def test_side_by_side_and_summary_reflect_deep_dive(self):
        """The side-by-side table and the Summary carry the deep dive's numbers for A
        (person-weeks, season breaks)."""
        doc = _read_doc()
        side = _section(doc, r"Side by side")
        effort_row = next(r for r in _table_rows(side) if r[0] == "Total effort")
        assert "45–70 person-weeks" in effort_row[1]
        assert any(r[0] == "Season breaks to go live" for r in _table_rows(side))
        assert "45–70 person-weeks" in _section(doc, r"Summary")

    def test_deep_dive_hub_claims_cite_paths(self):
        """Every part of the deep dive that makes hub claims cites hub file paths, and every
        Kana Cards path it cites exists in this repository."""
        for title, minimum in (("Target architecture in the hub", 15),
                               ("Data model mapping", 8),
                               ("Background work", 5),
                               ("Frontend", 3),
                               ("Twitch extension", 3),
                               ("Testing and quality gates", 5),
                               ("Risks and gains", 3)):
            assert len(_hub_paths(_sub(title))) >= minimum, title
        deep = _deep_dive()
        for path in re.findall(r"`((?:backend|frontend|twitch-extension|markdown)/[^`*]+)`", deep):
            assert os.path.exists(os.path.join(_REPO_ROOT, path)), path
        assert "`9e49c668c1a698a55974b3d0dec7af05480a2287`" in deep


def _models_source() -> str:
    with open(os.path.join(_REPO_ROOT, "backend", "models.py")) as f:
        return f.read()
